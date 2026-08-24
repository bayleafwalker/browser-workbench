from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workbench.errors import WorkbenchError  # noqa: E402
from workbench.native_transport import AdapterTransport  # noqa: E402

FAKE_ADAPTER = r'''
import json, sys

ordinal = 0
mode = sys.argv[1] if len(sys.argv) > 1 else "well-behaved"

def send(frame):
    global ordinal
    ordinal += 1
    frame["v"] = 1
    frame["ordinal"] = ordinal if mode != "ordinal-gap" or frame.get("type") != "reply" else ordinal + 5
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()

send({"type": "ready", "identity": {"adapter": "fake", "engine": "0.0.0"}})
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    seq = request["seq"]
    op = request["op"]
    if op == "shutdown":
        send({"type": "reply", "seq": seq, "ok": True, "result": {}})
        break
    if op == "emit":
        send({"type": "event", "kind": "load-changed", "monotonic_ms": 3, "payload": {"phase": "started"}})
        send({"type": "event", "kind": "load-changed", "monotonic_ms": 9, "payload": {"phase": "finished"}})
        send({"type": "reply", "seq": seq, "ok": True, "result": {"emitted": 2}})
        continue
    if op == "unsupported":
        send({"type": "reply", "seq": seq, "ok": False,
              "error": {"code": "capability_unsupported", "message": "nope", "details": {"op": op}}})
        continue
    if op == "wrong-seq":
        send({"type": "reply", "seq": seq + 40, "ok": True, "result": {}})
        continue
    send({"type": "reply", "seq": seq, "ok": True, "result": {"op": op}})
'''


class NativeTransportTest(unittest.TestCase):
    def transport(self, mode: str = "well-behaved") -> AdapterTransport:
        return AdapterTransport([sys.executable, "-c", FAKE_ADAPTER, mode], cwd=ROOT)

    def test_ready_then_request_reply(self) -> None:
        transport = self.transport()
        identity = transport.start()
        self.assertEqual(identity["adapter"], "fake")
        self.assertEqual(transport.request("handshake", {})["op"], "handshake")
        outcome = transport.close()
        self.assertTrue(outcome["requested_shutdown"])
        self.assertEqual(outcome["exit_code"], 0)
        self.assertFalse(outcome["killed"])

    def test_events_are_delivered_before_the_reply(self) -> None:
        transport = self.transport()
        transport.start()
        seen: list[dict] = []
        result = transport.request("emit", {}, on_event=seen.append)
        self.assertEqual(result, {"emitted": 2})
        self.assertEqual([event["payload"]["phase"] for event in seen], ["started", "finished"])
        # Events and replies share one contiguous ordinal sequence.
        self.assertEqual([event["ordinal"] for event in seen], [2, 3])
        transport.close()

    def test_adapter_error_becomes_a_workbench_error(self) -> None:
        transport = self.transport()
        transport.start()
        with self.assertRaises(WorkbenchError) as caught:
            transport.request("unsupported", {})
        self.assertEqual(caught.exception.code, "capability_unsupported")
        transport.close()

    def test_out_of_order_reply_is_rejected(self) -> None:
        transport = self.transport()
        transport.start()
        with self.assertRaises(WorkbenchError) as caught:
            transport.request("wrong-seq", {})
        self.assertEqual(caught.exception.code, "integrity_mismatch")
        transport.close()

    def test_ordinal_gap_is_rejected(self) -> None:
        transport = self.transport("ordinal-gap")
        transport.start()
        with self.assertRaises(WorkbenchError) as caught:
            transport.request("handshake", {})
        self.assertEqual(caught.exception.code, "integrity_mismatch")
        transport.close()

    def test_missing_binary_is_blocked_not_mocked(self) -> None:
        transport = AdapterTransport([str(ROOT / "no-such-adapter")], cwd=ROOT)
        with self.assertRaises(WorkbenchError) as caught:
            transport.start()
        self.assertEqual(caught.exception.code, "capability_blocked")

    def test_adapter_crash_is_reported_as_backend_failure(self) -> None:
        crashing = 'import sys, json; sys.stdout.write(json.dumps({"v":1,"ordinal":1,"type":"ready","identity":{}})+"\\n"); sys.stdout.flush(); sys.exit(3)'
        transport = AdapterTransport([sys.executable, "-c", crashing], cwd=ROOT)
        transport.start()
        with self.assertRaises(WorkbenchError) as caught:
            transport.request("handshake", {})
        self.assertEqual(caught.exception.code, "backend_failed")
        transport.close()


class FixtureServerTest(unittest.TestCase):
    def test_fixture_serves_pinned_bytes(self) -> None:
        import urllib.request

        from workbench.fixture_server import FixtureServer

        with FixtureServer() as fixture:
            body = urllib.request.urlopen(fixture.base_url + "index.html").read()
            self.assertIn(b"deterministic-fixture-index", body)
            identity = fixture.identity()
            self.assertIn("index.html", identity["files"])
            self.assertEqual(len(identity["files"]["index.html"]), 64)


if __name__ == "__main__":
    unittest.main()
