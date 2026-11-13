// ==UserScript==
// @name         JAWL Bridge — Console MCP (прямой доступ к вкладкам)
// @namespace    jawl-seniors-bridge
// @version      1.0
// @description  Универсальный воркер: забирает команды с 127.0.0.1:5051, исполняет в контексте страницы (eval/DOM/клики/печать/навигация) и возвращает результат агенту. Даёт внешнему локальному оркестратору «руки».
// @match        https://chatgpt.com/*
// @match        https://chat.com/*
// @match        https://arena.ai/*
// @match        https://*.lmarena.ai/*
// @match        https://chat.lmsys.org/*
// @match        http://127.0.0.1:3080/*
// @match        http://localhost:3080/*
// @grant        unsafeWindow
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
    'use strict';

    // ----- НАСТРОЙКИ ------------------------------------------------------
    const SERVER = 'http://127.0.0.1:5051';
    const POLL_MS = 2000;
    const LOG = '[MCP]';
    // ----------------------------------------------------------------------

    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const vis = el => !!el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;

    function tabName() {
        if (/3080/.test(location.host)) return 'dsh';
        if (/(^|\.)chatgpt\.com$|^chat\.com$/.test(location.hostname)) return 'chatgpt';
        if (location.hostname.endsWith('arena.ai') || location.hostname.includes('lmsys')) return 'arena';
        return null;
    }
    const TAB = tabName();
    if (!TAB) return; // чужие хосты молча пропускаем

    function gmFetch(url, opts = {}) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                url, method: opts.method || 'GET', headers: opts.headers || {},
                data: opts.data || null, timeout: 15000,
                onload: r => { try { resolve(JSON.parse(r.responseText)); } catch (e) { reject(e); } },
                onerror: () => reject(new Error('network')),
                ontimeout: () => reject(new Error('timeout')),
            });
        });
    }

    // Команды исполняются в контексте страницы через unsafeWindow.eval.
    function pageEval(code) {
        return new Promise(resolve => {
            try {
                const p = unsafeWindow.eval(`(async () => { ${code} })()`);
                Promise.resolve(p).then(
                    v => resolve({ ok: true, data: v === undefined ? null : v }),
                    e => resolve({ ok: false, error: String(e && e.message || e) })
                );
            } catch (e) {
                resolve({ ok: false, error: String(e && e.message || e) });
            }
        });
    }

    async function runCommand(cmd, args) {
        switch (cmd) {
            case 'ping':
                return { tab: TAB, url: location.href, title: document.title,
                         ready: document.readyState, ts: Date.now() };
            case 'eval':
                if (typeof (args && args.code) !== 'string') throw new Error('нужен args.code');
                return await pageEval(args.code);
            case 'dom': {
                if (!args || !args.sel) throw new Error('нужен args.sel');
                const els = Array.from(document.querySelectorAll(args.sel));
                const items = els.slice(0, (args.limit || 8)).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    id: el.id || undefined,
                    cls: (el.className && String(el.className).slice(0, 120)) || undefined,
                    vis: vis(el),
                    text: (el.innerText || '').slice(0, (args.textChars || 300)),
                    html: (args.html ? (el.outerHTML || '').slice(0, 1500) : undefined),
                    aria: el.getAttribute('aria-label') || undefined,
                    disabled: el.disabled === true ? true : undefined,
                }));
                return { count: els.length, items };
            }
            case 'click': {
                if (!args || !args.sel) throw new Error('нужен args.sel');
                const els = Array.from(document.querySelectorAll(args.sel)).filter(vis);
                if (!els.length) return { clicked: false, reason: 'нет видимых элементов' };
                const minions = (args.index !== undefined) ? els[args.index] : els[els.length - 1];
                minions.scrollIntoView({ block: 'center' });
                minions.click();
                return { clicked: true, tag: minions.tagName.toLowerCase(),
                         aria: minions.getAttribute('aria-label') || undefined };
            }
            case 'type': {
                if (!args || !args.sel || typeof args.text !== 'string')
                    throw new Error('нужны args.sel и args.text');
                const els = Array.from(document.querySelectorAll(args.sel)).filter(vis);
                if (!els.length) return { typed: false, reason: 'нет видимого элемента' };
                const el = (args.index !== undefined) ? els[args.index] : els[els.length - 1];
                el.focus();
                if (el.isContentEditable) {
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, args.text);
                } else {
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value').set;
                    setter.call(el, args.text);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }
                return { typed: true };
            }
            case 'key': {
                const comp = document.querySelector(args && args.sel);
                if (!comp) throw new Error('элемент для клавиши не найден');
                comp.focus();
                comp.dispatchEvent(new KeyboardEvent('keydown',
                    { key: args.key || 'Enter', code: args.code || 'Enter', bubbles: true, cancelable: true }));
                comp.dispatchEvent(new KeyboardEvent('keyup',
                    { key: args.key || 'Enter', code: args.code || 'Enter', bubbles: true, cancelable: true }));
                return { sent: true };
            }
            case 'navigate':
                if (!args || !args.url) throw new Error('нужен args.url');
                location.href = args.url;
                return { navigating: args.url };
            case 'sleep':
                await sleep(Math.min((args && args.ms) || 1000, 30000));
                return { slept: (args && args.ms) || 1000 };
            default:
                throw new Error(`неизвестная команда: ${cmd}`);
        }
    }

    let busy = false;
    setInterval(async () => {
        if (busy) return;
        try {
            const job = await gmFetch(`${SERVER}/jobs?tab=${TAB}`);
            if (!job || !job.cmd) return;
            busy = true;
            console.log(LOG, `команда агента: ${job.cmd}`, job.args || {});
            let result;
            try {
                const data = await runCommand(job.cmd, job.args || {});
                result = { id: job.id, ok: true, data, error: null };
            } catch (e) {
                result = { id: job.id, ok: false, data: null, error: String((e && e.message) || e) };
            }
            await gmFetch(SERVER + '/job_result', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                data: JSON.stringify(result),
            });
        } catch (e) { /* сервер не поднят — тихо ждём */ }
        finally { busy = false; }
    }, POLL_MS);

    console.log(`${LOG} воркер команд запущен. tab=${TAB}, url=${location.pathname}`);
})();
