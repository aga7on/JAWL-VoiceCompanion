from pathlib import Path

from scripts.prepare_daily_profile import CONFIG_ROOT, PROFILE_ROOT, SOURCE_ROOT, prepare


def test_daily_profile_preparation_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.prepare_daily_profile.PROFILE_ROOT", tmp_path / "daily")
    first = prepare()
    soul = tmp_path / "daily" / "prompts" / "personality" / "SOUL.md"
    assert soul.read_text(encoding="utf-8") == (CONFIG_ROOT / "SOUL.md").read_text(encoding="utf-8")
    second = prepare()
    assert first[0] != second[0]
    assert second[0] == "created_files=0"
