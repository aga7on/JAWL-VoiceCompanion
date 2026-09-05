"""Small, secret-free manifest contract for reproducible Companion profiles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_TOP = frozenset({"schema_version", "profile_id", "paths", "ports", "components", "consent"})
_PATHS = frozenset({"config", "data", "logs", "cache", "sandbox"})
_CONSENT = frozenset({"microphone", "system_audio", "screen", "unattended", "social_publish"})
_SECRET_WORDS = ("token", "secret", "password", "api_key", "credential")


def _text(value: Any, field: str, limit: int = 160) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{field} must be a bounded non-empty string")
    return value.strip()


def _relative_path(value: Any, field: str) -> str:
    value = _text(value, field, 240)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a relative path inside the profile root")
    return path.as_posix()


def _reject_secret_keys(value: Any, where: str = "profile") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).casefold()
            if any(word in name for word in _SECRET_WORDS):
                raise ValueError(f"{where} contains a secret-bearing field")
            _reject_secret_keys(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_keys(item, f"{where}[{index}]")


@dataclass(frozen=True)
class RuntimeProfile:
    schema_version: int
    profile_id: str
    paths: dict[str, str]
    ports: dict[str, Any]
    components: dict[str, dict[str, Any]]
    consent: dict[str, bool]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RuntimeProfile":
        if not isinstance(raw, Mapping):
            raise ValueError("runtime profile must be an object")
        _reject_secret_keys(raw)
        if set(raw) != _TOP:
            raise ValueError("runtime profile fields do not match schema v1")
        if raw["schema_version"] != 1 or isinstance(raw["schema_version"], bool):
            raise ValueError("unsupported runtime profile schema")
        profile_id = _text(raw["profile_id"], "profile_id", 64)
        if not _ID.fullmatch(profile_id):
            raise ValueError("profile_id contains unsupported characters")

        paths = raw["paths"]
        if not isinstance(paths, Mapping) or set(paths) != _PATHS:
            raise ValueError("paths must contain exactly config/data/logs/cache/sandbox")
        safe_paths = {key: _relative_path(paths[key], f"paths.{key}") for key in sorted(_PATHS)}

        ports = raw["ports"]
        if not isinstance(ports, Mapping) or set(ports) != {"control", "presentation", "reserved"}:
            raise ValueError("ports must contain control/presentation/reserved")
        values: dict[str, Any] = {}
        for key in ("control", "presentation"):
            value = ports[key]
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                raise ValueError(f"ports.{key} must be a valid TCP port")
            values[key] = value
        reserved = ports["reserved"]
        if not isinstance(reserved, list) or len(reserved) > 16:
            raise ValueError("ports.reserved must be a bounded array")
        for index, value in enumerate(reserved):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                raise ValueError(f"ports.reserved[{index}] must be a valid TCP port")
        if len(set(values.values())) != len(values) or set(values.values()) & set(reserved):
            raise ValueError("profile ports collide with each other or a reserved port")
        values["reserved"] = tuple(sorted(set(reserved)))

        components = raw["components"]
        if not isinstance(components, Mapping) or not components or len(components) > 16:
            raise ValueError("components must be a bounded non-empty object")
        safe_components: dict[str, dict[str, Any]] = {}
        for name, component in components.items():
            name = _text(name, "component name", 64)
            if not _ID.fullmatch(name) or not isinstance(component, Mapping):
                raise ValueError("component name or value is invalid")
            if set(component) - {"enabled", "version", "provider", "model"}:
                raise ValueError(f"components.{name} contains unknown fields")
            if not isinstance(component.get("enabled"), bool):
                raise ValueError(f"components.{name}.enabled must be boolean")
            safe_components[name] = {
                "enabled": component["enabled"],
                **{
                    key: _text(component[key], f"components.{name}.{key}", 128)
                    for key in ("version", "provider", "model")
                    if key in component
                },
            }

        consent = raw["consent"]
        if not isinstance(consent, Mapping) or set(consent) != _CONSENT:
            raise ValueError("consent fields do not match schema v1")
        safe_consent = {}
        for key in sorted(_CONSENT):
            if not isinstance(consent[key], bool):
                raise ValueError(f"consent.{key} must be boolean")
            safe_consent[key] = consent[key]
        return cls(1, profile_id, safe_paths, values, safe_components, safe_consent)

    @classmethod
    def load(cls, path: Path) -> "RuntimeProfile":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("runtime profile could not be read as JSON") from exc
        return cls.from_mapping(raw)

    def resolved_paths(self, root: Path) -> dict[str, Path]:
        base = Path(root).resolve()
        result = {}
        for key, relative in self.paths.items():
            candidate = (base / relative).resolve()
            try:
                candidate.relative_to(base)
            except ValueError as exc:
                raise ValueError(f"resolved paths.{key} escapes the profile root") from exc
            result[key] = candidate
        return result

    def summary(self) -> dict[str, Any]:
        """Return a safe diagnostic projection; no credentials or absolute paths."""
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "paths": dict(self.paths),
            "ports": {"control": self.ports["control"], "presentation": self.ports["presentation"]},
            "components": dict(self.components),
            "consent": dict(self.consent),
        }


__all__ = ["RuntimeProfile"]
