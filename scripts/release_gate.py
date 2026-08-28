#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "release-0.2.0"


def run(name: str, command: list[str], *, accept: set[int] = {0}) -> dict:
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    completed = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False, timeout=900
    )
    if completed.returncode == 0:
        status = "passed"
    elif completed.returncode in accept:
        status = "accepted-blocked" if completed.returncode == 78 else "accepted-nonzero"
    else:
        status = "failed"
    return {
        "name": name,
        "status": status,
        "exit_code": completed.returncode,
        "accepted_exit_codes": sorted(accept),
        "stdout": completed.stdout[-8192:],
        "stderr": completed.stderr[-8192:],
    }


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    checks = [
        run("source-validation", [python, "scripts/validate_source.py"]),
        run("python-tests", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]),
        run("chrome-tests", ["node", "--test", "chrome/state.test.mjs"]),
        run("mock-corpus-12x3", [python, "-m", "workbench.cli", "corpus", "--output", str(EVIDENCE / "mock-corpus")]),
        run("disclosure-scan", [python, "scripts/disclosure_scan.py", "."]),
        run("webkitgtk-native-probe", [python, "scripts/native_gate.py", "webkitgtk", "--output", str(EVIDENCE / "native-webkitgtk.json")], accept={0, 78}),
        run("servo-gtk-native-probe", [python, "scripts/native_gate.py", "servo-gtk", "--output", str(EVIDENCE / "native-servo-gtk.json")], accept={0, 78}),
        run("playwright-oracle-probe", [python, "scripts/native_gate.py", "playwright", "--output", str(EVIDENCE / "oracle-playwright.json")], accept={0, 78}),
        # One real WebKitGTK session. Blocked is an accepted outcome on a host
        # without the adapter built; a mock substitution never is.
        run("webkitgtk-native-e2e", [python, "scripts/native_e2e.py", "--output", str(EVIDENCE / "native-slice1")], accept={0, 78}),
        run("webkitgtk-native-e2e-observation", [python, "scripts/native_e2e.py", "--spec", "examples/native-webkitgtk-slice2.json", "--output", str(EVIDENCE / "native-slice2")], accept={0, 78}),
        run("webkitgtk-native-corpus-12x3-ephemeral", [python, "scripts/native_corpus.py", "--output", str(EVIDENCE / "native-corpus")], accept={0, 78}),
        run("webkitgtk-native-corpus-12x3-persistent", [python, "scripts/native_corpus.py", "--variant", "stable-persistent", "--output", str(EVIDENCE / "native-corpus-persistent")], accept={0, 78}),
        # A differing oracle is a finding to review, not something to waive:
        # only `blocked` (no host can run it) is accepted here.
        run("oracle-differential", [python, "scripts/oracle_differential.py", "--output", str(EVIDENCE / "oracle-differential")], accept={0, 78}),
        # The whole denominator against the oracle, every scenario classified.
        # `different` is never accepted; `blocked` (no oracle host) is.
        run("oracle-corpus-differential", [python, "scripts/oracle_corpus_differential.py", "--output", str(EVIDENCE / "oracle-corpus-differential")], accept={0, 78}),
        # Mock denominator versus the native corpora just produced above:
        # matching digests are not a differential report, this is.
        run("corpus-differential", [python, "scripts/corpus_differential.py", "--output", str(EVIDENCE / "corpus-differential"), "--native", str(EVIDENCE / "native-corpus"), "--native", str(EVIDENCE / "native-corpus-persistent")], accept={0, 78}),
    ]
    required = checks[:5]
    passed = all(item["status"] == "passed" for item in required)
    native_blocked = [item["name"] for item in checks[5:] if item["exit_code"] == 78]
    differential = next(item for item in checks if item["name"] == "oracle-differential")
    oracle_corpus = next(item for item in checks if item["name"] == "oracle-corpus-differential")
    corpus_differential = next(item for item in checks if item["name"] == "corpus-differential")
    e2e_checks = [item for item in checks if item["name"].startswith("webkitgtk-native-e2e")]
    corpus_checks = [item for item in checks if item["name"].startswith("webkitgtk-native-corpus")]
    corpus_passed = all(item["exit_code"] == 0 for item in corpus_checks)
    report = {
        "schema_version": "browser-workbench.release-gate/v1",
        "release": "0.2.0-source-checkpoint",
        "status": "passed" if passed else "failed",
        # The claim tracks what actually ran: the whole denominator on a real
        # engine, on both declared variants.
        "claim": (
            "source-mock-and-native-corpus-verified"
            if corpus_passed
            else "source-and-mock-verified"
        ),
        # One session through the public protocol on a real engine.
        "native_vertical_proof": "passed" if all(item["exit_code"] == 0 for item in e2e_checks) else "blocked",
        # The whole denominator, both declared variants, on a real engine —
        # the condition the baseline plan sets for a native runtime claim.
        # It says nothing about the oracle or about Servo, which report
        # separately in native_or_oracle_blocked.
        "native_runtime_claim": corpus_passed,
        "native_corpus_claim": corpus_passed,
        "oracle_differential": differential["status"],
        "oracle_corpus_differential": oracle_corpus["status"],
        "corpus_differential": corpus_differential["status"],
        "native_corpus_variants": {
            item["name"].rsplit("-", 1)[-1]: item["status"] for item in corpus_checks
        },
        "native_or_oracle_blocked": native_blocked,
        "checks": checks,
    }
    (EVIDENCE / "release-gate.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "claim", "native_vertical_proof", "native_runtime_claim", "native_corpus_claim", "oracle_differential", "oracle_corpus_differential", "corpus_differential", "native_or_oracle_blocked")}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
