"""Run the local browser control plane."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _boot_trace(label: str) -> None:
    try:
        import time as _boot_time
        with open(os.path.join(os.environ.get("TEMP", "."), "companion-boot.log"), "a", encoding="utf-8") as _fh:
            _fh.write(f"{_boot_time.strftime('%H:%M:%S')} {label} pid={os.getpid()}\n")
    except Exception:
        pass


_boot_trace("module-start")

from .companion_runtime import CompanionRuntime
from .composition import build_companion_runtime


def _default_frontend_dir() -> Path:
    """Find source-tree or wheel-installed frontend assets.

    The single-window desktop app (desktop/app.html) is the only UI since
    ADR-046. The legacy two-window shell (frontend/index.html + avatar.html)
    was removed; only mic-processor.js remains in frontend/.
    """

    source_root = Path(__file__).resolve().parents[2] / "frontend"
    installed_root = Path(sys.prefix) / "jawl_voicecompanion" / "frontend"
    for candidate in (source_root, installed_root):
        if (candidate / "mic-processor.js").is_file():
            return candidate
    return source_root


def _parse_redaction_rects(values: list[str]) -> tuple[tuple[int, int, int, int], ...]:
    """Parse explicit transient screen redaction rectangles."""
    rects = []
    for value in values:
        parts = [part.strip() for part in str(value).split(",")]
        if len(parts) != 4:
            raise ValueError("--screen-redact-rect must be left,top,right,bottom")
        try:
            rect = tuple(int(part) for part in parts)
        except ValueError as exc:
            raise ValueError("--screen-redact-rect coordinates must be integers") from exc
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            raise ValueError("--screen-redact-rect must have positive dimensions")
        rects.append(rect)
    return tuple(rects)


def main() -> None:
    _boot_trace('main-enter')
    parser = argparse.ArgumentParser(description="JAWL VoiceCompanion Phase 1 server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2367)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="explicitly allow private/LAN binds; remote control also requires TLS and JAWL_LAN_TOKEN",
    )
    parser.add_argument(
        "--tls-cert",
        type=Path,
        default=None,
        help="PEM certificate chain for HTTPS (required with --lan and a non-loopback host)",
    )
    parser.add_argument(
        "--tls-key",
        type=Path,
        default=None,
        help="PEM private key for HTTPS (required with --lan and a non-loopback host)",
    )
    parser.add_argument(
        "--lan-auth-token-env",
        default="JAWL_LAN_TOKEN",
        help="environment variable containing the LAN Basic-auth password; never put it in argv",
    )
    parser.add_argument(
        "--lan-auth-user",
        default="tablet",
        help="HTTP Basic-auth username for LAN control (default: tablet)",
    )
    parser.add_argument(
        "--lan-public-host",
        default=None,
        help="host/IP printed in the LAN URL when --host is 0.0.0.0 or ::",
    )
    parser.add_argument(
        "--presentation-host",
        default="127.0.0.1",
        help="loopback host for the isolated avatar/OBS presentation server",
    )
    parser.add_argument(
        "--presentation-port",
        type=int,
        default=8766,
        help="port for the isolated avatar/OBS presentation server (0 chooses a free port)",
    )
    parser.add_argument("--frontend", type=Path, default=None)
    parser.add_argument(
        "--jawl-port-file",
        type=Path,
        default=None,
        help="path to JAWL's terminal.port; omit to use the deterministic mock brain",
    )
    parser.add_argument(
        "--jawl-web-url",
        default=None,
        help="local JAWL web console URL, for example http://127.0.0.1:8770",
    )
    parser.add_argument(
        "--jawl-config-dir",
        type=Path,
        default=None,
        help="JAWL profile config dir; enables the unified config hub (GET/POST /api/config-hub)",
    )
    parser.add_argument(
        "--jawl-env-file",
        type=Path,
        default=None,
        help="JAWL .env path for the config hub; defaults to the config dir's sibling .env",
    )
    parser.add_argument(
        "--jawl-log-dir",
        type=Path,
        default=None,
        help="JAWL log dir; enables GET /api/logs/agent (redacted main.log tail)",
    )
    parser.add_argument(
        "--jawl-web-token-env",
        default="JAWL_WEB_TOKEN",
        help="environment variable containing JAWL's optional console token",
    )
    parser.add_argument(
        "--jawl-hostos-control",
        action="store_true",
        help="allow the browser to apply JAWL native HostOS levels and restart its agent",
    )
    parser.add_argument("--jawl-web-timeout", type=float, default=2.0)
    parser.add_argument("--jawl-chat-timeout", type=float, default=120.0)
    parser.add_argument(
        "--llm-url",
        default=None,
        help="optional OpenAI-compatible chat endpoint; mutually exclusive with JAWL adapters",
    )
    parser.add_argument("--llm-model", default=None, help="chat model name for --llm-url")
    parser.add_argument("--llm-api-key-env", default="LLM_API_KEY")
    parser.add_argument(
        "--llm-user-agent",
        default=None,
        help="optional HTTP User-Agent for providers with client-specific routing/rate limits",
    )
    parser.add_argument("--llm-timeout", type=float, default=120.0)
    parser.add_argument(
        "--hostos-live",
        action="store_true",
        help="enable real HostOS adapters; otherwise all tool requests are dry-run",
    )
    parser.add_argument(
        "--screen-enabled",
        action="store_true",
        help="explicitly enable focused-window snapshots for screen.observe",
    )
    parser.add_argument(
        "--screen-max-width",
        type=int,
        default=960,
        help="maximum captured screen width in pixels",
    )
    parser.add_argument(
        "--screen-max-height",
        type=int,
        default=720,
        help="maximum captured screen height in pixels",
    )
    parser.add_argument(
        "--screen-max-bytes",
        type=int,
        default=1_000_000,
        help="maximum transient JPEG size for screen.observe",
    )
    parser.add_argument(
        "--screen-ocr",
        action="store_true",
        help="enable optional transient OCR grounding; pytesseract remains optional",
    )
    parser.add_argument(
        "--screen-redact-rect",
        action="append",
        default=[],
        metavar="L,T,R,B",
        help="opaque-redact a transient screen rectangle before JPEG/VLM upload; repeatable",
    )
    parser.add_argument(
        "--screen-watch",
        action="store_true",
        help="start the explicit opt-in SCREEN_DELTA watcher",
    )
    parser.add_argument(
        "--hostos-level",
        type=int,
        choices=(0, 1, 2, 3),
        default=None,
        help="set the companion HostOS access level at startup (screen capture needs 1)",
    )
    parser.add_argument(
        "--screen-watch-interval",
        type=float,
        default=10.0,
        help="seconds between SCREEN_DELTA watcher polls",
    )
    parser.add_argument(
        "--sensory-file",
        default="",
        help="tail the sensory worker NDJSON file into bounded ambient memory",
    )
    parser.add_argument(
        "--user-activity",
        action="store_true",
        help="use low-privacy Windows idle/focus signals to suppress proactive interruptions",
    )
    parser.add_argument(
        "--user-activity-idle-seconds",
        type=float,
        default=60.0,
        help="seconds without Windows input before the user is considered idle",
    )
    parser.add_argument(
        "--jawl-event-dir",
        type=Path,
        default=None,
        help="explicit JAWL .jawl_events directory for proactive screen intents",
    )
    parser.add_argument(
        "--vision-url",
        default=None,
        help="OpenAI-compatible vision endpoint; requires --vision-model",
    )
    parser.add_argument(
        "--vision-model",
        default=None,
        help="vision model name for --vision-url",
    )
    parser.add_argument(
        "--vision-api-key-env",
        default="VISION_API_KEY",
        help="environment variable containing an optional vision API key",
    )
    parser.add_argument(
        "--vision-timeout",
        type=float,
        default=30.0,
        help="vision request timeout in seconds",
    )
    parser.add_argument(
        "--visual-describer",
        choices=("eg2", "qwen"),
        default="eg2",
        help="select the continuous visual describer lane (eg2 keeps embeddings/memory; qwen adds change-triggered captions)",
    )
    parser.add_argument(
        "--visual-describer-url",
        default=None,
        help="OpenAI-compatible Qwen endpoint for --visual-describer qwen (defaults to --vision-url)",
    )
    parser.add_argument(
        "--visual-describer-model",
        default="qwen3.5-0.8b",
        help="model name for --visual-describer qwen",
    )
    parser.add_argument(
        "--visual-describer-roi",
        default="0,0,1,1",
        metavar="X,Y,W,H",
        help="normalized screen ROI for Qwen captions",
    )
    parser.add_argument(
        "--visual-describer-display-index",
        type=int,
        choices=(0, 1, 2, 3),
        default=None,
        help="capture a physical display by index instead of the focused/target window",
    )
    parser.add_argument(
        "--visual-describer-active-interval",
        type=float,
        default=1.0,
        help="minimum seconds between Qwen requests on active video",
    )
    parser.add_argument(
        "--visual-describer-static-interval",
        type=float,
        default=4.0,
        help="minimum seconds between Qwen requests on static content",
    )
    parser.add_argument(
        "--visual-describer-periodic",
        type=float,
        default=4.0,
        help="periodic Qwen refresh even without visible change",
    )
    parser.add_argument(
        "--visual-describer-max-age",
        type=float,
        default=6.0,
        help="Qwen observation age after which the result is stale",
    )
    parser.add_argument(
        "--audio-describer",
        choices=("eg2", "qwen-omni"),
        default="eg2",
        help="Optional soundscape description backend; ASR remains independent",
    )
    parser.add_argument(
        "--audio-describer-url",
        default="",
        help="OpenAI-compatible /v1 endpoint for --audio-describer qwen-omni",
    )
    parser.add_argument(
        "--audio-describer-model",
        default="local-qwen3-omni",
        help="Model alias for --audio-describer qwen-omni",
    )
    parser.add_argument(
        "--voice-delivery-cues",
        action="store_true",
        help="Opt in to experimental CPU pitch/level measurements from direct microphone turns",
    )
    parser.add_argument(
        "--voicemem-python",
        type=Path,
        default=None,
        help="Python executable for the optional VoiceMem sidecar",
    )
    parser.add_argument(
        "--voicemem-timeout",
        type=float,
        default=30.0,
        help="VoiceMem sidecar request timeout in seconds",
    )
    parser.add_argument("--voicemem-mode", default="normal")
    parser.add_argument("--voicemem-audio-rate", type=int, default=16000)
    parser.add_argument(
        "--voicemem-local-memory",
        action="store_true",
        help="use VoiceMem local E5 memory components without an LLM request",
    )
    parser.add_argument(
        "--voicemem-memory-root",
        type=Path,
        default=None,
        help="explicit VoiceMem sensory cache directory (standalone default remains VoiceMem-managed)",
    )
    parser.add_argument(
        "--voicemem-warmup",
        choices=("none", "text", "audio"),
        default="none",
        help="preload VoiceMem models before serving (audio may take longer)",
    )
    parser.add_argument(
        "--streaming-asr",
        action="store_true",
        help="enable the streaming ASR lane (CrispASR) for sub-second drafts and adaptive endpointing",
    )
    parser.add_argument("--streaming-asr-exe", default="", help="path to the crispasr executable")
    parser.add_argument("--streaming-asr-model", default="", help="path to the streaming ASR GGUF model")
    parser.add_argument("--streaming-asr-backend", default="gigaam", help="CrispASR backend name")
    parser.add_argument("--streaming-asr-step-ms", type=int, default=500, help="streaming step between partials")
    parser.add_argument(
        "--ambient-memory",
        action="store_true",
        help="enable bounded ambient evidence; capture remains stopped until enabled in the browser",
    )
    parser.add_argument(
        "--ambient-audio",
        action="store_true",
        help="configure explicit Windows system-audio loopback controls (does not start capture)",
    )
    parser.add_argument(
        "--ambient-audio-autostart",
        action="store_true",
        help="start system-audio loopback with the companion (requires --ambient-audio)",
    )
    parser.add_argument(
        "--ambient-audio-device",
        default="",
        help="exact Windows output device name for loopback; defaults to the WASAPI default output",
    )
    parser.add_argument(
        "--ambient-triage-url",
        default=None,
        help="optional OpenAI-compatible delayed ambient-triage endpoint",
    )
    parser.add_argument(
        "--ambient-triage-model",
        default=None,
        help="model name for --ambient-triage-url, for example Bonsai-1.7B",
    )
    parser.add_argument("--ambient-triage-api-key-env", default="AMBIENT_TRIAGE_API_KEY")
    parser.add_argument("--ambient-triage-timeout", type=float, default=120.0)
    parser.add_argument(
        "--ambient-triage-interval",
        type=float,
        default=0.0,
        help="opt-in background triage interval in seconds; zero disables the worker",
    )
    parser.add_argument(
        "--tts-url",
        default=None,
        help="local TTS REST base URL, for example http://127.0.0.1:9889",
    )
    parser.add_argument(
        "--tts-provider",
        choices=("tera", "qwen", "voxcpm", "omnivoice"),
        default="tera",
        help="explicit worker contract behind --tts-url (default: tera)",
    )
    parser.add_argument("--tts-timeout", type=float, default=120.0)
    parser.add_argument(
        "--prosody-planner",
        action="store_true",
        help="annotate TTS sentences with per-sentence emotion envelopes via the local LLM",
    )
    parser.add_argument(
        "--prosody-url",
        default=os.environ.get("LLM_API_URL", "http://127.0.0.1:11434/v1"),
        help="OpenAI-compatible base URL for the prosody planner",
    )
    parser.add_argument(
        "--prosody-model",
        default="qwen3.8-27b-abliterated:latest",
        help="planner model name on the prosody provider",
    )
    parser.add_argument("--prosody-timeout", type=float, default=6.0)
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=None,
        help="metadata-only HostOS audit JSONL path (default: runtime/audit.ndjson)",
    )
    parser.add_argument(
        "--history-file",
        type=Path,
        default=None,
        help="conversation history JSONL path (default: runtime/conversation.ndjson)",
    )
    parser.add_argument("--sandbox-root", type=Path, default=None)
    parser.add_argument("--workspace-root", type=Path, action="append", default=[])
    parser.add_argument("--host-root", type=Path, action="append", default=[])
    parser.add_argument("--allowed-executable", action="append", default=[])
    parser.add_argument(
        "--supervise-workers",
        action="store_true",
        help=(
            "ADR-041 stage 2: start the configured local workers (brain LLM, TTS) "
            "through the product RuntimeSupervisor before serving and stop them on "
            "exit; a worker that exhausts its restart budget fails startup"
        ),
    )
    parser.add_argument(
        "--supervised-llm-command",
        default=None,
        help="executable for the supervised local brain worker",
    )
    parser.add_argument(
        "--supervised-llm-model",
        default=None,
        help="GGUF model for the supervised local brain worker",
    )
    parser.add_argument(
        "--supervised-llm-port",
        type=int,
        default=None,
        help="loopback port for the supervised local brain worker",
    )
    parser.add_argument(
        "--supervised-tts-command",
        default=None,
        help="executable for the supervised TTS worker",
    )
    parser.add_argument(
        "--supervised-tts-release",
        default=None,
        help="TeraTTS release directory for the supervised TTS worker",
    )
    parser.add_argument(
        "--supervised-tts-port",
        type=int,
        default=None,
        help="loopback port for the supervised TTS worker",
    )
    args = parser.parse_args()
    if args.ambient_audio_autostart and not args.ambient_audio:
        parser.error("--ambient-audio-autostart requires --ambient-audio")
    if args.lan_public_host and not args.lan:
        parser.error("--lan-public-host requires --lan")
    lan_access_token = os.environ.get(args.lan_auth_token_env, "") if args.lan else None
    if args.lan and len(lan_access_token or "") < 16:
        parser.error(
            f"--lan requires {args.lan_auth_token_env} with at least 16 characters; keep it in the environment"
        )
    try:
        screen_redaction_rects = _parse_redaction_rects(args.screen_redact_rect)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        supervisor_runtime = _build_worker_supervisor(args) if args.supervise_workers else None
    except ValueError as exc:
        parser.error(str(exc))
    runtime = build_companion_runtime(
        args,
        frontend_dir=args.frontend or _default_frontend_dir(),
        screen_redaction_rects=screen_redaction_rects,
        lan_access_token=lan_access_token,
        error=parser.error,
    )
    # ADR-041 stage 2: when asked, this process also owns the local workers.
    # They start before the server accepts traffic and stop when it exits.
    if supervisor_runtime is not None:
        report = supervisor_runtime.start()
        if not report.ok:
            runtime.close()
            print("supervised workers failed to become healthy:", file=sys.stderr)
            for name, summary in report.workers.items():
                print(f"  {name}: {summary}", file=sys.stderr)
            raise SystemExit(2)
        print("supervised workers healthy:")
        for name, summary in report.workers.items():
            print(f"  {name}: pid={summary['pid']}")
    try:
        server = runtime.control
        display_host = args.lan_public_host or args.host
        if display_host in {"0.0.0.0", "::"}:
            display_host = "<LAN-IP>"
        host_part = f"[{display_host}]" if ":" in display_host and not display_host.startswith("[") else display_host
        print(f"JAWL VoiceCompanion control: {server.url_scheme}://{host_part}:{server.server_port}")
        print(f"JAWL VoiceCompanion avatar/OBS: {server.presentation_url}")
        _boot_trace('serving')
        runtime.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        if supervisor_runtime is not None:
            supervisor_runtime.stop()
            print("supervised workers stopped")


def _build_worker_supervisor(args) -> "RuntimeSupervisor":  # noqa: ANN001
    """Specs for the local workers this process should own (stage 2 slice).

    Explicit CLI arguments override the validated canonical + local manifest.
    Missing workers or occupied ports fail before any model process starts;
    asking for a supervised stack must not silently serve a degraded mock.
    """
    from .runtime_manifest import load_runtime_manifest
    from .supervisor import RuntimeSupervisor, WorkerSpec
    from .worker_readiness import model_ready, require_free_ports

    repo = Path(__file__).resolve().parents[2]
    manifest = load_runtime_manifest(repo)
    ports, models, brain = (manifest[key] for key in ("ports", "models", "brain"))

    def configured_path(argument: str, key: str) -> Path:
        value = getattr(args, argument, None)
        value = value if value is not None else models.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"supervised worker setting models.{key} is missing")
        result = Path(value)
        return result if result.is_absolute() else repo / result

    llm_exe = configured_path("supervised_llm_command", "brain_server_exe")
    llm_model = configured_path("supervised_llm_model", "bonsai_model")
    tts_exe = configured_path("supervised_tts_command", "tera_python")
    tts_release = configured_path("supervised_tts_release", "tera_release")
    for name, path in (("brain executable", llm_exe), ("brain model", llm_model), ("TTS executable", tts_exe)):
        if not path.is_file():
            raise ValueError(f"supervised {name} is missing; configure runtime.manifest.local.json")
    if not tts_release.is_dir():
        raise ValueError("supervised TTS release is missing; configure runtime.manifest.local.json")
    llm_port = args.supervised_llm_port if args.supervised_llm_port is not None else ports["brain_port"]
    tts_port = args.supervised_tts_port if args.supervised_tts_port is not None else ports["tera_tts"]
    require_free_ports([llm_port, tts_port])
    return RuntimeSupervisor([
        WorkerSpec(
            name="brain",
            command=[str(llm_exe), "--model", str(llm_model),
                     "--alias", brain["model"], "--host", "127.0.0.1", "--port", str(llm_port),
                     "--threads", str(brain["threads"]), "--ctx-size", str(brain["context_size"]),
                     "--parallel", "1", "--gpu-layers", str(brain["gpu_layers"]),
                     "--device", brain["device"], "--reasoning", "off", "--no-webui"],
            cwd=str(repo),
            probe=lambda: model_ready(llm_port, brain["model"]),
            startup_timeout_seconds=240.0,
            max_restarts=1,
            order=0,
        ),
        WorkerSpec(
            name="tts",
            command=[str(tts_exe), str(repo / "scripts" / "teratts_server.py"),
                     "--release-dir", str(tts_release), "--voice", "ru_f1",
                     "--model", "distilled", "--threads", "24",
                     "--host", "127.0.0.1", "--port", str(tts_port)],
            cwd=str(repo),
            probe=lambda: model_ready(tts_port),
            startup_timeout_seconds=240.0,
            max_restarts=1,
            order=1,
        ),
    ])


if __name__ == "__main__":
    main()
