"""Small, bounded readiness report for the local control plane."""

from __future__ import annotations

from typing import Any


def _health(provider: Any | None) -> dict[str, Any]:
    if provider is None:
        return {"status": "not_configured"}
    checker = getattr(provider, "health", None)
    if not callable(checker):
        return {"status": "configured"}
    try:
        value = checker()
    except Exception:  # noqa: BLE001 - doctor must never break the control plane
        return {"status": "offline", "reason": "health check failed"}
    if not isinstance(value, dict) or any(
        key in value and value[key] is not True for key in ("ok", "ready")
    ):
        return {"status": "degraded"}
    return value


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
    resource_governor: Any | None = None,
    streaming_asr: Any | None = None,
    helper_urls: dict[str, str] | None = None,
    sensory_ingestor: Any | None = None,
    gigaam_transcriber: Any | None = None,
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
        ready=not mock_mode and jawl_status in {"connected", "online"},
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

    if gigaam_transcriber is not None:
        checks.append(_check(
            "asr", "gigaam",
            "Sber GigaAM batch final (crispasr); Qwen3-ASR is an optional fallback",
            ready=True,
        ))
    else:
        asr_health = _health(asr)
        asr_status = str(asr_health.get("status", "degraded"))
        checks.append(_check(
            "asr", asr_status, "External final-utterance ASR" if asr is not None else "External ASR is disabled",
            ready=asr is not None and asr_status in {"connected", "online", "ready", "ok"},
            action="Configure --asr-url and --asr-model for Qwen3-ASR" if asr is None else None,
        ))

    speech = _health(tts)
    tts_status = str(speech.get("status", "degraded"))
    checks.append(_check(
        "tts", tts_status, "Russian speech synthesis",
        action="Configure --tts-url; text-only mode remains available" if tts_status == "not_configured" else None,
    ))

    vision_status = vision.status() if callable(getattr(vision, "status", None)) else {"configured": False}
    # status() exposes configuration, not a live capture/model readiness probe.
    vision_configured = vision_status.get("configured") is True
    checks.append(_check(
        "vision", "configured" if vision_configured else "not_configured",
        "Vision configured; live capture/model not verified" if vision_configured else "Vision is disabled",
        ready=False,
        action="Validate the selected Vision profile" if vision_configured else "Vision selection is deferred; text/voice can work without it",
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
        capture = audio_state.get("capture", {})
        running = configured and capture.get("running") is True and not capture.get("last_error")
        checks.append(_check(
            "ambient_audio", "running" if running else "configured" if configured else "not_configured",
            "System-audio capture is running; ASR acceptance is separate" if running else "System-audio capture is not running",
            ready=running,
            action="Review consent and start system-audio capture explicitly" if not running else None,
        ))

    if resource_governor is not None:
        resource_state = resource_governor.state()
        checks.append(_check(
            "resources", "ready", "Bounded speech/vision/ambient resource governor",
            ready=True,
            action="Review the active resource profile" if resource_state.get("gaming_mode") else None,
        ))

    if streaming_asr is not None:
        snapshot = {}
        try:
            snapshot = streaming_asr.snapshot()
        except Exception:  # noqa: BLE001 - doctor must never break the control plane
            snapshot = {}
        active = bool(snapshot.get("active"))
        checks.append(_check(
            "streaming_asr", "online" if active else "idle",
            "Streaming ASR lane (partial drafts + adaptive endpoint)" if active else "Streaming ASR idle until capture",
            ready=True,
        ))
    if sensory_ingestor is not None:
        sensory_state = sensory_ingestor.state()
        running = bool(sensory_state.get("running"))
        counters = sensory_state.get("counters", {})
        checks.append(_check(
            "sensory_ingest", "online" if running else "stopped",
            "Sensory NDJSON -> ambient memory"
            f" (visual={counters.get('visual', 0)} music={counters.get('music', 0)} speech={counters.get('speech', 0)})",
            ready=running,
        ))
    for name, url in sorted((helper_urls or {}).items()):
        status = "offline"
        try:
            import urllib.request
            request = urllib.request.Request(str(url), headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=1.5) as response:
                status = "online" if int(response.status) < 500 else "degraded"
        except Exception:  # noqa: BLE001 - helpers are optional
            status = "offline"
        checks.append(_check(
            f"helper_{name}", status,
            f"Local helper: {name}",
            ready=status == "online",
        ))

    required_failures = [item for item in checks if item["required"] and not item["ready"]]
    warnings = [item for item in checks if not item["ready"]]
    overall = "blocked" if required_failures else "degraded" if warnings else "ready"
    return {
        "schema_version": 1,
        "status": overall,
        "text_mode_available": mock_mode or jawl_status in {"connected", "online"},
        "checks": checks,
        "recommendations": [item["action"] for item in warnings if item.get("action")][:8],
    }
