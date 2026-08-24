from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from workbench.runner import Runner
from workbench.util import repo_root


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = json.loads((repo_root() / "examples" / "mock-run.json").read_text(encoding="utf-8"))

    def test_declared_mock_workflow_passes_without_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = Runner(Path(directory)).run(self.spec)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["environment"]["retry_count"], 0)
            self.assertTrue(all(step["status"] == "passed" for step in result["steps"]))
            self.assertTrue((Path(directory) / self.spec["run_id"] / "manifest.json").is_file())

    def test_unknown_method_is_invalid_before_backend_use(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["run_id"] = "invalid-method"
        spec["workflow"][0]["method"] = "page.plan"
        with tempfile.TemporaryDirectory() as directory:
            result = Runner(Path(directory)).run(spec)
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(result["terminal_reason"]["code"], "invalid_request")
            self.assertTrue(all(step["status"] == "skipped" for step in result["steps"]))

    def test_native_lane_is_blocked_not_faked(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["run_id"] = "native-blocked"
        spec["backend"] = {"kind": "webkitgtk", "variant": "stable"}
        spec["required_capabilities"] = ["session.create"]
        with tempfile.TemporaryDirectory() as directory:
            result = Runner(Path(directory)).run(spec)
            self.assertEqual(result["status"], "blocked")
            self.assertIn(result["terminal_reason"]["code"], {"capability_blocked"})
            self.assertFalse(any(step["status"] == "passed" for step in result["steps"]))


if __name__ == "__main__":
    unittest.main()
