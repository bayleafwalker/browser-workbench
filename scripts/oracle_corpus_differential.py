#!/usr/bin/env python3
"""Run the frozen denominator's declared oracle workflows on WebKitGTK and on
the Playwright oracle, scenario by scenario, and classify all twelve.

Every scenario ends up in exactly one class:

  equivalent   both lanes executed the declared workflow and agree under the
               declared tolerances
  different    the lanes disagree; a finding to investigate, never waived
  blocked      no host could run the oracle for this scenario
  inapplicable the oracle structurally lacks what the scenario tests; the
               spec names the mechanism, per scenario

None of these shrinks the denominator: the report always lists twelve.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from oracle_differential import oracle_command  # noqa: E402
from workbench.compare import compare_runs  # noqa: E402
from workbench.errors import WorkbenchError  # noqa: E402
from workbench.fixture_server import FixtureServer  # noqa: E402
from workbench.native_probe import probe_backend  # noqa: E402
from workbench.runner import Runner  # noqa: E402
from workbench.util import pretty_json  # noqa: E402
from workbench.webkitgtk_backend import worker_binary  # noqa: E402

NATIVE_GATES = [
    {"id": "contract", "kind": "contract", "required": True},
    {"id": "capabilities", "kind": "capability", "required": True},
    {"id": "execution", "kind": "execution", "required": True},
    {"id": "evidence", "kind": "evidence", "required": True},
    {"id": "native", "kind": "native", "required": True},
]


def substitute(value: object, mapping: dict[str, str]) -> object:
    if isinstance(value, str):
        for key, replacement in mapping.items():
            value = value.replace(key, replacement)
        return value
    if isinstance(value, list):
        return [substitute(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, mapping) for key, item in value.items()}
    return value


def lane_spec(template: dict, scenario_id: str, backend: dict, mapping: dict[str, str], *, native: bool) -> dict:
    spec = dict(substitute(template, mapping))
    spec["run_id"] = f"oracle-corpus-{scenario_id}-{backend['kind']}"
    spec["backend"] = backend
    spec["gates"] = NATIVE_GATES if native else []
    return spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "oracle-corpus-differential")
    parser.add_argument("--oracle-runner", default="auto", choices=["auto", "local", "podman", "docker"])
    parser.add_argument("--scenario", action="append", help="limit to these scenario ids (the report still lists all twelve)")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)

    spec = json.loads((ROOT / "spec" / "ORACLE_CORPUS_V1.json").read_text(encoding="utf-8"))
    tolerances = json.loads((ROOT / "examples" / "tolerances-oracle.json").read_text(encoding="utf-8"))
    binary = worker_binary(ROOT)
    if not binary.is_file():
        report = {"schema_version": "browser-workbench.oracle-corpus-differential/v1", "status": "blocked", "reason": "adapter binary is not built"}
        (args.output / "oracle-corpus-differential.json").write_text(pretty_json(report), encoding="utf-8")
        print(pretty_json(report), end="")
        return 78

    scenarios: list[dict] = []
    runner_used: str | None = None
    with FixtureServer() as fixture:
        (args.output / "fixture-identity.json").write_text(pretty_json(fixture.identity()), encoding="utf-8")
        mapping = {"${FIXTURE_BASE_URL}": fixture.base_url, "${REPO_ROOT}": str(ROOT)}
        for scenario_id, declaration in sorted(spec["scenarios"].items()):
            entry: dict = {"scenario_id": scenario_id, "applicability": declaration["applicability"]}
            if declaration["applicability"] != "applicable":
                entry.update({"status": "inapplicable", "reason": declaration["reason"]})
                scenarios.append(entry)
                continue
            entry.update({
                "covers": declaration.get("covers", []),
                "omitted_assertions": declaration.get("omitted", {}),
                "expected_terminal_code": declaration.get("expected_terminal_code", "completed"),
            })
            if args.scenario and scenario_id not in args.scenario:
                entry.update({"status": "blocked", "reason": "not selected for this invocation"})
                scenarios.append(entry)
                continue

            template = json.loads((ROOT / declaration["workflow"]).read_text(encoding="utf-8"))
            scenario_dir = args.output / scenario_id
            native_spec = lane_spec(template, scenario_id, {"kind": "webkitgtk", "variant": "stable-ephemeral"}, mapping, native=True)
            native_result = Runner(scenario_dir / "webkitgtk").run(native_spec)
            entry["webkitgtk"] = {
                "status": native_result["status"],
                "terminal_code": native_result["terminal_reason"]["code"],
                "run_id": native_spec["run_id"],
            }

            oracle_spec = lane_spec(template, scenario_id, {"kind": "playwright", "variant": "webkit"}, mapping, native=False)
            oracle_dir = scenario_dir / "playwright"
            oracle_dir.mkdir(parents=True, exist_ok=True)
            oracle_spec_path = scenario_dir / "playwright.resolved.json"
            oracle_spec_path.write_text(pretty_json(oracle_spec), encoding="utf-8")
            command = oracle_command(args.oracle_runner, oracle_spec_path, oracle_dir, args.output)
            if command is None:
                entry.update({"status": "blocked", "reason": "no host can run the pinned oracle", "probe": probe_backend("playwright")["reasons"]})
                scenarios.append(entry)
                continue
            runner_used = command[0]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=900)
            (scenario_dir / "oracle-stdout.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
            oracle_result_path = oracle_dir / "result.json"
            if not oracle_result_path.is_file():
                entry.update({"status": "blocked", "reason": "the oracle produced no result", "exit_code": completed.returncode, "output_tail": (completed.stdout + completed.stderr)[-2000:]})
                scenarios.append(entry)
                continue
            oracle_result = json.loads(oracle_result_path.read_text(encoding="utf-8"))
            entry["playwright"] = {
                "status": oracle_result["status"],
                "terminal_code": oracle_result["terminal_reason"]["code"],
                "exit_code": completed.returncode,
                "oracle": oracle_result.get("oracle"),
            }
            try:
                comparison = compare_runs(scenario_dir / "webkitgtk" / native_spec["run_id"], oracle_dir, tolerances)
            except WorkbenchError as error:
                entry.update({"status": "invalid", "error": error.as_dict()})
                scenarios.append(entry)
                continue
            entry["differences"] = comparison["differences"]
            entry["declared_suppressions"] = comparison["declared_suppressions"]
            expected = entry["expected_terminal_code"]
            terminal_as_declared = all(lane["terminal_code"] == expected for lane in (entry["webkitgtk"], entry["playwright"]))
            if comparison["status"] == "equivalent" and terminal_as_declared:
                entry["status"] = "equivalent"
            else:
                entry["status"] = "different"
                if comparison["status"] == "equivalent":
                    # The lanes agree with each other but not with the declaration:
                    # still a finding, because the scenario was supposed to end there.
                    entry["reason"] = f"both lanes ended with {entry['webkitgtk']['terminal_code']}, declared {expected}"
            scenarios.append(entry)

    counts = {name: sum(item["status"] == name for item in scenarios) for name in ("equivalent", "different", "blocked", "inapplicable", "invalid")}
    if counts["different"] or counts["invalid"]:
        status = "different"
    elif counts["blocked"]:
        status = "blocked"
    else:
        status = "equivalent"
    report = {
        "schema_version": "browser-workbench.oracle-corpus-differential/v1",
        "status": status,
        "corpus": {"id": spec["corpus_id"], "version": spec["corpus_version"]},
        "scenario_count": len(scenarios),
        "counts": counts,
        "runner": runner_used,
        "tolerances": tolerances,
        "scenarios": scenarios,
        "oracle_is_not_proof": (
            "The oracle cross-checks observable behaviour on the scenarios it can express. "
            "It is not evidence that WebKitGTK is correct, it never gates the native lane, "
            "and an inapplicable scenario is neither a pass nor a fail."
        ),
    }
    (args.output / "oracle-corpus-differential.json").write_text(pretty_json(report), encoding="utf-8")
    print(pretty_json({"status": status, "counts": counts, "runner": runner_used}))
    for item in scenarios:
        line = f"{item['scenario_id']}: {item['status']}"
        if item.get("reason"):
            line += f" — {item['reason']}"
        if item.get("differences"):
            line += f" ({len(item['differences'])} differences)"
        print(line)
    return {"equivalent": 0, "blocked": 78}.get(status, 1)


if __name__ == "__main__":
    sys.exit(main())
