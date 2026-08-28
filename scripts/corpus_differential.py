#!/usr/bin/env python3
"""Produce the differential report between the mock denominator and a native
corpus run.

Matching semantic digests are not a differential report. This is: it runs
the mock corpus fresh, loads one or more native corpus summaries, and
compares them assertion by assertion, listing every declared semantic
divergence and every structural difference alongside the verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workbench.corpus import run_corpus  # noqa: E402
from workbench.corpus_compare import compare_corpora  # noqa: E402
from workbench.errors import WorkbenchError  # noqa: E402
from workbench.util import pretty_json, sha256_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "corpus-differential")
    parser.add_argument(
        "--native",
        type=Path,
        action="append",
        help="a native corpus root (containing corpus-summary.json); repeatable. "
        "Defaults to evidence/native-corpus and evidence/native-corpus-persistent when present.",
    )
    parser.add_argument("--repetitions", type=int)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)

    natives = args.native or [
        path
        for path in (ROOT / "evidence" / "native-corpus", ROOT / "evidence" / "native-corpus-persistent")
        if (path / "corpus-summary.json").is_file()
    ]
    if not natives:
        report = {
            "schema_version": "browser-workbench.corpus-differential-set/v1",
            "status": "blocked",
            "reason": "no native corpus summary to compare against",
        }
        (args.output / "corpus-differential.json").write_text(pretty_json(report), encoding="utf-8")
        print(pretty_json(report), end="")
        return 78

    baseline = run_corpus(args.output / "mock-corpus", args.repetitions)
    comparisons = []
    for native_root in natives:
        summary_path = (native_root / "corpus-summary.json").resolve()
        candidate = json.loads(summary_path.read_text(encoding="utf-8"))
        try:
            comparison = compare_corpora(baseline, candidate)
        except WorkbenchError as error:
            comparison = {"status": "invalid", "error": error.as_dict()}
        comparison["candidate_source"] = {
            "path": str(summary_path.relative_to(ROOT)) if ROOT in summary_path.parents else str(summary_path),
            "sha256": sha256_file(summary_path),
        }
        name = native_root.name
        (args.output / f"corpus-differential-{name}.json").write_text(pretty_json(comparison), encoding="utf-8")
        comparisons.append({"name": name, **{k: comparison[k] for k in comparison if k != "scenarios"}})

    statuses = {item["status"] for item in comparisons}
    report = {
        "schema_version": "browser-workbench.corpus-differential-set/v1",
        "status": "equivalent" if statuses == {"equivalent"} else ("invalid" if "invalid" in statuses else "different"),
        "baseline": {"backend": baseline["backend"], "semantic_digest": baseline["semantic_digest"], "status": baseline["status"]},
        "comparisons": comparisons,
        "not_proof": (
            "Equivalence with the mock denominator shows the frozen assertions hold on the "
            "native engine. It is not evidence about the engine beyond those assertions."
        ),
    }
    (args.output / "corpus-differential.json").write_text(pretty_json(report), encoding="utf-8")
    print(pretty_json({k: report[k] for k in ("status", "baseline")}), end="")
    print()
    for item in comparisons:
        print(f"{item['name']}: {item['status']}  digests_match={item.get('semantic_digests_match')}  "
              f"equivalent={item.get('equivalent_scenarios')}/{item.get('scenario_count')}  "
              f"declared_divergences={len(item.get('declared_semantic_divergences', []))}")
    return 0 if report["status"] == "equivalent" else 1


if __name__ == "__main__":
    sys.exit(main())
