#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night_autopilot.py — v2 ночного моста «исполнитель → старшие модели» JAWL-VoiceCompanion.

Ведёт цикл САМ через командный канал MCP (browser_mcp.py, порт 5051):
вкладки ChatGPT / LM Arena / DSH управляются командами ping/dom/type/click/key/navigate
(пользовательские воркеры bridge-console.user.js уже установлены).

Цикл:
  A. ChatGPT — разбор STATE/TODO (в цикле 1 ответ уже есть в диалоге — просто забираем)
  B. LM Arena «Argon» — гипотезы
  C. ChatGPT — финальный пошаговый план ('=== ПЛАН ===')
  D. Доставка плана в открытую сессию DSH (127.0.0.1:3080)
  пауза — ждём обновления docs/STATE.md (DSH отработал) или максимум 15 минут.

Устойчивость: END-маркеры (===GPT1_END=== / ===ARGON_END=== / ===PLAN_END===), токен-граница
после эха промпта, обрезка UI-шума, повторы, лог night_v2.log, извлечения в extracts/,
state v2_state.json, файл-лок night_autopilot.lock.

Запуск:  python tools/seniors_bridge/night_autopilot.py [--once]
  --once   только один цикл (дымовой прогон, для наблюдения)
Стоп: MAX_CYCLES (бюджет циклов за запуск; STOP_AFTER отключён юзером 08.11), фатальная недоступность MCP.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ----- НАСТРОЙКИ (менять только здесь) --------------------------------------
MCP = "http://127.0.0.1:5051"
BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(BRIDGE_DIR))
STATE = os.path.join(PROJECT_ROOT, "docs", "STATE.md")
TODO = os.path.join(PROJECT_ROOT, "TODO.md")
PLAN_OUT = os.path.join(BRIDGE_DIR, "last_plan.md")
LOG_FILE = os.path.join(BRIDGE_DIR, "night_v2.log")
STATEJSON = os.path.join(BRIDGE_DIR, "v2_state.json")
EXTRACTS = os.path.join(BRIDGE_DIR, "extracts")
LOCK_FILE = os.path.join(BRIDGE_DIR, "night_autopilot.lock")

HEAD_CHARS = 9000
MAX_CYCLES = 8
# STOP_AFTER (утренний гейт) отключён юзером 08.11 — пусть работает автономно.
NEXT_CYCLE_WAIT = 15 * 60
MIN_BREAK_AFTER_D = 4 * 60
FAILED_CYCLE_PAUSE = 6 * 60

GPT_COMPOSER = ('div[contenteditable="true"][aria-label="Спросить ChatGPT"], '
                'div[contenteditable="true"][aria-label="Ask ChatGPT"]')
GPT_SEND = ['button[data-testid="send-button"]',
            'button[aria-label*="Отправить"]',
            'button[aria-label^="Send" i]']
AR_COMPOSER = 'textarea[placeholder^="Ask followup"]'
AR_SEND = ['button[aria-label="Send message"]']
DS_COMPOSER = 'div[role="textbox"][data-composer-input]'
DS_SEND = ['button[aria-label="Send message"]', 'button[aria-label^="Send" i]']

DS_HOME = "http://127.0.0.1:3080/"
GPT_PIN = "/c/6aeb2af9-bed4-83ee-a372-8b9165dcedf8"   # закреплённый диалог-архитектор
AR_PIN = "/c/01a1b69b-9cba-730c-8ec6-fb7770bd6957"    # закреплённый диалог-Argon

SEED_KEY = "Ты — старший архитектор-критик проект JAWL Voice Companion"  # эхо v1-промпта в цикле 1
ARENA_CHIP = "gemini-4-argon-high"
GPT_FOOTERS = [("ChatGPT может допускать ошибки", 700), ("ChatGPT может ошибаться", 700),
               ("Последний ответ", 700), ("Уровень усилий рассуждения", 700)]
AR_FALLBACKS = [("Direct", 2000), (ARENA_CHIP, 2000), ("Deep Think", 2000)]

PROJECT_LINE = ("проект JAWL Voice Companion V0.5 — ежедневный живой компаньон на ПК владельца "
                "(личность, память, ASR/TTS локально, экран/зрение, инициатива). Исполнитель — "
                "агент DeepSeek в харнессе DSH, репозиторий G:/AI/JAWL-VoiceCompanion-V0.5.")

EXECUTOR_RULES = """Жёсткие правила исполнителя (сводка из AGENTS.md проекта, план обязан им подчиняться):
- Единственный dev-repo: G:/AI/JAWL-VoiceCompanion-V0.5; read-only зоны G:/AI/JAWL-Coding, G:/AI/VoiceMem, G:/RE.
- Одна итерация = один видимый результат + focused regression, затем обновление docs/STATE.md, TODO.md, CHANGELOG.md.
- Тесты: python -X utf8 -m pytest tests/ -q для затронутых зон; desktop node tests для UI правок.
- Не коммитить, не reset, не трогать чужие процессы; не занимать GPU0 неявно (Bonsai на GPU1).
- Латентность речи — KPI: voice_end→ASR уже ~0.31-0.41с; TTS first chunk ~1.19с — главный оставшийся floor.
- Не обещать 24x7 acceptance по короткому прогону; soak ≠ короткий тест.
- План обязан служить JAWL_GOAL.md: каждый шаг ссылается на AC-XX или инвариант; шаг, не служащий ни одному, — не делать или явно пометить деградцию цели.
"""

DSH_HEADER = ("=== ПЛАН ОТ СТАРШИХ (цепочка ChatGPT → LM Arena Argon → ChatGPT) ===\n"
              "Ты — агент-исполнитель JAWL Voice Companion. Правила цикла: "
              "tools/seniors_bridge/BRIDGE_LOOP.md. Выполни план ниже в одну рабочую итерацию "
              "(код + focused regression + бенчмарк-числа), затем обнови docs/STATE.md, TODO.md, "
              "CHANGELOG.md. Без вопросов — просто работай.\n\n")

GOAL_FILE = os.path.join(PROJECT_ROOT, "JAWL_GOAL.md")

GOAL_COMPACT = (
    "ЦЕЛЕВОЙ КОНТРАКТ (JAWL_GOAL.md): North Star — полностью локальный, постоянно "
    "доступный мультимодальный ИИ-компаньон (экран + системный звук + голос; понимание "
    "происходящего во времени; уместная инициатива; память совместного опыта; "
    "ретроспективная перепроверка прошлого по сырым A/V-свидетельствам). Различать "
    "событие / исходную запись / наблюдение модели / гипотезу / подтверждённый факт; "
    "правдоподобное без доказательства — не успех.\n"
    "Приёмочные критерии (целевые, требуют утверждения владельцем): AC-01 живое присутствие; "
    "AC-02 актуальное зрение (≥85% точности, честное not_observed); AC-03 голос и прерывание "
    "(voice_end→first audio p95 ≤4 c, остановка после barge-in ≤300 мс); AC-04 персональная/"
    "временная непрерывность (≥70% верных биндингов, ≤5% ложных); AC-05 уместная инициатива "
    "(0 нежелательных реплик, ≥80% значимых); AC-06 память диалога/событий (≥80% верных, "
    "0 выдуманных); AC-07 ретроспективное зрение (inspect_segment): ≥70% верных grounded-ответов "
    "на читаемых случаях, нечитаемые — честное воздержание; AC-08 надёжность/ресурсы "
    "(0 крашей, p95 FPS ≤5%); AC-09 контроль владельца/приватность (пауза, forget, offline)."
)


# ---- логирование --------------------------------------------------------------
log_lock = threading.Lock()
LOGHANDLE = [None]


def log(msg):
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    with log_lock:
        try:
            if LOGHANDLE[0] is None:
                LOGHANDLE[0] = open(LOG_FILE, "a", encoding="utf-8")
            LOGHANDLE[0].write(line + "\n")
            LOGHANDLE[0].flush()
        except Exception:
            print(line)
    print(line)


def save_state(obj):
    try:
        with open(STATEJSON, "w", encoding="utf-8") as f:
            json.dump({**obj, "updated_at": datetime.now().isoformat()}, f,
                      ensure_ascii=False, indent=1)
    except OSError:
        pass


def load_state():
    try:
        with open(STATEJSON, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def extract_save(cycle, name, text):
    os.makedirs(EXTRACTS, exist_ok=True)
    p = os.path.join(EXTRACTS, f"cycle{cycle:02d}_{name}.md")
    try:
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        log(f"[{name}] сохранено: {os.path.basename(p)} ({len(text)} симв.)")
    except OSError as exc:
        log(f"[{name}] НЕ СОХРАНЕНО: {exc}")


# ---- MCP-клиент ------------------------------------------------------------------
def mcp(tab, cmd, args, wait=40):
    data = json.dumps({"tab": tab, "cmd": cmd, "args": args}).encode("utf-8")
    req = urllib.request.Request(f"{MCP}/job?wait={wait}", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=wait + 15) as r:
            res = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        log(f"[mcp] {cmd}→{tab}: http-сбой {exc}")
        return None
    if not res or res.get("status") == "timeout":
        log(f"[mcp] {cmd}→{tab}: воркер не ответил")
        return None
    if not res.get("ok"):
        log(f"[mcp] {cmd}→{tab}: ошибка {res.get('error')}")
        return None
    return res.get("data")


def try_mcp(tab, cmd, args, wait=40, attempts=3, pause=4):
    for _ in range(attempts):
        d = mcp(tab, cmd, args, wait=wait)
        if d is not None:
            return d
        time.sleep(pause)
    return None


def alive_tabs():
    try:
        with urllib.request.urlopen(f"{MCP}/health", timeout=5) as r:
            return json.loads(r.read().decode("utf-8")).get("tabs", {})
    except Exception:
        return {}


def channel_alive(tab):
    return bool(alive_tabs().get(tab, {}).get("alive"))


def dance_to_pin():
    """Канала chatgpt нет → перегоняем живую dsh-вкладку на закреплённый диалог
    (воркер перерегистрируется по URL как chatgpt)."""
    if channel_alive("chatgpt"):
        return
    if not channel_alive("dsh"):
        log("[dance] нет ни chatgpt, ни dsh — танец невозможен")
        return
    log("[dance] канала chatgpt нет — перегоняю dsh-вкладку на закреплённый диалог ChatGPT")
    mcp("dsh", "navigate", {"url": "https://chatgpt.com" + GPT_PIN}, wait=20)
    for _ in range(12):
        time.sleep(3)
        if channel_alive("chatgpt"):
            wait_ready()
            log("[dance] канал chatgpt восстановлен")
            return
    log("[dance] канал chatgpt не восстановился после танца")


def dance_to_dsh():
    """Канала dsh нет, но кто-то на chatgpt (та же физическая вкладка) → вернуть домой."""
    if channel_alive("dsh") or not channel_alive("chatgpt"):
        return
    log("[dance] возвращаю вкладку из chatgpt домой в DSH")
    mcp("chatgpt", "navigate", {"url": DS_HOME}, wait=20)
    for _ in range(12):
        time.sleep(3)
        if channel_alive("dsh"):
            log("[dance] канал dsh восстановлен")
            return
    log("[dance] канал dsh не восстановился после танца")


# ---- текст страницы / извлечение ---------------------------------------------------
def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def page_text(tab, sel="main", chars=500000):
    d = try_mcp(tab, "dom", {"sel": sel, "limit": 1, "textChars": chars}, wait=90)
    try:
        return d["items"][0].get("text", "")
    except Exception:
        return ""


def cut_markers(tail, tags, fallback_phrases=()):
    pat = re.compile(r"==+\s*(?:" + "|".join(re.escape(t) for t in tags) + r")\s*==+")
    m = pat.search(tail)
    if m and m.start() > 30:
        return tail[: m.start()].rstrip()
    pos = len(tail)
    for item in fallback_phrases:
        phrase, min_pos = item if isinstance(item, tuple) else (item, 2000)
        i = tail.find(phrase)
        # min_pos отсекает ранние ложные вхождения (например, чип модели сразу после эха)
        if 2000 < i < pos and i >= min_pos:
            pos = i
    return tail[:pos].rstrip()


def extract_after_key(key, page_txt, tags, fallbacks, min_len=250, strip_prefix=None):
    n = norm(page_txt)
    idx = n.rfind(key)
    if idx < 0:
        log(f"[extract] ключ эха не найден: {key[:60]}")
        return None
    ans = cut_markers(n[idx + len(key):], tags, fallbacks)
    if strip_prefix:
        ans = re.sub(rf"^\s*{re.escape(strip_prefix)}\s*", "", ans)
    if len(ans) < min_len:
        log(f"[extract] ответ подозрительно короткий ({len(ans)} симв.) — отказ")
        return None
    return ans


# ---- ввод/отправка во вкладку -------------------------------------------------------
def find_enabled(tab, sels):
    """Возвращает первый селектор, у чьего ПОСЛЕДНЕГО видимого элемента есть «не disabled»."""
    for sel in (sels if isinstance(sels, (list, tuple)) else [sels]):
        cand = try_mcp(tab, "dom", {"sel": sel, "limit": 8, "textChars": 8}, wait=25)
        vis = [i for i in (cand or {}).get("items", []) if i.get("vis")]
        if vis and not vis[-1].get("disabled"):
            return sel
    return None


def send_text(tab, prompt, composer_sel, send_sels, mode="ce"):
    """Печатает prompt в композер и отправляет. mode: 'ce' — contenteditable (проверка по тексту),
    'ta' — textarea (проверка по активности кнопки). Возвращает True/False."""
    threshold = max(200, int(len(prompt) * 0.3))
    for attempt in (1, 2, 3):
        # фокусировка: клик по композеру, иначе type может «не долететь»
        try_mcp(tab, "click", {"sel": composer_sel}, wait=20)
        time.sleep(1.0)
        try_mcp(tab, "type", {"sel": composer_sel, "text": prompt}, wait=120)
        time.sleep(1.5)
        comp = try_mcp(tab, "dom", {"sel": composer_sel, "limit": 8, "textChars": 300000}, wait=25)
        items = (comp or {}).get("items", [])
        comp_text = items[-1].get("text", "") if items else ""
        filled = len(comp_text.strip()) >= threshold if mode == "ce" else True
        btn = find_enabled(tab, send_sels) if mode == "ta" else find_enabled(tab, send_sels)
        if mode == "ce" and not filled:
            log(f"[{tab}] попытка {attempt}: композер не заполнен ({len(comp_text)}/{len(prompt)})")
            time.sleep(3)
            continue
        if mode == "ta" and not btn:
            log(f"[{tab}] попытка {attempt}: кнопка неактивна — текст не принят")
            time.sleep(3)
            continue
        if btn:
            try_mcp(tab, "click", {"sel": btn}, wait=25)
            log(f"[{tab}] попытка {attempt}: клик по {btn}")
        else:
            try_mcp(tab, "key", {"sel": composer_sel, "key": "Enter"}, wait=20)
            log(f"[{tab}] попытка {attempt}: Enter по композеру (кнопка не найдена)")
        time.sleep(2.5)
        # подтверждение: композер очищен
        for _ in range(5):
            comp2 = try_mcp(tab, "dom", {"sel": composer_sel, "limit": 8, "textChars": 40}, wait=25)
            items2 = (comp2 or {}).get("items", [])
            t2 = items2[-1].get("text", "x") if items2 else "x"
            if not t2.strip():
                log(f"[{tab}] отправка подтверждена (композер очищен)")
                return True
            time.sleep(2)
        log(f"[{tab}] композер не очистился — повтор")
    log(f"[{tab}] СБОЙ отправки текста после 3 попыток")
    return False


Q_CAP = 52000  # encoded-бюджет ?q-предзаполнения (проверено: 52.5К ок; 105К убивает загрузку вкладки)


def wait_ready(attempts=12, pause=3.5):
    for _ in range(attempts):
        d = mcp("chatgpt", "ping", {}, wait=15)
        if d and d.get("ready") == "complete":
            return d
        time.sleep(pause)
    return None


def send_via_q(prompt, retries=2):
    """Доставка в ChatGPT через предзаполнение `?q=` на голом домене + Enter.
    ?q работает ТОЛЬКО на голом домене и редиректит в последний активный диалог
    (закреплённый); на /c/<id>?q= параметр игнорируется. Во время активной генерации
    предзаполнение не применяется — поэтому попыток несколько, без «зачисток»
    навигацией (навигация во время потока обрывает отправку/ответ)."""
    if not GPT_PIN.startswith("/c/"):
        log("[q] GPT_PIN не настроен — путь недоступен")
        return False
    for attempt in (1, 2, 3):
        enc = urllib.parse.quote(prompt, safe="")
        if len(enc) > Q_CAP:
            log(f"[q] encoded {len(enc)} > кап {Q_CAP} — нужно сжатие промпта")
            return False
        try_mcp("chatgpt", "navigate", {"url": "https://chatgpt.com/?q=" + enc}, wait=45)
        d = wait_ready()
        log(f"[q] попытка {attempt}: редирект {(d or {}).get('url', '?')[:48]}")
        if not d:
            # загрузка умерла (тяжёлый URL) — сани-навигация: не оставлять битый
            # ?q висеть в адресной строке и мёртвую вкладку в канале
            log("[q] загрузка не ожила — санитарная навигация на закреплённый диалог")
            try_mcp("chatgpt", "navigate", {"url": "https://chatgpt.com" + GPT_PIN}, wait=30)
            wait_ready()
            time.sleep(3)
        time.sleep(4)
        comp = try_mcp("chatgpt", "dom", {"sel": GPT_COMPOSER, "limit": 4, "textChars": 400000}, wait=35)
        items = (comp or {}).get("items", [])
        got = items[-1].get("text", "") if items else ""
        if len(got) < int(len(prompt) * 0.8):
            log(f"[q] попытка {attempt}: предзаполнение неполное ({len(got)}/{len(prompt)})")
            time.sleep(6)
            continue
        try_mcp("chatgpt", "key", {"sel": GPT_COMPOSER, "key": "Enter"}, wait=20)
        time.sleep(4)
        for _ in range(5):
            comp2 = try_mcp("chatgpt", "dom", {"sel": GPT_COMPOSER, "limit": 2, "textChars": 80}, wait=25)
            it2 = (comp2 or {}).get("items", [])
            t2 = it2[-1].get("text", "x") if it2 else "x"
            if not t2.strip():
                log("[q] отправка подтверждена (композер очищен)")
                return True
            time.sleep(2)
        log("[q] композер не очистился — повтор")
    log("[q] СБОЙ доставки через ?q")
    return False


def ensure_pin_page():
    """Вкладка chatgpt должна стоять на закреплённом диалоге. Если канал жив,
    но URL другой (корень/новый чат) — навигацией возвращаем на PIN."""
    d = mcp("chatgpt", "ping", {}, wait=15) or {}
    url = d.get("url") or ""
    if GPT_PIN in url:
        return True
    log(f"[pin] вкладка не на PIN ({url[:70]}) — возвращаю")
    try_mcp("chatgpt", "navigate", {"url": "https://chatgpt.com" + GPT_PIN}, wait=45)
    wait_ready()
    time.sleep(3)
    d2 = mcp("chatgpt", "ping", {}, wait=15) or {}
    ok = GPT_PIN in (d2.get("url") or "")
    log(f"[pin] после навигации: {'на PIN' if ok else 'всё ещё мимо'}")
    return ok


def hard_reload_pin():
    """Рендер залип: navigate на тот же URL — no-op. Уходим на корень и обратно."""
    log("[pin] hard reload: корень → PIN")
    try_mcp("chatgpt", "navigate", {"url": "https://chatgpt.com"}, wait=45)
    wait_ready()
    time.sleep(6)
    try_mcp("chatgpt", "navigate", {"url": "https://chatgpt.com" + GPT_PIN}, wait=45)
    wait_ready()
    time.sleep(6)
    return ensure_pin_page()


def send_chatgpt(prompt):
    """ChatGPT: сначала обычная набивка (только на PIN), при сбое — ?q-механизм."""
    dance_to_pin()
    if not ensure_pin_page() and not hard_reload_pin():
        log("[chatgpt] PIN не достижим — пробую ?q-доставку")
        return send_via_q(prompt)
    if send_text("chatgpt", prompt, GPT_COMPOSER, GPT_SEND, mode="ce"):
        return True
    if hard_reload_pin() and send_text("chatgpt", prompt, GPT_COMPOSER, GPT_SEND, mode="ce"):
        return True
    log("[chatgpt] набивка не удалась — переключаюсь на ?q-доставку")
    return send_via_q(prompt)


GPT_TOK_RE = re.compile(r"\(служебный токен, не упоминай и не повторяй его: ([0-9a-f]{4,32})")


def clean_gpt_answer(ans):
    """Срезает UI-мусор ChatGPT: свёрнутая копия сообщения, чип времени, aria-метка."""
    m = re.match(r"^.*?ChatGPT сказал:\s*", ans, re.S)
    if m and m.end() <= 500:
        ans = ans[m.end():]
    ans = re.sub(r"…?\s*Показать ещё\s*", "", ans)
    ans = re.sub(r"Обработка заняла \d+\s*s\s*", "", ans)
    return ans.strip()


def wait_gpt_answer(tok, endtag, fallbacks, timeout, poll=30):
    """Ожидание ответа архитектора в ChatGPT по токен-схеме: срез ПОСЛЕ эха промпта
    (служебный токен), маркер endtag ждём ТОЛЬКО внутри среза — эхо само содержит
    маркер-инструкцию, поэтому счёт маркеров по всей странице врёт."""
    phrase = f"(служебный токен, не упоминай и не повторяй его: {tok}" if tok else None
    t0 = time.time()
    checks = 0
    while time.time() - t0 < timeout:
        time.sleep(poll)
        checks += 1
        n = norm(page_text("chatgpt"))
        if phrase:
            i = n.rfind(phrase)
            s = n[i + len(phrase):] if i >= 0 else ""
        else:
            m_last = None
            for m in GPT_TOK_RE.finditer(n):
                m_last = m
            s = n[m_last.end():] if m_last else ""
        m_end = re.search(r"==+\s*" + re.escape(endtag) + r"\s*==+", s)
        if not m_end:
            log(f"[chatgpt] ожидание #{checks}: срез {len(s)} симв., маркера нет")
            continue
        ans = clean_gpt_answer(cut_markers(s[:m_end.start()], [endtag], fallbacks))
        if len(ans) < 250:
            log(f"[chatgpt] маркер есть, извлечение короткое ({len(ans)}) — продолжаю")
            continue
        log(f"[chatgpt] ответ получен (проверка #{checks}, {len(ans)} симв.)")
        return ans
    log(f"[chatgpt] ТАЙМАУТ ожидания токен-среза ({timeout // 60} мин)")
    return None


def wait_answer(tab, tok, endtag, fallbacks, before_len, timeout, poll=45, stable_need=3, strip=None):
    """Стоп-условие: счётчик маркеров endtag вырос после отправки (или текст стабилен).
    chatgpt — токен-схема через wait_gpt_answer; arena — по токену эха."""
    if tab == "chatgpt":
        return wait_gpt_answer(tok, endtag, fallbacks, timeout)
    pat = re.compile(r"==+\s*" + re.escape(endtag) + r"\s*==+")
    key = (tok if (tok and tab == "arena") else "ChatGPT сказал: ")
    strip_pfx = strip if tab == "arena" else None
    t0 = time.time()
    checks = 0
    base = None
    last_tail = None
    stable = 0
    while time.time() - t0 < timeout:
        time.sleep(poll)
        checks += 1
        fresh = page_text(tab)
        n = norm(fresh)
        cnt = len(pat.findall(n))
        if base is None:
            base = cnt
            log(f"[{tab}] база маркеров {endtag}: {base} (опрос #{checks})")
        if cnt > base:
            log(f"[{tab}] {endtag}: маркеров {cnt} > базы {base} — ответ готов (опрошено {checks}, контент {len(n)} сим.)")
            ans = extract_after_key(key, fresh, [endtag], fallbacks, strip_prefix=strip_pfx)
            if tab == "arena" and ans:
                ans = TOKEN_STRIP.sub("", ans)
            return ans if not ans or len(ans) >= 250 else None
        if last_tail is not None and n[-400:] == last_tail:
            stable += 1
        else:
            stable = 0
            last_tail = n[-400:]
        if stable >= stable_need:
            log(f"[{tab}] текст стабилен ({stable}) без роста счётчика маркеров — принудительный срез")
            ans = extract_after_key(key, fresh, [endtag], fallbacks, strip_prefix=strip_pfx)
            if tab == "arena" and ans:
                ans = TOKEN_STRIP.sub("", ans)
            return ans if not ans or len(ans) >= 250 else None
        log(f"[{tab}] ожидание #{checks}: маркеров {cnt}/{base}")
    log(f"[{tab}] ТАЙМАУТ ожидания ответа ({timeout // 60} мин)")
    return None


# ---- снимок проекта -------------------------------------------------------------------
def read_head(path, chars=HEAD_CHARS):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(chars)
    except OSError:
        return "(файл не найден)"


def snapshot():
    return ("СТАТУС ПРОЕКТА (docs/STATE.md, начало файла):\n<<<\n" + read_head(STATE)
            + "\n>>>\n\nТЕКУЩАЯ ОЧЕРЕДЬ (TODO.md, начало файла):\n<<<\n" + read_head(TODO) + "\n>>>")


def snapshot_compact(state_chars=3500, todo_chars=2200):
    """Компактный снимок для ?q-доставки (кап URL ~52-60К encoded)."""
    return ("СТАТУС ПРОЕКТА (docs/STATE.md, начало):\n<<<\n" + read_head(STATE, state_chars)
            + "\n>>>\n\nОЧЕРЕДЬ (TODO.md, начало):\n<<<\n" + read_head(TODO, todo_chars) + "\n>>>")


def hypotheses_toc(text, per=650):
    """Механическое оглавление гипотез Argon (полный текст агент прочтёт из файла)."""
    n = norm(text)
    parts = re.split(r"(?=\bГипотеза \d)", n)
    items = []
    for p in parts:
        if re.match(r"\bГипотеза \d", p):
            essence = p[:per]
            if len(p) > per:
                essence = essence.rstrip() + " …"
            items.append(essence)
    return "- " + "\n- ".join(items) if items else n[:per]


# ---- фазы цикла ------------------------------------------------------------------
def token_prompt(base, tag, endtag):
    tok = uuid.uuid4().hex[:8]
    return (base.rstrip()
            + f"\n\nЗакончи ответ отдельной последней строкой ровно так: ==={endtag}===\n"
            + "(служебный токен, не упоминай и не повторяй его: " + tok), tok


TOKEN_STRIP = re.compile(r"^[0-9a-fA-F]{6,12}\s*(?:gemini-4-argon-high\s*)?", re.IGNORECASE)


def newest_extract(suffix):
    if not os.path.isdir(EXTRACTS):
        return None
    cands = [os.path.join(EXTRACTS, n) for n in os.listdir(EXTRACTS) if n.endswith(suffix)]
    return max(cands, key=os.path.getmtime) if cands else None


def pop_flag(flag):
    st = load_state()
    if flag in st:
        st.pop(flag, None)
        save_state(st)


def phase_A(cycle, seed_mode):
    base = (f"Ты — старший архитектор-критик {PROJECT_LINE}\n\n{GOAL_COMPACT}\n\n{snapshot_compact()}\n\n"
            "Задача: 1) что из STATE/TODO подтверждено фактами, а что — обещания; "
            "2) главные риски и противоречия в очереди; 3) 3-5 конкретных ТЕХНИЧЕСКИХ направлений "
            "для генератора гипотез с учётом того, что ночью агент работает сам, без владельца; "
            "4) ДРЕЙФ ЦЕЛИ: куда работа уходит от JAWL_GOAL.md; пункты очереди, не служащие ни одному "
            "AC/инварианту, — назвать и отложить. "
            "Отвечай кратко, списками, без воды, по-русски. Не задавай вопросов — отвечай сразу.")
    ans = None
    if seed_mode:
        log("[A] цикл 1: готовый ответ архитектора уже в диалоге — забираю")
        ans = extract_after_key(SEED_KEY, page_text("chatgpt"), ["GPT1_END"], GPT_FOOTERS)
    elif load_state().get("extract_phase_a_inline"):
        log("[A] resume-inline: жду готовый ответ архитектора (токен-срез последнего эха)")
        pop_flag("extract_phase_a_inline")
        ans = wait_gpt_answer(None, "GPT1_END", GPT_FOOTERS, 40 * 60)
    elif load_state().get("reuse_phase_a"):
        p = newest_extract("phaseA_chatgpt.md")
        if p:
            try:
                ans = open(p, encoding="utf-8").read()
                log(f"[A] resume: переиспользую {os.path.basename(p)} ({len(ans)} симв.)")
            except OSError as exc:
                log(f"[A] resume-файл не читается: {exc}")
        pop_flag("reuse_phase_a")
    if ans is None and not seed_mode and load_state().get("extract_phase_a_inline") is None and load_state().get("reuse_phase_a") is None:
        prompt, tok = token_prompt(base, "GPT1", "GPT1_END")
        if not send_chatgpt(prompt):
            return None
        ans = wait_answer("chatgpt", tok, "GPT1_END", GPT_FOOTERS, 0, 40 * 60)
    if ans:
        extract_save(cycle, "phaseA_chatgpt", ans)
    return ans


def phase_B(cycle, analysis):
    ans = None
    if load_state().get("reuse_phase_b_file"):
        p = newest_extract("phaseB_argon.md")
        if p:
            try:
                ans = open(p, encoding="utf-8").read()
                log(f"[B] resume-file: переиспользую {os.path.basename(p)} ({len(ans)} симв.)")
            except OSError as exc:
                log(f"[B] resume-файл не читается: {exc}")
        pop_flag("reuse_phase_b_file")
    if ans is None and load_state().get("reuse_phase_b"):
        log("[B] resume: извлекаю уже сгенерированный ответ Argon из вкладки")
        ans = extract_after_key("не упоминай и не повторяй его: ", page_text("arena"),
                                ["ARGON_END"], AR_FALLBACKS)
        if ans:
            ans = TOKEN_STRIP.sub("", ans)
        pop_flag("reuse_phase_b")
    if ans is None:
        base = (f"Ты — генератор идей (без стереотипов, приоритет реалистичности) для {PROJECT_LINE}\n\n"
                f"{GOAL_COMPACT}\n\n"
                f"Текущее состояние и очередь проекта:\n<<<\n{snapshot()}\n>>>\n\n"
                f"Запрос архитектора (анализ последнего цикла):\n<<<\n{analysis}\n>>>\n\n"
                "Предложи 5-7 гипотез/подходов. Для каждой: суть; почему может сработать; какой "
                "AC/инвариант из цели она двигает; конкретный "
                "эксперимент (файлы/модули, шаги); измеримая метрика успеха (мс/%/тесты); риски и "
                "стоимость. Только то, что агент осилит за одну итерацию. Списком, по-русски, без воды. "
                "Не задавай вопросов — отвечай сразу.")
        prompt, tok = token_prompt(base, "ARGON", "ARGON_END")
        before_len = len(norm(page_text("arena")))
        if not send_text("arena", prompt, AR_COMPOSER, AR_SEND, mode="ta"):
            return None
        ans = wait_answer("arena", tok, "ARGON_END", AR_FALLBACKS, before_len, 30 * 60, strip=ARENA_CHIP)
        if ans:
            ans = TOKEN_STRIP.sub("", ans)
    if ans:
        extract_save(cycle, "phaseB_argon", ans)
    return ans


def trim(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[…подробности гипотез обрезаны по объёму — работай с тем, что есть]"


def phase_C(cycle, hypotheses):
    if load_state().get("reuse_phase_c_file"):
        p = newest_extract("phaseC_plan.md")
        pop_flag("reuse_phase_c_file")
        if p:
            try:
                ans = open(p, encoding="utf-8").read()
                if not ans.startswith("=== ПЛАН"):
                    ans = "=== ПЛАН ===\n" + ans
                log(f"[C] resume-file: переиспользую {os.path.basename(p)} ({len(ans)} симв.)")
                return ans
            except OSError as exc:
                log(f"[C] resume-файл не читается: {exc}")
    hyp_file = os.path.join(EXTRACTS, f"cycle{cycle:02d}_phaseB_argon.md")
    toc = hypotheses_toc(hypotheses)
    base = (f"Ты — старший архитектор {PROJECT_LINE}. Генератор гипотез (LM Arena Argon) вернул 6-7 гипотез. "
            f"{GOAL_COMPACT}\n\n"
            "ПОЛНЫЙ текст agent прочтёт сам из "
            f"G:/AI/JAWL-VoiceCompanion-V0.5/tools/seniors_bridge/extracts/cycle{cycle:02d}_phaseB_argon.md. "
            "Сжатое оглавление:\n<<<\n" + toc + "\n>>>\n\n"
            "1) Отбери 1-2 сильнейшие гипотезы (отклонённые — одной строкой почему).\n"
            "2) Напиши ЧЁТКИЙ ПОШАГОВЫЙ ПЛАН для агента-исполнителя на ближайшую итерацию "
            "(детали выбранной гипотезы — 'см. файл гипотез', не пересказывай его целиком).\n"
            + EXECUTOR_RULES +
            "\nТребования к плану: конкретные шаги с файлами; какие тесты писать и что фиксируют; "
            "измеримые метрики успеха; В ШАПКЕ плана — строка 'Соответствие цели: AC-XX — что и почему "
            "это двигает North Star'; цель — заметный видимый результат за цикл; в конце — требование "
            "обновить STATE/TODO/CHANGELOG. Начни ответ строкой '=== ПЛАН ===' и заголовком цикла. "
            "По-русски, технически. Не задавай вопросов.")
    prompt, tok = token_prompt(base, "PLAN", "PLAN_END")
    if not send_chatgpt(prompt):
        return None
    ans = wait_answer("chatgpt", tok, "PLAN_END", GPT_FOOTERS, 0, 45 * 60)
    if ans:
        if not ans.startswith("=== ПЛАН"):
            ans = "=== ПЛАН ===\n" + ans
        extract_save(cycle, "phaseC_plan", ans)
    return ans


def phase_D(cycle, plan, fallback_reason=None):
    dance_to_dsh()
    if fallback_reason:
        body = (f"=== ПЛАН (деградированный: {fallback_reason}) ===\n\n" + plan)
    else:
        body = plan
    hyp_file = os.path.join(EXTRACTS, f"cycle{cycle:02d}_phaseB_argon.md")
    pointer = ""
    if os.path.exists(hyp_file):
        pointer = ("\n\nПолный текст гипотез (прочти сам при выработке решения): "
                   f"G:/AI/JAWL-VoiceCompanion-V0.5/tools/seniors_bridge/extracts/cycle{cycle:02d}_phaseB_argon.md")
    msg = DSH_HEADER + body + pointer
    extract_save(cycle, "phaseD_message", msg)
    ok = send_text("dsh", msg, DS_COMPOSER, DS_SEND, mode="ce")
    if ok:
        log("[D] план доставлен в сессию DSH через браузер")
        return "DELIVERED_VIA_BROWSER"
    try:
        with open(PLAN_OUT, "w", encoding="utf-8", newline="") as f:
            f.write(msg)
        log("[D] в браузере не доставлено — план сохранён в last_plan.md (утром вручную)")
    except OSError as exc:
        log(f"[D] и файл не записан: {exc}")
    return "SAVED_TO_FILE"


# ---- цикл / паузы ---------------------------------------------------------------------
def nudge_dsh(why):
    """Тычок «уснувшего» DSH-агента: короткое '.' + кнопка отправки.
    Ручной приём владельца («отправь точку — и работа пошла») после обрыва
    хода по «все аккаунты пула на охлаждении» (RETIRED_MODEL / rate-limit)."""
    log(f"[подзатыльник] {why} — шлю '.' в DSH")
    try_mcp("dsh", "click", {"sel": DS_COMPOSER}, wait=20)
    time.sleep(1.0)
    try_mcp("dsh", "type", {"sel": DS_COMPOSER, "text": "."}, wait=120)
    time.sleep(1.5)
    btn = find_enabled("dsh", DS_SEND)
    if not btn:
        log("[подзатыльник] кнопки отправки не нашёл — пропускаю")
        return
    try_mcp("dsh", "click", {"sel": btn}, wait=20)
    time.sleep(3)
    comp = try_mcp("dsh", "dom", {"sel": DS_COMPOSER, "limit": 2, "textChars": 40}, wait=25)
    it = (comp or {}).get("items", [])
    t2 = it[-1].get("text", "x") if it else "x"
    if not t2.strip():
        log("[подзатыльник] '.' доставлена — агент должен продолжить")
    else:
        log("[подзатыльник] композер не очистился — вероятно, не отправлено")


def wait_state_change(before_mtime):
    nudged = set()
    t0 = time.time()
    while time.time() - t0 < NEXT_CYCLE_WAIT:
        if time.time() - t0 >= MIN_BREAK_AFTER_D:
            try:
                m = os.path.getmtime(STATE)
            except OSError:
                m = 0
            if m and m != before_mtime:
                log("[пауза] STATE.md изменился — даю DSH ещё 6 минут и стартую следующий цикл")
                time.sleep(6 * 60)
                return
            # агент молчит на STATE 9+ минут — тыкаем (пул шлюза мог уйти в cooldown)
            for at in (9, 13):
                if time.time() - t0 >= at * 60 and at not in nudged:
                    nudged.add(at)
                    nudge_dsh(f"STATE.md молчит {at} мин после доставки плана")
        time.sleep(60)
    log("[пауза] отработал бюджет паузы")


def mark_state(cycle, phase):
    """Обновляет cycle/phase, СОХРАНЯЯ resume-флаги и прочие ключи (не затирает)."""
    st = load_state()
    st["cycle"] = cycle
    st["phase"] = phase
    st.setdefault("cycle_done", 0)
    save_state(st)


def run_cycle(cycle, seed_mode):
    st_mtime0 = os.path.getmtime(STATE) if os.path.exists(STATE) else 0
    log(f"=== ЦИКЛ {cycle} СТАРТ (seed_mode={seed_mode}) ===")
    mark_state(cycle, "A")

    analysis = phase_A(cycle, seed_mode)
    if not analysis:
        log("=== ЦИКЛ ПРЕРВАН: нет анализа архитектора (A) ===")
        mark_state(cycle, "A-FAILED")
        return False

    mark_state(cycle, "B")
    hypotheses = phase_B(cycle, analysis)
    if not hypotheses:
        log("=== ЦИКЛ ПРЕРВАН: нет гипотез Argon (B) ===")
        mark_state(cycle, "B-FAILED")
        return False

    mark_state(cycle, "C")
    plan = phase_C(cycle, hypotheses)
    fallback = None
    if not plan:
        fallback = "фаза C не прошла, сводит только гипотезы"
        plan = (EXECUTOR_RULES + "\nГипотезы от Argon (выполни самую сильную по своему решению; "
                "полный список — в файле ниже):\n" + trim(hypotheses, 18000))
        log("=== АВАРИЙНЫЙ РЕЖИМ: план собран без фазы C ===")

    mark_state(cycle, "D")
    outcome = phase_D(cycle, plan, fallback_reason=fallback)
    log(f"=== ЦИКЛ {cycle} ЗАВЕРШЁН ({outcome}) ===")

    st = load_state()
    st["cycle_done"] = st.get("cycle", cycle)
    st["phase"] = "WAITING"
    st["outcome"] = outcome
    save_state(st)

    wait_state_change(st_mtime0)
    return True


def wait_tabs(max_wait=300):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        tabs = alive_tabs()
        got = [t for t in ("arena", "chatgpt", "dsh") if tabs.get(t, {}).get("alive")]
        if "arena" in got and ("chatgpt" in got or "dsh" in got):
            log(f"[tabs] вкладки активны: {', '.join(got)}")
            return True
        log(f"[tabs] жду: {json.dumps(tabs, ensure_ascii=False)[:220]}")
        time.sleep(10)
    log("[tabs] ФАТАЛЬНО: вкладки не оживили за 5 минут")
    return False


def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            pid = int(open(LOCK_FILE, encoding="utf-8").read().strip())
        except Exception:
            pid = 0
        if pid:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            if str(pid) in (r.stdout or ""):
                log(f"ЛОК: другой экземпляр жив (PID {pid}) — выходим")
                return False
        log("[лок] устарел — переписываю")
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


def main():
    once = "--once" in sys.argv
    if not acquire_lock():
        return
    try:
        log("=== night_autopilot v2 СТАРТ ===")
        if not wait_tabs():
            return
        attempted = 0
        while True:
            st = load_state()
            cycle = int(st.get("cycle_done", 0)) + 1
            has_a = False
            if os.path.isdir(EXTRACTS):
                try:
                    has_a = any(n.endswith("phaseA_chatgpt.md") for n in os.listdir(EXTRACTS))
                except OSError:
                    has_a = False
            seed_mode = (cycle == 1 and not has_a)
            # STOP_AFTER (утренний гейт) отключён 08.11 по решению юзера:
            # «пофиг на правило — пусть работает автономно». Бюджет циклов — per-run, см. ниже.
            if attempted >= MAX_CYCLES:
                log(f"=== MAX_CYCLES: исчерпано {MAX_CYCLES} циклов за этот запуск — стоп ===")
                break
            try:
                ok = run_cycle(cycle, seed_mode)
            except Exception as exc:
                ok = False
                log(f"=== ЦИКЛ ПАЛ ИСКЛЮЧЕНИЕМ: {exc!r} ===")
            attempted += 1
            if once and attempted >= 1:
                log("[once] дымовой цикл завершён — выходим")
                break
            if not ok:
                log("[цикл] следующий цикл через паузу-буфер")
                time.sleep(FAILED_CYCLE_PAUSE)
    finally:
        release_lock()
        log("=== night_autopilot v2 ЗАВЕРШЁН ===")


if __name__ == "__main__":
    main()
