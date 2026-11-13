// ==UserScript==
// @name         JAWL Bridge — ChatGPT (архитектор/критик)
// @namespace    jawl-seniors-bridge
// @version      1.0
// @description  Воркер фаз 1 и 3 моста: получает промпт с 127.0.0.1:5050, отправляет его в СУЩЕСТВУЮЩИЙ диалог ChatGPT, ждёт конца генерации (стабилизация текста), возвращает ответ оркестратору.
// @match        https://chatgpt.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
    'use strict';

    // ----- НАСТРОЙКИ (менять только здесь) --------------------------------
    const SERVER = 'http://127.0.0.1:5050';
    const CLIENT = 'chatgpt';
    const POLL_MS = 3000;          // период опроса сервера
    const STABLE_TICKS = 8;        // секунд без изменений текста = конец генерации
    const ANSWER_TIMEOUT_MS = 20 * 60 * 1000;
    // Продолжаем ТОЛЬКО существующий диалог владельца (не создавать новые):
    const PIN_URL_PART = '/c/6aeb2af9-bed4-83ee-a372-8b9165dcedf8';
    const LOG = '[Bridge-ChatGPT]';
    // ----------------------------------------------------------------------

    let busy = false;
    const onTarget = () => location.href.includes(PIN_URL_PART);

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
        const el = document.querySelector('#prompt-textarea');
        if (el && vis(el)) return el;
        const ce = Array.from(document.querySelectorAll('div[contenteditable="true"]'))
            .find(x => vis(x) && x.closest('form,main,[class*="composer"]'));
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

    function findSendButton() {
        const cands = document.querySelectorAll(
            'button[data-testid="send-button"], button#composer-submit-button, button[aria-label^="Send" i], button[aria-label*="Отправить" i]');
        for (const b of cands) if (vis(b) && !b.disabled) return b;
        return null;
    }

    function assistantBlocks() {
        let nodes = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
        if (nodes.length === 0) nodes = Array.from(document.querySelectorAll('[data-message-id]'));
        return nodes.filter(vis);
    }

    function stopVisible() {
        return Array.from(document.querySelectorAll('button[data-testid="stop-button"], button[aria-label*="Stop" i], button[aria-label*="Останов" i]')).some(vis);
    }

    async function waitAnswer(baselineCount, timeoutMs) {
        const t0 = Date.now();
        let lastText = '';
        let stable = 0;
        while (Date.now() - t0 < timeoutMs) {
            await sleep(1000);
            const blocks = assistantBlocks();
            if (blocks.length > baselineCount) {
                const text = blocks[blocks.length - 1].innerText.trim();
                if (text.length > 0 && text === lastText && !stopVisible()) {
                    if (++stable >= STABLE_TICKS) return text;
                } else { lastText = text; stable = 0; }
            } else { lastText = ''; stable = 0; }
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
            const baseline = assistantBlocks().length;
            const composer = await waitFor(getComposer, 30000);
            if (!composer) throw new Error('поле ввода ChatGPT не найдено');
            if (!insertText(composer, prompt)) throw new Error('текст не вставился');
            await sleep(500);
            const btn = findSendButton();
            if (btn) { btn.click(); }
            else {
                composer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
                console.warn(LOG, 'кнопка отправки не найдена — послал Enter');
            }
            const answer = await waitAnswer(baseline, ANSWER_TIMEOUT_MS);
            if (!answer || answer.length < 5) throw new Error('ответ не извлечён (таймаут/капча/лимит)');
            await gmFetch(SERVER + '/submit_result', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                data: JSON.stringify({ client: CLIENT, response: answer }),
            });
            console.log(LOG, 'ответ отправлен оркестратору, символов:', answer.length);
        } catch (e) {
            // Оставляем задачу активной: оркестратор отдаст её снова, попытка повторится.
            console.error(LOG, 'сбой:', (e && e.message) || e);
        } finally { busy = false; }
    }

    setInterval(async () => {
        if (busy || !onTarget()) return;
        try {
            const data = await gmFetch(SERVER + '/get_task?client=' + CLIENT);
            if (data && data.prompt) {
                console.log(LOG, 'получена задача фазы, символов:', data.prompt.length);
                handleTask(data.prompt);
            }
        } catch (e) { /* сервер ещё не поднят — ждём */ }
    }, POLL_MS);

    // Проверка из консоли вкладки: __bridgeHealth()
    window.__bridgeHealth = () => { gmFetch(SERVER + '/health').then(r => console.log(LOG, r)).catch(e => console.log(LOG, 'сервер недоступен')); };
    console.log(`${LOG} воркер запущен. Целевой диалог: ${PIN_URL_PART} | активна цель: ${onTarget()}`);
})();
