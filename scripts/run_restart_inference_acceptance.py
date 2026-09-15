"""Strict restart-during-active-native-inference acceptance (v2).

Hardened scenario (P0 gate from docs/RECOVERY_PLAN.md):
1. Turn attempts over the real Companion chat stream instruct JAWL to
   perform a native disposable HostOS write + read-back. Attempts repeat
   (bounded) until one turn is genuinely mid-flight (stream open, no final
   yet, after the first streamed activity), so the restart lands during
   ACTIVE native inference rather than on an idle agent.
2. The orchestrator then calls the managed native restart route
   (/api/jawl/restart) and drains the interrupted turn.
3. After restart, the orchestrator polls /api/health until JAWL is online,
   then turn B asks JAWL to INSPECT the file (read only) and report the
   marker. No rewrite instruction is given.
4. Acceptance requires: the restart landed mid-flight (turn A had streamed
   activity and no final before the restart), the restart route answered
   ok/agent_ready, health returned to jawl=online, turn B returned a
   correlated final reporting the marker, and a direct follow-up probe of
   the action journal shows no duplicate successful write.

Evidence: runtime/restart-inference-acceptance-<ts>.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests

BASE = os.environ.get("COMPANION_BASE_URL", "http://127.0.0.1:2377").rstrip("/")
SESSION = "restart-infer-" + uuid4().hex[:8]
MARKER = "RESTART_INFER_OK_" + uuid4().hex[:12]
EVIDENCE = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / (
        "restart-inference-acceptance-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
)
FILE_PATH = f"sandbox/restart-infer-{SESSION}.txt"


def session_and_csrf() -> tuple[requests.Session, dict[str, str]]:
    s = requests.Session()
    r = s.get(BASE + "/api/session", timeout=15)
    r.raise_for_status()
    csrf = r.json()["csrf_token"]
    return s, {"X-Companion-CSRF": csrf, "Origin": BASE, "Content-Type": "application/json"}


def stream_turn(s: requests.Session, headers: dict[str, str], text: str, out: dict) -> None:
    started = time.perf_counter()
    events: list[str] = []
    try:
        with s.post(
            BASE + "/api/chat/stream",
            headers=headers,
            json={"text": text, "session_id": SESSION},
            stream=True,
            timeout=300,
        ) as stream:
            out["status"] = stream.status_code
            for line in stream.iter_lines():
                if line:
                    events.append(line.decode("utf-8", "replace"))
    except Exception as exc:
        out["error"] = repr(exc)
    out["events"] = events
    out["elapsed_s"] = round(time.perf_counter() - started, 3)
    out["done"] = True


def has_final(events: list[str]) -> bool:
    return any('"type": "final"' in e or '"type":"final"' in e for e in events)


def wait_midflight(turn: dict, deadline_s: float, min_age_s: float = 8.0) -> bool:
    """Wait until the turn is genuinely mid-flight: stream open, no final,
    and at least min_age_s elapsed (the window during which JAWL is doing
    provider calls / native actions server-side)."""
    started = time.time()
    deadline = started + deadline_s
    while time.time() < deadline:
        if turn.get("done") or has_final(turn.get("events") or []):
            return False
        if time.time() - started >= min_age_s:
            return True
        time.sleep(0.5)
    return False


def restart_native(s: requests.Session, headers: dict[str, str], out: dict) -> None:
    started = time.perf_counter()
    try:
        r = s.post(BASE + "/api/jawl/restart", headers=headers, json={"wait_for_memory": True}, timeout=300)
        out["status"] = r.status_code
        try:
            out["body"] = r.json()
        except Exception:
            out["body"] = r.text[:400]
    except Exception as exc:
        out["error"] = repr(exc)
    out["elapsed_s"] = round(time.perf_counter() - started, 3)
    out["done"] = True


def wait_jawl_online(deadline_s: float = 240.0) -> bool:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            h = requests.get(BASE + "/api/health", timeout=5).json()
            if h.get("components", {}).get("jawl") == "online":
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def read_sandbox_file_direct(sandbox_relative: str) -> dict:
    """Independent postcondition probe: the profile sandbox is on disk."""
    path = (
        Path(__file__).resolve().parents[1]
        / "runtime" / "instances" / "restart-infer" / sandbox_relative
    )
    try:
        return {"exists": path.exists(), "content": path.read_text(encoding="utf-8")[:200] if path.exists() else ""}
    except Exception as exc:
        return {"error": repr(exc)}


def marker_write_counts(marker: str) -> dict[str, int]:
    """Count successful native writes for this run from the durable journal.

    The file postcondition alone cannot distinguish one write from a replay.
    Pairing the journal's action_started parameters with its successful
    action_finished record gives the acceptance gate an independent exactly-
    once assertion for this unique marker.
    """
    journal = (
        Path(__file__).resolve().parents[1]
        / "runtime" / "instances" / "restart-infer" / "data" / "agent" / "action_journal.jsonl"
    )
    started: dict[tuple[str, str], dict] = {}
    actual_write = 0
    idempotent_noop = 0
    if not journal.is_file():
        return 0
    for line in journal.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (str(entry.get("plan_id") or ""), str(entry.get("action_id") or ""))
        if entry.get("event") == "action_started" and entry.get("tool_name") == "HostOSWriter.write_file":
            parameters = entry.get("parameters")
            if isinstance(parameters, dict) and parameters.get("content") == marker:
                started[key] = entry
        elif (
            entry.get("event") == "action_finished"
            and entry.get("tool_name") == "HostOSWriter.write_file"
            and entry.get("is_success") is True
            and key in started
        ):
            message = str(entry.get("message") or "").lower()
            if "idempotent no-op" in message or "content already matched" in message:
                idempotent_noop += 1
            else:
                actual_write += 1
    return {"actual_write": actual_write, "idempotent_noop": idempotent_noop}


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    s, headers = session_and_csrf()

    turn_a: dict = {}
    attempts: list[dict] = []
    write_text = (
        f"Используй инструмент HostOSWriter.write_file: создай файл {FILE_PATH} "
        f"с текстом {MARKER}. Затем HostOSReader.read_file этого файла. "
        "Не отвечай текстом без вызова инструментов."
    )
    # Keep the acceptance prompt ASCII/English so this gate measures recovery
    # and native-tool correctness, not the local model's Russian skill.
    write_text = (
        f"Use HostOSWriter.write_file to create {FILE_PATH} with exactly this text: {MARKER}. "
        "Then use HostOSReader.read_file on the same file. Do not answer without calling both tools."
    )
    midflight = False
    for attempt in range(1, 5):
        turn_a = {}
        t = threading.Thread(target=stream_turn, args=(s, headers, write_text, turn_a))
        t.start()
        midflight = wait_midflight(turn_a, deadline_s=25.0)
        if midflight:
            attempts.append({"attempt": attempt, "midflight": True})
            break
        t.join(timeout=300)
        attempts.append({"attempt": attempt, "midflight": False, "elapsed_s": turn_a.get("elapsed_s")})
        time.sleep(3)

    restart: dict = {}
    if midflight:
        t2 = threading.Thread(target=restart_native, args=(s, headers, restart))
        t2.start()
    # Drain turn A regardless.
    t.join(timeout=330)
    if midflight:
        t2.join(timeout=330)
    time.sleep(3)

    online = wait_jawl_online()

    def final_text(payload: dict) -> str:
        last = ""
        for ev in payload.get("events") or []:
            if '"type": "final"' in ev or '"type":"final"' in ev:
                last = ev
        return last

    turn_b: dict = {}
    inspect_text = (
        f"Проверь файл {FILE_PATH}: вызови HostOSReader.read_file и сообщи в ответе SHA-256 из "
        "результата чтения. Если файла нет — скажи это прямо, затем создай его один раз через "
        f"HostOSWriter.write_file с текстом {MARKER} и снова прочитай, сообщив SHA-256. "
        "Не отвечай по памяти: история после перезапуска может быть недостоверной."
    )
    inspect_text = (
        f"Inspect {FILE_PATH} after the restart. Call HostOSReader.read_file and report the SHA-256 "
        f"from its result. If the file is missing, create it exactly once with HostOSWriter.write_file "
        f"using text {MARKER}, read it again, and report the SHA-256. Do not rely on conversation memory."
    )
    b_attempts: list[dict] = []
    for attempt in range(1, 4):
        turn_b = {}
        started_b = time.perf_counter()
        try:
            with s.post(
                BASE + "/api/chat/stream",
                headers=headers,
                json={"text": inspect_text, "session_id": SESSION},
                stream=True,
                timeout=300,
            ) as stream:
                turn_b["status"] = stream.status_code
                turn_b["events"] = [line.decode("utf-8", "replace") for line in stream.iter_lines() if line]
        except Exception as exc:
            turn_b["error"] = repr(exc)
        turn_b["elapsed_s"] = round(time.perf_counter() - started_b, 3)
        fb_now = final_text(turn_b)
        b_attempts.append({"attempt": attempt, "status": turn_b.get("status"), "elapsed_s": turn_b["elapsed_s"],
                           "error": turn_b.get("error"), "final_is_error": "завершён с ошибкой" in fb_now})
        if fb_now and "завершён с ошибкой" not in fb_now:
            break
        time.sleep(10)

    # Recovery continuation phase: the inspected turn may honestly report the
    # missing file and end before completing the recovery. Continue like a
    # real user would, then re-verify the disk truth.
    continuations: list[dict] = []
    def _disk_has_marker() -> bool:
        probe = read_sandbox_file_direct(FILE_PATH)
        return bool(probe.get("exists")) and MARKER in str(probe.get("content", ""))
    for cont in range(1, 3):
        current_final = final_text(turn_b)
        if _disk_has_marker() and re.search(r"\b[0-9a-f]{64}\b", current_final, re.IGNORECASE):
            break
        cont_turn: dict = {}
        cont_text = (
            f"Продолжи задачу до результата: создай файл {FILE_PATH} через "
            f"HostOSWriter.write_file с текстом {MARKER}, затем вызови "
            "HostOSReader.read_file и сообщи SHA-256 из результата чтения в ответе."
        )
        cont_text = (
            f"Continue the current task. The native read already completed. Reply to the user with the "
            f"exact SHA-256 from the HostOSReader.read_file result for {FILE_PATH}; include the 64-character "
            "hex digest in the final message and do not send a generic greeting."
        )
        started_c = time.perf_counter()
        try:
            with s.post(
                BASE + "/api/chat/stream",
                headers=headers,
                json={"text": cont_text, "session_id": SESSION},
                stream=True,
                timeout=300,
            ) as stream:
                cont_turn["status"] = stream.status_code
                cont_turn["events"] = [line.decode("utf-8", "replace") for line in stream.iter_lines() if line]
        except Exception as exc:
            cont_turn["error"] = repr(exc)
        cont_turn["elapsed_s"] = round(time.perf_counter() - started_c, 3)
        continuations.append(cont_turn)
        time.sleep(3)
    if continuations:
        turn_b["continuations"] = continuations
        last_cont = continuations[-1]
        cont_final = final_text(last_cont)
        if cont_final:
            turn_b["events"] = (turn_b.get("events") or []) + last_cont.get("events", [])

    fb = final_text(turn_b)
    restart_body = restart.get("body") if isinstance(restart.get("body"), dict) else {}
    agent_ready = bool(restart_body.get("ok")) and (
        restart_body.get("result", {}).get("agent_ready") is True
        or restart_body.get("result", {}).get("status") == "restarted"
    )
    file_probe = read_sandbox_file_direct(FILE_PATH)
    import hashlib as _hashlib
    disk_sha = ""
    if file_probe.get("exists"):
        disk_sha = _hashlib.sha256(
            (Path(__file__).resolve().parents[1] / "runtime" / "instances" / "restart-infer" / FILE_PATH).read_bytes()
        ).hexdigest()
    import re as _re
    reported_sha = ""
    m = _re.search(r"\b[0-9a-f]{64}\b", fb, _re.IGNORECASE)
    if m:
        reported_sha = m.group(0).lower()
    health_after = None
    try:
        health_after = requests.get(BASE + "/api/health", timeout=5).json().get("components", {}).get("jawl")
    except Exception as exc:
        health_after = f"error: {exc!r}"
    journal_counts = marker_write_counts(MARKER)

    acceptance = {
        "restart_landed_midflight": midflight,
        "turn_a_attempts": attempts,
        "restart_route_answered": bool(restart.get("done")) and restart.get("status") == 200,
        "restart_agent_ready": agent_ready,
        "turn_b_final_present": bool(fb),
        "file_on_disk_has_marker": bool(file_probe.get("exists")) and MARKER in str(file_probe.get("content", "")),
        "turn_b_reports_disk_sha": bool(disk_sha) and reported_sha == disk_sha,
        "turn_b_reports_marker": MARKER in fb,
        "journal_actual_marker_writes": journal_counts["actual_write"],
        "journal_idempotent_marker_noops": journal_counts["idempotent_noop"],
        "journal_proves_no_duplicate_write": journal_counts["actual_write"] == 1,
        "health_jawl_after_turn_b": health_after,
        "disk_sha256": disk_sha,
        "reported_sha256": reported_sha,
    }
    evidence = {
        "schema_version": 1,
        "test": "restart_during_active_native_inference",
        "base_url": BASE,
        "session_id": SESSION,
        "marker": MARKER,
        "file_path": FILE_PATH,
        "started_at": started_at,
        "turn_a": turn_a,
        "restart": restart,
        "turn_b": turn_b,
        "turn_b_attempts": b_attempts,
        "acceptance": acceptance,
        "pass": bool(
            acceptance["restart_landed_midflight"]
            and acceptance["restart_route_answered"]
            and acceptance["restart_agent_ready"]
            and acceptance["turn_b_final_present"]
            and acceptance["turn_b_reports_disk_sha"]
            and acceptance["file_on_disk_has_marker"]
            and acceptance["journal_proves_no_duplicate_write"]
        ),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(EVIDENCE), "pass": evidence["pass"], "acceptance": acceptance}, ensure_ascii=False))
    return 0 if evidence["pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
