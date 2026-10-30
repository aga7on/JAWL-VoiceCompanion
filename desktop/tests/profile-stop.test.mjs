import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const appSource = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const htmlSource = await readFile(new URL('../app.html', import.meta.url), 'utf8');

function appFunction(name) {
  let start = appSource.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists`);
  if (appSource.slice(start - 6, start) === 'async ') start -= 6;
  const open = appSource.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < appSource.length; i += 1) {
    if (appSource[i] === '{') depth += 1;
    else if (appSource[i] === '}' && --depth === 0) return appSource.slice(start, i + 1);
  }
  throw new Error(`could not read ${name}`);
}

function profileStopHarness(fetchImpl) {
  const requests = [];
  const statuses = [];
  let now = 0;
  const context = {
    API: {headers: () => ({'Content-Type': 'application/json', 'X-Companion-CSRF': 'csrf-test'})},
    fetch: async (url, options) => {
      requests.push({url, options});
      return fetchImpl(url, options);
    },
    Date: {now: () => now},
    setTimeout: (resolve, delay) => { now += delay; resolve(); return 1; },
    setConn: (kind, text, options = {}) => statuses.push({kind, text, options}),
    window: {jawlDesktop: {acknowledgeProfileStop() { context.acknowledgements += 1; }}},
    acknowledgements: 0,
  };
  let start = appSource.indexOf('async function requestManagedProfileStop(');
  const open = appSource.indexOf('{', start);
  let depth = 0;
  let end = -1;
  for (let i = open; i < appSource.length; i += 1) {
    if (appSource[i] === '{') depth += 1;
    else if (appSource[i] === '}' && --depth === 0) { end = i + 1; break; }
  }
  assert.ok(start >= 0 && end > start, 'managed stop function exists');
  vm.runInNewContext(`let managedProfileStopPending = false;\n${appSource.slice(start, end)}\nglobalThis.invoke = requestManagedProfileStop;`, context);
  return {context, requests, statuses};
}

const jsonResponse = (status, body) => ({status, ok: status >= 200 && status < 300, json: async () => body});

test('renderer keeps UI open until exact launcher acknowledgement and sends CSRF on status GET', async () => {
  const harness = profileStopHarness(async (url) => {
    if (url === '/api/profile/stop') return jsonResponse(202, {ok: true, status: 'stop_requested', request_id: 'request-1'});
    if (harness.requests.filter(request => request.url.endsWith('/status')).length === 1) {
      return jsonResponse(200, {ok: true, status: 'stopping', request_id: 'other-request'});
    }
    return jsonResponse(200, {ok: true, status: 'stopping', request_id: 'request-1'});
  });
  await harness.context.invoke();

  const polls = harness.requests.filter(request => request.url === '/api/profile/stop/status');
  assert.equal(polls.length, 2);
  assert.equal(polls[0].options.headers['X-Companion-CSRF'], 'csrf-test');
  assert.equal(polls[0].options.credentials, 'include');
  assert.equal(harness.context.acknowledgements, 1);
  assert.equal(harness.statuses[0].options.announce, true);
  assert.match(harness.statuses.at(-1).text, /\u0441\u043b\u0443\u0436\u0431\u044b/);
});

test('renderer does not close the app when launcher acknowledgement times out', async () => {
  const harness = profileStopHarness(async (url) => url === '/api/profile/stop'
    ? jsonResponse(202, {ok: true, status: 'stop_requested', request_id: 'request-2'})
    : jsonResponse(403, {error: 'CSRF required'}));
  await harness.context.invoke();

  assert.equal(harness.requests.filter(request => request.url.endsWith('/status')).length, 80);
  assert.equal(harness.context.acknowledgements, 0);
  assert.equal(harness.statuses.at(-1).kind, 'err');
  assert.equal(harness.statuses.at(-1).options.announce, true);
  assert.match(harness.statuses.at(-1).text, /\u043c\u043e\u0436\u0435\u0442 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0442\u044c/);
});

test('connection errors stay visible in compact HUD and are announced', () => {
  assert.match(htmlSource, /id="connection-feedback" role="status" aria-live="assertive"/);
  assert.match(htmlSource, /#connection-feedback\[hidden\] \{ display: none; \}/);
  const dot = {className: ''};
  const label = {textContent: ''};
  const feedback = {textContent: '', hidden: true, dataset: {}, classes: new Set(), classList: {toggle(name, on) {
    if (on) feedback.classes.add(name);
    else feedback.classes.delete(name);
  }}};
  const context = {document: {querySelector(selector) {
    return selector === '#conn-dot' ? dot : selector === '#conn-status' ? label : feedback;
  }}};
  vm.runInNewContext(appFunction('setConn'), context);
  context.setConn('err', 'temporary connection error');
  assert.equal(feedback.hidden, false);
  assert.equal(feedback.textContent, 'temporary connection error');
  assert.equal(feedback.classes.has('error'), true);
  context.setConn('ok', 'connected');
  assert.equal(feedback.hidden, true);
  context.setConn('err', 'stop failed', {announce: true});
  context.setConn('ok', 'background refresh');
  assert.equal(feedback.hidden, false);
  assert.equal(feedback.textContent, 'stop failed');
});
