from __future__ import annotations

import unittest

from workbench.capabilities import capability_report, require_capabilities
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


if __name__ == "__main__":
    unittest.main()
