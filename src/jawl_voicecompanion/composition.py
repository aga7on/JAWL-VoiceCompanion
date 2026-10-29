"""Composition root for the local JAWL VoiceCompanion runtime.

This module constructs replaceable adapters and wires them into the existing
public web-server factories. It deliberately owns no cognition, memory, tool
policy or model loop: those remain in JAWL or in bounded worker adapters.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, NoReturn
from urllib.parse import urlsplit

from .ambient_audio import AmbientAudioASRBridge, AmbientAudioService
from .system_audio import SystemAudioLoopback
from .ambient_memory import AmbientMemoryBuffer, AmbientTriageScheduler
from .ambient_triage import OpenAICompatibleTriageProvider
from .asr import UtteranceBuffer
from .browser_adapter import BrowserAdapter
from .companion_runtime import CompanionRuntime
from .prosody_planner import ProsodyPlanner
from .gateway import TextGateway
from .history import ConversationHistory
from .hostos_tools import HostOSExecutor
from .jawl_adapter import JawlTerminalAdapter
from .jawl_web import JawlWebChatAdapter
from .llm import OpenAICompatibleChatClient
from .screen_adapter import ScreenCaptureAdapter
from .tts import Qwen3TTSHttpClient, TeraTTSHttpClient, TTSService, VoxCPMHttpClient
from .user_activity import WindowsUserActivity
from .vision import OpenAICompatibleVisionClient
from .voicemem_client import VoiceMemProcessClient
from .web import create_presentation_server, create_server, is_loopback_host
from .windows_keyboard import WindowsKeyboardAdapter
from .windows_pointer import WindowsPointerAdapter
from .windows_ui import WindowsUIAutomationAdapter


ErrorFn = Callable[[str], NoReturn]


def _voicemem_sidecar_args(args: Any) -> tuple[str, ...]:
    """Build VoiceMem CLI arguments without inheriting a profile's storage root."""
    result = [
        "--mode", args.voicemem_mode,
        "--audio-sample-rate", str(args.voicemem_audio_rate),
    ]
    memory_root = getattr(args, "voicemem_memory_root", None)
    if memory_root is not None:
        result.extend(("--memory-root", str(memory_root)))
    if args.voicemem_local_memory:
        result.append("--local-memory")
    return tuple(result)


def _parse_visual_roi(value: Any) -> tuple[float, float, float, float]:
    try:
        parts = [float(part) for part in str(value or "").replace(" ", "").split(",")]
    except (TypeError, ValueError):
        return (0.0, 0.0, 1.0, 1.0)
    if len(parts) != 4:
        return (0.0, 0.0, 1.0, 1.0)
    x, y, width, height = parts
    x = max(0.0, min(x, 1.0))
    y = max(0.0, min(y, 1.0))
    width = max(0.01, min(width, 1.0 - x))
    height = max(0.01, min(height, 1.0 - y))
    return (round(x, 4), round(y, 4), round(width, 4), round(height, 4))


def build_companion_runtime(
    args: Any,
    *,
    frontend_dir: Path,
    screen_redaction_rects: tuple[tuple[int, int, int, int], ...],
    lan_access_token: str | None,
    error: ErrorFn,
) -> CompanionRuntime:
    """Build one runtime from CLI configuration.

    The returned object is the only lifecycle owner exposed to the launcher.
    The public server factories remain unchanged so embedded callers and tests
    can continue to compose smaller configurations directly.
    """

    project_root = Path(__file__).resolve().parents[2]
    responder = None
    brain_name = "phase1_mock_brain"
    jawl_web = None
    if (args.llm_url or args.llm_model) and (args.jawl_web_url or args.jawl_port_file):
        error("--llm-url/--llm-model cannot be combined with a JAWL adapter")
    if args.jawl_web_url:
        try:
            jawl_web = JawlWebChatAdapter(
                args.jawl_web_url,
                token=os.environ.get(args.jawl_web_token_env, ""),
                timeout_seconds=args.jawl_web_timeout,
                chat_timeout_seconds=args.jawl_chat_timeout,
                native_gateway=True,
            )
        except ValueError as exc:
            error(str(exc))
        responder = jawl_web
        brain_name = "jawl_web_chat"
        if args.jawl_port_file:
            # P0: keep one persistent terminal connection to the JAWL agent
            # for chat turns; the console adapter stays for memory/journal/
            # persona endpoints through JawlChatRouter delegation.
            try:
                from .jawl_terminal import JawlChatRouter, JawlTerminalGateway
                terminal = JawlTerminalGateway(
                    args.jawl_port_file,
                    timeout_seconds=args.jawl_chat_timeout,
                )
                terminal.start()
                responder = JawlChatRouter(console=jawl_web, terminal=terminal)
                brain_name = "jawl_terminal_gateway"
            except ValueError as exc:
                print(f"[composition] terminal gateway disabled: {exc}")
    elif args.jawl_port_file:
        responder = JawlTerminalAdapter(args.jawl_port_file)
        brain_name = "jawl_terminal"
    elif args.llm_url or args.llm_model:
        if not args.llm_url or not args.llm_model:
            error("--llm-url and --llm-model must be provided together")
        responder = OpenAICompatibleChatClient(
            args.llm_url,
            args.llm_model,
            api_key=os.environ.get(args.llm_api_key_env, ""),
            timeout_seconds=args.llm_timeout,
            user_agent=args.llm_user_agent,
        )
        brain_name = "openai_compatible_chat"
    if args.jawl_hostos_control and not args.jawl_web_url:
        error("--jawl-hostos-control requires --jawl-web-url")
    if args.jawl_hostos_control and not os.environ.get(args.jawl_web_token_env, ""):
        host = urlsplit(args.jawl_web_url).hostname if args.jawl_web_url else None
        if host not in {"127.0.0.1", "localhost", "::1"}:
            error(f"--jawl-hostos-control requires a token in {args.jawl_web_token_env} for non-loopback JAWL URLs")

    gateway = TextGateway(
        responder=responder,
        brain_name=brain_name,
        jawl_web=jawl_web,
        history_store=ConversationHistory(
            args.history_file or project_root / "runtime" / "conversation.ndjson"
        ),
    )
    if getattr(args, "hostos_level", None) is not None:
        gateway.policy.set_access_level(int(args.hostos_level), actor="launcher")
    hostos_executor = None
    if args.hostos_live:
        hostos_executor = HostOSExecutor(
            policy=gateway.policy,
            sandbox_root=args.sandbox_root or project_root / "runtime" / "sandbox",
            workspace_roots=tuple(args.workspace_root),
            host_roots=tuple(args.host_root),
            dry_run=False,
            allowed_executables=frozenset(args.allowed_executable),
            ui_automation=WindowsUIAutomationAdapter(),
            pointer=WindowsPointerAdapter(require_fresh_token=True),
            keyboard=WindowsKeyboardAdapter(),
            screen_capture=ScreenCaptureAdapter(
                enabled=args.screen_enabled,
                max_width=args.screen_max_width,
                max_height=args.screen_max_height,
                max_bytes=args.screen_max_bytes,
                ocr_enabled=args.screen_ocr,
                redaction_rects=screen_redaction_rects,
            ),
        )
        hostos_executor.browser = BrowserAdapter(ui_automation=hostos_executor.ui_automation)

    vision_describer = None
    if args.vision_url or args.vision_model:
        if not args.vision_url or not args.vision_model:
            error("--vision-url and --vision-model must be provided together")
        vision_describer = OpenAICompatibleVisionClient(
            args.vision_url,
            args.vision_model,
            api_key=os.environ.get(args.vision_api_key_env, ""),
            timeout_seconds=args.vision_timeout,
        )
    if args.screen_watch:
        eg2_model = project_root / "runtime" / "models" / "embeddinggemma-2-onnx" / "onnx" / "model_q4.onnx"
        if not (args.hostos_live and args.screen_enabled and (vision_describer or eg2_model.is_file())):
            error(
                "--screen-watch requires --hostos-live, --screen-enabled, and either "
                "--vision-url/--vision-model or the EmbeddingGemma 2 ONNX model"
            )

    voicemem_args = _voicemem_sidecar_args(args)
    voice_mem = (
        VoiceMemProcessClient(
            args.voicemem_python,
            args=tuple(voicemem_args),
            timeout_seconds=args.voicemem_timeout,
        )
        if args.voicemem_python
        else None
    )
    if voice_mem is not None and args.voicemem_warmup != "none":
        try:
            voice_mem.warmup(kind=args.voicemem_warmup)
        except Exception:
            time.sleep(5)
            try:
                voice_mem.warmup(kind=args.voicemem_warmup)
            except Exception as exc:
                voice_mem.close()
                error(f"VoiceMem {args.voicemem_warmup} warmup failed: {type(exc).__name__}")

    # GigaAM (crispasr file mode) is the only ASR engine: no provider URL, no
    # second engine and no fallback lane (owner decision 2026-09-21). The
    # buffer below holds one utterance; the transcriber owns the text.
    streaming_asr = None
    if getattr(args, "streaming_asr", False):
        if not args.streaming_asr_exe or not args.streaming_asr_model:
            error("--streaming-asr requires --streaming-asr-exe and --streaming-asr-model")
        from .streaming_asr import StreamingASRBridge
        streaming_asr = StreamingASRBridge(
            args.streaming_asr_exe,
            args.streaming_asr_model,
            backend=args.streaming_asr_backend,
            step_ms=args.streaming_asr_step_ms,
        )

    gigaam_transcriber = None
    if args.streaming_asr_exe and args.streaming_asr_model:
        from .giga_final import CrispASRFileTranscriber
        gigaam_transcriber = CrispASRFileTranscriber(
            args.streaming_asr_exe,
            args.streaming_asr_model,
        )

    # The utterance buffer exists only when the canonical transcriber is
    # available; without local audio the VoiceMem streaming path stays in charge.
    asr_service = UtteranceBuffer(gigaam_transcriber) if gigaam_transcriber is not None else None

    # Doctor probes only helpers that the current composition explicitly
    # exposes. Dev-only relay/coding workers are not part of the daily runtime
    # and must not appear as failed components when they are simply not raised.
    helper_urls: dict[str, str] = {}

    proactive_feed = None
    if jawl_web is not None:
        from .proactive import ProactiveFeed
        proactive_feed = ProactiveFeed(
            jawl_web,
            history=gateway.history_store,
            state_path=project_root / "runtime" / "proactive-state.json",
        )

    if args.ambient_triage_url or args.ambient_triage_model:
        if not args.ambient_triage_url or not args.ambient_triage_model:
            error("--ambient-triage-url and --ambient-triage-model must be provided together")
        triage_provider = OpenAICompatibleTriageProvider(
            args.ambient_triage_url,
            args.ambient_triage_model,
            api_key=os.environ.get(args.ambient_triage_api_key_env, ""),
            timeout=args.ambient_triage_timeout,
        )
    else:
        triage_provider = None
    if args.ambient_triage_interval < 0:
        error("--ambient-triage-interval must be zero or positive")
    ambient_memory = AmbientMemoryBuffer(enabled=args.ambient_memory, triage_provider=triage_provider)
    ambient_scheduler = (
        AmbientTriageScheduler(ambient_memory, args.ambient_triage_interval)
        if args.ambient_triage_interval > 0 else None
    )
    if ambient_scheduler is not None:
        ambient_scheduler.start()
    from .eg2_sensory import DEFAULT_EG2_ONNX_ROOT, EmbeddingGemmaSensoryCortex, RollingMediaBuffer
    from .perception_fusion import PerceptionFusion
    perception_fusion = PerceptionFusion(media_buffer=RollingMediaBuffer(window_seconds=300.0, max_items=1800))
    if getattr(args, "jawl_log_dir", None):
        perception_fusion.prompt_snapshot_path = Path(args.jawl_log_dir).resolve().parent / "data" / "sensory" / "current-perception.json"
    from .sensory_history import SensoryHistoryStore

    history_root = (
        Path(args.jawl_log_dir).resolve().parent
        if getattr(args, "jawl_log_dir", None)
        else project_root / "runtime"
    )
    sensory_history = SensoryHistoryStore(
        history_root / "data" / "sensory" / "weekly-history.json",
        enabled=lambda: ambient_memory.enabled and not ambient_memory.paused,
    )
    perception_fusion.history_store = sensory_history
    if getattr(args, "visual_describer", "eg2") == "qwen":
        perception_fusion.include_eg2_media_in_scene = False
    try:
        if (DEFAULT_EG2_ONNX_ROOT / "onnx" / "model_q4.onnx").is_file():
            perception_fusion.eg2 = EmbeddingGemmaSensoryCortex(
                DEFAULT_EG2_ONNX_ROOT, intra_op_num_threads=4
            )
            try:
                from .eg2_describer import DetailedSensoryDescriber, Eg2VisionDescriber
                perception_fusion.describer = DetailedSensoryDescriber(perception_fusion.eg2)
                if vision_describer is None:
                    vision_describer = Eg2VisionDescriber(perception_fusion.describer)
            except Exception:  # noqa: BLE001
                perception_fusion.describer = None
    except Exception:  # noqa: BLE001 - optional sensory cortex must not block startup
        perception_fusion.eg2 = None
        perception_fusion.describer = None

    eg2_audio_describer = None
    if getattr(args, "audio_describer", "eg2") == "qwen-omni":
        audio_url = str(getattr(args, "audio_describer_url", "") or "").strip()
        audio_model = str(getattr(args, "audio_describer_model", "") or "").strip()
        if not audio_url or not audio_model:
            error("--audio-describer qwen-omni requires --audio-describer-url and --audio-describer-model")
        try:
            from .audio_understanding import AudioDescriptionService
            from .qwen_omni_audio import QwenOmniAudioDescriptionProvider

            eg2_audio_describer = AudioDescriptionService(
                QwenOmniAudioDescriptionProvider(
                    audio_url,
                    model=audio_model,
                    timeout=float(getattr(args, "ambient_triage_timeout", 30.0)),
                )
            )
        except Exception as exc:  # noqa: BLE001 - audio description remains optional
            print(f"[audio-describer] disabled: {type(exc).__name__}: {str(exc)[:160]}")
    elif perception_fusion.describer is not None:
        try:
            from .audio_understanding import AudioDescriptionService
            from .eg2_describer import Eg2AudioDescriptionProvider

            eg2_audio_describer = AudioDescriptionService(
                Eg2AudioDescriptionProvider(perception_fusion.describer)
            )
        except Exception:  # noqa: BLE001 - ambient audio still works without descriptions
            eg2_audio_describer = None

    def _describe_displays(max_displays: int = 2, audio_wav_bytes: bytes | None = None) -> dict[str, Any]:
        adapter = getattr(hostos_executor, "screen_capture", None)
        if adapter is None or not hasattr(adapter, "capture_displays"):
            return {"status": "degraded", "reason": "screen_capture_not_configured", "persisted": False}
        captures = adapter.capture_displays(max_displays=max_displays)
        images: list[bytes] = []
        for capture in captures:
            if not isinstance(capture, dict) or capture.get("status") != "verified":
                continue
            image = capture.get("image")
            if not isinstance(image, dict):
                continue
            encoded = image.get("data_base64")
            if not isinstance(encoded, str) or not encoded:
                continue
            try:
                import base64

                images.append(base64.b64decode(encoded))
            except Exception:  # noqa: BLE001
                continue
        if not images:
            return {"status": "degraded", "reason": "no_verified_display_captures", "persisted": False}
        cortex = perception_fusion.eg2_cortex() if hasattr(perception_fusion, "eg2_cortex") else perception_fusion.eg2
        if cortex is None or not hasattr(cortex, "describe_displays"):
            return {"status": "degraded", "reason": "eg2_not_configured", "persisted": False}
        describer = getattr(perception_fusion, "describer", None)
        try:
            if describer is not None and hasattr(describer, "describe_displays_detailed"):
                description = str(describer.describe_displays_detailed(images) or "").strip()[:4000]
            else:
                description = str(cortex.describe_displays(images) or "").strip()[:4000]
            if audio_wav_bytes and describer is not None and hasattr(describer, "describe_audio_detailed"):
                from .audio_understanding import safe_detailed_audio_claim

                safe_audio = safe_detailed_audio_claim(describer.describe_audio_detailed(audio_wav_bytes))
                if safe_audio["kind"] == "speech" or safe_audio["description"] == "Possible rhythmic sound; music is not independently verified.":
                    description = (description + "; Audio: " + safe_audio["description"])[:4000]
        except Exception as exc:  # noqa: BLE001
            return {"status": "degraded", "reason": str(exc)[:200], "persisted": False}
        try:
            perception_fusion.observe_displays(images, cortex=cortex, audio_wav_bytes=audio_wav_bytes)
        except Exception:  # noqa: BLE001
            pass
        return {"status": "ok", "description": description, "displays": len(images), "audio_described": bool(audio_wav_bytes), "persisted": False}

    if hostos_executor is not None:
        hostos_executor.display_describer = _describe_displays
    from .resources import ResourceGovernor
    resource_governor = ResourceGovernor()
    sensory_ingestor = None
    if getattr(args, "sensory_file", ""):
        if not args.ambient_memory:
            error("--sensory-file requires --ambient-memory")
        from .sensory_ingest import SensoryIngestor
        sensory_ingestor = SensoryIngestor(
            ambient_memory, args.sensory_file, governor=resource_governor,
            fusion=perception_fusion,
        )
        sensory_ingestor.start()
    ambient_audio = None
    if args.ambient_audio:
        if voice_mem is None:
            error("--ambient-audio requires --voicemem-python")
        yamnet_soundscape_detector = None
        try:
            from .yamnet_soundscape import YamnetSoundscapeDetector

            yamnet_soundscape_detector = YamnetSoundscapeDetector()
        except Exception as exc:  # noqa: BLE001 - ASR must remain available without optional soundscape model
            print(f"[soundscape] disabled: {type(exc).__name__}: {str(exc)[:160]}")
        ambient_bridge = AmbientAudioASRBridge(
            voice_mem,
            ambient_memory,
            final_asr=asr_service,
            audio_describer=eg2_audio_describer,
            soundscape_detector=yamnet_soundscape_detector,
            perception_fusion=perception_fusion,
        )
        ambient_capture = SystemAudioLoopback(
            ambient_bridge.consume,
            session_id="ambient-audio",
            output_device_name=getattr(args, "ambient_audio_device", "") or None,
        )
        ambient_audio = AmbientAudioService(
            ambient_bridge, capture=ambient_capture, governor=resource_governor
        )
        if getattr(args, "ambient_audio_autostart", False):
            try:
                state = ambient_audio.start()
                capture_state = state.get("capture", {}) if isinstance(state, dict) else {}
                if not capture_state.get("running"):
                    print("[ambient-audio] autostart did not reach running capture state")
            except Exception as exc:  # noqa: BLE001 - expose degraded optional sensor state
                print(f"[ambient-audio] autostart failed: {type(exc).__name__}: {str(exc)[:160]}")

    streaming_perception = None
    if (
        getattr(args, "screen_watch", False)
        and getattr(args, "visual_describer", "eg2") != "qwen"
        and perception_fusion.eg2 is not None
        and perception_fusion.describer is not None
    ):
        try:
            from .eg2_sensory import DEFAULT_EG2_ONNX_ROOT
            from .eg2_transcribe import Eg2Transcriber
            from .streaming_perception import StreamingPerception

            vocab_path = DEFAULT_EG2_ONNX_ROOT / "visual_vocab.txt"
            vocab_cache = vocab_path.with_suffix(".npy")
            if not vocab_path.is_file() or not vocab_cache.is_file():
                raise RuntimeError(
                    "visual Haku vocabulary cache is missing; run scripts/build_visual_vocab.py and warm it"
                )
            transcriber = Eg2Transcriber(perception_fusion.eg2, vocab_path=vocab_path)
            streaming_perception = StreamingPerception(
                screen_capture=getattr(hostos_executor, "screen_capture", None),
                cortex=perception_fusion.eg2,
                describer=perception_fusion.describer,
                fusion=perception_fusion,
                transcriber=transcriber,
                ambient_audio=ambient_audio,
                target_title=os.environ.get("JAWL_SCREEN_TARGET_TITLE", ""),
                interval_seconds=1.0,
                audio_window_seconds=1.0,
            )
            streaming_perception.start()
        except Exception as exc:  # noqa: BLE001 - optional high-rate lane
            print(f"[sensory-stream] disabled: {type(exc).__name__}: {exc}")

    qwen_visual_sensor = None
    if getattr(args, "visual_describer", "eg2") == "qwen":
        qwen_url = getattr(args, "visual_describer_url", None) or args.vision_url
        screen_capture = getattr(hostos_executor, "screen_capture", None)
        if not qwen_url:
            print("[visual-describer] disabled: --visual-describer qwen requires --visual-describer-url or --vision-url")
        elif not (args.hostos_live and args.screen_enabled and screen_capture is not None):
            print("[visual-describer] disabled: qwen requires --hostos-live and --screen-enabled")
        else:
            try:
                from .qwen_event_describer import QwenEventDescriber
                from .qwen_visual_sensor import QwenVisualSensor

                qwen_describer = QwenEventDescriber(
                    qwen_url,
                    model=getattr(args, "visual_describer_model", "qwen3.5-0.8b"),
                    max_age_s=float(getattr(args, "visual_describer_max_age", 6.0)),
                    timeout=float(args.vision_timeout),
                )
                qwen_visual_sensor = QwenVisualSensor(
                    screen_capture=screen_capture,
                    describer=qwen_describer,
                    fusion=perception_fusion,
                    roi=_parse_visual_roi(getattr(args, "visual_describer_roi", "0,0,1,1")),
                    target_title=os.environ.get("JAWL_SCREEN_TARGET_TITLE", ""),
                    display_index=getattr(args, "visual_describer_display_index", None),
                    active_interval_s=float(getattr(args, "visual_describer_active_interval", 1.0)),
                    static_interval_s=float(getattr(args, "visual_describer_static_interval", 4.0)),
                    periodic_s=float(getattr(args, "visual_describer_periodic", 4.0)),
                )
            except Exception as exc:  # noqa: BLE001 - optional visual lane
                print(f"[visual-describer] disabled: {type(exc).__name__}: {exc}")

    if args.tts_url:
        tts_client = {
            "tera": TeraTTSHttpClient,
            "qwen": Qwen3TTSHttpClient,
            "voxcpm": VoxCPMHttpClient,
            "omnivoice": TeraTTSHttpClient,  # ADR-045: same /health + /tts WAV contract
        }[args.tts_provider]
        tts_service = TTSService(tts_client(args.tts_url, timeout_seconds=args.tts_timeout))
        if getattr(args, "prosody_planner", False) and args.tts_provider == "tera":
            planner = ProsodyPlanner(
                args.prosody_url,
                model=args.prosody_model,
                api_key=os.environ.get("LLM_API_KEY_1", "local-loopback"),
                timeout_seconds=args.prosody_timeout,
            )
            tts_service.prosody_planner = planner
    else:
        tts_service = None

    # ADR-045: the Live2D presentation surface is removed; the 3D VRM avatar
    # lives in the Electron desktop shell (desktop/). The envelope emotion and
    # avatar.audio lip-sync channel remain the product contract.

    config_hub = None
    if args.jawl_config_dir:
        try:
            from .config_hub import ConfigHub
            env_file = Path(args.jawl_env_file) if args.jawl_env_file else Path(args.jawl_config_dir).parent / ".env"
            config_hub = ConfigHub(Path(args.jawl_config_dir), env_file=env_file)
        except Exception as exc:  # noqa: BLE001 - the hub is optional at startup
            print(f"[config-hub] disabled: {type(exc).__name__}: {exc}")

    log_dir = Path(args.jawl_log_dir) if args.jawl_log_dir else None

    server = create_server(
        args.host,
        args.port,
        frontend_dir,
        gateway,
        hostos_executor,
        vision_describer,
        screen_watch=args.screen_watch,
        screen_watch_interval=args.screen_watch_interval,
        voice_mem=voice_mem,
        tts_service=tts_service,
        jawl_event_dir=args.jawl_event_dir,
        ambient_memory=ambient_memory,
        sensory_ingestor=sensory_ingestor,
        ambient_audio=ambient_audio,
        ambient_scheduler=ambient_scheduler,
        asr_service=asr_service,
        streaming_asr=streaming_asr,
        gigaam_transcriber=gigaam_transcriber,
        helper_urls=helper_urls,
        proactive_feed=proactive_feed,
        perception_fusion=perception_fusion,
        streaming_perception=streaming_perception,
        visual_sensor=qwen_visual_sensor,
        config_hub=config_hub,
        log_dir=log_dir,
        activity_provider=(
            WindowsUserActivity(args.user_activity_idle_seconds).sample
            if args.user_activity else None
        ),
        jawl_hostos_control=args.jawl_hostos_control,
        audit_file=args.audit_file or project_root / "runtime" / "audit.ndjson",
        presence_file=project_root / "runtime" / "presence.json",
        legacy_presentation=False,
        resource_governor=resource_governor,
        lan_mode=args.lan,
        lan_access_token=lan_access_token,
        lan_auth_user=args.lan_auth_user,
        tls_cert_file=args.tls_cert,
        tls_key_file=args.tls_key,
    )
    if qwen_visual_sensor is not None:
        from .arbiter import TurnPriority

        def _qwen_attention(observation: Any, *, _server: Any = server) -> None:
            try:
                _server.attention.consume(
                    {
                        "type": "SCREEN_DELTA",
                        "priority": int(TurnPriority.SCREEN_DELTA),
                        "event_id": f"qwen:{observation.frame_id}",
                        "payload": {
                            "changed": True,
                            "summary": observation.caption,
                            "significance": 2,
                            "source": observation.source,
                            "frame_id": observation.frame_id,
                            "scene_id": observation.scene_id,
                            "captured_at": observation.observed_at,
                            "age_ms": observation.age_ms,
                            "roi": observation.roi,
                        },
                    }
                )
            except Exception:
                pass

        qwen_visual_sensor.on_observation = _qwen_attention
        qwen_visual_sensor.start()

    runtime = CompanionRuntime(server)
    try:
        presentation = create_presentation_server(
            server,
            host=args.presentation_host,
            port=args.presentation_port,
            lan_mode=args.lan,
            tls_cert_file=(args.tls_cert if not is_loopback_host(args.presentation_host) else None),
            tls_key_file=(args.tls_key if not is_loopback_host(args.presentation_host) else None),
        )
        runtime.attach_presentation(presentation)
        return runtime
    except BaseException:
        runtime.close()
        raise


__all__ = ["build_companion_runtime"]
