// ==UserScript==
// @name         JAWL Bridge — LM Arena «Argon» (генератор гипотез)
// @namespace    jawl-seniors-bridge
// @version      1.0
// @description  Воркер фазы 2 моста: получает промпт с 127.0.0.1:5050, отправляет его в СУЩЕСТВУЮЩИЙ диалог LM Arena (Direct Chat, выбранная модель), ждёт конец генерации, возвращает ответ оркестратору.
// @match        https://lmarena.ai/*
// @match        https://*.lmarena.ai/*
// @match        https://arena.ai/*
// @match        https://chat.lmsys.org/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
    'use strict';

    // ----- НАСТРОЙКИ (менять только здесь) --------------------------------
    const SERVER = 'http://127.0.0.1:5050';
    const CLIENT = 'arena';
    const POLL_MS = 3000;
    const STABLE_TICKS = 8;
    const ANSWER_TIMEOUT_MS = 15 * 60 * 1000;
    // Продолжаем ТОЛЬКО существующий диалог владельца:
    const PIN_URL_PART = '/c/01a1b69b-9cba-730c-8ec6-fb7770bd6957';
    const LOG = '[Bridge-Arena]';
    // ----------------------------------------------------------------------

    let busy = false;
    // Цель = закреплённый существующий диалог владельца; host: lmarena.ai / arena.ai / *.lmarena.ai / lmsys.
    const onTarget = () => (location.hostname.endsWith('arena.ai') || location.hostname.includes('lmsys'))
        && location.href.includes(PIN_URL_PART);

    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const vis = el => !!el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;

    function gmFetch(url, opts = {}) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                url, method: opts.method || 'GET', headers: opts.headers || {},
                data: opts.data || null, timeout: 20000,
                onload: r => { try { resolve(JSON.parse(r.responseText)); } catch (e) { reject(e); } },
                onerror: () => reject(new Error('network')),
                ontimeout: () => reject(new Error('timeout')),
            });
        });
    }

    function getComposer() {
        const ta = Array.from(document.querySelectorAll('textarea')).filter(vis)
            .sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0];
        if (ta) return ta;
        const ce = Array.from(document.querySelectorAll('div[contenteditable="true"]'))
            .filter(vis).sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0];
        return ce || null;
    }

    function insertText(el, text) {
        el.focus();
        if (el.isContentEditable) {
            document.execCommand('selectAll', false, null);
            document.execCommand('insertText', false, text);
            return el.innerText.trim().length > 0;
        }
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
        setter.call(el, text);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        return el.value.length > 0;
    }

    function clickSend() {
        const cands = document.querySelectorAll(
            'button[aria-label*="Send" i], button[title*="Send" i], button[data-testid*="send" i], button[type="submit"]');
        for (const b of cands) if (vis(b) && !b.disabled) return b;
        return null;
    }

    function isWorkingOnAnswer() {
        // класс/атрибут неизвестен заранее: считаем занятость через видимые «индикаторы»
        return Array.from(document.querySelectorAll('[class*="stream" i], [class*="pending" i], [class*="loading" i], [data-pending="true"]')).filter(vis).length > 0;
    }

    // Извлечение ответа: сначала структурные кандидаты, затем общий tail-фолбэк.
    const ASSISTANT_SEL = '[data-message-author-role="assistant"], [role="assistant"], [data-testid*="assistant"], [class*="assistant" i], [class*="bot-msg"], .message.bot';
    const PROMPT_MARK_LEN = 60;

    function answerViaCandidates(baselineCount) {
        const blocks = Array.from(document.querySelectorAll(ASSISTANT_SEL)).filter(vis);
        if (blocks.length > baselineCount) return blocks[blocks.length - 1].innerText.trim();
        return null;
    }

    function tailSnapshot(marker) {
        const root = document.querySelector('main') || document.body;
        const text = root.innerText;
        const idx = text.indexOf(marker);
        if (idx === -1) return null;
        return text.slice(idx + marker.length).trim();
    }

    async function waitAnswer(baselineCount, prompt, timeoutMs) {
        const marker = prompt.replace(/\s+/g, ' ').slice(0, PROMPT_MARK_LEN);
        const t0 = Date.now();
        let lastText = '';
        let stable = 0;
        while (Date.now() - t0 < timeoutMs) {
            await sleep(1000);
            let text = answerViaCandidates(baselineCount) || tailSnapshot(marker);
            if (text && text.length > 30 && text === lastText && !isWorkingOnAnswer()) {
                if (++stable >= STABLE_TICKS) return text;
            } else { lastText = text || ''; stable = 0; }
        }
        return null;
    }

    function waitFor(fn, timeoutMs, stepMs) {
        return (async () => {
            const t0 = Date.now();
            while (Date.now() - t0 < timeoutMs) {
                const v = fn();
                if (v) return v;
                await sleep(stepMs || 500);
            }
            return null;
        })();
    }

    async function handleTask(prompt) {
        busy = true;
        try {
            const baseline = Array.from(document.querySelectorAll(ASSISTANT_SEL)).filter(vis).length;
            const composer = await waitFor(getComposer, 30000);
            if (!composer) throw new Error('поле ввода Arena не найдено (проверь режим Direct Chat)');
            insertText(composer, prompt);
            await sleep(700);
            const btn = clickSend();
            if (btn) btn.click();
            else {
                composer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
                composer.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
                console.warn(LOG, 'кнопка отправки не найдена — послал Enter');
            }
            const answer = await waitAnswer(baseline, prompt, ANSWER_TIMEOUT_MS);
            if (!answer || answer.length < 30) throw new Error('ответ не извлечён (таймаут/капча/изменился DOM)');
            await gmFetch(SERVER + '/submit_result', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                data: JSON.stringify({ client: CLIENT, response: answer }),
            });
            console.log(LOG, 'ответ Argon отправлен, символов:', answer.length);
        } catch (e) {
            console.error(LOG, 'сбой:', (e && e.message) || e);
        } finally { busy = false; }
    }

    setInterval(async () => {
        if (busy || !onTarget()) return;
        try {
            const data = await gmFetch(SERVER + '/get_task?client=' + CLIENT);
            if (data && data.prompt) {
                console.log(LOG, 'получена задача фазы 2, символов:', data.prompt.length);
                handleTask(data.prompt);
            }
        } catch (e) { /* сервер ещё не поднят — ждём */ }
    }, POLL_MS);

    window.__bridgeHealth = () => { gmFetch(SERVER + '/health').then(r => console.log(LOG, r)).catch(() => console.log(LOG, 'сервер недоступен')); };
    console.log(`${LOG} воркер запущен. Целевой диалог: ${PIN_URL_PART} | активна цель: ${onTarget()} | путь: ${location.pathname}`);
})();
