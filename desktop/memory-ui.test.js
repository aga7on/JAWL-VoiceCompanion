const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.value = ''; this.dataset = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() {}
  emit(name) { return this.listeners[name]?.({preventDefault() {}}); }
}

function harness() {
  const nodes = Object.fromEntries(['memory-log', 'memory-search', 'memory-kind', 'memory-status', 'memory-limit', 'memory-editor', 'memory-add', 'memory-refresh'].map(id => [id, new Element()]));
  const records = [{memory_key: 'one', revision: 1, kind: 'fact', subject: 'User', predicate: 'likes', value: 'tea'}];
  const calls = [];
  const document = {querySelector: selector => selector === '[data-section="memory"].active' ? {} : nodes[selector.slice(1)], createElement: tag => new Element(tag)};
  const fetch = async (url, options = {}) => {
    if (options.method === 'POST') {
      const payload = JSON.parse(options.body); calls.push(payload);
      if (payload.operation === 'remember') records.push({...payload, memory_key: 'new', revision: 1});
      if (payload.operation === 'revise') Object.assign(records.find(r => r.memory_key === payload.memory_key), payload, {revision: 2});
      if (payload.operation === 'forget') records.splice(records.findIndex(r => r.memory_key === payload.memory_key), 1);
      return {ok: true, json: async () => ({ok: true, redacted: {status: 'redacted'}})};
    }
    const kind = new URL(url, 'http://localhost').searchParams.get('kind');
    return {ok: true, json: async () => ({ok: true, native: true, memory: {memories: records.filter(r => r.kind === kind).map(r => ({...r}))}})};
  };
  const context = vm.createContext({document, fetch, API: {headers: () => ({})}, window: {confirm: () => true}, URL, console, setTimeout, clearTimeout});
  const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf('const memoryKinds'), source.indexOf('async function refreshProactive')), context);
  return {nodes, records, calls, context};
}

test('memory list supports filtering, creating, editing and forgetting', async () => {
  const h = harness();
  await h.context.refreshMemory(true);
  assert.equal(h.nodes['memory-log'].children.length, 1);
  h.nodes['memory-search'].value = 'nothing'; h.nodes['memory-search'].emit('input');
  assert.equal(h.nodes['memory-log'].children.length, 0);
  h.nodes['memory-search'].value = ''; h.nodes['memory-search'].emit('input');
  await h.nodes['memory-log'].children[0].children[3].children[0].emit('click');
  let form = h.nodes['memory-editor'].children[0];
  form.children[3].children[0].value = 'coffee';
  await form.emit('submit');
  assert.equal(h.records[0].value, 'coffee');
  h.nodes['memory-add'].emit('click');
  form = h.nodes['memory-editor'].children[0];
  form.children[1].children[0].value = 'User';
  form.children[2].children[0].value = 'enjoys';
  form.children[3].children[0].value = 'music';
  await form.emit('submit');
  assert.equal(h.records.length, 2);
  await h.nodes['memory-log'].children[0].children[3].children[1].emit('click');
  assert.equal(h.records.length, 1);
  assert.equal(h.nodes['memory-status'].dataset.error, 'false');
  assert.deepEqual(h.calls.map(c => c.operation), ['revise', 'remember', 'forget']);
});

test('changed revision is not overwritten by an old edit', async () => {
  const h = harness();
  await h.context.refreshMemory(true);
  h.nodes['memory-log'].children[0].children[3].children[0].emit('click');
  h.records[0].revision = 2;
  await h.nodes['memory-editor'].children[0].emit('submit');
  assert.equal(h.calls.length, 0);
  assert.equal(h.nodes['memory-status'].dataset.error, 'true');
});

test('forget button performs two-step inline confirmation when clicked with DOM event', async () => {
  const h = harness();
  let confirmCalls = 0;
  h.context.window.confirm = () => { confirmCalls += 1; return true; };
  await h.context.refreshMemory(true);
  const forgetBtn = h.nodes['memory-log'].children[0].children[3].children[1];
  
  // Step 1: First click asks for inline confirmation without calling window.confirm
  await forgetBtn.listeners.click({ target: forgetBtn, currentTarget: forgetBtn });
  assert.equal(forgetBtn.dataset.confirming, 'true');
  assert.equal(forgetBtn.textContent, 'Точно удалить?');
  assert.equal(h.records.length, 1);
  assert.equal(confirmCalls, 0);

  // Step 2: Second click confirms and executes deletion
  await forgetBtn.listeners.click({ target: forgetBtn, currentTarget: forgetBtn });
  assert.equal(forgetBtn.dataset.confirming, 'false');
  assert.equal(h.records.length, 0);
  assert.equal(confirmCalls, 0);
});


