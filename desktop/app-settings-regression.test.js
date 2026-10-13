const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.value = '';
    this.disabled = false;
    this.textContent = '';
  }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  async emit(name, event = {}) { return this.listeners.get(name)?.({...event, target: event.target || this}); }
}

function createHarness(fetchHandler = async () => response({ok: true, values: {}})) {
  const list = new Element('div');
  const search = new Element('input');
  const status = new Element('div');
  const alerts = [];
  const requests = [];
  const find = (root, predicate) => {
    if (predicate(root)) return root;
    for (const child of root.children) {
      const match = find(child, predicate);
      if (match) return match;
    }
    return null;
  };
  const document = {
    querySelector(selector) {
      return {'#settings-list': list, '#settings-search': search, '#conn-status': status}[selector]
        || (selector === '#settings-save' ? find(list, (el) => el.id === 'settings-save') : null);
    },
    createElement(tagName) { return new Element(tagName); },
  };
  const context = vm.createContext({
    document,
    API: {headers: () => ({})},
    alert: (message) => alerts.push(message),
    setStatusLine: (message) => { status.textContent = message; },
    fetch: async (...args) => {
      requests.push(args);
      return fetchHandler(...args);
    },
    console,
  });
  const source = fs.readFileSync(path.join(__dirname, 'app-settings.js'), 'utf8');
  vm.runInContext(source, context, {filename: 'app-settings.js'});
  vm.runInContext(`configHub = {
    ok: true,
    revision: 'r1',
    values: {'settings:identity.agent_name': 'Luna', 'settings:llm.temperature': 0.4}
  };
  renderSettings('');`, context);
  return {context, list, search, status, alerts, requests, find};
}

function response(body, {ok = true, status = ok ? 200 : 500} = {}) {
  return {ok, status, json: async () => body};
}

test('dirty edits enable save immediately and survive search rerenders', async () => {
  const h = createHarness();
  const save = () => h.find(h.list, (el) => el.id === 'settings-save');
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');

  assert.equal(save().disabled, true);
  input.value = 'Luna 2';
  await input.emit('input');
  assert.equal(save().disabled, false);
  assert.equal(save().textContent, 'сохранить (1)');

  h.search.value = 'temperature';
  await h.search.emit('input');
  assert.equal(save().disabled, false);
  h.search.value = '';
  await h.search.emit('input');
  const rerenderedInput = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  assert.equal(rerenderedInput.value, 'Luna 2');
});

test('save HTTP failures keep the draft and report failure', async () => {
  const h = createHarness(async () => response({error: 'conflict'}, {ok: false, status: 409}));
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  input.value = 'Edited';
  await input.emit('input');
  await h.find(h.list, (el) => el.id === 'settings-save').emit('click');

  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').disabled, false);
  assert.match(h.status.textContent, /черновики сохранены/);
  assert.equal(h.alerts.length, 1);
});

test('partial save acknowledgements keep unresolved drafts', async () => {
  const h = createHarness(async () => response({ok: true, unknown: ['settings:identity.agent_name']}));
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  input.value = 'Edited';
  await input.emit('input');
  await h.find(h.list, (el) => el.id === 'settings-save').emit('click');

  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').disabled, false);
  assert.match(h.status.textContent, /не сохранено; черновики сохранены/);
});

test('edits made while saving remain dirty after the earlier value is saved', async () => {
  let resolveSave;
  const h = createHarness(async (url) => {
    if (url === '/api/config-hub/save') {
      return new Promise((resolve) => { resolveSave = resolve; });
    }
    return response({ok: true, values: {'settings:identity.agent_name': 'First edit', 'settings:llm.temperature': 0.4}});
  });
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  input.value = 'First edit';
  await input.emit('input');
  const saving = h.find(h.list, (el) => el.id === 'settings-save').emit('click');
  await new Promise((resolve) => setImmediate(resolve));

  input.value = 'Second edit';
  await input.emit('input');
  resolveSave(response({ok: true, revision: 'r2', restart_required: false}));
  await saving;

  const updated = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  assert.equal(updated.value, 'Second edit');
  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').disabled, false);
  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').textContent, 'сохранить (1)');
});

test('restart HTTP failures are visible after a confirmed save', async () => {
  const h = createHarness(async (url) => {
    if (url === '/api/config-hub/save') return response({ok: true, revision: 'r2', restart_required: true});
    if (url === '/api/jawl/restart') return response({error: 'unavailable'}, {ok: false, status: 503});
    return response({ok: true, values: {'settings:identity.agent_name': 'Edited', 'settings:llm.temperature': 0.4}});
  });
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  input.value = 'Edited';
  await input.emit('input');
  await h.find(h.list, (el) => el.id === 'settings-save').emit('click');

  assert.equal(h.requests.some(([url]) => url === '/api/jawl/restart'), true);
  assert.match(h.status.textContent, /сохранено, но перезапуск не удался: HTTP 503/);
  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').disabled, true);
});
