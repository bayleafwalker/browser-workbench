from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .util import canonical_bytes, pretty_json, sha256_bytes, sha256_file


@dataclass(slots=True)
class ArtifactStore:
    root: Path
    run_id: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _record(
        self,
        relative_path: str,
        surface: str,
        source_refs: list[str] | None = None,
        media_type: str | None = None,
    ) -> dict[str, Any]:
        path = self.root / relative_path
        record = {
            "path": relative_path,
            "media_type": media_type
            or mimetypes.guess_type(relative_path)[0]
            or "application/octet-stream",
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "surface": surface,
            "source_refs": source_refs or [],
        }
        existing = next((item for item in self.artifacts if item["path"] == relative_path), None)
        if existing:
            self.artifacts.remove(existing)
        self.artifacts.append(record)
        return {**record, "artifact_ref": f"sha256:{record['sha256']}"}

    def write_bytes(
        self,
        relative_path: str,
        data: bytes,
        surface: str,
        source_refs: list[str] | None = None,
        media_type: str | None = None,
    ) -> dict[str, Any]:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self._record(relative_path, surface, source_refs, media_type)

    def write_text(
        self,
        relative_path: str,
        text: str,
        surface: str,
        source_refs: list[str] | None = None,
        media_type: str = "text/plain",
    ) -> dict[str, Any]:
        return self.write_bytes(
            relative_path,
            text.encode("utf-8"),
            surface,
            source_refs,
            media_type,
        )

    def write_json(
        self,
        relative_path: str,
        value: Any,
        surface: str,
        source_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.write_text(
            relative_path,
            pretty_json(value),
            surface,
            source_refs,
            "application/json",
        )

    def read_json_ref(self, artifact: dict[str, Any]) -> Any:
        import json

        path = self.root / artifact["path"]
        if sha256_file(path) != artifact["sha256"]:
            raise ValueError(f"artifact digest mismatch: {artifact['path']}")
        return json.loads(path.read_text(encoding="utf-8"))

    def manifest(self, *, complete: bool, redaction: dict[str, Any] | None = None) -> dict[str, Any]:
        ordered = sorted(self.artifacts, key=lambda item: item["path"])
        root_digest = sha256_bytes(canonical_bytes(ordered))
        return {
            "schema_version": "browser-workbench.evidence-manifest/v1",
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "artifacts": ordered,
            "root_digest": root_digest,
            "redaction": redaction or {"count": 0, "rule_ids": []},
            "complete": complete,
        }

    def finalize(self, *, complete: bool, redaction: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = self.manifest(complete=complete, redaction=redaction)
        path = self.root / "manifest.json"
        path.write_text(pretty_json(manifest), encoding="utf-8")
        return {
            "path": "manifest.json",
            "media_type": "application/json",
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "surface": "contract",
            "artifact_ref": f"sha256:{sha256_file(path)}",
            "root_digest": manifest["root_digest"],
        }
