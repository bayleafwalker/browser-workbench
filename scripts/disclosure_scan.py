#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".yaml", ".yml", ".js", ".mjs", ".css", ".html", ".txt", ".rs", ".ndjson"}
FORBIDDEN = {
    "workspace-path": re.compile(r"/(?:workspace|root)/"),
    "aws-key": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{24,}\b"),
    "openai-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=ROOT)
    args = parser.parse_args()
    findings = []
    for path in sorted(candidate for candidate in args.path.rglob("*") if candidate.is_file()):
        if ".git" in path.parts or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for rule, pattern in FORBIDDEN.items():
            for match in pattern.finditer(text):
                # Scanner source contains its own patterns; generated evidence may quote local probes.
                if path.resolve() == Path(__file__).resolve() or "evidence" in path.parts:
                    continue
                line = text.count("\n", 0, match.start()) + 1
                findings.append({"rule": rule, "path": str(path.relative_to(args.path)), "line": line})
    report = {"schema_version": "browser-workbench.disclosure-scan/v1", "status": "passed" if not findings else "failed", "findings": findings}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
