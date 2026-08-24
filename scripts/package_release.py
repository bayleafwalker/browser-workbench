#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", "dist"}
EXCLUDED_NAMES = {"PACKAGE_MANIFEST.json", "SHA256SUMS"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def payload_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts)
        and path.name not in EXCLUDED_NAMES
        and path.suffix != ".pyc"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = payload_files()
    records = [
        {"path": path.relative_to(ROOT).as_posix(), "size_bytes": path.stat().st_size, "sha256": digest(path)}
        for path in files
    ]
    manifest = {
        "schema_version": "browser-workbench.package-manifest/v1",
        "package": "browser-workbench",
        "version": VERSION,
        "classification": "source-and-mock-verified",
        "native_runtime_claim": False,
        "baseline": {"package": "hostproto", "version": "0.1.0", "scenario_count": 16},
        "workbench_corpus": {"scenario_count": 12, "repetitions": 3, "expected_run_count": 36},
        "payload_file_count": len(records),
        "files": records,
    }
    manifest_path = ROOT / "PACKAGE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksummed = [*files, manifest_path]
    sums_path = ROOT / "SHA256SUMS"
    sums_path.write_text(
        "".join(f"{digest(path)}  {path.relative_to(ROOT).as_posix()}\n" for path in checksummed),
        encoding="utf-8",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"browser-workbench-{VERSION}"
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in [*files, manifest_path, sums_path]:
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(f"{prefix}/{relative}", date_time=(2026, 8, 24, 0, 0, 0))
            executable = relative.startswith("scripts/") and path.suffix == ".py"
            mode = 0o755 if executable else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "size_bytes": args.output.stat().st_size,
                "sha256": digest(args.output),
                "payload_file_count": len(records) + 2,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
