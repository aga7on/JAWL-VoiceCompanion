"""Build an immutable source snapshot; never import or start the reference JAWL."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"__pycache__", "local", "data", "logs", "runtime", ".venv", "venv"}
SOURCE_TYPES = {".py", ".java", ".md"}
WEB_TYPES = {".html", ".css", ".js", ".svg", ".png", ".ico", ".woff2"}


def selected(relative: Path) -> bool:
    parts = relative.parts
    if any(part in EXCLUDED for part in parts):
        return False
    if relative.as_posix() in {
        "LICENSE", "requirements.txt", "pyproject.toml",
        "config/settings.example.yaml", "config/interfaces.example.yaml",
    }:
        return True
    if parts[0] == "src" and relative.suffix in SOURCE_TYPES:
        if "personality" in parts and relative.suffix == ".md":
            return relative.name.endswith(".example.md")
        return True
    return parts[0] == "web" and relative.suffix in WEB_TYPES


def inventory(source: Path) -> list[tuple[Path, bytes]]:
    source = source.resolve(strict=True)
    result = []
    # Walk only source/resource roots. No .env, logs, databases or working config reads.
    candidates = [source / name for name in ("LICENSE", "requirements.txt", "pyproject.toml")]
    candidates += [source / "config" / name for name in ("settings.example.yaml", "interfaces.example.yaml")]
    for name in ("src", "web"):
        pending = [source / name]
        while pending:
            directory = pending.pop()
            if directory.is_symlink() or directory.resolve() != directory:
                raise ValueError("source contains redirected directories")
            for entry in directory.iterdir():
                if entry.name in EXCLUDED:
                    continue
                if entry.is_symlink() or entry.resolve() != entry:
                    raise ValueError("source contains redirected entries")
                if entry.is_dir():
                    pending.append(entry)
                else:
                    candidates.append(entry)
    for path in sorted(candidates):
        relative = path.relative_to(source)
        if not selected(relative):
            continue
        if path.resolve() != path or not path.is_file():
            raise ValueError("missing or redirected source file")
        data = path.read_bytes()
        if len(data) > 5_000_000:
            raise ValueError("source file exceeds snapshot bound")
        if re.search(rb"sk-[A-Za-z0-9_-]{24,}", data):
            raise ValueError("key-shaped material detected; snapshot aborted without disclosure")
        result.append((relative, data))
    return result


def stage(source: Path, name: str, *, write: bool = False) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", name):
        raise ValueError("invalid snapshot name")
    destination = ROOT / "runtime" / "jawl-sources" / name
    if destination.resolve() != destination or destination.exists():
        raise ValueError("snapshot target already exists or is redirected")
    files = inventory(source)
    hashes = {path.as_posix(): hashlib.sha256(data).hexdigest() for path, data in files}
    manifest = {
        "schema_version": 1, "kind": "source-snapshot", "name": name,
        "files": hashes, "file_count": len(files),
        "snapshot_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        "runtime_ready": False,
    }
    if write:
        destination.mkdir(parents=True, exist_ok=False)
        # Manifest is written last. Interrupted builds are visibly incomplete.
        for relative, data in files:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
        with (destination / "SOURCE_MANIFEST.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
    return {key: value for key, value in manifest.items() if key != "files"} | {"written": write}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("name")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.name, write=args.write), indent=2))
