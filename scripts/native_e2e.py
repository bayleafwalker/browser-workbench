#!/usr/bin/env python3
"""End-to-end WebKitGTK vertical proof.

Starts the deterministic loopback fixture, resolves the slice 1 run spec
against its real base URL, and executes it through the public protocol with a
real adapter process. A compile-only gate is not sufficient evidence and this
script is not a substitute for the 12x3 corpus: it proves one session.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workbench.fixture_server import FixtureServer  # noqa: E402
from workbench.runner import Runner  # noqa: E402
from workbench.util import pretty_json  # noqa: E402
from workbench.webkitgtk_backend import worker_binary  # noqa: E402

SPEC = ROOT / "examples" / "native-webkitgtk-slice1.json"


def resolve(value: object, base_url: str) -> object:
    if isinstance(value, str):
        return value.replace("${FIXTURE_BASE_URL}", base_url)
    if isinstance(value, list):
        return [resolve(item, base_url) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, base_url) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "native-slice1")
    parser.add_argument("--variant", default="stable-ephemeral")
    parser.add_argument("--spec", type=Path, default=SPEC)
    args = parser.parse_args()
    args.output = args.output.resolve()

    binary = worker_binary(ROOT)
    if not binary.is_file():
        report = {
            "schema_version": "browser-workbench.native-e2e/v1",
            "status": "blocked",
            "reason": "adapter binary is not built",
            "expected_binary": str(binary.relative_to(ROOT)),
            "runtime_conformance_claim": False,
        }
        print(pretty_json(report), end="")
        return 78

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    with FixtureServer() as fixture:
        resolved = resolve(spec, fixture.base_url)
        resolved["backend"]["variant"] = args.variant
        resolved["run_id"] = f"{spec['run_id']}-{args.variant}"
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "fixture-identity.json").write_text(
            pretty_json(fixture.identity()), encoding="utf-8"
        )
        (args.output / "resolved-run-spec.json").write_text(pretty_json(resolved), encoding="utf-8")
        result = Runner(args.output).run(resolved)

    run_directory = args.output / resolved["run_id"]
    report = {
        "schema_version": "browser-workbench.native-e2e/v1",
        "slice": 1,
        "backend": result["backend"],
        "status": result["status"],
        "terminal_reason": result["terminal_reason"],
        "steps": [
            {"step_id": step["step_id"], "method": step["method"], "status": step["status"]}
            for step in result["steps"]
        ],
        "gates": result["gates"],
        "deviations": result["deviations"],
        "evidence_root": str(run_directory),
        "artifact_count": len(result["artifacts"]),
        # One real session is not corpus conformance. Wave 2 remains open.
        "runtime_conformance_claim": False,
        "corpus_claim": None,
    }
    (args.output / "native-e2e.json").write_text(pretty_json(report), encoding="utf-8")
    print(pretty_json(report), end="")
    return 0 if result["status"] == "passed" else 78 if result["status"] == "blocked" else 1


if __name__ == "__main__":
    sys.exit(main())
