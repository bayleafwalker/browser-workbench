#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    expected_lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    errors: list[str] = []
    verified = 0
    for line in expected_lines:
        expected, separator, relative = line.partition("  ")
        pure = PurePosixPath(relative)
        if not separator or pure.is_absolute() or ".." in pure.parts:
            errors.append(f"invalid checksum path: {relative}")
            continue
        path = root.joinpath(*pure.parts)
        if not path.is_file():
            errors.append(f"missing: {relative}")
        elif sha256(path) != expected:
            errors.append(f"digest mismatch: {relative}")
        else:
            verified += 1
    declared = {item["path"] for item in manifest["files"]}
    summed = {line.partition("  ")[2] for line in expected_lines if "  " in line}
    if not declared <= summed:
        errors.append("manifest payload is not fully covered by SHA256SUMS")
    report = {
        "schema_version": "browser-workbench.package-verification/v1",
        "status": "passed" if not errors else "failed",
        "verified_files": verified,
        "errors": errors,
        "classification": manifest["classification"],
        "native_runtime_claim": manifest["native_runtime_claim"],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
