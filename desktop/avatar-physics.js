// Small secondary-motion layer for explicitly weighted VRM custom nodes.
// Call restore(vrm) before writing the next base pose, then update(vrm, dt,
// inputs) after the base pose and before vrm.update(). update() never removes
// offsets: doing that after a base-pose write would subtract from that pose.

const TARGETS = Object.freeze({
  jawlie_soft_chest_l: {rotation: [0.010, 0.007, 0.009], position: [0.0012, 0.0010, 0.0008], phase: 1},
  jawlie_soft_chest_r: {rotation: [0.010, 0.007, 0.009], position: [0.0012, 0.0010, 0.0008], phase: -1},
  jawlie_soft_hip_l: {rotation: [0.008, 0.006, 0.007], position: [0.0010, 0.0008, 0.0006], phase: -0.8},
  jawlie_soft_hip_r: {rotation: [0.008, 0.006, 0.007], position: [0.0010, 0.0008, 0.0006], phase: 0.8},
  jawlie_cloth_hem_l: {rotation: [0.012, 0.008, 0.010], position: [0.0018, 0.0015, 0.0010], phase: 1.15},
  jawlie_cloth_hem_r: {rotation: [0.012, 0.008, 0.010], position: [0.0018, 0.0015, 0.0010], phase: -1.15},
  jawlie_hair_tail_l: {rotation: [0.018, 0.012, 0.014], position: [0.0022, 0.0018, 0.0018], phase: 1.35},
  jawlie_hair_tail_r: {rotation: [0.018, 0.012, 0.014], position: [0.0022, 0.0018, 0.0018], phase: -1.35},
});

const AXES = ['x', 'y', 'z'];
const FIXED_STEP = 1 / 60;
const MAX_STEPS = 5;
const MAX_DELTA = FIXED_STEP * MAX_STEPS;
const SPRING = 52;
const DAMPING = 10;
const MAX_POSE_ACCELERATION = 8;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const finite = (value) => Number.isFinite(value) ? value : 0;

function makeChannel(limit, gain) {
  return {limit, gain, value: 0, velocity: 0};
}

function makeTarget(node, spec) {
  const channels = [];
  for (let axis = 0; axis < 3; axis++) {
    channels.push(makeChannel(spec.rotation[axis], 0.055 * spec.phase * (axis === 1 ? -1 : 1)));
  }
  for (let axis = 0; axis < 3; axis++) {
    channels.push(makeChannel(spec.position[axis], 0.0025 * spec.phase * (axis === 0 ? -1 : 1)));
  }
  return {node, channels};
}

function findNamedNodes(vrm) {
  const found = new Map();
  const visit = (node) => {
    if (!node || typeof node !== 'object') return;
    if (Object.hasOwn(TARGETS, node.name) && !found.has(node.name)) found.set(node.name, node);
    for (const child of node.children || []) visit(child);
  };
  visit(vrm?.scene);
  return found;
}

function poseSample(vrm) {
  const humanoid = vrm?.humanoid;
  if (!humanoid?.getNormalizedBoneNode) return null;
  const sample = [];
  for (const name of ['hips', 'chest']) {
    const node = humanoid.getNormalizedBoneNode(name);
    if (!node) continue;
    const position = node.position || {};
    const rotation = node.rotation || {};
    sample.push(
      finite(position.x), finite(position.y), finite(position.z),
      finite(rotation.x), finite(rotation.y), finite(rotation.z),
    );
  }
  return sample.length ? sample : null;
}

export function createAvatarPhysicsController({enabled = true, intensity = 0.5, reducedMotion = false} = {}) {
  let isEnabled = Boolean(enabled);
  let isReduced = Boolean(reducedMotion);
  let amount = clamp(finite(Number(intensity)), 0, 1);
  let paused = false;
  let currentVrm = null;
  let targets = new Map();
  let applied = [];
  let accumulator = 0;
  let previousPose = null;
  let previousPoseVelocity = null;
  let previousSpeechDrive = 0;

  function restore() {
    for (const {node, rotation, position} of applied) {
      for (let i = 0; i < 3; i++) {
        if (node.rotation) node.rotation[AXES[i]] = rotation[i];
        if (node.position) node.position[AXES[i]] = position[i];
      }
    }
    applied = [];
  }

  function clearSimulation() {
    accumulator = 0;
    previousPose = null;
    previousPoseVelocity = null;
    previousSpeechDrive = 0;
    for (const target of targets.values()) {
      for (const channel of target.channels) {
        channel.value = 0;
        channel.velocity = 0;
      }
    }
  }

  function reset(vrm = currentVrm) {
    restore();
    currentVrm = vrm || null;
    targets = new Map([...findNamedNodes(currentVrm)].map(([name, node]) => [name, makeTarget(node, TARGETS[name])]));
    clearSimulation();
  }

  function setEnabled(value) {
    isEnabled = Boolean(value);
    if (!isEnabled) {
      restore();
      clearSimulation();
    }
  }

  function setReducedMotion(value) {
    isReduced = Boolean(value);
    if (isReduced) {
      restore();
      clearSimulation();
    }
  }

  function setIntensity(value) {
    amount = clamp(finite(Number(value)), 0, 1);
    if (amount === 0) {
      restore();
      clearSimulation();
    }
  }

  function setPaused(value) {
    paused = Boolean(value);
    if (paused) {
      restore();
      clearSimulation();
    }
  }

  function deriveDrive(vrm, dt, inputs) {
    const pose = poseSample(vrm);
    const computed = [0, 0, 0];
    if (pose && previousPose && pose.length === previousPose.length && dt > 0) {
      const velocity = pose.map((value, index) => (value - previousPose[index]) / dt);
      if (previousPoseVelocity) {
        for (let i = 0; i < pose.length; i++) {
          const acceleration = (velocity[i] - previousPoseVelocity[i]) / dt;
          computed[i % 3] += clamp(acceleration, -MAX_POSE_ACCELERATION, MAX_POSE_ACCELERATION);
        }
      }
      previousPoseVelocity = velocity;
    } else {
      previousPoseVelocity = null;
    }
    previousPose = pose;

    const supplied = inputs.torsoAcceleration;
    if (supplied && typeof supplied === 'object') {
      computed[0] += finite(Number(supplied.x));
      computed[1] += finite(Number(supplied.y));
      computed[2] += finite(Number(supplied.z));
    }
    const speech = inputs.state === 'speaking'
      ? clamp(finite(Number(inputs.speechLevel)), 0, 1)
      : 0;
    const speechChange = dt > 0 ? clamp((speech - previousSpeechDrive) / dt, -MAX_POSE_ACCELERATION, MAX_POSE_ACCELERATION) : 0;
    previousSpeechDrive = speech;
    computed[0] += speechChange * 0.35;
    computed[1] += speechChange * 0.55;
    computed[2] -= speechChange * 0.2;
    return computed.map((value) => clamp(value, -MAX_POSE_ACCELERATION, MAX_POSE_ACCELERATION));
  }

  function update(vrm, deltaSeconds, elapsed = 0, inputs = {}) {
    if (vrm !== currentVrm) reset(vrm);
    if (inputs.state === 'paused') paused = true;
    else if (inputs.state) paused = false;
    if (!isEnabled || isReduced || paused || amount === 0 || !targets.size) {
      restore();
      clearSimulation();
      return;
    }

    const delta = clamp(finite(Number(deltaSeconds)), 0, MAX_DELTA);
    // elapsed is part of the shared scene update signature. The spring uses
    // fixed deltas only, so wall-clock jumps and frame hitches cannot amplify it.
    void elapsed;
    const drive = deriveDrive(vrm, delta, inputs || {});
    accumulator = Math.min(accumulator + delta, MAX_DELTA);
    let steps = Math.min(MAX_STEPS, Math.floor((accumulator + 1e-9) / FIXED_STEP));
    while (steps-- > 0) {
      for (const target of targets.values()) {
        for (let index = 0; index < target.channels.length; index++) {
          const channel = target.channels[index];
          const driveAxis = index % 3;
          const forcing = drive[driveAxis] * channel.gain * amount;
          const acceleration = forcing - SPRING * channel.value - DAMPING * channel.velocity;
          channel.velocity += acceleration * FIXED_STEP;
          channel.value = clamp(channel.value + channel.velocity * FIXED_STEP, -channel.limit * amount, channel.limit * amount);
        }
      }
      accumulator -= FIXED_STEP;
    }

    for (const target of targets.values()) {
      const {node, channels} = target;
      if (!node.rotation || !node.position) continue;
      const values = channels.map((channel) => channel.value);
      const baseRotation = AXES.map((axis) => finite(node.rotation[axis]));
      const basePosition = AXES.map((axis) => finite(node.position[axis]));
      for (let i = 0; i < 3; i++) {
        node.rotation[AXES[i]] += values[i];
        node.position[AXES[i]] += values[i + 3];
      }
      applied.push({node, rotation: baseRotation, position: basePosition});
    }
  }

  function cleanup() {
    restore();
    clearSimulation();
    currentVrm = null;
    targets = new Map();
  }

  function getStats() {
    const boundNodeNames = [...targets.keys()];
    return {
      supported: boundNodeNames.length > 0,
      boundNodes: boundNodeNames.length,
      boundNodeNames,
      enabled: isEnabled,
      reducedMotion: isReduced,
      intensity: amount,
      paused,
    };
  }

  return {
    setEnabled,
    setReducedMotion,
    setIntensity,
    setPaused,
    reset,
    restore,
    update,
    cleanup,
    getStats,
    get enabled() { return isEnabled; },
    get reducedMotion() { return isReduced; },
    get intensity() { return amount; },
  };
}
