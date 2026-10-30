"""Direct vision request probe against the local brain server."""
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402

adapter = ScreenCaptureAdapter(enabled=True)
cap = adapter.observe()
img = (cap.get("image") or {}).get("data_base64", "")
print("image captured:", len(img))
body = json.dumps({
    "model": "local-bonsai2",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Опиши в двух предложениях, что на экране."},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img}},
    ]}],
    "max_tokens": 200,
    "chat_template_kwargs": {"enable_thinking": False},
}).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:8990/v1/chat/completions",
    data=body,
    headers={"Content-Type": "application/json"},
)
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=240) as r:
        data = json.loads(r.read())
    print("OK", round(time.time() - t0, 1), "s:", (data["choices"][0]["message"].get("content") or "")[:400])
except urllib.error.HTTPError as exc:  # noqa: BLE001
    body = exc.read().decode("utf-8", errors="replace")
    print("FAIL HTTP", exc.code, ":", body[:600])
except Exception as exc:  # noqa: BLE001
    print("FAIL:", str(exc)[:300])
