import fs from 'node:fs';
import assert from 'node:assert/strict';

const html = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
const worklet = fs.readFileSync(new URL('../frontend/mic-processor.js', import.meta.url), 'utf8');

assert.match(html, /AudioWorkletNode/);
assert.doesNotMatch(html, /createScriptProcessor/);
assert.match(html, /requestMicWorkletFlush/);
assert.match(worklet, /registerProcessor\('jawl-mic-processor'/);
assert.match(worklet, /event\.data\.type === 'flush'/);

function extractFunction(name) {
  const marker = `function ${name}(`;
  const start = html.indexOf(marker);
  assert.notEqual(start, -1, `missing ${name}`);
  const bodyStart = html.indexOf('{', start);
  let depth = 0;
  let inString = null;
  let escaped = false;
  for (let index = bodyStart; index < html.length; index += 1) {
    const character = html[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (character === '\\') escaped = true;
      else if (character === inString) inString = null;
      continue;
    }
    if (character === '"' || character === "'" || character === '`') {
      inString = character;
      continue;
    }
    if (character === '{') depth += 1;
    if (character === '}' && --depth === 0) return html.slice(start, index + 1);
  }
  throw new Error(`unterminated ${name}`);
}

const gate = new Function(
  `${extractFunction('clamp')}\n${extractFunction('appendGatePreRoll')}\n${extractFunction('passThroughMicGate')}\nreturn passThroughMicGate;`
)();

const active = {
  gate: {
    threshold: 0.035,
    open: false,
    silentBlocks: 0,
    releaseBlocks: 3,
    preRoll: [],
    preRollLimit: 3,
    calibration: null,
  },
};

let result = gate(active, [0.01, 0.01], 0.01);
assert.equal(result.capture, undefined, 'closed gate must reject quiet input');
assert.deepEqual(active.gate.preRoll, [0.01, 0.01]);

result = gate(active, [0.2, 0.2], 0.2);
assert.equal(result.capture, true, 'speech must open the gate');
assert.deepEqual(result.samples, [0.01, 0.01], 'speech keeps the pre-roll');
assert.equal(active.gate.open, true);

result = gate(active, [0.02], 0.02);
assert.equal(result.capture, true, 'hysteresis keeps a recently opened gate alive');
assert.equal(active.gate.open, true);
gate(active, [0.01], 0.01);
result = gate(active, [0.01], 0.01);
assert.equal(result.capture, true, 'release keeps the last bounded tail');
assert.equal(active.gate.open, false);
result = gate(active, [0.01], 0.01);
assert.equal(result.capture, undefined, 'closed gate must stop forwarding noise');

const queue = new Function(
  `const MAX_PENDING_AUDIO_CHUNKS = 8;
  const micGateStatus = { textContent: '' };
  const pcm16Base64 = () => 'stub';
  const downsample = samples => samples;
  let voiceQueue = Promise.resolve();
  const apiPost = async () => ({ ok: true, json: async () => ({ responses: [] }) });
  const addMessage = () => {};
  const speak = () => {};
  const document = { querySelector: () => ({ textContent: '' }) };
  ${extractFunction('queueVoiceChunk')}
  return { queueVoiceChunk: queueVoiceChunk, micGateStatus: micGateStatus };`
)();

const saturated = { pendingUploads: 7, droppedChunks: 0 };
assert.equal(queue.queueVoiceChunk([0.2, 0.2], 16000, 'synthetic', saturated), true, 'upload accepted below the cap');
assert.equal(saturated.pendingUploads, 8, 'accepted upload must reserve a slot');
assert.equal(queue.queueVoiceChunk([0.2, 0.2], 16000, 'synthetic', saturated), false, 'saturated queue must reject the chunk');
assert.equal(saturated.pendingUploads, 8, 'rejected chunk must not reserve a slot');
assert.equal(saturated.droppedChunks, 1, 'rejected chunk must be counted as dropped');
assert.match(queue.micGateStatus.textContent, /dropped 1/, 'drop must surface in the mic status line');

console.log('PASS synthetic microphone gate: pre-roll, hysteresis, release and backpressure');
