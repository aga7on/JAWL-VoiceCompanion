const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor() { this.children = []; this.listeners = {}; this.textContent = ''; this.disabled = false; }
  append(...items) { this.children.push(...items); }
  setAttribute() {}
  addEventListener(name, handler) { this.listeners[name] = handler; }
}

function harness(fetch) {
  const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
  const context = vm.createContext({
    document: {createElement: () => new Element(), querySelector: () => null},
    API: {headers: () => ({})}, fetch, console, setVal() {},
  });
  vm.runInContext(source.slice(source.indexOf('const MEMORY_SECTION'), source.indexOf('const memoryKinds')), context);
  return context;
}

test('only selected candidates can be handed off', async () => {
  const calls = [];
  const ctx = harness(async (url, options) => {
    calls.push({url, payload: JSON.parse(options.body)});
    return {ok: true, status: 200, json: async () => ({ok: true})};
  });
  const rejected = ctx.candidateRow({event_id: 'e1', payload: {summary: 'a', importance: 'discard'}}, true);
  assert.equal(rejected.children[2].disabled, true);
  const accepted = ctx.candidateRow({event_id: 'e2', payload: {summary: 'b', importance: 'promote_candidate'}}, true);
  assert.equal(accepted.children[2].disabled, false);
  await accepted.children[2].listeners.click();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/ambient-memory/handoff');
  assert.equal(calls[0].payload.episode_id, 'e2');
  assert.equal(calls[0].payload.confirm, true);
});

test('handoff network failure re-enables the control', async () => {
  const ctx = harness(async () => { throw new Error('offline'); });
  const row = ctx.candidateRow({event_id: 'e1', payload: {summary: 'a', importance: 'promote_candidate'}}, true);
  await row.children[2].listeners.click();
  assert.equal(row.children[2].disabled, false);
  assert.match(row.children[1].textContent, /не удалось/);
});
