"""Launch pinned native console with an explicit owned HTTP admission extension."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

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
    # Native HTTP admission lives in the owned kernel source; load it by
    # confined path without importing the companion package graph.
    return load_owned_extension("_owned_jawl_http_admission", resolve_source() / "src/web/admission.py")


def load_delivery_extension():
    return load_owned_extension("_owned_jawl_delivery", ROOT / "src/jawl_voicecompanion/native_jawl_delivery.py")


def load_turn_context_extension():  # retired with ADR-049 slice 3 (native turn context)
    raise RuntimeError("native turn context is installed in the kernel")


def load_owned_extension(name, path):
    # Do not import Companion's full package graph into the native console.
    spec = importlib.util.spec_from_file_location(name, Path(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def install_companion_console_entry(app, token):
    """Send a plain browser entry through Companion's session bootstrap."""
    from aiohttp import web
    raw = os.environ.get("JAWL_COMPANION_UI_URL", "")
    parsed = urlsplit(raw)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        return

    @web.middleware
    async def entry(request, handler):
        given = request.headers.get("X-Console-Token") or request.query.get("token")
        if request.method == "GET" and request.path == "/" and token and given != token:
            raise web.HTTPFound(raw.rstrip("/") + "/app?openConsole=1")
        return await handler(request)

    app.middlewares.append(entry)


def _repair_model_json(raw: str) -> str:
    """Repair the local model's escaped key quote and /dev/null tail."""
    text = raw.replace("**/dev/null**", "")
    return re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)\\*"(\s*:)', r'"\1"\2', text)


def _escape_json_controls(raw: str) -> tuple[str, bool]:
    """Escape literal control characters inside JSON strings."""
    out: list[str] = []
    in_string = False
    escaped = False
    changed = False
    for char in raw:
        if in_string:
            if escaped:
                out.append(char)
                escaped = False
            elif char == "\\":
                out.append(char)
                escaped = True
            elif char == '"':
                out.append(char)
                in_string = False
            elif char == "\n":
                out.append("\\n")
                changed = True
            elif char == "\r":
                out.append("\\r")
                changed = True
            elif char == "\t":
                out.append("\\t")
                changed = True
            elif ord(char) < 0x20:
                out.append(f"\\u{ord(char):04x}")
                changed = True
            else:
                out.append(char)
        else:
            if char == '"':
                in_string = True
            out.append(char)
    return "".join(out), changed


def install_json_repair() -> None:
    """Repair raw control characters before the pinned ReAct JSON parser."""
    from src.l3_agent.skills import schema as skills_schema
    from src.l3_agent.react import loop as react_loop

    original = skills_schema.parse_llm_json

    def repaired(raw_answer, _depth=0):
        if not isinstance(raw_answer, str):
            return original(raw_answer, _depth)
        cleaned, changed = _escape_json_controls(raw_answer)
        cleaned = _repair_model_json(cleaned)
        changed = changed or cleaned != raw_answer
        if not changed:
            return original(raw_answer, _depth)
        parsed, error = original(cleaned, _depth)
        if parsed is not None:
            try:
                log_dir = Path(os.environ.get("JAWL_LOG_DIR", str(ROOT / "runtime/instances/daily/logs")))
                log_dir.mkdir(parents=True, exist_ok=True)
                with (log_dir / "json-repair.log").open("a", encoding="utf-8") as stream:
                    stream.write(f"{len(raw_answer)} bytes; repaired=true; parsed=true\n")
            except Exception:
                pass
            return parsed, error
        return original(raw_answer, _depth)

    skills_schema.parse_llm_json = repaired
    react_loop.parse_llm_json = repaired
    for module_name in ("src.l3_agent.swarm.loop", "src.l3_agent.subconscious.runner"):
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "parse_llm_json"):
            module.parse_llm_json = repaired


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
        install_json_repair()
        owned_brain_script = (ROOT / "scripts" / "run_owned_jawl_brain.py").resolve()
        agent.MAIN_SCRIPT = owned_brain_script
        load_owned_extension("_owned_supervisor_identity", ROOT / "src/jawl_voicecompanion/native_supervisor_identity.py").install_native_supervisor_identity(InstanceManager)
        agent._supervised_manager = lambda: InstanceManager(
            agent.ROOT_DIR, entrypoint=owned_brain_script
        )
        os.environ["JAWL_SOURCE_ROOT"] = str(source)

        extension = load_extension()
        delivery_extension = load_delivery_extension()
        delivery_extension.install_native_delivery_guard()
        original_make_app = server.make_app

        def owned_app(token=None):
            app = original_make_app(token)
            install_companion_console_entry(app, token)
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
