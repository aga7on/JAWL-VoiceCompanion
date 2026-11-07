"""Tests for A-MEM NarrativeConsolidator."""

from __future__ import annotations

import json
import time
from typing import Any
import pytest

from jawl_voicecompanion.narrative_consolidator import NarrativeConsolidator


def test_narrative_consolidator_init_and_feed() -> None:
    nc = NarrativeConsolidator(consolidation_interval_sec=60.0, silence_trigger_sec=5.0)
    st = nc.state()
    assert st["total_episode_logs"] == 0
    assert st["total_character_cards"] == 0
    assert "Начало" in nc.get_last_story_line()

    nc.feed_subtitle("Привет! Куда идём?", speaker="Alice")
    nc.feed_subtitle("В подземелье к дракону.", speaker="Bob")
    nc.feed_keyframe("frm_001", "cache/frm_001.webp", summary="Вход в темную пещеру")

    st2 = nc.state()
    assert st2["subtitles_buffered"] == 2
    assert st2["keyframes_buffered"] == 1


def test_narrative_consolidator_triggers() -> None:
    nc = NarrativeConsolidator(consolidation_interval_sec=1.0, silence_trigger_sec=2.0)

    # Empty buffer should not trigger
    assert nc.check_trigger(silence_duration_sec=10.0) is False

    nc.feed_subtitle("Что-то происходит...")

    # Forced trigger
    assert nc.check_trigger(force=True) is True

    # Silence trigger (elapsed needs to be >= 30s or interval met)
    time.sleep(1.1)
    assert nc.check_trigger() is True


def test_narrative_consolidator_mock_llm() -> None:
    mock_llm_response = {
        "episode_log": "14:30 — Герои вошли в подземелье, Боб обнаружил тайный сундук.",
        "updated_entities": [
            {
                "name": "Боб",
                "new_trait": "внимательный искатель сокровищ",
                "keyframe_id": "frm_002.webp",
            },
            {
                "name": "Алиса",
                "new_trait": "лидер отряда магов",
                "keyframe_id": "frm_001.webp",
            },
        ],
    }

    class MockLLM:
        def complete(self, prompt: str) -> str:
            assert "субтитры" in prompt.lower()
            return f"```json\n{json.dumps(mock_llm_response, ensure_ascii=False)}\n```"

    nc = NarrativeConsolidator(llm_client=MockLLM())
    nc.feed_subtitle("Я вижу сундук!", speaker="Bob")
    nc.feed_keyframe("frm_002", "cache/frm_002.webp", summary="Сундук с золотом")

    res = nc.consolidate(force=True)
    assert res is not None
    assert "сундук" in res["episode_log"]
    assert len(res["updated_entities"]) == 2

    # Check state updates
    last_line = nc.get_last_story_line()
    assert "тайный сундук" in last_line

    cards = nc.get_character_cards()
    assert len(cards) == 2
    names = {c["name"] for c in cards}
    assert "Боб" in names
    assert "Алиса" in names


def test_narrative_consolidator_fallback_without_llm() -> None:
    nc = NarrativeConsolidator(llm_client=None)
    nc.feed_subtitle("Осторожно, здесь ловушка!", speaker="Hero")
    nc.feed_keyframe("frm_trap", "cache/trap.webp", summary="Шипы на полу")

    res = nc.consolidate(force=True)
    assert res is not None
    assert "ловушка" in res["episode_log"]
    assert nc.state()["total_episode_logs"] == 1


def test_narrative_consolidator_persistence_across_restarts(tmp_path) -> None:
    store_file = tmp_path / "narrative.json"

    mock_llm_response = {
        "episode_log": "15:00 — Секретная операция Дельта завершена успешно.",
        "updated_entities": [
            {
                "name": "Агент Дельта",
                "new_trait": "мастер скрытности",
                "keyframe_id": "frm_delta_01.webp",
            },
            {
                "name": "Напарник",
                "new_trait": "связной штаба",
                "keyframe_id": "frm_hq_02.webp",
            },
        ],
    }

    class MockLLM:
        def complete(self, prompt: str) -> str:
            return json.dumps(mock_llm_response, ensure_ascii=False)

    nc1 = NarrativeConsolidator(llm_client=MockLLM(), storage_path=store_file)
    nc1.feed_subtitle("Докладываю: операция завершена.")
    nc1.consolidate(force=True)

    assert store_file.exists()
    assert nc1.state()["total_episode_logs"] == 1
    assert nc1.state()["total_character_cards"] == 2

    # Simulate process restart by creating a new instance pointing to same file
    nc2 = NarrativeConsolidator(storage_path=store_file)
    assert nc2.state()["total_episode_logs"] == 1
    assert "Дельта" in nc2.get_last_story_line()
    cards2 = nc2.get_character_cards()
    assert len(cards2) == 2
    names = {c["name"] for c in cards2}
    assert "Агент Дельта" in names
    assert "Напарник" in names


def test_narrative_consolidator_redact(tmp_path) -> None:
    store_file = tmp_path / "narrative_redact.json"

    nc = NarrativeConsolidator(storage_path=store_file)
    nc._episode_logs = [
        "12:00 — Обычный диалог в кафе",
        "12:15 — Конфиденциальное обсуждение секретного проекта Orion",
        "12:30 — Возвращение в офис",
    ]
    nc._character_cards = {
        "Джон": {"name": "Джон", "traits": ["бариста"], "keyframe_id": "frame_cafe.webp"},
        "Орион-Куратор": {"name": "Орион-Куратор", "traits": ["секретный агент"], "keyframe_id": "frame_orion.webp"},
    }
    nc._save()

    # Redact by keyword / identifier "Orion"
    res = nc.redact(["Orion", "Орион-Куратор"], reason="GDPR forget request")
    assert res["status"] == "redacted"
    assert res["deleted_logs"] == 1
    assert res["deleted_cards"] == 1
    assert res["remaining_cards"] == 1

    # In-memory checks
    assert len(nc._episode_logs) == 2
    assert not any("Orion" in log for log in nc._episode_logs)
    cards = nc.get_character_cards()
    assert len(cards) == 1
    assert cards[0]["name"] == "Джон"

    # Disk checks after reload
    reloaded = NarrativeConsolidator(storage_path=store_file)
    assert len(reloaded._episode_logs) == 2
    assert not any("Orion" in log for log in reloaded._episode_logs)
    assert len(reloaded.get_character_cards()) == 1
    assert reloaded.get_character_cards()[0]["name"] == "Джон"

