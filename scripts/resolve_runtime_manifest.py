"""Print the validated effective runtime manifest as one JSON document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jawl_voicecompanion.runtime_manifest import load_runtime_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    try:
        manifest = load_runtime_manifest(args.repo_root, manifest_path=args.manifest)
    except (OSError, ValueError, RecursionError):
        print("runtime manifest could not be resolved", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
