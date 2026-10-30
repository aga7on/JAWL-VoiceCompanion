"""Load and validate the shared, secret-free Companion runtime manifest."""

from __future__ import annotations

import copy
import ipaddress
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_NAME = "runtime.manifest.json"
_LOCAL_MANIFEST_NAME = "runtime.manifest.local.json"
_MAX_JSON_BYTES = 128 * 1024
_SAFE_NON_SECRET_KEYS = frozenset({"max_output_tokens"})
_SECRET_WORDS = (
    "token",
    "secret",
    "password",
    "api_key",
    "private_key",
    "access_key",
    "credential",
    "authorization",
)
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")

_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "created",
        "purpose",
        "repo_root",
        "profile",
        "ports",
        "models",
        "mic",
        "brain",
        "profile_script",
        "launch",
        "vision",
        "audio",
    }
)
_PORT_KEYS = frozenset(
    {
        "control",
        "jawl_console",
        "opencode_relay",
        "qwen3_vl",
        "bonsai_coding",
        "tera_tts",
        "brain_port",
        "reserved",
    }
)
_MODEL_PATH_KEYS = frozenset(
    {
        "llama_server_exe",
        "brain_server_exe",
        "qwen3_vl_model",
        "qwen3_vl_mmproj",
        "bonsai_model",
        "bonsai_mmproj",
        "tera_python",
        "tera_release",
    }
)
_BRAIN_KEYS = frozenset(
    {
        "provider",
        "model",
        "llm_url",
        "use_relay",
        "raised_by",
        "relay_override",
        "context_size",
        "max_output_tokens",
        "device",
        "threads",
        "gpu_layers",
    }
)
_RELAY_KEYS = frozenset({"note", "model", "relay_port"})


def _reject_secret_keys(value: Any) -> None:
    """Reject credential-like keys at any depth without echoing the key."""
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > 64:
            raise ValueError("runtime manifest nesting exceeds the limit")
        if isinstance(current, dict):
            for key, child in current.items():
                folded = key.casefold()
                if folded not in _SAFE_NON_SECRET_KEYS and any(word in folded for word in _SECRET_WORDS):
                    raise ValueError("runtime manifest contains a secret-bearing field")
                pending.append((child, depth + 1))
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("runtime manifest contains duplicate fields")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as source:
            raw_bytes = source.read(_MAX_JSON_BYTES + 1)
    except OSError:
        raise ValueError("runtime manifest is not readable JSON") from None
    if len(raw_bytes) > _MAX_JSON_BYTES:
        raise ValueError("runtime manifest exceeds the size limit")
    try:
        decoded = raw_bytes.decode("utf-8")
        raw = json.loads(decoded, object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ValueError("runtime manifest is not readable JSON") from None
    if not isinstance(raw, dict):
        raise ValueError("runtime manifest must be a JSON object")
    _reject_secret_keys(raw)
    return raw


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a recursive merge without mutating either input mapping."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _validate_keys(value: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    if set(value) - allowed:
        raise ValueError(f"runtime manifest has unsupported fields in {where}")


def _text(value: Any, where: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"runtime manifest has an invalid {where}")
    return value


def _label(value: Any, where: str) -> str:
    value = _text(value, where, 128)
    if not _SAFE_LABEL.fullmatch(value):
        raise ValueError(f"runtime manifest has an invalid {where}")
    return value


def _port(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError(f"runtime manifest has an invalid {where}")
    return value


def _loopback_url(value: Any, where: str) -> tuple[str, int]:
    text = _text(value, where, 2048)
    try:
        parsed = urlsplit(text)
        host = parsed.hostname
        port = parsed.port
        is_loopback = host == "localhost"
        if host is not None and not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
    except ValueError as exc:
        raise ValueError(f"runtime manifest has an invalid {where}") from exc
    if (
        parsed.scheme != "http"
        or not is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is None
        or parsed.path not in ("/v1", "/v1/")
    ):
        raise ValueError(f"runtime manifest has an invalid {where}")
    return text, port


def _apply_legacy_defaults(config: dict[str, Any]) -> None:
    """Fill newer fields in-place on the private merged copy only."""
    for section in ("ports", "models", "brain", "launch", "vision", "audio"):
        config.setdefault(section, {})
    ports = config["ports"]
    models = config["models"]
    brain = config["brain"]
    launch = config["launch"]
    vision = config["vision"]
    audio = config["audio"]
    if not all(isinstance(value, dict) for value in (ports, models, brain, launch, vision, audio)):
        raise ValueError("runtime manifest contains an invalid section")

    old_llm_url = brain.get("llm_url")
    inferred_port: int | None = None
    if isinstance(old_llm_url, str):
        try:
            parsed = urlsplit(old_llm_url)
            inferred_port = parsed.port
        except ValueError:
            pass
    # ADR-052: the second presentation port is gone (single origin on the
    # control port). Accepted and dropped for one release so persisted
    # manifests keep loading; remove this drop after the next release.
    ports.pop("presentation", None)

    ports.setdefault("brain_port", inferred_port or 8990)

    models.setdefault("brain_server_exe", models.get("llama_server_exe", "llama-server.exe"))

    brain.setdefault("llm_url", f"http://127.0.0.1:{ports['brain_port']}/v1")
    brain.setdefault("context_size", 65536)
    brain.setdefault("max_output_tokens", 2048)
    brain.setdefault("device", "CUDA1")
    brain.setdefault("threads", 12)
    brain.setdefault("gpu_layers", 99)

    launch.setdefault("run_seconds", 0)
    launch.setdefault("tts_provider", "tera")

    vision.setdefault("url", "http://127.0.0.1:8986/v1")
    vision.setdefault("model", "bonsai")
    vision.setdefault("auto_start", False)
    audio.setdefault("loopback_output_device_name", "")


def _validate(config: dict[str, Any]) -> dict[str, Any]:
    _validate_keys(config, _TOP_LEVEL, "root")
    version = config.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ValueError("runtime manifest schema version is unsupported")

    for key in ("created", "purpose", "repo_root", "profile", "profile_script"):
        if key in config:
            _text(config[key], key)
    profile = config.get("profile", "daily")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", profile):
        raise ValueError("runtime manifest profile must be one safe directory name")
    if profile.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("runtime manifest profile uses a reserved directory name")

    ports = config.get("ports")
    if not isinstance(ports, dict):
        raise ValueError("runtime manifest ports must be an object")
    _validate_keys(ports, _PORT_KEYS, "ports")
    service_ports: dict[str, int] = {}
    for key, value in ports.items():
        if key == "reserved":
            continue
        service_ports[key] = _port(value, f"ports.{key}")
    reserved = ports.get("reserved", [])
    if not isinstance(reserved, list) or len(reserved) > 64:
        raise ValueError("runtime manifest has invalid reserved ports")
    reserved_ports = {_port(item, "ports.reserved") for item in reserved}
    reserved_ports.add(8765)
    if any(value == 8765 for value in service_ports.values()):
        raise ValueError("runtime manifest uses a reserved port")
    if len(set(service_ports.values())) != len(service_ports):
        raise ValueError("runtime manifest ports collide")
    if set(service_ports.values()) & reserved_ports:
        raise ValueError("runtime manifest ports collide with a reserved port")

    models = config.get("models")
    if not isinstance(models, dict):
        raise ValueError("runtime manifest models must be an object")
    _validate_keys(models, _MODEL_PATH_KEYS, "models")
    for key, value in models.items():
        _text(value, f"models.{key}")

    mic = config.get("mic", {})
    if not isinstance(mic, dict):
        raise ValueError("runtime manifest mic must be an object")
    _validate_keys(mic, frozenset({"prefer"}), "mic")
    if "prefer" in mic:
        _label(mic["prefer"], "mic.prefer")

    brain = config.get("brain")
    if not isinstance(brain, dict):
        raise ValueError("runtime manifest brain must be an object")
    _validate_keys(brain, _BRAIN_KEYS, "brain")
    _label(brain.get("model"), "brain.model")
    for key in ("provider", "model", "device"):
        if key in brain and key != "model":
            _label(brain[key], f"brain.{key}")
    for key in ("raised_by",):
        if key in brain:
            _text(brain[key], f"brain.{key}")
    resource_ranges = {
        "context_size": (512, 1_048_576),
        "max_output_tokens": (1, 65_536),
        "threads": (1, 128),
        "gpu_layers": (0, 256),
    }
    for key, (minimum, maximum) in resource_ranges.items():
        if key in brain and (
            isinstance(brain[key], bool)
            or not isinstance(brain[key], int)
            or not minimum <= brain[key] <= maximum
        ):
            raise ValueError(f"runtime manifest has an invalid brain.{key}")
    if brain["max_output_tokens"] >= brain["context_size"]:
        raise ValueError("runtime manifest output budget must be smaller than its context")
    if "use_relay" in brain and not isinstance(brain["use_relay"], bool):
        raise ValueError("runtime manifest has an invalid brain.use_relay")
    if "relay_override" in brain:
        relay = brain["relay_override"]
        if not isinstance(relay, dict):
            raise ValueError("runtime manifest has an invalid relay override")
        _validate_keys(relay, _RELAY_KEYS, "brain.relay_override")
        if "model" in relay:
            _label(relay["model"], "brain.relay_override.model")
        if "relay_port" in relay:
            _port(relay["relay_port"], "brain.relay_override.relay_port")
        if "note" in relay:
            _text(relay["note"], "brain.relay_override.note")
    _, llm_port = _loopback_url(brain.get("llm_url"), "brain.llm_url")
    if llm_port != service_ports.get("brain_port"):
        raise ValueError("runtime manifest brain URL does not match its port")

    launch = config.get("launch")
    if not isinstance(launch, dict):
        raise ValueError("runtime manifest launch must be an object")
    _validate_keys(launch, frozenset({"run_seconds", "tts_provider"}), "launch")
    if "run_seconds" in launch and (
        isinstance(launch["run_seconds"], bool)
        or not isinstance(launch["run_seconds"], int)
        or launch["run_seconds"] < 0
    ):
        raise ValueError("runtime manifest has an invalid launch.run_seconds")
    if "tts_provider" in launch:
        _label(launch["tts_provider"], "launch.tts_provider")
        if launch["tts_provider"] not in {"tera", "omnivoice", "voxcpm"}:
            raise ValueError("runtime manifest has an unsupported launch.tts_provider")

    vision = config.get("vision")
    if not isinstance(vision, dict):
        raise ValueError("runtime manifest vision must be an object")
    _validate_keys(vision, frozenset({"url", "model", "alias", "auto_start"}), "vision")
    if "url" in vision:
        _loopback_url(vision["url"], "vision.url")
    for key in ("model", "alias"):
        if key in vision:
            _label(vision[key], f"vision.{key}")
    if "auto_start" in vision and not isinstance(vision["auto_start"], bool):
        raise ValueError("runtime manifest has an invalid vision.auto_start")

    audio = config.get("audio")
    if not isinstance(audio, dict):
        raise ValueError("runtime manifest audio must be an object")
    _validate_keys(audio, frozenset({"loopback_output_device_name"}), "audio")
    device_name = audio.get("loopback_output_device_name", "")
    if not isinstance(device_name, str) or len(device_name) > 160 or "\x00" in device_name:
        raise ValueError("runtime manifest has an invalid audio.loopback_output_device_name")

    return config


def load_runtime_manifest(
    repo_root: Path | None = None,
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Load canonical and optional local manifests, merge, default, and validate.

    ``manifest_path`` selects the canonical file. Its sibling override is named
    ``runtime.manifest.local.json``. No paths or model files are created or
    required to exist during resolution.
    """
    root = Path(repo_root) if repo_root is not None else _DEFAULT_REPO_ROOT
    canonical = Path(manifest_path) if manifest_path is not None else root / "config" / _MANIFEST_NAME
    local = canonical.with_name(_LOCAL_MANIFEST_NAME)

    base = _read_json(canonical)
    override = _read_json(local) if local.exists() else {}
    effective = _deep_merge(base, override)
    _apply_legacy_defaults(effective)
    return _validate(effective)


__all__ = ["load_runtime_manifest"]
