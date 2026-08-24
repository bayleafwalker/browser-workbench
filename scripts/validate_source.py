#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    for path in sorted(ROOT.rglob("*.json")):
        if any(part in {"evidence", ".git"} for part in path.parts):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"invalid JSON {path.relative_to(ROOT)}: {error}")

    corpus = json.loads((ROOT / "spec" / "WORKBENCH_CORPUS_V1.json").read_text())
    if len(corpus["scenarios"]) != 12 or corpus["repetitions"] != 3:
        errors.append("workbench denominator must remain 12 scenarios x 3 repetitions")
    baseline = (ROOT / "baseline" / "hostproto-0.1.0" / "SCENARIO_CORPUS_V0.yaml").read_text()
    if baseline.count("  - id: HP-S") != 16:
        errors.append("frozen hostproto denominator no longer has 16 scenarios")

    hooks = (ROOT / "native" / "webkitgtk-worker" / "src" / "native_adapter.rs").read_text()
    for symbol in (
        "connect_load_changed", "connect_load_failed", "connect_resource_load_started",
        "connect_permission_request", "connect_run_file_chooser", "connect_script_dialog",
        "connect_web_process_terminated", "evaluate_javascript_future", "snapshot_future",
    ):
        if symbol not in hooks:
            errors.append(f"WebKitGTK source boundary lacks {symbol}")

    pins = json.loads((ROOT / "native" / "UPSTREAM_PINS.json").read_text())["pins"]
    cargo = (ROOT / "Cargo.toml").read_text()
    servo_cargo = (ROOT / "native" / "servo-gtk-worker" / "Cargo.toml").read_text()
    oracle = json.loads((ROOT / "oracle" / "playwright" / "package.json").read_text())
    if pins["webkit6-rs"]["crate"] not in cargo or pins["gtk4-rs"]["crate"] not in cargo:
        errors.append("Rust workspace versions do not match upstream pins")
    if pins["servo-gtk"]["revision"] not in servo_cargo:
        errors.append("ServoGTK Cargo revision does not match upstream pin")
    if oracle["devDependencies"]["@playwright/test"] != pins["playwright"]["version"]:
        errors.append("Playwright package does not match upstream pin")

    required = [
        "src/workbench/runner.py", "src/workbench/mock_backend.py", "src/workbench/bridge.py",
        "spec/WORKBENCH_PROTOCOL_V1.md", "spec/RUNNER_CONTRACT_V1.md", "chrome/index.html",
        "native/gtk-shell/src/native_shell.rs", "oracle/playwright/runner.mjs",
    ]
    for relative in required:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required source: {relative}")

    report = {"schema_version": "browser-workbench.source-validation/v1", "status": "passed" if not errors else "failed", "errors": errors}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
