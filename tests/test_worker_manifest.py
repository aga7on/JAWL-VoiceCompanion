from __future__ import annotations

import copy
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jawl_voicecompanion import __main__ as companion_main  # noqa: E402
from jawl_voicecompanion import runtime_manifest, supervisor, worker_readiness  # noqa: E402


REPO = Path(__file__).resolve().parents[1]


def _args(**overrides: object) -> SimpleNamespace:
    values = {
        "supervised_llm_command": None,
        "supervised_llm_model": None,
        "supervised_tts_command": None,
        "supervised_tts_release": None,
        "supervised_llm_port": None,
        "supervised_tts_port": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _fixture_manifest(root: Path) -> dict[str, object]:
    models_dir = root / "fixture-models"
    models_dir.mkdir(parents=True)
    brain_exe = models_dir / "brain-server.exe"
    brain_model = models_dir / "hikari.gguf"
    tera_python = models_dir / "python.exe"
    tera_release = models_dir / "tera-release"
    for path in (brain_exe, brain_model, tera_python):
        path.write_bytes(b"fixture")
    tera_release.mkdir()
    return {
        "schema_version": 1,
        "ports": {"brain_port": 18990, "tera_tts": 19889},
        "models": {
            "brain_server_exe": str(brain_exe),
            "bonsai_model": str(brain_model),
            "tera_python": str(tera_python),
            "tera_release": str(tera_release),
        },
        "brain": {
            "model": "hikari-fixture",
            "context_size": 32768,
            "max_output_tokens": 1024,
            "threads": 8,
            "gpu_layers": 99,
            "device": "CUDA1",
        },
    }


def _capture_supervisor(monkeypatch: pytest.MonkeyPatch) -> Mock:
    factory = Mock(side_effect=lambda specs: specs)
    monkeypatch.setattr(supervisor, "RuntimeSupervisor", factory)
    return factory


def _option(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def test_build_uses_actual_canonical_settings_and_absolute_tts_script_from_other_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    canonical = runtime_manifest.load_runtime_manifest(REPO)
    canonical_snapshot = copy.deepcopy(canonical)
    monkeypatch.setattr(runtime_manifest, "load_runtime_manifest", lambda _root: canonical)
    monkeypatch.setattr(Path, "is_file", lambda _path: True)
    monkeypatch.setattr(Path, "is_dir", lambda _path: True)
    checked_ports: list[list[int]] = []
    monkeypatch.setattr(worker_readiness, "require_free_ports", lambda ports: checked_ports.append(ports))
    factory = _capture_supervisor(monkeypatch)
    monkeypatch.chdir(tmp_path)

    specs = companion_main._build_worker_supervisor(_args())

    factory.assert_called_once()
    assert canonical == canonical_snapshot
    assert [spec.name for spec in specs] == ["brain", "tts"]
    brain, tts = specs
    assert _option(brain.command, "--alias") == canonical["brain"]["model"]
    assert _option(brain.command, "--ctx-size") == str(canonical["brain"]["context_size"])
    assert _option(brain.command, "--device") == canonical["brain"]["device"]
    assert _option(brain.command, "--threads") == str(canonical["brain"]["threads"])
    assert _option(brain.command, "--gpu-layers") == str(canonical["brain"]["gpu_layers"])
    assert Path(tts.command[1]).is_absolute()
    assert Path(tts.command[1]) == REPO / "scripts" / "teratts_server.py"
    assert Path(tts.command[0]).is_absolute()
    expected_release = Path(canonical["models"]["tera_release"])
    if not expected_release.is_absolute():
        expected_release = REPO / expected_release
    assert Path(_option(tts.command, "--release-dir")) == expected_release
    assert Path(brain.cwd) == REPO and Path(tts.cwd) == REPO
    assert checked_ports == [[canonical["ports"]["brain_port"], canonical["ports"]["tera_tts"]]]


def test_explicit_worker_overrides_win_over_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path / "canonical")
    override_dir = tmp_path / "overrides"
    override_dir.mkdir()
    llm_exe = override_dir / "custom-brain.exe"
    llm_model = override_dir / "custom-model.gguf"
    tts_exe = override_dir / "custom-python.exe"
    tts_release = override_dir / "custom-tera"
    for path in (llm_exe, llm_model, tts_exe):
        path.write_bytes(b"override")
    tts_release.mkdir()

    monkeypatch.setattr(runtime_manifest, "load_runtime_manifest", lambda _root: manifest)
    checked_ports: list[list[int]] = []
    monkeypatch.setattr(worker_readiness, "require_free_ports", lambda ports: checked_ports.append(ports))
    _capture_supervisor(monkeypatch)

    specs = companion_main._build_worker_supervisor(
        _args(
            supervised_llm_command=str(llm_exe),
            supervised_llm_model=str(llm_model),
            supervised_tts_command=str(tts_exe),
            supervised_tts_release=str(tts_release),
            supervised_llm_port=21001,
            supervised_tts_port=21002,
        )
    )

    brain, tts = specs
    assert brain.command[0] == str(llm_exe)
    assert _option(brain.command, "--model") == str(llm_model)
    assert tts.command[0] == str(tts_exe)
    assert _option(tts.command, "--release-dir") == str(tts_release)
    assert _option(brain.command, "--port") == "21001"
    assert _option(tts.command, "--port") == "21002"
    assert checked_ports == [[21001, 21002]]


@pytest.mark.parametrize("missing", ["brain_exe", "brain_model", "tts_exe", "tts_release"])
def test_missing_worker_resources_fail_before_supervisor_construction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    manifest = _fixture_manifest(tmp_path)
    path_key = {
        "brain_exe": "brain_server_exe",
        "brain_model": "bonsai_model",
        "tts_exe": "tera_python",
        "tts_release": "tera_release",
    }[missing]
    absent_path = tmp_path / "absent" / path_key
    manifest["models"][path_key] = str(absent_path)
    monkeypatch.setattr(runtime_manifest, "load_runtime_manifest", lambda _root: manifest)
    factory = _capture_supervisor(monkeypatch)

    with pytest.raises(ValueError, match="missing"):
        companion_main._build_worker_supervisor(_args())

    factory.assert_not_called()


def test_reserved_and_duplicate_ports_fail_before_any_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_socket(*_args: object, **_kwargs: object) -> socket.socket:
        raise AssertionError("port preflight must reject before opening a probe socket")

    monkeypatch.setattr(worker_readiness.socket, "socket", unexpected_socket)
    with pytest.raises(ValueError, match="reserved"):
        worker_readiness.require_free_ports([8765])
    with pytest.raises(ValueError, match="collide"):
        worker_readiness.require_free_ports([23001, 23001])


def test_occupied_port_is_reported_without_disturbing_its_listener() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    address = listener.getsockname()
    try:
        with pytest.raises(ValueError, match="unavailable"):
            worker_readiness.require_free_ports([address[1]])
        assert listener.fileno() >= 0
        assert listener.getsockname() == address
    finally:
        listener.close()


class _Response:
    def __init__(self, payload: bytes = b"", status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.payload


@pytest.mark.parametrize(
    ("payload", "expected", "result"),
    [
        (b'{"data":[{"id":"hikari-fixture"}]}', "hikari-fixture", True),
        (b'{"data":[{"id":"other-model"}]}', "hikari-fixture", False),
        (b"not-json", "hikari-fixture", False),
        (b" " * 65537, "hikari-fixture", False),
    ],
    ids=["expected-alias", "wrong-alias", "malformed-json", "oversized-response"],
)
def test_model_readiness_requires_expected_bounded_valid_alias(
    monkeypatch: pytest.MonkeyPatch, payload: bytes, expected: str, result: bool
) -> None:
    requested: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        requested.append(url)
        assert timeout == 2
        return _Response() if url.endswith("/health") else _Response(payload)

    monkeypatch.setattr(worker_readiness, "urlopen", fake_urlopen)

    assert worker_readiness.model_ready(18990, expected) is result
    assert requested == [
        "http://127.0.0.1:18990/health",
        "http://127.0.0.1:18990/v1/models",
    ]
