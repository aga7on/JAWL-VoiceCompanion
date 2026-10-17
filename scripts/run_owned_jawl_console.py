"""Launch pinned native console with an explicit owned HTTP admission extension."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (ROOT / "runtime/jawl-sources").resolve()


def resolve_source() -> Path:
    raw = os.environ.get("JAWL_SOURCE_ROOT")
    source = Path(raw).resolve() if raw else (SOURCE_ROOT / "jawl-20260906-daily-v2").resolve()
    if source == SOURCE_ROOT or not source.is_relative_to(SOURCE_ROOT) or not source.is_dir():
        raise ValueError("JAWL_SOURCE_ROOT must name a source snapshot under runtime/jawl-sources")
    return source


class RedactedConsole:
    """Bounded line filter, including split writes and native generated tokens."""
    def __init__(self, stream, secrets=()):
        self.stream, self.secrets = stream, tuple(value for value in secrets if value)
        self.pending, self.hide_next, self.dropping = "", False, False

    def write(self, text):
        size = len(text)
        for part in re.split(r"([\r\n])", text):
            if part in {"\r", "\n"}:
                if not self.dropping:
                    line = self.pending
                    for secret in self.secrets:
                        line = line.replace(secret, "<redacted>")
                    line = re.sub(r"([?&]token=)[^\s]+", r"\1<redacted>", line)
                    if self.hide_next and line.strip():
                        line, self.hide_next = "<redacted>", False
                    elif "токен доступа:" in line.lower():
                        self.hide_next = True
                    self.stream.write(line + part)
                self.pending, self.dropping = "", False
            elif not self.dropping:
                self.pending += part
                if len(self.pending) > 8192:
                    self.stream.write("<oversized console line omitted>\n")
                    self.pending, self.dropping = "", True
        return size

    def flush(self):
        self.stream.flush()  # never publish an incomplete credential-bearing line

    def __getattr__(self, key):
        return getattr(self.stream, key)


def check_isolation() -> None:
    raw_home = os.environ.get("JAWL_INSTANCE_HOME")
    if not raw_home or not Path(raw_home).is_absolute():
        raise ValueError("owned instance home is required")
    home = Path(raw_home).resolve()
    instances = (ROOT / "runtime/instances").resolve()
    if home == instances or not home.is_relative_to(instances):
        raise ValueError("instance home must stay in owned runtime/instances")
    registry = os.environ.get("JAWL_INSTANCES_ROOT")
    if not registry or not Path(registry).is_absolute() or Path(registry).resolve() != instances:
        raise ValueError("owned JAWL_INSTANCES_ROOT is required")
    for key in ("JAWL_DATA_DIR", "JAWL_CONFIG_DIR", "JAWL_LOG_DIR", "JAWL_CACHE_DIR",
                "JAWL_PROMPT_DIR", "JAWL_SANDBOX_DIR", "JAWL_ENV_FILE"):
        raw = os.environ.get(key)
        if not raw or not Path(raw).is_absolute() or not Path(raw).resolve().is_relative_to(home):
            raise ValueError(f"isolated {key} is required")


def load_extension():
    return load_owned_extension("_owned_jawl_http_admission", "native_jawl_admission.py")


def load_delivery_extension():
    return load_owned_extension("_owned_jawl_delivery", "native_jawl_delivery.py")


def load_turn_context_extension():
    return load_owned_extension("_owned_jawl_turn_context", "native_jawl_turn_context.py")


def load_owned_extension(name, filename):
    # Do not import Companion's full package graph into the native console.
    spec = importlib.util.spec_from_file_location(name, ROOT / "src/jawl_voicecompanion" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    check_isolation()
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    from verify_jawl_snapshot import verify
    source = resolve_source()
    verify(source)
    sys.path.insert(0, str(source))
    secrets = [os.environ.get("CONSOLE_TOKEN", "")]
    for index, arg in enumerate(sys.argv[1:], 1):
        if arg == "--token" and index + 1 < len(sys.argv):
            secrets.append(sys.argv[index + 1])
        elif arg.startswith("--token="):
            secrets.append(arg.split("=", 1)[1])
    streams = sys.stdout, sys.stderr
    for stream in streams:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout, sys.stderr = (RedactedConsole(stream, secrets) for stream in streams)
    try:
        from src.web import server
        from src.web import agent
        from src.instances.manager import InstanceManager
        owned_brain_script = (ROOT / "scripts" / "run_owned_jawl_brain.py").resolve()
        agent.MAIN_SCRIPT = owned_brain_script
        load_owned_extension("_owned_supervisor_identity", "native_supervisor_identity.py").install_native_supervisor_identity(InstanceManager)
        agent._supervised_manager = lambda: InstanceManager(
            agent.ROOT_DIR, entrypoint=owned_brain_script
        )
        os.environ["JAWL_SOURCE_ROOT"] = str(source)

        extension = load_extension()
        delivery_extension = load_delivery_extension()
        delivery_extension.install_native_delivery_guard()
        load_turn_context_extension().install_native_jawl_turn_context()
        original_make_app = server.make_app

        def owned_app(token=None):
            app = original_make_app(token)
            extension.install_native_admission(app, server.chatsrc.bridge)
            return app

        server.make_app = owned_app
        print("Owned native console: http-turn-admission-v1; native-delivery-guard-v1; turn-context-binding-v1 (bounded, process-local)", flush=True)
        server.main()
    finally:
        sys.stdout, sys.stderr = streams
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
