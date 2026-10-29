"""Live 20-turn text series against the running companion stack.

Measures dispatch->final latency per turn, verifies every turn produces a
user-facing reply (no error envelopes), and writes a bounded report with
p50/p95 statistics. No secrets, no thoughts, only reply text and timings.
"""
from __future__ import annotations

import http.cookiejar
import json
import statistics
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:2367"
OUT = Path(__file__).resolve().parents[1] / "runtime" / "live-text-series20.json"

QUESTIONS = [
    "Привет! Как дела?",
    "Какой сегодня день недели по твоим ощущениям?",
    "Назови любое блюдо, которое тебе нравится.",
    "Что ты думаешь о дождливой погоде?",
    "Расскажи одну короткую шутку.",
    "Какой твой любимый фильм?",
    "Опиши одним словом своё текущее настроение.",
    "Что бы ты делал, если бы у тебя был выходной?",
    "Какой цвет тебе ближе: синий или зелёный?",
    "Посоветуй одну книгу одним предложением.",
    "Какой сезон года тебе нравится больше?",
    "Скажи что-нибудь приятное.",
    "Что ты чувствуешь, когда работаешь?",
    "Назови одно хобби, которое тебя интересует.",
    "Как ты относишься к чаю?",
    "Опиши идеальный вечер одним предложением.",
    "Какая музыка тебе ближе?",
    "Что для тебя значит дружба? Одно предложение.",
    "Скажи комплимент моему проекту.",
    "Подведи итог нашей беседы одной фразой.",
]


def main() -> int:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    resp = opener.open(urllib.request.Request(BASE + "/api/session"), timeout=5)
    csrf = json.loads(resp.read())["csrf_token"]
    session = [c.value for c in jar if c.name == "companion_session"][0]
    headers = {
        "Content-Type": "application/json",
        "X-Companion-CSRF": csrf,
        "X-Companion-Session": session,
        "Origin": "http://127.0.0.1:2367",
    }

    turns = []
    failures = []
    for index, question in enumerate(QUESTIONS, start=1):
        body = json.dumps({"text": question}).encode("utf-8")
        req = urllib.request.Request(BASE + "/api/chat", data=body, headers=headers)
        t0 = time.time()
        try:
            with opener.open(req, timeout=300) as r:
                data = json.loads(r.read())
            elapsed = round(time.time() - t0, 2)
            text = str(data.get("text") or "")
            ok = bool(text) and "недоступен" not in text
            entry = {
                "turn": index,
                "question": question,
                "ok": ok,
                "latency_s": elapsed,
                "reply": text[:300] if ok else "",
                "speak": bool(data.get("speak")),
                "emotion": (data.get("emotion") or {}).get("id"),
            }
            if not ok:
                failures.append({"turn": index, "reply": text[:200]})
        except Exception as exc:  # noqa: BLE001 - record and continue the series
            elapsed = round(time.time() - t0, 2)
            entry = {
                "turn": index,
                "question": question,
                "ok": False,
                "latency_s": elapsed,
                "reply": "",
                "speak": False,
                "emotion": None,
            }
            failures.append({"turn": index, "error": str(exc)[:200]})
        turns.append(entry)
        print(f"[{index:2d}/{len(QUESTIONS)}] {'OK ' if entry['ok'] else 'FAIL'} {elapsed:6.1f}s  {entry['reply'][:80]}")

    latencies = [t["latency_s"] for t in turns if t["ok"]]
    report = {
        "schema_version": 1,
        "total": len(turns),
        "ok": len(latencies),
        "failed": len(failures),
        "failures": failures[:10],
        "latency": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": round(statistics.quantiles(latencies, n=20)[18], 2) if len(latencies) >= 20 else (round(max(latencies), 2) if latencies else None),
            "min": round(min(latencies), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
            "mean": round(statistics.mean(latencies), 2) if latencies else None,
        },
        "turns": turns,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== SERIES SUMMARY ===")
    print(f"ok/total: {report['ok']}/{report['total']}")
    print(f"latency p50/p95: {report['latency']['p50']} / {report['latency']['p95']} s")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
