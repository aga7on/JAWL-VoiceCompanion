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

import copy
import hashlib
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

_SNAPSHOT_SRC = Path(
    r"G:\AI\JAWL-VoiceCompanion\runtime\jawl-sources\jawl-20260906-daily-v2\src"
)


def _load_snapshot_modules(env_file: Path | None = None):
    # get_instance_paths() runs at config_io import time and can CREATE the
    # fallback .env inside the pinned snapshot directory. Point JAWL_ENV_FILE
    # at our target BEFORE the import so the bootstrap lands on the profile
    # (or the test's temp dir) instead of polluting the snapshot.
    if env_file is not None:
        import os

        os.environ["JAWL_ENV_FILE"] = str(env_file)
    if str(_SNAPSHOT_SRC) not in sys.path:
        sys.path.insert(0, str(_SNAPSHOT_SRC))
    snapshot_root = _SNAPSHOT_SRC.parent
    if str(snapshot_root) not in sys.path:
        sys.path.insert(0, str(snapshot_root))
    from web import config_io as cio  # noqa: PLC0415 - pinned snapshot module
    from web import schema as schema  # noqa: F401 - re-exported for callers

    return cio, schema


SECRET_MARKERS = ("KEY", "TOKEN", "PASSWORD", "SECRET", "HASH")

# The drives settings are managed by the console's /api/drives form (they are
# outside the snapshot's schema.py mapping), but the values themselves live in
# settings.yaml under system.db.sql.drives.* — the hub writes them with the
# same in-place semantics, so the unified settings can edit them too. The
# SQLite side (drive states/satisfaction) stays with /api/drives.
DRIVES_FIELDS: Dict[str, str] = {
    "settings:system.db.sql.drives.enabled": "system.db.sql.drives.enabled",
    "settings:system.db.sql.drives.dynamic_reduction": "system.db.sql.drives.dynamic_reduction",
    "settings:system.db.sql.drives.pause_on_offline": "system.db.sql.drives.pause_on_offline",
    "settings:system.db.sql.drives.max_custom_drives": "system.db.sql.drives.max_custom_drives",
    "settings:system.db.sql.drives.max_reflections_history": "system.db.sql.drives.max_reflections_history",
    "settings:system.db.sql.drives.fundamental.curiosity.enabled": "system.db.sql.drives.fundamental.curiosity.enabled",
    "settings:system.db.sql.drives.fundamental.curiosity.decay.rate": "system.db.sql.drives.fundamental.curiosity.decay.rate",
    "settings:system.db.sql.drives.fundamental.curiosity.decay.interval_sec": "system.db.sql.drives.fundamental.curiosity.decay.interval_sec",
    "settings:system.db.sql.drives.fundamental.mastery.enabled": "system.db.sql.drives.fundamental.mastery.enabled",
    "settings:system.db.sql.drives.fundamental.mastery.decay.rate": "system.db.sql.drives.fundamental.mastery.decay.rate",
    "settings:system.db.sql.drives.fundamental.mastery.decay.interval_sec": "system.db.sql.drives.fundamental.mastery.decay.interval_sec",
    "settings:system.db.sql.drives.fundamental.social.enabled": "system.db.sql.drives.fundamental.social.enabled",
    "settings:system.db.sql.drives.fundamental.social.decay.rate": "system.db.sql.drives.fundamental.social.decay.rate",
    "settings:system.db.sql.drives.fundamental.social.decay.interval_sec": "system.db.sql.drives.fundamental.social.decay.interval_sec",
}


class ConfigHub:
    """Revision-aware facade over the pinned snapshot's config writer."""

    def __init__(self, config_dir: Path, env_file: Path | None = None) -> None:
        self.config_dir = Path(config_dir)
        self.settings_file = self.config_dir / "settings.yaml"
        self.interfaces_file = self.config_dir / "interfaces.yaml"
        self.env_file = Path(env_file) if env_file else self.config_dir.parent / ".env"
        self.cio, self.schema = _load_snapshot_modules(self.env_file)
        # The snapshot's env helpers read a module-level ENV_FILE; this process
        # owns the snapshot import (the console is not running here), so point
        # it at OUR profile env once, at startup.
        self.cio.ENV_FILE = Path(self.env_file)
        # One writer per process: the revision check, the backups and the
        # write must be atomic against concurrent requests.
        self._writer_lock = threading.Lock()
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
        values.update(_collect(DRIVES_FIELDS, settings))
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

    def read_voice_capture(self) -> Dict[str, Any]:
        """Read the capture subtree without projecting it through snapshot schema."""
        with self._writer_lock:
            interfaces = self.cio.load_yaml(self.interfaces_file)
            if not isinstance(interfaces, dict):
                raise ValueError("interfaces.yaml root must be a mapping")
            voice = interfaces.get("voice", {})
            if voice is None and "voice" in interfaces:
                raise ValueError("interfaces.yaml voice entry is null")
            if not isinstance(voice, dict):
                raise ValueError("interfaces.yaml voice entry must be a mapping")
            capture = voice.get("capture", {})
            if capture is None and "capture" in voice:
                raise ValueError("interfaces.yaml voice.capture entry is null")
            if not isinstance(capture, dict):
                raise ValueError("interfaces.yaml voice.capture entry must be a mapping")
            return {"settings": dict(capture), "revision": self.revision()}

    def write_voice_capture(
        self, settings: Dict[str, Any], expected_revision: str,
    ) -> Dict[str, Any]:
        """Persist capture fields through this hub's revision lock and backups."""
        if not isinstance(settings, dict):
            raise ValueError("voice capture settings must be an object")
        from .voice_capture import VoiceCaptureSettings  # local import avoids a module cycle

        settings = VoiceCaptureSettings.from_mapping(settings).as_settings_dict()
        with self._writer_lock:
            current = self.revision()
            if expected_revision != current:
                return {
                    "ok": False,
                    "status": "conflict",
                    "error": "config changed since read; reload and retry",
                    "revision": current,
                }

            # Parse before backing up or changing anything. Invalid/unknown
            # interface data is surfaced instead of being reset to defaults.
            yaml_text, expected_interfaces = self._ensure_capture_subtree(settings)
            self._atomic_apply_capture(settings, yaml_text, expected_interfaces)
            return {
                "ok": True,
                "revision": self.revision(),
                "written": [self.interfaces_file.name],
                "settings": dict(settings),
                "restart_required": False,
                "restart_policy": "next_capture",
            }

    def _ensure_capture_subtree(self, settings: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Insert only absent YAML mapping lines, retaining original text bytes."""
        interfaces = self.cio.load_yaml(self.interfaces_file)
        if not isinstance(interfaces, dict):
            raise ValueError("interfaces.yaml root must be a mapping")
        original_has_voice = "voice" in interfaces
        voice = interfaces.get("voice", {})
        if voice is None and original_has_voice:
            raise ValueError("voice: null is unsupported for safe capture settings insertion")
        if not isinstance(voice, dict):
            raise ValueError("interfaces.yaml voice entry must be a mapping")
        capture = voice.get("capture", {})
        if capture is None and "capture" in voice:
            raise ValueError("voice.capture: null is unsupported for safe settings insertion")
        if not isinstance(capture, dict):
            raise ValueError("interfaces.yaml voice.capture entry must be a mapping")

        with self.interfaces_file.open("r", encoding="utf-8", newline="") as source:
            text = source.read()
        newline = "\r\n" if text.count("\r\n") > text.count("\n") // 2 else "\n"
        lines = text.splitlines(keepends=True)
        if not lines and text:
            lines = [text]

        voice_line = _yaml_mapping_line(lines, ("voice",)) if original_has_voice else None
        if original_has_voice and voice_line is None:
            raise ValueError("quoted or unsupported voice key syntax cannot be edited safely")
        if voice_line is None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            lines.extend(["voice:" + newline, "  capture:" + newline])
            capture_indent = 2
        else:
            voice_indent = _leading_indent(lines[voice_line])
            voice_text, voice_ending = _strip_line_ending(lines[voice_line])
            voice_match = re.match(r"^(\s*voice\s*:\s*)(.*)$", voice_text)
            assert voice_match is not None
            tail = voice_match.group(2)
            body = _yaml_value_without_comment(tail)
            if body == "{}":
                lines[voice_line] = voice_match.group(1) + _yaml_comment(tail) + voice_ending
                capture_start = voice_line + 1
                lines[capture_start:capture_start] = [
                    " " * (voice_indent + 2) + "capture:" + newline,
                ]
                capture_indent = voice_indent + 2
            elif body:
                raise ValueError("voice must use a block mapping for safe capture settings insertion")
            else:
                capture_line = _yaml_mapping_line(lines, ("voice", "capture"))
                if capture_line is None:
                    insertion = _mapping_end(lines, voice_line, voice_indent)
                    if insertion and not lines[insertion - 1].endswith(("\n", "\r")):
                        lines[insertion - 1] += newline
                    capture_indent = voice_indent + 2
                    lines[insertion:insertion] = [
                        " " * capture_indent + "capture:" + newline,
                    ]
                else:
                    capture_indent = _leading_indent(lines[capture_line])

        # Empty inline capture mappings are expanded locally. Other inline
        # mappings are rejected because rewriting them could disturb user YAML.
        capture_line = _yaml_mapping_line(lines, ("voice", "capture"))
        if capture_line is None:
            raise ValueError("could not safely insert voice.capture mapping")
        capture_text, capture_ending = _strip_line_ending(lines[capture_line])
        capture_match = re.match(r"^(\s*capture\s*:\s*)(.*)$", capture_text)
        assert capture_match is not None
        capture_body = _yaml_value_without_comment(capture_match.group(2))
        if capture_body == "{}":
            lines[capture_line] = capture_match.group(1) + _yaml_comment(capture_match.group(2)) + capture_ending
        elif capture_body:
            raise ValueError("voice.capture must be a block mapping")

        missing = [key for key in settings if key not in capture]
        if missing:
            insertion = _mapping_end(lines, capture_line, capture_indent)
            if insertion and not lines[insertion - 1].endswith(("\n", "\r")):
                lines[insertion - 1] += newline
            block = [
                " " * (capture_indent + 2) + key + ": " + _yaml_scalar(settings[key]) + newline
                for key in missing
            ]
            lines[insertion:insertion] = block

        expected = copy.deepcopy(interfaces)
        expected_voice = expected.setdefault("voice", {})
        expected_capture = expected_voice.setdefault("capture", {})
        if not isinstance(expected_capture, dict):
            raise ValueError("voice.capture must be a block mapping for safe settings insertion")
        expected_capture.update(settings)
        return "".join(lines), expected

    def _atomic_apply_capture(
        self, settings: Dict[str, Any], yaml_text: str, expected_interfaces: Dict[str, Any],
    ) -> None:
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", suffix=".yaml",
                prefix=".interfaces-capture-", dir=self.config_dir, delete=False,
            ) as temp_file:
                temp_name = temp_file.name
                temp_file.write(yaml_text)
            with Path(temp_name).open("r", encoding="utf-8", newline="") as candidate_file:
                lines = candidate_file.read().splitlines(keepends=True)
            for key, value in settings.items():
                if not _replace_yaml_scalar(lines, ("voice", "capture", key), value):
                    raise ValueError("could not safely write capture setting: " + key)
            with Path(temp_name).open("w", encoding="utf-8", newline="") as candidate_file:
                candidate_file.write("".join(lines))
            try:
                candidate_interfaces = self.cio.load_yaml(Path(temp_name))
            except Exception as exc:
                raise ValueError(
                    "capture settings edit produced invalid YAML; "
                    "this layout is unsupported and was left unchanged"
                ) from exc
            if candidate_interfaces != expected_interfaces:
                raise ValueError(
                    "capture settings YAML edit changed unrelated interfaces data; "
                    "this YAML layout is unsupported and was left unchanged"
                )
            self._backup_all()
            os.replace(temp_name, self.interfaces_file)
            temp_name = None
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)

    # ----------------------------------------------------------------- write

    def write(self, payload: Dict[str, Any], expected_revision: str | None = None) -> Dict[str, Any]:
        values = payload.get("values") or {}
        lists = payload.get("lists") or {}
        with self._writer_lock:
            return self._write_locked(values, lists, expected_revision)

    def _write_locked(self, values: Dict[str, Any], lists: Dict[str, Any], expected_revision: str | None) -> Dict[str, Any]:
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
            # The agent calls load_config() once at startup (src/main.py), so
            # every config key is conservative: an agent restart applies it.
            # No config key is currently proven live-cycle-reloaded.
            "restart_required": bool(written),
            "restart_policy": "agent_restart",
        }

    # ------------------------------------------------------------ internals

    def _split_scalars(self, values: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
        scalars: Dict[str, Any] = {}
        ifc_scalars: Dict[str, Any] = {}
        unknown: List[str] = []
        for cfg_key, value in values.items():
            if cfg_key in self.schema.SETTINGS_FIELDS or cfg_key in DRIVES_FIELDS:
                path = self.schema.SETTINGS_FIELDS.get(cfg_key) or DRIVES_FIELDS[cfg_key]
                scalars[path] = value
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
                # Masked placeholders must never be written literally. Merge
                # positionally: a "__SET__"/empty slot keeps the stored key at
                # the same index, a typed value replaces it, "-" deletes it,
                # and extra typed values append as new keys.
                stored = self.cio.env_prefixed(prefix)
                merged: List[str] = []
                for index, item in enumerate(items):
                    value = str(item or "").strip()
                    if value == "-":
                        continue
                    if value and value != "__SET__":
                        merged.append(value)
                    elif index < len(stored):
                        merged.append(str(stored[index]).strip())
                env_prefixed[prefix] = [entry for entry in merged if entry]
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


def _strip_line_ending(line: str) -> Tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1:]
    return line, ""


def _leading_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _yaml_mapping_line(lines: List[str], path: Tuple[str, ...]) -> int | None:
    stack: List[Tuple[int, str]] = []
    for index, line in enumerate(lines):
        content, _ = _strip_line_ending(line)
        match = re.match(r"^(\s*)([A-Za-z_][\w-]*)\s*:(.*)$", content)
        if match is None:
            continue
        indent = len(match.group(1))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        candidate = tuple([key for _, key in stack] + [match.group(2)])
        if candidate == path:
            return index
        stack.append((indent, match.group(2)))
    return None


def _mapping_end(lines: List[str], start: int, parent_indent: int) -> int:
    for index in range(start + 1, len(lines)):
        content, _ = _strip_line_ending(lines[index])
        if not content.strip() or content.lstrip().startswith("#"):
            continue
        if _leading_indent(content) <= parent_indent:
            return index
    return len(lines)


def _yaml_value_without_comment(value: str) -> str:
    if value.lstrip().startswith("#"):
        return ""
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _yaml_comment(value: str) -> str:
    if value.lstrip().startswith("#"):
        return value
    match = re.search(r"\s+#.*$", value)
    return match.group(0) if match else ""


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("capture config values must be numeric")
    return repr(value) if isinstance(value, float) else str(value)


def _replace_yaml_scalar(lines: List[str], path: Tuple[str, ...], value: Any) -> bool:
    stack: List[Tuple[int, str]] = []
    for index, line in enumerate(lines):
        content, ending = _strip_line_ending(line)
        match = re.match(r"^(\s*)([A-Za-z_][\w-]*)\s*:(.*)$", content)
        if match is None:
            continue
        indent = len(match.group(1))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        candidate = tuple([key for _, key in stack] + [match.group(2)])
        if candidate == path:
            rest = match.group(3)
            comment = _yaml_comment(rest)
            lines[index] = (
                match.group(1) + match.group(2) + ": " + _yaml_scalar(value) + comment + ending
            )
            return True
        stack.append((indent, match.group(2)))
    return False


__all__ = ["ConfigHub", "SECRET_MARKERS"]
