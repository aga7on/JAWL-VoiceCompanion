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


AUDIO_KINDS = frozenset({"speech", "music", "sound", "unknown"})
TENTATIVE_RHYTHM_CUE = "Possible rhythmic sound; music is not independently verified."
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
    candidate_hypotheses: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        result = {
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
        if self.candidate_hypotheses:
            result["candidate_hypotheses"] = [
                {
                    "category": item["category"],
                    "candidates": [dict(candidate) for candidate in item["candidates"]],
                }
                for item in self.candidate_hypotheses
            ]
        return result


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
        "candidate_hypotheses": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["category", "candidates"],
                "properties": {
                    "category": {"type": "string", "maxLength": 40},
                    "candidates": {
                        "type": "array", "maxItems": 2,
                        "items": {
                            "type": "object", "additionalProperties": False,
                            "required": ["label", "similarity"],
                            "properties": {
                                "label": {"type": "string", "maxLength": 80},
                                "similarity": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                        },
                    },
                },
            },
        },
    },
}


def safe_detailed_audio_claim(observation: Any, *, transcript: str = "") -> dict[str, Any]:
    """Project EG2's raw observation into claims safe for ambient context.

    EG2's speech/music flags share heuristic DSP, so simultaneous flags mean
    speech only. A music claim is retained only when the existing music gate is
    true and speech is absent. Similarity scores are deliberately not exposed
    as calibrated confidence.
    """
    level2 = getattr(observation, "level2", {})
    level1 = getattr(observation, "level1", {})
    dsp = level2.get("dsp", {}) if isinstance(level2, dict) else {}
    speech = bool(dsp.get("is_speech_likely")) or bool(str(transcript or "").strip())
    music = bool(dsp.get("is_music_likely"))
    try:
        rms = float(dsp.get("rms_dbfs", -100.0))
    except (TypeError, ValueError):
        rms = -100.0
    duration = dsp.get("duration_s", 0.1)
    try:
        duration = max(0.1, min(float(duration), MAX_CLIP_SECONDS))
    except (TypeError, ValueError):
        duration = 0.1

    transcript_text = str(transcript or "").strip()
    if transcript_text:
        return {
            "kind": "speech",
            "description": transcript_text[:MAX_DESCRIPTION_CHARS],
            "tags": [], "mood": "", "confidence": 0.0, "duration_seconds": duration,
        }
    if speech:
        # A DSP speech heuristic alone is not enough: the preserved A16 noise
        # negative sets this flag alongside the music heuristic.
        return {
            "kind": "unknown", "description": "Audio event not identified.",
            "tags": [], "mood": "", "confidence": 0.0, "duration_seconds": duration,
        }
    if rms < -55.0:
        return {
            "kind": "unknown", "description": "No reliable audio event detected.",
            "tags": [], "mood": "", "confidence": 0.0, "duration_seconds": duration,
        }
    if not music:
        return {
            "kind": "sound", "description": "Audio event not identified.",
            "tags": [], "mood": "", "confidence": 0.0, "duration_seconds": duration,
        }

    # The same heuristic gate accepts at least one synthetic-noise fixture;
    # preserve a tentative rhythm cue only, never genre/mood/BPM/key claims.
    return {
        "kind": "sound",
        "description": TENTATIVE_RHYTHM_CUE,
        "tags": [], "mood": "", "confidence": 0.0, "duration_seconds": duration,
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
    if kind == "mixed":
        raise AudioDescriptionUnavailable("mixed audio requires an independent overlap detector")
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
    bounded_description = description.replace("\x00", "").strip()[:MAX_DESCRIPTION_CHARS]
    bounded_mood = mood.replace("\x00", "").strip()[:MAX_MOOD_CHARS]
    raw_hypotheses = result.get("candidate_hypotheses", [])
    if not isinstance(raw_hypotheses, list) or len(raw_hypotheses) > 8:
        raise AudioDescriptionUnavailable("audio candidate hypotheses are invalid")
    bounded_hypotheses: list[dict[str, Any]] = []
    for hypothesis in raw_hypotheses:
        if not isinstance(hypothesis, dict):
            raise AudioDescriptionUnavailable("audio candidate hypothesis is not an object")
        category = hypothesis.get("category")
        candidates = hypothesis.get("candidates")
        if not isinstance(category, str) or not category.strip() or not isinstance(candidates, list) or len(candidates) > 2:
            raise AudioDescriptionUnavailable("audio candidate hypothesis has invalid fields")
        bounded_candidates = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise AudioDescriptionUnavailable("audio candidate is not an object")
            label = candidate.get("label")
            similarity = candidate.get("similarity")
            if (
                not isinstance(label, str) or not label.strip()
                or isinstance(similarity, bool) or not isinstance(similarity, (int, float))
                or not 0 <= float(similarity) <= 1
            ):
                raise AudioDescriptionUnavailable("audio candidate has invalid label or similarity")
            bounded_candidates.append({
                "label": label.replace("\x00", "").strip()[:80],
                "similarity": round(float(similarity), 4),
            })
        if bounded_candidates:
            bounded_hypotheses.append({
                "category": category.replace("\x00", "").strip()[:40],
                "candidates": bounded_candidates,
            })
    tentative_rhythm = (
        kind == "sound"
        and description.strip() == TENTATIVE_RHYTHM_CUE
        and not bounded_tags
        and not bounded_mood
        and float(confidence) == 0.0
    )
    if kind in {"unknown", "sound", "speech"}:
        # These classes do not establish music mood/genre or detailed SFX.
        bounded_description = {
            "unknown": "No reliable audio event detected.",
            "sound": TENTATIVE_RHYTHM_CUE if tentative_rhythm else "Audio event not identified.",
            "speech": "Speech detected; background music is not independently confirmed.",
        }[kind]
        bounded_tags = ()
        bounded_mood = ""
        bounded_confidence = 0.0
    else:
        bounded_confidence = round(float(confidence), 3)
    return AudioDescription(
        schema_version=1,
        clip_id=str(clip_id or "audio-clip")[:120],
        kind=kind,
        description=bounded_description,
        tags=bounded_tags,
        mood=bounded_mood,
        confidence=bounded_confidence,
        duration_seconds=round(duration, 3),
        candidate_hypotheses=tuple(bounded_hypotheses),
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
    "safe_detailed_audio_claim",
    "TENTATIVE_RHYTHM_CUE",
]
