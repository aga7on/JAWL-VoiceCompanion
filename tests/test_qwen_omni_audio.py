from __future__ import annotations

import base64
import io
import json
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

def audible_pcm16(sample_count: int) -> bytes:
    return b"\x00\x10" * sample_count

from jawl_voicecompanion.audio_understanding import AudioDescriptionService, AudioDescriptionUnavailable
from jawl_voicecompanion.qwen_omni_audio import QwenOmniAudioDescriptionProvider


def test_qwen_audio_provider_sends_bounded_wav_and_returns_validated_music() -> None:
    captured: dict = {}

    def transport(payload: dict) -> str:
        captured.update(payload)
        audio = payload["messages"][0]["content"][1]["input_audio"]
        wav_bytes = base64.b64decode(audio["data"])
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            assert wav.getframerate() == 16_000
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getnframes() == 16_000
        return json.dumps({
            "kind": "music",
            "description": "Electronic dance fragment; audible word hello.",
            "tags": ["electronic", "dance"],
            "mood": "energetic",
            "confidence": 0.82,
            "duration_seconds": 1.0,
        }, ensure_ascii=False)

    service = AudioDescriptionService(QwenOmniAudioDescriptionProvider(
        "http://127.0.0.1:8990/v1",
        model="local-qwen3-omni",
        transport=transport,
    ))
    result = service.describe(audible_pcm16(16_000), sample_rate=16_000, channels=1, clip_id="clip-1")

    assert result["kind"] == "music"
    assert result["tags"] == ["electronic", "dance"]
    assert result["raw_audio_persisted"] is False
    assert captured["model"] == "local-qwen3-omni"
    assert captured["messages"][0]["content"][1]["type"] == "input_audio"
    response_format = captured["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert "sung vocals with accompaniment as music" in captured["messages"][0]["content"][0]["text"]


@pytest.mark.parametrize("response", ["no json", "{bad json}", "[]"])
def test_qwen_audio_provider_rejects_malformed_description(response: str) -> None:
    provider = QwenOmniAudioDescriptionProvider(
        "http://127.0.0.1:8990/v1",
        model="local-qwen3-omni",
        transport=lambda payload: response,
    )
    service = AudioDescriptionService(provider)
    with pytest.raises(AudioDescriptionUnavailable):
        service.describe(audible_pcm16(160), sample_rate=16_000, channels=1, clip_id="clip-1")


def test_qwen_audio_provider_normalizes_optional_null_fields() -> None:
    provider = QwenOmniAudioDescriptionProvider(
        "http://127.0.0.1:8990/v1",
        model="local-qwen3-omni",
        transport=lambda payload: json.dumps({
            "kind": "music", "description": "Dance music.",
            "tags": None, "mood": None, "confidence": 1.4,
        }, ensure_ascii=False),
    )
    result = AudioDescriptionService(provider).describe(
        audible_pcm16(160), sample_rate=16_000, channels=1, clip_id="clip-1"
    )
    assert result["tags"] == []
    assert result["mood"] == ""
    assert result["confidence"] == 1.0


def test_qwen_audio_provider_skips_silence_without_calling_model() -> None:
    def fail_if_called(payload: dict) -> str:
        raise AssertionError("silence should be gated before inference")

    provider = QwenOmniAudioDescriptionProvider(
        "http://127.0.0.1:8990/v1",
        model="local-qwen3-omni",
        transport=fail_if_called,
    )
    result = AudioDescriptionService(provider).describe(
        b"\0\0" * 16_000, sample_rate=16_000, channels=1, clip_id="silent"
    )
    assert result["kind"] == "unknown"
    assert result["raw_audio_persisted"] is False
