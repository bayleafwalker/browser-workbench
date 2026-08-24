from __future__ import annotations

import base64
import copy
import json
import time
from pathlib import Path
from typing import Any

from .errors import WorkbenchError
from .events import EventLog
from .evidence import ArtifactStore
from .native_transport import AdapterTransport
from .redaction import redact
from .util import canonical_bytes, json_size, repo_root, sha256_bytes

WORKER_PACKAGE = "browser-workbench-webkitgtk-worker"
WORKER_BINARY = "browser-workbench-webkitgtk-worker"
HANDSHAKE_DEADLINE_MS = 30000
AWAIT_POLL_MS = 50

# Raw engine callback -> normalized protocol event. The adapter never performs
# this mapping; keeping it here is what makes the raw trace independently
# reviewable against the normalized one.
EVENT_KINDS = {
    "load-changed:started": "navigation.started",
    "load-changed:redirected": "navigation.redirected",
    "load-changed:committed": "navigation.committed",
    "load-changed:finished": "navigation.finished",
    "load-failed": "navigation.failed",
    "resource-load-started": "network.request",
    "resource-response": "network.response",
    "resource-failed": "network.failed",
    "script-dialog": "dialog.opened",
    "permission-request": "permission.requested",
    "file-chooser": "file_chooser.opened",
    "download-started": "download.started",
    "download-destination": "download.destination",
    "download-finished": "download.finished",
    "download-failed": "download.failed",
    "title-changed": "page.title_changed",
    "web-process-terminated": "page.terminated",
}


def worker_binary(root: Path | None = None) -> Path:
    root = root or repo_root()
    return root / "target" / "debug" / WORKER_BINARY


class WebKitGtkBackend:
    """Host-side WebKitGTK backend over the native adapter contract.

    Only the operations slice 1 evidences are implemented. Everything else
    reports `capability_unsupported` rather than degrading to injected
    JavaScript or to the mock, because a silent substitution is exactly the
    failure this project exists to avoid.
    """

    SUPPORTED_METHODS = {
        "session.create",
        "page.navigate",
        "page.observe",
        "page.await",
        "page.act",
        "session.export",
        "session.checkpoint",
        "page.tabs",
    }
    SUPPORTED_PROJECTIONS = {
        "state",
        "raw-events",
        "dom",
        "console",
        "network",
        "screenshot",
        "targets",
        "dialogs",
        "permissions",
        "downloads",
    }
    SUPPORTED_INTENTS = {
        "javascript",
        "click",
        "type",
        "dialog.resolve",
        "permission.resolve",
        "upload",
        "download.accept",
        "test.crash",
    }

    def __init__(self, store: ArtifactStore, variant: str = "stable-ephemeral", *, root: Path | None = None) -> None:
        if variant not in {"stable-ephemeral", "stable-persistent", "default"}:
            raise WorkbenchError("invalid_request", "unknown webkitgtk variant", {"variant": variant})
        self.store = store
        self.variant = variant
        self.root = root or repo_root()
        self.session_id = "session-0001"
        self.log = EventLog(self.session_id, provider="webkitgtk")
        self.transport: AdapterTransport | None = None
        self.identity: dict[str, Any] = {}
        self.page: dict[str, Any] | None = None
        self.pages: dict[str, dict[str, Any]] = {}
        self.active_page_id: str | None = None
        self.viewport: dict[str, Any] = {}
        self.dialogs: dict[str, dict[str, Any]] = {}
        self.permissions: dict[str, dict[str, Any]] = {}
        self.file_choosers: dict[str, dict[str, Any]] = {}
        self.downloads: dict[str, dict[str, Any]] = {}
        self.checkpoint_parent: str | None = None
        self.quarantine: Path | None = None
        self._checkpoint_counter = 0
        self.writer_id: str | None = None
        self.lease_epoch = 0
        self.lease_id: str | None = None
        self.backend_invocations = 0
        self._observation_counter = 0
        self._receipt_counter = 0
        self._action_counter = 0
        self._screenshot_counter = 0
        self._export_counter = 0
        self._deviations: list[dict[str, Any]] = []

    # -- connection --------------------------------------------------------

    def connect(self) -> dict[str, Any]:
        """Start the adapter and verify its identity. Failure is blocked, not mocked."""
        binary = worker_binary(self.root)
        if not binary.is_file():
            raise WorkbenchError(
                "capability_blocked",
                "the native adapter binary has not been built",
                {"expected": str(binary.relative_to(self.root)), "package": WORKER_PACKAGE},
            )
        transport = AdapterTransport([str(binary)], cwd=self.root)
        self.identity = transport.start()
        self.transport = transport
        handshake = transport.request("handshake", {}, deadline_ms=HANDSHAKE_DEADLINE_MS)
        self.identity = dict(handshake.get("identity") or self.identity)
        self.log.capture_raw("adapter.ready", copy.deepcopy(self.identity))
        self.log.emit("adapter.connected", copy.deepcopy(self.identity), source="host")
        return self.identity

    def close(self) -> dict[str, Any]:
        if self.transport is None:
            return {}
        outcome = self.transport.close()
        self._deviations.extend(self.transport.deviations)
        self.log.emit("adapter.closed", copy.deepcopy(outcome), source="host")
        stderr = "\n".join(self.transport.stderr_lines)
        if stderr:
            self.store.write_text("traces/adapter-stderr.log", stderr + "\n", "raw")
        self.transport = None
        return outcome

    @property
    def deviations(self) -> list[dict[str, Any]]:
        return list(self._deviations)

    # -- event ingestion ---------------------------------------------------

    def _ingest(self, frame: dict[str, Any]) -> None:
        """Record one raw engine callback, then its normalized projection."""
        kind = str(frame.get("kind", "unknown"))
        payload = frame.get("payload") or {}
        monotonic = int(frame.get("monotonic_ms", self.log.monotonic_ms))
        if monotonic > self.log.monotonic_ms:
            self.log.advance(monotonic - self.log.monotonic_ms)

        page_id = frame.get("page_id") or (self.page and self.page["page_id"])
        raw_id = self.log.capture_raw(kind, copy.deepcopy(payload), page_id=page_id)
        if kind == "script-message":
            self._ingest_script_message(payload, raw_id)
            return

        self._register_pending(kind, payload)

        lookup = kind
        if kind == "load-changed":
            lookup = f"load-changed:{payload.get('phase', 'unknown')}"
        normalized_kind = EVENT_KINDS.get(lookup)
        if normalized_kind is None:
            # An unmapped callback is retained raw and surfaced, never dropped.
            self._deviations.append({"kind": "unmapped-engine-event", "raw_kind": lookup})
            return

        page = self.pages.get(page_id) if page_id else None
        self._apply(lookup, payload, page)
        self.log.emit(
            normalized_kind,
            copy.deepcopy(payload),
            page_id=page_id,
            generation=page and page["generation"],
            source="engine",
            raw_refs=[raw_id],
        )

    def _register_pending(self, kind: str, payload: dict[str, Any]) -> None:
        """Record a browser-owned request that is now waiting on the host.

        The engine holds each of these open until a decision is delivered, so
        the host has to know the token exists before it can decide anything.
        """
        token = payload.get("token")
        if not token:
            return
        if kind == "script-dialog":
            self.dialogs[token] = {
                "token": token,
                "kind": "dialog",
                "dialog_type": payload.get("dialog_type"),
                "message": payload.get("message"),
                "status": "pending",
                "default": "deny",
            }
        elif kind == "permission-request":
            self.permissions[token] = {
                "token": token,
                "kind": payload.get("request_type"),
                "status": "pending",
                "default": "deny",
            }
        elif kind == "file-chooser":
            self.file_choosers[token] = {
                "token": token,
                "selects_multiple": payload.get("selects_multiple"),
                "status": "pending",
                "default": "cancel",
            }
        elif kind == "download-started":
            self.downloads[token] = {
                "token": token,
                "download_id": token,
                "url": payload.get("url"),
                "status": "pending",
                "destination": None,
            }
        elif kind == "download-finished" and token in self.downloads:
            self.downloads[token].update(
                {
                    "status": "completed",
                    "destination": payload.get("destination"),
                    "received_bytes": payload.get("received_bytes"),
                }
            )
        elif kind == "download-failed" and token in self.downloads:
            self.downloads[token].update({"status": "failed", "error": payload.get("error")})

    def _apply(self, lookup: str, payload: dict[str, Any], page: dict[str, Any] | None) -> None:
        """Fold an engine callback into the host's page projection."""
        if page is None:
            return
        if lookup == "load-changed:started":
            page["load_state"] = "loading"
        elif lookup == "load-changed:committed":
            page["generation"] += 1
            page["url"] = payload.get("url") or page["url"]
        elif lookup == "load-changed:finished":
            page["load_state"] = "idle"
            page["last_navigation_outcome"] = "success"
            page["url"] = payload.get("url") or page["url"]
            if payload.get("title"):
                page["title"] = payload["title"]
        elif lookup == "load-failed":
            page["load_state"] = "idle"
            page["last_navigation_outcome"] = "failed"
        elif lookup == "title-changed":
            if payload.get("title"):
                page["title"] = payload["title"]
        elif lookup == "web-process-terminated":
            page["lifecycle"] = "terminated"
            page["load_state"] = "idle"

    def _ingest_script_message(self, payload: dict[str, Any], raw_id: str) -> None:
        """Normalize one injected bridge message.

        The bridge posts a JSON string, so the engine hands back a JSON-encoded
        string: decode twice, and treat anything unparseable as a deviation
        rather than guessing at its shape.
        """
        decoded: Any = payload.get("json")
        for _ in range(2):
            if not isinstance(decoded, str):
                break
            try:
                decoded = json.loads(decoded)
            except json.JSONDecodeError:
                break
        if not isinstance(decoded, dict) or decoded.get("kind") != "console":
            self._deviations.append({"kind": "unparsed-script-message", "raw_id": raw_id})
            return
        self.log.emit(
            "console.message",
            {"level": decoded.get("level"), "text": decoded.get("text")},
            page_id=self.page and self.page["page_id"],
            generation=self.page and self.page["generation"],
            # Injected, not engine: a page can see and defeat this bridge.
            source="injected",
            raw_refs=[raw_id],
        )

    def _evaluate(self, script: str, *, deadline_ms: int = 30000) -> Any:
        """Run declared JavaScript and decode the engine's JSON projection."""
        result = self._request(
            "page.evaluate",
            {"script": script, "page_id": self.active_page_id},
            deadline_ms=deadline_ms,
        )
        raw = result.get("json")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def _request(self, op: str, params: dict[str, Any], *, deadline_ms: int = 30000) -> dict[str, Any]:
        if self.transport is None:
            raise WorkbenchError("backend_failed", "adapter transport is not connected")
        self.backend_invocations += 1
        return self.transport.request(op, params, deadline_ms=deadline_ms, on_event=self._ingest)

    def _require_writer(self, client_id: str | None) -> None:
        if self.writer_id is None:
            raise WorkbenchError("lease_fenced", "session has no active writer")
        if client_id and client_id != self.writer_id:
            raise WorkbenchError(
                "lease_conflict",
                "client does not hold the single-writer lease",
                {"holder": self.writer_id, "client": client_id, "lease_epoch": self.lease_epoch},
            )

    def _active_page(self, page_id: str | None = None) -> dict[str, Any]:
        page_id = page_id or self.active_page_id
        page = self.pages.get(page_id) if page_id else None
        if page is None:
            raise WorkbenchError("page_not_found", "page does not exist", {"page_id": page_id})
        return page

    def _new_page_record(self, page_id: str, generation: int = 1) -> dict[str, Any]:
        page = {
            "page_id": page_id,
            "generation": generation,
            "lifecycle": "open",
            "url": "about:blank",
            "title": "",
            "load_state": "idle",
            "last_navigation_outcome": None,
        }
        self.pages[page_id] = page
        self.active_page_id = page_id
        self.page = page
        return page

    # -- protocol operations ----------------------------------------------

    def session_create(self, params: dict[str, Any]) -> dict[str, Any]:
        client = params.get("client", {})
        client_id = client.get("id", "anonymous")
        if self.writer_id and self.writer_id != client_id:
            raise WorkbenchError(
                "lease_conflict",
                "session already has a writer",
                {"holder": self.writer_id, "client": client_id},
            )
        profile = params.get("profile", {"mode": "ephemeral", "name": "default"})
        if profile.get("mode") not in {"ephemeral", "persistent"}:
            raise WorkbenchError("invalid_request", "unknown profile mode")
        if profile.get("mode") == "persistent":
            raise WorkbenchError(
                "capability_unsupported",
                "persistent profiles are not wired in this slice",
                {"profile": profile},
            )
        resume = params.get("resume_checkpoint")
        checkpoint: dict[str, Any] | None = None
        if resume:
            if not isinstance(resume, dict):
                raise WorkbenchError(
                    "invalid_request", "resume_checkpoint must be an artifact descriptor"
                )
            checkpoint = self.store.read_json_ref(resume)

        viewport = params.get("viewport", {"width": 1280, "height": 800})
        self.viewport = viewport
        self.quarantine = self.store.root / "downloads"
        self.quarantine.mkdir(parents=True, exist_ok=True)
        result = self._request(
            "session.open",
            {
                "width": int(viewport.get("width", 1280)),
                "height": int(viewport.get("height", 800)),
                "quarantine_dir": str(self.quarantine),
            },
        )
        page = self._new_page_record(str(result["page_id"]))

        if checkpoint:
            # Restoring is a real navigation when the checkpoint held one, so
            # the successor observes the engine reaching that state rather than
            # being told it is already there.
            self._restore(checkpoint, page)
            self.lease_epoch = int(checkpoint["lease"]["epoch"]) + 1
            self.checkpoint_parent = checkpoint["checkpoint_id"]
        else:
            self.lease_epoch = 1
        self.writer_id = client_id
        self.lease_id = f"lease-{self.lease_epoch:04d}"
        event = self.log.emit(
            "session.created",
            {
                "profile": profile,
                "writer_id": client_id,
                "lease_epoch": self.lease_epoch,
                "engine": self.identity,
            },
            source="host",
        )
        return {
            "session_id": self.session_id,
            "page_id": self.page["page_id"],
            "profile": profile,
            "lease": {
                "lease_id": self.lease_id,
                "lease_epoch": self.lease_epoch,
                "writer_id": self.writer_id,
                "mode": "single-writer",
            },
            "backend": {"kind": "webkitgtk", "variant": self.variant, "identity": self.identity},
            "resumed_from": self.checkpoint_parent,
            "event_id": event["event_id"],
        }

    def _restore(self, checkpoint: dict[str, Any], page: dict[str, Any]) -> None:
        """Bring a fresh session up to a checkpoint's canonical page state."""
        saved_pages: dict[str, Any] = checkpoint["state"]["pages"]
        saved = saved_pages.get(checkpoint["state"]["active_page_id"]) or next(
            iter(saved_pages.values())
        )
        url = saved.get("url") or "about:blank"
        if url != "about:blank":
            self.page_navigate({"page_id": page["page_id"], "client_id": None, "url": url})
            self.page_await(
                {
                    "page_id": page["page_id"],
                    "conditions": [{"kind": "load_state", "equals": "idle"}],
                    "deadline_ms": 30000,
                }
            )
        # A restored page is a new generation of the same page object.
        page["generation"] = int(saved.get("generation", 1)) + 1
        page["title"] = saved.get("title", page["title"])
        page["lifecycle"] = "open"
        page["load_state"] = "idle"
        self.log.emit(
            "session.restored",
            {"checkpoint_id": checkpoint["checkpoint_id"], "generation": page["generation"]},
            page_id=page["page_id"],
            generation=page["generation"],
            source="host",
        )

    def session_checkpoint(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_writer(params.get("client_id"))
        self._checkpoint_counter += 1
        checkpoint_id = f"checkpoint-{self._checkpoint_counter:04d}"
        checkpoint = {
            "schema_version": "browser-workbench.checkpoint/v1",
            "checkpoint_id": checkpoint_id,
            "session_id": self.session_id,
            "parent": self.checkpoint_parent,
            "event_cursor": self.log.cursor,
            "state": {
                "active_page_id": self.active_page_id,
                "pages": copy.deepcopy(self.pages),
            },
            "lease": {"id": self.lease_id, "epoch": self.lease_epoch, "writer_id": self.writer_id},
            "backend": {"kind": "webkitgtk", "variant": self.variant, "identity": self.identity},
            # A checkpoint records state. It is not an approval token.
            "approval": None,
        }
        artifact = self.store.write_json(
            f"checkpoints/{checkpoint_id}.json", checkpoint, "normalized"
        )
        released = bool(params.get("release_lease", False))
        if released:
            prior_writer = self.writer_id
            self.writer_id = None
            self.lease_id = None
            self.log.emit(
                "session.handover_ready",
                {
                    "checkpoint_id": checkpoint_id,
                    "prior_writer": prior_writer,
                    "lease_epoch": self.lease_epoch,
                },
                source="host",
            )
        return {
            "checkpoint_id": checkpoint_id,
            "artifact": artifact,
            "released_lease": released,
            "approval": None,
        }

    def page_tabs(self, params: dict[str, Any]) -> dict[str, Any]:
        """Open, list, or close host-owned tabs."""
        action = params.get("action", "list")
        if action == "list":
            return {"pages": self._request("page.list", {})["pages"], "count": len(self.pages)}
        self._require_writer(params.get("client_id"))
        if action == "new":
            result = self._request("page.new", {})
            page = self._new_page_record(str(result["page_id"]))
            self.log.emit(
                "page.opened", {"page_id": page["page_id"]}, page_id=page["page_id"], source="host"
            )
            return {"page_id": page["page_id"], "count": len(self.pages)}
        if action == "close":
            page = self._active_page(params.get("page_id"))
            self._request("page.close", {"page_id": page["page_id"]})
            self.pages.pop(page["page_id"], None)
            self.active_page_id = next(iter(self.pages), None)
            self.page = self.pages.get(self.active_page_id) if self.active_page_id else None
            return {"closed": page["page_id"], "count": len(self.pages)}
        raise WorkbenchError("invalid_request", "unknown tab action", {"action": action})

    def page_navigate(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("client_id") is not None or self.writer_id:
            self._require_writer(params.get("client_id"))
        page = self._active_page(params.get("page_id"))
        if page["lifecycle"] != "open":
            raise WorkbenchError("backend_rejected", "page is not open")
        url = params["url"]
        before = sha256_bytes(canonical_bytes(page))
        cursor = self.log.cursor
        # The host marks its own request before issuing it. Without this a wait
        # for an idle page can be satisfied by the idle state the page was
        # already in, before the engine has even started the navigation. The
        # engine's events still decide when it becomes idle again.
        page["load_state"] = "loading"
        page["last_navigation_outcome"] = None
        try:
            result = self._request("page.navigate", {"page_id": page["page_id"], "url": url})
        except WorkbenchError:
            page["load_state"] = "idle"
            raise
        caused = [event["event_id"] for event in self.log.since(cursor)]
        return {
            "accepted": bool(result.get("accepted")),
            "navigation_id": result.get("navigation_id"),
            "caused_event_ids": caused,
            "receipt_id": f"receipt-{result.get('navigation_id')}",
            "provider": "engine",
            "state_before": before,
            "state_after": sha256_bytes(canonical_bytes(page)),
        }

    def page_await(self, params: dict[str, Any]) -> dict[str, Any]:
        """Host-side, event-driven wait over the ordered adapter stream.

        The host blocks on the channel rather than sampling the engine, so the
        events the conditions are judged against are the same ones the evidence
        keeps.
        """
        page = self._active_page(params.get("page_id"))
        conditions = params.get("conditions", [])
        if not conditions:
            raise WorkbenchError("invalid_request", "await requires at least one condition")
        deadline_ms = int(params.get("deadline_ms", 30000))
        expires = time.monotonic() + deadline_ms / 1000.0

        while not all(self._condition(page, condition) for condition in conditions):
            remaining_ms = int((expires - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                unsatisfied = [c for c in conditions if not self._condition(page, c)]
                raise WorkbenchError(
                    "deadline_exceeded",
                    "await deadline elapsed",
                    {"unsatisfied": unsatisfied, "event_cursor": self.log.cursor},
                )
            if self.transport is None:
                raise WorkbenchError("backend_failed", "adapter transport is not connected")
            self.transport.pump_events(
                timeout_ms=min(AWAIT_POLL_MS, remaining_ms), on_event=self._ingest
            )
        return {
            "satisfied": True,
            "conditions": conditions,
            "event_cursor": self.log.cursor,
            "monotonic_ms": self.log.monotonic_ms,
        }

    def _condition(self, page: dict[str, Any], condition: dict[str, Any]) -> bool:
        kind = condition.get("kind")
        expected = condition.get("equals")
        if kind == "load_state":
            return page["load_state"] == expected
        if kind == "url":
            return page["url"] == expected
        if kind == "title":
            return page["title"] == expected
        if kind == "generation":
            return page["generation"] == expected
        if kind == "event_kind":
            return any(event["kind"] == expected for event in self.log.events)
        raise WorkbenchError("invalid_request", f"unknown await condition: {kind}")

    def await_pending(self, *, dialogs: int = 0, permissions: int = 0, deadline_ms: int = 15000) -> None:
        """Wait for the engine to raise the browser-owned requests we expect.

        A prompt exists when the engine says so, not when the page's script
        claims to have asked for one.
        """
        deadline = time.monotonic() + deadline_ms / 1000.0
        while time.monotonic() < deadline:
            if len(self.dialogs) >= dialogs and len(self.permissions) >= permissions:
                return
            if self.transport is None:
                break
            self.transport.pump_events(timeout_ms=AWAIT_POLL_MS, on_event=self._ingest)
        raise WorkbenchError(
            "deadline_exceeded",
            "the engine did not raise the expected browser-owned requests",
            {
                "expected": {"dialogs": dialogs, "permissions": permissions},
                "observed": {"dialogs": len(self.dialogs), "permissions": len(self.permissions)},
            },
        )

    def await_download(self, *, deadline_ms: int = 30000) -> str:
        deadline = time.monotonic() + deadline_ms / 1000.0
        while time.monotonic() < deadline:
            if self.downloads:
                return sorted(self.downloads)[0]
            if self.transport is None:
                break
            self.transport.pump_events(timeout_ms=AWAIT_POLL_MS, on_event=self._ingest)
        raise WorkbenchError("deadline_exceeded", "the engine never started a download")


    def page_observe(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._active_page(params.get("page_id"))
        projections = params.get("projection", ["state"])
        if isinstance(projections, str):
            projections = [projections]
        unsupported = [name for name in projections if name not in self.SUPPORTED_PROJECTIONS]
        if unsupported:
            raise WorkbenchError(
                "capability_unsupported",
                "observation projection is not wired in this slice",
                {"projections": unsupported, "supported": sorted(self.SUPPORTED_PROJECTIONS)},
            )
        since_event = int(params.get("since_event", 0))
        max_bytes = int(params.get("max_bytes", 32768))
        if max_bytes < 512:
            raise WorkbenchError("invalid_request", "max_bytes must be at least 512")

        data: dict[str, Any] = {}
        if "dom" in projections:
            html = self._evaluate("document.documentElement.outerHTML")
            if not isinstance(html, str):
                raise WorkbenchError(
                    "backend_rejected",
                    "the page did not return serialized DOM",
                    {"observed_type": type(html).__name__},
                )
            data["dom"] = {"html": html, "sha256": sha256_bytes(html.encode())}
        if "console" in projections:
            data["console"] = [
                event for event in self.log.since(since_event) if event["kind"] == "console.message"
            ]
        if "network" in projections:
            data["network"] = [
                event
                for event in self.log.since(since_event)
                if event["kind"].startswith("network.")
            ]
        if "screenshot" in projections:
            data["screenshot"] = self._screenshot(page)
        if "targets" in projections:
            data["targets"] = self._targets(page)
        if "dialogs" in projections:
            data["dialogs"] = list(copy.deepcopy(self.dialogs).values())
        if "permissions" in projections:
            data["permissions"] = list(copy.deepcopy(self.permissions).values())
        if "downloads" in projections:
            data["downloads"] = list(copy.deepcopy(self.downloads).values())
        if "state" in projections:
            engine = self._request("page.observe", {"page_id": page["page_id"]})
            # Engine truth wins over the folded projection; a divergence is a finding.
            page["url"] = engine.get("url") or page["url"]
            page["title"] = engine.get("title") or page["title"]
            page["load_state"] = "loading" if engine.get("is_loading") else page["load_state"]
            data["state"] = {**copy.deepcopy(page), "engine": engine}
        if "raw-events" in projections:
            data["raw-events"] = [record for record in self.log.raw if record["ordinal"] > since_event]

        self._observation_counter += 1
        response = {
            "page_id": page["page_id"],
            "generation": page["generation"],
            "since_event": since_event,
            "next_event": self.log.cursor,
            "max_bytes": max_bytes,
            "lossy": False,
            "returned_projections": projections,
            "omitted": {},
            "raw_ref": None,
            "provider": "engine",
            "data": data,
        }
        if json_size(response) <= max_bytes:
            return response

        raw = self.store.write_json(
            f"observations/observation-{self._observation_counter:04d}.json", response, "raw"
        )
        compact: dict[str, Any] = {}
        omitted: dict[str, int] = {}
        for name, value in data.items():
            if name == "state":
                compact[name] = value
            elif isinstance(value, list):
                compact[name] = value[:1]
                omitted[name] = max(0, len(value) - 1)
            else:
                compact[name] = {"omitted": True, "type": type(value).__name__}
                omitted[name] = 1
        response.update({"lossy": True, "omitted": omitted, "raw_ref": raw["artifact_ref"], "data": compact})
        if json_size(response) > max_bytes:
            # Last resort: keep the mandatory envelope and say what was dropped.
            # The full observation is already retained as a raw artifact.
            response["data"] = {
                "state": {"page_id": page["page_id"], "generation": page["generation"]}
            }
            response["omitted"] = {name: 1 for name in projections}
        if json_size(response) > max_bytes:
            raise WorkbenchError(
                "invalid_request",
                "max_bytes cannot hold the mandatory observation envelope",
                {"minimum_observed": json_size(response)},
            )
        return response

    # Generation-scoped target enumeration. WebKitGTK exposes no accessibility
    # target API to the host, so targets are discovered by injected script and
    # declared `provider: injected` accordingly.
    TARGET_SCRIPT = """
(() => {
  const selector = 'a[href], button, input, select, textarea, [contenteditable="true"]';
  return Array.from(document.querySelectorAll(selector)).map((element, index) => {
    const id = 'target-' + (index + 1);
    element.setAttribute('data-wb-target', id);
    const tag = element.tagName.toLowerCase();
    const type = (element.getAttribute('type') || '').toLowerCase();
    const role = element.getAttribute('role')
      || (tag === 'a' ? 'link'
      : tag === 'button' ? 'button'
      : (tag === 'input' && type === 'file') ? 'file'
      : (tag === 'input' || tag === 'textarea') ? 'textbox'
      : tag);
    const name = (element.getAttribute('aria-label') || element.textContent
      || element.value || element.id || '').trim().slice(0, 80);
    return {
      target_id: id,
      role: role,
      name: name,
      actions: role === 'textbox' ? ['type', 'click'] : ['click'],
    };
  });
})()
"""

    def _targets(self, page: dict[str, Any]) -> list[dict[str, Any]]:
        found = self._evaluate(self.TARGET_SCRIPT)
        if not isinstance(found, list):
            raise WorkbenchError(
                "backend_rejected",
                "target enumeration did not return a list",
                {"observed_type": type(found).__name__},
            )
        # The host stamps the generation: a target is only valid for the
        # document it was read from.
        return [{**item, "generation": page["generation"]} for item in found]

    def _check_target(
        self, page: dict[str, Any], target: dict[str, Any] | None, action: str
    ) -> dict[str, Any]:
        if not target:
            raise WorkbenchError("invalid_request", f"{action} requires a target")
        if int(target.get("generation", -1)) != page["generation"]:
            # Rejected before the backend is invoked at all: a stale target
            # must never reach the engine.
            raise WorkbenchError(
                "stale_target",
                "target belongs to an earlier generation",
                {
                    "target_id": target.get("target_id"),
                    "target_generation": target.get("generation"),
                    "page_generation": page["generation"],
                },
            )
        if action not in target.get("actions", []):
            raise WorkbenchError(
                "capability_unsupported",
                "target does not declare this action",
                {"target_id": target.get("target_id"), "action": action},
            )
        return target

    def _screenshot(self, page: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            "page.snapshot",
            {"region": "full-document", "page_id": page["page_id"]},
            deadline_ms=60000,
        )
        png = base64.b64decode(result["png_base64"])
        if len(png) != int(result.get("bytes", len(png))):
            raise WorkbenchError(
                "integrity_mismatch",
                "snapshot byte count does not match the decoded image",
                {"declared": result.get("bytes"), "decoded": len(png)},
            )
        self._screenshot_counter += 1
        descriptor = self.store.write_bytes(
            f"screenshots/{page['page_id']}-g{page['generation']}-{self._screenshot_counter:02d}.png",
            png,
            "raw",
            media_type="image/png",
        )
        # A full-document snapshot may legitimately be taller than the
        # viewport, but a narrower one means the engine never laid out at the
        # declared width. That is recorded, not quietly accepted.
        declared_width = self.viewport.get("width")
        observed_width = result.get("width")
        if declared_width and observed_width and observed_width != declared_width:
            self._deviations.append(
                {
                    "kind": "viewport-width-divergence",
                    "declared": declared_width,
                    "observed": observed_width,
                }
            )
        return {
            **descriptor,
            "width": observed_width,
            "height": result.get("height"),
            "declared_viewport": copy.deepcopy(self.viewport),
            "region": result.get("region"),
            "provider": "engine",
        }

    CLICK_SCRIPT = """
(() => {
  const element = document.querySelector('[data-wb-target="%s"]');
  if (!element) { return {ok: false, reason: 'target is no longer in the document'}; }
  element.click();
  return {ok: true, tag: element.tagName.toLowerCase()};
})()
"""

    TYPE_SCRIPT = """
(() => {
  const element = document.querySelector('[data-wb-target="%s"]');
  if (!element) { return {ok: false, reason: 'target is no longer in the document'}; }
  element.focus();
  element.value = %s;
  element.dispatchEvent(new Event('input', {bubbles: true}));
  element.dispatchEvent(new Event('change', {bubbles: true}));
  return {ok: true, value: element.value};
})()
"""

    def page_act(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute one declared intent, exactly once, with a causal receipt."""
        self._require_writer(params.get("client_id"))
        page = self._active_page(params.get("page_id"))
        intent = params.get("intent") or {}
        kind = intent.get("kind")
        if kind not in self.SUPPORTED_INTENTS:
            raise WorkbenchError(
                "capability_unsupported",
                "intent family is not wired on this backend",
                {"intent": kind, "supported": sorted(self.SUPPORTED_INTENTS)},
            )
        self._check_preconditions(page, params.get("preconditions") or {})

        # Everything above this line runs before the backend is invoked, so a
        # rejected precondition or stale target never reaches the engine.
        handlers = {
            "javascript": self._act_javascript,
            "click": self._act_click,
            "type": self._act_type,
            "dialog.resolve": self._act_dialog,
            "permission.resolve": self._act_permission,
            "upload": self._act_upload,
            "download.accept": self._act_download,
            "test.crash": self._act_crash,
        }
        self._action_counter += 1
        action_id = f"action-{self._action_counter:04d}"
        before = sha256_bytes(canonical_bytes(page))
        cursor = self.log.cursor
        provider, effects = handlers[str(kind)](page, params, intent)
        self._drain_effects()
        caused = [event["event_id"] for event in self.log.since(cursor)]

        self._receipt_counter += 1
        return {
            "receipt_id": f"receipt-{self._receipt_counter:04d}",
            "action_id": action_id,
            "attempted": True,
            "accepted": True,
            "executed": True,
            # Verified means an effect or a causal event was actually observed,
            # not merely that the call did not raise.
            "verified": bool(caused) or bool(effects),
            "provider": provider,
            "caused_event_ids": caused,
            "effects": effects,
            "state_before": before,
            "state_after": sha256_bytes(canonical_bytes(page)),
        }

    def _act_javascript(
        self, page: dict[str, Any], params: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        value = self._evaluate(str(intent.get("value") or ""))
        return "engine", [{"kind": "javascript.result", "value": value}]

    def _act_click(
        self, page: dict[str, Any], params: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        target = self._check_target(page, params.get("target"), "click")
        result = self._evaluate(self.CLICK_SCRIPT % target["target_id"])
        if not isinstance(result, dict) or not result.get("ok"):
            raise WorkbenchError(
                "backend_rejected",
                "click did not reach a live element",
                {"target_id": target["target_id"], "detail": (result or {}).get("reason")},
            )
        # Injected, not engine: synthesized DOM activation, not a real pointer.
        return "injected", [{"kind": "click", "target_id": target["target_id"]}]

    def _act_type(
        self, page: dict[str, Any], params: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        target = self._check_target(page, params.get("target"), "type")
        text = json.dumps(str(intent.get("value") or ""))
        result = self._evaluate(self.TYPE_SCRIPT % (target["target_id"], text))
        if not isinstance(result, dict) or not result.get("ok"):
            raise WorkbenchError(
                "backend_rejected",
                "type did not reach a live element",
                {"target_id": target["target_id"], "detail": (result or {}).get("reason")},
            )
        return "injected", [
            {"kind": "type", "target_id": target["target_id"], "value": result.get("value")}
        ]

    def _decide(self, registry: dict[str, dict[str, Any]], intent: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
        """Resolve one browser-owned request. A token is consumed exactly once."""
        token = intent.get("decision_token")
        record = registry.get(str(token))
        if record is None or record.get("status") != "pending":
            raise WorkbenchError(
                "precondition_failed",
                "decision token is unknown or already resolved",
                {"decision_token": token},
            )
        decision = str(intent.get("decision") or record["default"])
        if decision not in allowed:
            raise WorkbenchError(
                "invalid_request", "unknown decision", {"decision": decision}
            )
        return {"token": str(token), "record": record, "decision": decision}

    def _act_dialog(
        self, page: dict[str, Any], params: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        chosen = self._decide(self.dialogs, intent, {"accept", "dismiss"})
        self._request(
            "page.decide",
            {
                "token": chosen["token"],
                "decision": "accept" if chosen["decision"] == "accept" else "dismiss",
                "value": intent.get("value", ""),
            },
        )
        chosen["record"].update({"status": "resolved", "decision": chosen["decision"]})
        self.log.emit(
            "dialog.resolved",
            {"token": chosen["token"], "decision": chosen["decision"]},
            page_id=page["page_id"],
            generation=page["generation"],
            source="host",
        )
        return "engine", [{"kind": "dialog.decision", "decision": chosen["decision"], "token": chosen["token"]}]

    def _act_permission(
        self, page: dict[str, Any], params: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        chosen = self._decide(self.permissions, intent, {"allow", "deny"})
        self._request("page.decide", {"token": chosen["token"], "decision": chosen["decision"]})
        chosen["record"].update({"status": "resolved", "decision": chosen["decision"]})
        self.log.emit(
            "permission.resolved",
            {"token": chosen["token"], "decision": chosen["decision"]},
            page_id=page["page_id"],
            generation=page["generation"],
            source="host",
        )
        return "engine", [
            {"kind": "permission.decision", "decision": chosen["decision"], "token": chosen["token"]}
        ]

    def _act_upload(
        self, page: dict[str, Any], params: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        path = Path(str(intent.get("path", ""))).resolve()
        allowed_root = (self.root / "examples" / "fixtures").resolve()
        # The declared fixture tree is the whole allowlist. Anything else is
        # refused before the file chooser is ever opened.
        if allowed_root not in path.parents or not path.is_file():
            raise WorkbenchError(
                "precondition_failed",
                "upload path is outside the declared fixture tree",
                {"path": str(path), "allowed_root": str(allowed_root)},
            )
        target = self._check_target(page, params.get("target"), "click")
        pending_before = set(self.file_choosers)
        self._evaluate(self.CLICK_SCRIPT % target["target_id"])
        token = self._await_token(self.file_choosers, pending_before, "file chooser")
        self._request(
            "page.decide", {"token": token, "decision": "select", "files": [str(path)]}
        )
        self.file_choosers[token].update({"status": "resolved", "path": str(path)})
        chosen = self._evaluate(
            "(() => { const element = document.querySelector('[data-wb-target=\"%s\"]');"
            " return element && element.files && element.files.length"
            " ? element.files[0].name : null; })()" % target["target_id"]
        )
        return "engine", [
            {
                "kind": "upload",
                "path": str(path),
                "file_name": chosen,
                "sha256": sha256_bytes(path.read_bytes()),
            }
        ]

    def _act_download(
        self, page: dict[str, Any], params: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        token = str(intent.get("download_id") or "")
        record = self.downloads.get(token)
        if record is None:
            raise WorkbenchError(
                "precondition_failed", "unknown download", {"download_id": token}
            )
        deadline = time.monotonic() + 30.0
        while record.get("status") == "pending" and time.monotonic() < deadline:
            if self.transport is None:
                break
            self.transport.pump_events(timeout_ms=AWAIT_POLL_MS, on_event=self._ingest)
        if record.get("status") != "completed":
            raise WorkbenchError(
                "backend_failed",
                "download did not complete",
                {"download_id": token, "status": record.get("status")},
            )
        destination = Path(str(record["destination"]))
        payload = destination.read_bytes()
        artifact = self.store.write_bytes(
            f"downloads/{destination.name}", payload, "raw", media_type="application/octet-stream"
        )
        # Quarantined: captured as evidence, never opened, executed, or moved
        # anywhere the run could act on it.
        record.update({"status": "quarantined", "artifact_ref": artifact["artifact_ref"]})
        return "engine", [
            {
                "kind": "download",
                "download_id": token,
                "status": "quarantined",
                "artifact_ref": artifact["artifact_ref"],
                "bytes": len(payload),
            }
        ]

    def _act_crash(
        self, page: dict[str, Any], params: dict[str, Any], intent: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        self._request("page.terminate", {"page_id": page["page_id"]})
        deadline = time.monotonic() + 15.0
        while page["lifecycle"] != "terminated" and time.monotonic() < deadline:
            if self.transport is None:
                break
            self.transport.pump_events(timeout_ms=AWAIT_POLL_MS, on_event=self._ingest)
        if page["lifecycle"] != "terminated":
            raise WorkbenchError(
                "backend_failed", "web process did not report termination", {"page": page["page_id"]}
            )
        return "engine", [{"kind": "page.terminated", "page_id": page["page_id"]}]

    def quiesce(self, *, quiet_ms: int = 250, max_ms: int = 4000) -> None:
        """Consume events until the engine goes quiet.

        A page is settled when the engine has stopped talking about it. Waiting
        only for the load state leaves late events — a title notification
        arrives after the load finishes — to land during whatever the caller
        does next and mutate state it believed was stable.
        """
        self._drain_effects(quiet_ms=quiet_ms, max_ms=max_ms)

    def _drain_effects(self, *, quiet_ms: int = 250, max_ms: int = 4000) -> None:
        """Collect the engine's immediate reaction to an action before sealing
        the receipt.

        A click that navigates produces its events after the script call
        returns. Without this the receipt would claim no observed effect for an
        action that plainly had one. This observes; it never re-issues the
        action.
        """
        deadline = time.monotonic() + max_ms / 1000.0
        while time.monotonic() < deadline:
            if self.transport is None:
                return
            if not self.transport.pump_events(timeout_ms=quiet_ms, on_event=self._ingest):
                return


    def _await_token(
        self, registry: dict[str, dict[str, Any]], before: set[str], what: str
    ) -> str:
        """Wait for the engine to raise a new browser-owned request."""
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            fresh = set(registry) - before
            if fresh:
                return sorted(fresh)[0]
            if self.transport is None:
                break
            self.transport.pump_events(timeout_ms=AWAIT_POLL_MS, on_event=self._ingest)
        raise WorkbenchError("deadline_exceeded", f"the engine never raised a {what}")

    def _check_preconditions(self, page: dict[str, Any], preconditions: dict[str, Any]) -> None:
        for field in ("url", "title", "generation"):
            if field in preconditions and page[field] != preconditions[field]:
                raise WorkbenchError(
                    "precondition_failed",
                    f"page {field} does not match",
                    {"field": field, "expected": preconditions[field], "observed": page[field]},
                )

    def session_export(self, params: dict[str, Any]) -> dict[str, Any]:
        self._export_counter += 1
        since_event = int(params.get("since_event", 0))
        max_bytes = int(params.get("max_bytes", 1024 * 1024))
        selected = {
            "session_id": self.session_id,
            "events": self.log.since(since_event),
            "raw": self.log.raw if params.get("include_raw", False) else [],
            "metadata": copy.deepcopy(params.get("metadata", {})),
        }
        redacted, report = redact(selected)
        payload = canonical_bytes(redacted)
        lossy = len(payload) > max_bytes
        if lossy:
            redacted["events"] = redacted["events"][:1]
            redacted["raw"] = []
            redacted["loss"] = {"reason": "byte-budget", "original_bytes": len(payload)}
        if json_size(redacted) > max_bytes:
            raise WorkbenchError(
                "invalid_request",
                "max_bytes cannot hold the mandatory export envelope",
                {"minimum_observed": json_size(redacted)},
            )
        artifact = self.store.write_json(
            f"exports/export-{self._export_counter:04d}.json", redacted, "redacted"
        )
        return {"artifact": artifact, "redaction": report.as_dict(), "lossy": lossy}

    def flush_traces(self) -> list[dict[str, Any]]:
        raw = self.store.write_text(
            "traces/raw.ndjson",
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in self.log.raw),
            "raw",
            media_type="application/x-ndjson",
        )
        normalized = self.store.write_text(
            "traces/normalized.ndjson",
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in self.log.events),
            "normalized",
            media_type="application/x-ndjson",
        )
        return [raw, normalized]

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        operations = {
            "session.create": self.session_create,
            "page.navigate": self.page_navigate,
            "page.observe": self.page_observe,
            "page.await": self.page_await,
            "page.act": self.page_act,
            "session.checkpoint": self.session_checkpoint,
            "page.tabs": self.page_tabs,
            "session.export": self.session_export,
        }
        operation = operations.get(method)
        if not operation:
            raise WorkbenchError(
                "capability_unsupported",
                f"backend method is not wired in this slice: {method}",
                {"method": method, "supported": sorted(self.SUPPORTED_METHODS)},
            )
        return operation(params)
