import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const appSource = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const speechModule = await import('../speech-stream.js');
const micModule = await import('../voice-input.js');
const draftModule = await import('../voice-draft.js');

function speechHarness(fetchImpl = async () => ndjsonResponse([audioEvent(0), doneEvent(1)])) {
  const stopButton = {disabled: true, listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; }};
  const made = {sources: [], requests: [], disconnected: 0, lip: [], motion: [], diagnostics: [], messages: [], stopButton};
  let speechRequestId = 0;
  class FakeAudioContext {
    state = 'running';
    currentTime = 0;
    destination = {};
    async decodeAudioData(wav) {
      const view = new DataView(wav);
      return {duration: view.getUint32(40, true) / (view.getUint32(28, true) || 32000)};
    }
    createBufferSource() {
      const source = {
        connect: (node) => node,
        disconnect: () => { made.disconnected += 1; },
        start: (at) => { source.startAt = at; made.sources.push(source); },
        stop: () => { source.stopped = true; },
      };
      return source;
    }
    createAnalyser() {
      return {
        frequencyBinCount: 4,
        getByteTimeDomainData: (data) => data.fill(128),
        connect: (node) => node,
        disconnect: () => { made.disconnected += 1; },
      };
    }
  }
  const context = {
    API: {headers: () => ({})},
    state: {speechGeneration: 0, speechPlayback: null},
    fetch: async (...args) => {
      made.requests.push(args);
      return fetchImpl(...args);
    },
    AbortController,
    crypto: {randomUUID: () => `speech-${++speechRequestId}`},
    setTimeout,
    clearTimeout,
    document: {querySelector: selector => selector === '#speech-stop' ? stopButton : null},
    AudioContext: FakeAudioContext,
    cancelAnimationFrame: () => {},
    requestAnimationFrame: () => 1,
    performance: {now: () => 10},
    addMessage: (...args) => made.messages.push(args),
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    window: {
      dispatchEvent: event => made.diagnostics.push(event.detail),
      __jawlScene: {setLipLevel: (level) => made.lip.push(level), setMotionState: (mode) => made.motion.push(mode)},
    },
  };
  const start = appSource.indexOf('// speech: /api/tts/stream');
  const end = appSource.indexOf('// microphone: the panel', start);
  assert.ok(start >= 0 && end > start, 'speech lifecycle section exists');
  context.consumeSpeechStream = speechModule.consumeSpeechStream;
  const section = appSource.slice(start, end).replace(
    "await import('./speech-stream.js')",
    'await Promise.resolve({consumeSpeechStream: globalThis.consumeSpeechStream})',
  );
  vm.runInNewContext(`${section}\nglobalThis.speech = {speakFinal, cancelSpeechPlayback};`, context);
  return {context, made, speech: context.speech};
}

function wavBase64(duration = 0.2) {
  const sampleRate = 32000;
  const sampleCount = Math.round(sampleRate * duration);
  const wav = new ArrayBuffer(44 + sampleCount * 2);
  const view = new DataView(wav);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint32(40, sampleCount * 2, true);
  return Buffer.from(wav).toString('base64');
}

function audioEvent(index, duration = 0.2, extra = {}) {
  return {type: 'audio', index, media_type: 'audio/wav', data_base64: wavBase64(duration), ...extra};
}
const doneEvent = count => ({type: 'done', count});
function ndjsonResponse(events, {trailing = true, splitAt = null} = {}) {
  const text = events.map(event => JSON.stringify(event)).join('\n') + (trailing ? '' : '\n');
  const bytes = Buffer.from(text);
  const chunks = splitAt === null ? [bytes] : [bytes.subarray(0, splitAt), bytes.subarray(splitAt)];
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) if (chunk.length) controller.enqueue(new Uint8Array(chunk));
      controller.close();
    },
  }), {headers: {'content-type': 'application/x-ndjson; charset=utf-8'}});
}
async function waitFor(predicate) {
  for (let i = 0; i < 100; i += 1) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('condition did not become true');
}

function appFunction(name) {
  let start = appSource.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists in app.js`);
  if (appSource.slice(start - 6, start) === 'async ') start -= 6;
  const open = appSource.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < appSource.length; i += 1) {
    if (appSource[i] === '{') depth += 1;
    if (appSource[i] === '}' && --depth === 0) return appSource.slice(start, i + 1);
  }
  throw new Error(`could not read ${name}`);
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

function jsonResponse(data = {}, status = 200) {
  return new Response(JSON.stringify(data), {status, headers: {'content-type': 'application/json'}});
}

function abortable(signal) {
  return new Promise((_resolve, reject) => {
    const abort = () => reject(signal.reason || new Error('aborted'));
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, {once: true});
  });
}

// Run the actual app function bodies, replacing only browser resources,
// module loading and the clock. Lease acquire/renew/release remain real.
function micHarness({fetchImpl, getUserMedia, closeContext} = {}) {
  const made = {requests: [], streams: [], contexts: [], nodes: [], leases: [],
    permissionRequests: [], messages: [], envelopes: [], diagnostics: [], cancellations: 0, now: 0};
  const timers = new Map();
  let timerId = 0;
  const schedule = (callback, delay, interval = 0) => {
    const id = ++timerId;
    timers.set(id, {callback, at: made.now + delay, interval});
    return id;
  };
  const clock = {
    setTimeout: (callback, delay) => schedule(callback, delay),
    setInterval: (callback, delay) => schedule(callback, delay, delay),
    clear: id => timers.delete(id),
    async advance(ms) {
      const until = made.now + ms;
      for (;;) {
        const next = [...timers].filter(([, item]) => item.at <= until)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        const [id, item] = next;
        made.now = item.at;
        if (item.interval) item.at += item.interval;
        else timers.delete(id);
        item.callback();
        await new Promise(resolve => setImmediate(resolve));
      }
      made.now = until;
      await new Promise(resolve => setImmediate(resolve));
    },
  };
  const deadlineSignal = parent => {
    const controller = new AbortController();
    clock.setTimeout(() => controller.abort(new Error('voice request timed out')), 5000);
    return parent ? AbortSignal.any([parent, controller.signal]) : controller.signal;
  };
  const fallbackFetch = (_url, options) => {
    const payload = JSON.parse(options.body);
    return jsonResponse(payload.action ? {
      ok: true, owner: payload.action === 'release' ? null : 'desktop',
      capture_id: payload.capture_id, lease_ttl_ms: 15000,
      gate_open: .02, gate_close: .012, silence_ms: 1200, pre_roll_ms: 120,
    } : {});
  };
  const fetch = async (url, options) => {
    made.requests.push({url, options, payload: JSON.parse(options.body)});
    return fetchImpl ? fetchImpl(url, options, fallbackFetch) : fallbackFetch(url, options);
  };
  class Lease extends micModule.CaptureLease {
    constructor(options) {
      super({...options, fetchImpl: fetch, requestSignal: deadlineSignal});
      made.leases.push(this);
    }
    startRenewal(interval) {
      this.stopRenewal();
      this.released = false;
      this.renewTimer = clock.setInterval(() => { void this.renew(); }, interval);
    }
    stopRenewal() { clock.clear(this.renewTimer); this.renewTimer = null; }
  }
  class Gate extends micModule.MicInputGate {
    push(samples, rate) { return super.push(samples, rate, made.now); }
  }
  const stream = () => {
    const track = {label: 'test mic', stopped: false, stop() { this.stopped = true; }};
    const item = {track, getTracks: () => [track], getAudioTracks: () => [track]};
    made.streams.push(item);
    return item;
  };
  class AudioContext {
    state = 'running';
    sampleRate = 48000;
    audioWorklet = {addModule: async () => {}};
    constructor() { made.contexts.push(this); }
    createMediaStreamSource() { return {connect() {}}; }
    createAnalyser() { return {}; }
    close() { this.state = 'closed'; return closeContext?.(this) || Promise.resolve(); }
  }
  class AudioWorkletNode {
    constructor() {
      this.port = {onmessage: null, postMessage: data => { this.sent.push(data); }};
      this.sent = [];
      made.nodes.push(this);
    }
    samples(frame) { this.port.onmessage({data: frame.buffer}); }
    flushed() { this.port.onmessage({data: {type: 'flushed'}}); }
  }
  let captureId = 0;
  const context = {
    state: {mic: null, micActive: false, voiceSequence: 0}, API: {headers: () => ({})},
    micHelpers: {...micModule, CaptureLease: Lease, MicInputGate: Gate, voiceRequestSignal: deadlineSignal},
    draftHelpers: {createVoiceDraftController: options => draftModule.createVoiceDraftController({
      ...options, setTimer: clock.setTimeout, clearTimer: clock.clear,
    })},
    fetch, AudioContext, AudioWorkletNode, AbortController, AbortSignal, ArrayBuffer, Float32Array,
    performance: {now: () => made.now}, crypto: {randomUUID: () => `capture-${++captureId}`},
    setTimeout: clock.setTimeout, clearTimeout: clock.clear,
    setInterval: clock.setInterval, clearInterval: clock.clear,
    navigator: {mediaDevices: {getUserMedia: constraints => {
      made.permissionRequests.push(constraints);
      return getUserMedia ? getUserMedia(stream, made.permissionRequests.length) : Promise.resolve(stream());
    }}},
    preferredMicId: () => 'selected-device', refreshMicDevices: () => {}, setVal: () => {},
    chatMic: {style: {}}, micState: {textContent: ''},
    cancelSpeechPlayback: () => { made.cancellations += 1; context.state.speechPlayback = null; },
    addMessage: (...args) => made.messages.push(args), handleEnvelope: data => made.envelopes.push(data),
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    window: {__jawlScene: {setMotionState() {}}, dispatchEvent: event => made.diagnostics.push(event.detail)},
    btoa: text => Buffer.from(text, 'binary').toString('base64'),
  };
  const names = ['startMic', 'getCaptureClientId', 'uploadChunk', 'voiceCaptureDiagnostic', 'enqueueMicOperation',
    'finalizeAfterMicUploads', 'micTurnIsCurrent', 'newVoiceUtterance', 'finishUtterance',
    'flushMicWorklet', 'stopMic', 'downsample', 'pcm16Base64', 'updateMicTurn'];
  const source = names.map(appFunction).join('\n').replace(
    "await import('./voice-input.js')", 'await Promise.resolve(globalThis.micHelpers)',
  ).replace("await import('./voice-draft.js')", 'await Promise.resolve(globalThis.draftHelpers)');
  vm.runInNewContext(`let micStartGeneration = 0, micStarting = false, pendingCaptureLease = null;
    ${source}
    globalThis.voice = {${names.join(',')},
      get controls() { return {micStartGeneration, micStarting, pendingCaptureLease}; }};`, context);
  return {context, made, clock, voice: context.voice, makeStream: stream,
    requests: (suffix) => made.requests.filter(item => item.url.endsWith(suffix))};
}

test('actual app draft wiring renders transient text and clears it on finalization and stop', async () => {
  let finishDraft;
  const harness = micHarness({fetchImpl: (url, options, fallback) => {
    if (url.endsWith('/api/voice/draft')) return new Promise(resolve => { finishDraft = resolve; });
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const draft = mic.drafts.tick();
  await waitFor(() => harness.requests('/api/voice/draft').length === 1);
  const request = harness.requests('/api/voice/draft')[0];
  assert.equal(request.payload.session_id, mic.utterance.sessionId);
  assert.equal(request.payload.correlation_id, mic.utterance.correlationId);
  assert.equal(request.payload.capture_id, mic.lease.leaseId);
  finishDraft(jsonResponse({ok: true, mode: 'streaming', draft: 'Проверка '.repeat(100)}));
  await draft;
  assert.ok(harness.context.micState.textContent.startsWith('Слышу (предварительно): '));
  assert.ok(harness.context.micState.textContent.length <= 184);
  assert.equal(harness.made.messages.length, 0);
  const finishing = harness.voice.finishUtterance();
  assert.equal(mic.draftText, '');
  assert.equal(harness.context.micState.textContent, 'Распознаю…');
  await harness.voice.stopMic();
  await finishing;
  assert.equal(harness.context.micState.textContent, 'Микрофон выключен.');
  assert.equal((await mic.drafts.tick()).status, 'stopped');
});

function listeningMic(harness) {
  const mic = harness.context.state.mic;
  mic.heard = true;
  mic.turnGeneration = 1;
  // PCM acceptance is controlled here so these tests isolate the app's session
  // routing; the real gate's speech/noise behavior has its own tests.
  mic.inputGate.push = frame => ({opened: false, frames: [frame]});
  return mic;
}

function loadQueueHelper() {
  const context = {};
  vm.runInNewContext([
    appFunction('enqueueMicOperation'),
    appFunction('finalizeAfterMicUploads'),
    appFunction('micTurnIsCurrent'),
    'globalThis.helpers = {enqueueMicOperation, finalizeAfterMicUploads, micTurnIsCurrent};',
  ].join('\n'), context);
  return context.helpers;
}

test('cancel during TTS fetch aborts the owner and ignores a late stream response', async () => {
  let resolveFetch;
  const harness = speechHarness((url, options) => url === '/api/tts/cancel'
    ? Promise.resolve({ok: true}) : new Promise((resolve) => {
    resolveFetch = resolve;
    options.signal.addEventListener('abort', () => {}, {once: true});
  }));
  const pending = harness.speech.speakFinal({text: 'старый ответ'});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.made.stopButton.disabled, false);
  harness.speech.cancelSpeechPlayback();
  assert.equal(harness.made.stopButton.disabled, true);
  assert.equal(harness.made.requests[0][1].signal.aborted, true);
  resolveFetch(ndjsonResponse([audioEvent(0), doneEvent(1)]));
  await pending;
  assert.equal(harness.made.sources.length, 0);
});

test('one playback owner schedules NDJSON WAV and cancellation stops every source', async () => {
  const harness = speechHarness();
  const task = harness.speech.speakFinal({text: 'ответ'});
  await waitFor(() => harness.made.sources.length === 1);
  const source = harness.made.sources[0];
  assert.ok(source);
  assert.equal(source.startAt, 0.12);
  assert.equal(harness.made.diagnostics[0].state, 'firstscheduled');
  harness.speech.cancelSpeechPlayback();
  await task;
  assert.equal(source.stopped, true);
  assert.equal(harness.made.disconnected, 2);
  assert.equal(harness.context.state.speechPlayback, null);
  assert.deepEqual(harness.made.motion, ['speaking', 'idle']);
  assert.equal(harness.made.diagnostics.at(-1).state, 'cancel');
});

test('stop button uses the single speech cancellation path', async () => {
  const harness = speechHarness();
  const task = harness.speech.speakFinal({text: 'ответ'});
  await waitFor(() => harness.made.sources.length === 1);
  assert.equal(harness.made.stopButton.disabled, false);
  harness.made.stopButton.listeners.click();
  await task;
  assert.equal(harness.made.sources[0].stopped, true);
  assert.equal(harness.made.stopButton.disabled, true);
  assert.equal(harness.made.diagnostics.at(-1).state, 'cancel');
});

test('completed stream emits only bounded playback diagnostics and preview shares the stream path', async () => {
  const harness = speechHarness(() => ndjsonResponse([audioEvent(0), audioEvent(1), doneEvent(2)]));
  const task = harness.speech.speakFinal({text: 'preview text'});
  await waitFor(() => harness.made.sources.length === 2);
  assert.deepEqual(harness.made.diagnostics.map(item => item.state), ['firstscheduled', 'sourcespeak']);
  assert.ok(harness.made.diagnostics.every(item => !('text' in item) && !('audio' in item)));
  assert.equal(harness.made.diagnostics[0].generation, 1);
  for (const source of harness.made.sources) source.onended?.();
  await task;
  assert.equal(harness.made.diagnostics.at(-1).state, 'done');
  assert.equal(harness.made.requests[0][0], '/api/tts/stream');
  assert.match(appSource, /void speakFinal\(\{text\}\)/);
  assert.doesNotMatch(appSource, /\/api\/tts\/synthesize/);
});

test('queued audio uploads remain ordered ahead of utterance finalization', async () => {
  const {enqueueMicOperation, finalizeAfterMicUploads} = loadQueueHelper();
  const mic = {active: true, uploadQueue: {tail: Promise.resolve(), pending: 0}};
  const order = [];
  let releaseOldUpload;
  enqueueMicOperation(mic, () => {
    order.push('old-audio-1');
    return new Promise((resolve) => { releaseOldUpload = resolve; });
  });
  enqueueMicOperation(mic, async () => { order.push('old-audio-2'); });
  let markEndStarted;
  const endStarted = new Promise((resolve) => { markEndStarted = resolve; });
  let releaseResponse;
  const finalization = finalizeAfterMicUploads(mic, () => {
    order.push('end-start');
    markEndStarted();
    return new Promise((resolve) => { releaseResponse = resolve; });
  });
  enqueueMicOperation(mic, async () => { order.push('next-audio'); });
  await mic.uploadQueue.tail;
  assert.deepEqual(order, ['old-audio-1', 'next-audio']);
  releaseOldUpload();
  await endStarted;
  assert.deepEqual(order, ['old-audio-1', 'next-audio', 'old-audio-2', 'end-start']);
  enqueueMicOperation(mic, async () => { order.push('response-audio'); });
  await mic.uploadQueue.tail;
  assert.deepEqual(order, ['old-audio-1', 'next-audio', 'old-audio-2', 'end-start', 'response-audio']);
  releaseResponse({ok: true});
  await finalization;
});

test('audio upload backlog stays bounded', async () => {
  const {enqueueMicOperation} = loadQueueHelper();
  const mic = {active: true, uploadQueue: {tail: Promise.resolve(), pending: 0}};
  const tasks = Array.from({length: 6}, () => enqueueMicOperation(mic, async () => {}, true));
  assert.equal(mic.uploadQueue.pending, 6);
  assert.equal(enqueueMicOperation(mic, async () => {}, true), null);
  await Promise.all(tasks);
  await mic.uploadQueue.tail;
  assert.equal(mic.uploadQueue.pending, 0);
});

test('stop invalidates queued uploads, finalization, and any pending turn response', async () => {
  const {enqueueMicOperation, finalizeAfterMicUploads, micTurnIsCurrent} = loadQueueHelper();
  const mic = {active: true, turnGeneration: 4, uploadQueue: {tail: Promise.resolve(), pending: 0}};
  const context = {state: {mic}};
  const started = [];
  let markStarted;
  const firstStarted = new Promise((resolve) => { markStarted = resolve; });
  let releaseUpload;
  const first = enqueueMicOperation(mic, () => new Promise((resolve) => {
    started.push('in-flight');
    markStarted();
    releaseUpload = resolve;
  }));
  const queued = enqueueMicOperation(mic, async () => { started.push('queued'); });
  const finalization = finalizeAfterMicUploads(mic, async () => { started.push('end'); });
  await firstStarted;
  assert.deepEqual(started, ['in-flight']);
  mic.active = false;
  context.state.mic = null;
  releaseUpload();
  await Promise.all([first, queued, finalization]);
  assert.deepEqual(started, ['in-flight']);

  const currentCheck = vm.runInNewContext(
    `${appFunction('micTurnIsCurrent')}\nglobalThis.check = micTurnIsCurrent;`, context,
  );
  assert.equal(currentCheck(mic, 4), false);
});

test('actual finish flush uploads and ends the old utterance before rotating identity', async () => {
  let releaseAudio;
  const harness = micHarness({fetchImpl: (url, _options, fallback) => {
    if (url.endsWith('/api/voice/audio')) return new Promise(resolve => { releaseAudio = () => resolve(jsonResponse()); });
    return fallback(url, _options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const oldId = mic.utterance.sessionId;
  const oldCorrelation = mic.utterance.correlationId;
  const finishing = harness.voice.finishUtterance();
  await waitFor(() => mic.gate.sent.some(message => message?.type === 'flush'));
  mic.gate.samples(new Float32Array(160).fill(0.03));
  await waitFor(() => harness.requests('/api/voice/audio').length === 1);
  const chunk = harness.requests('/api/voice/audio')[0].payload;
  assert.equal(chunk.session_id, oldId);
  assert.equal(chunk.correlation_id, oldCorrelation);
  mic.gate.flushed();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.requests('/api/voice/end').length, 0);
  releaseAudio();
  await waitFor(() => harness.requests('/api/voice/end').length === 1);
  const end = harness.requests('/api/voice/end')[0].payload;
  assert.equal(end.session_id, oldId);
  assert.equal(end.correlation_id, oldCorrelation);
  assert.notEqual(mic.utterance.sessionId, oldId);
  await finishing;
  await harness.voice.stopMic();
});

test('actual finish preserves the utterance when speech resumes during worklet flush', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const utterance = mic.utterance;
  const finishing = harness.voice.finishUtterance();
  await waitFor(() => mic.gate.sent.some(message => message?.type === 'flush'));
  mic.inputGate.lastVoiceAt += 100;
  mic.gate.samples(new Float32Array(160).fill(0.03));
  mic.gate.flushed();
  await finishing;
  await mic.uploadQueue.tail;
  assert.equal(harness.requests('/api/voice/end').length, 0);
  assert.equal(mic.utterance, utterance);
  assert.equal(mic.heard, true);
  assert.equal(mic.finalizing, false);
  await harness.voice.stopMic();
});

test('actual microphone barge-in cancels playback only and leaves a durable task untouched', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  const task = {status: 'running', cancelCalls: 0};
  harness.context.state.durableTask = task;
  harness.context.state.speechPlayback = {};
  const mic = harness.context.state.mic;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  mic.gate.samples(new Float32Array(160).fill(0.03));
  assert.equal(harness.made.cancellations, 0, 'onset alone does not establish an interruption');
  mic.draftText = 'Стой!';
  await harness.clock.advance(100);
  assert.equal(harness.made.cancellations, 1);
  assert.deepEqual(task, {status: 'running', cancelCalls: 0});
  assert.equal(harness.made.requests.some(item => /cancel|task/i.test(item.url)), false);
  await harness.voice.stopMic();
});

test('short overlapping acknowledgement finalizes under its own identity without cancelling speech', async () => {
  const harness = micHarness({fetchImpl: (url, options, fallback) => url.endsWith('/api/voice/end')
    ? jsonResponse({ok: true, filtered: 'user_backchannel', responses: []}) : fallback(url, options)});
  await harness.voice.startMic();
  const playback = {};
  harness.context.state.speechPlayback = playback;
  const mic = harness.context.state.mic;
  const oldSession = mic.utterance.sessionId;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  mic.gate.samples(new Float32Array(4800).fill(0.03));
  mic.draftText = 'Угу, понятно.';
  await harness.clock.advance(400);
  assert.equal(mic.finalizing, true);
  mic.gate.flushed();
  await waitFor(() => harness.requests('/api/voice/end').length === 1 && !mic.finalizing);
  assert.equal(harness.made.cancellations, 0);
  assert.equal(harness.context.state.speechPlayback, playback);
  const end = harness.requests('/api/voice/end')[0].payload;
  assert.equal(end.session_id, oldSession);
  assert.equal(end.suppress_backchannel, true);
  assert.notEqual(mic.utterance.sessionId, oldSession);
  assert.equal(harness.made.envelopes.length, 0);
  await harness.voice.stopMic();
});

test('noise followed by silence cannot accumulate barge-in duration or cancel a newer playback', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  harness.context.state.speechPlayback = {};
  const mic = harness.context.state.mic;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  mic.gate.samples(new Float32Array(4800).fill(0.03));
  await harness.clock.advance(600);
  assert.equal(harness.made.cancellations, 0);
  assert.equal(mic.voicedMs, 100);
  harness.context.state.speechPlayback = {};
  mic.draftText = 'Стоп';
  await harness.clock.advance(100);
  assert.equal(harness.made.cancellations, 0, 'old draft cannot cancel replacement playback');
  await harness.voice.stopMic();
});

test('sustained voiced audio interrupts when streaming drafts are unavailable', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  harness.context.state.speechPlayback = {};
  const mic = harness.context.state.mic;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  for (let i = 0; i < 6; i += 1) mic.gate.samples(new Float32Array(4800).fill(0.03));
  assert.equal(harness.made.cancellations, 1);
  mic.gate.samples(new Float32Array(4800).fill(0.03));
  assert.equal(harness.made.cancellations, 1);
  await harness.voice.stopMic();
});

test('Russian unfinished draft extends the actual microphone endpoint beyond the configured silence', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  mic.draftText = 'Я хотел чтобы';
  await harness.clock.advance(1300);
  assert.equal(mic.finalizing, false);
  assert.equal(harness.requests('/api/voice/end').length, 0);
  await harness.clock.advance(900);
  assert.equal(mic.finalizing, true);
  await harness.voice.stopMic();
});

test('an older stop cannot clear a replacement microphone start', async () => {
  let releaseClose;
  const harness = micHarness({closeContext: context => context === harnessContext?.made.contexts[0]
    ? new Promise(resolve => { releaseClose = resolve; }) : Promise.resolve()});
  const harnessContext = harness;
  await harness.voice.startMic();
  const oldLease = harness.context.state.mic.lease;
  const stopping = harness.voice.stopMic();
  await harness.voice.startMic();
  const replacement = harness.context.state.mic;
  assert.ok(replacement?.active);
  assert.notEqual(replacement.lease, oldLease);
  releaseClose();
  await stopping;
  assert.equal(harness.context.state.mic, replacement);
  assert.equal(harness.context.state.micActive, true);
  await harness.voice.stopMic();
});

test('lease loss while getUserMedia is pending stops visibly and rejects the late stream', async () => {
  let resolveMedia;
  const harness = micHarness({
    getUserMedia: makeStream => new Promise(resolve => { resolveMedia = () => resolve(makeStream()); }),
    fetchImpl: async (url, options, fallback) => {
      const payload = JSON.parse(options.body);
      if (url.endsWith('/api/voice/capture') && payload.action === 'renew') return jsonResponse({}, 409);
      return fallback(url, options);
    },
  });
  const starting = harness.voice.startMic();
  await waitFor(() => harness.made.permissionRequests.length === 1);
  const lease = harness.made.leases[0];
  await lease.renew();
  await waitFor(() => harness.made.requests.some(item => item.payload.action === 'release'));
  resolveMedia();
  await starting;
  assert.equal(harness.context.state.mic, null);
  assert.match(harness.made.messages.at(-1)[1], /Захват остановлен.*409/);
  assert.ok(harness.made.streams[0].track.stopped);
});

test('a lost acquire response is followed by a best-effort release', async () => {
  const harness = micHarness({fetchImpl: async (url, options, fallback) => {
    const payload = JSON.parse(options.body);
    if (url.endsWith('/api/voice/capture') && payload.action === 'acquire') throw new Error('response lost');
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  assert.deepEqual(harness.made.requests.map(item => item.payload.action), ['acquire', 'release']);
  assert.equal(harness.made.permissionRequests.length, 0);
  assert.match(harness.context.micState.textContent, /Микрофон недоступен: response lost/);
});

test('actual audio upload backlog is capped and overflow stops capture visibly', async () => {
  const harness = micHarness({fetchImpl: (url, options, fallback) => {
    if (url.endsWith('/api/voice/audio')) return new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('aborted')), {once: true});
    });
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  harness.voice.uploadChunk(new Float32Array(160), 48000);
  await waitFor(() => harness.requests('/api/voice/audio').length === 1);
  for (let i = 0; i < 6; i += 1) harness.voice.uploadChunk(new Float32Array(160), 48000);
  await waitFor(() => harness.context.state.mic === null);
  assert.equal(mic.uploadQueue.pending, 6);
  assert.equal(harness.requests('/api/voice/audio').length, 1);
  assert.ok(harness.made.messages.some(([, message]) => /аудиоканал не успевает/.test(message)));
  assert.equal(harness.context.state.micActive, false);
  assert.equal(harness.made.diagnostics[0].reason, 'upload_backpressure');
});

test('HTTP 409 from an actual audio chunk reports failure and stops capture', async () => {
  const harness = micHarness({fetchImpl: async (url, options, fallback) => {
    if (url.endsWith('/api/voice/audio')) return jsonResponse({error: 'capture conflict'}, 409);
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  harness.voice.uploadChunk(new Float32Array(160), 48000);
  await waitFor(() => harness.context.state.mic === null);
  assert.equal(mic.active, false);
  assert.equal(harness.context.state.micActive, false);
  assert.ok(harness.made.messages.some(([, message]) => /Захват остановлен: voice\/audio failed \(HTTP 409\)/.test(message)));
  assert.equal(harness.context.micState.textContent, 'Микрофон выключен.');
  assert.equal(harness.made.diagnostics[0].reason, 'http_failure');
  assert.equal(harness.made.diagnostics[0].status, 409);
});

test('audio fetch failure emits bounded redacted evidence before capture teardown', async () => {
  const harness = micHarness({fetchImpl: (url, options, fallback) => {
    if (url.endsWith('/api/voice/audio')) throw new TypeError('PRIVATE_CAPTURE_SENTINEL');
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  harness.voice.uploadChunk(new Float32Array(160), 48000);
  await waitFor(() => harness.context.state.mic === null);
  const evidence = harness.made.diagnostics[0];
  assert.equal(evidence.reason, 'transport_failure');
  assert.equal(evidence.context_state, 'running');
  assert.equal(evidence.active, true);
  assert.equal(evidence.status, null);
  assert.ok(!JSON.stringify(evidence).includes('PRIVATE_CAPTURE_SENTINEL'));
  for (const key of ['capture_id', 'pcm16_base64', 'transcript', 'message']) assert.ok(!(key in evidence));
  assert.equal(mic.active, false);
});

test('HTTP 409 from actual turn finalization reports failure and stops capture', async () => {
  const harness = micHarness({fetchImpl: async (url, options, fallback) => {
    if (url.endsWith('/api/voice/end')) return jsonResponse({error: 'capture conflict'}, 409);
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const finishing = harness.voice.finishUtterance();
  await waitFor(() => mic.gate.sent.some(message => message?.type === 'flush'));
  mic.gate.flushed();
  await finishing;
  assert.equal(harness.context.state.mic, null);
  assert.equal(harness.context.state.micActive, false);
  assert.ok(harness.made.messages.some(([, message]) => /Голосовой ход не завершился: voice\/end failed \(HTTP 409\)/.test(message)));
  assert.equal(harness.context.micState.textContent, 'Микрофон выключен.');
});
