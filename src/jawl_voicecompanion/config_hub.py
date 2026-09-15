"""Unified config hub: revision, secret masking, backups, readback.

The pinned JAWL snapshot owns the real writer semantics (in-place YAML
editing with CRLF/LF preservation, env prefix renumbering); this hub reuses
`web.config_io` + `web.schema` from the snapshot directly instead of
reimplementing them, and adds the U1 layer the snapshot lacks:

* revision — a content hash of settings.yaml + interfaces.yaml + .env,
  checked against the client's expected revision before writing;
* pre-save backups — rotated `*.pre-save-N.bak` copies before every write;
* secret masking — env secret fields are never returned in plaintext and
  `__SET__` round-trips without touching the stored value;
* readback — the written keys with their post-write values.

The console keeps working as before (transitional); the unified UI writes
only through this hub.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

_SNAPSHOT_SRC = Path(
    r"G:\AI\JAWL-VoiceCompanion\runtime\jawl-sources\jawl-20260906-daily-v2\src"
)


def _load_snapshot_modules():
    if str(_SNAPSHOT_SRC) not in sys.path:
        sys.path.insert(0, str(_SNAPSHOT_SRC))
    snapshot_root = _SNAPSHOT_SRC.parent
    if str(snapshot_root) not in sys.path:
        sys.path.insert(0, str(snapshot_root))
    from web import config_io as cio  # noqa: PLC0415 - pinned snapshot module
    from web import schema as schema  # noqa: F401 - re-exported for callers

    return cio, schema


SECRET_MARKERS = ("KEY", "TOKEN", "PASSWORD", "SECRET", "HASH")


class ConfigHub:
    """Revision-aware facade over the pinned snapshot's config writer."""

    def __init__(self, config_dir: Path, env_file: Path | None = None) -> None:
        self.config_dir = Path(config_dir)
        self.settings_file = self.config_dir / "settings.yaml"
        self.interfaces_file = self.config_dir / "interfaces.yaml"
        self.env_file = Path(env_file) if env_file else self.config_dir.parent / ".env"
        self.cio, self.schema = _load_snapshot_modules()
        # The snapshot's env helpers read a module-level ENV_FILE; this process
        # owns the snapshot import (the console is not running here), so point
        # it at OUR profile env once, at startup.
        self.cio.ENV_FILE = Path(self.env_file)
        self.backup_keep = 5

    # ------------------------------------------------------------- revision

    def revision(self) -> str:
        digest = hashlib.sha256()
        for path in (self.settings_file, self.interfaces_file, self.env_file):
            digest.update(path.name.encode("utf-8"))
            try:
                digest.update(path.read_bytes())
            except OSError:
                digest.update(b"\0missing")
        return digest.hexdigest()[:32]

    def file_hashes(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for path in (self.settings_file, self.interfaces_file, self.env_file):
            try:
                out[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            except OSError:
                out[path.name] = "missing"
        return out

    # ------------------------------------------------------------------ read

    def read(self, *, mask_secrets: bool = True) -> Dict[str, Any]:
        settings = self.cio.load_yaml(self.settings_file)
        interfaces = self.cio.load_yaml(self.interfaces_file)
        env = self.cio.load_env()

        values: Dict[str, Any] = {}
        values.update(_collect(self.schema.SETTINGS_FIELDS, settings))
        values.update(_collect(self.schema.INTERFACES_FIELDS, interfaces))
        for cfg_key, env_key in self.schema.ENV_FIELDS.items():
            raw = env.get(env_key, "")
            if mask_secrets and self._is_secret(cfg_key, env_key) and raw:
                values[cfg_key] = "__SET__"
            else:
                values[cfg_key] = raw

        lists: Dict[str, Any] = {}
        for list_id, path in self.schema.SETTINGS_LISTS.items():
            lists[list_id] = [str(x) for x in (self.cio.get_path(settings, path) or [])]
        for list_id, path in self.schema.INTERFACES_LISTS.items():
            lists[list_id] = [str(x) for x in (self.cio.get_path(interfaces, path) or [])]
        for list_id, (path, keys) in self.schema.INTERFACES_OBJECT_LISTS.items():
            lists[list_id] = [
                {k: str(row.get(k, "")) for k in keys}
                for row in (self.cio.get_path(interfaces, path) or [])
            ]
        for list_id, prefix in self.schema.ENV_LISTS.items():
            entries = self.cio.env_prefixed(prefix)
            if mask_secrets and self._is_secret_prefix(prefix):
                entries = ["__SET__" if str(e).strip() else "" for e in entries]
            lists[list_id] = entries

        return {
            "ok": True,
            "revision": self.revision(),
            "file_hashes": self.file_hashes(),
            "values": values,
            "lists": lists,
        }

    # ----------------------------------------------------------------- write

    def write(self, payload: Dict[str, Any], expected_revision: str | None = None) -> Dict[str, Any]:
        values = payload.get("values") or {}
        lists = payload.get("lists") or {}
        current = self.revision()
        if expected_revision and expected_revision != current:
            return {
                "ok": False,
                "status": "conflict",
                "error": "config changed since read; reload and retry",
                "revision": current,
            }

        self._backup_all()

        scalars, ifc_scalars, unknown = self._split_scalars(values)
        yaml_lists, ifc_lists = self._split_lists(lists)
        env_values, env_prefixed = self._split_env(values, lists)

        written: List[str] = []
        missing: List[str] = []
        if scalars or yaml_lists:
            missing.extend(self.cio.apply_yaml(self.settings_file, scalars, yaml_lists))
            written.append(self.settings_file.name)
        if ifc_scalars or ifc_lists or any(True for _ in self._object_lists(lists)):
            missing.extend(self.cio.apply_yaml(self.interfaces_file, ifc_scalars, ifc_lists, dict(self._object_lists(lists))))
            written.append(self.interfaces_file.name)
        if env_values or env_prefixed:
            self.cio.save_env(env_values, env_prefixed)
            written.append(self.env_file.name)

        return {
            "ok": True,
            "revision": self.revision(),
            "written": sorted(set(written)),
            "unknown": sorted(set(unknown)),
            "missing": missing,
            "readback": self.read(mask_secrets=True),
        }

    # ------------------------------------------------------------ internals

    def _split_scalars(self, values: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
        scalars: Dict[str, Any] = {}
        ifc_scalars: Dict[str, Any] = {}
        unknown: List[str] = []
        for cfg_key, value in values.items():
            if cfg_key in self.schema.SETTINGS_FIELDS:
                scalars[self.schema.SETTINGS_FIELDS[cfg_key]] = value
            elif cfg_key in self.schema.INTERFACES_FIELDS:
                ifc_scalars[self.schema.INTERFACES_FIELDS[cfg_key]] = value
            elif cfg_key not in self.schema.ENV_FIELDS:
                unknown.append(cfg_key)
        return scalars, ifc_scalars, unknown

    def _split_lists(self, lists: Dict[str, Any]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        yaml_lists: Dict[str, List[str]] = {}
        ifc_lists: Dict[str, List[str]] = {}

        def _clean(items: Iterable[Any]) -> List[str]:
            return [str(x).strip() for x in items if str(x).strip()]

        for list_id, items in lists.items():
            if list_id in self.schema.SETTINGS_LISTS:
                yaml_lists[self.schema.SETTINGS_LISTS[list_id]] = _clean(items)
            elif list_id in self.schema.INTERFACES_LISTS:
                ifc_lists[self.schema.INTERFACES_LISTS[list_id]] = _clean(items)
        return yaml_lists, ifc_lists

    def _object_lists(self, lists: Dict[str, Any]) -> Iterable[Tuple[str, Tuple[List[Dict[str, Any]], List[str]]]]:
        for list_id, items in lists.items():
            spec = self.schema.INTERFACES_OBJECT_LISTS.get(list_id)
            if spec is None:
                continue
            path, keys = spec
            rows = [
                r for r in items
                if isinstance(r, dict) and any(str(r.get(k, "")).strip() for k in keys)
            ]
            yield path, (rows, keys)

    def _split_env(self, values: Dict[str, Any], lists: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
        env_values: Dict[str, str] = {}
        for cfg_key, value in values.items():
            env_key = self.schema.ENV_FIELDS.get(cfg_key)
            if env_key is None:
                continue
            if self._is_secret(cfg_key, env_key) and self._secret_unchanged(value):
                # masked or empty secret: keep the stored value untouched
                continue
            env_values[env_key] = "" if value is None else str(value)
        env_prefixed: Dict[str, List[str]] = {}
        for list_id, items in lists.items():
            prefix = self.schema.ENV_LISTS.get(list_id)
            if prefix is None:
                continue
            if self._is_secret_prefix(prefix):
                entries = [str(x).strip() for x in items]
                current = self.cio.env_prefixed(prefix)
                # only replace entries that are not masked placeholders
                if not any(e and e != "__SET__" for e in entries):
                    continue
                env_prefixed[prefix] = entries
            else:
                env_prefixed[prefix] = [str(x).strip() for x in items if str(x).strip()]
        return env_values, env_prefixed

    def _secret_unchanged(self, value: Any) -> bool:
        return value in (None, "", "__SET__")

    def _is_secret(self, cfg_key: str, env_key: str) -> bool:
        haystack = f"{cfg_key} {env_key}".upper()
        return any(marker in haystack for marker in SECRET_MARKERS)

    def _is_secret_prefix(self, prefix: str) -> bool:
        return any(marker in prefix.upper() for marker in SECRET_MARKERS)

    # --------------------------------------------------------------- backups

    def _backup_path(self, target: Path, index: int) -> Path:
        return target.with_name(f"{target.name}.pre-save-{index}.bak")

    def _backup_all(self) -> None:
        for target in (self.settings_file, self.interfaces_file, self.env_file):
            if not target.exists():
                continue
            for index in range(self.backup_keep, 1, -1):
                src = self._backup_path(target, index - 1)
                dst = self._backup_path(target, index)
                if src.exists():
                    dst.write_bytes(src.read_bytes())
            self._backup_path(target, 1).write_bytes(target.read_bytes())


def _collect(mapping: Dict[str, str], data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for cfg_key, path in mapping.items():
        out[cfg_key] = _get(data, path)
    return out


def _get(data: Dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


__all__ = ["ConfigHub", "SECRET_MARKERS"]
