"""Capture reviewable, metadata-only source identity without committing changes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jawl_voicecompanion.runtime_manifest import load_runtime_manifest
from verify_jawl_snapshot import verify

SOURCE_PREFIXES = ("src/", "scripts/", "tests/", "desktop/", "rust-client/src/", "config/", "tools/")
SOURCE_SUFFIXES = {".py", ".ps1", ".js", ".mjs", ".json", ".rs", ".toml", ".html", ".css", ".yaml"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def capture(root: Path) -> dict:
    root = root.resolve(strict=True)
    manifest = load_runtime_manifest(root)
    paths = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode("utf-8").split("\x00")
    sources = {}
    for relative in sorted(set(paths)):
        path = root / relative
        if (
            not relative.startswith(SOURCE_PREFIXES)
            or path.suffix not in SOURCE_SUFFIXES
            or path.name == "runtime.manifest.local.json"
            or path.is_symlink()
            or not path.is_file()
            or root not in path.resolve().parents
            or path.stat().st_size > 4 * 1024 * 1024
        ):
            continue
        sources[relative] = sha(path.read_bytes())
    status = git(root, "status", "--porcelain=v1", "--untracked-files=normal")
    # Diff content is never printed or persisted. Exclude credential files even
    # if accidentally tracked. Untracked sources are covered by the hash map.
    diff = git(root, "diff", "HEAD", "--no-ext-diff", "--binary", "--", ".",
               ":(exclude)**/.env*", ":(exclude)*.key", ":(exclude)*.pem",
               ":(exclude)*.token", ":(exclude)config/runtime.manifest.local.json")
    inventory = {}
    for key, value in manifest["models"].items():
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        stat = path.stat() if path.is_file() else None
        inventory[key] = {
            "present": path.exists(), "bytes": stat.st_size if stat else None,
            "mtime_ns": stat.st_mtime_ns if stat else None,
            "sha256": file_sha(path) if stat and stat.st_size <= 128 * 1024 * 1024 and path.suffix == ".exe" else None,
        }
    assets = {}
    asset_root = root / "runtime" / "vrm-models"
    asset_hash_budget = 256 * 1024 * 1024
    for path in sorted(asset_root.glob("*.vrm"))[:64]:
        if not path.is_symlink() and root in path.resolve().parents:
            stat = path.stat()
            digest = None
            if stat.st_size <= asset_hash_budget:
                digest = file_sha(path)
                asset_hash_budget -= stat.st_size
            assets[path.name] = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}
    versions = {}
    for name in ("jawl-voicecompanion", "aiohttp", "crispasr", "numpy"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "schema_version": 1,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "post-slice working-tree metadata; not release, provider, device or art acceptance",
        "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "dirty": bool(status), "status_sha256": sha(status), "dirty_diff_sha256": sha(diff),
        "source_count": len(sources), "source_hashes": sources,
        "source_sha256": sha(json.dumps(sources, sort_keys=True).encode()),
        "snapshot": verify(root / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"),
        "python": platform.python_version(), "installed_packages": versions,
        "worker_files": inventory, "asset_metadata": assets,
        "asset_limit": "max64, hash budget256MiB; active avatar not selected or changed; no likeness inference",
        "effective": {key: manifest[key] for key in ("profile", "ports", "brain", "vision", "launch")},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    target = args.report.resolve()
    runtime = (ROOT / "runtime").resolve()
    if ROOT.resolve() not in runtime.parents or runtime not in target.parents or target.suffix != ".json" or target.exists():
        parser.error("report must be a new JSON file inside this repo's runtime directory")
    try:
        result = capture(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
    except (ValueError, OSError, subprocess.SubprocessError):
        print("baseline capture failed; inspect configuration/snapshot without exposing secrets", file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "report": str(target), "head": result["head"],
                      "source_count": result["source_count"], "source_sha256": result["source_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
