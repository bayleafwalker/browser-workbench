from __future__ import annotations

import copy
import unittest

from workbench.corpus_compare import compare_corpora
from workbench.errors import WorkbenchError


def summary(kind: str = "mock", *, flip: str | None = None, semantics: dict | None = None) -> dict:
    def record(scenario: str, rep: int) -> dict:
        assertions = [{"text": "a holds", "passed": True}, {"text": "b holds", "passed": True}]
        if flip == scenario:
            assertions[1]["passed"] = False
        return {
            "scenario_id": scenario,
            "repetition": rep,
            "status": "passed" if flip != scenario else "failed",
            "assertions": assertions,
            "error": None,
            "deviations": [],
            "runtime_verification": {"page.navigate": 1},
            "manifest": {"root_digest": "x"},
        }

    return {
        "corpus_id": "denominator",
        "corpus_version": "1.0.0",
        "backend": {"kind": kind, "variant": "v"},
        "status": "passed" if not flip else "failed",
        "deterministic": True,
        "passed": 4,
        "failed": 0,
        "run_count": 4,
        "semantic_digest": "d-" + kind + (flip or ""),
        "assertion_semantics": semantics or {},
        "records": [record("S1", 1), record("S1", 2), record("S2", 1), record("S2", 2)],
    }


class CorpusCompareTests(unittest.TestCase):
    def test_identical_outcomes_are_equivalent_and_declared_divergences_are_listed(self) -> None:
        report = compare_corpora(summary(), summary("webkitgtk", semantics={"a holds": "by other means"}))
        self.assertEqual(report["status"], "equivalent")
        self.assertEqual(report["equivalent_scenarios"], 2)
        self.assertFalse(report["semantic_digests_match"])
        self.assertEqual(len(report["declared_semantic_divergences"]), 2)
        self.assertEqual(report["declared_semantic_divergences"][0]["candidate"], "by other means")

    def test_one_flipped_assertion_is_a_difference(self) -> None:
        report = compare_corpora(summary(), summary("webkitgtk", flip="S2"))
        self.assertEqual(report["status"], "different")
        self.assertEqual(report["different_scenarios"], 1)
        kinds = {d["kind"] for d in report["differences"]}
        self.assertIn("assertion", kinds)
        self.assertIn("status", kinds)

    def test_non_determinism_is_a_difference_even_with_equal_outcomes(self) -> None:
        candidate = summary("webkitgtk")
        candidate["deterministic"] = False
        report = compare_corpora(summary(), candidate)
        self.assertEqual(report["status"], "different")
        self.assertEqual(report["differences"][0]["kind"], "determinism")

    def test_different_denominators_are_rejected(self) -> None:
        candidate = copy.deepcopy(summary("webkitgtk"))
        candidate["corpus_version"] = "2.0.0"
        with self.assertRaises(WorkbenchError):
            compare_corpora(summary(), candidate)


if __name__ == "__main__":
    unittest.main()
