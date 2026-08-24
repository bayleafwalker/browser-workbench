from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workbench.corpus import DRIVERS, run_corpus
from workbench.util import repo_root


class CorpusTests(unittest.TestCase):
    def test_frozen_workbench_corpus_has_twelve_bound_drivers(self) -> None:
        corpus = json.loads((repo_root() / "spec" / "WORKBENCH_CORPUS_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(corpus["scenarios"]), 12)
        self.assertEqual({item["driver"] for item in corpus["scenarios"]}, set(DRIVERS))
        self.assertEqual(corpus["repetitions"], 3)

    def test_one_repetition_passes_all_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = run_corpus(Path(directory), repetitions=1)
            self.assertEqual(summary["status"], "passed")
            self.assertEqual(summary["passed"], 12)
            self.assertEqual(summary["failed"], 0)

    def test_frozen_hostproto_baseline_still_has_sixteen_scenarios(self) -> None:
        text = (repo_root() / "baseline" / "hostproto-0.1.0" / "SCENARIO_CORPUS_V0.yaml").read_text(encoding="utf-8")
        self.assertEqual(text.count("  - id: HP-S"), 16)


if __name__ == "__main__":
    unittest.main()
