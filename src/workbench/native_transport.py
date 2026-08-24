from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .errors import WorkbenchError

PROTOCOL_VERSION = 1
READY_TIMEOUT_S = 30.0
SHUTDOWN_GRACE_S = 10.0
MAX_FRAME_BYTES = 1024 * 1024


class AdapterExit(Exception):
    """The adapter process ended while the host still expected frames."""


class AdapterTransport:
    """Ordered bidirectional line-delimited JSON channel to a native adapter.

    Implements spec/NATIVE_ADAPTER_CONTRACT_V1.md. The transport enforces the
    contract rather than trusting it: ordinal continuity, one reply per seq,
    and reply order are checked on every frame, because a channel that silently
    drops an engine event would produce evidence that looks complete and is not.
    """

    def __init__(self, argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.process: subprocess.Popen[str] | None = None
        self.frames: queue.Queue[dict[str, Any] | AdapterExit] = queue.Queue()
        self.stderr_lines: list[str] = []
        self.identity: dict[str, Any] = {}
        self._seq = 0
        self._ordinal = 0
        self._readers: list[threading.Thread] = []
        self._deviations: list[dict[str, Any]] = []

    @property
    def deviations(self) -> list[dict[str, Any]]:
        return list(self._deviations)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> dict[str, Any]:
        environment = {**os.environ, **(self.env or {})}
        try:
            self.process = subprocess.Popen(
                self.argv,
                cwd=str(self.cwd),
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            raise WorkbenchError(
                "capability_blocked",
                "native adapter process could not be started",
                {"argv": self.argv, "detail": str(error)},
            ) from error

        self._readers = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for reader in self._readers:
            reader.start()

        try:
            ready = self._next_frame(READY_TIMEOUT_S)
        except WorkbenchError as error:
            # An adapter that never reaches `ready` never executed anything.
            # That is a blocked environment — no display, no GTK, a bad build —
            # not a failed execution, and the two must not be reported alike:
            # `blocked` says nothing was attempted, `failed` says something was
            # attempted and went wrong.
            if error.code in {"backend_failed", "deadline_exceeded"}:
                raise WorkbenchError(
                    "capability_blocked",
                    "the native adapter never became ready",
                    {
                        "argv": self.argv,
                        "detail": error.data.get("detail", error.message),
                        "stderr_tail": self.stderr_lines[-10:],
                    },
                ) from error
            raise
        if ready.get("type") != "ready":
            raise WorkbenchError(
                "backend_failed",
                "adapter did not announce readiness first",
                {"frame_type": ready.get("type")},
            )
        self.identity = dict(ready.get("identity", {}))
        return self.identity

    def close(self) -> dict[str, Any]:
        """Orderly teardown. Never claims a clean exit it did not observe."""
        outcome: dict[str, Any] = {"requested_shutdown": False, "exit_code": None, "killed": False}
        if self.process is None:
            return outcome
        if self.process.poll() is None:
            try:
                self.request("shutdown", {}, deadline_ms=int(SHUTDOWN_GRACE_S * 1000))
                outcome["requested_shutdown"] = True
            except (WorkbenchError, AdapterExit):
                # A shutdown that cannot be delivered is recorded, not retried.
                self._deviations.append(
                    {"kind": "adapter-shutdown-unacknowledged", "reason": "adapter did not reply to shutdown"}
                )
        try:
            outcome["exit_code"] = self.process.wait(timeout=SHUTDOWN_GRACE_S)
        except subprocess.TimeoutExpired:
            self.process.kill()
            outcome["exit_code"] = self.process.wait(timeout=SHUTDOWN_GRACE_S)
            outcome["killed"] = True
            self._deviations.append(
                {"kind": "adapter-killed", "reason": "adapter did not exit within the declared grace period"}
            )
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass
        return outcome

    # -- framing -----------------------------------------------------------

    def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            if len(line) > MAX_FRAME_BYTES:
                self.frames.put(AdapterExit("adapter frame exceeded the declared bound"))
                return
            try:
                self.frames.put(json.loads(line))
            except json.JSONDecodeError:
                self.frames.put(AdapterExit(f"adapter emitted a non-JSON line: {line[:200]}"))
                return
        self.frames.put(AdapterExit("adapter stdout closed"))

    def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            self.stderr_lines.append(line.rstrip("\n"))

    def _next_frame(self, timeout_s: float) -> dict[str, Any]:
        try:
            frame = self.frames.get(timeout=max(0.0, timeout_s))
        except queue.Empty as error:
            raise WorkbenchError(
                "deadline_exceeded",
                "adapter produced no frame before the deadline",
                {"timeout_s": timeout_s},
            ) from error
        if isinstance(frame, AdapterExit):
            raise WorkbenchError(
                "backend_failed",
                "native adapter ended unexpectedly",
                {"detail": str(frame), "stderr_tail": self.stderr_lines[-10:]},
            )
        if frame.get("v") != PROTOCOL_VERSION:
            raise WorkbenchError(
                "protocol_mismatch",
                "adapter frame declares an unknown transport version",
                {"observed": frame.get("v"), "expected": PROTOCOL_VERSION},
            )
        ordinal = frame.get("ordinal")
        if ordinal != self._ordinal + 1:
            raise WorkbenchError(
                "integrity_mismatch",
                "adapter frame ordinal is not contiguous",
                {"expected": self._ordinal + 1, "observed": ordinal},
            )
        self._ordinal = int(ordinal)
        return frame

    # -- operations --------------------------------------------------------

    def request(
        self,
        op: str,
        params: dict[str, Any],
        *,
        deadline_ms: int = 30000,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Send one request and consume frames until its reply. Never retries."""
        if self.process is None or self.process.stdin is None:
            raise WorkbenchError("backend_failed", "adapter transport is not running")
        self._seq += 1
        seq = self._seq
        frame = json.dumps(
            {"v": PROTOCOL_VERSION, "seq": seq, "op": op, "params": params},
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            self.process.stdin.write(frame + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise WorkbenchError(
                "backend_failed",
                "adapter channel closed while sending a request",
                {"op": op, "detail": str(error), "stderr_tail": self.stderr_lines[-10:]},
            ) from error

        expires = time.monotonic() + deadline_ms / 1000.0
        while True:
            received = self._next_frame(expires - time.monotonic())
            kind = received.get("type")
            if kind == "event":
                if on_event:
                    on_event(received)
                continue
            if kind != "reply":
                raise WorkbenchError(
                    "integrity_mismatch", "unexpected adapter frame type", {"type": kind}
                )
            if received.get("seq") != seq:
                raise WorkbenchError(
                    "integrity_mismatch",
                    "adapter replied out of request order",
                    {"expected_seq": seq, "observed_seq": received.get("seq")},
                )
            if not received.get("ok"):
                error = received.get("error") or {}
                raise WorkbenchError(
                    str(error.get("code", "backend_failed")),
                    str(error.get("message", "adapter rejected the operation"))[:512],
                    {"op": op, **(error.get("details") or {})},
                )
            return dict(received.get("result") or {})

    def pump_events(
        self, *, timeout_ms: int, on_event: Callable[[dict[str, Any]], None]
    ) -> bool:
        """Consume one pending event frame. Returns False when none arrived in time.

        A reply can never appear here: the host keeps at most one request in
        flight and has already consumed its reply.
        """
        try:
            frame = self._next_frame(timeout_ms / 1000.0)
        except WorkbenchError as error:
            if error.code == "deadline_exceeded":
                return False
            raise
        if frame.get("type") != "event":
            raise WorkbenchError(
                "integrity_mismatch",
                "adapter sent a non-event frame with no request in flight",
                {"type": frame.get("type")},
            )
        on_event(frame)
        return True
