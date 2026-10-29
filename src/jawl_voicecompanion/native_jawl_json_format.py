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

# Fast lane: a short casual turn needs the persona and the delivery contract,
# not the full skills/browser/hostos catalogue. Capping the system prompt at
# the wire cuts the prefill that otherwise delays the first spoken sentence.
_FAST_LANE_SYSTEM_CHARS = 1800
_FAST_LANE_USER_CHARS = 400
_FAST_LANE_NOTE = (
    "\n\n[FAST LANE] Short conversational turn. Reply briefly in Russian with "
    "exactly one send_message_to_terminal action; do not use tools."
)
_PERCEPTION_RE = re.compile(
    r"\[(?:ФОН ВОСПРИЯТИЯ|ВНУТРЕННИЕ НАБЛЮДЕНИЯ)[^\]]{0,900}\]", re.S
)


def _last_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if (
            isinstance(message, dict)
            and message.get("role") == "user"
            and isinstance(message.get("content"), str)
        ):
            return message["content"]
    return ""


def _perception_block(text: str) -> str:
    match = _PERCEPTION_RE.search(str(text or ""))
    return match.group(0) if match else ""


def _fast_lane_user_content(utterance: str, original: str) -> str:
    """Replace the heavy native context with the utterance and fresh perception."""
    text = str(utterance or "").strip()[: _FAST_LANE_USER_CHARS]
    block = _perception_block(original)
    if block:
        text = f"{text}\n\n{block[:700]}"
    return f"{text}{_FAST_LANE_NOTE}"


def _fast_lane_messages(messages: list[Any]) -> list[Any] | None:
    """Return messages with a slim system prompt and user context, or None."""
    if os.environ.get("JAWL_FAST_CONVERSATION") != "1":
        return None
    delivery = sys.modules.get("_owned_jawl_delivery")
    getter = getattr(delivery, "active_companion_message", None)
    utterance = getter() if callable(getter) else ""
    if not utterance:
        utterance = _last_user_text(messages)
    turn_context = sys.modules.get("src.l3_agent.context.companion")
    if turn_context is None:
        try:
            from src.l3_agent.context import companion as turn_context
        except Exception:
            turn_context = None
    conversational = getattr(turn_context, "is_conversational_text", None)
    if not callable(conversational) or not conversational(utterance):
        return None
    last_user = None
    for index, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            last_user = index
    slimmed: list[Any] = []
    changed = False
    for index, message in enumerate(messages):
        if (
            isinstance(message, dict)
            and message.get("role") == "system"
            and isinstance(message.get("content"), str)
            and len(message["content"]) > _FAST_LANE_SYSTEM_CHARS
        ):
            head = message["content"][: _FAST_LANE_SYSTEM_CHARS]
            cut = head.rfind("\n")
            if cut > _FAST_LANE_SYSTEM_CHARS // 2:
                head = head[:cut]
            slimmed.append({**message, "content": head + _FAST_LANE_NOTE})
            changed = True
        elif (
            index == last_user
            and isinstance(message, dict)
            and isinstance(message.get("content"), str)
        ):
            content = _fast_lane_user_content(utterance, message["content"])
            if len(content) < len(message["content"]):
                slimmed.append({**message, "content": content})
                changed = True
            else:
                slimmed.append(message)
        else:
            slimmed.append(message)
    return slimmed if changed else None


def _fast_lane_reply_schema() -> dict[str, Any]:
    """Require the short-chat lane to produce a deliverable terminal reply.

    The old schema only required a nonempty ``actions`` list. Gemini could
    satisfy that with a terminal action whose ``parameters`` were empty, which
    passed generation but failed JAWL's runtime skill validation and retried
    the same turn. Fast-lane classification already excludes requests that
    need tools, so its wire contract can safely be one strict terminal action.
    """
    return {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "enum": ["HostTerminalMessages.send_message_to_terminal"],
                        },
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "minLength": 1, "maxLength": 16000}
                            },
                            "required": ["text"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["tool_name", "parameters"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["actions"],
        "additionalProperties": False,
    }


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
                         "active_goal_heading_count": len(re.findall(r"(?m)^## ACTIVE GOAL\s*$", content)),
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
    action_items = kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {}).get("properties", {}).get("actions", {}).get("items", {})
    action_branches = action_items.get("oneOf", [action_items])
    action_names = {name for branch in action_branches for name in branch.get("properties", {}).get("tool_name", {}).get("enum", [])}
    record = {"schema_version": 1, "pid": os.getpid(), "created_at": datetime.now(timezone.utc).isoformat(),
              "turn_id": turn_id, "messages": messages[:64],
              "wire": {"json_schema": kwargs.get("response_format", {}).get("type") == "json_schema",
                       "ordinary_action_enum_count": len(action_names),
                       "ordinary_allows_goal_create": "GoalSkills.create_goal" in action_names,
                       "ordinary_allows_file_read": "HostOSReader.read_file" in action_names,
                       "sdk_tools_count": len(kwargs.get("tools") or []),
                       "goal_v2_branch_count": len(kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {}).get("oneOf", [])),
                       "goal_v2_required": all(name in kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {}).get("properties", {})
                                                for name in ("v", "state", "calls")),
                       "goal_v2_call_tool_enum_count": len(
                           kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {}).get("properties", {}).get("calls", {}).get("items", {}).get("properties", {}).get("tool", {}).get("enum", [])
                       ),
                       "goal_v2_terminal_only_after_no_progress": bool(
                           len(kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {}).get("oneOf", [])) == 1
                           and kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {}).get("oneOf", [{}])[0].get("properties", {}).get("state", {}).get("enum") == ["wait", "done", "blocked"]
                       ),
                       "bounded_chat_fields": any(name in kwargs.get("response_format", {}).get("json_schema", {}).get("schema", {}).get("properties", {})
                                                  for name in ("observation", "reasoning", "reflection"))}}
    line = json.dumps(record) + "\n"
    if (path.stat().st_size if path.exists() else 0) + len(line.encode("utf-8")) > 128 * 1024:
        return
    logs.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)


def _hide_legacy_goal_lifecycle_skill_docs(messages):
    """Remove the competing legacy lifecycle API from active Goal catalogs.

    Goal-v2 requests already carry their lifecycle in the structured envelope.
    Showing update_goal/create_goal beside that protocol repeatedly pulled the
    model back into the legacy completion path, even when it was explicitly
    told to return state=done.
    """
    cleaned = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            cleaned.append(message)
            continue
        content = message["content"]
        sections = re.split(r"(?m)(^## [^\r\n]+\s*$)", content)
        for index in range(1, len(sections), 2):
            heading = sections[index].strip().casefold()
            if heading == "## skills":
                body_index = index + 1
                lines = sections[body_index].splitlines(keepends=True)
                sections[body_index] = "".join(
                    line for line in lines
                    if not re.match(r"^\s*`?GoalSkills\.[A-Za-z_]\w*\s*\(", line)
                )
        updated = dict(message)
        updated["content"] = "".join(sections)
        cleaned.append(updated)
    return cleaned


def _active_goal_call_tool_names(messages, *, include_goal_lifecycle=False):
    """Expose registered action tools while removing competing Goal lifecycle calls."""
    registry = sys.modules.get("src.l3_agent.skills.registry")
    entries = getattr(registry, "_REGISTRY", None)
    if not isinstance(entries, dict):
        return None
    names = sorted(
        name for name, entry in entries.items()
        if isinstance(name, str)
        and (include_goal_lifecycle or not name.startswith("GoalSkills."))
        and isinstance(entry, dict)
        and not entry.get("hidden", False)
    )
    if len(names) <= 512:
        return names or None
    # Large registries should expose the exact bounded catalogue the model
    # received, rather than burdening the grammar with hidden/unseen tools.
    visible = set()
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            continue
        sections = re.split(r"(?m)(^## [^\r\n]+\s*$)", content)
        for index in range(1, len(sections), 2):
            if sections[index].strip().casefold() != "## skills":
                continue
            for line in sections[index + 1].splitlines():
                match = re.match(r"^\s*`?([A-Za-z_][\w.]*)\s*\(", line)
                if match and match.group(1) in names:
                    visible.add(match.group(1))
    return sorted(visible) or None


def _companion_action_items_schema(action_item: dict[str, Any], tool_names: list[str] | None) -> dict[str, Any]:
    """Keep ordinary tools available while requiring usable terminal text."""
    terminal_name = "HostTerminalMessages.send_message_to_terminal"
    names = [name for name in (tool_names or []) if isinstance(name, str) and name]
    nonterminal_names = sorted({name for name in names if name != terminal_name})

    terminal = deepcopy(action_item) if isinstance(action_item, dict) else {"type": "object"}
    terminal_properties = deepcopy(terminal.get("properties") or {})
    terminal_properties["tool_name"] = {
        **(terminal_properties.get("tool_name") or {}),
        "type": "string",
        "enum": [terminal_name],
    }
    parameters = deepcopy(terminal_properties.get("parameters") or {})
    parameter_properties = deepcopy(parameters.get("properties") or {})
    parameter_properties["text"] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 16000,
    }
    parameters.update({
        "type": "object",
        "properties": parameter_properties,
        "required": list(dict.fromkeys([*(parameters.get("required") or []), "text"])),
        # The native skill also accepts an optional response envelope. JAWL's
        # own skill guard validates any other supplied arguments.
        "additionalProperties": True,
    })
    terminal_properties["parameters"] = parameters
    terminal["properties"] = terminal_properties
    terminal["required"] = list(dict.fromkeys([*(terminal.get("required") or []), "tool_name", "parameters"]))

    if not nonterminal_names and tool_names is not None:
        return terminal

    other = deepcopy(action_item) if isinstance(action_item, dict) else {"type": "object"}
    other_properties = deepcopy(other.get("properties") or {})
    other_properties["tool_name"] = {
        **(other_properties.get("tool_name") or {}),
        "type": "string",
        **({"enum": nonterminal_names} if nonterminal_names else {"not": {"enum": [terminal_name]}}),
    }
    other["properties"] = other_properties
    return {"oneOf": [terminal, other]}


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
        model = str(getattr(request, "model", "") or kwargs.get("model") or "").casefold()
        grammar = os.environ.get("JAWL_ENVELOPE_GRAMMAR", "auto").casefold()
        if (request.tool_transport == "json_envelope" and envelope_wrapper
                and (grammar == "off" or (grammar == "auto" and "gemini" in model))):
            # A loopback API relay is not necessarily llama.cpp. The current
            # Gemini relay loses union branches/open argument objects in JSON
            # Schema: native tools become unusable although their docs remain.
            # Plain JSON preserves the full canonical envelope/arguments;
            # JAWL's normal parser, Pydantic guards and policy still validate it.
            kwargs["response_format"] = {"type": "json_object"}
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
            note = (
                "JSON ENVELOPE TRANSPORT: return the native action envelope directly "
                "in message content. No SDK function is offered in this request. "
                "For ordinary work return {observation, reasoning, reflection, actions} "
                "with exact registered tool_name/parameters. With an ACTIVE GOAL you "
                "may use native Goal Protocol v2. Never return an empty object as a "
                "substitute for the next action or an explicit Goal state.\n\n"
            )
            messages = list(kwargs.get("messages") or [])
            if messages and messages[0].get("role") == "system":
                kwargs["messages"] = [{**messages[0], "content": note + str(messages[0].get("content") or "")}, *messages[1:]]
            else:
                kwargs["messages"] = [{"role": "system", "content": note}, *messages]
            record_owned_context_summary(kwargs)
            return kwargs
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
            properties = {name: deepcopy(native_properties[name]) for name in (
                "actions", "calls", "v", "state", "note", "summary",
                "wake_after_seconds", "ledger",
            )
                          if isinstance(native_properties.get(name), dict)
                          and (name not in {"actions", "calls"}
                               or native_properties[name].get("type") == "array")}
            # Enforce the existing concise Companion-turn prompt at the wire
            # boundary: an observed model loop filled the entire completion
            # with private reasoning, truncating JSON before any action.
            # Chat and startup are bounded; active Goals and ordinary
            # autonomous cycles retain their budget.
            guard = sys.modules.get("_owned_jawl_delivery")
            ordinary = getattr(guard, "native_companion_chat_active", None)
            companion_turn = callable(ordinary) and ordinary()
            # Startup is an uncorrelated ReAct cycle, so the companion-chat
            # flag is false there. The local 27B otherwise fills the whole
            # 2048-token completion with a single internal string, truncating
            # the envelope before any action and blocking readiness. Bound the
            # internal fields for this one startup event; active Goals and
            # ordinary autonomous cycles keep their full budget.
            metadata = getattr(request, "metadata", None)
            trace = metadata.get("trace") if isinstance(metadata, dict) else None
            event_name = str(trace.get("event_name") or "") if isinstance(trace, dict) else ""
            startup = event_name == "SYSTEM_CORE_START"
            heartbeat = event_name in {"HEARTBEAT", "HOST_OS_SANDBOX_EVENT"}
            messages = kwargs.get("messages") or []
            active_goal_context = any(
                isinstance(message, dict)
                and isinstance(message.get("content"), str)
                and re.search(r"(?m)^## ACTIVE GOAL\s*$", message["content"]) is not None
                for message in messages
            )
            # A Goal continuation may itself be scheduled by HEARTBEAT. Keep
            # the passive-perception response grammar off that request: it
            # removes Goal-v2 fields/calls and can starve the durable task.
            # A heartbeat is an autonomous native work cycle, not a sensor
            # notification. It must retain tools even before a Goal exists.
            perception_cycle = startup and not active_goal_context
            goal_action_request = active_goal_context and event_name in {
                "GOAL_OPERATOR_CONTROL", "SYSTEM_CORE_START"
            }
            # An operator-controlled Goal may carry a normal companion turn
            # correlation id. The Goal contract takes precedence for that
            # explicit event so the model cannot answer with chat/actions.
            active_goal_cycle = active_goal_context and (
                not companion_turn or goal_action_request
            )
            goal_no_progress_seen = active_goal_context and any(
                isinstance(message, dict)
                and isinstance(message.get("content"), str)
                and re.search(r"(?i)no-progress-repeat=\d+", message["content"])
                for message in messages
            )
            if companion_turn or perception_cycle:
                properties.update({name: {"type": "string", "maxLength": 320}
                                   for name in ("observation", "reasoning", "reflection")})
            if active_goal_cycle:
                # Keep active Goal output on the compact native protocol. A
                # oneOf discriminator lets action states require calls while
                # terminal/wait states remain valid without calls.
                goal_properties = {name: deepcopy(properties[name]) for name in (
                    "note", "summary", "wake_after_seconds", "ledger"
                ) if isinstance(properties.get(name), dict)}
                goal_properties["v"] = {"type": "integer", "enum": [2]}
                all_states = ["act", "continue", "wait", "done", "blocked"]
                goal_properties["state"] = {"type": "string", "enum": all_states}
                goal_properties["calls"] = {
                    "type": "array",
                    "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string", "minLength": 1},
                        "args": {"type": "object", "additionalProperties": True},
                        "action_id": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "parallel_group": {"type": "string"},
                        "resources": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["tool", "args"],
                    "additionalProperties": False,
                    },
                }
                cleaned_goal_messages = _hide_legacy_goal_lifecycle_skill_docs(
                    list(kwargs.get("messages") or [])
                )
                call_tool_names = _active_goal_call_tool_names(cleaned_goal_messages)
                if call_tool_names is not None:
                    goal_properties["calls"]["items"]["properties"]["tool"]["enum"] = call_tool_names
                def goal_branch(states, *, calls_min=None, calls_max=None, summary_required=False):
                    branch_properties = deepcopy(goal_properties)
                    branch_properties["state"] = {"type": "string", "enum": states}
                    if calls_min is not None:
                        branch_properties["calls"]["minItems"] = calls_min
                    if calls_max is not None:
                        branch_properties["calls"]["maxItems"] = calls_max
                    required = ["v", "state"]
                    if calls_min is not None:
                        required.append("calls")
                    if summary_required:
                        branch_properties["summary"] = {"type": "string", "minLength": 1}
                        required.append("summary")
                    return {
                        "type": "object",
                        "properties": branch_properties,
                        "required": required,
                        "additionalProperties": False,
                    }

                act_branch = goal_branch(["act"], calls_min=1, calls_max=1)
                continue_branch = goal_branch(["continue"], calls_max=0)
                terminal_branch = goal_branch(
                    ["wait", "done", "blocked"], calls_max=0, summary_required=True
                )
                # The same GOAL_OPERATOR_CONTROL event can span several
                # ReAct steps. Requiring an action-only envelope for that
                # entire event prevents a completed Goal from ever emitting
                # its native terminal state and pushes the model toward the
                # legacy GoalSkills.update_goal tool. Completion repair still
                # validates the ledger before accepting state=done.
                schema["oneOf"] = (
                    [terminal_branch]
                    if goal_no_progress_seen
                    else [act_branch, continue_branch, terminal_branch]
                )
                schema["required"] = ["v", "state"]
                schema["additionalProperties"] = False
                properties = goal_properties
            if perception_cycle:
                # A passive perception cycle is not a free-form reasoning
                # budget: the local 27B otherwise fills 2048 tokens with one
                # unterminated string and never reaches the action envelope.
                current_limit = kwargs.get("max_tokens")
                limit = 320
                if isinstance(current_limit, int) and not isinstance(current_limit, bool):
                    limit = min(current_limit, limit)
                kwargs["max_tokens"] = max(1, limit)
            if companion_turn and not goal_action_request:
                # A correlated turn cannot satisfy delivery with a terminal
                # action that has no text. Keep registered non-terminal tools
                # available for tool-using requests, but separate their names
                # from the strict terminal-message branch so the model cannot
                # pass an empty terminal payload through the generic schema.
                action_schema = properties.get("actions", {})
                action_item = action_schema.get("items", {"type": "object"})
                available_tools = _active_goal_call_tool_names(
                    list(kwargs.get("messages") or []), include_goal_lifecycle=True
                )
                properties["actions"] = {
                    "type": "array", "minItems": 1,
                    "items": _companion_action_items_schema(action_item, available_tools),
                }
                schema["required"] = ["actions"]
            if heartbeat and not companion_turn and not active_goal_context:
                # Without a registered Goal use ordinary native actions, not
                # a fabricated Goal-v2 completion. Keep discovery and goal
                # creation available; an empty list remains valid for idle.
                action_item = properties.get("actions", {}).get("items", {"type": "object"})
                properties = {
                    "actions": {
                        "type": "array",
                        "items": _companion_action_items_schema(
                            action_item,
                            _active_goal_call_tool_names(list(kwargs.get("messages") or []), include_goal_lifecycle=True),
                        ),
                    },
                    **{name: {"type": "string"} for name in ("observation", "reasoning", "reflection")},
                }
                schema["required"] = ["actions"]
            if startup and not companion_turn and not active_goal_context:
                # A passive startup/heartbeat either stays silent or emits one
                # short terminal comment. Expose only actions so the model
                # cannot invent a Goal-v2 envelope when no active Goal is in
                # context; free-form reasoning previously consumed the output
                # budget and caused startup readiness to fail.
                properties = {
                    "actions": {
                        "type": "array",
                        "maxItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_name": {
                                    "type": "string",
                                    "enum": ["HostTerminalMessages.send_message_to_terminal"],
                                },
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "maxLength": 300}
                                    },
                                    "required": ["text"],
                                    "additionalProperties": False,
                                },
                            },
                            "required": ["tool_name", "parameters"],
                            "additionalProperties": False,
                        },
                    },
                }
            if properties:
                schema["properties"] = properties
                schema["additionalProperties"] = not (
                    active_goal_cycle
                    or (startup and not companion_turn and not active_goal_context)
                    or (heartbeat and not companion_turn and not active_goal_context)
                )
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "jawl_action_envelope", "schema": schema},
            }
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
            # Local thinking-capable models (llama.cpp Hikari) emit an empty
            # ``content`` with all output in ``reasoning_content`` unless
            # thinking is explicitly disabled for the request. The JAWL
            # ReAct parser reads ``content`` only, so an undisabled thinking
            # mode turns every conversational turn into empty actions.
            # ``chat_template_kwargs`` is a llama.cpp extension: the OpenAI SDK
            # rejects it as a direct keyword, but forwards it inside
            # ``extra_body`` to the HTTP request. Servers that do not support
            # the flag ignore it, so remote and non-thinking providers are
            # unaffected.
            extra_body = dict(kwargs.get("extra_body") or {})
            template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
            template_kwargs.setdefault("enable_thinking", False)
            extra_body["chat_template_kwargs"] = template_kwargs
            kwargs["extra_body"] = extra_body
            # Reinforce the correlated-turn delivery obligation at the wire
            # boundary: on long native prompts the local 27B sometimes leaves
            # the reply only in the reasoning fields and returns an empty
            # actions array, which ends the turn without a user-facing
            # delivery. A final bounded system reminder keeps the contract
            # adjacent to the response and is only added for the local
            # json-envelope lane with an active companion chat.
            if companion_turn:
                messages = list(kwargs.get("messages") or [])
                reminder = (
                    "CORRELATED COMPANION TURN ACTIVE. This turn REQUIRES a "
                    "user-facing final reply AFTER the requested work. Use registered "
                    "tools first when the request needs actions. For delegated continuing "
                    "work, create a native GoalSkills.create_goal before acknowledging it. "
                    "The final actions array contains one "
                    "HostTerminalMessages.send_message_to_terminal call with "
                    "the `text` argument holding the result. Sending this message closes "
                    "the chat cycle; an acknowledgement alone does not start background work. "
                    "Do not answer only "
                    "in observation/reasoning/reflection: those are internal "
                    "and never reach the user. Do not return an empty actions "
                    "array while the turn is unanswered. "
                )
                if messages and messages[0].get("role") == "system":
                    reinforced = dict(messages[0])
                    reinforced["content"] = reminder + str(messages[0].get("content") or "")
                    kwargs["messages"] = [reinforced] + list(messages[1:])
                elif messages:
                    kwargs["messages"] = [{"role": "system", "content": reminder}] + list(messages)
                else:
                    kwargs["messages"] = [{"role": "system", "content": reminder}]
                fast_lane = _fast_lane_messages(list(kwargs.get("messages") or []))
                if fast_lane is not None:
                    kwargs["messages"] = fast_lane
                    kwargs["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "jawl_fast_lane_reply",
                            "schema": _fast_lane_reply_schema(),
                        },
                    }
            if perception_cycle and not companion_turn:
                messages = list(kwargs.get("messages") or [])
                reminder = (
                    "PASSIVE PERCEPTION CYCLE. Return one JSON object. Keep "
                    "observation/reasoning/reflection under 320 characters. "
                    "If you choose to comment, use exactly one "
                    "HostTerminalMessages.send_message_to_terminal action with "
                    "a single-line text under 300 characters. Never put raw "
                    "newlines inside JSON strings. Do not write shell commands, "
                    "/dev/null, Markdown, or any text after the JSON object. "
                )
                if messages and messages[0].get("role") == "system":
                    reinforced = dict(messages[0])
                    reinforced["content"] = reminder + str(messages[0].get("content") or "")
                    kwargs["messages"] = [reinforced] + list(messages[1:])
                elif messages:
                    kwargs["messages"] = [{"role": "system", "content": reminder}] + list(messages)
                else:
                    kwargs["messages"] = [{"role": "system", "content": reminder}]
            if active_goal_cycle:
                kwargs["messages"] = cleaned_goal_messages
                reminder = (
                    "ACTIVE DURABLE GOAL. Use only the compact Goal Protocol v2 "
                    "JSON object: v=2, state, calls, and concise operational "
                    "ledger/summary fields. For state=act, provide exactly one "
                    "valid calls item with exact native tool and args. For "
                    "continue/wait/done/blocked, do not call GoalSkills or "
                    "set_current_goal; express lifecycle state in this JSON, "
                    "with a concise summary for wait/done/blocked. Record a sparse "
                    "evidence-backed ledger. No legacy actions array, chain of "
                    "thought, Markdown, or text outside the JSON object."
                )
                if goal_no_progress_seen:
                    reminder += (
                        " A previously successful action batch repeated. Do not "
                        "issue another call; return one terminal state: done only "
                        "with reconciled evidence, otherwise wait or blocked."
                    )
                goal_messages = list(kwargs.get("messages") or [])
                if goal_messages and goal_messages[0].get("role") == "system":
                    reinforced = dict(goal_messages[0])
                    reinforced["content"] = (
                        str(reinforced.get("content") or "") + "\n\n" + reminder
                    )
                    kwargs["messages"] = [reinforced] + goal_messages[1:]
                else:
                    kwargs["messages"] = [{"role": "system", "content": reminder}] + goal_messages
        record_owned_context_summary(kwargs)
        return kwargs

    installation = NativeJsonFormatInstallation(provider_class, original, wrapped)
    provider_class._request_kwargs = wrapped
    setattr(provider_class, _INSTALL_ATTR, installation)
    return installation
