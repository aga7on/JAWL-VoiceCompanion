// Embedded 3D scene for the single-window app (ADR-046).
// Same rendering core as desktop/avatar-scene.js (presets, rest pose,
// framing, lip sync, idle), but in-page: no cross-origin bridge needed.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { createAvatarMotionController, createGenerationGate } from './avatar-motion.js';
import { createAvatarPhysicsController } from './avatar-physics.js';

const canvas = document.getElementById('avatar-canvas');
const statusEl = document.getElementById('avatar-status');

const WARDROBE_ROOT = '/api/avatar/model'; // served by the companion

const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
renderer.setClearColor(0x00000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

const scene = new THREE.Scene();
const gazeTarget = new THREE.Object3D();
scene.add(gazeTarget);
const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 40);
// Soft three-point light: the single hard PI-strength directional blew out
// the MToon materials (vision check: near-uniform white). VRM/MToon wants
// gentle intensities.
const key = new THREE.DirectionalLight(0xffffff, 0.9);
key.position.set(2, 3, 2);
scene.add(key);
const fill = new THREE.DirectionalLight(0xdfefff, 0.35);
fill.position.set(-2, 2, 1);
scene.add(fill);
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const clock = new THREE.Clock();
const reducedMotionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');
const preferencesKey = 'jawl-avatar-motion-v1';
let preferences = {enabled: true, intensity: 0.5, reducedMotion: false};
try {
  const saved = JSON.parse(localStorage.getItem(preferencesKey) || 'null');
  if (saved && typeof saved === 'object') {
    if (typeof saved.enabled === 'boolean') preferences.enabled = saved.enabled;
    if (typeof saved.reducedMotion === 'boolean') preferences.reducedMotion = saved.reducedMotion;
    if (Number.isFinite(saved.intensity)) preferences.intensity = Math.max(0, Math.min(1, saved.intensity));
  }
} catch { /* Invalid/blocked storage cannot prevent rendering. */ }
let reducedMotion = Boolean(reducedMotionQuery?.matches || preferences.reducedMotion);
const motion = createAvatarMotionController({reducedMotion});
const physics = createAvatarPhysicsController({...preferences, reducedMotion});
reducedMotionQuery?.addEventListener?.('change', (event) => setReducedMotion(event.matches || preferences.reducedMotion));
const idleRestPoses = new WeakMap();
const expressionAliases = new WeakMap();
const modelLoadGate = createGenerationGate();
let lastEnvelopeGestureId = '';

const state = {
  vrm: null,
  expression: 'neutral',
  expressionWeight: 0,
  lipLevel: 0,
  blinkNext: 0,
  lookTarget: new THREE.Vector3(0, 1.35, 4),
  wornModel: null,
  motionState: 'idle',
};

const EMOTION_PRESETS = {
  happy: 'happy', joyful: 'happy', excited: 'happy',
  angry: 'angry', sad: 'sad', concerned: 'sad',
  calm: 'relaxed', relaxed: 'relaxed', attentive: 'relaxed', thinking: 'relaxed',
  surprised: 'surprised', confused: 'surprised',
  neutral: null, error: 'sad',
};

function setStatus(text) { statusEl.textContent = text; }

function tick() {
  requestAnimationFrame(tick);
  const delta = Math.min(clock.getDelta(), 0.05);
  const elapsed = clock.elapsedTime;
  const vrm = state.vrm;
  if (vrm) {
    state.expressionWeight = reducedMotion ? 1 : Math.min(1, state.expressionWeight + delta * 3.0);
    applyExpression(vrm, state.expression, state.expressionWeight);
    applyLipSync(vrm, state.lipLevel);
    physics.restore(vrm);
    motion.restore(vrm);
    applyIdle(vrm, delta, elapsed);
    motion.update(vrm, delta, elapsed, state.motionState, state.lipLevel);
    // Gaze: the look-at target IS the head controller in three-vrm (it
    // overrides head bone rotation in vrm.update), so the living gaze
    // drift goes through the target, not the bones.
    if (vrm.lookAt?.target) {
      const t = state.lookTarget;
      vrm.lookAt.target.position.set(
        t.x + (reducedMotion ? 0 : noise1(elapsed * 0.31, 5.2) * 0.09),
        t.y + (reducedMotion ? 0 : noise1(elapsed * 0.23, 8.1) * 0.06),
        t.z);
    }
    vrm.update(reducedMotion ? 0 : delta);
    // These weighted custom bones are NOT native spring bones. One owner,
    // after the normalized pose has reached the raw rig, before rendering.
    physics.update(vrm, delta, elapsed, {state: state.motionState, speechLevel: state.lipLevel});
  }
  renderer.render(scene, camera);
}

function applyExpression(vrm, expression, weight) {
  const manager = vrm?.expressionManager;
  if (!manager) return;
  let aliases = expressionAliases.get(manager);
  if (!aliases) {
    aliases = new Map(manager.expressions.map(e => [e.expressionName.toLowerCase(), e.expressionName]));
    expressionAliases.set(manager, aliases);
  }
  for (const name of ['happy', 'angry', 'sad', 'relaxed', 'surprised']) {
    const actual = aliases.get(name);
    if (actual) manager.setValue(actual, expression === name ? weight : 0);
  }
  manager.update();
}

function applyLipSync(vrm, level) {
  const manager = vrm?.expressionManager;
  if (!manager) return;
  const lv = Number(level) || 0;
  manager.setValue('aa', lv);
  const t = typeof clock !== 'undefined' && clock ? clock.elapsedTime : 0;
  if (lv > 0.04) {
    manager.setValue('oh', lv * (0.25 + 0.25 * Math.sin(t * 11.3)));
    manager.setValue('ee', lv * (0.18 + 0.18 * Math.cos(t * 14.7)));
  } else {
    manager.setValue('oh', 0);
    manager.setValue('ee', 0);
  }
}

function resetLipSync(vrm) {
  const manager = vrm?.expressionManager;
  if (!manager) return;
  applyLipSync(vrm, 0);
  manager.update();
}

// ---------------------------------------------------------------------------
// Idle life: the body must breathe, sway, shift weight and micro-move ALL the
// time; emotions and speech add body gestures on top (owner requirement:
// "тело должно непрерывно жить"). Everything is additive on the normalized
// bones and decays back to the rest pose.
// ---------------------------------------------------------------------------

// layered sine "noise" (deterministic, cheap, smooth)
function noise1(t, seed) {
  return (
    Math.sin(t * 1.0 + seed) * 0.5 +
    Math.sin(t * 2.3 + seed * 1.7) * 0.3 +
    Math.sin(t * 4.1 + seed * 3.1) * 0.2
  );
}

const gesture = {
  // random micro-gesture scheduler
  nextAt: 4,
  kind: null,
  phase: 0,
  // emotion burst: set on setEmotion, decays over ~2.5 s
  emotion: null,
  emotionAt: -10,
};

// per-emotion body reaction targets (radians, additive)
const EMOTION_BODY = {
  happy:    { spineX: -0.06, headX: -0.05, armLiftL: 0.25, armLiftR: 0.25, shoulderL: 0.05 },
  surprised:{ spineX: 0.07,  headX: 0.04,  armLiftL: -0.15, armLiftR: -0.15, shoulderL: 0.12 },
  sad:      { spineX: 0.10,  headX: 0.16,  armLiftL: 0, armLiftR: 0, shoulderL: -0.06 },
  angry:    { spineX: -0.03, headX: -0.02, armLiftL: -0.08, armLiftR: -0.08, shoulderL: 0.05 },
  relaxed:  { spineX: 0.03,  headX: 0.03,  armLiftL: 0.05, armLiftR: 0.05, shoulderL: 0 },
};

// random micro-gestures: nod, head tilt, shoulder roll, weight shift
const MICRO_GESTURES = ['nod', 'tilt', 'shoulder', 'shift', 'stretch'];

function applyIdle(vrm, delta, elapsed) {
  const humanoid = vrm?.humanoid;
  const manager = vrm?.expressionManager;
  if (!humanoid || !manager) return;
  if (reducedMotion) {
    manager.setValue('blink', 0);
    const rest = idleRestPoses.get(vrm);
    const k = 1 - Math.exp(-Math.min(delta, 0.05) / 0.18);
    if (rest) {
      for (const {node, rotation, y} of rest) {
        node.rotation.x += (rotation.x - node.rotation.x) * k;
        node.rotation.y += (rotation.y - node.rotation.y) * k;
        node.rotation.z += (rotation.z - node.rotation.z) * k;
        if (y !== null) node.position.y += (y - node.position.y) * k;
      }
    }
    gesture.kind = null;
    return;
  }

  // ---- blink: irregular, sometimes double ----
  if (elapsed > state.blinkNext) {
    state.blinkNext = elapsed + 2.2 + Math.random() * 3.5;
    state.blinkUntil = elapsed + 0.12 + Math.random() * 0.06;
    state.blinkDouble = Math.random() < 0.2 ? elapsed + 0.28 : 0;
  }
  const blinking =
    elapsed < (state.blinkUntil || 0) ||
    (state.blinkDouble && elapsed > state.blinkDouble && elapsed < state.blinkDouble + 0.1);
  manager.setValue('blink', blinking ? 1 : 0);

  // ---- breath: chest expand + shoulder rise + subtle vertical bob ----
  const breathRate = 0.9 + (state.lipLevel > 0.05 ? 0.35 : 0); // speaking breathes faster
  const breath = Math.sin(elapsed * Math.PI * breathRate);
  const chest = humanoid.getNormalizedBoneNode('chest');
  const spine = humanoid.getNormalizedBoneNode('spine');
  const hips = humanoid.getNormalizedBoneNode('hips');
  const neck = humanoid.getNormalizedBoneNode('neck');
  const head = humanoid.getNormalizedBoneNode('head');
  const lShoulder = humanoid.getNormalizedBoneNode('leftShoulder');
  const rShoulder = humanoid.getNormalizedBoneNode('rightShoulder');
  const lArm = humanoid.getNormalizedBoneNode('leftUpperArm');
  const rArm = humanoid.getNormalizedBoneNode('rightUpperArm');

  // Emotion bursts are offsets from rest, never additions to last frame.
  if (lArm) lArm.rotation.z = (lArm.userData.baseZ ??= lArm.rotation.z);
  if (rArm) rArm.rotation.z = (rArm.userData.baseZ ??= rArm.rotation.z);

  if (chest) chest.rotation.x = breath * 0.022;
  if (lShoulder) lShoulder.rotation.z = -breath * 0.03;
  if (rShoulder) rShoulder.rotation.z = breath * 0.03;
  // vertical bob: hips sink slightly on exhale
  if (hips) hips.position.y = (hips.userData.baseY ??= hips.position.y) - 0.004 + breath * 0.004;

  // ---- weight shift: slow sway, hips lead, spine counter-rotates ----
  const sway = noise1(elapsed * 0.22, 7.3);
  if (hips) {
    hips.rotation.z = sway * 0.05;
    hips.rotation.y = sway * 0.07;
  }
  if (spine) {
    spine.rotation.z = -sway * 0.035;
    spine.rotation.x = breath * 0.02;
  }

  // ---- head: layered micro-noise + slow gaze drift ----
  const hx = noise1(elapsed * 0.5, 2.1) * 0.05;
  const hy = noise1(elapsed * 0.37, 9.4) * 0.13;
  const hz = noise1(elapsed * 0.43, 4.8) * 0.03;
  if (neck) {
    neck.rotation.x = hx * 0.4;
    neck.rotation.y = hy * 0.4;
  }
  if (head) {
    head.rotation.x = hx;
    head.rotation.y = hy;
    head.rotation.z = hz;
  }

  // ---- speaking: subtle head bob + hand emphasis ----
  if (state.lipLevel > 0.04) {
    const talk = state.lipLevel;
    if (head) head.rotation.x += Math.sin(elapsed * 6.5) * 0.02 * talk;
    if (rArm) rArm.rotation.x = (rArm.userData.baseX ??= rArm.rotation.x) + Math.sin(elapsed * 3.1) * 0.06 * talk;
    if (lArm) lArm.rotation.x = (lArm.userData.baseX ??= lArm.rotation.x) + Math.sin(elapsed * 2.7 + 1.4) * 0.04 * talk;
  } else {
    // decay both arms back to their captured base pose
    const k = Math.min(1, delta * 4);
    if (rArm && rArm.userData.baseX !== undefined) {
      rArm.rotation.x += (rArm.userData.baseX - rArm.rotation.x) * k;
    }
    if (lArm && lArm.userData.baseX !== undefined) {
      lArm.rotation.x += (lArm.userData.baseX - lArm.rotation.x) * k;
    }
  }

  // ---- random micro-gesture every 7-16 s ----
  if (!gesture.kind && elapsed > gesture.nextAt) {
    gesture.kind = MICRO_GESTURES[Math.floor(Math.random() * MICRO_GESTURES.length)];
    gesture.phase = 0;
  }
  if (gesture.kind) {
    gesture.phase += delta;
    const t = gesture.phase;
    const env = Math.sin(Math.min(1, t / 1.4) * Math.PI); // 0..1..0 over ~1.4 s
    if (gesture.kind === 'nod' && head) head.rotation.x += env * 0.12;
    if (gesture.kind === 'tilt' && head) head.rotation.z += env * 0.09;
    if (gesture.kind === 'shoulder') {
      if (lShoulder) lShoulder.rotation.z += env * 0.1;
      if (rShoulder) rShoulder.rotation.z -= env * 0.1;
    }
    if (gesture.kind === 'shift' && hips) hips.rotation.z += env * 0.05;
    if (gesture.kind === 'stretch') {
      if (chest) chest.rotation.x -= env * 0.05;
      if (lShoulder) lShoulder.rotation.z -= env * 0.14;
      if (rShoulder) rShoulder.rotation.z += env * 0.14;
    }
    if (t > 1.4) {
      gesture.kind = null;
      gesture.nextAt = elapsed + 7 + Math.random() * 9;
    }
  }

  // ---- emotion body burst: reacts for ~2.5 s then decays ----
  const body = EMOTION_BODY[state.expression];
  if (body) {
    const age = elapsed - (gesture.emotionAt || -10);
    if (age < 2.5) {
      // quick attack, smooth decay
      const k = age < 0.25 ? age / 0.25 : Math.max(0, 1 - (age - 0.25) / 2.25);
      const ease = k * k * (3 - 2 * k); // smoothstep
      if (spine) spine.rotation.x += body.spineX * ease;
      if (head) head.rotation.x += body.headX * ease;
      if (lShoulder) lShoulder.rotation.z -= body.shoulderL * ease;
      if (rShoulder) rShoulder.rotation.z += body.shoulderL * ease;
      // arms lift toward the body: left rest z is -1.05, right +1.05
      if (lArm) lArm.rotation.z += body.armLiftL * ease;
      if (rArm) rArm.rotation.z -= body.armLiftR * ease;
    }
  }
}

function resize() {
  const width = canvas.clientWidth || 1;
  const height = canvas.clientHeight || 1;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

function listExpressions(vrm) {
  const manager = vrm?.expressionManager;
  if (!manager) return [];
  return manager.expressions.map(e => e.expressionName);
}

// Raw bone lookup by VRM bone name (works for VRM 0.x 'J_Bip_*' and 1.0).
function findRawBone(vrm, pattern) {
  let found = null;
  vrm.scene.traverse((node) => {
    if (!found && node.name && pattern.test(node.name)) found = node;
  });
  return found;
}

const worldPos = (node, out) => {
  node.updateWorldMatrix(true, false);
  return node.getWorldPosition(out);
};

function applyRestPose(vrm) {
  const humanoid = vrm?.humanoid;
  if (!humanoid) return;
  vrm.update(0.0);

  // Arms-down test on RAW bones (world space, version-independent): the
  // elbow must hang below the shoulder.
  const lUpper = findRawBone(vrm, /^J_Bip_L_UpperArm$/i) || findRawBone(vrm, /LeftArm|leftUpperArm/i);
  const lLower = findRawBone(vrm, /^J_Bip_L_LowerArm$/i) || findRawBone(vrm, /LeftForeArm|leftLowerArm/i);
  const rUpper = findRawBone(vrm, /^J_Bip_R_UpperArm$/i) || findRawBone(vrm, /RightArm|rightUpperArm/i);
  const rLower = findRawBone(vrm, /^J_Bip_R_LowerArm$/i) || findRawBone(vrm, /RightForeArm|rightLowerArm/i);
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const armsDown = () => {
    if (!(lUpper && lLower && rUpper && rLower)) return true; // cannot measure: trust the model
    worldPos(lUpper, a); worldPos(lLower, b);
    const leftDown = b.y < a.y - 0.02;
    worldPos(rUpper, a); worldPos(rLower, b);
    const rightDown = b.y < a.y - 0.02;
    return leftDown && rightDown;
  };
  if (armsDown()) {
    window.__jawlRestPose = 'model-provided';
    return;
  }

  // T-pose: bend the arms down through NORMALIZED bones, then verify in raw
  // world space and flip the sign when the model's coordinate convention
  // inverts it (VRM 0.x vs 1.0 - measured, not guessed).
  const lArmN = humanoid.getNormalizedBoneNode('leftUpperArm');
  const rArmN = humanoid.getNormalizedBoneNode('rightUpperArm');
  const lForeN = humanoid.getNormalizedBoneNode('leftLowerArm');
  const rForeN = humanoid.getNormalizedBoneNode('rightLowerArm');
  for (const sign of [-1, 1]) {
    if (lArmN) lArmN.rotation.z = sign * -1.05;
    if (rArmN) rArmN.rotation.z = sign * 1.05;
    if (lForeN) lForeN.rotation.z = sign * -0.25;
    if (rForeN) rForeN.rotation.z = sign * 0.25;
    vrm.update(0.0);
    if (armsDown()) {
      window.__jawlRestPose = `applied(sign=${sign})`;
      return;
    }
  }
  window.__jawlRestPose = 'failed-to-verify';
}

function captureIdleRestPose(vrm) {
  const humanoid = vrm?.humanoid;
  if (!humanoid) return;
  const names = ['chest', 'spine', 'hips', 'neck', 'head', 'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm'];
  const pose = [];
  for (const name of names) {
    const node = humanoid.getNormalizedBoneNode(name);
    if (!node) continue;
    if (name.endsWith('UpperArm')) node.userData.baseZ = node.rotation.z;
    pose.push({
      node,
      rotation: {x: node.rotation.x, y: node.rotation.y, z: node.rotation.z},
      y: name === 'hips' ? node.position.y : null,
    });
  }
  idleRestPoses.set(vrm, pose);
}

function frameCamera(vrm) {
  // VRM 0.x models face -Z; the canonical helper rotates them to +Z (1.0
  // models are untouched). Camera sits at +Z, so this is "face the viewer"
  // for every model version.
  VRMUtils.rotateVRM0?.(vrm);
  // Spring tails were initialized before the VRM0 root was rotated. Rebase
  // their world-space history so the first frame is not a 180-degree impulse.
  vrm.springBoneManager?.reset();
  vrm.update(0.0);
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const distance = (Math.max(size.y, size.x * 1.2) / 2) / Math.tan((camera.fov * Math.PI) / 360) * 1.15;
  camera.position.set(center.x, center.y, center.z + distance);
  camera.lookAt(center.x, center.y, center.z);
  state.lookTarget.set(center.x, center.y, center.z + distance);
  const head = vrm.humanoid?.getNormalizedBoneNode('head');
  window.__jawlFacing = head
    ? Math.round(new THREE.Vector3(0, 0, 1).applyQuaternion(head.getWorldQuaternion(new THREE.Quaternion())).z * 100) / 100
    : null;
  resize();
}

async function loadModel(url, requestId) {
  if (modelLoadGate.isCurrent(requestId)) setStatus(`Аватар: загрузка…`);
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  // Fetch with the session CSRF header first, then parse from memory:
  // GLTFLoader's own fetch omits X-Companion-CSRF, which the companion
  // requires for every API route (403 + white model otherwise). The
  // resource path is the same - no security is relaxed.
  const resource = url.startsWith('/api/')
    ? new URL(url, location.origin).href
    : url;
  let gltf;
  if (url.startsWith('/api/')) {
    const response = await wardrobeFetch(url);
    if (!response.ok) throw new Error(`${url} responded with ${response.status}`);
    const buffer = await response.arrayBuffer();
    gltf = await new Promise((resolve, reject) =>
      loader.parse(buffer, '/api/avatar/model/', resolve, reject));
  } else {
    gltf = await loader.loadAsync(resource);
  }
  const vrm = gltf.userData.vrm;
  if (!modelLoadGate.isCurrent(requestId)) {
    VRMUtils.deepDispose(vrm.scene);
    return null;
  }
  // No removeUnnecessaryJoints/combineSkeletons: they collapse finger bones
  // on VRM 0.x models (AvatarSample_A rendered wedge hands - vision-caught).
  // They are perf optimizations; correctness first.
  applyRestPose(vrm);
  return vrm;
}

function unload(vrm) {
  if (vrm) {
    motion.restore(null);
    resetLipSync(vrm);
    scene.remove(vrm.scene);
    VRMUtils.deepDispose(vrm.scene);
  }
}

async function swapModel(url, requestId = modelLoadGate.next()) {
  const previous = state.vrm;
  try {
    const next = await loadModel(url, requestId);
    if (!next || !modelLoadGate.isCurrent(requestId)) {
      if (next) VRMUtils.deepDispose(next.scene);
      return null;
    }
    state.lipLevel = 0;
    state.motionState = 'idle';
    motion.setState('idle');
    resetLipSync(next);
    scene.add(next.scene);
    captureIdleRestPose(next);
    frameCamera(next);
    if (next.lookAt) next.lookAt.target = gazeTarget;
    if (reducedMotion) next.springBoneManager?.reset();
    state.vrm = next;
    physics.reset(next);
    renderPhysicsControls();
    unload(previous);
    setStatus(`Аватар: готов (${listExpressions(next).length} выражений)`);
  } catch (error) {
    if (!modelLoadGate.isCurrent(requestId)) return null;
    setStatus(`Аватар: ошибка загрузки: ${error}`);
    state.vrm = previous;
    return null;
  }
  return state.vrm;
}

async function wear(model) {
  return wearForRequest(model, modelLoadGate.next());
}

async function wearForRequest(model, requestId) {
  const name = String(model || '').replace(/[^a-zA-Z0-9_-]/g, '');
  if (!name) return null;
  // resolve through the wardrobe API (bounded, session-gated)
  try {
    const r = await wardrobeFetch('/api/avatar/wardrobe');
    const w = await r.json();
    if (!modelLoadGate.isCurrent(requestId)) return null;
    const known = (w.models || []).some(m => m.model === name);
    if (!known) { setStatus(`Аватар: модель ${name} не в гардеробе`); return null; }
  } catch {
    if (modelLoadGate.isCurrent(requestId)) setStatus('Аватар: гардероб недоступен');
    return null;
  }
  const vrm = await swapModel(`${WARDROBE_ROOT}/${name}.vrm`, requestId);
  if (!vrm || !modelLoadGate.isCurrent(requestId)) return null;
  state.wornModel = name;
  return vrm;
}

// session-aware fetch: the app window shares the companion session/csrf
// with app.js (window.__jcsrf is set there after /api/session).
async function wardrobeFetch(url) {
  const headers = {};
  const csrf = window.__jcsrf;
  if (csrf) headers['X-Companion-CSRF'] = csrf;
  return fetch(url, {credentials: 'include', headers});
}

function setEmotion(emotionId) {
  const preset = EMOTION_PRESETS[emotionId] || null;
  const next = preset || 'neutral';
  if (next !== state.expression) {
    // timestamp the change: applyIdle animates a body burst for ~2.5 s
    gesture.emotionAt = clock.elapsedTime;
  }
  state.expression = next;
}

function setMotionState(mode) {
  const normalized = mode === 'working' ? 'thinking' : mode;
  if (normalized === 'idle' || normalized === 'listening' || normalized === 'thinking' || normalized === 'speaking') {
    state.motionState = normalized;
    if (normalized !== 'speaking') state.lipLevel = 0;
    motion.setState(normalized);
  }
}

function setLipLevel(level) {
  const value = Number(level);
  state.lipLevel = state.motionState === 'speaking' && Number.isFinite(value)
    ? Math.max(0, Math.min(1, value))
    : 0;
}

function setReducedMotion(enabled) {
  reducedMotion = Boolean(enabled);
  motion.setReducedMotion(reducedMotion);
  physics.setReducedMotion(reducedMotion);
  if (reducedMotion) {
    gesture.kind = null;
    state.vrm?.springBoneManager?.reset();
  }
  renderPhysicsControls();
}

function renderPhysicsControls() {
  const stats = physics.getStats();
  const enabled = document.getElementById('avatar-physics-enabled');
  const intensity = document.getElementById('avatar-physics-intensity');
  const reduced = document.getElementById('avatar-reduced-motion');
  const status = document.getElementById('avatar-physics-status');
  if (enabled) enabled.checked = stats.enabled;
  if (reduced) reduced.checked = reducedMotion;
  if (intensity) {
    intensity.value = Math.round(stats.intensity * 100);
    intensity.disabled = !stats.enabled || reducedMotion || !stats.supported;
    intensity.setAttribute('aria-valuetext', `${intensity.value}%`);
    const output = document.getElementById('avatar-physics-value');
    if (output) output.textContent = `${intensity.value}%`;
  }
  if (status) status.textContent = !state.vrm ? 'Проверяем риг модели…'
    : reducedMotion ? 'Уменьшенное движение: вторичная физика остановлена.'
    : !stats.supported ? 'У этой модели нет подготовленных костей вторичной физики.'
    : !stats.enabled ? 'Вторичная физика выключена.'
    : `Поддерживается ${stats.boundNodes} костей. Сила: ${Math.round(stats.intensity * 100)}%.`;
}

function saveMotionPreferences() {
  const status = document.getElementById('avatar-preferences-status');
  try {
    localStorage.setItem(preferencesKey, JSON.stringify(preferences));
    if (status) status.textContent = '';
  } catch {
    if (status) status.textContent = 'Настройки действуют сейчас, но браузер запретил их сохранение.';
  }
}

document.getElementById('avatar-physics-enabled')?.addEventListener('change', (event) => {
  preferences.enabled = event.target.checked;
  physics.setEnabled(preferences.enabled);
  renderPhysicsControls();
  saveMotionPreferences();
});
document.getElementById('avatar-physics-intensity')?.addEventListener('input', (event) => {
  preferences.intensity = Math.max(0, Math.min(1, Number(event.target.value) / 100 || 0));
  physics.setIntensity(preferences.intensity);
  renderPhysicsControls();
  saveMotionPreferences();
});
document.getElementById('avatar-reduced-motion')?.addEventListener('change', (event) => {
  preferences.reducedMotion = event.target.checked;
  setReducedMotion(preferences.reducedMotion || reducedMotionQuery?.matches);
  saveMotionPreferences();
});

function applyAvatarEnvelope(envelope) {
  if (!envelope || typeof envelope !== 'object') return false;
  const avatar = envelope.avatar;
  if (!avatar || typeof avatar !== 'object') return false;
  setEmotion(avatar.expression || envelope.emotion?.id || 'neutral');
  setMotionState(avatar.state || 'idle');

  const requested = String(avatar.motion || '').toLowerCase();
  const gestures = {wave: 'wave', greeting: 'greeting', nod: 'nod', soft_nod: 'nod'};
  const gestureName = gestures[requested];
  if (gestureName) {
    const gestureId = String(envelope.response_id || envelope.turn_id || '');
    if (!gestureId || gestureId !== lastEnvelopeGestureId) {
      motion.triggerGesture(gestureName);
      lastEnvelopeGestureId = gestureId;
    }
  }
  return true;
}

window.addEventListener('jawl-avatar-envelope', (event) => applyAvatarEnvelope(event.detail));

// public surface for app.js
window.__jawlScene = {
  setEmotion,
  setLipLevel,
  setMotionState,
  triggerMotion: (gestureName) => motion.triggerGesture(gestureName),
  setReducedMotion,
  get physicsStats() { return physics.getStats(); },
  get isReducedMotion() { return reducedMotion; },
  applyAvatarEnvelope,
  swapModel,
  wear,
  get currentEmotion() { return state.expression; },
  get wornModel() { return state.wornModel; },
};

resize();
renderPhysicsControls();
tick();
// default model: the wardrobe's first, else the constraint sample.
// Waits for app.js to establish the session (csrf) first - the wardrobe
// and model endpoints are session-gated.
(async () => {
  const requestId = modelLoadGate.next();
  for (let i = 0; i < 20 && !window.__jcsrf; i++) {
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  if (!modelLoadGate.isCurrent(requestId)) return;
  try {
    const r = await wardrobeFetch('/api/avatar/wardrobe');
    const w = await r.json();
    if (!modelLoadGate.isCurrent(requestId)) return;
    const first = (w.models || [])[0];
    if (first) {
      const vrm = await wearForRequest(first.model, requestId);
      if (vrm) return;
    }
  } catch { /* fall through to direct load */ }
  if (modelLoadGate.isCurrent(requestId)) {
    await swapModel('/app/runtime/vrm-models/VRM1_Constraint_Twist_Sample.vrm', requestId);
  }
})();
