"""Standalone supervised brain holder (ADR-041 stage 2).

Raises one llama-server worker (the local brain) through RuntimeSupervisor and
holds it alive until terminated. Used by the local-brain wrapper when the JAWL
agent must find a live endpoint at its FIRST heartbeat - the in-process
`--supervise-workers` path raises the brain only with the Companion entry,
which starts after the agent. The holder's Job Object
(KILL_ON_JOB_CLOSE) guarantees no orphan workers if this process dies.

Usage:
    python -X utf8 scripts/hold_supervised_brain.py --seconds N [--port 8990]
        [--llm-exe PATH] [--model PATH] [--alias NAME]

Prints `READY` once the worker answers /health, then serves the hold window
(default: until terminated). Exits non-zero if the worker fails its budget.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec  # noqa: E402
from jawl_voicecompanion.worker_readiness import model_ready, require_free_ports  # noqa: E402
from resolve_runtime_manifest import load_runtime_manifest  # noqa: E402

REPORT = ROOT / "runtime" / "supervised-brain-holder.json"


def _manifest_defaults(manifest_path: Path | None = None) -> dict:
    manifest = load_runtime_manifest(repo_root=ROOT, manifest_path=manifest_path)
    brain = manifest.get("brain", {})
    models = manifest.get("models", {})
    ports = manifest.get("ports", {})
    return {
        "port": ports.get("brain_port", 8990),
        "llm_exe": models.get("brain_server_exe", r"G:\AI\llamacpp-prism\build-fa\bin\llama-server.exe"),
        "model": models.get("bonsai_model", ""),
        "alias": brain.get("model", "local-bonsai2"),
        "threads": brain.get("threads", 12),
        "ctx_size": brain.get("context_size", 65536),
        "max_tokens": brain.get("max_output_tokens", 2048),
        "gpu_layers": brain.get("gpu_layers", 99),
        "device": brain.get("device", "CUDA1"),
        "url": brain.get("llm_url", "http://127.0.0.1:8990/v1"),
    }


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _is_valid_api_url(value: str, port: int) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port == port
            and parsed.path.rstrip("/") == "/v1"
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def main() -> int:
    manifest_parser = argparse.ArgumentParser(add_help=False)
    manifest_parser.add_argument("--manifest", type=Path, default=None)
    manifest_args, _ = manifest_parser.parse_known_args()
    defaults = _manifest_defaults(manifest_args.manifest)
    parser = argparse.ArgumentParser(description="Hold a supervised local brain worker")
    parser.add_argument("--manifest", type=Path, default=manifest_args.manifest,
                        help="canonical manifest path; its sibling local override is merged")
    parser.add_argument("--port", type=int, default=defaults["port"])
    parser.add_argument("--llm-exe", default=defaults["llm_exe"])
    parser.add_argument("--model", default=defaults["model"])
    parser.add_argument("--alias", default=defaults["alias"])
    parser.add_argument("--threads", type=int, default=defaults["threads"])
    # 64k context (owner decision 2026-10-01): 16k was cramped for the JAWL
    # ReAct envelope (~10-12k prompt + history); the model ran out of room
    # for a well-formed tool-JSON answer.
    parser.add_argument("--ctx-size", type=int, default=defaults["ctx_size"])
    # Output cap per completion: overlong "thinking" (observed 3370-token
    # rambling that broke tool-JSON) is cut before it derails the cycle.
    # The reasoning economy is ~40 words per step anyway (ZZ_COMPANION_DELIVERY).
    parser.add_argument("--max-tokens", type=int, default=defaults["max_tokens"])
    parser.add_argument("--gpu-layers", type=int, default=defaults["gpu_layers"])
    parser.add_argument("--device", default=defaults["device"])
    parser.add_argument("--url", default=None, help="OpenAI-compatible base URL; defaults to the manifest URL")
    parser.add_argument("--seconds", type=float, default=0.0, help="0 = hold until terminated")
    parser.add_argument("--startup-timeout", type=float, default=240.0)
    args = parser.parse_args()
    api_url = args.url or defaults["url"]
    if args.url is None:
        try:
            parsed_url = urlsplit(api_url)
            if parsed_url.port != args.port:
                host = parsed_url.hostname or "127.0.0.1"
                if ":" in host:
                    host = f"[{host}]"
                api_url = urlunsplit((parsed_url.scheme, f"{host}:{args.port}", parsed_url.path,
                                      parsed_url.query, parsed_url.fragment))
        except ValueError:
            parser.error("manifest brain URL is invalid")
    if not _is_valid_api_url(api_url, args.port):
        parser.error("--url must be a loopback /v1 URL whose port matches --port")

    limits = (
        ("port", args.port, 1, 65535),
        ("threads", args.threads, 1, 128),
        ("context size", args.ctx_size, 512, 1_048_576),
        ("max tokens", args.max_tokens, 1, 65_536),
        ("GPU layers", args.gpu_layers, 0, 256),
    )
    for label, value, minimum, maximum in limits:
        if not minimum <= value <= maximum:
            parser.error(f"{label} must be between {minimum} and {maximum}")
    if args.max_tokens >= args.ctx_size:
        parser.error("max tokens must be smaller than context size")
    if args.seconds < 0 or args.startup_timeout <= 0:
        parser.error("seconds must be nonnegative and startup timeout must be positive")

    args.llm_exe = str(_repo_path(args.llm_exe))
    args.model = str(_repo_path(args.model))
    if not Path(args.llm_exe).is_file():
        parser.error("brain server executable does not exist")
    if not Path(args.model).is_file():
        parser.error("brain model file does not exist")

    def probe() -> bool:
        return model_ready(args.port, args.alias)

    require_free_ports([args.port])

    spec = WorkerSpec(
        name="brain",
        command=[args.llm_exe, "--model", args.model, "--alias", args.alias,
                 "--host", "127.0.0.1", "--port", str(args.port),
                 "--threads", str(args.threads), "--ctx-size", str(args.ctx_size),
                 "--parallel", "1", "--gpu-layers", str(args.gpu_layers), "--device", args.device,
                 "--reasoning", "off", "--no-webui"],
        probe=probe,
        startup_timeout_seconds=args.startup_timeout,
        max_restarts=1,
        order=0,
    )
    supervisor = RuntimeSupervisor([spec])
    began = time.perf_counter()
    report = supervisor.start()
    if not report.ok:
        REPORT.write_text(json.dumps({"ok": False, "workers": report.workers},
                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"FAILED: {report.workers}", flush=True)
        return 2
    print(f"READY port={args.port} pid={report.workers['brain']['pid']} "
          f"startup={time.perf_counter() - began:.1f}s", flush=True)
    try:
        if args.seconds > 0:
            deadline = time.time() + args.seconds
            while time.time() < deadline:
                time.sleep(1.0)
                if not supervisor.health().ok:
                    print("BRAIN DIED", flush=True)
                    return 3
        else:
            while True:
                time.sleep(5.0)
                if not supervisor.health().ok:
                    print("BRAIN DIED", flush=True)
                    return 3
    except KeyboardInterrupt:
        pass
    finally:
        supervisor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
