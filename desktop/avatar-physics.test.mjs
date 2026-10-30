import test from 'node:test';
import assert from 'node:assert/strict';
import {createAvatarPhysicsController} from './avatar-physics.js';

const NAMES = [
  'jawlie_soft_chest_l', 'jawlie_soft_chest_r',
  'jawlie_soft_hip_l', 'jawlie_soft_hip_r',
  'jawlie_cloth_hem_l', 'jawlie_cloth_hem_r',
  'jawlie_hair_tail_l', 'jawlie_hair_tail_r',
];

function makeNode(name) {
  return {name, position: {x: 0, y: 0, z: 0}, rotation: {x: 0, y: 0, z: 0}, children: []};
}

function makeRig(names = NAMES, withTorso = true) {
  const nodes = Object.fromEntries([...names, 'unlisted_helper', 'native_spring_bone'].map((name) => [name, makeNode(name)]));
  const scene = {children: Object.values(nodes)};
  const torso = withTorso ? {
    hips: {position: {x: 0, y: 0, z: 0}, rotation: {x: 0, y: 0, z: 0}},
    chest: {position: {x: 0, y: 0, z: 0}, rotation: {x: 0, y: 0, z: 0}},
  } : {};
  return {
    nodes,
    scene,
    humanoid: {getNormalizedBoneNode: (name) => torso[name] || null},
    torso,
  };
}

function frame(controller, rig, elapsed, state = 'speaking', speechLevel = 0) {
  controller.restore(rig);
  rig.torso.chest.rotation.x = Math.sin(elapsed * 3) * 0.03;
  controller.update(rig, 1 / 60, elapsed, {state, speechLevel});
}

function offset(node, base, key) {
  return node[key].x - base[key].x;
}

test('binds and reports only the eight supported custom nodes', () => {
  const controller = createAvatarPhysicsController();
  const rig = makeRig();
  controller.reset(rig);

  const stats = controller.getStats();
  assert.equal(stats.supported, true);
  assert.equal(stats.boundNodes, 8);
  assert.deepEqual(stats.boundNodeNames, NAMES);
  assert.equal(stats.intensity, 0.5);
});

test('adds bounded offsets after a fresh base pose and does not accumulate across frames', () => {
  const controller = createAvatarPhysicsController();
  const rig = makeRig();
  const baseRotation = {x: 0.12, y: -0.04, z: 0.03};
  const basePosition = {x: 0.1, y: 0.2, z: -0.1};

  for (let i = 0; i < 180; i++) {
    controller.restore(rig);
    Object.assign(rig.nodes.jawlie_hair_tail_l.rotation, baseRotation);
    Object.assign(rig.nodes.jawlie_hair_tail_l.position, basePosition);
    rig.torso.chest.rotation.x = i === 30 ? 0.08 : Math.sin(i / 7) * 0.03;
    controller.update(rig, 1 / 60, i / 60, {state: 'speaking', speechLevel: i % 40 < 20 ? 0.35 : 0});
    assert.ok(Math.abs(rig.nodes.jawlie_hair_tail_l.rotation.x - baseRotation.x) <= 0.018);
    assert.ok(Math.abs(rig.nodes.jawlie_hair_tail_l.position.x - basePosition.x) <= 0.0022);
  }

  controller.restore(rig);
  assert.deepEqual(rig.nodes.jawlie_hair_tail_l.rotation, baseRotation);
  assert.deepEqual(rig.nodes.jawlie_hair_tail_l.position, basePosition);
  assert.deepEqual(rig.nodes.unlisted_helper.rotation, {x: 0, y: 0, z: 0});
  assert.deepEqual(rig.nodes.native_spring_bone.position, {x: 0, y: 0, z: 0});
});

test('spring response damps back to rest after a speech-level impulse', () => {
  const controller = createAvatarPhysicsController();
  const rig = makeRig();
  controller.reset(rig);
  controller.update(rig, 1 / 60, 0, {state: 'speaking', speechLevel: 0});
  controller.update(rig, 1 / 60, 1 / 60, {state: 'speaking', speechLevel: 1});
  const peak = Math.abs(rig.nodes.jawlie_soft_chest_l.rotation.x);
  assert.ok(peak > 0);
  for (let i = 2; i < 420; i++) frame(controller, rig, i / 60, 'idle', 0);
  controller.restore(rig);
  assert.ok(Math.abs(rig.nodes.jawlie_soft_chest_l.rotation.x) < 1e-6);
  assert.ok(Math.abs(rig.nodes.jawlie_soft_chest_l.position.y) < 1e-6);
});

test('normalized torso acceleration drives secondary motion without a speech signal', () => {
  const controller = createAvatarPhysicsController();
  const rig = makeRig();
  controller.reset(rig);
  controller.update(rig, 1 / 60, 0, {state: 'idle', speechLevel: 0});
  rig.torso.chest.rotation.x = 0.03;
  controller.update(rig, 1 / 60, 1 / 60, {state: 'idle', speechLevel: 0});
  rig.torso.chest.rotation.x = 0.03;
  controller.update(rig, 1 / 60, 2 / 60, {state: 'idle', speechLevel: 0});
  assert.ok(Math.abs(rig.nodes.jawlie_soft_chest_l.rotation.x) > 0);
});

test('large frame deltas clamp work and keep every transform within its bound', () => {
  const controller = createAvatarPhysicsController({intensity: 1});
  const rig = makeRig();
  controller.reset(rig);
  controller.update(rig, 50, 0, {state: 'speaking', speechLevel: 1});
  for (const name of NAMES) {
    for (const axis of ['x', 'y', 'z']) {
      assert.ok(Math.abs(rig.nodes[name].rotation[axis]) <= 0.018 + 1e-12);
      assert.ok(Math.abs(rig.nodes[name].position[axis]) <= 0.0022 + 1e-12);
    }
  }
});

test('disabled and reduced-motion settings synchronously restore exact base transforms', () => {
  const controller = createAvatarPhysicsController();
  const rig = makeRig();
  controller.reset(rig);
  controller.update(rig, 1 / 60, 0, {state: 'speaking', speechLevel: 0});
  controller.update(rig, 1 / 60, 1 / 60, {state: 'speaking', speechLevel: 1});
  const baseX = 0.17;
  controller.restore(rig);
  rig.nodes.jawlie_soft_hip_l.rotation.x = baseX;
  controller.update(rig, 1 / 60, 2 / 60, {state: 'speaking', speechLevel: 0.8});
  controller.setReducedMotion(true);
  assert.equal(rig.nodes.jawlie_soft_hip_l.rotation.x, baseX);
  assert.equal(controller.getStats().reducedMotion, true);

  controller.setReducedMotion(false);
  controller.update(rig, 1 / 60, 3 / 60, {state: 'speaking', speechLevel: 1});
  controller.setEnabled(false);
  assert.equal(rig.nodes.jawlie_soft_hip_l.rotation.x, baseX);
  assert.equal(controller.getStats().enabled, false);
});

test('model reset remaps nodes and cleanup restores then releases bindings', () => {
  const controller = createAvatarPhysicsController();
  const first = makeRig();
  const second = makeRig(['jawlie_hair_tail_r']);
  controller.reset(first);
  controller.update(first, 1 / 60, 0, {state: 'speaking', speechLevel: 0});
  controller.update(first, 1 / 60, 1 / 60, {state: 'speaking', speechLevel: 1});
  controller.update(second, 1 / 60, 2 / 60, {state: 'idle', speechLevel: 0});
  assert.equal(controller.getStats().boundNodes, 1);
  assert.deepEqual(first.nodes.jawlie_hair_tail_l.rotation, {x: 0, y: 0, z: 0});
  assert.deepEqual(first.nodes.jawlie_hair_tail_l.position, {x: 0, y: 0, z: 0});

  controller.update(second, 1 / 60, 3 / 60, {state: 'speaking', speechLevel: 0});
  controller.update(second, 1 / 60, 4 / 60, {state: 'speaking', speechLevel: 1});
  controller.cleanup();
  assert.equal(controller.getStats().supported, false);
  assert.deepEqual(second.nodes.jawlie_hair_tail_r.rotation, {x: 0, y: 0, z: 0});
});

test('missing helpers report unsupported and paused state restores without drift', () => {
  const controller = createAvatarPhysicsController();
  const rig = makeRig([], false);
  controller.reset(rig);
  assert.deepEqual(controller.getStats().supported, false);
  assert.equal(controller.getStats().boundNodes, 0);

  const supported = makeRig(['jawlie_cloth_hem_l']);
  controller.reset(supported);
  controller.update(supported, 1 / 60, 0, {state: 'speaking', speechLevel: 0});
  controller.update(supported, 1 / 60, 1 / 60, {state: 'speaking', speechLevel: 1});
  controller.update(supported, 1 / 60, 2 / 60, {state: 'paused', speechLevel: 1});
  assert.equal(supported.nodes.jawlie_cloth_hem_l.rotation.x, 0);
  assert.equal(controller.getStats().paused, true);
});
