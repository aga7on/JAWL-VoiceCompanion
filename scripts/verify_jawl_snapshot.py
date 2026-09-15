"""Verify the pinned, owned JAWL source snapshot without starting it."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"
MANIFEST_NAME = "SOURCE_MANIFEST.json"
_KEY_SHAPED = re.compile(rb"sk-[A-Za-z0-9_-]{24,}")


def _is_generated_bytecode(path: Path) -> bool:
    """Return whether *path* is interpreter cache, not source input."""

    return path.suffix.lower() == ".pyc" and "__pycache__" in path.parts


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(source: Path) -> dict[str, object]:
    source = source.resolve(strict=True)
    manifest_path = source / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("source manifest is missing or redirected")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict) or not files:
        raise ValueError("source manifest has no file hashes")

    actual: dict[str, str] = {}
    for relative, expected in sorted(files.items()):
        relative_path = Path(str(relative))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("source manifest contains an unsafe path")
        path = (source / relative_path).resolve()
        if path.parent != source and source not in path.parents:
            raise ValueError("source manifest path escapes snapshot")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"snapshot file is missing or redirected: {relative}")
        data = path.read_bytes()
        if len(data) > 5_000_000:
            raise ValueError(f"snapshot file exceeds bound: {relative}")
        if _KEY_SHAPED.search(data):
            raise ValueError("key-shaped material detected in source snapshot")
        digest = _hash(path)
        if digest != str(expected).lower():
            raise ValueError(f"snapshot hash mismatch: {relative}")
        actual[str(relative)] = digest

    actual_paths = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME and not _is_generated_bytecode(path)
    }
    manifest_paths = set(actual)
    extras = sorted(actual_paths - manifest_paths)
    if extras:
        raise ValueError(f"snapshot contains files absent from manifest: {', '.join(extras[:5])}")
    if manifest_paths - actual_paths:
        # The per-file loop normally catches this; keep an explicit invariant for
        # future changes to the traversal above.
        raise ValueError("source manifest contains files absent from snapshot")

    digest_input = json.dumps(actual, sort_keys=True).encode()
    snapshot_sha256 = hashlib.sha256(digest_input).hexdigest()
    if snapshot_sha256 != str(manifest.get("snapshot_sha256", "")).lower():
        raise ValueError("source snapshot digest does not match manifest")
    return {
        "ok": True,
        "source": str(source),
        "name": str(manifest.get("name", "")),
        "file_count": len(actual),
        "snapshot_sha256": snapshot_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    try:
        result = verify(args.source)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:240]}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
