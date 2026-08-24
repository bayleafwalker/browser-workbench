#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workbench.native_probe import probe_backend  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=["webkitgtk", "servo-gtk", "playwright"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true", help="compile/check after the prerequisite probe passes")
    args = parser.parse_args()
    probe = probe_backend(args.backend)
    command: list[str] | None = None
    if args.backend == "webkitgtk":
        command = ["cargo", "check", "-p", "browser-workbench-webkitgtk-worker", "--no-default-features", "--features", "native"]
    elif args.backend == "servo-gtk":
        command = ["cargo", "check", "-p", "browser-workbench-servo-gtk-worker", "--no-default-features", "--features", "native"]
    elif args.backend == "playwright":
        command = ["node", "oracle/playwright/probe.mjs", "--launch"]
    executed = False
    exit_code: int | None = None
    output = ""
    if probe["ready"] and args.execute and command:
        executed = True
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=900)
        exit_code = completed.returncode
        output = (completed.stdout + completed.stderr)[-8192:]
    status = "passed" if probe["ready"] and (not args.execute or exit_code == 0) else "blocked" if not probe["ready"] else "failed"
    report = {
        "schema_version": "browser-workbench.native-gate/v1",
        "backend": args.backend,
        "status": status,
        "probe": probe,
        "command": command,
        "executed": executed,
        "exit_code": exit_code,
        "output": output,
        "claim": (
            "oracle-launch-verified"
            if status == "passed" and executed and args.backend == "playwright"
            else "native-compile-verified"
            if status == "passed" and executed
            else "prerequisite-only"
            if status == "passed"
            else "not-runtime-verified"
        ),
        "runtime_conformance_claim": False,
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if status == "passed" else 78 if status == "blocked" else 1


if __name__ == "__main__":
    sys.exit(main())
