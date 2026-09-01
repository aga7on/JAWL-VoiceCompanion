"""Run the local browser control plane."""

from __future__ import annotations

import argparse
from pathlib import Path

from .gateway import TextGateway
from .browser_adapter import BrowserAdapter
from .jawl_adapter import JawlTerminalAdapter
from .hostos_tools import HostOSExecutor
from .screen_adapter import ScreenCaptureAdapter
from .vision import OpenAICompatibleVisionClient
from .windows_ui import WindowsUIAutomationAdapter
from .web import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="JAWL VoiceCompanion Phase 1 server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--frontend", type=Path, default=None)
    parser.add_argument(
        "--jawl-port-file",
        type=Path,
        default=None,
        help="path to JAWL's terminal.port; omit to use the deterministic mock brain",
    )
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
    parser.add_argument("--sandbox-root", type=Path, default=None)
    parser.add_argument("--workspace-root", type=Path, action="append", default=[])
    parser.add_argument("--host-root", type=Path, action="append", default=[])
    parser.add_argument("--allowed-executable", action="append", default=[])
    args = parser.parse_args()
    gateway = TextGateway()
    if args.jawl_port_file:
        gateway = TextGateway(
            responder=JawlTerminalAdapter(args.jawl_port_file),
            brain_name="jawl_terminal",
        )
    hostos_executor = None
    if args.hostos_live:
        project_root = Path(__file__).resolve().parents[2]
        hostos_executor = HostOSExecutor(
            policy=gateway.policy,
            sandbox_root=args.sandbox_root or project_root / "runtime" / "sandbox",
            workspace_roots=tuple(args.workspace_root),
            host_roots=tuple(args.host_root),
            dry_run=False,
            allowed_executables=frozenset(args.allowed_executable),
            ui_automation=WindowsUIAutomationAdapter(),
            screen_capture=ScreenCaptureAdapter(enabled=args.screen_enabled),
        )
        hostos_executor.browser = BrowserAdapter(ui_automation=hostos_executor.ui_automation)
    vision_describer = None
    if args.vision_url or args.vision_model:
        if not args.vision_url or not args.vision_model:
            parser.error("--vision-url and --vision-model must be provided together")
        import os

        vision_describer = OpenAICompatibleVisionClient(
            args.vision_url,
            args.vision_model,
            api_key=os.environ.get(args.vision_api_key_env, ""),
            timeout_seconds=args.vision_timeout,
        )
    server = create_server(
        args.host,
        args.port,
        args.frontend,
        gateway,
        hostos_executor,
        vision_describer,
    )
    print(f"JAWL VoiceCompanion listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
