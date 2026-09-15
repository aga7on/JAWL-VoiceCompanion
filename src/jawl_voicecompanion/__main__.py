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
    """Find source-tree or wheel-installed frontend assets."""

    source_root = Path(__file__).resolve().parents[2] / "frontend"
    installed_root = Path(sys.prefix) / "jawl_voicecompanion" / "frontend"
    for candidate in (source_root, installed_root):
        if (candidate / "index.html").is_file() and (candidate / "avatar.html").is_file():
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
        "--voicemem-warmup",
        choices=("none", "text", "audio"),
        default="none",
        help="preload VoiceMem models before serving (audio may take longer)",
    )
    parser.add_argument(
        "--asr-url",
        default=None,
        help="optional OpenAI-compatible final-utterance ASR endpoint; requires --asr-model",
    )
    parser.add_argument(
        "--asr-model",
        default=None,
        help="ASR model name for --asr-url, for example Qwen3-ASR-0.6B",
    )
    parser.add_argument("--asr-api-key-env", default="ASR_API_KEY")
    parser.add_argument("--asr-timeout", type=float, default=30.0)
    parser.add_argument("--asr-max-utterance-bytes", type=int, default=4 * 1024 * 1024)
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
        choices=("tera", "qwen", "voxcpm"),
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
    parser.add_argument("--live2d-assets", type=Path, default=None)
    parser.add_argument("--live2d-model", default="model3.json")
    parser.add_argument("--live2d-runtime", default="live2d-runtime.js")
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
    args = parser.parse_args()
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
    runtime = build_companion_runtime(
        args,
        frontend_dir=args.frontend or _default_frontend_dir(),
        screen_redaction_rects=screen_redaction_rects,
        lan_access_token=lan_access_token,
        error=parser.error,
    )
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


if __name__ == "__main__":
    main()
