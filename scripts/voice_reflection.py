"""VoiceMem reflection job: segment-triggered conversation consolidation.

Implements the adopted pattern (docs/DUPLEX_RESEARCH_ADOPTION.md, §5): the
recent dialogue is buffered, split into closed semantic segments (time-gap
based), and each closed segment is consolidated with ONE bounded LLM call
into a summary + candidate facts/preferences. The summary is written back
into VoiceMem through its own ingest pipeline; the newest open segment is
never consolidated.

Safety: fail-soft everywhere, bounded transcript size, checkpointed by
timestamp, no canonical-memory writes (JAWL remains the canonical owner).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = REPO / "runtime" / "conversation.ndjson"
DEFAULT_STATE = REPO / "runtime" / "reflection-state.json"
DEFAULT_JOURNAL = REPO / "runtime" / "reflection-journal.ndjson"
VOICEMEM_PYTHON = r"G:\AI\VoiceMem\.venv\Scripts\python.exe"
INGEST_HELPER = REPO / "services" / "voicemem_ingest_helper.py"

PROMPT = (
    "Ты — слой рефлексии голосового компаньона. Ниже фрагмент диалога с пользователем.\n"
    "Сформируй СТРОГО JSON без пояснений:\n"
    '{"summary": "1-3 предложения: что происходило и что важно запомнить",\n'
    ' "facts": ["устойчивый факт о пользователе/проекте, до 5 пунктов"],\n'
    ' "preferences": ["предпочтение пользователя, до 5 пунктов; пусто если нет"]}\n'
    "Только то, что явно следует из диалога. Без эмодзи.\n\nДиалог:\n"
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_turns(path: Path) -> list[dict]:
    turns: list[dict] = []
    if not path.is_file():
        return turns
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_ts(item.get("created_at", ""))
            user = str(item.get("user") or "").strip()
            response = item.get("response") or {}
            answer = str(response.get("text") or "").strip() if isinstance(response, dict) else ""
            if ts is None or not user or not answer:
                continue
            if len(user) <= 2 or answer.startswith("JAWL ограничил"):
                continue
            turns.append({"ts": ts, "user": user[:800], "answer": answer[:1200]})
    turns.sort(key=lambda turn: turn["ts"])
    return turns


def segment_turns(turns: list[dict], gap_minutes: int) -> list[list[dict]]:
    segments: list[list[dict]] = []
    current: list[dict] = []
    for turn in turns:
        if current and (turn["ts"] - current[-1]["ts"]).total_seconds() > gap_minutes * 60:
            segments.append(current)
            current = []
        current.append(turn)
    if current:
        segments.append(current)
    return segments


def render_transcript(segment: list[dict], max_chars: int = 6000) -> str:
    lines = []
    for turn in segment:
        lines.append(f"Пользователь: {turn['user']}")
        lines.append(f"Компаньон: {turn['answer']}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


def llm_json(relay_url: str, model: str, prompt: str, timeout: float = 90.0) -> dict | None:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 700,
    }).encode("utf-8")
    request = urllib.request.Request(
        relay_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = str(payload["choices"][0]["message"].get("content") or "")
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"llm error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(content[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary") or "").strip()[:600]
    if not summary:
        return None

    def clean(items: object, limit: int) -> list[str]:
        values = []
        if isinstance(items, list):
            for item in items:
                text = str(item or "").strip()[:300]
                if text and text not in values:
                    values.append(text)
                if len(values) >= limit:
                    break
        return values

    return {"summary": summary, "facts": clean(data.get("facts"), 5), "preferences": clean(data.get("preferences"), 5)}


def save_to_jawl(items: list[dict], companion_url: str) -> dict:
    """Write consolidated items into canonical JAWL memory through its own API.

    Uses the same session-protected `/api/jawl/memory` route as the Memory
    tab; JAWL remains the canonical owner and validates every write.
    """
    if not items:
        return {"ok": True, "saved": 0}
    try:
        import http.cookiejar
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        origin = {"Origin": companion_url}
        session = json.loads(opener.open(urllib.request.Request(
            companion_url.rstrip("/") + "/api/session", headers=origin), timeout=15).read())
        csrf = str(session.get("csrf_token") or "")
        saved = 0
        for item in items:
            payload = {
                "operation": "remember",
                "kind": str(item.get("kind") or "fact")[:32],
                "subject": str(item.get("subject") or "AGA7ON")[:120],
                "predicate": str(item.get("predicate") or "факт")[:120],
                "value": str(item.get("value") or "")[:2000],
                "source": "reflection",
            }
            if item.get("memory_key"):
                payload["memory_key"] = str(item["memory_key"])[:200]
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", "X-Companion-CSRF": csrf, **origin}
            try:
                result = json.loads(opener.open(urllib.request.Request(
                    companion_url.rstrip("/") + "/api/jawl/memory", data=body, headers=headers),
                    timeout=120).read())
                if result.get("ok"):
                    saved += 1
            except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
                print(f"jawl write failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {"ok": saved == len(items), "saved": saved, "via": "jawl"}
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
        return {"ok": False, "saved": 0, "error": f"{type(exc).__name__}: {exc}"}


def ingest_to_voicemem(texts: list[str], memory_root: str | None, companion_url: str) -> dict:
    """Write consolidated texts into VoiceMem through the live Companion.

    The live sidecar owns the local vector store (Qdrant single-instance
    lock), so the companion route `/api/reflection/note` is the only safe
    concurrent writer. Falls back to the offline helper when the Companion is
    not running (then no live sidecar holds the lock).
    """
    if not texts:
        return {"ok": True, "ingested": 0}
    if companion_url:
        try:
            import http.cookiejar
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            origin = {"Origin": companion_url}
            session = json.loads(opener.open(urllib.request.Request(
                companion_url.rstrip("/") + "/api/session", headers=origin), timeout=15).read())
            csrf = str(session.get("csrf_token") or "")
            ok = 0
            for text in texts:
                body = json.dumps({"text": text}).encode("utf-8")
                headers = {"Content-Type": "application/json", "X-Companion-CSRF": csrf, **origin}
                result = json.loads(opener.open(urllib.request.Request(
                    companion_url.rstrip("/") + "/api/reflection/note", data=body, headers=headers),
                    timeout=120).read())
                if result.get("ok"):
                    ok += 1
            return {"ok": ok == len(texts), "ingested": ok, "via": "companion"}
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
            print(f"companion ingest failed ({type(exc).__name__}), falling back to helper", file=sys.stderr)
    payload = json.dumps({
        "texts": texts,
        "user_id": "voice_user",
        "local": True,
        "memory_root": memory_root or None,
    }).encode("utf-8")
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [VOICEMEM_PYTHON, str(INGEST_HELPER)],
            input=payload,
            capture_output=True,
            cwd=str(REPO),
            timeout=600,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    output = result.stdout.decode("utf-8", "replace").strip().splitlines()
    for line in reversed(output):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {"ok": False, "error": "helper produced no JSON", "stderr": result.stderr.decode("utf-8", "replace")[-300:]}


def main() -> int:
    parser = argparse.ArgumentParser(description="VoiceMem reflection / segment consolidation job")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--relay-url", default=os.environ.get("REFLECTION_RELAY_URL", "http://127.0.0.1:8891/v1"))
    parser.add_argument("--model", default=os.environ.get("REFLECTION_MODEL", "big-pickle"))
    parser.add_argument("--segment-gap-min", type=int, default=30)
    parser.add_argument("--close-age-min", type=int, default=10)
    parser.add_argument("--max-segments", type=int, default=3)
    parser.add_argument("--no-voicemem", action="store_true", help="journal only, skip VoiceMem ingest")
    parser.add_argument("--companion-url", default=os.environ.get("REFLECTION_COMPANION_URL", "http://127.0.0.1:2367"), help="Companion control URL for the live sidecar write path")
    parser.add_argument("--memory-root", default=None)
    args = parser.parse_args()

    turns = load_turns(args.history)
    if not turns:
        print(json.dumps({"ok": True, "reason": "no history"}))
        return 0

    state = {}
    if args.state.is_file():
        try:
            state = json.loads(args.state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    last_ts = parse_ts(str(state.get("last_ts", ""))) or datetime(1970, 1, 1, tzinfo=timezone.utc)

    segments = segment_turns(turns, args.segment_gap_min)
    close_before = now_utc().timestamp() - args.close_age_min * 60
    candidates = [
        segment for segment in segments
        if segment and segment[-1]["ts"].timestamp() <= close_before and segment[-1]["ts"] > last_ts
    ]
    candidates = candidates[: args.max_segments]

    journal_path: Path = args.journal
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal = journal_path.open("a", encoding="utf-8")

    processed = 0
    ingested = 0
    new_last = last_ts
    for segment in candidates:
        result = llm_json(args.relay_url, args.model, PROMPT + render_transcript(segment))
        if result is None:
            break  # stop on LLM failure; do not skip the checkpoint forward
        entry = {
            "ts": now_utc().isoformat(),
            "segment": [segment[0]["ts"].isoformat(), segment[-1]["ts"].isoformat()],
            "turns": len(segment),
            "model": args.model,
            "summary": result["summary"],
            "facts": result["facts"],
            "preferences": result["preferences"],
        }
        if not args.no_voicemem:
            stamp = segment[-1]["ts"].strftime("%Y%m%dT%H%M%S")
            items = [{
                "kind": "summary",
                "subject": "AGA7ON",
                "predicate": "сводка диалога",
                "value": result["summary"],
                "memory_key": "reflection-" + stamp,
            }]
            for index, fact in enumerate(result["facts"]):
                items.append({
                    "kind": "fact",
                    "subject": "AGA7ON",
                    "predicate": "факт",
                    "value": fact,
                    "memory_key": f"reflection-fact-{stamp}-{index}",
                })
            for index, pref in enumerate(result["preferences"]):
                items.append({
                    "kind": "preference",
                    "subject": "AGA7ON",
                    "predicate": "предпочтение",
                    "value": pref,
                    "memory_key": f"reflection-pref-{stamp}-{index}",
                })
            outcome = save_to_jawl(items, args.companion_url)
            entry["jawl"] = {"ok": bool(outcome.get("ok")), "saved": outcome.get("saved", 0)}
            ingested += int(outcome.get("saved", 0) or 0)
        journal.write(json.dumps(entry, ensure_ascii=False) + "\n")
        journal.flush()
        processed += 1
        new_last = max(new_last, segment[-1]["ts"])

    journal.close()
    if processed:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps({"last_ts": new_last.isoformat(), "updated_at": now_utc().isoformat()}, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "segments_total": len(segments),
        "segments_processed": processed,
        "voicemem_ingested": ingested,
        "last_ts": new_last.isoformat(),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
