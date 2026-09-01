import fs from 'node:fs';
import assert from 'node:assert/strict';

const html = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');

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

console.log('PASS synthetic microphone gate: pre-roll, hysteresis and release');
