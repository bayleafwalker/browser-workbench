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
) -> dict[str, Any]:
    matrix = matrix or load_matrix()
    probe = probe or probe_backend(backend)
    if backend not in {"mock", "webkitgtk", "playwright", "servo-gtk"}:
        raise WorkbenchError("invalid_request", f"unknown backend: {backend}")

    capabilities: dict[str, Any] = {}
    for name, lanes in matrix["capabilities"].items():
        availability, provider, semantics = lanes[backend]
        verification = "runtime" if backend == "mock" else "source-audit"
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

    return {
        "schema_version": "browser-workbench.capabilities/v1",
        "backend": backend,
        "variant": variant,
        "identity": {"probe": probe},
        "capabilities": capabilities,
    }


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
