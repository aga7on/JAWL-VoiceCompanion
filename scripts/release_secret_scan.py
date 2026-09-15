"""Fail-closed, value-redacting secret scan for release inputs.

Generated runtime logs, model weights and dist install trees are deliberately
outside the release source scan. The scanner reports only path/line/category;
it never prints the matched value.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


SKIP_DIRS = {".git", ".venv", "venv", "runtime", "dist", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {
    ".cfg", ".conf", ".css", ".csv", ".html", ".ini", ".json", ".js", ".md",
    ".ps1", ".py", ".toml", ".txt", ".yaml", ".yml", ".mjs", ".lock",
}
PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]+ PRIVATE KEY-----")),
    ("api_key_literal", re.compile(r"\b(?:sk|rk)-[A-Za-z0-9]{20,}\b")),
    (
        "bearer_literal",
        re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
    ),
)


def iter_release_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        if path.name in {".env", ".env.local", ".env.production"}:
            continue
        yield path


def scan_file(path: Path, root: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for category, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(
                    {
                        "path": str(path.relative_to(root)).replace("\\", "/"),
                        "line": line_number,
                        "category": category,
                        "value_redacted": True,
                    }
                )
    return findings


def scan_tree(root: Path) -> dict[str, Any]:
    resolved = root.resolve()
    findings: list[dict[str, Any]] = []
    files_scanned = 0
    for path in iter_release_files(resolved):
        files_scanned += 1
        findings.extend(scan_file(path, resolved))
    return {
        "schema_version": 1,
        "root": str(resolved),
        "files_scanned": files_scanned,
        "findings": findings,
        "pass": not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = scan_tree(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
