"""Validate one secret-free Companion runtime manifest without starting services."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jawl_voicecompanion.runtime_profile import RuntimeProfile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    try:
        profile = RuntimeProfile.load(args.profile)
        resolved = profile.resolved_paths(args.root or args.profile.parent.parent)
    except ValueError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "valid", "profile": profile.summary(), "resolved_paths": {
        key: str(value) for key, value in resolved.items()
    }}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
