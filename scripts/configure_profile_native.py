"""Apply explicit native capability switches to one disposable JAWL profile.

The repository baseline stays fail-closed (sandbox, Debug Broker disabled).
This helper changes only the selected profile after ``prepare_daily_profile``
has copied the managed configuration.  JAWL still owns the policy, registry,
approval and execution path; this file only selects profile configuration.
"""

from __future__ import annotations

import argparse
import os
import json
from pathlib import Path

try:
    from native_context_budget import budget_for_window, RECEIPT_NAME
except ModuleNotFoundError:
    from scripts.native_context_budget import budget_for_window, RECEIPT_NAME

try:
    import yaml
except ImportError as exc:  # pragma: no cover - owned runtime supplies PyYAML
    raise RuntimeError("PyYAML is required to configure a JAWL profile") from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTANCES_ROOT = REPO_ROOT / "runtime" / "instances"


def _profile_root(name: str) -> Path:
    value = name.strip()
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError("profile must be one safe directory name")
    root = (INSTANCES_ROOT / value).resolve()
    if root.parent != INSTANCES_ROOT.resolve():
        raise ValueError("profile must remain inside runtime/instances")
    return root


def configure(
    profile: str,
    *,
    access_level: int,
    enable_debug_broker: bool,
    model_override: str = "",
    temperature_override: str = "",
    enable_browser: bool = False,
    context_window_tokens: int = 0,
) -> Path:
    if access_level not in range(4):
        raise ValueError("access_level must be 0, 1, 2 or 3")
    context_budget = budget_for_window(context_window_tokens)
    profile_root = _profile_root(profile)
    path = profile_root / "config" / "interfaces.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"prepared profile interfaces are missing: {path}")
    model_override = model_override.strip()
    if len(model_override) > 200:
        raise ValueError("model_override exceeds 200 characters")
    temperature_override = temperature_override.strip()
    temperature = None
    if temperature_override:
        try:
            temperature = float(temperature_override)
        except ValueError as exc:
            raise ValueError("temperature_override must be a number from 0 to 2") from exc
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature_override must be a number from 0 to 2")

    if model_override or temperature is not None or context_budget:
        settings_path = profile_root / "config" / "settings.yaml"
        if not settings_path.is_file():
            raise FileNotFoundError(f"prepared profile settings are missing: {settings_path}")
        settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError("profile settings must be a YAML mapping")
        llm = settings.get("llm")
        if not isinstance(llm, dict):
            raise ValueError("profile settings must contain an llm mapping")
        if model_override:
            llm["main_model"] = model_override
        if temperature is not None:
            llm["temperature"] = temperature
        if context_budget:
            settings.setdefault("system", {}).setdefault("context_depth", {}).setdefault("budget", {}).update(context_budget)
        settings_tmp = settings_path.with_name(settings_path.name + ".model.tmp")
        settings_tmp.write_text(
            yaml.safe_dump(settings, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(settings_tmp, settings_path)
        if context_budget:
            receipt_path = profile_root / RECEIPT_NAME
            receipt_tmp = receipt_path.with_suffix(".tmp")
            receipt_tmp.write_text(json.dumps({"schema_version": 1,
                                              "context_window_tokens": context_window_tokens,
                                              "budget": context_budget}, indent=2), encoding="utf-8")
            os.replace(receipt_tmp, receipt_path)

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("profile interfaces must be a YAML mapping")
    host = payload.get("host")
    if not isinstance(host, dict) or not isinstance(host.get("os"), dict):
        raise ValueError("profile interfaces must contain host.os mapping")
    host_os = host["os"]
    host_os["access_level"] = access_level

    broker = payload.get("debug_broker")
    if not isinstance(broker, dict):
        broker = {}
        payload["debug_broker"] = broker
    broker["enabled"] = bool(enable_debug_broker)

    if enable_browser:
        web = payload.setdefault("web", {})
        if not isinstance(web, dict):
            raise ValueError("profile interfaces must contain a web mapping")
        browser = web.setdefault("browser", {})
        if not isinstance(browser, dict):
            raise ValueError("profile web.browser must be a mapping")
        browser["enabled"] = True
        browser.setdefault("headless", True)

    temporary = path.with_name(path.name + ".native.tmp")
    temporary.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--access-level", type=int, choices=range(4), default=0)
    parser.add_argument("--enable-debug-broker", action="store_true")
    parser.add_argument("--model-override", default="")
    parser.add_argument("--temperature-override", default="")
    parser.add_argument("--enable-browser", action="store_true")
    parser.add_argument("--context-window-tokens", type=int, default=0)
    args = parser.parse_args()
    path = configure(
        args.profile,
        access_level=args.access_level,
        enable_debug_broker=args.enable_debug_broker,
        model_override=args.model_override,
        temperature_override=args.temperature_override,
        enable_browser=args.enable_browser,
        context_window_tokens=args.context_window_tokens,
    )
    print(
        f"configured profile={args.profile} access_level={args.access_level} "
        f"debug_broker={str(args.enable_debug_broker).lower()} path={path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
