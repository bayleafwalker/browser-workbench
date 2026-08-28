from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import WorkbenchError
from .native_probe import probe_backend
from .util import repo_root


def load_matrix(path: Path | None = None) -> dict[str, Any]:
    path = path or repo_root() / "spec" / "CAPABILITY_MATRIX_V1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def capability_report(
    backend: str,
    variant: str,
    *,
    probe: dict[str, Any] | None = None,
    matrix: dict[str, Any] | None = None,
    runtime_ledger: "RuntimeLedger | dict[str, int] | None" = None,
) -> dict[str, Any]:
    matrix = matrix or load_matrix()
    probe = probe or probe_backend(backend)
    if backend not in {"mock", "webkitgtk", "playwright", "servo-gtk"}:
        raise WorkbenchError("invalid_request", f"unknown backend: {backend}")

    capabilities: dict[str, Any] = {}
    for name, lanes in matrix["capabilities"].items():
        availability, provider, semantics = lanes[backend]
        # Runtime verification is earned per capability by execution, on every
        # backend including the mock: see `with_runtime_verification`. Until a
        # capability has actually run, the honest class is a source audit.
        verification = "source-audit"
        notes: list[str] = []

        if not probe["ready"] and availability != "unsupported":
            if provider != "host" or name == "session.create":
                availability = "blocked"
                semantics = "none"
                verification = "none"
                notes.extend(probe.get("reasons", []))
        if availability == "unsupported":
            verification = "source-audit"
            notes.append("unsupported by the pinned public backend surface")
        elif availability == "partial":
            notes.append("partial semantics must not satisfy an exact-capability gate")

        capabilities[name] = {
            "availability": availability,
            "provider": provider,
            "semantics": semantics,
            "verification": verification,
            "notes": sorted(set(notes)),
        }

    report = {
        "schema_version": "browser-workbench.capabilities/v1",
        "backend": backend,
        "variant": variant,
        "identity": {"probe": probe},
        "capabilities": capabilities,
    }
    if runtime_ledger:
        report = with_runtime_verification(report, runtime_ledger)
    return report


# -- runtime verification, earned per capability ---------------------------

_PROJECTION_CAPABILITY = {
    "state": "page.observe.state",
    "dom": "page.observe.dom",
    "accessibility": "page.observe.accessibility",
    "screenshot": "page.observe.screenshot",
    "console": "page.observe.console",
    "network": "page.observe.network",
}
_INTENT_CAPABILITY = {
    "javascript": "page.act.javascript",
    "click": "page.act.pointer",
    "type": "page.act.keyboard",
    "dialog.resolve": "page.dialog",
    "permission.resolve": "page.permission",
    "upload": "page.upload",
    "download.accept": "page.download",
    "test.crash": "page.termination",
}
_METHOD_CAPABILITY = {
    "page.navigate": "page.navigate",
    "page.await": "page.await",
    "page.tabs": "page.tabs",
    "session.checkpoint": "session.checkpoint",
    "session.export": "session.export",
    "run.compare": "run.compare",
}


def exercised_capabilities(method: str, params: dict[str, Any]) -> list[str]:
    """Name the matrix capabilities one successful operation actually exercised.

    This is the only bridge between an executed operation and the capability
    matrix, so a `runtime` verification class can never be granted by
    declaration — only by an operation that completed.
    """
    params = params or {}
    if method == "session.create":
        mode = (params.get("profile") or {}).get("mode", "ephemeral")
        return ["session.create", f"session.profile.{mode}"]
    if method == "page.observe":
        projections = params.get("projection", ["state"])
        if isinstance(projections, str):
            projections = [projections]
        return sorted({_PROJECTION_CAPABILITY[p] for p in projections if p in _PROJECTION_CAPABILITY})
    if method == "page.act":
        kind = (params.get("intent") or {}).get("kind")
        return [_INTENT_CAPABILITY[kind]] if kind in _INTENT_CAPABILITY else []
    return [_METHOD_CAPABILITY[method]] if method in _METHOD_CAPABILITY else []


class RuntimeLedger:
    """Counts successful executions per capability for one run or corpus."""

    def __init__(self) -> None:
        self.executions: dict[str, int] = {}

    def record(self, method: str, params: dict[str, Any]) -> list[str]:
        names = exercised_capabilities(method, params)
        for name in names:
            self.executions[name] = self.executions.get(name, 0) + 1
        return names

    def merge(self, other: "RuntimeLedger | dict[str, int]") -> None:
        executions = other.executions if isinstance(other, RuntimeLedger) else other
        for name, count in executions.items():
            self.executions[name] = self.executions.get(name, 0) + int(count)

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self.executions.items()))


def with_runtime_verification(
    report: dict[str, Any], ledger: "RuntimeLedger | dict[str, int]"
) -> dict[str, Any]:
    """Upgrade `verification` to `runtime` only where the ledger shows execution.

    Availability is never changed here: a partial capability that ran is
    still partial, now runtime-verified as partial. Blocked and unsupported
    capabilities cannot have run and are left alone even if a ledger names
    them, which would itself be a finding.
    """
    executions = ledger.executions if isinstance(ledger, RuntimeLedger) else dict(ledger)
    upgraded = json.loads(json.dumps(report))
    verified: list[str] = []
    unexplained: list[str] = []
    for name, count in sorted(executions.items()):
        declaration = upgraded["capabilities"].get(name)
        if declaration is None or count < 1:
            continue
        if declaration["availability"] in {"blocked", "unsupported"}:
            unexplained.append(name)
            continue
        declaration["verification"] = "runtime"
        declaration["runtime_executions"] = int(count)
        verified.append(name)
    upgraded["runtime_verified"] = verified
    upgraded["runtime_unexplained"] = unexplained
    return upgraded


def require_capabilities(
    report: dict[str, Any],
    required: list[str],
    allowed_providers: list[str] | None = None,
) -> None:
    capabilities = report["capabilities"]
    for name in required:
        declaration = capabilities.get(name)
        if declaration is None:
            raise WorkbenchError(
                "capability_unsupported",
                f"required capability is unknown: {name}",
                {"capability": name},
            )
        if declaration["availability"] == "blocked":
            raise WorkbenchError(
                "capability_blocked",
                f"required capability is blocked: {name}",
                {"capability": name, "declaration": declaration},
            )
        if declaration["availability"] != "supported":
            raise WorkbenchError(
                "capability_unsupported",
                f"required capability is not fully supported: {name}",
                {"capability": name, "declaration": declaration},
            )
        if allowed_providers and declaration["provider"] not in allowed_providers:
            raise WorkbenchError(
                "capability_unsupported",
                f"provider is not allowed for {name}",
                {
                    "capability": name,
                    "provider": declaration["provider"],
                    "allowed_providers": allowed_providers,
                },
            )
