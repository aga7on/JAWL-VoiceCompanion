"""Probe with the exact native ActionCall schema shape."""
import json
import time
import urllib.request

system = (
    "You are the JAWL agent (full native discovery omitted for probe). "
    "CORRELATED COMPANION DELIVERY CONTRACT: reply via exactly one "
    "HostTerminalMessages.send_message_to_terminal call in actions. "
    "Action items use tool_name and parameters fields."
)
action_item = {
    "type": "object",
    "properties": {
        "tool_name": {"type": "string"},
        "parameters": {"type": "object"},
        "action_id": {"type": "string"},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "parallel_group": {"type": "string"},
        "resources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tool_name"],
}
schema = {
    "type": "object",
    "properties": {
        "actions": {"type": "array", "items": action_item},
        "calls": {"type": "array"},
        "observation": {"type": "string", "maxLength": 320},
        "reasoning": {"type": "string", "maxLength": 320},
        "reflection": {"type": "string", "maxLength": 320},
        "protocol_version": {"type": "integer"},
        "goal_state": {"type": "string"},
        "goal_summary": {"type": "string"},
    },
    "additionalProperties": True,
}
body = {
    "model": "local-bonsai2",
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": "## ACTIVE COMPANION TURN\nFast conversational reply mode: return one JSON envelope with exactly one HostTerminalMessages.send_message_to_terminal action using its `text` argument.\n\nПривет! Проверка связи: ответь одной короткой фразой."},
    ],
    "max_tokens": 2048,
    "temperature": 0.3,
    "response_format": {
        "type": "json_schema",
        "json_schema": {"name": "jawl_action_envelope", "schema": schema},
    },
    "chat_template_kwargs": {"enable_thinking": False},
}
req = urllib.request.Request(
    "http://127.0.0.1:8990/v1/chat/completions",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
t0 = time.time()
with urllib.request.urlopen(req, timeout=240) as resp:
    data = json.loads(resp.read())
msg = data["choices"][0]["message"]
print("elapsed", round(time.time() - t0, 1))
content = msg.get("content") or ""
print("content:", content[:700])
try:
    parsed = json.loads(content)
    print("actions:", json.dumps(parsed.get("actions"), ensure_ascii=False)[:400])
except Exception as exc:
    print("JSON parse failed:", exc)
