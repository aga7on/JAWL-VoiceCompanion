"""Prepare the owned JAWL profile with managed-file versioning.

Managed files are updated only when the active copy still matches the previous
managed hash. A user edit is preserved and reported as a conflict; a backup is
created before every managed update.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - the managed runtime includes PyYAML
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"
CONFIG_ROOT = REPO_ROOT / "config" / "jawl"
PROFILE_NAME = os.environ.get("JAWL_PROFILE_NAME", "daily").strip() or "daily"
if Path(PROFILE_NAME).name != PROFILE_NAME or PROFILE_NAME in {".", ".."}:
    raise ValueError("JAWL_PROFILE_NAME must be one safe directory name")
PROFILE_ROOT = REPO_ROOT / "runtime" / "instances" / PROFILE_NAME
EMBEDDING_RELATIVE = Path(
    "models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
) / "snapshots" / "faf4aa4225822f3bc6376869cb1164e8e3feedd0" / "model_optimized.onnx"
EMBEDDING_ASSET_ROOT = REPO_ROOT / "runtime" / "assets" / "embeddings"
EMBEDDING_BOOTSTRAP_ROOT = REPO_ROOT / "runtime" / "instances" / "daily" / "data" / "vector" / "embeddings"
MANIFEST_NAME = ".managed-files.json"
SOURCE_MANIFEST_NAME = "SOURCE_MANIFEST.json"


class ProfileConflict(RuntimeError):
    """The active profile contains an unapproved user override."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping_contains(expected: object, actual: object) -> bool:
    """Return whether every managed YAML value is preserved in actual.

    JAWL normalizes its settings on first boot and adds schema defaults. Those
    generated keys are profile-owned state, not a user override. Existing
    managed leaves still have to match, so changing a managed value remains a
    fail-closed conflict.
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _mapping_contains(value, actual[key])
                   for key, value in expected.items())
    if isinstance(expected, list):
        return expected == actual
    return expected == actual


def _is_jawl_generated_config(source: Path, target: Path) -> bool:
    if yaml is None or source.suffix.lower() not in {".yaml", ".yml"}:
        return False
    try:
        expected = yaml.safe_load(source.read_text(encoding="utf-8"))
        actual = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    # The integrated launcher deliberately applies runtime-selectable
    # capability switches after the managed baseline is copied.  They are
    # profile controls, not arbitrary user edits: every other managed leaf
    # must still match the repository baseline.  Keeping this exception here
    # makes relaunch/recovery idempotent without weakening fail-closed config
    # conflict detection for settings or unrelated interface changes.
    if source.name == "interfaces.yaml" and isinstance(expected, dict) and isinstance(actual, dict):
        normalized = copy.deepcopy(expected)
        expected_host = normalized.get("host")
        actual_host = actual.get("host")
        if isinstance(expected_host, dict) and isinstance(actual_host, dict):
            expected_os = expected_host.get("os")
            actual_os = actual_host.get("os")
            if isinstance(expected_os, dict) and isinstance(actual_os, dict):
                level = actual_os.get("access_level")
                if isinstance(level, int) and level in range(4):
                    expected_os["access_level"] = level
        expected_broker = normalized.get("debug_broker")
        actual_broker = actual.get("debug_broker")
        if isinstance(expected_broker, dict) and isinstance(actual_broker, dict):
            enabled = actual_broker.get("enabled")
            if isinstance(enabled, bool):
                expected_broker["enabled"] = enabled
        expected = normalized
    # The launcher may deliberately select another provider model for a
    # disposable profile.  Keep that one leaf as an approved runtime
    # override, but only when the override is explicit in this process and
    # every other managed setting still matches the repository baseline.
    # Without the environment marker an unexplained model edit remains a
    # fail-closed profile conflict.
    if source.name == "settings.yaml":
        override = os.environ.get("JAWL_MODEL_OVERRIDE", "").strip()
        temperature_override = os.environ.get("JAWL_TEMPERATURE_OVERRIDE", "").strip()
        if override and isinstance(expected, dict) and isinstance(actual, dict):
            expected_llm = expected.get("llm")
            actual_llm = actual.get("llm")
            if not isinstance(expected_llm, dict) or not isinstance(actual_llm, dict):
                return False
            if actual_llm.get("main_model") != override:
                return False
            normalized = copy.deepcopy(expected)
            normalized.setdefault("llm", {})["main_model"] = override
            expected = normalized
        if temperature_override and isinstance(expected, dict) and isinstance(actual, dict):
            try:
                temperature = float(temperature_override)
            except ValueError:
                return False
            if not 0.0 <= temperature <= 2.0:
                return False
            expected_llm = expected.get("llm")
            actual_llm = actual.get("llm")
            actual_temperature = actual_llm.get("temperature") if isinstance(actual_llm, dict) else None
            if (
                not isinstance(expected_llm, dict)
                or not isinstance(actual_llm, dict)
                or isinstance(actual_temperature, bool)
                or not isinstance(actual_temperature, (int, float))
                or abs(float(actual_temperature) - temperature) > 1e-9
            ):
                return False
            normalized = copy.deepcopy(expected)
            normalized.setdefault("llm", {})["temperature"] = temperature
            expected = normalized
    return _mapping_contains(expected, actual)


def _atomic_copy(source: Path, target: Path) -> None:
    """Copy a managed file without exposing a partially written target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _provision_embedding_cache() -> str:
    """Copy the verified local embedding asset into this profile's data tree."""
    target = PROFILE_ROOT / "data" / "vector" / "embeddings" / EMBEDDING_RELATIVE
    if target.is_file():
        return "embedding_cache=existing"
    candidates = (
        EMBEDDING_ASSET_ROOT / EMBEDDING_RELATIVE,
        EMBEDDING_BOOTSTRAP_ROOT / EMBEDDING_RELATIVE,
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        return "embedding_cache=missing"
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_copy(source, target)
    return f"embedding_cache=provisioned:{source}"


def _source_identity() -> dict[str, object]:
    """Return provenance recorded with every prepared profile."""
    path = SOURCE_ROOT / SOURCE_MANIFEST_NAME
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"Pinned JAWL source manifest is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = payload.get("files") if isinstance(payload, dict) else None
    snapshot_sha256 = payload.get("snapshot_sha256") if isinstance(payload, dict) else None
    if not isinstance(files, dict) or not files or not isinstance(snapshot_sha256, str):
        raise ValueError("Pinned JAWL source manifest is incomplete")
    return {
        "name": str(payload.get("name", SOURCE_ROOT.name)),
        "snapshot_sha256": snapshot_sha256.lower(),
        "file_count": len(files),
    }


def _sources() -> list[tuple[Path, Path]]:
    prompt_source = SOURCE_ROOT / "src" / "l3_agent" / "prompt"
    pairs = [
        (CONFIG_ROOT / "SOUL.md", PROFILE_ROOT / "prompts" / "personality" / "SOUL.md"),
        (CONFIG_ROOT / "settings.yaml", PROFILE_ROOT / "config" / "settings.yaml"),
        (CONFIG_ROOT / "interfaces.yaml", PROFILE_ROOT / "config" / "interfaces.yaml"),
    ]
    for source in sorted(prompt_source.rglob("*")):
        if source.is_file() and "__pycache__" not in source.parts:
            pairs.append((source, PROFILE_ROOT / "prompts" / source.relative_to(prompt_source)))
    custom_source = CONFIG_ROOT / "prompts" / "custom"
    if custom_source.is_dir():
        for source in sorted(custom_source.rglob("*")):
            if source.is_file():
                pairs.append((source, PROFILE_ROOT / "prompts" / "custom" / source.relative_to(custom_source)))
    return pairs


def prepare(*, sync: bool = False) -> list[str]:
    if not SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"Pinned JAWL source is missing: {SOURCE_ROOT}")
    source_identity = _source_identity()
    pairs = _sources()
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = PROFILE_ROOT / MANIFEST_NAME
    previous: dict[str, str] = {}
    if manifest_path.is_file():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous = dict(payload.get("managed", {}))
    managed: dict[str, str] = {}
    created = updated = 0
    conflicts: list[str] = []
    decisions: list[tuple[Path, Path, str, str, str | None]] = []
    for source, target in pairs:
        if not source.is_file():
            raise FileNotFoundError(source)
        key = target.relative_to(PROFILE_ROOT).as_posix()
        source_hash = _sha256(source)
        if target.exists():
            current_hash = _sha256(target)
            old_hash = previous.get(key)
            if current_hash != source_hash:
                generated_config = (
                    key in {"config/settings.yaml", "config/interfaces.yaml"}
                    and _is_jawl_generated_config(source, target)
                )
                if (old_hash is None or current_hash != old_hash) and not sync and not generated_config:
                    conflicts.append(key)
                    decisions.append((source, target, key, source_hash, current_hash))
                    continue
                decisions.append((source, target, key, source_hash, current_hash))
            else:
                decisions.append((source, target, key, source_hash, current_hash))
        else:
            decisions.append((source, target, key, source_hash, None))
    if conflicts:
        joined = ", ".join(conflicts[:12])
        suffix = "..." if len(conflicts) > 12 else ""
        raise ProfileConflict(
            f"profile contains unapproved managed-file override(s): {joined}{suffix}; "
            "review or rerun with --sync"
        )

    for source, target, key, source_hash, current_hash in decisions:
        if current_hash is None:
            _atomic_copy(source, target)
            created += 1
        elif current_hash != source_hash:
            if key in {"config/settings.yaml", "config/interfaces.yaml"} and _is_jawl_generated_config(source, target):
                # Keep JAWL's normalized superset; managed leaves were checked
                # above and still match the repository baseline.
                managed[key] = current_hash
                continue
            backup = target.with_name(target.name + ".bak")
            if sync and backup.exists():
                backup = target.with_name(target.name + ".bak.sync")
            shutil.copy2(target, backup)
            _atomic_copy(source, target)
            updated += 1
        managed[key] = _sha256(target)
    for directory in (PROFILE_ROOT / "data", PROFILE_ROOT / "logs", PROFILE_ROOT / "cache", PROFILE_ROOT / "sandbox"):
        directory.mkdir(parents=True, exist_ok=True)
    embedding_status = _provision_embedding_cache()
    manifest = {
        "schema_version": 2,
        "source": source_identity,
        "managed": managed,
        "conflicts": conflicts,
    }
    _atomic_json(manifest_path, manifest)
    return [
        f"created_files={created}",
        f"updated_files={updated}",
        f"conflicts={len(conflicts)}",
        f"profile={PROFILE_ROOT}",
        f"soul={PROFILE_ROOT / 'prompts' / 'personality' / 'SOUL.md'}",
        embedding_status,
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync", action="store_true", help="update conflicting managed files after a backup")
    args = parser.parse_args()
    try:
        lines = prepare(sync=args.sync)
    except ProfileConflict as exc:
        print(f"ERROR {exc}")
        return 2
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
