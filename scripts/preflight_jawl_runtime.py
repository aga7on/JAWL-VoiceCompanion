"""Fail-fast checks for the owned daily JAWL profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_ROOT = REPO_ROOT / "runtime" / "instances" / "daily"
REQUIRED = (
    PROFILE_ROOT / "config" / "settings.yaml",
    PROFILE_ROOT / "config" / "interfaces.yaml",
    PROFILE_ROOT / "prompts" / "personality" / "SOUL.md",
    PROFILE_ROOT / "data" / "vector" / "embeddings" / "models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q" / "snapshots" / "faf4aa4225822f3bc6376869cb1164e8e3feedd0" / "model_optimized.onnx",
)


def check(*, allow_missing_model: bool = False) -> dict[str, object]:
    missing = [str(path) for path in REQUIRED if not path.is_file()]
    model = str(REQUIRED[-1])
    if allow_missing_model:
        missing = [path for path in missing if path != model]
    result = {
        "ok": not missing,
        "profile": str(PROFILE_ROOT),
        "embedding_cache": "ready" if Path(model).is_file() else "missing",
        "missing": missing,
    }
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
