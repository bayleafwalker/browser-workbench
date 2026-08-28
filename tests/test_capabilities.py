from __future__ import annotations

import unittest

from workbench.capabilities import (
    RuntimeLedger,
    capability_report,
    exercised_capabilities,
    require_capabilities,
    with_runtime_verification,
)
from workbench.errors import WorkbenchError


class CapabilityTests(unittest.TestCase):
    def test_servo_missing_public_hooks_are_explicitly_unsupported(self) -> None:
        probe = {"ready": True, "reasons": [], "backend": "servo-gtk"}
        report = capability_report("servo-gtk", "pinned", probe=probe)
        for name in ("page.observe.state", "page.act.javascript", "page.dialog", "page.termination"):
            self.assertEqual(report["capabilities"][name]["availability"], "unsupported")
            self.assertEqual(report["capabilities"][name]["verification"], "source-audit")

    def test_partial_capability_does_not_satisfy_exact_gate(self) -> None:
        probe = {"ready": True, "reasons": [], "backend": "servo-gtk"}
        report = capability_report("servo-gtk", "pinned", probe=probe)
        with self.assertRaises(WorkbenchError) as context:
            require_capabilities(report, ["page.await"])
        self.assertEqual(context.exception.code, "capability_unsupported")

    def test_verification_is_source_audit_until_executed(self) -> None:
        probe = {"ready": True, "reasons": [], "backend": "mock"}
        report = capability_report("mock", "denominator", probe=probe)
        self.assertTrue(all(c["verification"] == "source-audit" for c in report["capabilities"].values()))

    def test_runtime_verification_is_earned_per_capability(self) -> None:
        probe = {"ready": True, "reasons": [], "backend": "webkitgtk"}
        ledger = RuntimeLedger()
        ledger.record("session.create", {"profile": {"mode": "persistent"}})
        ledger.record("page.observe", {"projection": ["state", "dom", "targets"]})
        ledger.record("page.act", {"intent": {"kind": "click"}})
        ledger.record("page.act", {"intent": {"kind": "click"}})
        report = with_runtime_verification(capability_report("webkitgtk", "stable-persistent", probe=probe), ledger)
        caps = report["capabilities"]
        self.assertEqual(caps["session.profile.persistent"]["verification"], "runtime")
        self.assertEqual(caps["session.profile.ephemeral"]["verification"], "source-audit")
        self.assertEqual(caps["page.act.pointer"]["runtime_executions"], 2)
        self.assertEqual(caps["page.observe.dom"]["verification"], "runtime")
        self.assertEqual(caps["page.navigate"]["verification"], "source-audit")
        self.assertEqual(sorted(report["runtime_verified"]), sorted(ledger.executions))

    def test_runtime_never_upgrades_unsupported_or_blocked(self) -> None:
        probe = {"ready": True, "reasons": [], "backend": "servo-gtk"}
        report = with_runtime_verification(capability_report("servo-gtk", "pinned", probe=probe), {"page.dialog": 1})
        self.assertEqual(report["capabilities"]["page.dialog"]["verification"], "source-audit")
        self.assertEqual(report["runtime_unexplained"], ["page.dialog"])

    def test_exercised_mapping_ignores_non_matrix_projections(self) -> None:
        self.assertEqual(exercised_capabilities("page.observe", {"projection": "dialogs"}), [])
        self.assertEqual(exercised_capabilities("page.act", {"intent": {"kind": "test.crash"}}), ["page.termination"])


if __name__ == "__main__":
    unittest.main()
