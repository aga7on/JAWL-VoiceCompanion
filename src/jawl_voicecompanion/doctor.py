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


def _voice_health_snapshot(provider: Any | None) -> dict[str, Any]:
    """Use cached process state for VoiceMem instead of a blocking pipe probe."""
    if provider is None:
        return {"status": "not_configured"}
    state = getattr(provider, "state", None)
    if callable(state):
        try:
            value = state()
        except Exception:  # noqa: BLE001 - readiness must stay non-blocking
            return {"status": "offline"}
        if isinstance(value, dict) and "running" in value:
            if value.get("running") is not True:
                status = "offline" if value.get("status") not in {"not_started", "stopped"} else str(value.get("status"))
            elif value.get("last_request_ok") is False:
                status = "degraded"
            elif value.get("ready") is True:
                status = "ready"
            else:
                status = "starting"
            return {**value, "status": status, "health_probe": "cached_process_state"}
    return _health(provider)


def _check(
    check_id: str,
    status: str,
    summary: str,
    *,
    required: bool = False,
    ready: bool | None = None,
    state: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    is_ready = status in {"connected", "online", "ready", "ok"} if ready is None else ready
    if state is None:
        state = "ok" if is_ready else ("error" if required else "off")
    return {
        "id": check_id,
        "status": status,
        "state": state,
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
    ambient_memory: Any | None = None,
    ambient_audio: Any | None = None,
    resource_governor: Any | None = None,
    streaming_asr: Any | None = None,
    visual_sensor: Any | None = None,
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
        state="warn" if mock_mode else None,
        action="Configure --jawl-web-url or --jawl-port-file" if mock_mode else (
            "Check JAWL process and its correlated chat stream" if jawl_status not in {"connected", "online"} else None
        ),
    ))

    voice = _voice_health_snapshot(voice_mem)
    voice_status = str(voice.get("status", "degraded"))
    voice_ready = voice_status in {"connected", "online", "ready", "ok"}
    checks.append(_check(
        "voicemem", voice_status, "VoiceMem streaming sidecar",
        ready=voice_ready,
        state="ok" if voice_ready else "off" if voice_mem is None else "warn",
        action="Configure --voicemem-python for voice input" if voice_mem is None else None,
    ))

    if gigaam_transcriber is not None:
        checks.append(_check(
            "asr", "gigaam",
            "Sber GigaAM (crispasr) is the only ASR engine; there is no provider fallback",
            ready=True,
        ))
    else:
        asr_health = _health(asr)
        asr_status = str(asr_health.get("status", "degraded"))
        asr_ready = asr is not None and asr_status in {"connected", "online", "ready", "ok"}
        checks.append(_check(
            "asr", asr_status, "GigaAM final ASR" if asr is not None else "GigaAM ASR is disabled",
            ready=asr_ready,
            state="ok" if asr_ready else "off" if asr is None else "warn",
            action="Pass --streaming-asr-exe and --streaming-asr-model (GigaAM/crispasr)" if asr is None else None,
        ))

    speech = _health(tts)
    tts_status = str(speech.get("status", "degraded"))
    tts_ready = tts_status in {"connected", "online", "ready", "ok"}
    checks.append(_check(
        "tts", tts_status, "Russian speech synthesis",
        ready=tts_ready,
        state="ok" if tts_ready else "off" if tts is None else "warn",
        action="Configure --tts-url; text-only mode remains available" if tts is None else None,
    ))

    vision_status = vision.status() if callable(getattr(vision, "status", None)) else {"configured": False}
    vision_configured = vision_status.get("configured") is True
    vision_enabled = vision_configured and vision_status.get("screen_enabled") is True
    visual_state = visual_sensor.state() if visual_sensor is not None else None
    if isinstance(visual_state, dict):
        visual_running = visual_state.get("running") is True
        visual_live = (
            visual_running
            and int(visual_state.get("captures") or 0) > 0
            and int(visual_state.get("delivered") or 0) > 0
            and visual_state.get("caption_fresh") is True
        )
        checks.append(_check(
            "vision", "online" if visual_live else "degraded" if visual_running else "stopped",
            "Live visual sensor has a fresh delivered caption" if visual_live
            else "Visual sensor is running but has no fresh delivered caption" if visual_running
            else "Visual sensor is stopped",
            ready=visual_live,
            state="ok" if visual_live else "warn",
            action="Check screen capture, Qwen endpoint and caption freshness" if not visual_live else None,
        ))
    else:
        checks.append(_check(
            "vision", "configured" if vision_configured else "not_configured",
            "Vision profile enabled; live capture/model not verified" if vision_enabled
            else "Vision configured; screen capture is off" if vision_configured
            else "Vision is disabled",
            ready=False,
            state="warn" if vision_enabled else "off",
            action="Validate the selected Vision profile" if vision_enabled else None,
        ))

    checks.append(_check(
        "avatar", "desktop",
        "3D VRM avatar lives in the Electron desktop shell (ADR-045); "
        "the envelope emotion and avatar.audio lip-sync channel are the contract",
        ready=True,
    ))

    dry_run = bool(getattr(hostos, "dry_run", True))
    checks.append(_check(
        "hostos", "dry_run" if dry_run else "live",
        "HostOS policy-only dry-run (safe default)" if dry_run else "HostOS live executor",
        ready=True,
    ))

    if ambient_memory is not None:
        memory_state = ambient_memory.state()
        enabled = bool(memory_state.get("enabled"))
        checks.append(_check(
            "ambient_memory", "ready" if enabled else "disabled",
            "Bounded ambient evidence" if enabled else "Ambient evidence is disabled by default",
            ready=enabled,
            state="ok" if enabled else "off",
        ))
    if ambient_audio is not None:
        audio_state = ambient_audio.state()
        configured = bool(audio_state.get("configured"))
        capture = audio_state.get("capture", {})
        error = capture.get("last_error")
        running = configured and capture.get("running") is True and not error
        consumer_age_ms = capture.get("last_consumer_chunk_age_ms")
        try:
            consumer_age_ms = float(consumer_age_ms) if consumer_age_ms is not None else None
        except (TypeError, ValueError, OverflowError):
            consumer_age_ms = None
        try:
            consumer_chunks = max(0, int(capture.get("consumer_chunks") or 0))
        except (TypeError, ValueError, OverflowError):
            consumer_chunks = 0
        has_pcm = consumer_chunks > 0
        has_recent_pcm = (
            has_pcm
            and consumer_age_ms is not None
            and 0 <= consumer_age_ms <= 5000
        )
        audio_ready = running and has_recent_pcm
        audio_status = (
            "online" if audio_ready else
            "waiting_for_samples" if running and not has_pcm else
            "stale_samples" if running else
            "configured" if configured and not error else
            "stopped"
        )
        checks.append(_check(
            "ambient_audio", audio_status,
            "System-audio loopback is receiving fresh PCM; ASR acceptance is separate" if audio_ready
            else "Loopback is open but has not delivered fresh PCM" if running
            else "System-audio capture stopped while configured" if error
            else "System-audio capture is off",
            ready=audio_ready,
            state="ok" if audio_ready else "warn" if running or error else "off",
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
            state="ok" if running else "off",
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
            f"Explicitly configured helper: {name}",
            ready=status == "online",
            state="ok" if status == "online" else "warn",
        ))

    required_failures = [item for item in checks if item["required"] and not item["ready"]]
    warnings = [item for item in checks if item["state"] in {"warn", "error"}]
    overall = "blocked" if required_failures else "degraded" if warnings else "ready"
    return {
        "schema_version": 1,
        "status": overall,
        "text_mode_available": mock_mode or jawl_status in {"connected", "online"},
        "checks": checks,
        "optional_off": [item["id"] for item in checks if item["state"] == "off"],
        "recommendations": [item["action"] for item in warnings if item.get("action")][:8],
    }
