#!/usr/bin/env python3
"""Execute the frozen 12-scenario denominator against a real WebKitGTK engine.

This is the corpus, not a sample of it. A partial run is a failure, not a
smaller success: the denominator is twelve scenarios times the declared
repetitions, and anything less does not license a conformance claim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workbench.corpus import run_corpus  # noqa: E402
from workbench.corpus_profiles import profile_for  # noqa: E402
from workbench.fixture_server import FixtureServer  # noqa: E402
from workbench.util import pretty_json  # noqa: E402
from workbench.webkitgtk_backend import worker_binary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "native-corpus")
    parser.add_argument("--variant", default="stable-ephemeral")
    parser.add_argument("--repetitions", type=int)
    args = parser.parse_args()
    args.output = args.output.resolve()

    binary = worker_binary(ROOT)
    if not binary.is_file():
        report = {
            "schema_version": "browser-workbench.native-corpus/v1",
            "status": "blocked",
            "reason": "adapter binary is not built",
            "expected_binary": str(binary.relative_to(ROOT)),
        }
        print(pretty_json(report), end="")
        return 78

    with FixtureServer() as fixture:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "fixture-identity.json").write_text(
            pretty_json(fixture.identity()), encoding="utf-8"
        )
        profile = profile_for("webkitgtk", base_url=fixture.base_url, variant=args.variant)
        summary = run_corpus(args.output, args.repetitions, profile=profile)

    failures = [
        {
            "scenario_id": record["scenario_id"],
            "repetition": record["repetition"],
            "error": record["error"],
            "failed_assertions": [
                item["text"] for item in record["assertions"] if not item["passed"]
            ],
        }
        for record in summary["records"]
        if record["status"] != "passed"
    ]
    digest = {
        "schema_version": "browser-workbench.native-corpus/v1",
        "status": summary["status"],
        "backend": summary["backend"],
        "scenario_count": summary["scenario_count"],
        "repetitions": summary["repetitions"],
        "run_count": summary["run_count"],
        "passed": summary["passed"],
        "failed": summary["failed"],
        "deterministic": summary["deterministic"],
        "semantic_digest": summary["semantic_digest"],
        "assertion_semantics": summary["assertion_semantics"],
        "failures": failures,
    }
    (args.output / "native-corpus.json").write_text(pretty_json(digest), encoding="utf-8")
    print(pretty_json(digest), end="")
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
