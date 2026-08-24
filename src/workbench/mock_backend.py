from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .errors import WorkbenchError
from .events import EventLog
from .evidence import ArtifactStore
from .redaction import redact
from .util import canonical_bytes, json_size, repo_root, sha256_bytes


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class MockBackend:
    """Deterministic backend for protocol, authority, and evidence conformance."""

    def __init__(self, store: ArtifactStore, variant: str = "default") -> None:
        self.store = store
        self.variant = variant
        self.session_id = "session-0001"
        self.log = EventLog(self.session_id, provider="mock")
        self.pages: dict[str, dict[str, Any]] = {}
        self.active_page_id: str | None = None
        self.writer_id: str | None = None
        self.lease_epoch = 0
        self.lease_id: str | None = None
        self.checkpoint_parent: str | None = None
        self.scheduled: list[tuple[int, int, Callable[[], None]]] = []
        self._schedule_order = 0
        self._navigation_counter = 0
        self._observation_counter = 0
        self._receipt_counter = 0
        self._checkpoint_counter = 0
        self._export_counter = 0
        self.backend_invocations = 0
        self.dialogs: dict[str, dict[str, Any]] = {}
        self.permissions: dict[str, dict[str, Any]] = {}
        self.downloads: dict[str, dict[str, Any]] = {}

    def _schedule(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self._schedule_order += 1
        self.scheduled.append((self.log.monotonic_ms + delay_ms, self._schedule_order, callback))
        self.scheduled.sort(key=lambda item: (item[0], item[1]))

    def _page(self, page_id: str) -> dict[str, Any]:
        page = self.pages.get(page_id)
        if page is None:
            raise WorkbenchError("page_not_found", "page does not exist", {"page_id": page_id})
        return page

    def _require_writer(self, client_id: str | None) -> None:
        if self.writer_id is None:
            raise WorkbenchError("lease_fenced", "session has no active writer")
        if client_id and client_id != self.writer_id:
            raise WorkbenchError(
                "lease_conflict",
                "client does not hold the single-writer lease",
                {"holder": self.writer_id, "client": client_id, "lease_epoch": self.lease_epoch},
            )

    def _new_page(self, generation: int = 1) -> dict[str, Any]:
        page_id = f"page-{len(self.pages) + 1}"
        page = {
            "page_id": page_id,
            "generation": generation,
            "lifecycle": "open",
            "url": "about:blank",
            "title": "New Page",
            "load_state": "idle",
            "history": ["about:blank"],
            "history_index": 0,
            "dom": "<main><a id='next'>Next</a><input id='query'></main>",
            "values": {"target-query": ""},
            "last_navigation_outcome": None,
        }
        self.pages[page_id] = page
        return page

    def _targets(self, page: dict[str, Any]) -> list[dict[str, Any]]:
        generation = page["generation"]
        return [
            {
                "target_id": "target-next",
                "generation": generation,
                "role": "link",
                "name": "Next",
                "actions": ["click"],
            },
            {
                "target_id": "target-query",
                "generation": generation,
                "role": "textbox",
                "name": "Query",
                "actions": ["type"],
            },
        ]

    def _emit_backend(
        self,
        raw_kind: str,
        event_kind: str,
        payload: dict[str, Any],
        *,
        page: dict[str, Any] | None = None,
        causes: list[str] | None = None,
        source: str = "mock",
    ) -> dict[str, Any]:
        raw_id = self.log.capture_raw(
            raw_kind,
            copy.deepcopy(payload),
            page_id=page and page["page_id"],
            causes=causes,
        )
        return self.log.emit(
            event_kind,
            copy.deepcopy(payload),
            page_id=page and page["page_id"],
            generation=page and page["generation"],
            source=source,
            causes=causes,
            raw_refs=[raw_id],
        )

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

        resume = params.get("resume_checkpoint")
        if resume:
            checkpoint = self.store.read_json_ref(resume) if isinstance(resume, dict) else None
            if not checkpoint:
                raise WorkbenchError("invalid_request", "resume_checkpoint must be an artifact descriptor")
            self.pages = copy.deepcopy(checkpoint["state"]["pages"])
            for page in self.pages.values():
                page["generation"] += 1
                if page["lifecycle"] == "terminated":
                    page["lifecycle"] = "open"
                    page["load_state"] = "idle"
            self.active_page_id = checkpoint["state"]["active_page_id"]
            self.lease_epoch = checkpoint["lease"]["epoch"] + 1
            self.checkpoint_parent = checkpoint["checkpoint_id"]
        elif not self.pages:
            page = self._new_page()
            self.active_page_id = page["page_id"]
            self.lease_epoch = 1

        self.writer_id = client_id
        self.lease_id = f"lease-{self.lease_epoch:04d}"
        event = self.log.emit(
            "session.created",
            {"profile": profile, "writer_id": client_id, "lease_epoch": self.lease_epoch},
            source="host",
        )
        return {
            "session_id": self.session_id,
            "page_id": self.active_page_id,
            "profile": profile,
            "lease": {
                "lease_id": self.lease_id,
                "lease_epoch": self.lease_epoch,
                "writer_id": self.writer_id,
                "mode": "single-writer",
            },
            "resumed_from": self.checkpoint_parent,
            "event_id": event["event_id"],
        }

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https", "about"}:
            raise WorkbenchError("invalid_request", "URL scheme is not allowed", {"url": url})
        if parsed.scheme in {"http", "https"} and not parsed.netloc:
            raise WorkbenchError("invalid_request", "URL is not absolute", {"url": url})

    def page_navigate(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_writer(params.get("client_id"))
        page = self._page(params["page_id"])
        if page["lifecycle"] != "open":
            raise WorkbenchError("backend_rejected", "page is not open")
        url = params["url"]
        self._validate_url(url)
        self.backend_invocations += 1
        self._navigation_counter += 1
        navigation_id = f"navigation-{self._navigation_counter:04d}"
        raw_id = self.log.capture_raw(
            "navigate.invoked",
            {"navigation_id": navigation_id, "url": url},
            page_id=page["page_id"],
        )
        page["load_state"] = "loading"
        started = self.log.emit(
            "navigation.started",
            {"navigation_id": navigation_id, "url": url},
            page_id=page["page_id"],
            generation=page["generation"],
            raw_refs=[raw_id],
        )

        def commit() -> None:
            page["generation"] += 1
            page["url"] = url
            page["title"] = _title_for_url(url)
            page["history"] = page["history"][: page["history_index"] + 1] + [url]
            page["history_index"] = len(page["history"]) - 1
            page["dom"] = _dom_for_url(url)
            request = self._emit_backend(
                "resource.request",
                "network.request",
                {"request_id": navigation_id, "url": url, "method": "GET"},
                page=page,
                causes=[started["event_id"]],
            )
            self._emit_backend(
                "resource.response",
                "network.response",
                {"request_id": navigation_id, "url": url, "status": 200},
                page=page,
                causes=[request["event_id"]],
            )
            self._emit_backend(
                "load.committed",
                "navigation.committed",
                {"navigation_id": navigation_id, "url": url, "title": page["title"]},
                page=page,
                causes=[started["event_id"]],
            )
            if "console" in url:
                self._emit_backend(
                    "console.message",
                    "console.message",
                    {"level": "info", "text": "fixture console record"},
                    page=page,
                )
            if "prompts" in url:
                self.dialogs["dialog-0001"] = {"token": "dialog-0001", "status": "pending", "default": "deny"}
                self.permissions["permission-0001"] = {
                    "token": "permission-0001",
                    "kind": "geolocation",
                    "status": "pending",
                    "default": "deny",
                }
                self.log.emit(
                    "dialog.opened",
                    copy.deepcopy(self.dialogs["dialog-0001"]),
                    page_id=page["page_id"],
                    generation=page["generation"],
                )
                self.log.emit(
                    "permission.requested",
                    copy.deepcopy(self.permissions["permission-0001"]),
                    page_id=page["page_id"],
                    generation=page["generation"],
                )

        def finish() -> None:
            page["load_state"] = "idle"
            page["last_navigation_outcome"] = "success"
            self._emit_backend(
                "load.finished",
                "navigation.finished",
                {"navigation_id": navigation_id, "url": url, "outcome": "success"},
                page=page,
                causes=[started["event_id"]],
            )

        self._schedule(5, commit)
        self._schedule(10, finish)
        if params.get("wait") == "commit":
            self._run_next_scheduled()
        return {
            "accepted": True,
            "navigation_id": navigation_id,
            "caused_event_ids": [started["event_id"]],
        }

    def _run_next_scheduled(self) -> bool:
        if not self.scheduled:
            return False
        due, _, callback = self.scheduled.pop(0)
        self.log.advance(max(0, due - self.log.monotonic_ms))
        callback()
        return True

    def _projection_data(self, page: dict[str, Any], projection: str, since_event: int) -> Any:
        if projection == "state":
            return copy.deepcopy(page)
        if projection == "targets":
            return self._targets(page)
        if projection == "dom":
            return {"html": page["dom"], "sha256": sha256_bytes(page["dom"].encode())}
        if projection == "accessibility":
            return {
                "role": "document",
                "name": page["title"],
                "children": [{"role": item["role"], "name": item["name"]} for item in self._targets(page)],
            }
        if projection == "console":
            return [event for event in self.log.since(since_event) if event["kind"] == "console.message"]
        if projection == "network":
            return [event for event in self.log.since(since_event) if event["kind"].startswith("network.")]
        if projection == "dialogs":
            return list(copy.deepcopy(self.dialogs).values())
        if projection == "permissions":
            return list(copy.deepcopy(self.permissions).values())
        if projection == "downloads":
            return list(copy.deepcopy(self.downloads).values())
        if projection == "raw-events":
            return [record for record in self.log.raw if record["ordinal"] > since_event]
        if projection == "screenshot":
            descriptor = self.store.write_bytes(
                f"screenshots/{page['page_id']}-g{page['generation']}.png",
                ONE_PIXEL_PNG,
                "raw",
                media_type="image/png",
            )
            return descriptor
        raise WorkbenchError(
            "capability_unsupported",
            f"observation projection is unsupported: {projection}",
            {"projection": projection},
        )

    def page_observe(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._page(params["page_id"])
        projections = params.get("projection", ["state"])
        if isinstance(projections, str):
            projections = [projections]
        since_event = int(params.get("since_event", 0))
        max_bytes = int(params.get("max_bytes", 32768))
        if max_bytes < 512:
            raise WorkbenchError("invalid_request", "max_bytes must be at least 512")
        data = {name: self._projection_data(page, name, since_event) for name in projections}
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
            "data": data,
        }
        if json_size(response) <= max_bytes:
            return response

        raw = self.store.write_json(
            f"observations/observation-{self._observation_counter:04d}.json",
            response,
            "raw",
        )
        compact_data: dict[str, Any] = {}
        omitted: dict[str, int] = {}
        for name, value in data.items():
            if name == "state":
                compact_data[name] = value
            elif isinstance(value, list):
                compact_data[name] = value[:1]
                omitted[name] = max(0, len(value) - 1)
            else:
                compact_data[name] = {"omitted": True, "type": type(value).__name__}
                omitted[name] = 1
        response.update({"lossy": True, "omitted": omitted, "raw_ref": raw["artifact_ref"], "data": compact_data})
        if json_size(response) > max_bytes:
            response["data"] = {"state": {"page_id": page["page_id"], "generation": page["generation"]}}
            response["omitted"] = {name: 1 for name in projections}
        if json_size(response) > max_bytes:
            raise WorkbenchError(
                "invalid_request",
                "max_bytes cannot hold the mandatory observation envelope",
                {"minimum_observed": json_size(response)},
            )
        return response

    def _check_preconditions(self, page: dict[str, Any], preconditions: dict[str, Any]) -> None:
        for field in ("url", "title", "generation"):
            if field in preconditions and page[field] != preconditions[field]:
                raise WorkbenchError(
                    "precondition_failed",
                    f"page {field} does not match",
                    {"field": field, "expected": preconditions[field], "observed": page[field]},
                )

    def _check_target(self, page: dict[str, Any], target: dict[str, Any] | None, kind: str) -> None:
        if kind not in {"click", "type"}:
            return
        if not target:
            raise WorkbenchError("invalid_request", "intent requires a target")
        if target.get("generation") != page["generation"]:
            raise WorkbenchError(
                "stale_target",
                "target belongs to a different page generation",
                {"target_generation": target.get("generation"), "page_generation": page["generation"]},
            )
        available = {item["target_id"]: item for item in self._targets(page)}
        declaration = available.get(target.get("target_id"))
        if not declaration or kind not in declaration["actions"]:
            raise WorkbenchError("precondition_failed", "target does not support the requested intent")

    def _receipt(
        self,
        action_id: str,
        provider: str,
        before: str,
        caused: list[str],
        page: dict[str, Any],
        effects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._receipt_counter += 1
        return {
            "receipt_id": f"receipt-{self._receipt_counter:04d}",
            "action_id": action_id,
            "attempted": True,
            "accepted": True,
            "executed": True,
            "verified": bool(caused or effects),
            "provider": provider,
            "caused_event_ids": caused,
            "effects": effects,
            "state_before": before,
            "state_after": sha256_bytes(canonical_bytes(page)),
        }

    def page_act(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_writer(params.get("client_id"))
        page = self._page(params["page_id"])
        self._check_preconditions(page, params.get("preconditions", {}))
        intent = params.get("intent", {})
        kind = intent.get("kind")
        if not isinstance(kind, str):
            raise WorkbenchError("invalid_request", "intent kind is required")
        self._check_target(page, params.get("target"), kind)
        before = sha256_bytes(canonical_bytes(page))
        action_id = intent.get("action_id", f"action-{self._receipt_counter + 1:04d}")
        provider = "mock"
        caused: list[str] = []
        effects: list[dict[str, Any]] = []

        supported_intents = {
            "click", "type", "javascript", "dialog.resolve", "permission.resolve",
            "upload", "download.accept", "navigation.stop", "test.crash",
        }
        if kind not in supported_intents:
            raise WorkbenchError("capability_unsupported", f"intent is unsupported: {kind}")
        if kind == "javascript":
            script = str(intent.get("value", ""))
            if script != "return-title" and not script.startswith("set-title:"):
                raise WorkbenchError("backend_rejected", "mock JavaScript fixture command is not declared")
        if kind in {"dialog.resolve", "permission.resolve"}:
            collection = self.dialogs if kind.startswith("dialog") else self.permissions
            token = intent.get("decision_token")
            record = collection.get(token)
            if not record:
                raise WorkbenchError("precondition_failed", "decision token is unknown")
            if record["status"] != "pending":
                raise WorkbenchError("precondition_failed", "decision token is already resolved")
            if intent.get("decision", "deny") not in {"allow", "deny", "accept", "dismiss"}:
                raise WorkbenchError("invalid_request", "decision is invalid")
        if kind == "upload":
            source = Path(str(intent.get("path", ""))).resolve()
            allowed = (repo_root() / "examples" / "fixtures").resolve()
            if allowed not in source.parents or not source.is_file():
                raise WorkbenchError("precondition_failed", "upload path is outside the declared fixture root")

        self.backend_invocations += 1
        raw_id = self.log.capture_raw("action.invoked", copy.deepcopy(intent), page_id=page["page_id"])
        accepted = self.log.emit(
            "action.accepted",
            {"action_id": action_id, "kind": kind},
            page_id=page["page_id"],
            generation=page["generation"],
            raw_refs=[raw_id],
        )
        caused.append(accepted["event_id"])

        if kind == "click":
            event = self.log.emit(
                "target.clicked",
                {"target_id": params["target"]["target_id"]},
                page_id=page["page_id"],
                generation=page["generation"],
                causes=[accepted["event_id"]],
            )
            caused.append(event["event_id"])
            effects.append({"kind": "input", "target_id": params["target"]["target_id"]})
        elif kind == "type":
            value = str(intent.get("value", ""))
            page["values"][params["target"]["target_id"]] = value
            event = self.log.emit(
                "target.value_changed",
                {"target_id": params["target"]["target_id"], "length": len(value)},
                page_id=page["page_id"],
                generation=page["generation"],
                causes=[accepted["event_id"]],
            )
            caused.append(event["event_id"])
            effects.append({"kind": "value", "length": len(value)})
        elif kind == "javascript":
            provider = "injected"
            if script == "return-title":
                effects.append({"kind": "script-result", "value": page["title"]})
            elif script.startswith("set-title:"):
                page["title"] = script.split(":", 1)[1][:256]
                event = self.log.emit(
                    "page.title_changed",
                    {"title": page["title"]},
                    page_id=page["page_id"],
                    generation=page["generation"],
                    causes=[accepted["event_id"]],
                    source="injected",
                )
                caused.append(event["event_id"])
                effects.append({"kind": "title", "value": page["title"]})
        elif kind in {"dialog.resolve", "permission.resolve"}:
            collection = self.dialogs if kind.startswith("dialog") else self.permissions
            token = intent.get("decision_token")
            record = collection.get(token)
            decision = intent.get("decision", "deny")
            assert record is not None
            record["status"] = decision
            event = self.log.emit(
                f"{kind.split('.')[0]}.resolved",
                {"token": token, "decision": decision},
                page_id=page["page_id"],
                generation=page["generation"],
                causes=[accepted["event_id"]],
            )
            caused.append(event["event_id"])
            effects.append({"kind": kind, "decision": decision})
        elif kind == "upload":
            artifact = self.store.write_bytes(
                f"uploads/{source.name}", source.read_bytes(), "raw", media_type="application/octet-stream"
            )
            effects.append({"kind": "upload", "artifact_ref": artifact["artifact_ref"]})
        elif kind == "download.accept":
            download_id = str(intent.get("download_id", "download-0001"))
            payload = f"quarantined fixture download {download_id}\n".encode()
            artifact = self.store.write_bytes(
                f"downloads/quarantine/{download_id}.txt", payload, "raw", media_type="text/plain"
            )
            self.downloads[download_id] = {
                "download_id": download_id,
                "status": "quarantined",
                "artifact_ref": artifact["artifact_ref"],
            }
            effects.append(copy.deepcopy(self.downloads[download_id]))
        elif kind == "navigation.stop":
            page["load_state"] = "idle"
            page["last_navigation_outcome"] = "stopped"
            self.scheduled.clear()
            event = self.log.emit(
                "navigation.stopped",
                {"outcome": "stopped"},
                page_id=page["page_id"],
                generation=page["generation"],
                causes=[accepted["event_id"]],
            )
            caused.append(event["event_id"])
        elif kind == "test.crash":
            page["lifecycle"] = "terminated"
            page["load_state"] = "idle"
            event = self._emit_backend(
                "process.terminated",
                "page.terminated",
                {"reason": "mock-injected-crash", "recoverable": True},
                page=page,
                causes=[accepted["event_id"]],
            )
            caused.append(event["event_id"])
        return self._receipt(action_id, provider, before, caused, page, effects)

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

    def page_await(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._page(params["page_id"])
        conditions = params.get("conditions", [])
        if not conditions:
            raise WorkbenchError("invalid_request", "await requires at least one condition")
        deadline_ms = int(params.get("deadline_ms", 30000))
        deadline = self.log.monotonic_ms + deadline_ms
        while not all(self._condition(page, condition) for condition in conditions):
            if not self.scheduled or self.scheduled[0][0] > deadline:
                self.log.advance(max(0, deadline - self.log.monotonic_ms))
                unsatisfied = [condition for condition in conditions if not self._condition(page, condition)]
                raise WorkbenchError(
                    "deadline_exceeded",
                    "await deadline elapsed",
                    {"unsatisfied": unsatisfied, "event_cursor": self.log.cursor},
                )
            self._run_next_scheduled()
        return {
            "satisfied": True,
            "conditions": conditions,
            "event_cursor": self.log.cursor,
            "monotonic_ms": self.log.monotonic_ms,
        }

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
            "state": {"active_page_id": self.active_page_id, "pages": copy.deepcopy(self.pages)},
            "lease": {"id": self.lease_id, "epoch": self.lease_epoch, "writer_id": self.writer_id},
            "approval": None,
        }
        artifact = self.store.write_json(f"checkpoints/{checkpoint_id}.json", checkpoint, "normalized")
        released = bool(params.get("release_lease", False))
        if released:
            prior_writer = self.writer_id
            self.writer_id = None
            self.lease_id = None
            self.log.emit(
                "session.handover_ready",
                {"checkpoint_id": checkpoint_id, "prior_writer": prior_writer, "lease_epoch": self.lease_epoch},
                source="host",
            )
        return {
            "checkpoint_id": checkpoint_id,
            "artifact": artifact,
            "released_lease": released,
            "approval": None,
        }

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
            redacted = {
                "session_id": self.session_id,
                "events": [],
                "raw": [],
                "metadata": {},
                "loss": {"reason": "byte-budget", "original_bytes": len(payload)},
            }
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
            "page.act": self.page_act,
            "page.await": self.page_await,
            "session.checkpoint": self.session_checkpoint,
            "session.export": self.session_export,
        }
        operation = operations.get(method)
        if not operation:
            raise WorkbenchError("capability_unsupported", f"backend method is unavailable: {method}")
        return operation(params)


def _title_for_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "Home"
    return path.replace("-", " ").title()


def _dom_for_url(url: str) -> str:
    title = _title_for_url(url)
    filler = " evidence" * (200 if "large" in url else 2)
    return f"<main><h1>{title}</h1><a id='next'>Next</a><input id='query'><p>{filler}</p></main>"
