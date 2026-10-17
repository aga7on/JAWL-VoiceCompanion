import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {CaptureLease, MicInputGate, normalizeMicConfig, uploadUtteranceFor,
  completeMicFlushBoundary, detachMicState, invalidatePendingCapture,
  requireVoiceResponseOk, decideMicTurn} from './voice-input.js';

test('turn heuristic distinguishes Russian overlap, finished questions, and bounded hesitation', () => {
  assert.equal(decideMicTurn({text: 'Угу, понятно.', overlap: true, voicedMs: 300, silenceMs: 400}).action, 'finish_backchannel');
  for (const text of ['Стой!', 'Нет, подожди', 'Открой браузер']) {
    assert.equal(decideMicTurn({text, overlap: true}).action, 'cancel_tts');
  }
  assert.equal(decideMicTurn({text: 'И что теперь?', silenceMs: 400}).action, 'commit_turn');
  for (const text of ['я хотел чтобы', 'ну как бы', 'э-э...', 'давай напишем мод, который']) {
    assert.equal(decideMicTurn({text, silenceMs: 1300}).action, 'hold_turn');
    assert.equal(decideMicTurn({text, silenceMs: 2200}).action, 'commit_turn');
  }
  assert.equal(decideMicTurn({overlap: true, voicedMs: 100, silenceMs: 600}).action, 'hold_turn');
});

const block = (value, length = 2048) => Float32Array.from({length}, () => value);
const rate = 48000;

test('closed gate drops quiet frames and opens with bounded pre-roll on qualified speech', () => {
  const gate = new MicInputGate({openRms: 0.02, closeRms: 0.01, preRollMs: 120, minSpeechMs: 40});
  for (let i = 0; i < 5; i += 1) {
    const rms = i === 4 ? 0.014 : 0.004; // soft consonant stays below the opening threshold
    assert.deepEqual(gate.push(block(rms), rate, i * 42).frames, []);
  }
  const onset = gate.push(block(0.04), rate, 250);
  assert.equal(onset.opened, true);
  assert.equal(onset.frames.length, 4); // bounded history plus the onset block
  assert.ok(onset.frames.some(frame => Math.abs(frame[0] - 0.014) < 0.000001)); // soft lead-in survives qualification
  assert.ok(onset.frames.some(frame => Math.abs(frame[0] - 0.04) < 0.000001));
  assert.equal(onset.voiceActive, true);
});

test('hysteresis keeps short pauses and closes after sustained low energy', () => {
  const gate = new MicInputGate({openRms: 0.02, closeRms: 0.01, minSpeechMs: 20, releaseMs: 100});
  gate.push(block(0.04), rate, 0);
  assert.equal(gate.open, true);
  assert.equal(gate.push(block(0.015), rate, 50).closed, false); // between thresholds
  assert.equal(gate.push(block(0.003), rate, 90).closed, false); // brief pause
  assert.equal(gate.open, true);
  assert.equal(gate.push(block(0.003), rate, 130).closed, false);
  assert.equal(gate.push(block(0.003), rate, 170).closed, true);
  assert.equal(gate.open, false);
});

test('short RU-like low-energy interruption does not lose the following voiced phrase', () => {
  const gate = new MicInputGate({openRms: 0.018, closeRms: 0.009, minSpeechMs: 20, releaseMs: 160});
  const first = gate.push(block(0.035), rate, 0);
  assert.equal(first.opened, true);
  const quietPause = gate.push(block(0.002), rate, 45);
  assert.equal(quietPause.closed, false);
  const resumed = gate.push(block(0.027), rate, 90);
  assert.equal(resumed.frames.length, 1);
  assert.equal(resumed.voiceActive, true);
});

test('settings are bounded and preserve threshold hysteresis', () => {
  const config = normalizeMicConfig({openRms: -1, closeRms: 0.9, silenceMs: 99999, preRollMs: 999});
  assert.equal(config.openRms, 0.001);
  assert.ok(config.closeRms < config.openRms);
  assert.equal(config.silenceMs, 5000);
  assert.equal(config.preRollMs, 500);
});

test('capture lease acquires before media, renews with its id, then releases', async () => {
  const requests = [];
  const lease = new CaptureLease({
    captureId: 'desk-1',
    fetchImpl: async (url, options) => {
      requests.push({url, body: JSON.parse(options.body)});
      const body = requests.length === 1
        ? {ok: true, owner: 'desktop', capture_id: 'desk-1', lease_ttl_ms: 15000, gate_open: 0.03}
        : {ok: true, gate_open: 0.04, config: {openRms: 0.05}};
      return new Response(JSON.stringify(body), {status: 200});
    },
  });
  const acquired = await lease.acquire();
  assert.equal(acquired.config.openRms, 0.03);
  assert.equal(acquired.renewAfterMs, 5000);
  await lease.renew();
  assert.equal(lease.config.openRms, 0.03); // renewal extends the lease; settings apply next start
  await lease.release();
  assert.deepEqual(requests.map(item => item.body.action), ['acquire', 'renew', 'release']);
  assert.ok(requests.every(item => item.body.owner === 'desktop' && item.body.capture_id === 'desk-1'));
  assert.equal(lease.leaseId, null);
});

test('release waits for an in-flight acquire so a late grant cannot outlive stop', async () => {
  let resolveAcquire;
  const actions = [];
  const lease = new CaptureLease({captureId: 'desk-pending', fetchImpl: async (_url, options) => {
    const action = JSON.parse(options.body).action;
    actions.push(action);
    if (action === 'acquire') return new Promise(resolve => { resolveAcquire = resolve; });
    return new Response(JSON.stringify({ok: true}), {status: 200});
  }});
  const acquiring = lease.acquire();
  await new Promise(resolve => setImmediate(resolve));
  const releasing = lease.release();
  assert.deepEqual(actions, ['acquire']);
  resolveAcquire(new Response(JSON.stringify({ok: true, owner: 'desktop',
    capture_id: 'desk-pending', lease_ttl_ms: 15000}), {status: 200}));
  await Promise.all([acquiring, releasing]);
  await lease.release();
  assert.deepEqual(actions, ['acquire', 'release']);
  assert.equal(lease.leaseId, null);
});

test('renewal rejects a successful response for a different capture owner', async () => {
  let actionCount = 0;
  const lease = new CaptureLease({captureId: 'desk-current', fetchImpl: async () => {
    actionCount += 1;
    return new Response(JSON.stringify({ok: true, owner: 'desktop',
      capture_id: actionCount === 1 ? 'desk-current' : 'desk-other'}), {status: 200});
  }});
  let lost;
  lease.onLost = error => { lost = error; };
  await lease.acquire();
  await lease.renew();
  assert.match(lost.message, /renewal response/);
});

test('AudioWorklet retains 2048-sample chunks and flush message compatibility', async () => {
  const source = await readFile(new URL('../frontend/mic-processor.js', import.meta.url), 'utf8');
  const posted = [];
  let Processor;
  class AudioWorkletProcessor {
    constructor() { this.port = {postMessage: (data) => posted.push(data), onmessage: null}; }
  }
  vm.runInNewContext(source, {
    AudioWorkletProcessor,
    registerProcessor: (_name, definition) => { Processor = definition; },
  });
  const processor = new Processor();
  processor.process([[new Float32Array(2048).fill(0.1)]]);
  assert.equal(posted.length, 1);
  assert.equal(posted[0].byteLength, 2048 * Float32Array.BYTES_PER_ELEMENT);
  processor.process([[new Float32Array(320).fill(0.2)]]);
  processor.port.onmessage({data: {type: 'flush'}});
  assert.equal(posted[1].byteLength, 320 * Float32Array.BYTES_PER_ELEMENT);
  assert.equal(posted[2].type, 'flushed');
});

test('worklet flush tail belongs to the old utterance until its boundary is acknowledged', () => {
  const old={sessionId:'old'}; const next={sessionId:'next'};
  const mic={utterance:old,flushDestination:old,inputGate:{lastVoiceAt:100},heard:true};
  assert.equal(uploadUtteranceFor(mic),old);
  const result=completeMicFlushBoundary(mic,100,next);
  assert.equal(result.utterance,old);
  assert.equal(uploadUtteranceFor(mic),next);
  assert.equal(mic.heard,false);
});

test('speech resuming during flush retains the current utterance instead of finalizing it', () => {
  const old={sessionId:'old'};
  const mic={utterance:old,flushDestination:old,inputGate:{lastVoiceAt:200},heard:true};
  assert.equal(completeMicFlushBoundary(mic,100,{sessionId:'next'}).resumed,true);
  assert.equal(mic.utterance,old);
  assert.equal(mic.heard,true);
});

test('old capture teardown and stale pending lease cannot invalidate a replacement', () => {
  const old={active:true}; const next={active:true}; const state={mic:next,micActive:true};
  assert.equal(detachMicState(state,old),false);
  assert.equal(state.mic,next);
  let invalidated=false;
  assert.equal(invalidatePendingCapture({lease:old,pendingLease:next,
    captureGeneration:1,currentGeneration:2,invalidate:()=>{invalidated=true;}}),false);
  assert.equal(invalidated,false);
});

test('hysteresis in-band speech refreshes the endpoint clock', () => {
  const gate=new MicInputGate({openRms:.02,closeRms:.01,minSpeechMs:20});
  gate.push(block(.04),rate,0);
  gate.push(block(.015),rate,1300);
  assert.equal(gate.lastVoiceAt,1300);
});

test('capture HTTP errors never masquerade as successful voice uploads', () => {
  assert.throws(()=>requireVoiceResponseOk({ok:false,status:409},'voice/audio'),/409/);
  assert.equal(requireVoiceResponseOk({ok:true},'voice/audio').ok,true);
});
