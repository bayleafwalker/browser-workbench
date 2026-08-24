from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workbench.compare import compare_runs
from workbench.errors import WorkbenchError
from workbench.util import pretty_json, tree_digest


def fixture(order: tuple[str, ...] = ("a", "b"), status: str = "passed") -> dict:
    return {
        "status": status,
        "steps": [{"step_id": item, "method": item, "status": "passed", "wall_time": index} for index, item in enumerate(order)],
        "gates": [],
        "terminal_reason": {"code": "completed" if status == "passed" else "failed"},
        "capabilities": {"capabilities": {}},
    }


class CompareTests(unittest.TestCase):
    def test_declared_partial_order_normalization(self) -> None:
        report = compare_runs(fixture(), fixture(("b", "a")), {"step_order": "by_step_id"})
        self.assertEqual(report["status"], "equivalent")

    def test_semantic_change_is_visible(self) -> None:
        report = compare_runs(fixture(), fixture(status="failed"))
        self.assertEqual(report["status"], "different")
        self.assertTrue(report["differences"])

    def test_declared_candidate_digest_blocks_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline"
            candidate = root / "candidate"
            baseline.mkdir()
            candidate.mkdir()
            (baseline / "result.json").write_text(pretty_json(fixture()), encoding="utf-8")
            (candidate / "result.json").write_text(pretty_json(fixture()), encoding="utf-8")
            expected = tree_digest(candidate)
            changed = fixture(status="failed")
            (candidate / "result.json").write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(WorkbenchError) as context:
                compare_runs(baseline, candidate, expected_candidate_digest=expected)
            self.assertEqual(context.exception.code, "candidate_mutated")


if __name__ == "__main__":
    unittest.main()
