from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .errors import WorkbenchError


MAX_REQUEST_BYTES = 1024 * 1024


class LoopbackBridge:
    """Authenticated loopback-only JSON bridge for a single backend dispatcher."""

    def __init__(self, dispatch: Callable[[str, dict[str, Any]], dict[str, Any]], token: str | None = None):
        self.dispatch = dispatch
        self.token = token or secrets.token_urlsafe(32)
        self.server: ThreadingHTTPServer | None = None

    def bind(self, port: int = 0) -> tuple[str, int]:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "browser-workbench-bridge/1"

            def log_message(self, format: str, *args: object) -> None:
                return

            def _send(self, status: int, value: dict[str, Any]) -> None:
                payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/dispatch":
                    self._send(404, {"ok": False, "error": {"code": "not_found"}})
                    return
                if self.headers.get("Authorization") != f"Bearer {bridge.token}":
                    self._send(401, {"ok": False, "error": {"code": "unauthorized"}})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length < 1 or length > MAX_REQUEST_BYTES:
                    self._send(413, {"ok": False, "error": {"code": "request_too_large"}})
                    return
                try:
                    request = json.loads(self.rfile.read(length))
                    result = bridge.dispatch(request["method"], request.get("params", {}))
                    self._send(200, {"ok": True, "id": request.get("id"), "result": result})
                except WorkbenchError as error:
                    self._send(400, {"ok": False, "error": error.as_dict()})
                except (json.JSONDecodeError, KeyError, TypeError) as error:
                    self._send(
                        400,
                        {"ok": False, "error": {"code": "invalid_request", "message": str(error)}},
                    )

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        host, bound_port = self.server.server_address[:2]
        return str(host), int(bound_port)

    def close(self) -> None:
        if self.server:
            self.server.server_close()
            self.server = None
