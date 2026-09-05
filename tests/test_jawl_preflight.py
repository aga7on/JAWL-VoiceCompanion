from scripts.preflight_jawl_runtime import check


def test_daily_profile_preflight_has_no_missing_files(monkeypatch, tmp_path):
    model = tmp_path / "model.onnx"
    files = [tmp_path / name for name in ("settings.yaml", "interfaces.yaml", "SOUL.md")]
    for path in files + [model]:
        path.write_text("ready", encoding="utf-8")
    required = tuple(files + [model])
    monkeypatch.setattr("scripts.preflight_jawl_runtime.REQUIRED", required)
    monkeypatch.setattr("scripts.preflight_jawl_runtime.PROFILE_ROOT", tmp_path)
    assert check()["ok"] is True


def test_preflight_reports_missing_embedding_cache(monkeypatch, tmp_path):
    required = (tmp_path / "settings.yaml", tmp_path / "model.onnx")
    required[0].write_text("ready", encoding="utf-8")
    monkeypatch.setattr("scripts.preflight_jawl_runtime.REQUIRED", required)
    monkeypatch.setattr("scripts.preflight_jawl_runtime.PROFILE_ROOT", tmp_path)
    result = check()
    assert result["ok"] is False
    assert result["embedding_cache"] == "missing"
