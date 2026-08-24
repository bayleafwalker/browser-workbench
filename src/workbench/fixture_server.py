from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .util import repo_root, sha256_bytes

FIXTURE_ROOT = "examples/fixtures/site"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".bin": "application/octet-stream",
}
# Served as an attachment so the engine starts a real download instead of
# navigating to the file.
ATTACHMENT_SUFFIXES = {".bin"}


class FixtureServer:
    """Loopback-only static server for the pinned fixture site.

    The fixture is part of the denominator: a run is only comparable against
    another run if both saw the same bytes, so the served files are hashed and
    the digests travel with the evidence.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or repo_root() / FIXTURE_ROOT).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"fixture root is missing: {self.root}")
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.host = "127.0.0.1"
        self.port = 0

    def digests(self) -> dict[str, str]:
        return {
            path.relative_to(self.root).as_posix(): sha256_bytes(path.read_bytes())
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }

    def start(self) -> str:
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "browser-workbench-fixture/1"
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                relative = self.path.split("?", 1)[0].lstrip("/") or "index.html"
                target = (fixture.root / relative).resolve()
                # Path traversal is rejected outright; the fixture is a closed set.
                if not target.is_file() or fixture.root not in target.parents:
                    self.send_error(404)
                    return
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
                self.send_header("Content-Length", str(len(body)))
                if target.suffix in ATTACHMENT_SUFFIXES:
                    self.send_header(
                        "Content-Disposition", f'attachment; filename="{target.name}"'
                    )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer((self.host, 0), Handler)
        self.host, self.port = self.server.server_address[:2]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.base_url

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def identity(self) -> dict[str, Any]:
        return {"base_url": self.base_url, "root": FIXTURE_ROOT, "files": self.digests()}

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None

    def __enter__(self) -> "FixtureServer":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()
