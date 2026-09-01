"""Small, bounded readiness report for the local control plane."""

from __future__ import annotations

from typing import Any


def _health(provider: Any | None) -> dict[str, Any]:
    if provider is None:
        return {"status": "not_configured"}
    checker = getattr(provider, "health", None)
    if not callable(checker):
        return {"status": "ready"}
    try:
        value = checker()
    except Exception:  # noqa: BLE001 - doctor must never break the control plane
        return {"status": "offline", "reason": "health check failed"}
    return value if isinstance(value, dict) else {"status": "degraded"}


def _check(
    check_id: str,
    status: str,
    summary: str,
    *,
    required: bool = False,
    ready: bool | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    is_ready = status in {"connected", "online", "ready", "ok"} if ready is None else ready
    return {
        "id": check_id,
        "status": status,
        "ready": is_ready,
        "required": required,
        "summary": summary[:240],
        **({"action": action[:240]} if action else {}),
    }


def build_doctor_report(
    *,
    gateway: Any,
    hostos: Any,
    vision: Any,
    voice_mem: Any | None = None,
    asr: Any | None = None,
    tts: Any | None = None,
    avatar_assets: Any | None = None,
    ambient_memory: Any | None = None,
    ambient_audio: Any | None = None,
) -> dict[str, Any]:
    """Return bounded component readiness without exposing paths or secrets."""
    health = gateway.health()
    components = health.get("components", {}) if isinstance(health, dict) else {}
    checks: list[dict[str, Any]] = []

    jawl_status = str(components.get("jawl", "offline"))
    mock_mode = gateway.responder is None and jawl_status == "not_connected"
    checks.append(_check(
        "jawl", "mock" if mock_mode else jawl_status,
        "Text-only mock brain is available" if mock_mode else "JAWL chat transport",
        required=not mock_mode,
        ready=not mock_mode and jawl_status in {"connected", "online", "configured"},
        action="Configure --jawl-web-url or --jawl-port-file" if mock_mode else (
            "Check JAWL process and its correlated chat stream" if jawl_status not in {"connected", "online"} else None
        ),
    ))

    voice = _health(voice_mem)
    voice_status = str(voice.get("status", "degraded"))
    checks.append(_check(
        "voicemem", voice_status, "VoiceMem streaming sidecar",
        action="Configure --voicemem-python for voice input" if voice_status == "not_configured" else None,
    ))

    asr_health = _health(asr)
    asr_status = str(asr_health.get("status", "degraded"))
    checks.append(_check(
        "asr", asr_status, "External final-utterance ASR" if asr is not None else "External ASR is disabled",
        ready=asr is None or asr_status in {"connected", "online", "ready", "ok"},
        action="Configure --asr-url and --asr-model for Qwen3-ASR" if asr is None else None,
    ))

    speech = _health(tts)
    tts_status = str(speech.get("status", "degraded"))
    checks.append(_check(
        "tts", tts_status, "Russian speech synthesis",
        action="Configure --tts-url; text-only mode remains available" if tts_status == "not_configured" else None,
    ))

    vision_status = vision.status() if callable(getattr(vision, "status", None)) else {"configured": False}
    vision_ready = bool(vision_status.get("configured")) and bool(vision_status.get("screen_enabled"))
    checks.append(_check(
        "vision", "ready" if vision_ready else "not_configured",
        "Focused-window vision capture and VLM",
        ready=vision_ready,
        action="Enable --hostos-live, --screen-enabled and a VLM endpoint" if not vision_ready else None,
    ))

    avatar = avatar_assets.config() if avatar_assets is not None else {"ready": False}
    avatar_ready = bool(avatar.get("ready"))
    checks.append(_check(
        "avatar", "ready" if avatar_ready else "fallback",
        "Live2D bundle" if avatar_ready else "Reactive transparent 2D fallback avatar",
        ready=avatar_ready,
        action="Supply a validated user-owned Live2D model/runtime bundle" if not avatar_ready else None,
    ))

    dry_run = bool(getattr(hostos, "dry_run", True))
    checks.append(_check(
        "hostos", "dry_run" if dry_run else "live",
        "HostOS policy-only executor" if dry_run else "HostOS live executor",
        ready=not dry_run,
        action="Use --hostos-live only after reviewing roots and approvals" if dry_run else None,
    ))

    if ambient_memory is not None:
        memory_state = ambient_memory.state()
        enabled = bool(memory_state.get("enabled"))
        checks.append(_check(
            "ambient_memory", "ready" if enabled else "disabled",
            "Bounded ambient evidence" if enabled else "Ambient evidence is disabled",
            ready=enabled,
            action="Enable ambient memory only after reviewing retention and privacy controls" if not enabled else None,
        ))
    if ambient_audio is not None:
        audio_state = ambient_audio.state()
        configured = bool(audio_state.get("configured"))
        checks.append(_check(
            "ambient_audio", "ready" if configured else "not_configured",
            "System-audio loopback is configured" if configured else "System-audio loopback is not configured",
            ready=configured,
            action="Configure --ambient-audio and start it explicitly from the browser" if not configured else None,
        ))

    required_failures = [item for item in checks if item["required"] and not item["ready"]]
    warnings = [item for item in checks if not item["ready"]]
    overall = "blocked" if required_failures else "degraded" if warnings else "ready"
    return {
        "schema_version": 1,
        "status": overall,
        "text_mode_available": True,
        "checks": checks,
        "recommendations": [item["action"] for item in warnings if item.get("action")][:8],
    }
