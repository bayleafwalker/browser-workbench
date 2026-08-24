from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ERROR_STATUS = {
    "capability_unsupported": "unsupported",
    "capability_blocked": "blocked",
    "invalid_request": "invalid",
    "protocol_mismatch": "invalid",
    "evidence_incomplete": "invalid",
    "integrity_mismatch": "invalid",
    "candidate_mutated": "invalid",
    "internal_invariant": "invalid",
}


@dataclass(slots=True)
class WorkbenchError(Exception):
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return ERROR_STATUS.get(self.code, "failed")

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "data": self.data}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
