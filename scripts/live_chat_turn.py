import urllib.request
import http.cookiejar
import json
import time
import sys

sys.stdout.reconfigure(encoding="utf-8")

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

with opener.open("http://127.0.0.1:2367/api/session") as r:
    data = json.loads(r.read())
    csrf = data["csrf_token"]

def post_chat(text):
    headers = {
        "X-Companion-CSRF": csrf,
        "Origin": "http://127.0.0.1:2367",
        "Host": "127.0.0.1:2367",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:2367/api/chat", data=payload, headers=headers)
    t0 = time.perf_counter()
    with opener.open(req, timeout=120) as r:
        body = json.loads(r.read())
        elapsed = time.perf_counter() - t0
        return body, elapsed

print("Sending real turn to Companion live gateway...")
try:
    res, elapsed = post_chat("Привет! Как ты себя чувствуешь?")
    print(f"Response received in {elapsed:.2f}s:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Error during chat turn: {e}")
