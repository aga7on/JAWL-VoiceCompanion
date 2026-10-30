import test from 'node:test';
import assert from 'node:assert/strict';
import {createVoiceDraftController, VOICE_DRAFT_MAX_CHARS} from './voice-draft.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

function timers() {
  let next = 1;
  const pending = new Map();
  return {
    pending,
    setTimer(callback, delay) {
      const id = next++;
      pending.set(id, {callback, delay});
      return id;
    },
    clearTimer(id) { pending.delete(id); },
    fire(id) {
      const timer = pending.get(id);
      assert.ok(timer, `timer ${id} should be pending`);
      pending.delete(id);
      timer.callback();
    },
  };
}

function snapshot(overrides = {}) {
  return {
    session_id: 'session-1',
    correlation_id: 'utterance-1',
    capture_id: 'capture-1',
    generation: 1,
    active: true,
    heard: true,
    finalizing: false,
    ...overrides,
  };
}

function successful(draft) { return {ok: true, draft, mode: 'streaming'}; }

test('success sends the scoped desktop payload, truncates and deduplicates rendering', async () => {
  const renders = [];
  const calls = [];
  const time = timers();
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: (payload, signal) => {
      calls.push({payload, signal});
      return Promise.resolve(successful('я'.repeat(VOICE_DRAFT_MAX_CHARS + 10)));
    },
    onDraft: (text, identity) => renders.push({text, identity}),
    setTimer: time.setTimer,
    clearTimer: time.clearTimer,
  });

  assert.equal((await controller.tick()).status, 'updated');
  assert.equal((await controller.tick()).status, 'updated');
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0].payload, {
    session_id: 'session-1', correlation_id: 'utterance-1', owner: 'desktop', capture_id: 'capture-1',
  });
  assert.equal(renders.length, 1);
  assert.equal(renders[0].text.length, VOICE_DRAFT_MAX_CHARS);
  assert.deepEqual(renders[0].identity, {
    session_id: 'session-1', correlation_id: 'utterance-1', capture_id: 'capture-1', generation: 1,
  });
  assert.equal(time.pending.size, 0);
});

test('pending request blocks overlap even when later ticks run', async () => {
  const gate = deferred();
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: () => { calls += 1; return gate.promise; },
  });
  const first = controller.tick();
  await Promise.resolve();
  assert.equal((await controller.tick()).status, 'busy');
  assert.equal(calls, 1);
  gate.resolve(successful('часть фразы'));
  assert.equal((await first).status, 'updated');
});

test('generation, session, or capture changes abort and drop stale output', async t => {
  for (const change of [
    {generation: 2}, {session_id: 'session-2'}, {capture_id: 'capture-2'},
  ]) {
    await t.test(JSON.stringify(change), async () => {
      const gate = deferred();
      const renders = [];
      let current = snapshot();
      let signal;
      const controller = createVoiceDraftController({
        getCurrent: () => current,
        request: (_payload, requestSignal) => { signal = requestSignal; return gate.promise; },
        onDraft: text => renders.push(text),
      });
      const first = controller.tick();
      await Promise.resolve();
      current = snapshot(change);
      assert.equal((await controller.tick()).status, 'busy');
      assert.equal(signal.aborted, true);
      gate.resolve(successful('устаревший текст'));
      assert.equal((await first).status, 'stale');
      assert.deepEqual(renders, []);
      assert.equal((await controller.tick()).status, 'updated');
      assert.equal(renders.at(-1), 'устаревший текст');
    });
  }
});

test('stop clears the visible draft and fences a request that ignores abort', async () => {
  const firstGate = deferred();
  const renders = [];
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: () => (++calls === 1 ? Promise.resolve(successful('visible')) : firstGate.promise),
    onDraft: text => renders.push(text),
  });
  await controller.tick();
  const late = controller.tick();
  await Promise.resolve();
  controller.stop();
  assert.deepEqual(renders, ['visible', '']);
  firstGate.resolve(successful('late'));
  assert.equal((await late).status, 'stale');
  assert.deepEqual(renders, ['visible', '']);
  assert.equal((await controller.tick()).status, 'stopped');
});

test('synchronous stop before the dispatch microtask prevents the request', async () => {
  const time = timers();
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: () => { calls += 1; return Promise.resolve(successful('must not dispatch')); },
    setTimer: time.setTimer,
    clearTimer: time.clearTimer,
  });
  const pending = controller.tick();
  controller.stop();
  assert.equal((await pending).status, 'stale');
  assert.equal(calls, 0);
  assert.equal(time.pending.size, 0);
});

test('pause and finalize clear draft and abort their own pending request', async t => {
  for (const method of ['pause', 'finalize']) {
    await t.test(method, async () => {
      const gate = deferred();
      const renders = [];
      let signal;
      const controller = createVoiceDraftController({
        getCurrent: () => snapshot(),
        request: (_payload, requestSignal) => { signal = requestSignal; return gate.promise; },
        onDraft: text => renders.push(text),
      });
      const pending = controller.tick();
      await Promise.resolve();
      controller[method]();
      assert.equal(signal.aborted, true);
      assert.equal((await controller.tick()).status, 'paused');
      gate.resolve(successful('late'));
      assert.equal((await pending).status, 'stale');
      assert.deepEqual(renders, []);
    });
  }
});

test('unavailable response and request errors clear the draft without throwing', async () => {
  const renders = [];
  let next = successful('visible');
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: () => {
      if (next instanceof Error) return Promise.reject(next);
      return Promise.resolve(next);
    },
    onDraft: text => renders.push(text),
  });
  assert.equal((await controller.tick()).status, 'updated');
  next = {ok: true, mode: 'unavailable', draft: ''};
  assert.equal((await controller.tick()).status, 'unavailable');
  assert.deepEqual(renders, ['visible', '']);
  next = new Error('network down');
  assert.equal((await controller.tick()).status, 'error');
  assert.deepEqual(renders, ['visible', '']);
});

test('reset clears and aborts immediately but allows the next request only after settlement', async () => {
  const oldGate = deferred();
  const renders = [];
  let calls = 0;
  let oldSignal;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: (_payload, signal) => {
      calls += 1;
      if (calls === 1) { oldSignal = signal; return oldGate.promise; }
      return Promise.resolve(successful('new'));
    },
    onDraft: text => renders.push(text),
  });
  const old = controller.tick();
  await Promise.resolve();
  controller.reset();
  assert.equal(oldSignal.aborted, true);
  assert.equal((await controller.tick()).status, 'busy');
  assert.equal(calls, 1);
  oldGate.resolve(successful('old'));
  assert.equal((await old).status, 'stale');
  assert.equal((await controller.tick()).status, 'updated');
  assert.deepEqual(renders, ['new']);
});

test('timeout aborts, drops late output and cleans its timer without releasing a stuck slot', async () => {
  const gate = deferred();
  const time = timers();
  const renders = [];
  let signal;
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: (_payload, requestSignal) => { calls += 1; signal = requestSignal; return gate.promise; },
    onDraft: text => renders.push(text),
    timeoutMs: 1234,
    setTimer: time.setTimer,
    clearTimer: time.clearTimer,
  });
  const pending = controller.tick();
  await Promise.resolve();
  const [timerId] = time.pending.keys();
  assert.equal(time.pending.get(timerId).delay, 1234);
  time.fire(timerId);
  assert.equal((await pending).status, 'timeout');
  assert.equal(signal.aborted, true);
  assert.equal(time.pending.size, 0);
  assert.equal((await controller.tick()).status, 'busy');
  assert.equal(calls, 1);
  gate.resolve(successful('late'));
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(renders, []);
  assert.equal(time.pending.size, 0);
});

test('invalid or inactive identity does not issue a request and clears prior draft', async () => {
  const renders = [];
  let current = snapshot();
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => current,
    request: () => { calls += 1; return Promise.resolve(successful('draft')); },
    onDraft: text => renders.push(text),
  });
  assert.equal((await controller.tick()).status, 'updated');
  for (const invalid of [
    null, snapshot({session_id: ''}), snapshot({correlation_id: null}),
    snapshot({capture_id: undefined}), snapshot({generation: NaN}),
    snapshot({heard: false}), snapshot({active: false}), snapshot({finalizing: true}),
  ]) {
    current = invalid;
    assert.equal((await controller.tick()).status, 'inactive');
  }
  assert.equal(calls, 1);
  assert.deepEqual(renders, ['draft', '']);
});

test('timeoutMs must be finite, positive and no greater than 30 seconds', () => {
  const options = {request: () => Promise.resolve(successful('x')), getCurrent: () => snapshot()};
  for (const timeoutMs of [0, -1, NaN, Infinity, 30_001]) {
    assert.throws(() => createVoiceDraftController({...options, timeoutMs}), RangeError);
  }
  assert.doesNotThrow(() => createVoiceDraftController({...options, timeoutMs: 30_000}));
});
