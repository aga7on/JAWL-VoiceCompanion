"""Apply the wrapper's LLM overrides directly into the instance settings.yaml.

Why: JAWL reads llm.temperature / llm.main_model from config at startup.
The launcher's env overrides (JAWL_TEMPERATURE_OVERRIDE, JAWL_MODEL_OVERRIDE)
were only *validated* by prepare_daily_profile.py when the instance file
differed from the repository baseline - when they matched (the usual case),
nothing was ever written, so the brain silently ran at the baseline values.

This script is the single writer: it sets the overrides atomically before
the profile starts, and prepare_daily_profile then approves the exact
values (its override checks compare against these same envs).

Usage:
  python -X utf8 scripts/apply_llm_overrides.py --profile daily
Env:
  JAWL_TEMPERATURE_OVERRIDE  (optional, 0..2)
  JAWL_MODEL_OVERRIDE        (optional)
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="daily")
    args = parser.parse_args()

    settings = REPO / "runtime" / "instances" / args.profile / "config" / "settings.yaml"
    if not settings.is_file():
        print(f"[overrides] settings.yaml not found: {settings}", file=sys.stderr)
        return 2

    data = yaml.safe_load(settings.read_text(encoding="utf-8")) or {}
    llm = data.setdefault("llm", {})
    changed = []

    temperature = os.environ.get("JAWL_TEMPERATURE_OVERRIDE", "").strip()
    if temperature:
        value = float(temperature)
        if not 0.0 <= value <= 2.0:
            print(f"[overrides] temperature out of range: {value}", file=sys.stderr)
            return 2
        if llm.get("temperature") != value:
            llm["temperature"] = value
            changed.append(f"temperature={value}")

    model = os.environ.get("JAWL_MODEL_OVERRIDE", "").strip()
    if model and llm.get("main_model") != model:
        llm["main_model"] = model
        changed.append(f"main_model={model}")

    if not changed:
        print("[overrides] nothing to change")
        return 0

    # atomic replace: no partially written config for a concurrent reader
    fd, tmp_name = tempfile.mkstemp(prefix=".settings.", dir=str(settings.parent), suffix=".yaml")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.replace(tmp, settings)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    print(f"[overrides] applied: {', '.join(changed)} -> {settings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())