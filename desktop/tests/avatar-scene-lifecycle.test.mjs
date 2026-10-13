import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const sceneSource = await readFile(new URL('../app-scene.js', import.meta.url), 'utf8');

function extractFunction(name) {
  const asyncStart = sceneSource.indexOf(`async function ${name}(`);
  const start = asyncStart >= 0 ? asyncStart : sceneSource.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists in app-scene.js`);
  const open = sceneSource.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < sceneSource.length; i += 1) {
    if (sceneSource[i] === '{') depth += 1;
    if (sceneSource[i] === '}' && --depth === 0) return sceneSource.slice(start, i + 1);
  }
  throw new Error(`could not read ${name}`);
}

function makeVrm(name, initialAa) {
  const events = [];
  const values = {aa: initialAa};
  return {
    name,
    scene: {name: `${name}-root`},
    values,
    events,
    expressionManager: {
      setValue: (key, value) => { values[key] = value; events.push(['set', key, value]); },
      update: () => events.push(['update']),
    },
  };
}

test('model handoff clears old and new aa and restores motion before old root disposal', async () => {
  const oldVrm = makeVrm('old', 0.72);
  const nextVrm = makeVrm('next', 0.35);
  const events = [];
  const state = {vrm: oldVrm, lipLevel: 0.64, motionState: 'speaking'};
  const context = {
    state,
    motion: {
      restore: (vrm) => events.push(['motion.restore', vrm]),
      setState: (mode) => events.push(['motion.state', mode]),
    },
    scene: {
      add: (root) => events.push(['scene.add', root]),
      remove: (root) => events.push(['scene.remove', root]),
    },
    VRMUtils: {deepDispose: (root) => events.push(['dispose', root])},
    modelLoadGate: {isCurrent: () => true},
    loadModel: async () => nextVrm,
    captureIdleRestPose: () => {},
    frameCamera: () => {},
    reducedMotion: false,
    physics: {reset: () => {}},
    renderPhysicsControls: () => {},
    listExpressions: () => [],
    setStatus: () => {},
  };
  vm.runInNewContext([
    extractFunction('applyLipSync'), extractFunction('resetLipSync'),
    extractFunction('unload'), extractFunction('swapModel'),
    extractFunction('setMotionState'), extractFunction('setLipLevel'),
  ].join('\n'), context);

  assert.equal(await context.swapModel('replacement', 1), nextVrm);
  assert.equal(state.lipLevel, 0);
  assert.equal(oldVrm.values.aa, 0);
  assert.equal(nextVrm.values.aa, 0);
  assert.equal(state.motionState, 'idle');
  context.setLipLevel(0.9); // a late pre-handoff analyser sample
  assert.equal(state.lipLevel, 0);
  context.setMotionState('speaking');
  context.setLipLevel(0.4);
  assert.equal(state.lipLevel, 0.4);
  context.setMotionState('idle');
  context.setLipLevel(0.8); // late sample after Stop
  assert.equal(state.lipLevel, 0);
  assert.ok(oldVrm.events.some(([type]) => type === 'update'));
  assert.ok(nextVrm.events.some(([type]) => type === 'update'));

  const restoreIndex = events.findIndex(([type, vrm]) => type === 'motion.restore' && vrm === null);
  const removeIndex = events.findIndex(([type, root]) => type === 'scene.remove' && root === oldVrm.scene);
  const disposeIndex = events.findIndex(([type, root]) => type === 'dispose' && root === oldVrm.scene);
  assert.ok(restoreIndex >= 0 && restoreIndex < removeIndex);
  assert.ok(removeIndex < disposeIndex);
});

test('stale and failed model loads leave the current avatar and speech state intact', async () => {
  const oldVrm = makeVrm('current', 0.61);
  const staleVrm = makeVrm('stale', 0.2);
  const state = {vrm: oldVrm, lipLevel: 0.48, motionState: 'speaking'};
  const events = [];
  let currentRequest = false;
  let load = async () => staleVrm;
  const context = {
    state,
    motion: {restore: (vrm) => events.push(['motion.restore', vrm]), setState: () => {}},
    scene: {
      add: (root) => events.push(['scene.add', root]),
      remove: (root) => events.push(['scene.remove', root]),
    },
    VRMUtils: {deepDispose: (root) => events.push(['dispose', root])},
    modelLoadGate: {isCurrent: () => currentRequest},
    loadModel: (...args) => load(...args),
    captureIdleRestPose: () => {},
    frameCamera: () => {},
    reducedMotion: false,
    physics: {reset: () => {}},
    renderPhysicsControls: () => {},
    listExpressions: () => [],
    setStatus: () => {},
  };
  vm.runInNewContext([
    extractFunction('applyLipSync'), extractFunction('resetLipSync'),
    extractFunction('unload'), extractFunction('swapModel'),
  ].join('\n'), context);

  assert.equal(await context.swapModel('stale', 1), null);
  assert.equal(state.vrm, oldVrm);
  assert.equal(state.lipLevel, 0.48);
  assert.equal(state.motionState, 'speaking');
  assert.equal(oldVrm.values.aa, 0.61);
  assert.ok(events.some(([type, root]) => type === 'dispose' && root === staleVrm.scene));
  assert.ok(!events.some(([type]) => type === 'scene.remove' || type === 'motion.restore'));

  currentRequest = true;
  load = async () => { throw new Error('synthetic load failure'); };
  assert.equal(await context.swapModel('broken', 2), null);
  assert.equal(state.vrm, oldVrm);
  assert.equal(state.lipLevel, 0.48);
  assert.equal(state.motionState, 'speaking');
  assert.equal(oldVrm.values.aa, 0.61);
  assert.ok(!events.some(([type]) => type === 'scene.remove' || type === 'motion.restore'));
});
