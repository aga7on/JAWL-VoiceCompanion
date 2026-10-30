"""Probe: 17k-token system prompt + native schema + thinking off."""
import json
import time
import urllib.request

# Emulate the large native discovery catalog (~17k tokens).
catalog = "\n".join(
    f"### Skill {i}: ExampleSkill{i}.operation\n"
    f"Description: performs a bounded example operation {i} with parameters "
    f"alpha, beta, gamma; risk class observe; access level observer; returns "
    "a structured result object with status and bounded data fields."
    for i in range(400)
)
system = (
    "You are the JAWL agent. " + catalog +
    "\nCORRELATED COMPANION DELIVERY CONTRACT: reply via exactly one "
    "HostTerminalMessages.send_message_to_terminal call in actions. "
    "Action items use tool_name and parameters fields."
)
action_item = {
    "type": "object",
    "properties": {
        "tool_name": {"type": "string"},
        "parameters": {"type": "object"},
    },
    "required": ["tool_name"],
}
schema = {
    "type": "object",
    "properties": {
        "actions": {"type": "array", "items": action_item},
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
        {"role": "user", "content": "## ACTIVE COMPANION TURN\nFast conversational reply mode: one send_message_to_terminal action.\n\nПривет! Проверка связи: ответь одной короткой фразой."},
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
print("prompt_tokens:", data.get("usage", {}).get("prompt_tokens"))
content = msg.get("content") or ""
print("content:", content[:600])
try:
    parsed = json.loads(content)
    print("actions:", json.dumps(parsed.get("actions"), ensure_ascii=False)[:400])
except Exception as exc:
    print("JSON parse failed:", exc)
