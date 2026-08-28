from __future__ import annotations

import copy
import json
import platform
from pathlib import Path
from typing import Any

from .capabilities import RuntimeLedger, capability_report, require_capabilities, with_runtime_verification
from .compare import compare_runs
from .errors import WorkbenchError
from .evidence import ArtifactStore
from .mock_backend import MockBackend
from .models import terminal_status, validate_run_spec
from .native_probe import probe_backend
from .webkitgtk_backend import WebKitGtkBackend
from .util import json_size


def _lookup_path(value: Any, path: str) -> Any:
    current = value
    if path:
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                raise WorkbenchError(
                    "invalid_request", "workflow reference does not resolve", {"path": path}
                )
    return copy.deepcopy(current)


def _resolve(value: Any, outputs: dict[str, Any]) -> Any:
    if isinstance(value, dict) and set(value) <= {"$step", "path"} and "$step" in value:
        step_id = value["$step"]
        if step_id not in outputs:
            raise WorkbenchError(
                "invalid_request", "workflow references an unavailable step", {"step_id": step_id}
            )
        return _lookup_path(outputs[step_id], str(value.get("path", "")))
    if isinstance(value, dict):
        return {key: _resolve(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, outputs) for item in value]
    return value


def _expect(result: Any, expectation: dict[str, Any]) -> None:
    if not expectation:
        return
    if "path" in expectation:
        observed = _lookup_path(result, str(expectation["path"]))
    else:
        observed = result
    if "equals" in expectation and observed != expectation["equals"]:
        raise WorkbenchError(
            "precondition_failed",
            "step expectation did not match",
            {"expected": expectation["equals"], "observed": observed},
        )
    if expectation.get("truthy") and not observed:
        raise WorkbenchError("precondition_failed", "step expectation was not truthy")


class Runner:
    """Executes a declared run spec once. It never plans, retries, or changes intent."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def run(self, spec: dict[str, Any]) -> dict[str, Any]:
        run_id = str(spec.get("run_id", "invalid-run"))
        store = ArtifactStore(self.output_root / run_id, run_id)
        steps: list[dict[str, Any]] = []
        gates: list[dict[str, Any]] = []
        deviations: list[dict[str, Any]] = []
        terminal_error: WorkbenchError | None = None
        capability: dict[str, Any] = {}
        backend: MockBackend | WebKitGtkBackend | None = None
        ledger = RuntimeLedger()

        store.write_json("contract/run-spec.json", spec, "contract")
        try:
            validate_run_spec(spec)
            kind = spec["backend"]["kind"]
            variant = spec["backend"]["variant"]
            probe = probe_backend(kind)
            capability = capability_report(kind, variant, probe=probe)
            store.write_json("diagnostics/capabilities.json", capability, "diagnostic")
            require_capabilities(
                capability,
                spec["required_capabilities"],
                spec.get("allowed_providers"),
            )
            if kind == "mock":
                backend = MockBackend(store, variant=variant)
            elif kind == "webkitgtk":
                # The block lifts only for a probed host with an adapter that
                # actually connects. connect() raises rather than degrading.
                if not probe["ready"]:
                    raise WorkbenchError(
                        "capability_blocked",
                        "the WebKitGTK prerequisites are not satisfied on this host",
                        {"backend": kind, "reasons": probe["reasons"]},
                    )
                native = WebKitGtkBackend(store, variant=variant)
                identity = native.connect()
                store.write_json("diagnostics/adapter-identity.json", identity, "diagnostic")
                backend = native
            else:
                raise WorkbenchError(
                    "capability_blocked",
                    "this checkpoint has no connected adapter process for this backend",
                    {
                        "backend": kind,
                        "probe_ready": probe["ready"],
                        "source_boundary": f"native/{kind}-worker" if kind != "playwright" else "oracle/playwright",
                    },
                )
        except WorkbenchError as error:
            terminal_error = error

        outputs: dict[str, Any] = {}
        for declaration in spec.get("workflow", []):
            step_record = {
                "step_id": declaration.get("step_id", "unknown"),
                "method": declaration.get("method", "unknown"),
                "status": "skipped" if terminal_error else "passed",
                "result": None,
                "error": None,
                "receipt": None,
            }
            if terminal_error is None:
                try:
                    params = _resolve(declaration["params"], outputs)
                    if declaration["method"] == "run.compare":
                        result = compare_runs(
                            Path(params["baseline"]),
                            Path(params["candidate"]),
                            params.get("tolerances"),
                            expected_baseline_digest=params.get("expected_baseline_digest"),
                            expected_candidate_digest=params.get("expected_candidate_digest"),
                        )
                    else:
                        assert backend is not None
                        result = backend.dispatch(declaration["method"], params)
                    _expect(result, declaration.get("expect", {}))
                    step_record["result"] = result
                    if isinstance(result, dict) and "receipt_id" in result:
                        step_record["receipt"] = result
                    outputs[declaration["step_id"]] = result
                    step_record["exercised"] = ledger.record(declaration["method"], params)
                except WorkbenchError as error:
                    terminal_error = error
                    step_record["status"] = error.status
                    step_record["error"] = error.as_dict()
                except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
                    terminal_error = WorkbenchError(
                        "invalid_request", "step parameters could not be executed", {"detail": str(error)}
                    )
                    step_record["status"] = terminal_error.status
                    step_record["error"] = terminal_error.as_dict()
            steps.append(step_record)

        if backend is not None:
            # Teardown before the trace flush so the adapter's own closing
            # record is part of the evidence rather than lost after it.
            close = getattr(backend, "close", None)
            if close is not None:
                try:
                    close()
                except WorkbenchError as error:
                    deviations.append({"kind": "adapter-teardown-error", "error": error.as_dict()})
            deviations.extend(getattr(backend, "deviations", []))
            backend.flush_traces()

        status = terminal_status(terminal_error)
        if capability:
            # The pre-run report stays as written: it is what the run was
            # admitted on. The post-run report carries what was then earned.
            capability = with_runtime_verification(capability, ledger)
            store.write_json("diagnostics/capabilities-runtime.json", capability, "diagnostic")
        for gate in spec.get("gates", []):
            kind = gate["kind"]
            if kind == "native":
                passed = spec.get("backend", {}).get("kind") == "mock" or bool(
                    capability.get("identity", {}).get("probe", {}).get("ready")
                )
            elif kind == "capability":
                passed = terminal_error is None or terminal_error.code not in {
                    "capability_blocked",
                    "capability_unsupported",
                }
            elif kind == "evidence":
                passed = bool(store.artifacts)
            else:
                passed = status == "passed"
            gate_status = "passed" if passed else ("blocked" if status == "blocked" else "failed")
            gates.append(
                {
                    "id": gate["id"],
                    "kind": kind,
                    "status": gate_status,
                    "required": gate["required"],
                    "details": {"run_status": status},
                }
            )

        if status == "passed":
            failed_required = [g for g in gates if g["required"] and g["status"] != "passed"]
            if failed_required:
                terminal_error = WorkbenchError(
                    "evidence_incomplete", "one or more required gates did not pass"
                )
                status = terminal_error.status

        maximum = int(spec.get("evidence", {}).get("max_artifact_bytes", 1024 * 1024))
        oversized = [a for a in store.artifacts if a["size_bytes"] > maximum]
        if oversized and status == "passed":
            terminal_error = WorkbenchError(
                "evidence_incomplete",
                "an evidence artifact exceeds the declared bound",
                {"paths": [item["path"] for item in oversized]},
            )
            status = terminal_error.status

        result = {
            "schema_version": "browser-workbench.result/v1",
            "run_id": run_id,
            "status": status,
            "backend": spec.get("backend", {}),
            "capabilities": capability,
            "runtime_verification": ledger.as_dict(),
            "steps": steps,
            "gates": gates,
            "artifacts": sorted(store.artifacts, key=lambda item: item["path"]),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "runner": "browser-workbench/0.2.0",
                "retry_count": 0,
            },
            "deviations": deviations,
            "terminal_reason": terminal_error.as_dict() if terminal_error else {"code": "completed"},
        }
        if json_size(result) > maximum:
            result["capabilities"] = {
                "schema_version": capability.get("schema_version"),
                "backend": capability.get("backend"),
                "variant": capability.get("variant"),
                "capabilities": {
                    key: value
                    for key, value in capability.get("capabilities", {}).items()
                    if key in spec.get("required_capabilities", [])
                },
            }
            result["deviations"].append(
                {"kind": "bounded-result", "reason": "capability report moved to diagnostic artifact"}
            )
        store.write_json("result.json", result, "contract")
        store.finalize(complete=status == "passed")
        return result


def run_spec_file(path: Path, output_root: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    return Runner(output_root).run(spec)
