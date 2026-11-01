"""Ownership policy for memory, aligned with the JAWL core.

JAWL owns durable memory.  Inside the pinned JAWL snapshot the canonical store
is ``SQLStructuredMemory`` (``structured_memories``: append-only revisions,
``kind``/``subject``/``predicate``/``value``, confidence, provenance, validity
window and retention tier) and only the agent — or the owner through JAWL's own
allowlisted operator control path — appends to it.

The companion therefore owns observation layers, not truth:

    observation -> temporary history -> candidate -> JAWL decision -> durable memory

* observations are model output, never facts;
* the rolling buffers exist so "what is happening now" survives while the brain
  is busy or restarting;
* the sensor history is text only and bounded, raw media is never persisted;
* a candidate is a *proposal*; JAWL decides whether it becomes memory.

This module is the single place that turns a companion observation into the
provenance JAWL receives.  Everything here is deliberately boring: no ranking,
no judgement, no wording that could pass a guess off as a fact.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Trust vocabulary shared by every producer.  ``verified`` means independently
# checked (for example the owner typed or said the fact himself), not "the model
# was confident".
TRUST_OWNER_STATED = "owner_stated"
TRUST_UNVERIFIED = "unverified_model_observation"

#: Retention tiers understood by JAWL's ``structured_memories`` table.
RETENTION_TIERS = ("short", "standard", "long", "permanent")

#: Event type the companion writes into JAWL's IPC event folder so the agent
#: can make the decision itself.
HANDOFF_EVENT_TYPE = "MEMORY_CANDIDATE"


def observation_class(payload: Mapping[str, Any] | None) -> str:
    """Name the observation honestly, for provenance and for the agent."""

    value = payload if isinstance(payload, Mapping) else {}
    stream = str(value.get("stream") or value.get("source") or "").strip().lower()
    modality = str(
        value.get("modality") or value.get("evidence_type") or ""
    ).strip().lower()
    audio_kind = str(value.get("audio_kind") or "").strip().lower()
    if stream in {"screen", "visual", "mixed"} and stream != "mixed":
        return "screen_description"
    if modality in {"visual", "screen", "screenshot"}:
        return "screen_description"
    if stream in {"system_audio", "audio"} or audio_kind:
        if audio_kind == "speech" or modality in {"speech", "asr_transcript"}:
            return "ambient_speech"
        if audio_kind == "music":
            return "music_observation"
        if audio_kind == "sound":
            return "sound_event"
        return "ambient_audio"
    return "ambient_observation"


def retention_tier_for(*, verified: bool, confidence: float, observation: str) -> str:
    """Map an observation onto JAWL's retention tiers.

    Owner-confirmed material deserves a long tier; an unverified model
    observation starts short so it expires unless JAWL keeps it.  Nothing here
    deletes anything by itself — the tier is the promise we make to JAWL.
    """

    if verified:
        return "long"
    if observation in {"screen_description", "music_observation", "sound_event"}:
        return "short"
    return "standard" if float(confidence) >= 0.7 else "short"


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.5
    return max(0.0, min(1.0, float(value)))


def _bounded(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _event_ids(values: Any) -> list[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return []
    result: list[str] = []
    for item in values:
        text = _bounded(item, 120)
        if text and text not in result:
            result.append(text)
    return result[:32]


def candidate_provenance(
    payload: Mapping[str, Any] | None,
    *,
    memory_key: str,
    triage_provider: str | None = None,
    episode_id: str | None = None,
) -> dict[str, Any]:
    """Build the provenance object JAWL stores with a candidate.

    JAWL's schema has no ``verified`` column, so the trust level travels inside
    ``provenance`` and inside the predicate.  ``confidence`` is never inflated:
    it is copied from the episode exactly as the sensors produced it.
    """

    value = payload if isinstance(payload, Mapping) else {}
    verified = value.get("verified") is True
    confidence = _confidence(value.get("confidence"))
    observation = observation_class(value)
    return {
        "schema_version": 1,
        "origin": "jawl_voicecompanion.ambient",
        "memory_key": _bounded(memory_key, 128),
        "trust": TRUST_OWNER_STATED if verified else TRUST_UNVERIFIED,
        "verified": verified,
        "observation_class": observation,
        "ambient_episode_id": _bounded(value.get("ambient_episode_id") or episode_id, 120),
        "source_event_ids": _event_ids(value.get("source_event_ids")),
        "observed_from": _bounded(value.get("observed_from"), 80),
        "observed_until": _bounded(value.get("observed_until"), 80),
        "triage_provider": _bounded(triage_provider or value.get("triage_provider") or "deterministic", 80),
        "confidence_calibrated": value.get("confidence_calibrated") is True,
        "raw_audio_persisted": False,
        "raw_frame_persisted": False,
    }


def predicate_for(*, verified: bool) -> str:
    """Keep the trust level visible in JAWL's own prompt projection.

    ``STRUCTURED MEMORY`` renders ``kind: subject — predicate = value``; putting
    the caveat in the predicate is the only way the agent keeps seeing it later.
    """

    return "episode_summary" if verified else "episode_summary_unverified"


def handoff_event(
    episode: Mapping[str, Any],
    *,
    memory_key: str,
    triage_provider: str | None = None,
    limit: int = 1200,
) -> dict[str, Any]:
    """Describe one candidate for JAWL's event intake.

    The companion proposes; the agent decides.  This dict is not a memory write:
    ``JawlEventFileSink.publish_candidate`` turns it into a bounded observation
    event that wakes JAWL's normal event pipeline.
    """

    payload = episode.get("payload") if isinstance(episode, Mapping) else None
    payload = payload if isinstance(payload, Mapping) else {}
    provenance = candidate_provenance(
        payload,
        memory_key=memory_key,
        triage_provider=triage_provider,
        episode_id=episode.get("event_id") if isinstance(episode, Mapping) else None,
    )
    summary = _bounded(payload.get("summary"), limit)
    return {
        "type": HANDOFF_EVENT_TYPE,
        "event_id": _bounded(episode.get("event_id") if isinstance(episode, Mapping) else "", 120),
        "payload": {
            "memory_key": provenance["memory_key"],
            "summary": summary,
            "trust": provenance["trust"],
            "verified": provenance["verified"],
            "observation_class": provenance["observation_class"],
            # Copied exactly as the sensors produced it - never inflated.
            "confidence": payload.get("confidence"),
            "retention_tier": retention_tier_for(
                verified=provenance["verified"],
                confidence=_confidence(payload.get("confidence")),
                observation=provenance["observation_class"],
            ),
            "source_event_ids": provenance["source_event_ids"],
            "observed_from": provenance["observed_from"],
            "observed_until": provenance["observed_until"],
            "triage_provider": provenance["triage_provider"],
            "provenance": provenance,
        },
    }


def memory_key_for(episode_id: str) -> str:
    """Deterministic key so a repeated proposal cannot fork one episode."""

    return f"ambient.episode.{_bounded(episode_id, 100)}"


def describe_pipeline() -> dict[str, Any]:
    """Machine-readable ownership map used by the UI and by docs checks."""

    return {
        "schema_version": 1,
        "writer": "jawl",
        "stages": [
            {"id": "perception", "owner": "companion", "ttl": "seconds", "durable": False},
            {"id": "sensory_history", "owner": "companion", "ttl": "1h detailed + 7d moments", "durable": "text_only"},
            {"id": "candidate", "owner": "companion", "ttl": "episode ttl", "durable": False},
            {"id": "memory", "owner": "jawl", "ttl": "retention_tier", "durable": True},
        ],
        "handoff_event_type": HANDOFF_EVENT_TYPE,
        "trust": {TRUST_OWNER_STATED: "owner confirmed", TRUST_UNVERIFIED: "model observation"},
        "retention_tiers": list(RETENTION_TIERS),
    }


__all__ = [
    "HANDOFF_EVENT_TYPE",
    "RETENTION_TIERS",
    "TRUST_OWNER_STATED",
    "TRUST_UNVERIFIED",
    "candidate_provenance",
    "describe_pipeline",
    "handoff_event",
    "memory_key_for",
    "observation_class",
    "predicate_for",
    "retention_tier_for",
]
