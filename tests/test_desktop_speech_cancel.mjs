import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {consumeSpeechStream} from '../desktop/speech-stream.js';

const appSource = await readFile(new URL('../desktop/app.js', import.meta.url), 'utf8');

function deferred() {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return {promise, resolve};
}

function doneResponse() {
  const body = Buffer.from(JSON.stringify({type: 'done', count: 0}));
  return new Response(body, {headers: {'content-type': 'application/x-ndjson'}});
}

function speechHarness(fetchImpl) {
  const requests = [];
  const messages = [];
  let nextId = 0;
  const stopButton = {disabled: true, addEventListener() {}};
  class FakeAudioContext {
    state = 'running';
    currentTime = 0;
    destination = {};
    async decodeAudioData() { return {duration: 0.2}; }
    createAnalyser() {
      return {frequencyBinCount: 4, connect() {}, disconnect() {}, getByteTimeDomainData(data) { data.fill(128); }};
    }
  }
  const context = {
    API: {headers: () => ({'Content-Type': 'application/json', 'X-Companion-CSRF': 'csrf-test'})},
    state: {speechGeneration: 0, speechPlayback: null},
    crypto: {randomUUID: () => `speech-${++nextId}`},
    AbortController,
    AudioContext: FakeAudioContext,
    TextDecoder,
    Uint8Array,
    setTimeout,
    clearTimeout,
    document: {querySelector: selector => selector === '#speech-stop' ? stopButton : null},
    fetch: (url, options) => {
      requests.push({url, options});
      return fetchImpl(url, options);
    },
    performance: {now: () => 10},
    cancelAnimationFrame() {},
    requestAnimationFrame: () => 1,
    addMessage: (...args) => messages.push(args),
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    window: {dispatchEvent() {}, __jawlScene: {setLipLevel() {}, setMotionState() {}}},
  };
  const start = appSource.indexOf('// speech: /api/tts/stream');
  const end = appSource.indexOf('// microphone: the panel', start);
  assert.ok(start >= 0 && end > start, 'speech lifecycle section exists');
  context.consumeSpeechStream = consumeSpeechStream;
  const section = appSource.slice(start, end).replace(
    "await import('./speech-stream.js')",
    'await Promise.resolve({consumeSpeechStream: globalThis.consumeSpeechStream})',
  );
  vm.runInNewContext(`${section}\nglobalThis.speech = {speakFinal, cancelSpeechPlayback};`, context);
  return {speech: context.speech, requests, stopButton, messages};
}

const streamRequest = requests => requests.find(request => request.url === '/api/tts/stream');
const cancelRequests = requests => requests.filter(request => request.url === '/api/tts/cancel');
const payload = request => JSON.parse(request.options.body);

test('stream request carries the playback UUID and the authenticated scope', async () => {
  const harness = speechHarness(async () => doneResponse());
  await harness.speech.speakFinal({text: 'answer'});

  const stream = streamRequest(harness.requests);
  assert.equal(payload(stream).text, 'answer');
  assert.equal(payload(stream).request_id, 'speech-1');
  assert.deepEqual(stream.options.headers, {
    'Content-Type': 'application/json', 'X-Companion-CSRF': 'csrf-test',
  });
  assert.deepEqual(harness.messages, []);
  assert.deepEqual(cancelRequests(harness.requests), []);
});

test('cancel before the first audio event targets the dispatched generation', async () => {
  const pendingStream = deferred();
  const harness = speechHarness((url) => url === '/api/tts/stream' ? pendingStream.promise : Promise.resolve({ok: true}));
  const playback = harness.speech.speakFinal({text: 'not heard yet'});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(streamRequest(harness.requests) !== undefined, true);
  assert.equal(harness.speech.cancelSpeechPlayback(), undefined);
  assert.equal(cancelRequests(harness.requests).length, 1);
  const cancel = cancelRequests(harness.requests)[0];
  assert.deepEqual(payload(cancel), {request_id: 'speech-1'});
  assert.equal(cancel.options.method, 'POST');
  assert.equal(cancel.options.credentials, 'include');
  assert.deepEqual(cancel.options.headers, {
    'Content-Type': 'application/json', 'X-Companion-CSRF': 'csrf-test',
  });
  assert.equal(cancel.options.keepalive, true);
  assert.notEqual(cancel.options.signal, streamRequest(harness.requests).options.signal);
  assert.equal(cancel.options.signal.aborted, false);
  assert.equal(streamRequest(harness.requests).options.signal.aborted, true);

  pendingStream.resolve(doneResponse());
  await playback;
});

test('late cleanup from replaced playback cannot cancel the new playback', async () => {
  const oldStream = deferred();
  const harness = speechHarness((url, options) => {
    if (url === '/api/tts/cancel') return Promise.resolve({ok: true});
    if (payload({options}).text === 'old') return oldStream.promise;
    return Promise.resolve(doneResponse());
  });
  const oldPlayback = harness.speech.speakFinal({text: 'old'});
  await new Promise(resolve => setImmediate(resolve));
  await harness.speech.speakFinal({text: 'new'});
  const streams = harness.requests.filter(request => request.url === '/api/tts/stream');
  assert.equal(payload(streams[0]).request_id, 'speech-1');
  assert.equal(payload(streams[1]).request_id, 'speech-2');
  assert.deepEqual(cancelRequests(harness.requests).map(payload), [{request_id: 'speech-1'}]);

  oldStream.resolve(doneResponse());
  await oldPlayback;
  assert.deepEqual(cancelRequests(harness.requests).map(payload), [{request_id: 'speech-1'}]);
});

test('successful done never sends remote cancellation', async () => {
  const harness = speechHarness(async () => doneResponse());
  await harness.speech.speakFinal({text: 'complete'});
  assert.equal(harness.stopButton.disabled, true);
  assert.deepEqual(cancelRequests(harness.requests), []);
});

test('cancelling before dispatch never sends a stream or remote cancel', async () => {
  const harness = speechHarness(async () => doneResponse());
  const playback = harness.speech.speakFinal({text: 'not dispatched'});
  harness.speech.cancelSpeechPlayback();
  await playback;
  assert.deepEqual(harness.requests, []);
});

test('post-dispatch failure cancels only the failed request', async () => {
  const harness = speechHarness(async url => url === '/api/tts/stream'
    ? new Response('unavailable', {status: 503}) : {ok: true});
  await harness.speech.speakFinal({text: 'failed'});
  assert.deepEqual(cancelRequests(harness.requests).map(payload), [{request_id: 'speech-1'}]);
  assert.equal(harness.messages.length, 1);
  assert.equal(harness.stopButton.disabled, true);
});

test('local stop aborts immediately without waiting for cancel fetch', async () => {
  const pendingStream = deferred();
  const pendingCancel = deferred();
  const harness = speechHarness(url => url === '/api/tts/cancel' ? pendingCancel.promise : pendingStream.promise);
  const playback = harness.speech.speakFinal({text: 'stop now'});
  await new Promise(resolve => setImmediate(resolve));
  const stream = streamRequest(harness.requests);

  const stopResult = harness.speech.cancelSpeechPlayback();
  assert.equal(stopResult, undefined);
  assert.equal(stream.options.signal.aborted, true);
  assert.equal(cancelRequests(harness.requests).length, 1);

  pendingStream.resolve(doneResponse());
  await playback;
});
