from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SENSITIVE_KEYS = re.compile(
    r"(^|_)(authorization|cookie|password|passwd|secret|token|api[_-]?key|private[_-]?key)($|_)",
    re.IGNORECASE,
)
BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE)
LONG_CREDENTIAL = re.compile(r"\b(?:sk|ghp|glpat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b")


@dataclass(slots=True)
class RedactionReport:
    count: int = 0
    rule_ids: set[str] | None = None

    def __post_init__(self) -> None:
        if self.rule_ids is None:
            self.rule_ids = set()

    def as_dict(self) -> dict[str, Any]:
        return {"count": self.count, "rule_ids": sorted(self.rule_ids or set())}


def redact(value: Any, report: RedactionReport | None = None) -> tuple[Any, RedactionReport]:
    report = report or RedactionReport()

    def visit(node: Any, key: str | None = None) -> Any:
        if key and SENSITIVE_KEYS.search(key):
            report.count += 1
            assert report.rule_ids is not None
            report.rule_ids.add("sensitive-key")
            return "[REDACTED]"
        if isinstance(node, dict):
            return {str(k): visit(v, str(k)) for k, v in node.items()}
        if isinstance(node, list):
            return [visit(item) for item in node]
        if isinstance(node, str):
            replaced, bearer_count = BEARER.subn("Bearer [REDACTED]", node)
            replaced, credential_count = LONG_CREDENTIAL.subn("[REDACTED]", replaced)
            if bearer_count:
                report.count += bearer_count
                assert report.rule_ids is not None
                report.rule_ids.add("bearer-value")
            if credential_count:
                report.count += credential_count
                assert report.rule_ids is not None
                report.rule_ids.add("credential-pattern")
            return replaced
        return node

    return visit(value), report
