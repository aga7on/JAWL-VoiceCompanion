"""Optional bounded description of music and non-speech audio.

Speech ASR and audio captioning are deliberately separate providers.  This
module only defines the small boundary between them; it does not select a
model or persist the supplied PCM bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AudioDescriptionUnavailable(RuntimeError):
    """Raised when an audio-description provider is unavailable or unsafe."""


class AudioDescriptionProvider(Protocol):
    name: str

    def describe(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        channels: int,
        clip_id: str,
    ) -> dict[str, Any]: ...


AUDIO_KINDS = frozenset({"speech", "music", "sound", "mixed", "unknown"})
MAX_DESCRIPTION_CHARS = 600
MAX_TAGS = 8
MAX_TAG_CHARS = 40
MAX_MOOD_CHARS = 80
MAX_CLIP_SECONDS = 30.0


@dataclass(frozen=True)
class AudioDescription:
    """Validated, text-only result safe to pass to delayed ambient memory."""

    schema_version: int
    clip_id: str
    kind: str
    description: str
    tags: tuple[str, ...]
    mood: str
    confidence: float
    duration_seconds: float
    raw_audio_persisted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "clip_id": self.clip_id,
            "kind": self.kind,
            "description": self.description,
            "tags": list(self.tags),
            "mood": self.mood,
            "confidence": self.confidence,
            "duration_seconds": self.duration_seconds,
            "raw_audio_persisted": False,
        }


AUDIO_DESCRIPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "description", "tags", "mood", "confidence", "duration_seconds"],
    "properties": {
        "kind": {"type": "string", "enum": sorted(AUDIO_KINDS)},
        "description": {"type": "string", "maxLength": MAX_DESCRIPTION_CHARS},
        "tags": {"type": "array", "items": {"type": "string", "maxLength": MAX_TAG_CHARS}, "maxItems": MAX_TAGS},
        "mood": {"type": "string", "maxLength": MAX_MOOD_CHARS},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "duration_seconds": {"type": "number", "minimum": 0, "maximum": MAX_CLIP_SECONDS},
    },
}


def validate_audio_description(result: Any, *, clip_id: str, duration_seconds: float) -> dict[str, Any]:
    """Fail closed and retain only bounded text metadata; never retain PCM."""
    if not isinstance(result, dict):
        raise AudioDescriptionUnavailable("audio description is not an object")
    kind = result.get("kind")
    description = result.get("description")
    tags = result.get("tags")
    mood = result.get("mood", "")
    confidence = result.get("confidence")
    if kind not in AUDIO_KINDS or not isinstance(description, str) or not description.strip():
        raise AudioDescriptionUnavailable("audio description has invalid kind or text")
    if not isinstance(tags, list) or len(tags) > MAX_TAGS or any(not isinstance(item, str) for item in tags):
        raise AudioDescriptionUnavailable("audio description has invalid tags")
    if not isinstance(mood, str):
        raise AudioDescriptionUnavailable("audio description has invalid mood")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise AudioDescriptionUnavailable("audio description has invalid confidence")
    duration = float(duration_seconds)
    if duration <= 0 or duration > MAX_CLIP_SECONDS:
        raise AudioDescriptionUnavailable("audio description clip is outside the bounded duration")
    bounded_tags = tuple(item.replace("\x00", "").strip()[:MAX_TAG_CHARS] for item in tags if item.strip())
    return AudioDescription(
        schema_version=1,
        clip_id=str(clip_id or "audio-clip")[:120],
        kind=kind,
        description=description.replace("\x00", "").strip()[:MAX_DESCRIPTION_CHARS],
        tags=bounded_tags,
        mood=mood.replace("\x00", "").strip()[:MAX_MOOD_CHARS],
        confidence=round(float(confidence), 3),
        duration_seconds=round(duration, 3),
    ).as_dict()


class AudioDescriptionService:
    """Validate a provider result while bounding the transient input clip."""

    def __init__(self, provider: AudioDescriptionProvider, *, max_clip_seconds: float = MAX_CLIP_SECONDS) -> None:
        if not hasattr(provider, "describe"):
            raise TypeError("audio description provider must provide describe")
        self.provider = provider
        self.max_clip_seconds = max(1.0, min(float(max_clip_seconds), MAX_CLIP_SECONDS))

    def describe(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        channels: int,
        clip_id: str,
    ) -> dict[str, Any]:
        if not isinstance(pcm16, bytes) or not pcm16 or len(pcm16) % 2:
            raise ValueError("audio description input must be non-empty PCM16")
        if isinstance(sample_rate, bool) or not 8000 <= int(sample_rate) <= 96000:
            raise ValueError("audio description sample rate is unsupported")
        if isinstance(channels, bool) or not 1 <= int(channels) <= 2:
            raise ValueError("audio description channels must be 1 or 2")
        duration = len(pcm16) / 2 / int(channels) / int(sample_rate)
        if duration <= 0 or duration > self.max_clip_seconds:
            raise ValueError("audio description clip is too long")
        result = self.provider.describe(
            pcm16,
            sample_rate=int(sample_rate),
            channels=int(channels),
            clip_id=str(clip_id or "audio-clip")[:120],
        )
        return validate_audio_description(result, clip_id=clip_id, duration_seconds=duration)


__all__ = [
    "AUDIO_DESCRIPTION_SCHEMA",
    "AUDIO_KINDS",
    "AudioDescription",
    "AudioDescriptionProvider",
    "AudioDescriptionService",
    "AudioDescriptionUnavailable",
    "validate_audio_description",
]
