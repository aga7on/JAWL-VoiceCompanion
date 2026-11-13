# -*- coding: utf-8 -*-
"""DSH-сторож: авторетраи точки '.' в DSH, пока пул шлюза голодает.
Фазы:
  WAIT_AGENT     — ждём завершения текущего плана (STATE.md изменится), тыкаем '.' раз в 10 мин
  WAIT_PLAN_EXEC — план cycle04 доставлен из last_plan.md, ждём его выполнения (ещё одно изменение STATE)
После второго изменения STATE — перезапускает night_autopilot (новая версия с ensure_pin_page) и выходит.
Бюджет: 6 часов, затем выходит с записью в лог.
"""
import json, os, subprocess, sys, time, io, urllib.request

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

MCP = "http://127.0.0.1:5051"
BR = r"G:\AI\JAWL-VoiceCompanion-V0.5\tools\seniors_bridge"
PROJ = r"G:\AI\JAWL-VoiceCompanion-V0.5"
STATE = os.path.join(PROJ, "docs", "STATE.md")
PLAN = os.path.join(BR, "last_plan.md")
LOG = os.path.join(BR, "dsh_watchdog.log")
LOCK = os.path.join(BR, "night_autopilot.lock")
COMPOSER = 'div[role="textbox"][data-composer-input]'
SEND = ['button[aria-label="Send message"]', 'button[aria-label^="Send" i]']

POKE_EVERY = 10 * 60
MAX_SECONDS = 6 * 3600


def log(msg):
    line = time.strftime("[%m-%d %H:%M:%S] ") + msg
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line)


def job(tab, cmd, args, wait=60):
    data = json.dumps({"tab": tab, "cmd": cmd, "args": args}).encode("utf-8")
    req = urllib.request.Request(f"{MCP}/job?wait={wait}", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=wait + 15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        log(f"[mcp] {cmd}->{tab}: сбой {exc}")
        return None


def dom(sel, limit=4, chars=200):
    res = job("dsh", "dom", {"sel": sel, "limit": limit, "textChars": chars})
    d = (res or {}).get("data") or {}
    return d.get("count") or 0, d.get("items", [])


def state_mtime():
    try:
        return os.path.getmtime(STATE)
    except OSError:
        return 0


def composer_free():
    stop, _ = dom('button[aria-label*="Stop"]', 2, 20)
    if stop > 0:
        return False
    c, items = dom(COMPOSER, 4, 200)
    return any(i.get("vis") for i in items)


def send_msg(text):
    if not composer_free():
        return False
    job("dsh", "click", {"sel": COMPOSER}, wait=20)
    time.sleep(1)
    job("dsh", "type", {"sel": COMPOSER, "text": text}, wait=120)
    time.sleep(1.5)
    _, items = dom(COMPOSER, 4, 400000)
    got = (items[-1].get("text") if items else "") or ""
    if len(got.strip()) < max(1, min(5, len(text) // 10)):
        log(f"[send] композер не заполнен ({len(got)}/{len(text)})")
        return False
    btn = None
    for sel in SEND:
        _, its = dom(sel, 8, 20)
        vis = [i for i in its if i.get("vis") and not i.get("disabled")]
        if vis:
            btn = sel
            break
    if not btn:
        log("[send] кнопка Send не найдена/неактивна")
        return False
    job("dsh", "click", {"sel": btn}, wait=20)
    time.sleep(3)
    _, it3 = dom(COMPOSER, 2, 50)
    t3 = (it3[-1].get("text") if it3 else "") or ""
    return not t3.strip()


def restart_autopilot():
    if os.path.exists(LOCK):
        try:
            os.remove(LOCK)
        except OSError as exc:
            log(f"[restart] лок не удаляется: {exc}")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, "-u", "night_autopilot.py"], cwd=BR,
                     creationflags=flags, close_fds=True)
    log("[restart] night_autopilot запущен detached — сторож выходит")


def main():
    t0 = time.time()
    st0 = state_mtime()
    phase = "WAIT_AGENT"
    last_poke = 0.0
    log(f"=== СТОРОЖ СТАРТ === фаза {phase}, STATE mtime {time.strftime('%H:%M:%S', time.localtime(st0))}")

    while time.time() - t0 < MAX_SECONDS:
        time.sleep(60)
        st = state_mtime()
        if st != st0:
            if phase == "WAIT_AGENT":
                log("[watch] STATE обновился — агент завершил план. Доставляю last_plan.md")
                try:
                    plan = open(PLAN, encoding="utf-8").read()
                except OSError as exc:
                    log(f"[watch] last_plan.md не читается: {exc}")
                    return
                if not plan.strip():
                    log("[watch] last_plan.md пуст — нечего доставлять, перезапускаю автопилот")
                    restart_autopilot()
                    return
                for _ in range(10):
                    if send_msg(plan):
                        log(f"[watch] план цикла 4 доставлен ({len(plan)} симв.)")
                        phase = "WAIT_PLAN_EXEC"
                        st0 = state_mtime()
                        last_poke = time.time()
                        break
                    time.sleep(60)
                else:
                    log("[watch] не удалось доставить план 10 раз — оставляю для ручного разбора")
                    return
            else:  # WAIT_PLAN_EXEC
                log("[watch] STATE обновился снова — план выполнен, перезапускаю автопилот")
                restart_autopilot()
                return
            continue

        if time.time() - last_poke >= POKE_EVERY:
            if composer_free():
                if send_msg("."):
                    log(f"[poke] '.' отправлен (фаза {phase})")
                    last_poke = time.time()
                else:
                    log("[poke] '.' не ушёл — повтор через минуту")
            else:
                log("[poke] композер занят (идёт генерация) — пропуск")

    log("=== СТОРОЖ: бюджет 6 часов истёк без результата — нужен владелец (аккаунты пула) ===")


if __name__ == "__main__":
    main()
