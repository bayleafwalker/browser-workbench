from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from workbench.bridge import LoopbackBridge
from workbench.evidence import ArtifactStore
from workbench.errors import WorkbenchError
from workbench.mock_backend import MockBackend


class ProtocolTests(unittest.TestCase):
    def backend(self, directory: str) -> MockBackend:
        return MockBackend(ArtifactStore(Path(directory), "test"))

    def test_stale_target_is_rejected_before_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = self.backend(directory)
            page_id = backend.session_create({"client": {"id": "a"}})["page_id"]
            target = backend.page_observe({"page_id": page_id, "projection": "targets"})["data"]["targets"][0]
            backend.page_navigate({"page_id": page_id, "client_id": "a", "url": "https://fixture.invalid/new", "wait": "commit"})
            count = backend.backend_invocations
            with self.assertRaises(WorkbenchError) as context:
                backend.page_act({"page_id": page_id, "client_id": "a", "target": target, "intent": {"kind": "click"}})
            self.assertEqual(context.exception.code, "stale_target")
            self.assertEqual(backend.backend_invocations, count)

    def test_export_redacts_sensitive_keys_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = self.backend(directory)
            backend.session_create({"client": {"id": "a"}})
            descriptor = backend.session_export({"metadata": {"password": "not-for-output", "note": "Bearer credential"}})
            value = backend.store.read_json_ref(descriptor["artifact"])
            encoded = json.dumps(value)
            self.assertNotIn("not-for-output", encoded)
            self.assertNotIn("Bearer credential", encoded)
            self.assertGreaterEqual(descriptor["redaction"]["count"], 2)

    def test_unsupported_intent_is_rejected_before_backend_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = self.backend(directory)
            page_id = backend.session_create({"client": {"id": "a"}})["page_id"]
            count = backend.backend_invocations
            with self.assertRaises(WorkbenchError) as context:
                backend.page_act({"page_id": page_id, "client_id": "a", "intent": {"kind": "invent-success"}})
            self.assertEqual(context.exception.code, "capability_unsupported")
            self.assertEqual(backend.backend_invocations, count)
            self.assertFalse(any(event["kind"] == "action.accepted" for event in backend.log.events))

    def test_loopback_bridge_requires_bearer_and_never_binds_wildcard(self) -> None:
        bridge = LoopbackBridge(lambda method, params: {"method": method, "params": params}, token="test-token")
        host, port = bridge.bind()
        self.assertEqual(host, "127.0.0.1")
        thread = threading.Thread(target=bridge.server.handle_request, daemon=True)  # type: ignore[union-attr]
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/dispatch",
            data=b'{"method":"session.create","params":{}}',
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 401)
        thread.join(timeout=2)
        bridge.close()


if __name__ == "__main__":
    unittest.main()
