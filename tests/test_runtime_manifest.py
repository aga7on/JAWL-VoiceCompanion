from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jawl_voicecompanion.runtime_manifest import load_runtime_manifest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve_runtime_manifest.py"


def _write_manifest(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile": "fixture",
        "ports": {"control": 2367, "presentation": 8766},
        "models": {
            "llama_server_exe": "Z:/missing/llama-server.exe",
            "bonsai_model": "Z:/missing/Hikari-PQ2.gguf",
        },
        "brain": {"provider": "local-hikari", "model": "local-bonsai2"},
    }


def test_legacy_defaults_keep_model_identity_and_allow_missing_model_files(tmp_path: Path) -> None:
    canonical = tmp_path / "config" / "runtime.manifest.json"
    original = _manifest()
    _write_manifest(canonical, original)

    result = load_runtime_manifest(tmp_path)

    assert result["ports"]["brain_port"] == 8990
    assert result["models"]["brain_server_exe"] == "Z:/missing/llama-server.exe"
    assert result["brain"]["model"] == "local-bonsai2"
    assert result["brain"]["context_size"] == 65536
    assert result["brain"]["max_output_tokens"] == 2048
    assert result["brain"]["device"] == "CUDA1"
    assert result["brain"]["threads"] == 12
    assert result["launch"] == {"run_seconds": 0, "tts_provider": "tera"}
    assert result["vision"] == {
        "url": "http://127.0.0.1:8986/v1",
        "model": "bonsai",
        "auto_start": False,
    }
    assert "tera_python" not in result["models"]
    assert "tera_release" not in result["models"]
    assert original == _manifest()
    assert not (tmp_path / "Z:/missing").exists()


def test_local_manifest_deep_merges_without_mutating_inputs(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    canonical_path = config_dir / "runtime.manifest.json"
    local_path = config_dir / "runtime.manifest.local.json"
    original = _manifest()
    override = {"brain": {"threads": 6}, "ports": {"presentation": 8866}}
    _write_manifest(canonical_path, original)
    _write_manifest(local_path, override)
    canonical_bytes = canonical_path.read_bytes()
    local_bytes = local_path.read_bytes()

    result = load_runtime_manifest(tmp_path)

    assert result["ports"]["control"] == 2367
    assert result["ports"]["presentation"] == 8866
    assert result["brain"]["model"] == "local-bonsai2"
    assert result["brain"]["threads"] == 6
    assert canonical_path.read_bytes() == canonical_bytes
    assert local_path.read_bytes() == local_bytes
    assert override == {"brain": {"threads": 6}, "ports": {"presentation": 8866}}
    assert original == _manifest()


@pytest.mark.parametrize(
    "ports",
    [
        {"control": 8765, "presentation": 8766, "brain_port": 8990},
        {"control": 2367, "presentation": 2367, "brain_port": 8990},
        {"control": 2367, "presentation": 8766, "brain_port": 8766},
    ],
)
def test_reserved_and_duplicate_ports_are_rejected(tmp_path: Path, ports: dict[str, int]) -> None:
    manifest = _manifest()
    manifest["ports"] = ports
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)


@pytest.mark.parametrize("value", [True, False])
def test_boolean_port_is_rejected(tmp_path: Path, value: bool) -> None:
    manifest = _manifest()
    manifest["ports"]["control"] = value
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)


def test_unknown_and_secret_bearing_nested_fields_are_rejected(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["brain"]["arbitrary"] = {"depth": [{"payload": "do not load"}]}
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)

    manifest["brain"].pop("arbitrary")
    manifest["untrusted"] = [{"api_key": "fixture-secret-value"}]
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)
    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)

    manifest.pop("untrusted")
    manifest["brain"]["model_tokenizer"] = "fixture-secret-value"
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)
    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)


def test_invalid_json_fails_without_exposing_source_text(tmp_path: Path) -> None:
    path = tmp_path / "config" / "runtime.manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 1, "api_key": "fixture-secret-value"', encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_runtime_manifest(tmp_path)

    assert "fixture-secret-value" not in str(exc.value)
    assert str(path) not in str(exc.value)

    path.write_text('{"schema_version": 1, "sentinel": "redact-this",}', encoding="utf-8")
    with pytest.raises(ValueError) as malformed:
        load_runtime_manifest(tmp_path)
    assert "redact-this" not in str(malformed.value)

    path.write_bytes(b'{"payload":"decode-redact-\xff"}')
    with pytest.raises(ValueError) as decode_error:
        load_runtime_manifest(tmp_path)
    assert "decode-redact" not in str(decode_error.value)


def test_manifest_json_is_size_bounded(tmp_path: Path) -> None:
    path = tmp_path / "config" / "runtime.manifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{" + b" " * (128 * 1024) + b"}")

    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)


@pytest.mark.parametrize(
    "brain_url",
    [
        "http://user:password@127.0.0.1:8990/v1",
        "http://example.com:8990/v1",
        "http://127.0.0.1:8991/v1",
        "http://127.0.0.1:8990/health",
    ],
)
def test_brain_url_must_be_loopback_credential_free_and_match_port(
    tmp_path: Path, brain_url: str
) -> None:
    manifest = _manifest()
    manifest["ports"]["brain_port"] = 8990
    manifest["brain"]["llm_url"] = brain_url
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("models", "llama_server_exe", ""),
        ("models", "llama_server_exe", "bad\x00path"),
        ("brain", "model", "../unsafe-model"),
    ],
)
def test_paths_and_model_aliases_must_be_safe_nonempty_strings(
    tmp_path: Path, section: str, key: str, value: str
) -> None:
    manifest = _manifest()
    manifest[section][key] = value
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("context_size", 1_048_577),
        ("context_size", 511),
        ("max_output_tokens", 65_537),
        ("threads", 129),
        ("gpu_layers", -1),
        ("gpu_layers", 257),
        ("threads", True),
    ],
)
def test_brain_resource_limits_are_bounded(tmp_path: Path, key: str, value: object) -> None:
    manifest = _manifest()
    manifest["brain"][key] = value
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)


def test_output_budget_must_be_smaller_than_context(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["brain"].update({"context_size": 4096, "max_output_tokens": 4096})
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    with pytest.raises(ValueError):
        load_runtime_manifest(tmp_path)


def test_brain_model_is_required_and_bounded(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["brain"].pop("model")
    path = tmp_path / "config" / "runtime.manifest.json"
    _write_manifest(path, manifest)

    with pytest.raises(ValueError, match="brain.model"):
        load_runtime_manifest(tmp_path)

    manifest["brain"]["model"] = "m" * 129
    _write_manifest(path, manifest)
    with pytest.raises(ValueError, match="brain.model"):
        load_runtime_manifest(tmp_path)


@pytest.mark.parametrize("provider", ["local", "Tera", "unknown-provider"])
def test_tts_provider_must_be_a_supported_choice(tmp_path: Path, provider: str) -> None:
    manifest = _manifest()
    manifest["launch"] = {"tts_provider": provider}
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    with pytest.raises(ValueError, match="tts_provider"):
        load_runtime_manifest(tmp_path)


@pytest.mark.parametrize("provider", ["tera", "omnivoice", "voxcpm"])
def test_tts_provider_accepts_supported_choices(tmp_path: Path, provider: str) -> None:
    manifest = _manifest()
    manifest["launch"] = {"tts_provider": provider}
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    assert load_runtime_manifest(tmp_path)["launch"]["tts_provider"] == provider


def test_tera_paths_are_optional_but_validated_when_present(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["models"].update(
        {"tera_python": "Z:/missing/tera/python.exe", "tera_release": "Z:/missing/tera/release"}
    )
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)

    result = load_runtime_manifest(tmp_path)
    assert result["models"]["tera_python"] == "Z:/missing/tera/python.exe"
    assert result["models"]["tera_release"] == "Z:/missing/tera/release"


def test_resolution_performs_no_writes_outside_manifest_files(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    canonical = config_dir / "runtime.manifest.json"
    local = config_dir / "runtime.manifest.local.json"
    _write_manifest(canonical, _manifest())
    _write_manifest(local, {"brain": {"threads": 10}})
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}

    load_runtime_manifest(tmp_path)

    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before == {
        Path("config/runtime.manifest.json"),
        Path("config/runtime.manifest.local.json"),
    }


def test_cli_emits_one_json_document_from_an_unrelated_working_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_manifest(repo / "config" / "runtime.manifest.json", _manifest())
    foreign_cwd = tmp_path / "elsewhere"
    foreign_cwd.mkdir()

    completed = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--repo-root", str(repo)],
        cwd=foreign_cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    decoded = json.loads(completed.stdout)
    assert decoded["brain"]["model"] == "local-bonsai2"
    assert completed.stdout.count("\n") == 1
    assert {path for path in tmp_path.rglob("*") if path.is_file()} == {
        repo / "config" / "runtime.manifest.json",
    }


@pytest.mark.parametrize("profile", ["../daily", "..", "a/b", "a\\b", "C:daily", "a b", "CON", "NUL", "COM1", "LPT9", "x" * 49])
def test_rejects_unsafe_profile_names(tmp_path: Path, profile: str) -> None:
    manifest = _manifest()
    manifest["profile"] = profile
    _write_manifest(tmp_path / "config" / "runtime.manifest.json", manifest)
    with pytest.raises(ValueError, match="profile"):
        load_runtime_manifest(tmp_path)


def test_cli_redacts_errors_and_emits_no_json_on_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    path = repo / "config" / "runtime.manifest.json"
    secret = "fixture-secret-value"
    manifest = _manifest()
    manifest["ports"]["control"] = 8765
    manifest["diagnostic"] = secret
    _write_manifest(path, manifest)

    completed = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--manifest", str(path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert secret not in completed.stderr
    assert str(path) not in completed.stderr
    assert completed.stderr.strip() == "runtime manifest could not be resolved"
