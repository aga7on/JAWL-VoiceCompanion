import test from 'node:test';
import assert from 'node:assert/strict';
import {createAvatarMotionController, createGenerationGate} from './avatar-motion.js';

function makeRig(bones = ['upperChest', 'rightLowerArm', 'rightHand']) {
  const nodes = Object.fromEntries(bones.map((name) => [name, {rotation: {x: 0, y: 0, z: 0}}]));
  return {
    nodes,
    humanoid: {getNormalizedBoneNode: (name) => nodes[name] || null},
  };
}

const step = (controller, rig, from, to, state, speech = 0) => {
  controller.setState(state);
  for (let time = from; time <= to; time += 1 / 60) controller.update(rig, 1 / 60, time, state, speech);
};

test('idle breathing stays bounded and returns to rest when reduced motion is enabled', () => {
  const controller = createAvatarMotionController();
  const rig = makeRig();
  step(controller, rig, 0, 2, 'idle');
  assert.ok(Math.abs(rig.nodes.upperChest.rotation.x) <= 0.019);
  controller.setReducedMotion(true);
  step(controller, rig, 2, 4, 'idle');
  assert.ok(Math.abs(rig.nodes.upperChest.rotation.x) < 1e-8);
});

test('listening, thinking and speaking blend without exceeding motion limits', () => {
  const controller = createAvatarMotionController();
  const rig = makeRig();
  step(controller, rig, 0, 1.5, 'listening');
  assert.ok(rig.nodes.upperChest.rotation.x > 0);
  step(controller, rig, 1.5, 3, 'thinking');
  assert.ok(rig.nodes.upperChest.rotation.x > 0);
  assert.ok(rig.nodes.rightLowerArm.rotation.z < 0);
  step(controller, rig, 3, 4.5, 'speaking', 0.8);
  assert.ok(Math.abs(rig.nodes.upperChest.rotation.x) <= 0.16);
  assert.ok(Math.abs(rig.nodes.rightHand.rotation.x) <= 0.16);
});

test('greeting wave and nod decay fully back to the base pose', () => {
  const controller = createAvatarMotionController();
  const rig = makeRig();
  rig.nodes.upperChest.rotation.x = 0.2;
  rig.nodes.rightLowerArm.rotation.z = 0.1;
  rig.nodes.rightHand.rotation.z = -0.08;
  controller.update(rig, 1 / 60, 0);
  assert.equal(controller.triggerGesture('greeting'), true);
  step(controller, rig, 0, 1.2, 'idle');
  assert.ok(Math.abs(rig.nodes.rightLowerArm.rotation.z) > 0.1);
  assert.ok(Math.abs(rig.nodes.rightHand.rotation.z) > 0.1);
  step(controller, rig, 1.2, 3, 'idle');
  assert.ok(Math.abs(rig.nodes.rightLowerArm.rotation.z - 0.1) < 1e-8);
  assert.ok(Math.abs(rig.nodes.rightHand.rotation.z + 0.08) < 1e-8);

  controller.triggerGesture('nod');
  step(controller, rig, 3, 4.2, 'idle');
  assert.ok(Math.abs(rig.nodes.upperChest.rotation.x - 0.2) < 0.02);
});

test('missing optional bones and reduced-motion gestures are safe', () => {
  const controller = createAvatarMotionController({reducedMotion: true});
  const rig = makeRig([]);
  assert.equal(controller.triggerGesture('wave'), false);
  step(controller, rig, 0, 1, 'speaking', 1);
  assert.deepEqual(rig.nodes, {});
});

test('nod falls back to chest without accumulating across base-pose resets', () => {
  const controller = createAvatarMotionController();
  const rig = makeRig(['chest']);
  controller.triggerGesture('nod');
  let peak = 0;
  for (let frame = 0; frame < 120; frame++) {
    controller.restore(rig);
    rig.nodes.chest.rotation.x = 0.02;
    controller.update(rig, 1 / 60, frame / 60);
    peak = Math.max(peak, rig.nodes.chest.rotation.x);
  }
  assert.ok(peak > 0.1 && peak <= 0.18);
  assert.ok(Math.abs(rig.nodes.chest.rotation.x - 0.02) < 1e-8);
});

test('model replacement and teardown restore offsets on the rig that received them', () => {
  const controller = createAvatarMotionController();
  const previous = makeRig();
  const replacement = makeRig();
  previous.nodes.rightHand.rotation.x = 0.1;
  replacement.nodes.rightHand.rotation.x = -0.2;

  controller.update(previous, 1 / 60, 0.2, 'speaking', 1);
  assert.notEqual(previous.nodes.rightHand.rotation.x, 0.1);

  controller.restore(replacement);
  assert.ok(Math.abs(previous.nodes.rightHand.rotation.x - 0.1) < 1e-8);
  assert.equal(replacement.nodes.rightHand.rotation.x, -0.2);

  controller.update(replacement, 1 / 60, 0.3, 'speaking', 1);
  controller.restore(null);
  assert.ok(Math.abs(replacement.nodes.rightHand.rotation.x + 0.2) < 1e-8);
});

test('generation gate rejects a startup load after a newer wardrobe choice', () => {
  const gate = createGenerationGate();
  const startup = gate.next();
  const userChoice = gate.next();
  assert.equal(gate.isCurrent(startup), false);
  assert.equal(gate.isCurrent(userChoice), true);
});
