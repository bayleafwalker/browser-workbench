"""Differential comparison of two corpus runs of the same frozen denominator.

Matching semantic digests say that every assertion resolved the same way.
They do not say *how* each lane got there, and they hide which assertions a
backend reaches by declared, different means. This report makes both
visible: outcome agreement per assertion, the declared semantic divergences
each lane carries, and the structural differences (errors, deviations,
runtime-verified capabilities) that a digest never covers.
"""
from __future__ import annotations

from typing import Any

from .errors import WorkbenchError


def _outcomes(summary: dict[str, Any]) -> dict[str, dict[str, set[bool]]]:
    """scenario_id -> assertion text -> set of observed outcomes across repetitions."""
    outcomes: dict[str, dict[str, set[bool]]] = {}
    for record in summary.get("records", []):
        per_scenario = outcomes.setdefault(record["scenario_id"], {})
        for item in record.get("assertions", []):
            per_scenario.setdefault(item["text"], set()).add(bool(item["passed"]))
    return outcomes


def _lane(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend": summary.get("backend"),
        "status": summary.get("status"),
        "deterministic": summary.get("deterministic"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "run_count": summary.get("run_count"),
        "semantic_digest": summary.get("semantic_digest"),
    }


def compare_corpora(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare two corpus summaries scenario by scenario, assertion by assertion."""
    for field in ("corpus_id", "corpus_version"):
        if baseline.get(field) != candidate.get(field):
            raise WorkbenchError(
                "invalid_request",
                f"corpora differ in {field}; they are not the same denominator",
                {"baseline": baseline.get(field), "candidate": candidate.get(field)},
            )

    base_outcomes = _outcomes(baseline)
    cand_outcomes = _outcomes(candidate)
    base_semantics = baseline.get("assertion_semantics") or {}
    cand_semantics = candidate.get("assertion_semantics") or {}
    base_records = {r["scenario_id"]: [] for r in baseline.get("records", [])}
    cand_records = {r["scenario_id"]: [] for r in candidate.get("records", [])}
    for record in baseline.get("records", []):
        base_records[record["scenario_id"]].append(record)
    for record in candidate.get("records", []):
        cand_records[record["scenario_id"]].append(record)

    scenarios: list[dict[str, Any]] = []
    differences: list[dict[str, Any]] = []
    declared: list[dict[str, Any]] = []
    for scenario_id in sorted(set(base_outcomes) | set(cand_outcomes)):
        left = base_outcomes.get(scenario_id)
        right = cand_outcomes.get(scenario_id)
        if left is None or right is None:
            differences.append(
                {"scenario_id": scenario_id, "kind": "presence", "baseline": left is not None, "candidate": right is not None}
            )
            scenarios.append({"scenario_id": scenario_id, "status": "different", "reason": "scenario missing on one lane"})
            continue
        assertions: list[dict[str, Any]] = []
        scenario_differs = False
        for text in sorted(set(left) | set(right)):
            base_set = left.get(text)
            cand_set = right.get(text)
            entry: dict[str, Any] = {
                "text": text,
                "baseline": sorted(base_set) if base_set else None,
                "candidate": sorted(cand_set) if cand_set else None,
            }
            if text in base_semantics or text in cand_semantics:
                entry["declared_semantics"] = {
                    "baseline": base_semantics.get(text),
                    "candidate": cand_semantics.get(text),
                }
                declared.append({"scenario_id": scenario_id, "text": text, **entry["declared_semantics"]})
            same = base_set is not None and cand_set is not None and base_set == cand_set and len(base_set) == 1
            entry["agrees"] = same
            if not same:
                scenario_differs = True
                differences.append(
                    {"scenario_id": scenario_id, "kind": "assertion", "text": text, "baseline": entry["baseline"], "candidate": entry["candidate"]}
                )
            assertions.append(entry)

        def _structural(records: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "statuses": sorted({r["status"] for r in records}),
                "errors": sorted({(r.get("error") or {}).get("code", "") for r in records if r.get("error")}),
                "deviation_kinds": sorted({d.get("kind", "") for r in records for d in r.get("deviations", [])}),
                "runtime_verification": sorted(
                    {name for r in records for name in (r.get("runtime_verification") or {})}
                ),
                "manifests_complete": all((r.get("manifest") or {}).get("root_digest") for r in records),
            }

        structural = {
            "baseline": _structural(base_records.get(scenario_id, [])),
            "candidate": _structural(cand_records.get(scenario_id, [])),
        }
        status_differs = structural["baseline"]["statuses"] != structural["candidate"]["statuses"]
        if status_differs:
            scenario_differs = True
            differences.append(
                {"scenario_id": scenario_id, "kind": "status", "baseline": structural["baseline"]["statuses"], "candidate": structural["candidate"]["statuses"]}
            )
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "status": "different" if scenario_differs else "equivalent",
                "assertions": assertions,
                # Reported, never a difference: how each lane got there.
                "structural": structural,
            }
        )

    both_deterministic = bool(baseline.get("deterministic")) and bool(candidate.get("deterministic"))
    if not both_deterministic:
        differences.append(
            {"kind": "determinism", "baseline": baseline.get("deterministic"), "candidate": candidate.get("deterministic")}
        )
    status = "equivalent" if not differences else "different"
    return {
        "schema_version": "browser-workbench.corpus-differential/v1",
        "status": status,
        "corpus": {"id": baseline.get("corpus_id"), "version": baseline.get("corpus_version")},
        "baseline": _lane(baseline),
        "candidate": _lane(candidate),
        "semantic_digests_match": baseline.get("semantic_digest") == candidate.get("semantic_digest"),
        "scenario_count": len(scenarios),
        "equivalent_scenarios": sum(s["status"] == "equivalent" for s in scenarios),
        "different_scenarios": sum(s["status"] == "different" for s in scenarios),
        # Assertions the candidate reaches by declared, backend-specific means.
        # They agree in outcome; they are listed because a digest hides them.
        "declared_semantic_divergences": declared,
        "differences": differences,
        "scenarios": scenarios,
        "what_this_means": (
            "equivalent: every frozen assertion resolved identically on both lanes and both "
            "were deterministic. It does not mean the lanes produced identical evidence; "
            "the structural section shows where they differ in how."
        ),
    }
