from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def pretty_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    entries: list[dict[str, Any]] = []
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        entries.append(
            {
                "path": item.relative_to(path).as_posix(),
                "size": item.stat().st_size,
                "sha256": sha256_file(item),
            }
        )
    return sha256_bytes(canonical_bytes(entries))


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "spec").exists():
            return parent
    raise RuntimeError("browser-workbench repository root not found")


def deep_remove(value: Any, dotted_paths: Iterable[str]) -> Any:
    clone = json.loads(json.dumps(value))
    for dotted in dotted_paths:
        parts = dotted.split(".")
        node = clone
        for part in parts[:-1]:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                node = None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return clone


def json_size(value: Any) -> int:
    return len(canonical_bytes(value))
