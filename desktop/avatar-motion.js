// Small additive motion layer. Restore its offsets before writing the next
// base pose; no Three.js dependency keeps the motion math testable alone.
const MODES = new Set(['idle', 'listening', 'speaking']);
const GESTURES = {wave: 2.4, greeting: 2.8, nod: 0.9};
const LIMITS = {upperChestX: 0.16, upperChestZ: 0.07, forearmZ: 0.72, handZ: 0.62, handX: 0.16};
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const smoothstep = (value) => {
  const t = clamp(value, 0, 1);
  return t * t * (3 - 2 * t);
};

export function createGenerationGate() {
  let generation = 0;
  return {
    next: () => ++generation,
    isCurrent: (candidate) => candidate === generation,
  };
}

export function createAvatarMotionController({reducedMotion = false} = {}) {
  let mode = 'idle';
  let reduced = Boolean(reducedMotion);
  let elapsed = 0;
  let gesture = null;
  let currentVrm = null;
  const weights = {idle: 1, listening: 0, speaking: 0};
  const applied = new Map();

  function setState(next) {
    if (MODES.has(next)) mode = next;
  }

  function triggerGesture(name) {
    if (reduced || !GESTURES[name]) return false;
    gesture = {name, start: elapsed, duration: GESTURES[name]};
    return true;
  }

  function setReducedMotion(value) {
    reduced = Boolean(value);
    if (reduced) {
      gesture = null;
      for (const key of Object.keys(weights)) weights[key] = 0;
    }
  }

  function restore(vrm) {
    if (vrm !== currentVrm) {
      // The previous rig may still be alive during a swap (or be inspected
      // after teardown). Remove our last frame from its original nodes before
      // dropping ownership; never transfer an offset to the replacement rig.
      for (const {node, axes} of applied.values()) {
        for (const [axis, value] of Object.entries(axes)) node.rotation[axis] -= value;
      }
      currentVrm = vrm;
      applied.clear();
      return;
    }
    // Remove only this controller's last-frame offsets. This preserves the
    // model pose and any other system's contribution to these same channels.
    for (const {node, axes} of applied.values()) {
      for (const [axis, value] of Object.entries(axes)) node.rotation[axis] -= value;
    }
    applied.clear();
  }

  function update(vrm, delta, time, nextMode = mode, speechLevel = 0) {
    const safeDelta = clamp(Number(delta) || 0, 0, 0.05);
    elapsed = Math.max(elapsed, Number(time) || 0);
    setState(nextMode);
    restore(vrm);
    const humanoid = vrm?.humanoid;
    if (!humanoid) return;
    const chest = humanoid.getNormalizedBoneNode('chest');

    const speaking = Number.isFinite(Number(speechLevel)) && Number(speechLevel) > 0.04;
    const target = reduced
      ? {idle: 0, listening: 0, speaking: 0}
      : {idle: mode === 'idle' && !speaking ? 1 : 0,
        listening: mode === 'listening' && !speaking ? 1 : 0,
        speaking: speaking || mode === 'speaking' ? 1 : 0};
    const blend = 1 - Math.exp(-safeDelta / 0.24);
    for (const key of Object.keys(weights)) weights[key] += (target[key] - weights[key]) * blend;

    const upperChest = humanoid.getNormalizedBoneNode('upperChest');
    const forearm = humanoid.getNormalizedBoneNode('rightLowerArm');
    const hand = humanoid.getNormalizedBoneNode('rightHand');
    const outputs = new Map();
    const add = (node, axis, value, limit) => {
      if (!node || !Number.isFinite(value)) return;
      const axes = outputs.get(node) || {};
      axes[axis] = clamp((axes[axis] || 0) + value, -limit, limit);
      outputs.set(node, axes);
    };

    // Upper chest is optional in VRM; basic rigs already breathe in app-scene.
    add(upperChest, 'x', Math.sin(elapsed * Math.PI * 0.48) * 0.018 * weights.idle, LIMITS.upperChestX);
    add(upperChest, 'x', 0.026 * weights.listening, LIMITS.upperChestX);
    add(upperChest, 'z', Math.sin(elapsed * 0.55) * 0.018 * weights.listening, LIMITS.upperChestZ);
    add(upperChest, 'x', Math.sin(elapsed * 5.2) * 0.014 * weights.speaking, LIMITS.upperChestX);
    add(hand, 'x', Math.sin(elapsed * 4.8) * 0.035 * weights.speaking, LIMITS.handX);

    if (gesture) {
      const progress = (elapsed - gesture.start) / gesture.duration;
      if (progress >= 1) {
        gesture = null;
      } else if (progress >= 0) {
        const envelope = smoothstep(Math.min(1, progress * 4)) *
          smoothstep(Math.min(1, (1 - progress) * 4));
        if (gesture.name === 'nod') {
          add(upperChest || chest, 'x', Math.sin(progress * Math.PI) * 0.13 * envelope, LIMITS.upperChestX);
        } else {
          const cycles = gesture.name === 'greeting' ? 3 : 2.5;
          add(forearm, 'z', -0.58 * envelope, LIMITS.forearmZ);
          add(hand, 'z', Math.sin(progress * Math.PI * 2 * cycles) * 0.48 * envelope, LIMITS.handZ);
        }
      }
    }

    for (const [node, axes] of outputs) {
      for (const [axis, value] of Object.entries(axes)) node.rotation[axis] += value;
      applied.set(node, {node, axes});
    }
  }

  return {setState, triggerGesture, setReducedMotion, restore, update};
}
