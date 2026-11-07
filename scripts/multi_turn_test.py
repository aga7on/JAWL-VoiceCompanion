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

def send_turn(query):
    headers = {
        "X-Companion-CSRF": csrf,
        "Origin": "http://127.0.0.1:2367",
        "Host": "127.0.0.1:2367",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"text": query}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:2367/api/chat", data=payload, headers=headers)
    t0 = time.perf_counter()
    with opener.open(req, timeout=120) as r:
        body = json.loads(r.read())
        elapsed = time.perf_counter() - t0
        return body, elapsed

prompts = [
    "Напомни, какая у нас сейчас цель и статус?",
    "Отлично. Готов ли ты к постоянной ежедневной работе?",
]

for p in prompts:
    print(f"\n---> User: {p}")
    body, elapsed = send_turn(p)
    print(f"<--- Companion ({elapsed:.2f}s): {body.get('text')}")
    print(f"     Emotion: {body.get('emotion')}, Avatar: {body.get('avatar')}")
