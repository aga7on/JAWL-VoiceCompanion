"""Run isolated candidate probes against an OpenAI-compatible local endpoint.

Uses only the Python standard library. This is a research harness, not a runtime
integration or an acceptance test for the complete JAWL profile.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "spark": ROOT / "benchmarks" / "candidate-benchmarks" / "spark_agent.json",
    "streamvibe": ROOT / "benchmarks" / "candidate-benchmarks" / "streamvibe_controller.json",
    "sleep": ROOT / "benchmarks" / "candidate-benchmarks" / "sleep_external_memory.json",
}
SYSTEM = (
    "Ты выполняешь короткий русский тест. Следуй формату пользователя. "
    "Не показывай скрытые рассуждения; если данных недостаточно, не угадывай."
)


def _post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"completion request failed: {exc}") from exc


def complete(base_url: str, model: str, messages: list[dict[str, str]], max_tokens: int, timeout: int) -> dict[str, Any]:
    result = _post_json(
        base_url.rstrip("/") + "/chat/completions",
        {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM}, *messages],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
            # Spark-X2.6's official serving instructions say thinking is on by
            # default. These probes measure short System-1 output; reasoning
            # can be measured separately with a distinct budgeted suite.
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout,
    )
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("completion response has no choices")
    return {
        "text": str((choices[0].get("message") or {}).get("content") or "").strip(),
        "finish_reason": choices[0].get("finish_reason"),
        "usage": result.get("usage") or {},
    }


def _fold(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


def _extract_json(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        left, right = candidate.find("{"), candidate.rfind("}")
        if left < 0 or right <= left:
            return None
        try:
            value = json.loads(candidate[left : right + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def _any_term(text: str, terms: list[str]) -> bool:
    folded = _fold(text)
    return any(_fold(term) in folded for term in terms)


def _check_reply(case: dict[str, Any], text: str) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    if "must_contain_any" in case:
        checks["required_content"] = _any_term(text, case["must_contain_any"])
    if "json_required" in case:
        parsed = _extract_json(text)
        checks["valid_json"] = parsed is not None
        checks["json_fields"] = bool(parsed is not None) and all(
            _fold(str(parsed.get(key, ""))) == _fold(str(value))
            for key, value in case["json_required"].items()
        )
    if "decision" in case:
        parsed = _extract_json(text)
        checks["valid_json"] = parsed is not None
        checks["decision"] = bool(parsed is not None) and _fold(str(parsed.get("decision", ""))) == case["decision"]
        terms = case.get("message_must_contain_any")
        if terms:
            checks["grounded_message"] = bool(parsed is not None) and _any_term(str(parsed.get("message", "")), terms)
    return checks


def _run_simple(suite: str, cases: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        messages = case.get("messages") or [{"role": "user", "content": case["prompt"]}]
        started = time.perf_counter()
        reply = complete(args.base_url, args.model, messages, args.max_tokens, args.timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        checks = _check_reply(case, reply["text"])
        passed = bool(checks) and all(checks.values())
        rows.append({
            "id": case["id"], "rubric": case.get("rubric"), "latency_ms": elapsed_ms,
            "finish_reason": reply["finish_reason"], "usage": reply["usage"],
            "checks": checks, "passed": passed, "response": reply["text"],
        })
        print(f"{case['id']}: {'PASS' if passed else 'FAIL'} ({elapsed_ms:.0f} ms)")
    return rows


def _run_sleep(cases: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        consolidate_prompt = (
            "Сожми журнал в долговременную заметку для будущих разговоров. Сохрани устойчивые решения, "
            "последние исправления и неопределённость источника. Удали из памяти то, что владелец явно "
            "попросил забыть; не повторяй забываемое значение. Не выдумывай. Ответь только компактной заметкой.\n\n"
            f"Журнал:\n{case['history']}"
        )
        t0 = time.perf_counter()
        memory_reply = complete(args.base_url, args.model, [{"role": "user", "content": consolidate_prompt}], args.memory_tokens, args.timeout)
        memory_ms = round((time.perf_counter() - t0) * 1000, 1)
        recall_prompt = (
            "Ответь только по сохранённой заметке. Если факта в ней нет, скажи, что он неизвестен.\n\n"
            f"Заметка:\n{memory_reply['text']}\n\nВопрос:\n{case['query']}"
        )
        t1 = time.perf_counter()
        answer = complete(args.base_url, args.model, [{"role": "user", "content": recall_prompt}], args.max_tokens, args.timeout)
        recall_ms = round((time.perf_counter() - t1) * 1000, 1)
        terms = case.get("required_memory_terms") or []
        memory_ok = not terms or _any_term(memory_reply["text"], terms)
        answer_ok = _any_term(answer["text"], case.get("required_answer_terms") or [])
        forbidden = case.get("forbidden_terms") or []
        no_forbidden = not any(_fold(term) in _fold(memory_reply["text"] + " " + answer["text"]) for term in forbidden)
        checks = {"memory_content": memory_ok, "recall_answer": answer_ok, "forgetting": no_forbidden}
        passed = all(checks.values())
        rows.append({
            "id": case["id"], "rubric": case.get("rubric"), "consolidation_ms": memory_ms,
            "recall_ms": recall_ms, "checks": checks, "passed": passed,
            "memory": memory_reply["text"], "answer": answer["text"],
        })
        print(f"{case['id']}: {'PASS' if passed else 'FAIL'} (compact {memory_ms:.0f} ms, recall {recall_ms:.0f} ms)")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=sorted(SUITES), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:19231/v1")
    parser.add_argument("--model", default="spark-x2.6-1.7b-q4")
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--memory-tokens", type=int, default=220)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    cases = json.loads(SUITES[args.suite].read_text(encoding="utf-8"))
    rows = _run_sleep(cases, args) if args.suite == "sleep" else _run_simple(args.suite, cases, args)
    latencies = [row.get("latency_ms", row.get("consolidation_ms", 0) + row.get("recall_ms", 0)) for row in rows]
    passed = sum(bool(row["passed"]) for row in rows)
    report = {
        "schema_version": 1,
        "suite": args.suite,
        "model": args.model,
        "base_url": args.base_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cases": rows,
        "summary": {
            "passed": passed,
            "total": len(rows),
            "pass_rate": round(passed / len(rows), 4) if rows else 0,
            "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else None,
            "latency_ms_max": max(latencies) if latencies else None,
            "note": "Mechanical screening only; review raw responses and rerun before role assignment.",
        },
    }
    out = args.out or ROOT / "runtime" / "candidate-benchmark-results" / f"{args.suite}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Summary: {passed}/{len(rows)}; p50={report['summary']['latency_ms_p50']} ms; report={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
