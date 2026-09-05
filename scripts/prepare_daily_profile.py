"""Prepare the owned JAWL daily profile from the pinned source snapshot.

The operation is intentionally idempotent and never overwrites an existing
runtime file. Working config and the owned SOUL are the repository's source of
truth; the JAWL source tree supplies only prompt assets and runtime defaults.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "runtime" / "jawl-sources" / "jawl-20260905-daily-v1"
CONFIG_ROOT = REPO_ROOT / "config" / "jawl"
PROFILE_ROOT = REPO_ROOT / "runtime" / "instances" / "daily"


def copy_missing(source: Path, target: Path) -> int:
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return 1


def prepare() -> list[str]:
    if not SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"Pinned JAWL source is missing: {SOURCE_ROOT}")
    prompt_source = SOURCE_ROOT / "src" / "l3_agent" / "prompt"
    prompt_target = PROFILE_ROOT / "prompts"
    copied = 0
    for source in prompt_source.rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts:
            copied += copy_missing(source, prompt_target / source.relative_to(prompt_source))

    copied += copy_missing(
        CONFIG_ROOT / "SOUL.md", prompt_target / "personality" / "SOUL.md"
    )
    copied += copy_missing(CONFIG_ROOT / "settings.yaml", PROFILE_ROOT / "config" / "settings.yaml")
    copied += copy_missing(
        CONFIG_ROOT / "interfaces.yaml", PROFILE_ROOT / "config" / "interfaces.yaml"
    )
    for directory in (
        PROFILE_ROOT / "data",
        PROFILE_ROOT / "logs",
        PROFILE_ROOT / "sandbox",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return [f"created_files={copied}", f"profile={PROFILE_ROOT}", f"soul={prompt_target / 'personality' / 'SOUL.md'}"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the owned JAWL daily profile")
    parser.parse_args()
    for line in prepare():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
