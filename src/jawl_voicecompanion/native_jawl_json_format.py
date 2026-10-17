"""Make local JSON-envelope requests carry a nonempty object schema.

The pinned provider's json_object format maps to an empty schema in the local
llama.cpp server. Some chat-template parsers treat that as no response format.
The JSON-envelope transport uses an object grammar instead of also offering
the same envelope as an SDK function call. The native parser, discovery and
all goal/action fields stay intact; argument validation stays in JAWL.
Remote/native-tool requests and explicit format choices retain their behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit

_INSTALL_ATTR = "__jawl_owned_json_format_installation__"
ROOT = Path(__file__).resolve().parents[2]
_DIAGNOSTIC_NAMES = (
    "BrowserNavigation.navigate", "BrowserExtraction.extract_text",
    "BrowserInteraction.fill_text", "BrowserInteraction.click", "SkillCatalog.search_skills",
    "SQLStructuredMemory.remember", "SQLStructuredMemory.revise_memory",
    "SQLStructuredMemory.list_memories", "HostTerminalMessages.send_message_to_terminal",
    "HostOSWriter.write_file", "HostOSReader.read_file",
)


def record_owned_context_summary(kwargs):
    """Opt-in structural acceptance evidence; never persist message content."""
    if os.environ.get("JAWL_ACCEPTANCE_CONTEXT_DIAGNOSTICS") != "1":
        return
    raw_home, raw_log = os.environ.get("JAWL_INSTANCE_HOME", ""), os.environ.get("JAWL_LOG_DIR", "")
    if not raw_home or not raw_log or not Path(raw_home).is_absolute() or not Path(raw_log).is_absolute():
        raise ValueError("owned context diagnostics require absolute profile paths")
    home, logs = Path(raw_home).resolve(), Path(raw_log).resolve()
    instances = (ROOT / "runtime/instances").resolve()
    if home == instances or not home.is_relative_to(instances) or not logs.is_relative_to(home):
        raise ValueError("context diagnostic paths must stay inside the owned profile")
    path = logs / "owned-context-summary.jsonl"
    if path.is_symlink():
        raise ValueError("context diagnostic file must not be a symbolic link")
    if path.exists() and path.stat().st_size >= 128 * 1024:
        return
    markers = []
    marker_file = logs / "acceptance-context-markers.json"
    if marker_file.exists():
        if marker_file.is_symlink():
            raise ValueError("acceptance marker file must not be a symbolic link")
        with marker_file.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("acceptance marker file exceeds bound")
        markers = json.loads(raw)
        if not isinstance(markers, list) or len(markers) > 8 or any(not isinstance(value, str) or not 0 < len(value) <= 128 for value in markers):
            raise ValueError("acceptance markers must be a bounded text list")
    messages = []
    for message in kwargs.get("messages", []):
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            continue
        content = message["content"]
        role = message.get("role")
        browser_match = re.search(r"(?m)^### WEB BROWSER \[ON\]\s*\n", content)
        browser = ""
        if browser_match is not None:
            browser = content[browser_match.end():]
            next_heading = re.search(r"(?m)^#{2,3} ", browser)
            if next_heading is not None:
                browser = browser[:next_heading.start()]
        messages.append({"role": role if role in {"system", "user", "assistant", "tool"} else "other",
                         "chars": len(content),
                         "acceptance_marker_counts": [content.count(value) for value in markers],
                         "native_browser_marker_counts": [browser.count(value) for value in markers],
                         "native_browser_block_present": browser_match is not None,
                         "native_browser_chars": len(browser),
                         "native_browser_viewport_error": "Error building accessibility tree:" in browser,
                         "native_browser_initial_count": browser.count("Initial"),
                         "native_browser_saved_prefix_count": browser.count("Saved:"),
                         "public_skill_name_counts": {name: content.count(name) for name in _DIAGNOSTIC_NAMES}})
    native_gateway = sys.modules.get("src.l3_agent.companion_gateway")
    accessor = getattr(native_gateway, "current_companion_turn_id", None)
    turn_id = accessor() if callable(accessor) else ""
    if not isinstance(turn_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", turn_id) is None:
        turn_id = ""
    record = {"schema_version": 1, "pid": os.getpid(), "created_at": datetime.now(timezone.utc).isoformat(),
              "turn_id": turn_id, "messages": messages[:64],
              "wire": {"json_schema": kwargs.get("response_format", {}).get("type") == "json_schema",
                       "sdk_tools_count": len(kwargs.get("tools") or []),
                       "bounded_chat_fields": any(name in kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {}).get("properties", {})
                                                  for name in ("observation", "reasoning", "reflection"))}}
    line = json.dumps(record) + "\n"
    if (path.stat().st_size if path.exists() else 0) + len(line.encode("utf-8")) > 128 * 1024:
        return
    logs.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)


@dataclass(frozen=True)
class NativeJsonFormatInstallation:
    provider_class: type
    original_kwargs: Any
    wrapped_kwargs: Any


def install_native_json_format(provider_class: type | None = None) -> NativeJsonFormatInstallation:
    if provider_class is None:
        provider_class = importlib.import_module(
            "src.l3_agent.llm.providers.openai_compatible"
        ).OpenAICompatibleProvider
    existing = vars(provider_class).get(_INSTALL_ATTR)
    if existing is not None:
        if (isinstance(existing, NativeJsonFormatInstallation)
                and provider_class._request_kwargs is existing.wrapped_kwargs):
            return existing
        raise RuntimeError("native JSON format is already differently installed")
    original = provider_class._request_kwargs

    def wrapped(provider, request):
        kwargs = original(provider, request)
        # Read the provider's effective client URL, not an environment guess.
        client = getattr(provider, "client", None)
        base_url = getattr(client, "base_url", "")
        # The native LLMClient keeps the endpoint in api_url.
        if not base_url:
            base_url = getattr(client, "api_url", "")
        try:
            parsed = urlsplit(str(base_url))
            local = parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        except ValueError:
            local = False
        response_format = kwargs.get("response_format")
        tools = kwargs.get("tools")
        wrapper = (
            tools[0].get("function") if isinstance(tools, list) and len(tools) == 1
            and isinstance(tools[0], dict) else None
        )
        envelope_wrapper = (
            isinstance(wrapper, dict) and wrapper.get("name") == "execute_skill"
            and isinstance(wrapper.get("parameters"), dict)
        )
        if (local and request.tool_transport == "json_envelope"
                and isinstance(response_format, dict)
                and response_format == {"type": "json_object"}
                and envelope_wrapper and kwargs.get("tool_choice") in (None, "auto")):
            # Reuse the native wire definitions for planned actions/calls.
            # A real response copied historical action outcomes into actions,
            # omitting tool_name; generic object syntax did not prevent it.
            # Tool names/arguments stay open and validated by native JAWL.
            schema = {"type": "object"}
            native_properties = wrapper["parameters"].get("properties", {})
            properties = {name: deepcopy(native_properties[name]) for name in ("actions", "calls")
                          if isinstance(native_properties.get(name), dict)
                          and native_properties[name].get("type") == "array"}
            # Enforce the existing concise Companion-turn prompt at the wire
            # boundary: an observed model loop filled the entire completion
            # with private reasoning, truncating JSON before any action.
            # Native active Goals and uncorrelated cycles retain their budget.
            guard = sys.modules.get("_owned_jawl_delivery")
            ordinary = getattr(guard, "native_companion_chat_active", None)
            if callable(ordinary) and ordinary():
                properties.update({name: {"type": "string", "maxLength": 320}
                                   for name in ("observation", "reasoning", "reflection")})
            if properties:
                schema["properties"] = properties
                schema["additionalProperties"] = True
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "jawl_action_envelope", "schema": schema},
            }
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
        record_owned_context_summary(kwargs)
        return kwargs

    installation = NativeJsonFormatInstallation(provider_class, original, wrapped)
    provider_class._request_kwargs = wrapped
    setattr(provider_class, _INSTALL_ATTR, installation)
    return installation
