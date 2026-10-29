"""Probe: does the brain produce a JAWL JSON envelope with thinking off?"""
import json
import sys
import time
import urllib.request

system = (
    "You are a JAWL agent. Reply strictly as JSON: "
    '{"thoughts": str, "tool_calls": [{"name": str, "arguments": dict}]}. '
    "To answer the user, call HostTerminalMessages.send_message_to_terminal "
    "with a text argument. Empty tool_calls are forbidden while the user turn "
    "is unanswered."
)
body = {
    "model": "local-bonsai2",
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": "Привет! Ответь одной короткой фразой. turn_id: turn-abc123."},
    ],
    "max_tokens": 300,
    "response_format": {"type": "json_object"},
    "chat_template_kwargs": {"enable_thinking": False},
}
req = urllib.request.Request(
    "http://127.0.0.1:8990/v1/chat/completions",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
t0 = time.time()
with urllib.request.urlopen(req, timeout=180) as resp:
    data = json.loads(resp.read())
msg = data["choices"][0]["message"]
print("elapsed", round(time.time() - t0, 1))
print("content:", repr(msg.get("content"))[:600])
print("reasoning:", repr(msg.get("reasoning_content"))[:100])
try:
    parsed = json.loads(msg.get("content") or "")
    print("JSON OK; tool_calls:", json.dumps(parsed.get("tool_calls"), ensure_ascii=False)[:300])
except Exception as exc:
    print("JSON parse failed:", exc)
