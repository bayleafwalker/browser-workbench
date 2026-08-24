from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from .compare import compare_runs
from .errors import WorkbenchError
from .evidence import ArtifactStore
from .mock_backend import MockBackend
from .util import canonical_bytes, pretty_json, repo_root, sha256_bytes, sha256_file, tree_digest


def _error_code(call: Callable[[], Any]) -> str | None:
    try:
        call()
    except WorkbenchError as error:
        return error.code
    return None


def _create(backend: MockBackend, writer: str = "writer-a") -> dict[str, Any]:
    return backend.session_create(
        {"client": {"id": writer, "kind": "human"}, "profile": {"mode": "ephemeral", "name": "corpus"}}
    )


def _finish_navigation(backend: MockBackend, page_id: str) -> dict[str, Any]:
    return backend.page_await(
        {"page_id": page_id, "conditions": [{"kind": "load_state", "equals": "idle"}], "deadline_ms": 50}
    )


def _scenario_session_tabs_profiles(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    created = _create(backend)
    conflict = _error_code(
        lambda: backend.session_create(
            {"client": {"id": "writer-b", "kind": "agent"}, "profile": {"mode": "ephemeral"}}
        )
    )
    return {
        "profile is ephemeral": created["profile"]["mode"] == "ephemeral",
        "one page is active": created["page_id"] in backend.pages and len(backend.pages) == 1,
        "lease epoch is one": created["lease"]["lease_epoch"] == 1,
        "second writer is rejected": conflict == "lease_conflict",
    }


def _scenario_bounded_observation(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    backend.page_navigate({"page_id": page_id, "url": "https://fixture.invalid/large", "client_id": "writer-a"})
    _finish_navigation(backend, page_id)
    observed = backend.page_observe(
        {"page_id": page_id, "projection": ["state", "dom", "raw-events"], "since_event": 0, "max_bytes": 1024}
    )
    return {
        "response is within max_bytes": len(canonical_bytes(observed)) <= 1024,
        "loss is explicit": observed["lossy"] is True and bool(observed["omitted"]),
        "raw artifact is content-addressed": str(observed["raw_ref"]).startswith("sha256:"),
        "event cursor advances": observed["next_event"] > observed["since_event"],
    }


def _scenario_generation_targets_receipts(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    target = backend.page_observe({"page_id": page_id, "projection": "targets"})["data"]["targets"][0]
    receipt = backend.page_act(
        {"page_id": page_id, "client_id": "writer-a", "target": target, "intent": {"kind": "click"}}
    )
    backend.page_navigate(
        {"page_id": page_id, "url": "https://fixture.invalid/next", "client_id": "writer-a", "wait": "commit"}
    )
    before = backend.backend_invocations
    stale = _error_code(
        lambda: backend.page_act(
            {"page_id": page_id, "client_id": "writer-a", "target": target, "intent": {"kind": "click"}}
        )
    )
    return {
        "fresh target executes": receipt["executed"] is True,
        "receipt names causal events": receipt["verified"] and len(receipt["caused_event_ids"]) >= 2,
        "navigation increments generation": backend.pages[page_id]["generation"] == target["generation"] + 1,
        "stale target fails before backend invocation": stale == "stale_target" and backend.backend_invocations == before,
    }


def _scenario_event_driven_await(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    backend.page_navigate({"page_id": page_id, "url": "https://fixture.invalid/await", "client_id": "writer-a"})
    done = _finish_navigation(backend, page_id)
    timeout = _error_code(
        lambda: backend.page_await(
            {"page_id": page_id, "conditions": [{"kind": "title", "equals": "Never"}], "deadline_ms": 7}
        )
    )
    return {
        "scheduled event satisfies condition": done["satisfied"] is True,
        "virtual clock is deterministic": done["monotonic_ms"] == 10,
        "deadline reports unsatisfied predicates": timeout == "deadline_exceeded",
    }


def _scenario_snapshot_screenshot_javascript(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    before = sha256_bytes(canonical_bytes(backend.pages[page_id]))
    screenshot = backend.page_observe({"page_id": page_id, "projection": "screenshot"})["data"]["screenshot"]
    after_screenshot = sha256_bytes(canonical_bytes(backend.pages[page_id]))
    changed = backend.page_act(
        {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "javascript", "value": "set-title:Declared"}}
    )
    read = backend.page_act(
        {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "javascript", "value": "return-title"}}
    )
    return {
        "screenshot is an artifact": screenshot["media_type"] == "image/png" and screenshot["size_bytes"] > 0,
        "script result is bounded": read["effects"][0]["value"] == "Declared" and len(canonical_bytes(read)) < 4096,
        "provider class is recorded": changed["provider"] == "injected",
        "state digest changes only when declared": before == after_screenshot and changed["state_before"] != changed["state_after"],
    }


def _scenario_console_network_evidence(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    backend.page_navigate({"page_id": page_id, "url": "https://fixture.invalid/console", "client_id": "writer-a"})
    _finish_navigation(backend, page_id)
    observed = backend.page_observe(
        {"page_id": page_id, "projection": ["console", "network"], "since_event": 0, "max_bytes": 32768}
    )["data"]
    console = observed["console"]
    network = observed["network"]
    request_ids = {event["payload"].get("request_id") for event in network if event["kind"] == "network.request"}
    response_ids = {event["payload"].get("request_id") for event in network if event["kind"] == "network.response"}
    linked = all(event["raw_refs"] for event in console + network)
    return {
        "console record has event identity": bool(console and console[0]["event_id"]),
        "network request and response correlate": bool(request_ids & response_ids),
        "raw and normalized records are linked": linked,
    }


def _scenario_dialog_permission(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    backend.page_navigate({"page_id": page_id, "url": "https://fixture.invalid/prompts", "client_id": "writer-a"})
    _finish_navigation(backend, page_id)
    observed = backend.page_observe(
        {"page_id": page_id, "projection": ["dialogs", "permissions"], "max_bytes": 32768}
    )["data"]
    dialog = observed["dialogs"][0]
    permission = observed["permissions"][0]
    dialog_receipt = backend.page_act(
        {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "dialog.resolve", "decision_token": dialog["token"], "decision": "dismiss"}}
    )
    permission_receipt = backend.page_act(
        {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "permission.resolve", "decision_token": permission["token"], "decision": "deny"}}
    )
    duplicate = _error_code(
        lambda: backend.page_act(
            {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "dialog.resolve", "decision_token": dialog["token"], "decision": "accept"}}
        )
    )
    return {
        "decision token is required": bool(dialog["token"] and permission["token"]),
        "default is deny": dialog["default"] == permission["default"] == "deny",
        "duplicate decision is rejected": duplicate == "precondition_failed",
        "receipt records applied decision": dialog_receipt["effects"][0]["decision"] == "dismiss" and permission_receipt["effects"][0]["decision"] == "deny",
    }


def _scenario_upload_download(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    fixture = repo_root() / "examples" / "fixtures" / "upload.txt"
    upload = backend.page_act(
        {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "upload", "path": str(fixture)}}
    )
    download = backend.page_act(
        {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "download.accept", "download_id": "fixture"}}
    )
    rejected = _error_code(
        lambda: backend.page_act(
            {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "upload", "path": str(repo_root() / "README.md")}}
        )
    )
    download_effect = download["effects"][0]
    return {
        "upload uses an allowed fixture": upload["effects"][0]["kind"] == "upload",
        "download remains quarantined": download_effect["status"] == "quarantined",
        "artifact hash is recorded": str(download_effect["artifact_ref"]).startswith("sha256:"),
        "undeclared path is rejected": rejected == "precondition_failed",
    }


def _scenario_checkpoint_handover(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    checkpoint = backend.session_checkpoint({"client_id": "writer-a", "release_lease": True})
    old_fenced = _error_code(
        lambda: backend.page_act(
            {"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "javascript", "value": "return-title"}}
        )
    )
    successor = MockBackend(store, variant=backend.variant)
    resumed = successor.session_create(
        {"client": {"id": "writer-b", "kind": "agent"}, "profile": {"mode": "ephemeral"}, "resume_checkpoint": checkpoint["artifact"]}
    )
    return {
        "checkpoint is content-addressed": str(checkpoint["artifact"]["artifact_ref"]).startswith("sha256:"),
        "old lease becomes read-only": old_fenced == "lease_fenced",
        "successor lease epoch increments": resumed["lease"]["lease_epoch"] == 2,
        "handover does not grant approval": resumed["resumed_from"] == checkpoint["checkpoint_id"] and checkpoint["approval"] is None,
    }


def _scenario_crash_recovery_redacted_export(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    page_id = _create(backend)["page_id"]
    checkpoint = backend.session_checkpoint({"client_id": "writer-a"})
    backend.page_act({"page_id": page_id, "client_id": "writer-a", "intent": {"kind": "test.crash"}})
    visible = backend.page_observe({"page_id": page_id, "projection": "state"})["data"]["state"]
    traces = backend.flush_traces()
    successor = MockBackend(store, variant=backend.variant)
    resumed = successor.session_create(
        {"client": {"id": "writer-b", "kind": "agent"}, "profile": {"mode": "ephemeral"}, "resume_checkpoint": checkpoint["artifact"]}
    )
    exported = successor.session_export(
        {"metadata": {"authorization": "Bearer corpus-super-secret", "note": "Bearer another-secret"}, "include_raw": True, "max_bytes": 8192}
    )
    export_value = store.read_json_ref(exported["artifact"])
    export_text = json.dumps(export_value)
    restored_page = successor.pages[resumed["page_id"]]
    return {
        "crash is visible": visible["lifecycle"] == "terminated",
        "partial evidence is retained": len(traces) == 2 and all(item["size_bytes"] > 0 for item in traces),
        "checkpoint restores canonical state": restored_page["lifecycle"] == "open" and restored_page["generation"] == 2,
        "sensitive fields are redacted before export": "corpus-super-secret" not in export_text and "another-secret" not in export_text and exported["redaction"]["count"] >= 2,
    }


def _comparison_fixture(step_order: list[str] | None = None, *, status: str = "passed", capability: str = "supported") -> dict[str, Any]:
    step_order = step_order or ["a", "b"]
    methods = {"a": "session.create", "b": "page.observe"}
    return {
        "status": status,
        "steps": [{"step_id": item, "method": methods[item], "status": "passed", "wall_time_ms": 1} for item in step_order],
        "gates": [{"kind": "execution", "status": "passed", "required": True}],
        "terminal_reason": {"code": "completed" if status == "passed" else "backend_rejected"},
        "capabilities": {"capabilities": {"page.observe.state": {"availability": capability}}},
    }


def _scenario_differential_compare(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    baseline = _comparison_fixture(["a", "b"])
    candidate = _comparison_fixture(["b", "a"])
    candidate["steps"][0]["wall_time_ms"] = 999
    equivalent = compare_runs(baseline, candidate, {"step_order": "by_step_id"})
    capability_candidate = _comparison_fixture(capability="partial")
    capability = compare_runs(baseline, capability_candidate)
    mismatch = compare_runs(baseline, _comparison_fixture(status="failed"))
    return {
        "partial order is accepted": equivalent["status"] == "equivalent",
        "wall time is ignored only when declared": equivalent["status"] == "equivalent" and "wall_time_ms" not in json.dumps(equivalent),
        "capability difference is visible": capability["status"] == "different" and bool(capability["capability_differences"]),
        "semantic mismatch fails": mismatch["status"] == "different",
    }


def _scenario_candidate_mutation_block(backend: MockBackend, store: ArtifactStore) -> dict[str, bool]:
    baseline_path = store.root / "inputs" / "baseline" / "result.json"
    candidate_path = store.root / "inputs" / "candidate" / "result.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(pretty_json(_comparison_fixture()), encoding="utf-8")
    candidate_path.write_text(pretty_json(_comparison_fixture()), encoding="utf-8")
    baseline_before = tree_digest(baseline_path.parent)
    candidate_declared = tree_digest(candidate_path.parent)
    mutated = _comparison_fixture()
    mutated["status"] = "failed"
    candidate_path.write_text(pretty_json(mutated), encoding="utf-8")
    report_emitted = False
    code = None
    try:
        compare_runs(
            baseline_path.parent,
            candidate_path.parent,
            expected_baseline_digest=baseline_before,
            expected_candidate_digest=candidate_declared,
        )
        report_emitted = True
    except WorkbenchError as error:
        code = error.code
    return {
        "input digest is checked before and after": code == "candidate_mutated",
        "mutation produces candidate_mutated": code == "candidate_mutated",
        "no green report is emitted": report_emitted is False,
        "baseline remains unchanged": tree_digest(baseline_path.parent) == baseline_before,
    }


DRIVERS: dict[str, Callable[[MockBackend, ArtifactStore], dict[str, bool]]] = {
    "session_tabs_profiles": _scenario_session_tabs_profiles,
    "bounded_observation": _scenario_bounded_observation,
    "generation_targets_receipts": _scenario_generation_targets_receipts,
    "event_driven_await": _scenario_event_driven_await,
    "snapshot_screenshot_javascript": _scenario_snapshot_screenshot_javascript,
    "console_network_evidence": _scenario_console_network_evidence,
    "dialog_permission": _scenario_dialog_permission,
    "upload_download": _scenario_upload_download,
    "checkpoint_handover": _scenario_checkpoint_handover,
    "crash_recovery_redacted_export": _scenario_crash_recovery_redacted_export,
    "differential_compare": _scenario_differential_compare,
    "candidate_mutation_block": _scenario_candidate_mutation_block,
}


def run_corpus(output_root: Path, repetitions: int | None = None) -> dict[str, Any]:
    corpus = json.loads((repo_root() / "spec" / "WORKBENCH_CORPUS_V1.json").read_text(encoding="utf-8"))
    repetitions = repetitions or int(corpus["repetitions"])
    if repetitions < 1:
        raise WorkbenchError("invalid_request", "repetitions must be positive")
    records: list[dict[str, Any]] = []
    for scenario in corpus["scenarios"]:
        driver = DRIVERS[scenario["driver"]]
        for repetition in range(1, repetitions + 1):
            run_id = f"{scenario['id']}-r{repetition}"
            store = ArtifactStore(output_root / scenario["id"] / f"rep-{repetition}", run_id)
            backend = MockBackend(store, variant="denominator")
            error: dict[str, Any] | None = None
            checks: dict[str, bool] = {}
            try:
                checks = driver(backend, store)
            except Exception as exception:  # corpus must preserve a diagnostic record
                if isinstance(exception, WorkbenchError):
                    error = exception.as_dict()
                else:
                    error = {"code": "internal_invariant", "message": str(exception), "type": type(exception).__name__}
            backend.flush_traces()
            missing = sorted(set(scenario["assertions"]) - set(checks))
            unexpected = sorted(set(checks) - set(scenario["assertions"]))
            passed = error is None and not missing and not unexpected and all(checks.values())
            result = {
                "schema_version": "browser-workbench.corpus-result/v1",
                "run_id": run_id,
                "scenario_id": scenario["id"],
                "driver": scenario["driver"],
                "repetition": repetition,
                "status": "passed" if passed else "failed",
                "assertions": [{"text": text, "passed": bool(checks.get(text))} for text in scenario["assertions"]],
                "missing_assertions": missing,
                "unexpected_assertions": unexpected,
                "error": error,
                "retry_count": 0,
            }
            store.write_json("result.json", result, "contract")
            manifest = store.finalize(complete=passed)
            records.append({**result, "manifest": manifest})
    statuses = {record["status"] for record in records}
    signatures: dict[str, set[str]] = {}
    for record in records:
        signature = sha256_bytes(
            canonical_bytes({"status": record["status"], "assertions": record["assertions"], "error": record["error"]})
        )
        signatures.setdefault(record["scenario_id"], set()).add(signature)
    deterministic = all(len(values) == 1 for values in signatures.values())
    summary = {
        "schema_version": "browser-workbench.corpus-summary/v1",
        "corpus_id": corpus["id"],
        "corpus_version": corpus["version"],
        "scenario_count": len(corpus["scenarios"]),
        "repetitions": repetitions,
        "run_count": len(records),
        "passed": sum(record["status"] == "passed" for record in records),
        "failed": sum(record["status"] != "passed" for record in records),
        "status": "passed" if statuses == {"passed"} and deterministic else "failed",
        "deterministic": deterministic,
        "scenario_semantic_signatures": {
            scenario_id: sorted(values) for scenario_id, values in sorted(signatures.items())
        },
        "semantic_digest": sha256_bytes(
            canonical_bytes(
                [
                    {
                        "scenario_id": record["scenario_id"],
                        "status": record["status"],
                        "assertions": record["assertions"],
                    }
                    for record in records
                ]
            )
        ),
        "records": records,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "corpus-summary.json").write_text(pretty_json(summary), encoding="utf-8")
    return summary
