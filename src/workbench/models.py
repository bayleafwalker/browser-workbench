from __future__ import annotations

from typing import Any

from .errors import WorkbenchError


METHODS = {
    "session.create",
    "page.navigate",
    "page.observe",
    "page.act",
    "page.await",
    "session.checkpoint",
    "session.export",
    "run.compare",
}


def validate_run_spec(spec: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "run_id",
        "backend",
        "required_capabilities",
        "workflow",
        "gates",
        "evidence",
    }
    missing = sorted(required - spec.keys())
    if missing:
        raise WorkbenchError("invalid_request", "run spec is incomplete", {"missing": missing})
    if spec["schema_version"] != "browser-workbench.run/v1":
        raise WorkbenchError(
            "protocol_mismatch",
            "unsupported run spec version",
            {"observed": spec["schema_version"], "supported": ["browser-workbench.run/v1"]},
        )
    if not isinstance(spec["run_id"], str) or not spec["run_id"]:
        raise WorkbenchError("invalid_request", "run_id must be a non-empty string")
    backend = spec["backend"]
    if not isinstance(backend, dict) or backend.get("kind") not in {
        "mock",
        "webkitgtk",
        "playwright",
        "servo-gtk",
    }:
        raise WorkbenchError("invalid_request", "backend kind is invalid")
    if not isinstance(backend.get("variant"), str) or not backend["variant"]:
        raise WorkbenchError("invalid_request", "backend variant must be declared")
    if not isinstance(spec["required_capabilities"], list):
        raise WorkbenchError("invalid_request", "required_capabilities must be a list")
    if len(spec["required_capabilities"]) != len(set(spec["required_capabilities"])):
        raise WorkbenchError("invalid_request", "required_capabilities contains duplicates")
    if not isinstance(spec["workflow"], list) or not spec["workflow"]:
        raise WorkbenchError("invalid_request", "workflow must contain at least one step")

    step_ids: set[str] = set()
    for index, step in enumerate(spec["workflow"]):
        if not isinstance(step, dict):
            raise WorkbenchError("invalid_request", "workflow step must be an object", {"index": index})
        step_id = step.get("step_id")
        if not isinstance(step_id, str) or not step_id:
            raise WorkbenchError("invalid_request", "workflow step_id is invalid", {"index": index})
        if step_id in step_ids:
            raise WorkbenchError("invalid_request", "workflow step_id is duplicated", {"step_id": step_id})
        step_ids.add(step_id)
        if step.get("method") not in METHODS:
            raise WorkbenchError(
                "invalid_request",
                "workflow contains an unknown method",
                {"step_id": step_id, "method": step.get("method")},
            )
        if not isinstance(step.get("params"), dict):
            raise WorkbenchError("invalid_request", "workflow params must be an object", {"step_id": step_id})
        deadline = step.get("deadline_ms", 30000)
        if not isinstance(deadline, int) or deadline < 1 or deadline > 300000:
            raise WorkbenchError("invalid_request", "step deadline is outside bounds", {"step_id": step_id})

    evidence = spec["evidence"]
    if not isinstance(evidence, dict) or not {"raw", "normalized", "max_artifact_bytes"} <= evidence.keys():
        raise WorkbenchError("invalid_request", "evidence policy is incomplete")
    maximum = evidence["max_artifact_bytes"]
    if not isinstance(maximum, int) or not 1024 <= maximum <= 1024 * 1024 * 1024:
        raise WorkbenchError("invalid_request", "max_artifact_bytes is outside bounds")


def terminal_status(error: WorkbenchError | None) -> str:
    return "passed" if error is None else error.status
