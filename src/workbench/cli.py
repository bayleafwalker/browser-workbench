from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .capabilities import capability_report
from .compare import compare_runs
from .corpus import run_corpus
from .errors import WorkbenchError
from .native_probe import probe_backend
from .runner import run_spec_file
from .util import pretty_json


EXIT = {"passed": 0, "different": 1, "failed": 1, "unsupported": 2, "invalid": 64, "blocked": 78}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browser-workbench")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="execute one declared run spec")
    run.add_argument("spec", type=Path)
    run.add_argument("--output", type=Path, required=True)
    cap = sub.add_parser("capabilities", help="emit a truthful capability report")
    cap.add_argument("backend", choices=["mock", "webkitgtk", "playwright", "servo-gtk"])
    cap.add_argument("--variant", default="default")
    cap.add_argument(
        "--runtime-ledger",
        type=Path,
        help="a runtime-verification.json produced by a corpus run; upgrades verification only where it shows execution",
    )
    probe = sub.add_parser("probe", help="probe backend prerequisites")
    probe.add_argument("backend", choices=["mock", "webkitgtk", "playwright", "servo-gtk"])
    compare = sub.add_parser("compare", help="compare two evidence results")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--tolerances", type=Path)
    corpus = sub.add_parser("corpus", help="execute the frozen workbench denominator")
    corpus.add_argument("--output", type=Path, required=True)
    corpus.add_argument("--repetitions", type=int)
    corpus.add_argument("--backend", choices=["mock", "webkitgtk"], default="mock")
    corpus.add_argument("--variant")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            result = run_spec_file(args.spec, args.output)
            print(pretty_json(result), end="")
            return EXIT.get(result["status"], 1)
        if args.command == "capabilities":
            ledger = None
            if args.runtime_ledger:
                ledger_file = json.loads(args.runtime_ledger.read_text(encoding="utf-8"))
                if ledger_file.get("backend", {}).get("kind") != args.backend:
                    raise WorkbenchError(
                        "invalid_request",
                        "the runtime ledger belongs to a different backend",
                        {"ledger_backend": ledger_file.get("backend"), "requested": args.backend},
                    )
                ledger = ledger_file["executions"]
            report = capability_report(args.backend, args.variant, runtime_ledger=ledger)
            print(pretty_json(report), end="")
            return 0 if report["identity"]["probe"]["ready"] else 78
        if args.command == "probe":
            report = probe_backend(args.backend)
            print(pretty_json(report), end="")
            return 0 if report["ready"] else 78
        if args.command == "compare":
            tolerances = json.loads(args.tolerances.read_text()) if args.tolerances else None
            report = compare_runs(args.baseline, args.candidate, tolerances)
            print(pretty_json(report), end="")
            return EXIT.get(report["status"], 1)
        if args.command == "corpus":
            if args.backend == "mock":
                summary = run_corpus(args.output, args.repetitions)
            else:
                # A native corpus needs the fixture site to exist for the
                # duration of every scenario, not just the first.
                from .corpus_profiles import profile_for
                from .fixture_server import FixtureServer

                with FixtureServer() as fixture:
                    summary = run_corpus(
                        args.output,
                        args.repetitions,
                        profile=profile_for(
                            args.backend, base_url=fixture.base_url, variant=args.variant
                        ),
                    )
            print(pretty_json(summary), end="")
            return EXIT[summary["status"]]
    except WorkbenchError as error:
        print(pretty_json({"status": error.status, "error": error.as_dict()}), end="")
        return EXIT.get(error.status, 1)
    return 64


if __name__ == "__main__":
    sys.exit(main())
