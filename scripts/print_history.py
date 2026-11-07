import json

with open("runtime/instances/daily/data/interfaces/host/terminal/history.json", "r", encoding="utf-8") as f:
    history = json.load(f)

for i, m in enumerate(history[-5:]):
    print(f"Message {i} [{m.get('sender')}]: {repr(m.get('text'))}")
