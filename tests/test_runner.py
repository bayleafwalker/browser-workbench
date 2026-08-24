from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workbench import runner as runner_module
from workbench import webkitgtk_backend
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

    def _native_spec(self, kind: str, variant: str) -> dict:
        spec = copy.deepcopy(self.spec)
        spec["run_id"] = f"native-blocked-{kind}"
        spec["backend"] = {"kind": kind, "variant": variant}
        spec["required_capabilities"] = ["session.create"]
        spec["allowed_providers"] = ["engine", "host"]
        return spec

    def test_native_lane_blocks_rather_than_falling_back_to_the_mock(self) -> None:
        """The block lifts only for a connected adapter, never for a present host.

        This is the guard the whole project rests on: a native lane that cannot
        run must say so, and must never quietly produce mock evidence under a
        native backend label. It holds whether or not this host has WebKitGTK.
        """
        spec = self._native_spec("webkitgtk", "stable-ephemeral")
        missing = repo_root() / "target" / "debug" / "no-such-adapter-binary"
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(webkitgtk_backend, "worker_binary", return_value=missing):
                result = Runner(Path(directory)).run(spec)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["terminal_reason"]["code"], "capability_blocked")
            self.assertFalse(any(step["status"] == "passed" for step in result["steps"]))
            self.assertEqual(result["backend"]["kind"], "webkitgtk")

    def test_unprobed_native_host_is_blocked(self) -> None:
        spec = self._native_spec("webkitgtk", "stable-ephemeral")
        unready = {
            "backend": "webkitgtk",
            "ready": False,
            "reasons": ["WebKitGTK 6.0 development package missing"],
            "checks": {},
            "display": {"wayland": False, "x11": False},
        }
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(runner_module, "probe_backend", return_value=unready):
                result = Runner(Path(directory)).run(spec)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["terminal_reason"]["code"], "capability_blocked")
            self.assertFalse(any(step["status"] == "passed" for step in result["steps"]))

    def test_backends_without_an_adapter_remain_blocked(self) -> None:
        for kind in ("servo-gtk", "playwright"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                result = Runner(Path(directory)).run(self._native_spec(kind, "default"))
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["terminal_reason"]["code"], "capability_blocked")
                self.assertFalse(any(step["status"] == "passed" for step in result["steps"]))


if __name__ == "__main__":
    unittest.main()
