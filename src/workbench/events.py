from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EventLog:
    session_id: str
    provider: str = "mock"
    _seq: int = 0
    _raw_ordinal: int = 0
    monotonic_ms: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    raw: list[dict[str, Any]] = field(default_factory=list)

    @property
    def cursor(self) -> int:
        return self._seq

    def capture_raw(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        page_id: str | None = None,
        causes: list[str] | None = None,
    ) -> str:
        self._raw_ordinal += 1
        raw_id = f"raw-{self._raw_ordinal:06d}"
        self.raw.append(
            {
                "raw_id": raw_id,
                "ordinal": self._raw_ordinal,
                "kind": kind,
                "payload": payload,
                "page_id": page_id,
                "causes": causes or [],
                "monotonic_ms": self.monotonic_ms,
                "source": self.provider,
            }
        )
        return raw_id

    def emit(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        page_id: str | None = None,
        generation: int | None = None,
        source: str | None = None,
        causes: list[str] | None = None,
        raw_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        event = {
            "schema_version": "browser-workbench.event/v1",
            "event_id": f"event-{self._seq:06d}",
            "event_seq": self._seq,
            "kind": kind,
            "session_id": self.session_id,
            "page_id": page_id,
            "generation": generation,
            "payload": payload,
            "source": source or self.provider,
            "causes": causes or [],
            "raw_refs": raw_refs or [],
            "monotonic_ms": self.monotonic_ms,
        }
        self.events.append(event)
        return event

    def advance(self, milliseconds: int) -> None:
        if milliseconds < 0:
            raise ValueError("monotonic time cannot move backwards")
        self.monotonic_ms += milliseconds

    def since(self, cursor: int) -> list[dict[str, Any]]:
        return [event for event in self.events if event["event_seq"] > cursor]
