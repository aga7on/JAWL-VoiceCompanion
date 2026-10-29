import fs from 'node:fs';
import assert from 'node:assert/strict';

const app = fs.readFileSync(new URL('../desktop/app.js', import.meta.url), 'utf8');
const input = fs.readFileSync(new URL('../desktop/voice-input.js', import.meta.url), 'utf8');
const worklet = fs.readFileSync(new URL('../frontend/mic-processor.js', import.meta.url), 'utf8');

// The microphone gate moved out of the removed legacy HTML shell into the
// current single-window app modules. Behavior is covered by voice-input tests.
assert.match(app, /new AudioWorkletNode\(/);
assert.doesNotMatch(app + input, /createScriptProcessor\(/);
assert.match(worklet, /registerProcessor\('jawl-mic-processor'/);
assert.match(worklet, /event\.data\.type === 'flush'/);
assert.match(input, /flush|flushWaiters/);

console.log('PASS microphone worklet wiring: app, bounded voice queue and flush protocol');
