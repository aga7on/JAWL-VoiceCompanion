# -*- coding: utf-8 -*-
"""DSH full-duplex orchestrator (engineer+admin). Runs until 2026-11-10 11:00:00 local PC time.
Responsibilities:
- Pivot DSH to FULLDUPLEX_ROADMAP once idle (deliver fullduplex_plan.md).
- Monitor DSH: busy/idle, STATE/TODO/CHANGELOG changes, 503-like stalls.
- On iteration complete (STATE changed + DSH idle): send next-iteration continuation prompt.
- On stall (idle, no STATE change for IDLE_NUDGE_S): nudge continuation.
- On 503/cooldown signature in recent tail or repeated failed delivery: backoff, retry nudge.
- Never patch @deepseek-ai/dsh. Never touch read-only zones. Log everything.
"""
import json, os, re, subprocess, sys, time, io, urllib.request
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

MCP = "http://127.0.0.1:5051"
PROJ = r"G:\AI\JAWL-VoiceCompanion-V0.5"
BR = os.path.join(PROJ, "tools", "seniors_bridge")
STATE = os.path.join(PROJ, "docs", "STATE.md")
TODO = os.path.join(PROJ, "TODO.md")
CHANGELOG = os.path.join(PROJ, "CHANGELOG.md")
ROADMAP = os.path.join(PROJ, "docs", "FULLDUPLEX_ROADMAP.md")
PIVOT = os.path.join(BR, "fullduplex_plan.md")
LOG = os.path.join(BR, "orchestrator.log")
OSTATE = os.path.join(BR, "orchestrator_state.json")
COMPOSER = 'div[role="textbox"][data-composer-input]'
SEND = ['button[aria-label="Send message"]', 'button[aria-label^="Send" i]']
STOP_SEL = 'button[aria-label*="Stop"]'

DEADLINE = datetime(2026, 11, 10, 11, 0, 0)
POLL_S = 45
IDLE_NUDGE_S = 10 * 60          # idle with no state change -> nudge
BUSY_STUCK_S = 45 * 60          # Stop visible this long -> log warning (don't kill)
COOLDOWN_NUDGE_S = 12 * 60      # min gap between nudges
BACKOFF_503_S = 90


def log(msg):
    line = time.strftime("[%m-%d %H:%M:%S] ") + msg
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line)
    except Exception:
        pass


def load_os():
    try:
        with open(OSTATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_os(d):
    try:
        with open(OSTATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def mcp(tab, cmd, args, wait=60):
    data = json.dumps({"tab": tab, "cmd": cmd, "args": args}).encode("utf-8")
    req = urllib.request.Request(f"{MCP}/job?wait={wait}", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=wait + 15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        log(f"[mcp] {cmd}->{tab}: {exc}")
        return None


def dom(sel, limit=4, chars=300):
    res = mcp("dsh", "dom", {"sel": sel, "limit": limit, "textChars": chars})
    d = (res or {}).get("data") or {}
    return d.get("count") or 0, d.get("items", [])


def dsh_state():
    stop, _ = dom(STOP_SEL, 2, 20)
    send, sitems = dom(SEND[0], 4, 20)
    comp, citems = dom(COMPOSER, 4, 120)
    send_ok = any(i.get("vis") and not i.get("disabled") for i in sitems) if sitems else False
    comp_vis = any(i.get("vis") for i in citems) if citems else (comp > 0)
    return {"busy": stop > 0, "send_ok": send_ok, "composer": comp_vis}


def mtimes():
    out = {}
    for k, p in (("state", STATE), ("todo", TODO), ("changelog", CHANGELOG)):
        try:
            out[k] = os.path.getmtime(p)
        except OSError:
            out[k] = 0
    return out


def read_file(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def send_dsh(text):
    st = dsh_state()
    if st["busy"]:
        return False, "busy"
    mcp("dsh", "click", {"sel": COMPOSER}, wait=20)
    time.sleep(1)
    mcp("dsh", "type", {"sel": COMPOSER, "text": text}, wait=180)
    time.sleep(1.5)
    _, items = dom(COMPOSER, 4, 500000)
    got = (items[-1].get("text") if items else "") or ""
    if len(got.strip()) < max(80, int(min(len(text), 4000) * 0.6)):
        return False, f"fill_fail {len(got)}/{len(text)}"
    btn = None
    for sel in SEND:
        _, its = dom(sel, 8, 20)
        if any(i.get("vis") and not i.get("disabled") for i in its):
            btn = sel
            break
    if not btn:
        return False, "no_send"
    mcp("dsh", "click", {"sel": btn}, wait=20)
    time.sleep(4)
    _, it3 = dom(COMPOSER, 2, 80)
    t3 = (it3[-1].get("text") if it3 else "") or ""
    st2 = dsh_state()
    ok = (not t3.strip()) or st2["busy"]
    return ok, f"cleared={not t3.strip()} generating={st2['busy']}"


NUDGE = (
    "ПРОДОЛЖАЙ (оркестратор: harness2 Propose→Probe→Compose; дедлайн 11:00 10.11.2026 ПК).\n"
    "ПРИОРИТЕТЫ: (A) full-duplex аудио-слой с TTS как MOSS Live; (B) проактив по сенсорике через мотивации/drives (интересное в описаниях экрана → рост мотивации → проактивный ответ, turn-policy, без спама).\n"
    "1) Прочитай docs/FULLDUPLEX_ROADMAP.md, docs/SENSORY_MOTIVATION_DESIGN.md, tools/seniors_bridge/IMPROVEMENT_HARNESS.md, docs/STATE.md, TODO.md.\n"
    "2) Выбери ОДИН следующий невыполненный пункт: сперва P0→P5 full-duplex если есть выполнимый; иначе P-M0/P-M1 сенсорной мотивации. BLOCKED → причина + следующий выполнимый.\n"
    "3) Реализуй: код/контракт + focused regression (deterministic где возможно) + числа/доказательство. Не трогай read-only (JAWL-Coding, VoiceMem, G:\\RE, runtime/jawl-sources). Без вопросов.\n"
    "4) Обнови docs/STATE.md, TODO.md, CHANGELOG.md (PASS/FAILED/UNKNOWN/BLOCKED, file:line, метрики). Честно.\n"
    "Работай."
)


def main():
    os_state = load_os()
    pivoted = bool(os_state.get("pivoted"))
    last_nudge = float(os_state.get("last_nudge", 0))
    last_mt = os_state.get("last_mt") or mtimes()
    last_progress = float(os_state.get("last_progress", time.time()))
    busy_since = None
    log(f"=== ОРКЕСТРАТОР СТАРТ === deadline={DEADLINE} pivoted={pivoted}")

    while datetime.now() < DEADLINE:
        time.sleep(POLL_S)
        try:
            st = dsh_state()
        except Exception as exc:
            log(f"[poll] ошибка: {exc}")
            continue
        mt = mtimes()
        progressed = any(mt[k] != last_mt.get(k, 0) for k in ("state", "todo", "changelog"))
        now = time.time()

        if progressed:
            changed = [k for k in ("state", "todo", "changelog") if mt[k] != last_mt.get(k, 0)]
            log(f"[progress] обновлены: {','.join(changed)} @ " + ", ".join(
                f"{k}={time.strftime('%H:%M:%S', time.localtime(mt[k]))}" for k in changed))
            last_mt = mt
            last_progress = now
            os_state["last_mt"] = mt
            os_state["last_progress"] = last_progress
            save_os(os_state)

        if st["busy"]:
            if busy_since is None:
                busy_since = now
                log("[dsh] генерация началась")
            elif now - busy_since > BUSY_STUCK_S:
                log(f"[warn] DSH busy уже {int((now-busy_since)/60)} мин — наблюдаю (не убиваю)")
                busy_since = now  # не спамить
            continue
        else:
            if busy_since is not None:
                log("[dsh] генерация завершилась (idle)")
                busy_since = None

        # idle path
        if not pivoted:
            msg = read_file(PIVOT)
            if not msg.strip():
                log("[pivot] fullduplex_plan.md пуст — нечего слать")
                time.sleep(60)
                continue
            ok, info = send_dsh(msg)
            log(f"[pivot] доставка: ok={ok} info={info}")
            if ok:
                pivoted = True
                last_nudge = now
                os_state.update({"pivoted": True, "last_nudge": last_nudge})
                save_os(os_state)
            else:
                if "busy" not in info and now - last_nudge > BACKOFF_503_S:
                    last_nudge = now
                    os_state["last_nudge"] = last_nudge
                    save_os(os_state)
            continue

        # post-pivot: nudge if idle long enough since last progress or last nudge
        idle_for = now - last_progress
        since_nudge = now - last_nudge
        if idle_for >= IDLE_NUDGE_S and since_nudge >= COOLDOWN_NUDGE_S:
            ok, info = send_dsh(NUDGE)
            log(f"[nudge] idle={int(idle_for)}с ok={ok} info={info}")
            last_nudge = now
            os_state["last_nudge"] = last_nudge
            if ok:
                # treat nudge as activity prompt; progress timer resets on actual doc change
                pass
            save_os(os_state)

    log(f"=== ОРКЕСТРАТОР СТОП: дедлайн {DEADLINE} достигнут ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"[FATAL] {exc!r}")
        raise
