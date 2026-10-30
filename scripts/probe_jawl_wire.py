"""Probe the exact JAWL wire shape: json_schema envelope + thinking off."""
import json
import time
import urllib.request

system = (
    "You are the JAWL agent. Native discovery, persona, policy, Goal Protocol v2. "
    "CORRELATED COMPANION DELIVERY CONTRACT: For every correlated Companion turn, "
    "a user-facing reply MUST be delivered by exactly one call to "
    "HostTerminalMessages.send_message_to_terminal. Never finish a Companion turn "
    "with empty actions while leaving the reply only in thoughts: thoughts are "
    "internal and are not user-facing text."
)
schema = {
    "type": "object",
    "properties": {
        "actions": {"type": "array"},
        "calls": {"type": "array"},
        "observation": {"type": "string", "maxLength": 320},
        "reasoning": {"type": "string", "maxLength": 320},
        "reflection": {"type": "string", "maxLength": 320},
    },
    "additionalProperties": True,
}
body = {
    "model": "local-bonsai2",
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": "## ACTIVE COMPANION TURN\n...\nFast conversational reply mode: Return one JSON envelope with exactly one HostTerminalMessages.send_message_to_terminal action using its `text` argument.\n\nПривет! Проверка связи: ответь одной короткой фразой."},
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
print("content:", content[:600])
try:
    parsed = json.loads(content)
    print("actions:", json.dumps(parsed.get("actions"), ensure_ascii=False)[:300])
except Exception as exc:
    print("JSON parse failed:", exc)
