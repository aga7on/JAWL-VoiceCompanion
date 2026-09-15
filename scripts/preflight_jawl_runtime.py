"""Fail-fast checks for the owned daily JAWL profile."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from .verify_jawl_snapshot import DEFAULT_SOURCE, verify
except ImportError:  # direct script execution
    from verify_jawl_snapshot import DEFAULT_SOURCE, verify


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_NAME = os.environ.get("JAWL_PROFILE_NAME", "daily").strip() or "daily"
if Path(PROFILE_NAME).name != PROFILE_NAME or PROFILE_NAME in {".", ".."}:
    raise ValueError("JAWL_PROFILE_NAME must be one safe directory name")
PROFILE_ROOT = REPO_ROOT / "runtime" / "instances" / PROFILE_NAME
REQUIRED_DIRECTORIES = (
    PROFILE_ROOT / "data",
    PROFILE_ROOT / "logs",
    PROFILE_ROOT / "cache",
    PROFILE_ROOT / "sandbox",
)
REQUIRED = (
    PROFILE_ROOT / "config" / "settings.yaml",
    PROFILE_ROOT / "config" / "interfaces.yaml",
    PROFILE_ROOT / "prompts" / "personality" / "SOUL.md",
    PROFILE_ROOT / ".managed-files.json",
    PROFILE_ROOT / "data" / "vector" / "embeddings" / "models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q" / "snapshots" / "faf4aa4225822f3bc6376869cb1164e8e3feedd0" / "model_optimized.onnx",
)


def check(*, allow_missing_model: bool = False) -> dict[str, object]:
    missing = [str(path) for path in REQUIRED if not path.is_file()]
    missing += [str(path) for path in REQUIRED_DIRECTORIES if not path.is_dir()]
    model = str(REQUIRED[-1])
    if allow_missing_model:
        missing = [path for path in missing if path != model]
    source_error = None
    source_result: dict[str, object] | None = None
    profile_source_error = None
    try:
        source_result = verify(DEFAULT_SOURCE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        source_error = str(exc)[:240]
    manifest_path = PROFILE_ROOT / ".managed-files.json"
    if not source_error and manifest_path.is_file():
        try:
            profile_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if profile_manifest.get("source") != {
                "name": source_result["name"],
                "snapshot_sha256": source_result["snapshot_sha256"],
                "file_count": source_result["file_count"],
            }:
                profile_source_error = "profile managed manifest points to a different JAWL snapshot"
        except (OSError, ValueError, json.JSONDecodeError, AttributeError) as exc:
            profile_source_error = f"managed profile manifest is invalid: {str(exc)[:160]}"
    result = {
        "ok": not missing,
        "profile": str(PROFILE_ROOT),
        "source": source_result or {"ok": False, "error": source_error},
        "profile_source": "matched" if not profile_source_error else "mismatch",
        "embedding_cache": "ready" if Path(model).is_file() else "missing",
        "missing": missing,
    }
    if source_error or profile_source_error:
        result["ok"] = False
    if profile_source_error:
        result["source_error"] = profile_source_error
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check owned JAWL daily runtime readiness")
    parser.add_argument("--allow-missing-model", action="store_true")
    args = parser.parse_args()
    result = check(allow_missing_model=args.allow_missing_model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
