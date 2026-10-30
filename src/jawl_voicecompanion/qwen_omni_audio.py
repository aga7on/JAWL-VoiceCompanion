"""Bounded audio description through the active Qwen3-Omni endpoint.

The provider accepts a short PCM clip, creates a transient WAV payload and
retains only the validated text description returned by the local model.
"""

from __future__ import annotations

import base64
import io
import json
import math
import sys
import wave
from array import array
from typing import Any, Callable

import requests

from .audio_understanding import AudioDescriptionUnavailable


DEFAULT_AUDIO_PROMPT = (
    "Listen only to the attached audio. Classify sung vocals with accompaniment as music. "
    "Describe clearly audible sources, broad style, instruments, rhythm and dynamics in "
    "one concise sentence (at most 24 words). Quote words only when unmistakable. Never "
    "invent lyrics or sounds. Use tags and mood only when clearly supported; otherwise "
    "leave them empty. Return the requested fields only."
)

AUDIO_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["speech", "music", "sound", "unknown"]},
        "description": {"type": "string", "maxLength": 300},
        "tags": {"type": "array", "items": {"type": "string", "maxLength": 48}, "maxItems": 4},
        "mood": {"type": "string", "maxLength": 32},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "duration_seconds": {"type": "number", "minimum": 0, "maximum": 15},
    },
    "required": ["kind", "description", "tags", "mood", "confidence", "duration_seconds"],
    "additionalProperties": False,
}


class QwenOmniAudioDescriptionProvider:
    """OpenAI-compatible Qwen3-Omni audio-only descriptor."""

    name = "qwen3-omni"

    def __init__(
        self,
        base_url: str,
        *,
        model: str,
        timeout: float = 30.0,
        max_tokens: int = 128,
        prompt: str = DEFAULT_AUDIO_PROMPT,
        transport: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        value = str(base_url or "").strip().rstrip("/")
        for suffix in ("/chat/completions", "/responses"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
        self.base_url = value
        self.model = str(model or "").strip()
        self.timeout = max(1.0, float(timeout))
        self.max_tokens = max(48, min(int(max_tokens), 512))
        self.prompt = str(prompt or DEFAULT_AUDIO_PROMPT).strip()
        self._transport = transport or self._http_transport
        if not self.base_url or not self.model:
            raise ValueError("Qwen3-Omni audio endpoint and model are required")

    @staticmethod
    def _wav_base64(pcm16: bytes, sample_rate: int, channels: int) -> str:
        target = io.BytesIO()
        with wave.open(target, "wb") as wav:
            wav.setnchannels(int(channels))
            wav.setsampwidth(2)
            wav.setframerate(int(sample_rate))
            wav.writeframes(pcm16)
        return base64.b64encode(target.getvalue()).decode("ascii")

    def _payload(self, pcm16: bytes, sample_rate: int, channels: int) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": self.prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": self._wav_base64(pcm16, sample_rate, channels),
                            "format": "wav",
                        },
                    },
                ],
            }],
            "temperature": 0.0,
            "max_tokens": self.max_tokens,
            "stream": False,
            # Prompt-only JSON elicitation produced empty or truncated replies
            # on Qwen3-Omni. Constrain the response at the server so the
            # validated live observation keeps its structured fields.
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "audio_description",
                    "strict": True,
                    "schema": AUDIO_RESPONSE_SCHEMA,
                },
            },
            # Multimodal cache reuse was disabled in the passing direct Omni
            # probes. Audio content is carried outside ordinary text tokens.
            "cache_prompt": False,
        }

    def _http_transport(self, payload: dict[str, Any]) -> str:
        response = requests.post(
            self.base_url + "/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") if isinstance(body, dict) else None
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content", "") if isinstance(message, dict) else ""
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            )
        if not isinstance(content, str) or not content.strip():
            raise AudioDescriptionUnavailable("Qwen3-Omni returned no audio description")
        return content.strip()

    @staticmethod
    def _parse_object(text: str) -> dict[str, Any]:
        value = str(text or "").strip()
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise AudioDescriptionUnavailable("Qwen3-Omni audio description is not JSON")
        try:
            parsed = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AudioDescriptionUnavailable("Qwen3-Omni audio JSON is invalid") from exc
        if not isinstance(parsed, dict):
            raise AudioDescriptionUnavailable("Qwen3-Omni audio result is not an object")
        return parsed

    def describe(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        channels: int,
        clip_id: str,
    ) -> dict[str, Any]:
        # Duration and bounds are enforced by AudioDescriptionService before
        # this method is called. Keep only the result; the byte payload is
        # transient and is never written to disk by this provider.
        del clip_id
        samples = array("h")
        samples.frombytes(pcm16)
        if sys.byteorder != "little":
            samples.byteswap()
        rms = math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))
        duration = len(pcm16) / 2 / int(channels) / int(sample_rate)
        if rms < 58.3:  # approximately -55 dBFS; do not ask the model to narrate silence
            return {
                "kind": "unknown",
                "description": "No reliable audio event detected.",
                "tags": [],
                "mood": "",
                "confidence": 0.0,
                "duration_seconds": duration,
            }
        result = self._parse_object(self._transport(self._payload(pcm16, sample_rate, channels)))
        # Some generations use JSON null for optional fields despite the
        # schema prompt. Normalize only optional metadata; malformed content
        # itself remains a fail-closed error in AudioDescriptionService.
        if result.get("mood") is None:
            result["mood"] = ""
        if not isinstance(result.get("mood"), str):
            result["mood"] = ""
        raw_tags = result.get("tags")
        result["tags"] = [tag for tag in raw_tags[:8] if isinstance(tag, str)] if isinstance(raw_tags, list) else []
        confidence = result.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            result["confidence"] = 0.0
        else:
            result["confidence"] = max(0.0, min(1.0, float(confidence)))
        return result


__all__ = ["DEFAULT_AUDIO_PROMPT", "QwenOmniAudioDescriptionProvider"]
