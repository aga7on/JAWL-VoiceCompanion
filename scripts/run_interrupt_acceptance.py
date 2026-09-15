"""Exercise two real Companion chat streams with a one-second barge-in."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import requests


BASE = "http://127.0.0.1:2367"
SESSION = "interrupt-20260906"
EVIDENCE = Path(__file__).resolve().parents[1] / "runtime" / "interrupt-acceptance-20260906.json"


def main() -> None:
    session = requests.Session()
    response = session.get(BASE + "/api/session", timeout=10)
    response.raise_for_status()
    csrf = response.json()["csrf_token"]
    headers = {
        "X-Companion-CSRF": csrf,
        "Origin": BASE,
        "Content-Type": "application/json",
    }
    results: list[dict[str, object]] = []

    def run(text: str, delay: float) -> None:
        time.sleep(delay)
        started = time.perf_counter()
        rows: list[str] = []
        try:
            stream = session.post(
                BASE + "/api/chat/stream",
                headers=headers,
                json={"text": text, "session_id": SESSION},
                stream=True,
                timeout=180,
            )
            for line in stream.iter_lines():
                if line:
                    rows.append(line.decode("utf-8", "replace"))
            result = {"status": stream.status_code, "events": rows}
        except Exception as exc:  # evidence must retain transport failures
            result = {"error": repr(exc), "events": rows}
        result.update({"text": text, "delay": delay, "elapsed_s": round(time.perf_counter() - started, 3)})
        results.append(result)

    first = threading.Thread(
        target=run,
        args=("Дай длинный подробный ответ про архитектуру памяти и не завершай быстро", 0.0),
    )
    second = threading.Thread(
        target=run,
        args=("Стоп. Ответь коротко: подтверждение прерывания", 1.0),
    )
    first.start()
    second.start()
    first.join()
    second.join()
    evidence = {
        "schema_version": 1,
        "test": "real_companion_concurrent_barge_in",
        "base_url": BASE,
        "session_id": SESSION,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": results,
        "acceptance": {
            "first_turn_cancelled": any(
                "Ответ отменён" in str(event) for item in results[:1] for event in item.get("events", [])
            ),
            "second_turn_completed": any(
                '"type": "final"' in str(event) and "подтверждено" in str(event)
                for item in results[1:] for event in item.get("events", [])
            ),
            "http_errors": [item.get("status") for item in results if item.get("status") != 200],
        },
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
