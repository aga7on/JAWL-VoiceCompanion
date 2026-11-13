#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
connect_seniors.py — мост «исполнитель → старшие модели» профиля JAWL-VoiceCompanion.

Пинг-понг одной итерации:
  фаза 1  ChatGPT (вкладка браузера, Tampermonkey-воркер)  — архитектор/критик: разбор STATE/TODO
  фаза 2  LM Arena «Argon» (вкладка, Tampermonkey-воркер)  — генератор гипотез
  фаза 3  ChatGPT                                          — сводит в пошаговый ПЛАН
  фаза 4  доставка плана в открытую сессию DSH (вкладка 127.0.0.1:3080)

Механика: воркеры в браузере опрашивают GET /get_task?client=..., сервер раздаёт промпты
строго по фазам, принимает POST /submit_result, в конце пишет last_plan.md и завершается.

Запуск из корня проекта (или где угодно — пути абсолютные):
  python G:\\AI\\JAWL-VoiceCompanion-V0.5\\tools\\seniors_bridge\\connect_seniors.py
  флаги: --selftest (прогон фаз без браузера), --quiet-read (ничего не менять, служебный)

Правила исполнителя: tools/seniors_bridge/BRIDGE_LOOP.md
Коды выхода: 0 план готов; 1 порт занят; 2 таймаут; 3 самотест не прошёл.
"""
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PORT = 5050
HOST = "127.0.0.1"
BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(BRIDGE_DIR))  # G:\AI\JAWL-VoiceCompanion-V0.5
STATE = os.path.join(PROJECT_ROOT, "docs", "STATE.md")
TODO = os.path.join(PROJECT_ROOT, "TODO.md")
PLAN_OUT = os.path.join(BRIDGE_DIR, "last_plan.md")
RESULT_NOTE = os.path.join(BRIDGE_DIR, "last_result.txt")

READY_TIMEOUT = 50 * 60     # общий дедлайн пинга
STEP_TIMEOUT = 30 * 60      # ожидание одного клиента в фазе
DSH_ACK_TIMEOUT = 8 * 60    # ожидание ack вкладки DSH
HEAD_CHARS = 9000           # сколько берём от STATE/TODO (текущая очередь в начале файлов)
POLL_MS_HINT = 3000

PHASES = ["chatgpt", "arena", "chatgpt", "dsh"]

PROJECT_LINE = ("проект JAWL Voice Companion V0.5 — ежедневный живой компаньон на ПК владельца "
                "(личность, память, ASR/TTS локально, экран/зрение, инициатива). Исполнитель — "
                "агент DeepSeek в харнессе DSH, работает в G:\\AI\\JAWL-VoiceCompanion-V0.5.")

EXECUTOR_RULES = """Жёсткие правила исполнителя (сводка из AGENTS.md проекта, план обязан им подчиняться):
- Единственный dev-repo: G:\\AI\\JAWL-VoiceCompanion-V0.5; read-only зоны G:\\AI\\JAWL-Coding, G:\\AI\\VoiceMem, G:\\RE, pinned runtime snapshot.
- Одна итерация = один видимый результат + focused regression, потом короткое обновление docs/STATE.md, TODO.md, CHANGELOG.md.
- Тесты: python -X utf8 -m pytest tests/ -q для затронутых зон; desktop node tests для UI правок.
- Не коммитить, не reset, не трогать чужие процессы; не занимать GPU0 неявно (Bonsai на GPU1).
- Латентность речи — KPI: voice_end→ASR уже ~0.31-0.41с; TTS first chunk ~1.19с — главный оставшийся floor.
- Не обещать 24x7 acceptance по короткому прогону; soak ≠ короткий тест.
"""


def read_head(path, chars):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(chars)
    except OSError:
        return "(файл не найден)"


def project_snapshot():
    return (
        "СТАТУС ПРОЕКТА (docs/STATE.md, начало файла — последние проверки):\n<<<\n"
        + read_head(STATE, HEAD_CHARS)
        + "\n>>>\n\nТЕКУЩАЯ ОЧЕРЕДЬ (TODO.md, начало файла):\n<<<\n"
        + read_head(TODO, HEAD_CHARS)
        + "\n>>>"
    )


DSH_DELIVERY_HEADER = (
    "=== ПЛАН ОТ СТАРШИХ (продвижение цепочки ChatGPT → LM Arena Argon → ChatGPT) ===\n"
    "Ты — агент-исполнитель JAWL Voice Companion. Правила цикла: "
    "tools/seniors_bridge/BRIDGE_LOOP.md. Выполни план ниже в одну рабочую итерацию "
    "(код + focused regression + бенчмарк-числа), затем обнови docs/STATE.md, TODO.md, "
    "CHANGELOG.md и запусти: python tools/seniors_bridge/connect_seniors.py\n\n"
)


class Bridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.step = 0
        self.task_for = None
        self.phase_started_at = None
        self.deadline = time.time() + READY_TIMEOUT
        self.finished = threading.Event()
        self.outcome = None
        self.prompts = self._build()

    def _build(self):
        snap = project_snapshot()
        return {
            0: f"Ты — старший архитектор-критик {PROJECT_LINE}\n\n{snap}\n\n"
               "Задача: 1) что из STATE/TODO подтверждено фактами, а что — обещания;\n"
               "2) главные риски, узкие места и противоречия в очереди;\n"
               "3) 3-5 конкретных ТЕХНИЧЕСКИХ направлений для генератора гипотез (что предложить: "
               "архитектурные решения, алгоритмы, эксперименты) с учётом того, что ночью агент работает по цепочке сам, без владельца.\n"
               "Отвечай кратко, списками, без воды.",
        }

    # --- консистентное состояние для HTTP --------------------------------- #

    def current_client(self):
        return PHASES[self.step] if self.step < len(PHASES) else None

    def get_task(self, client):
        with self.lock:
            if client != self.current_client():
                return None
            if self.task_for is None:
                self.task_for = {"client": client, "prompt": self.prompts[self.step],
                                 "opened_at": time.time()}
                if self.phase_started_at is None:
                    self.phase_started_at = time.time()
                print(f"[bridge] фаза {self.step + 1}/4 ({client}): задача выдана")
            return self.task_for

    def submit(self, client, response):
        with self.lock:
            if client != self.current_client():
                return {"status": "ignored", "reason": "wrong phase"}
            if self.step == 3:
                self.outcome = "DELIVERED_VIA_BROWSER"
                self.finished.set()
                print("[bridge] доставка в сессию DSH подтверждена")
                return {"status": "ok"}
            text = (response or "").strip()
            if len(text) < 10:
                return {"status": "ignored", "reason": "empty response"}
            nxt = self.step + 1
            if self.step == 0:
                self.prompts[1] = (
                    f"Ты — генератор идей (без ограничений стереотипов) для {PROJECT_LINE}\n\n"
                    f"Текущее состояние и очередь проекта:\n<<<\n{project_snapshot()}\n>>>\n\n"
                    f"Запрос архитектора (анализ последнего цикла):\n<<<\n{text}\n>>>\n\n"
                    "Предложи 5-7 гипотез/подходов. Для каждой: суть; почему может сработать; "
                    "конкретный эксперимент (файлы/модули, шаги); измеримая метрика успеха (мс/%/тесты); "
                    "риски и стоимость. Не предлагай проекты на недели — только то, что агент осилит "
                    "за одну рабочую итерацию. Список с заголовками."
                )
            elif self.step == 1:
                self.prompts[2] = (
                    f"Ты — старший архитектор {PROJECT_LINE}. Генератор гипотез (LM Arena Argon) предложил:\n"
                    f"<<<\n{text}\n>>>\n\n"
                    "1) Отбери 1-3 сильнейшие гипотезы (отклонённые — одной строкой почему).\n"
                    "2) Напиши ЧЁТКИЙ ПОШАГОВЫЙ ПЛАН для агента-исполнителя на ближайшую итерацию:\n"
                    + EXECUTOR_RULES +
                    "\nТребования к плану: конкретные шаги с файлами; какие тесты (pytest/node) писать и "
                    "что фиксируют; какие измеримые метрики считать успехом; цель — заметный видимый "
                    "результат за цикл; в конце план должен требовать обновления STATE/TODO/CHANGELOG.\n"
                    "Начни ответ строкой '=== ПЛАН ===' и заголовком цикла. По-русски, технически."
                )
            elif self.step == 2:
                self.prompts[3] = DSH_DELIVERY_HEADER + text
            self.step = nxt
            self.task_for = None
            self.phase_started_at = None
            print(f"[bridge] фаза {nxt + 1}/4: ожидание {PHASES[nxt]}")
            return {"status": "ok"}

    def _final_plan_text(self):
        t = self.task_for
        if t and t["client"] == "dsh" and t.get("prompt"):
            return t["prompt"]
        if self.step >= 3:
            return self.prompts.get(3)
        return None

    def watch(self):
        while not self.finished.wait(timeout=5):
            now = time.time()
            if now > self.deadline:
                self.outcome = f"TIMEOUT (общий дедлайн), фаза {self.step + 1} ({self.current_client()})"
                self.finished.set()
                break
            opened = self.task_for["opened_at"] if self.task_for else self.phase_started_at
            budget = DSH_ACK_TIMEOUT if self.step == 3 else STEP_TIMEOUT
            if opened is not None and now - opened > budget:
                self.outcome = (f"TIMEOUT: {self.current_client()} не ответил {budget}с "
                                "(проверь вкладку/капчу/логин в консоли F12)")
                self.finished.set()
                break

    def finalize(self):
        plan_text = self._final_plan_text()
        if plan_text and len(plan_text.strip()) > 50:
            with open(PLAN_OUT, "w", encoding="utf-8", newline="") as f:
                f.write(plan_text)
            print(f"[bridge] план сохранён: {PLAN_OUT}")
        else:
            print("[bridge] ПЛАН НЕ СОХРАНЁН (маркер ниже)")
        marker = "BRIDGE_RESULT: " + (self.outcome or
                                      "SAVED_TO_FILE (вкладка dsh не подтвердила — агент читает last_plan.md)")
        print(marker)
        with open(RESULT_NOTE, "w", encoding="utf-8") as f:
            f.write(marker + "\n")


class Handler(BaseHTTPRequestHandler):
    bridge = None

    def log_message(self, fmt, *args):  # видимый журнал HTTP для ночной диагностики
        print(f"[http] {fmt % args}")

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        q = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(q.query)
        if q.path == "/health":
            b = self.bridge
            self._json({"step": b.step + 1, "waiting_for": b.current_client(),
                        "finished": b.finished.is_set()})
        elif q.path == "/get_task":
            client = params.get("client", [""])[0].strip()
            task = self.bridge.get_task(client)
            self._json({"prompt": task["prompt"] if task else None, "poll_hint_ms": POLL_MS_HINT})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/submit_result":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json({"error": "bad json"}, 400)
            return
        self._json(self.bridge.submit((body.get("client") or "").strip(), body.get("response") or ""))


def run_selftest():
    base = f"http://{HOST}:{PORT}"

    def get(client):
        with urllib.request.urlopen(f"{base}/get_task?client={client}", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(client, text):
        data = json.dumps({"client": client, "response": text}).encode("utf-8")
        req = urllib.request.Request(f"{base}/submit_result", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    try:
        p1 = get("chatgpt").get("prompt")
        assert p1 and "STATE.md" in p1 and "TODO.md" in p1, "фаза 1: снимок проекта не вошёл"
        assert get("arena").get("prompt") is None, "фаза 1: arena рано "
        assert post("chatgpt", "ТЕСТ: анализ готов, узкие места X и Y.")["status"] == "ok"
        p2 = get("arena").get("prompt")
        assert p2 and "узкие места X" in p2, "фаза 2: анализ не дошёл до arena"
        assert post("arena", "ТЕСТ: гипотеза А, гипотеза Б, эксперимент W.")["status"] == "ok"
        p3 = get("chatgpt").get("prompt")
        assert p3 and "гипотеза А" in p3 and "ПЛАН" in p3, "фаза 3: гипотезы не вошли"
        assert post("chatgpt", "=== ПЛАН === ТЕСТ: шаг 1 — сделать X. шаг 2 — измерить Y.")["status"] == "ok"
        p4 = get("dsh").get("prompt")
        assert p4 and "=== ПЛАН ===" in p4 and "seniors_bridge" in p4, "фаза 4: доставка не сформирована"
        with open(PLAN_OUT, "w", encoding="utf-8", newline="") as f:
            f.write(p4)
        print("[bridge] план сохранён: " + PLAN_OUT)
        assert post("dsh", "delivered")["status"] == "ok"
        print("[selftest] все 4 фазы пройдены")
        return True
    except Exception as exc:
        print(f"[selftest] ПРОВАЛ: {exc!r}")
        return False


def main():
    selftest = "--selftest" in sys.argv
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"[bridge] НЕ ЗАПУСКАЕТСЯ: порт {PORT} занят ({exc}) — вероятно, другой экземпляр уже работает.")
        sys.exit(1)

    b = Bridge()
    Handler.bridge = b
    threading.Thread(target=b.watch, daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[bridge] оркестратор на http://{HOST}:{PORT}; фаза 1/4: жду ChatGPT")
    print(f"[bridge] снимок: {STATE} + {TODO}")

    if selftest:
        b.outcome = "SELFTEST_OK" if run_selftest() else "SELFTEST_FAILED"
        b.finished.set()

    b.finished.wait()
    b.finalize()
    server.shutdown()
    try:
        server.server_close()
    except Exception:
        pass
    if selftest and b.outcome != "SELFTEST_OK":
        sys.exit(3)
    if (b.outcome or "").startswith("TIMEOUT"):
        sys.exit(2)


if __name__ == "__main__":
    main()
