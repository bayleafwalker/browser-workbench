#!/usr/bin/env python3
"""Run one declared workflow on WebKitGTK and on the Playwright oracle, then
compare the two under declared tolerances.

The oracle is an external cross-check, never product core, and never proof
that WebKitGTK is correct. A difference here is a finding to investigate, not
an automatic failure of either lane — but it must be visible, which is the
whole point of running both.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workbench.compare import compare_runs  # noqa: E402
from workbench.errors import WorkbenchError  # noqa: E402
from workbench.fixture_server import FixtureServer  # noqa: E402
from workbench.native_probe import probe_backend  # noqa: E402
from workbench.runner import Runner  # noqa: E402
from workbench.util import pretty_json  # noqa: E402
from workbench.webkitgtk_backend import worker_binary  # noqa: E402

ORACLE_IMAGE = "mcr.microsoft.com/playwright:v1.62.1-noble"


def resolve(value: object, base_url: str) -> object:
    if isinstance(value, str):
        return value.replace("${FIXTURE_BASE_URL}", base_url)
    if isinstance(value, list):
        return [resolve(item, base_url) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, base_url) for key, item in value.items()}
    return value


def oracle_command(runner: str, spec: Path, output: Path, mount_root: Path) -> list[str] | None:
    """Pick how to invoke the oracle, or None when no host can run it."""
    local_ready = probe_backend("playwright")["ready"]
    if runner in {"auto", "local"} and local_ready:
        return ["node", "oracle/playwright/runner.mjs", str(spec), str(output)]
    if runner == "local":
        return None
    for engine in ("podman", "docker"):
        if runner in {"auto", engine} and shutil.which(engine):
            # The pinned image is the "enabled oracle host" the lane's README
            # means. Host networking is required to reach the loopback fixture.
            # The spec and output paths are passed as host-absolute paths, so
            # the repo is mounted at its own path as well as at /work. Without
            # the self-mount an evidence root inside the repo is invisible to
            # the container, and the oracle fails before it starts.
            command = [
                engine, "run", "--rm", "--network=host",
                "-v", f"{ROOT}:/work",
                "-v", f"{ROOT}:{ROOT}",
            ]
            # The evidence root may live outside the repo, and the container
            # cannot write to a path it cannot see.
            if ROOT not in mount_root.parents and mount_root != ROOT:
                command += ["-v", f"{mount_root}:{mount_root}"]
            command += [
                "-w", "/work",
                "-e", "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright",
                ORACLE_IMAGE,
                "node", "oracle/playwright/runner.mjs", str(spec), str(output),
            ]
            return command
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "oracle-differential")
    parser.add_argument("--oracle-runner", default="auto", choices=["auto", "local", "podman", "docker"])
    args = parser.parse_args()
    args.output = args.output.resolve()

    binary = worker_binary(ROOT)
    if not binary.is_file():
        print(pretty_json({"status": "blocked", "reason": "adapter binary is not built"}), end="")
        return 78

    tolerances = json.loads((ROOT / "examples" / "tolerances-oracle.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)

    with FixtureServer() as fixture:
        (args.output / "fixture-identity.json").write_text(
            pretty_json(fixture.identity()), encoding="utf-8"
        )
        native_spec = resolve(
            json.loads((ROOT / "examples" / "parity-webkitgtk.json").read_text()), fixture.base_url
        )
        native_result = Runner(args.output / "webkitgtk").run(native_spec)

        oracle_spec = resolve(
            json.loads((ROOT / "examples" / "parity-playwright.json").read_text()), fixture.base_url
        )
        oracle_dir = args.output / "playwright"
        oracle_dir.mkdir(parents=True, exist_ok=True)
        oracle_spec_path = args.output / "parity-playwright.resolved.json"
        oracle_spec_path.write_text(pretty_json(oracle_spec), encoding="utf-8")

        command = oracle_command(args.oracle_runner, oracle_spec_path, oracle_dir, args.output)
        if command is None:
            report = {
                "schema_version": "browser-workbench.oracle-differential/v1",
                "status": "blocked",
                "reason": "no host can run the pinned oracle",
                "probe": probe_backend("playwright")["reasons"],
                "webkitgtk_status": native_result["status"],
            }
            (args.output / "oracle-differential.json").write_text(
                pretty_json(report), encoding="utf-8"
            )
            print(pretty_json(report), end="")
            return 78

        completed = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=900
        )
        (args.output / "oracle-stdout.log").write_text(
            completed.stdout + completed.stderr, encoding="utf-8"
        )

    oracle_result_path = oracle_dir / "result.json"
    if not oracle_result_path.is_file():
        report = {
            "schema_version": "browser-workbench.oracle-differential/v1",
            "status": "blocked",
            "reason": "the oracle produced no result",
            "exit_code": completed.returncode,
            "output_tail": (completed.stdout + completed.stderr)[-2000:],
        }
        (args.output / "oracle-differential.json").write_text(pretty_json(report), encoding="utf-8")
        print(pretty_json(report), end="")
        return 78

    try:
        comparison = compare_runs(
            args.output / "webkitgtk" / native_spec["run_id"], oracle_dir, tolerances
        )
    except WorkbenchError as error:
        report = {
            "schema_version": "browser-workbench.oracle-differential/v1",
            "status": "invalid",
            "error": error.as_dict(),
        }
        (args.output / "oracle-differential.json").write_text(pretty_json(report), encoding="utf-8")
        print(pretty_json(report), end="")
        return 64

    report = {
        "schema_version": "browser-workbench.oracle-differential/v1",
        # `different` is a finding to investigate, not proof either lane is wrong.
        "status": comparison["status"],
        "runner": command[0],
        "webkitgtk": {"status": native_result["status"], "run_id": native_spec["run_id"]},
        "playwright": {
            "status": json.loads(oracle_result_path.read_text())["status"],
            "exit_code": completed.returncode,
        },
        "tolerances": tolerances,
        "differences": comparison["differences"],
        "capability_differences_ignored": bool(comparison["capability_differences"]),
        "input_integrity": comparison["input_integrity"],
        "oracle_is_not_proof": (
            "The oracle cross-checks observable behaviour. It is not evidence that "
            "WebKitGTK is correct, and it never gates the native lane."
        ),
    }
    (args.output / "oracle-differential.json").write_text(pretty_json(report), encoding="utf-8")
    print(pretty_json(report), end="")
    return 0 if comparison["status"] == "equivalent" else 1


if __name__ == "__main__":
    sys.exit(main())
