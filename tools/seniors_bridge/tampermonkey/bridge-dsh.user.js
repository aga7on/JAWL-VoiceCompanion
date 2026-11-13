// ==UserScript==
// @name         JAWL Bridge — DSH (доставка плана агенту)
// @namespace    jawl-seniors-bridge
// @version      1.0
// @description  Воркер фазы 4 моста: забирает готовый план с 127.0.0.1:5050 и отправляет его в открытую сессию DeepSeek Harness (dsh-web, 127.0.0.1:3080) через composer. Если агент занят — сообщение уходит в очередь/steer штатным Enter-поведением.
// @match        http://127.0.0.1:3080/*
// @match        http://localhost:3080/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
    'use strict';

    // ----- НАСТРОЙКИ (менять только здесь) --------------------------------
    const SERVER = 'http://127.0.0.1:5050';
    const CLIENT = 'dsh';
    const POLL_MS = 3000;
    const SEND_RETRY_SEC = 90;       // суммарный срок доставок (агент может быть занят)
    const LOG = '[Bridge-DSH]';
    // ----------------------------------------------------------------------

    let busy = false;

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

    // Composer DSH: div[role="textbox"][data-composer-input] (Lexical, см. ComposerContentEditable.tsx)
    function getComposer() {
        return document.querySelector('div[role="textbox"][data-composer-input]');
    }

    function insertText(el, text) {
        el.focus();
        document.execCommand('selectAll', false, null);
        document.execCommand('insertText', false, text);
        return el.textContent.trim().length > 0;
    }

    function clickSendIfPossible() {
        // Строго кнопка отправки; НИКОГДА не трогаем кнопку Stop ("Stop generating").
        const cands = document.querySelectorAll(
            'button[aria-label="Send message"], button[aria-label="发送消息"], button[aria-label^="Send" i]');
        for (const b of cands) if (vis(b) && !b.disabled) return b;
        return null;
    }

    async function deliver(prompt) {
        const t0 = Date.now();
        let inserted = false;
        while (Date.now() - t0 < SEND_RETRY_SEC * 1000) {
            const comp = getComposer();
            if (!comp) { await sleep(2000); continue; }
            if (!inserted) {
                if (comp.textContent.trim().length > 0) {
                    // в композере уже есть черновик — мешать никому не станем; ждём очистки
                    await sleep(3000); continue;
                }
                if (!insertText(comp, prompt)) { await sleep(1500); continue; }
                inserted = true;
                console.log(LOG, 'план вставлен в composer, символов:', prompt.length);
                await sleep(700);
            }
            const btn = clickSendIfPossible();
            if (btn) {
                btn.click();
            } else {
                // агент занят: Enter превращается в очередь/steer согласно настройке сессии
                comp.focus();
                comp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
                comp.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
            }
            await sleep(1500);
            const cleared = getComposer() && getComposer().textContent.trim().length === 0;
            if (cleared) {
                console.log(LOG, 'план отправлен в сессию DSH');
                await sleep(1500); // даём сессии принять ввод
                await gmFetch(SERVER + '/submit_result', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    data: JSON.stringify({ client: CLIENT, response: 'delivered' }),
                });
                return true;
            }
            await sleep(6000);
        }
        throw new Error('не удалось отправить план за отведённое время (composer занят/залочен)');
    }

    async function handleTask(prompt) {
        busy = true;
        try {
            await deliver(prompt);
        } catch (e) {
            console.error(LOG, 'сбой доставки:', (e && e.message) || e);
        } finally { busy = false; }
    }

    setInterval(async () => {
        if (busy) return;
        try {
            const data = await gmFetch(SERVER + '/get_task?client=' + CLIENT);
            if (data && data.prompt) {
                console.log(LOG, 'получен план для доставки, символов:', data.prompt.length);
                handleTask(data.prompt);
            }
        } catch (e) { /* сервер не поднят — ждём */ }
    }, POLL_MS);

    window.__bridgeHealth = () => { gmFetch(SERVER + '/health').then(r => console.log(LOG, r)).catch(() => console.log(LOG, 'сервер недоступен')); };
    console.log(`${LOG} воркер запущен на ${location.host}. Path=${location.pathname}`);
})();
