from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import WorkbenchError
from .util import canonical_bytes, deep_remove, sha256_bytes, tree_digest


def _load(value: dict[str, Any] | Path) -> tuple[dict[str, Any], str, str]:
    if isinstance(value, Path):
        before = tree_digest(value)
        if value.is_dir():
            candidate = value / "result.json"
            if not candidate.is_file():
                raise WorkbenchError(
                    "evidence_incomplete",
                    "evidence directory has no result.json",
                    {"path": str(value)},
                )
        else:
            candidate = value
        data = json.loads(candidate.read_text(encoding="utf-8"))
        after = tree_digest(value)
        return data, before, after
    digest = sha256_bytes(canonical_bytes(value))
    return json.loads(json.dumps(value)), digest, digest


def _semantic_projection(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "steps": [
            {
                "step_id": step.get("step_id"),
                "method": step.get("method"),
                "status": step.get("status"),
                "error_code": (step.get("error") or {}).get("code"),
                "verified": (step.get("receipt") or {}).get("verified"),
            }
            for step in result.get("steps", [])
        ],
        "gates": [
            {"kind": gate.get("kind"), "status": gate.get("status"), "required": gate.get("required")}
            for gate in result.get("gates", [])
        ],
        "terminal_code": (result.get("terminal_reason") or {}).get("code"),
    }


def _diff(left: Any, right: Any, path: str = "$") -> list[dict[str, Any]]:
    if type(left) is not type(right):
        return [{"path": path, "baseline": left, "candidate": right, "kind": "type"}]
    if isinstance(left, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append(
                    {"path": f"{path}.{key}", "baseline": left.get(key), "candidate": right.get(key), "kind": "presence"}
                )
            else:
                differences.extend(_diff(left[key], right[key], f"{path}.{key}"))
        return differences
    if isinstance(left, list):
        differences = []
        if len(left) != len(right):
            differences.append({"path": path, "baseline": len(left), "candidate": len(right), "kind": "length"})
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            differences.extend(_diff(left_item, right_item, f"{path}[{index}]"))
        return differences
    if left != right:
        return [{"path": path, "baseline": left, "candidate": right, "kind": "value"}]
    return []


def compare_runs(
    baseline: dict[str, Any] | Path,
    candidate: dict[str, Any] | Path,
    tolerances: dict[str, Any] | None = None,
    *,
    expected_baseline_digest: str | None = None,
    expected_candidate_digest: str | None = None,
) -> dict[str, Any]:
    tolerances = tolerances or {}
    baseline_data, baseline_before, baseline_after = _load(baseline)
    candidate_data, candidate_before, candidate_after = _load(candidate)

    if expected_baseline_digest and expected_baseline_digest != baseline_before:
        raise WorkbenchError(
            "integrity_mismatch",
            "baseline digest does not match the declared input",
            {"expected": expected_baseline_digest, "observed": baseline_before},
        )
    if expected_candidate_digest and expected_candidate_digest != candidate_before:
        raise WorkbenchError(
            "candidate_mutated",
            "candidate differs from the declared comparison input",
            {"expected": expected_candidate_digest, "observed": candidate_before},
        )
    if baseline_before != baseline_after:
        raise WorkbenchError("integrity_mismatch", "baseline changed during comparison")
    if candidate_before != candidate_after:
        raise WorkbenchError("candidate_mutated", "candidate changed during comparison")

    ignore_fields = tolerances.get("ignore_fields", [])
    baseline_semantic = deep_remove(_semantic_projection(baseline_data), ignore_fields)
    candidate_semantic = deep_remove(_semantic_projection(candidate_data), ignore_fields)
    if tolerances.get("step_order") == "by_step_id":
        baseline_semantic["steps"] = sorted(
            baseline_semantic["steps"], key=lambda step: str(step.get("step_id"))
        )
        candidate_semantic["steps"] = sorted(
            candidate_semantic["steps"], key=lambda step: str(step.get("step_id"))
        )
    differences = _diff(baseline_semantic, candidate_semantic)

    left_capabilities = baseline_data.get("capabilities", {}).get("capabilities", {})
    right_capabilities = candidate_data.get("capabilities", {}).get("capabilities", {})
    capability_differences = _diff(left_capabilities, right_capabilities, "$.capabilities")
    if capability_differences and not tolerances.get("allow_capability_differences", False):
        differences.extend(capability_differences)

    return {
        "schema_version": "browser-workbench.comparison/v1",
        "status": "equivalent" if not differences else "different",
        "baseline": {"digest": baseline_before},
        "candidate": {"digest": candidate_before},
        "tolerances": tolerances,
        "differences": differences,
        "capability_differences": capability_differences,
        "input_integrity": {
            "baseline_before": baseline_before,
            "baseline_after": baseline_after,
            "candidate_before": candidate_before,
            "candidate_after": candidate_after,
            "unchanged": baseline_before == baseline_after and candidate_before == candidate_after,
        },
    }
