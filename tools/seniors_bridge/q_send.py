#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
q_send.py — разовый скрипт: доставляет промпт фазы C в ChatGPT через механизм
предзаполнения `https://chatgpt.com/?q=<encoded>` (набивка execCommand сломана),
жмёт Enter и следит за появлением маркера ===PLAN_END=== в транскрипте.
Готовый ответ сохраняет в extracts/cycle02_phaseC_plan.md.
"""
import os
import re
import sys
import time
import urllib.parse
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import night_autopilot as ap  # noqa: E402

BRIDGE = os.path.dirname(os.path.abspath(__file__))
HYP_FILE = os.path.join(BRIDGE, "extracts", "cycle02_phaseB_argon.md")
PROMPT_DUMP = os.path.join(BRIDGE, "extracts", "tmp_phaseC_prompt.txt")
PIN_URL = "https://chatgpt.com/c/6aeb2af9-bed4-83ee-a372-8b9165dcedf8"
PIN_HOME = "https://chatgpt.com/"
KEY = "ChatGPT сказал: "

MARK = re.compile(r"==+\s*PLAN_END\s*==+")


def build_toc(text, per=650):
    n = ap.norm(text)
    parts = re.split(r"(?=\bГипотеза \d)", n)
    items = []
    for p in parts:
        if re.match(r"\bГипотеза \d", p):
            essence = p[:per]
            if len(p) > per:
                essence = essence.rstrip() + " …"
            items.append(essence)
    return "- " + "\n- ".join(items)


def build_prompt():
    with open(HYP_FILE, encoding="utf-8") as f:
        text = f.read()
    toc = build_toc(text)
    tok = uuid.uuid4().hex[:8]
    prompt = (
        "ПРОДОЛЖАЕМ НОЧНУЮ ЦЕПОЧКУ. Твой разбор STATE/TODO (предыдущее твоё сообщение) в силе — используй его.\n\n"
        "Генератор гипотез (LM Arena Argon) вернул 6 гипотез. ПОЛНЫЙ текст у агента-исполнителя "
        "в G:/AI/JAWL-VoiceCompanion-V0.5/tools/seniors_bridge/extracts/cycle02_phaseB_argon.md — "
        "агент прочитает детали сам. Сжатое оглавление:\n\n"
        + toc + "\n\n"
        "Напиши ЧЁТКИЙ ПОШАГОВЫЙ ПЛАН на ОДНУ ночную итерацию агента:\n"
        "1) выбери 1 (максимум 2) гипотезы выше;\n"
        "2) план: конкретные шаги с файлами; какие тесты писать (python -X utf8 -m pytest tests/ -q; "
        "desktop node tests для UI); измеримые метрики (мс/%/фикстуры); ссылки на детали выбранной "
        "гипотезы — 'см. файл гипотез', не пересказывай его целиком.\n"
        + ap.EXECUTOR_RULES +
        "\nВ конце плана — требование обновить docs/STATE.md, TODO.md, CHANGELOG.md. "
        "Начни ответ строкой '=== ПЛАН ===' и заголовком цикла. По-русски, технически, без воды. "
        "Не задавай вопросов.\n"
        "Закончи ответ отдельной строкой ровно так: ===PLAN_END===\n\n"
        f"(служебный токен, не упоминай и не повторяй его: {tok})"
    )
    return prompt


def wait_ping_ready(attempts=12, pause=3.5):
    for _ in range(attempts):
        d = ap.mcp("chatgpt", "ping", {}, wait=15)
        if d and d.get("ready") == "complete":
            return d
        time.sleep(pause)
    return None


def main():
    ap.log("[q_send] строю компактный промпт фазы C…")
    prompt = build_prompt()
    try:
        with open(PROMPT_DUMP, "w", encoding="utf-8", newline="") as f:
            f.write(prompt)
    except OSError as exc:
        ap.log(f"[q_send] дамп промпта не записан: {exc}")
    enc = urllib.parse.quote(prompt, safe="")
    ap.log(f"[q_send] промпт {len(prompt)} симв., encoded {len(enc)}")

    # 1) очистка композера: навигация на вкладку без q
    ap.mcp("chatgpt", "navigate", {"url": PIN_URL}, wait=25)
    wait_ping_ready()
    time.sleep(2)

    # 2) предзаполнение через q
    ap.mcp("chatgpt", "navigate", {"url": PIN_HOME + "?q=" + enc}, wait=45)
    d = wait_ping_ready()
    ap.log(f"[q_send] после q-навигации: url={(d or {}).get('url', '?')[:50]}")
    time.sleep(2)

    # 3) проверка предзаполнения
    comp = ap.try_mcp("chatgpt", "dom", {"sel": ap.GPT_COMPOSER, "limit": 4, "textChars": 400000}, wait=35)
    items = (comp or {}).get("items", [])
    got = items[-1].get("text", "") if items else ""
    ap.log(f"[q_send] в композере {len(got.strip())} из {len(prompt)} симв.")
    if len(got) < int(len(prompt) * 0.8):
        ap.log("[q_send] ПРЕДЗАПОЛННЕНИЕ СОРВАЛОСЬ — выхожу")
        return

    # 4) Enter
    r = ap.try_mcp("chatgpt", "key", {"sel": ap.GPT_COMPOSER, "key": "Enter"}, wait=20)
    ap.log(f"[q_send] Enter: {r}")
    time.sleep(4)

    cleared = False
    for _ in range(5):
        comp2 = ap.try_mcp("chatgpt", "dom", {"sel": ap.GPT_COMPOSER, "limit": 2, "textChars": 80}, wait=25)
        it = (comp2 or {}).get("items", [])
        t2 = it[-1].get("text", "") if it else ""
        if not t2.strip():
            cleared = True
            break
        time.sleep(2)
    ap.log(f"[q_send] композер очищен = {cleared} → {'ОТПРАВЛЕНО' if cleared else 'НЕ отправлено'}")
    if not cleared:
        return

    # 5) ждём маркер ===PLAN_END=== в转录те
    base = None
    t0 = time.time()
    checks = 0
    while time.time() - t0 < 40 * 60:
        checks += 1
        time.sleep(40)
        fresh = ap.page_text("chatgpt")
        n = ap.norm(fresh)
        cnt = len(MARK.findall(n))
        if base is None:
            base = cnt
            ap.log(f"[q_send] база маркеров PLAN_END: {base}")
        if cnt > base:
            ap.log(f"[q_send] PLAN_END получен (проверка #{checks})")
            ans = ap.extract_after_key(KEY, fresh, ["PLAN_END"], ap.GPT_FOOTERS)
            if ans:
                ap.extract_save(2, "phaseC_plan", ans)
                ap.log("[q_send] ГОТОВО: cycle02_phaseC_plan.md сохранён")
            else:
                ap.log("[q_send] маркер есть, извлечение не удалось — нужен ручной разбор")
            return
        ap.log(f"[q_send] ожидание #{checks}: маркеров {cnt}/{base}, текст {len(n)} сим.")
    ap.log("[q_send] ТАЙМАУТ ожидания PLAN_END")


if __name__ == "__main__":
    main()
