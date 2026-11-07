import json

with open("runtime/instances/daily/data/interfaces/host/terminal/history.json", "r", encoding="utf-8") as f:
    h = json.load(f)

print(f"Total messages: {len(h)}")
for i, m in enumerate(h):
    text = m.get("text", "")
    if len(text) > 300:
        print(f"Msg {i} ({m.get('sender')}): {len(text)} chars: {text[:100]}...")
