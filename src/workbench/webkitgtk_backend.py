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
    }
    SUPPORTED_PROJECTIONS = {"state", "raw-events", "dom", "console", "network", "screenshot"}
    SUPPORTED_INTENTS = {"javascript"}

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
        self.viewport: dict[str, Any] = {}
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

        raw_id = self.log.capture_raw(
            kind,
            copy.deepcopy(payload),
            page_id=self.page and self.page["page_id"],
        )
        if kind == "script-message":
            self._ingest_script_message(payload, raw_id)
            return

        lookup = kind
        if kind == "load-changed":
            lookup = f"load-changed:{payload.get('phase', 'unknown')}"
        normalized_kind = EVENT_KINDS.get(lookup)
        if normalized_kind is None:
            # An unmapped callback is retained raw and surfaced, never dropped.
            self._deviations.append({"kind": "unmapped-engine-event", "raw_kind": lookup})
            return

        self._apply(lookup, payload)
        self.log.emit(
            normalized_kind,
            copy.deepcopy(payload),
            page_id=self.page and self.page["page_id"],
            generation=self.page and self.page["generation"],
            source="engine",
            raw_refs=[raw_id],
        )

    def _apply(self, lookup: str, payload: dict[str, Any]) -> None:
        """Fold an engine callback into the host's page projection."""
        page = self.page
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
        result = self._request("page.evaluate", {"script": script}, deadline_ms=deadline_ms)
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

    def _active_page(self, page_id: str) -> dict[str, Any]:
        if self.page is None or page_id != self.page["page_id"]:
            raise WorkbenchError("page_not_found", "page does not exist", {"page_id": page_id})
        return self.page

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
        if params.get("resume_checkpoint"):
            raise WorkbenchError(
                "capability_unsupported",
                "checkpoint resume is not wired in this slice",
            )

        viewport = params.get("viewport", {"width": 1280, "height": 800})
        self.viewport = viewport
        result = self._request(
            "session.open",
            {"width": int(viewport.get("width", 1280)), "height": int(viewport.get("height", 800))},
        )
        self.page = {
            "page_id": str(result["page_id"]),
            "generation": int(result["generation"]),
            "lifecycle": "open",
            "url": "about:blank",
            "title": "",
            "load_state": "idle",
            "last_navigation_outcome": None,
        }
        self.writer_id = client_id
        self.lease_epoch = 1
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
            "resumed_from": None,
            "event_id": event["event_id"],
        }

    def page_navigate(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_writer(params.get("client_id"))
        page = self._active_page(params["page_id"])
        if page["lifecycle"] != "open":
            raise WorkbenchError("backend_rejected", "page is not open")
        url = params["url"]
        before = sha256_bytes(canonical_bytes(page))
        cursor = self.log.cursor
        result = self._request("page.navigate", {"url": url})
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
        page = self._active_page(params["page_id"])
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

    def page_observe(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._active_page(params["page_id"])
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
        if "state" in projections:
            engine = self._request("page.observe", {})
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
            raise WorkbenchError(
                "invalid_request",
                "max_bytes cannot hold the mandatory observation envelope",
                {"minimum_observed": json_size(response)},
            )
        return response

    def _screenshot(self, page: dict[str, Any]) -> dict[str, Any]:
        result = self._request("page.snapshot", {"region": "full-document"}, deadline_ms=60000)
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

    def page_act(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute one declared intent. Only the wired intent families run."""
        self._require_writer(params.get("client_id"))
        page = self._active_page(params["page_id"])
        intent = params.get("intent") or {}
        kind = intent.get("kind")
        if kind not in self.SUPPORTED_INTENTS:
            raise WorkbenchError(
                "capability_unsupported",
                "intent family is not wired in this slice",
                {"intent": kind, "supported": sorted(self.SUPPORTED_INTENTS)},
            )
        self._check_preconditions(page, params.get("preconditions") or {})

        self._action_counter += 1
        action_id = f"action-{self._action_counter:04d}"
        before = sha256_bytes(canonical_bytes(page))
        cursor = self.log.cursor
        value = self._evaluate(str(intent.get("value") or ""))
        caused = [event["event_id"] for event in self.log.since(cursor)]

        self._receipt_counter += 1
        return {
            "receipt_id": f"receipt-{self._receipt_counter:04d}",
            "action_id": action_id,
            "attempted": True,
            "accepted": True,
            "executed": True,
            # Verified means the engine returned a value or an effect was
            # observed, not merely that the call did not raise.
            "verified": value is not None or bool(caused),
            "provider": "engine",
            "caused_event_ids": caused,
            "effects": [{"kind": "javascript.result", "value": value}],
            "state_before": before,
            "state_after": sha256_bytes(canonical_bytes(page)),
        }

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
