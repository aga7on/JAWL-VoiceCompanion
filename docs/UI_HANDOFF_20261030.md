# JAWL Voice Companion - UI handoff (text bundle)

Text-only export of the UI sources from `main` (`b6c12b7`, 2026-10-30), prepared for upload services that do not accept ZIP files. Binary images and the VRM model are excluded.

## Context

- User interface: `http://127.0.0.1:2367/app`.
- OBS mode: the same page with `?mode=obs`.
- Electron opens the same `/app` page by default.
- Port `8770` is an internal JAWL console, not a second user interface.
- Styles are embedded in `desktop/app.html`.
- The UI talks to the Companion backend through same-origin `/api/*` routes. Backend and models are not included.
- Desktop packages are described by `desktop/package.json` and `desktop/package-lock.json`; install with `npm ci` from `desktop`.

## Included source files

### `desktop/app-scene.js`

`````javascript
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
const DEFAULT_MODEL = 'JawlieBlockingV3';
const MODEL_PREFERENCE_KEY = 'jawl-avatar-model-v2';

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
  try { localStorage.setItem(MODEL_PREFERENCE_KEY, name); } catch { /* storage is optional */ }
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
// Default model: the owner-selected model, else the previous choice, else the
// wardrobe's first entry. Waits for app.js to establish the session (csrf)
// first - the wardrobe and model endpoints are session-gated.
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
    const models = w.models || [];
    let saved = '';
    try { saved = localStorage.getItem(MODEL_PREFERENCE_KEY) || ''; } catch { /* storage is optional */ }
    const preferred = [saved, DEFAULT_MODEL]
      .find(name => name && models.some(model => model.model === name));
    const selected = models.find(model => model.model === preferred) || models[0];
    if (selected) {
      const vrm = await wearForRequest(selected.model, requestId);
      if (vrm) return;
    }
  } catch { /* fall through to direct load */ }
  if (modelLoadGate.isCurrent(requestId)) {
    await swapModel('/app/runtime/vrm-models/VRM1_Constraint_Twist_Sample.vrm', requestId);
  }
})();
`````

### `desktop/app-settings-regression.test.js`

`````javascript
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.value = '';
    this.disabled = false;
    this.textContent = '';
  }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  async emit(name, event = {}) { return this.listeners.get(name)?.({...event, target: event.target || this}); }
}

function createHarness(fetchHandler = async () => response({ok: true, values: {}})) {
  const list = new Element('div');
  const search = new Element('input');
  const status = new Element('div');
  const alerts = [];
  const requests = [];
  const find = (root, predicate) => {
    if (predicate(root)) return root;
    for (const child of root.children) {
      const match = find(child, predicate);
      if (match) return match;
    }
    return null;
  };
  const document = {
    querySelector(selector) {
      return {'#settings-list': list, '#settings-search': search, '#conn-status': status}[selector]
        || (selector === '#settings-save' ? find(list, (el) => el.id === 'settings-save') : null);
    },
    createElement(tagName) { return new Element(tagName); },
  };
  const context = vm.createContext({
    document,
    API: {headers: () => ({})},
    alert: (message) => alerts.push(message),
    setStatusLine: (message) => { status.textContent = message; },
    fetch: async (...args) => {
      requests.push(args);
      return fetchHandler(...args);
    },
    console,
  });
  const source = fs.readFileSync(path.join(__dirname, 'app-settings.js'), 'utf8');
  vm.runInContext(source, context, {filename: 'app-settings.js'});
  vm.runInContext(`configHub = {
    ok: true,
    revision: 'r1',
    values: {'settings:identity.agent_name': 'Luna', 'settings:llm.temperature': 0.4}
  };
  renderSettings('');`, context);
  return {context, list, search, status, alerts, requests, find};
}

function response(body, {ok = true, status = ok ? 200 : 500} = {}) {
  return {ok, status, json: async () => body};
}

test('dirty edits enable save immediately and survive search rerenders', async () => {
  const h = createHarness();
  const save = () => h.find(h.list, (el) => el.id === 'settings-save');
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');

  assert.equal(save().disabled, true);
  input.value = 'Luna 2';
  await input.emit('input');
  assert.equal(save().disabled, false);
  assert.equal(save().textContent, 'сохранить (1)');

  h.search.value = 'temperature';
  await h.search.emit('input');
  assert.equal(save().disabled, false);
  h.search.value = '';
  await h.search.emit('input');
  const rerenderedInput = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  assert.equal(rerenderedInput.value, 'Luna 2');
});

test('settings load failure is localized and retry restores the settings form', async () => {
  let attempts = 0;
  const h = createHarness(async () => {
    attempts += 1;
    if (attempts === 1) return response({error: 'unavailable'}, {ok: false, status: 503});
    return response({ok: true, revision: 'r2', values: {'settings:identity.agent_name': 'Luna'}});
  });
  h.context.configHub = null;
  await h.context.loadSettings();

  const alert = h.find(h.list, (el) => el.className === 'card settings-load-error');
  assert.ok(alert);
  assert.equal(alert.getAttribute('role'), 'group');
  assert.equal(alert.children[1].getAttribute('role'), 'alert');
  assert.match(alert.children[1].textContent, /Сервис настроек не ответил/);
  const retry = h.find(alert, (el) => el.textContent === 'Повторить загрузку');
  assert.ok(retry);
  await retry.emit('click');

  assert.equal(attempts, 2);
  assert.equal(h.find(h.list, (el) => el.id === 'settings-save')?.disabled, true);
  assert.equal(h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text')?.value, 'Luna');
  assert.equal(h.find(h.list, (el) => el.className === 'card settings-load-error'), null);
});

test('typed settings controls expose names and use keyboard-focusable switches', async () => {
  const h = createHarness();
  vm.runInContext(`configHub = {
    ok: true,
    revision: 'r1',
    values: {
      'settings:system.proactive_guidance': false,
      'settings:llm.temperature': 0.4,
    },
  };`, h.context);
  h.context.renderSettings('');

  const toggle = h.find(h.list, (el) => el.getAttribute('role') === 'switch');
  assert.equal(toggle.tagName, 'button');
  assert.equal(toggle.type, 'button');
  assert.equal(toggle.getAttribute('aria-checked'), 'false');
  assert.equal(toggle.getAttribute('aria-label'), 'Проактивные подсказки');
  await toggle.emit('click');
  assert.equal(toggle.getAttribute('aria-checked'), 'true');

  const range = h.find(h.list, (el) => el.type === 'range');
  const number = h.find(h.list, (el) => el.type === 'number');
  assert.equal(range.getAttribute('aria-label'), 'Температура, ползунок');
  assert.equal(number.getAttribute('aria-label'), 'Температура, числовое значение');
});

test('save HTTP failures keep the draft and report failure', async () => {
  const h = createHarness(async () => response({error: 'conflict'}, {ok: false, status: 409}));
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  input.value = 'Edited';
  await input.emit('input');
  await h.find(h.list, (el) => el.id === 'settings-save').emit('click');

  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').disabled, false);
  assert.match(h.status.textContent, /черновики сохранены/);
  assert.equal(h.alerts.length, 1);
});

test('partial save acknowledgements keep unresolved drafts', async () => {
  const h = createHarness(async () => response({ok: true, unknown: ['settings:identity.agent_name']}));
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  input.value = 'Edited';
  await input.emit('input');
  await h.find(h.list, (el) => el.id === 'settings-save').emit('click');

  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').disabled, false);
  assert.match(h.status.textContent, /не сохранено; черновики сохранены/);
});

test('edits made while saving remain dirty after the earlier value is saved', async () => {
  let resolveSave;
  const h = createHarness(async (url) => {
    if (url === '/api/config-hub/save') {
      return new Promise((resolve) => { resolveSave = resolve; });
    }
    return response({ok: true, values: {'settings:identity.agent_name': 'First edit', 'settings:llm.temperature': 0.4}});
  });
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  input.value = 'First edit';
  await input.emit('input');
  const saving = h.find(h.list, (el) => el.id === 'settings-save').emit('click');
  await new Promise((resolve) => setImmediate(resolve));

  input.value = 'Second edit';
  await input.emit('input');
  resolveSave(response({ok: true, revision: 'r2', restart_required: false}));
  await saving;

  const updated = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  assert.equal(updated.value, 'Second edit');
  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').disabled, false);
  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').textContent, 'сохранить (1)');
});

test('restart HTTP failures are visible after a confirmed save', async () => {
  const h = createHarness(async (url) => {
    if (url === '/api/config-hub/save') return response({ok: true, revision: 'r2', restart_required: true});
    if (url === '/api/jawl/restart') return response({error: 'unavailable'}, {ok: false, status: 503});
    return response({ok: true, values: {'settings:identity.agent_name': 'Edited', 'settings:llm.temperature': 0.4}});
  });
  const input = h.find(h.list, (el) => el.tagName === 'input' && el.type === 'text');
  input.value = 'Edited';
  await input.emit('input');
  await h.find(h.list, (el) => el.id === 'settings-save').emit('click');

  assert.equal(h.requests.some(([url]) => url === '/api/jawl/restart'), true);
  assert.match(h.status.textContent, /сохранено, но перезапуск не удался: HTTP 503/);
  assert.equal(h.find(h.list, (el) => el.id === 'settings-save').disabled, true);
});
`````

### `desktop/app-settings.js`

`````javascript
// Settings section: config-hub rendered as typed V.E.G.A.-style fields
// (toggles, sliders, selects with human labels) — not a text editor.
// Groups are an accordion: everyday groups open, engineering groups
// collapsed; search matches Russian labels, descriptions and keys.

const SETTING_FIELDS = [
  // --- interfaces: mcp ---
  { key: 'interfaces:mcp.enabled', label: 'MCP-интерфейс', desc: 'Канал внешних MCP-серверов', type: 'bool' },
  { key: 'interfaces:mcp.startup_timeout_sec', label: 'MCP: таймаут старта', type: 'number', min: 1, max: 300, step: 1, unit: 'сек' },
  { key: 'interfaces:mcp.request_timeout_sec', label: 'MCP: таймаут запроса', type: 'number', min: 1, max: 600, step: 1, unit: 'сек' },
  { key: 'interfaces:mcp.max_catalog_items', label: 'MCP: макс. инструментов', type: 'number', min: 0, max: 500, step: 1, unit: 'шт' },
  { key: 'interfaces:mcp.max_result_chars', label: 'MCP: макс. символов', type: 'number', min: 0, max: 100000, step: 1000, unit: 'симв' },
  { key: 'interfaces:mcp.max_binary_bytes', label: 'MCP: макс. бинарных', type: 'number', min: 0, max: 104857600, step: 1048576, unit: 'МБ·м' },
  // --- interfaces: debug broker ---
  { key: 'interfaces:debug_broker.enabled', label: 'Debug Broker', desc: 'RE/отладочный контур', type: 'bool' },
  { key: 'interfaces:debug_broker.auto_start', label: 'Debug Broker: автозапуск', type: 'bool' },
  { key: 'interfaces:debug_broker.startup_timeout_sec', label: 'Debug Broker: старт', type: 'number', min: 1, max: 300, unit: 'сек' },
  { key: 'interfaces:debug_broker.request_timeout_sec', label: 'Debug Broker: запрос', type: 'number', min: 1, max: 600, unit: 'сек' },
  { key: 'interfaces:debug_broker.max_result_chars', label: 'Debug Broker: макс. симв.', type: 'number', min: 0, max: 100000, step: 1000, unit: 'симв' },
  { key: 'interfaces:debug_broker.max_sessions', label: 'Debug Broker: сессий', type: 'number', min: 1, max: 32, unit: 'шт' },
  { key: 'interfaces:debug_broker.re_root', label: 'Debug Broker: корень RE', type: 'text' },
  // --- interfaces: multimodality ---
  { key: 'interfaces:multimodality.enabled', label: 'Мультимодальность', desc: 'Изображения и медиа в ходы', type: 'bool' },
  { key: 'interfaces:multimodality.video_understanding_enabled', label: 'Понимание видео', type: 'bool' },
  { key: 'interfaces:multimodality.media_generation_enabled', label: 'Генерация медиа', type: 'bool' },
  { key: 'interfaces:multimodality.media_request_timeout_sec', label: 'Медиа: таймаут', type: 'number', min: 1, max: 600, unit: 'сек' },
  { key: 'interfaces:multimodality.media_poll_interval_sec', label: 'Медиа: опрос', type: 'number', min: 0.5, max: 60, step: 0.5, unit: 'сек' },
  { key: 'interfaces:multimodality.media_max_upload_mb', label: 'Медиа: загрузка макс.', type: 'number', min: 1, max: 200, unit: 'МБ' },
  { key: 'interfaces:multimodality.media_max_download_mb', label: 'Медиа: скачивание макс.', type: 'number', min: 1, max: 500, unit: 'МБ' },
  // --- llm (через config-hub секции) ---
  { key: 'settings:llm.temperature', label: 'Температура', desc: '0.1 — исполнительность, 1.0 — обычный', type: 'range', min: 0, max: 2, step: 0.01 },
  { key: 'settings:llm.max_react_steps', label: 'Максимум шагов ReAct', desc: 'После лимита такт закрывается', type: 'number', min: 1, max: 100, unit: 'шаг' },
  { key: 'settings:llm.language', label: 'Язык мышления и ответов', type: 'enum', options: [['ru', 'ru — русский'], ['en', 'en — английский'], ['auto', 'auto — по собеседнику']] },
  { key: 'settings:identity.agent_name', label: 'Имя агента', desc: 'В системный промпт и приветствие', type: 'text' },
  { key: 'settings:system.proactive_guidance', label: 'Проактивные подсказки', desc: 'Агент сам предлагает следующий шаг', type: 'bool' },
  { key: 'settings:llm.is_multimodal', label: 'Мультимодальность модели', desc: 'Изображения и скриншоты в модель', type: 'bool' },
  // --- llm выход ---
  { key: 'settings:llm.max_output_tokens', label: 'Максимум выходных токенов', desc: 'Лимит «размышлений» за шаг', type: 'number', min: 64, max: 32768, step: 64, unit: 'ток' },
  { key: 'settings:llm.context_tokens', label: 'Контекст модели', desc: '64k рекомендован для ReAct', type: 'number', min: 1024, max: 131072, step: 1024, unit: 'ток' },
];

// Everyday groups render open; engineering groups start collapsed (accordion).
const SETTING_GROUPS = [
  { title: 'Мозг и личность', match: (k) => k.startsWith('settings:llm') || k.startsWith('settings:identity') || k.startsWith('settings:system') },
  { title: 'Чувства и мультимодальность', match: (k) => k.startsWith('interfaces:multimodality') },
  { title: 'Инструменты и MCP-мосты', collapsed: true, match: (k) => k.startsWith('interfaces:mcp') },
  { title: 'Инженерия и реверс', collapsed: true, match: (k) => k.startsWith('interfaces:debug_broker') },
];

function fieldDescriptor(key, value) {
  return SETTING_FIELDS.find(f => f.key === key) || {
    key,
    label: key.split(':').pop(),
    type: typeof value === 'boolean' ? 'bool' : typeof value === 'number' ? 'number' : 'text',
  };
}

function mk(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

let configHub = null;
const settingsDirty = new Map();
const groupOpen = new Map();
let settingsSaving = false;

function updateSaveButton() {
  const save = document.querySelector('#settings-save');
  if (!save) return;
  save.textContent = settingsSaving ? 'сохранение…' : `сохранить (${settingsDirty.size})`;
  save.disabled = settingsSaving || settingsDirty.size === 0;
}

function markSettingDirty(key, value) {
  settingsDirty.set(key, value);
  updateSaveButton();
}

async function loadSettings() {
  const list = document.querySelector('#settings-list');
  if (!list) return;
  try {
    const r = await fetch('/api/config-hub', {credentials: 'include', headers: API.headers()});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const hub = await r.json();
    if (!hub || (!hub.ok && !hub.values)) throw new Error('config hub недоступен');
    configHub = hub;
    renderSettings('');
  } catch (e) {
    if (settingsDirty.size) {
      setStatusLine(`не удалось обновить настройки; черновики сохранены: ${e.message}`);
      renderSettings(document.querySelector('#settings-search')?.value || '');
    } else {
      const message = mk('p', 'note', 'Сервис настроек не ответил. Повторите загрузку позже.');
      message.setAttribute('role', 'alert');
      const retry = mk('button', 'btn secondary', 'Повторить загрузку');
      retry.type = 'button';
      retry.addEventListener('click', loadSettings);
      const heading = mk('h3', '', 'Настройки недоступны');
      heading.id = 'settings-load-error-heading';
      const card = mk('div', 'card settings-load-error');
      card.setAttribute('role', 'group');
      card.setAttribute('aria-labelledby', heading.id);
      card.append(heading, message, retry);
      list.replaceChildren(card);
    }
  }
}

function flattenHub(values, prefix = '') {
  const out = [];
  for (const [key, value] of Object.entries(values || {})) {
    const path = prefix ? `${prefix}:${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      out.push(...flattenHub(value, path));
    } else {
      out.push([path, value]);
    }
  }
  return out;
}

function renderSettings(filter) {
  const list = document.querySelector('#settings-list');
  if (!list || !configHub) return;
  // config-hub returns FLAT dotted keys ('settings:llm.temperature') —
  // flattenHub is only for nested payloads; use whichever shape arrived.
  const values = configHub.values || configHub.sections || {};
  const isFlat = Object.keys(values).some(k => k.includes(':'));
  const flat = isFlat ? Object.entries(values) : flattenHub(values);
  const f = String(filter || '').trim().toLowerCase();
  const entries = flat.filter(([key, value]) => {
    if (!f) return true;
    const d = fieldDescriptor(key, value);
    return key.toLowerCase().includes(f)
      || (d.label || '').toLowerCase().includes(f)
      || (d.desc || '').toLowerCase().includes(f);
  });
  list.replaceChildren();
  if (!entries.length) list.textContent = 'ничего не найдено';

  const groups = SETTING_GROUPS.map(g => ({...g, entries: []}));
  const other = { title: 'Прочее', entries: [] };
  for (const entry of entries) {
    const group = groups.find(g => g.match(entry[0])) || other;
    group.entries.push(entry);
  }

  for (const group of [...groups, other]) {
    if (!group.entries.length) continue;
    // Search always opens matches; otherwise respect the user's fold state.
    const open = f ? true : (groupOpen.get(group.title) ?? !group.collapsed);
    const toggle = mk('button', 'group-toggle', group.title);
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', String(open));
    toggle.addEventListener('click', () => {
      groupOpen.set(group.title, !(groupOpen.get(group.title) ?? !group.collapsed));
      renderSettings(filter);
    });
    const body = mk('div', 'group-body');
    if (!open) body.setAttribute('hidden', '');
    for (const [key, value] of group.entries) {
      body.appendChild(renderField(key, settingsDirty.has(key) ? settingsDirty.get(key) : value));
    }
    const card = mk('div', 'card settings-group');
    card.appendChild(mk('h3')).appendChild(toggle);
    card.appendChild(body);
    list.appendChild(card);
  }
  const save = mk('button', 'btn');
  save.id = 'settings-save';
  save.type = 'button';
  save.addEventListener('click', saveSettings);
  list.appendChild(save);
  updateSaveButton();
}

function renderField(key, value) {
  const d = fieldDescriptor(key, value);
  const row = mk('div', 'field');
  const fl = mk('div', 'fl');
  const fn = mk('div', 'fn', d.label);
  fn.id = `setting-label-${key.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  fl.appendChild(fn);
  let description = null;
  if (d.desc) {
    description = mk('div', 'fd', d.desc);
    description.id = `${fn.id}-description`;
    fl.appendChild(description);
  }
  row.appendChild(fl);
  const associateControl = (element, label = d.label) => {
    element.setAttribute('aria-label', label);
    if (description) element.setAttribute('aria-describedby', description.id);
  };

  let control;
  if (d.type === 'bool') {
    control = mk('button', 'sw');
    control.type = 'button';
    control.setAttribute('role', 'switch');
    control.setAttribute('aria-checked', String(!!value));
    associateControl(control);
    control.addEventListener('click', () => {
      const next = control.getAttribute('aria-checked') !== 'true';
      control.setAttribute('aria-checked', String(next));
      markSettingDirty(key, next);
    });
  } else if (d.type === 'range') {
    const range = mk('input');
    range.type = 'range';
    range.min = d.min ?? 0; range.max = d.max ?? 100; range.step = d.step ?? 1;
    range.value = Number(value) || 0;
    associateControl(range, `${d.label}, ползунок`);
    const num = mk('input');
    num.type = 'number';
    num.min = range.min; num.max = range.max; num.step = range.step;
    num.value = range.value;
    associateControl(num, `${d.label}, числовое значение`);
    range.addEventListener('input', () => { num.value = range.value; markSettingDirty(key, Number(range.value)); });
    num.addEventListener('input', () => { range.value = num.value; markSettingDirty(key, Number(num.value)); });
    control = mk('span', 'fc');
    control.append(range, num);
  } else if (d.type === 'number') {
    control = mk('span', 'fc');
    const num = mk('input');
    num.type = 'number';
    num.value = Number(value) || 0;
    associateControl(num);
    if (d.min !== undefined) num.min = d.min;
    if (d.max !== undefined) num.max = d.max;
    if (d.step !== undefined) num.step = d.step;
    num.addEventListener('input', () => markSettingDirty(key, Number(num.value)));
    control.appendChild(num);
    if (d.unit) control.appendChild(mk('span', 'unit', d.unit));
  } else if (d.type === 'enum') {
    control = mk('select');
    associateControl(control);
    for (const [v, label] of (d.options || [])) control.appendChild(mk('option', '', label)).value = v;
    control.value = String(value ?? '');
    control.addEventListener('change', () => markSettingDirty(key, control.value));
  } else {
    control = mk('input');
    control.type = 'text';
    control.value = value === null || value === undefined ? '' : String(value);
    associateControl(control);
    control.addEventListener('input', () => markSettingDirty(key, control.value));
  }
  row.appendChild(control);
  return row;
}

async function saveSettings() {
  if (!configHub || !settingsDirty.size || settingsSaving) return;
  const values = Object.fromEntries(settingsDirty);
  settingsSaving = true;
  updateSaveButton();
  try {
    const r = await fetch('/api/config-hub/save', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({values, expected_revision: configHub.revision}),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (!d || d.ok !== true) throw new Error(d?.error || 'сервер не подтвердил сохранение');
    if (d.unknown?.length || d.missing?.length) {
      throw new Error(`не записаны ключи: ${[...(d.unknown || []), ...(d.missing || [])].join(', ')}`);
    }
    for (const [key, savedValue] of Object.entries(values)) {
      if (settingsDirty.get(key) === savedValue) settingsDirty.delete(key);
    }
    if (typeof d.revision === 'string') configHub.revision = d.revision;
    updateSaveButton();
    // JAWL reads settings.yaml at startup: apply means save + agent restart.
    // The hub itself reports restart_required; honor it automatically so the
    // UI never shows stale "not applied" values.
    if (d.restart_required) {
      setStatusLine('настройки сохранены — перезапускаю JAWL…');
      try {
        const restart = await fetch('/api/jawl/restart', {
          method: 'POST', credentials: 'include', headers: API.headers(), body: '{}'});
        if (!restart.ok) throw new Error(`HTTP ${restart.status}`);
        const result = await restart.json();
        if (!result || result.ok !== true) {
          throw new Error(result?.error || 'сервер не подтвердил перезапуск');
        }
        setStatusLine(`JAWL перезапускается с новыми настройками…${settingsDirty.size ? '; остались несохранённые черновики' : ''}`);
      } catch (e) {
        setStatusLine(`сохранено, но перезапуск не удался: ${e.message}${settingsDirty.size ? '; остались несохранённые черновики' : ''}`);
      }
    } else {
      setStatusLine(`настройки сохранены${settingsDirty.size ? '; остались несохранённые черновики' : ''}`);
    }
    await loadSettings();
  } catch (e) {
    setStatusLine('не сохранено; черновики сохранены: ' + e.message);
    alert('Ошибка сохранения: ' + e.message);
  } finally {
    settingsSaving = false;
    updateSaveButton();
  }
}

function setStatusLine(text) {
  const el = document.querySelector('#conn-status');
  if (el) el.textContent = text;
}

document.querySelector('#settings-search')?.addEventListener('input', (e) => {
  renderSettings(e.target.value);
});

// Shared microphone capture configuration. Values are saved through the
// capture lease endpoint and are read by the server on the next mic acquire.
const MIC_CAPTURE_FIELDS = {
  gate_open: '#mic-gate-open',
  gate_close: '#mic-gate-close',
  silence_ms: '#mic-silence-ms',
  pre_roll_ms: '#mic-pre-roll-ms',
};
let micCaptureRevision = null;
let micCaptureWritable = false;
let micCaptureLoading = false;
let micCaptureSaving = false;
let micCaptureDirty = false;
let micCaptureNeedsReload = false;

function micCaptureControls() {
  return Object.fromEntries(Object.entries(MIC_CAPTURE_FIELDS).map(([key, selector]) => [
    key, document.querySelector(selector),
  ]));
}

function micCaptureValues() {
  return Object.fromEntries(Object.entries(micCaptureControls()).map(([key, input]) => [
    key, input?.value.trim() ? Number(input.value) : Number.NaN,
  ]));
}

function setMicCaptureStatus(message) {
  const status = document.querySelector('#mic-capture-disabled');
  if (status) status.textContent = message;
}

function setMicCaptureError(message) {
  const error = document.querySelector('#mic-capture-error');
  if (!error) return;
  error.textContent = message;
  error.hidden = !message;
}

function updateMicCaptureControls() {
  const fieldset = document.querySelector('#mic-capture-fields');
  const save = document.querySelector('#mic-capture-save');
  const reload = document.querySelector('#mic-capture-reload');
  if (fieldset) fieldset.disabled = !micCaptureWritable || micCaptureLoading || micCaptureSaving;

  const values = micCaptureValues();
  const controls = micCaptureControls();
  const individuallyValid = Object.values(controls).every(input => input && input.checkValidity());
  const thresholdsValid = Number.isFinite(values.gate_open)
    && Number.isFinite(values.gate_close) && values.gate_close < values.gate_open;
  if (micCaptureDirty && !individuallyValid) {
    setMicCaptureError('Заполните все поля и проверьте допустимые диапазоны.');
  } else if (micCaptureDirty && !thresholdsValid) {
    setMicCaptureError('Порог закрытия должен быть ниже порога открытия.');
  }
  controls.gate_open?.setAttribute('aria-invalid', String(!controls.gate_open?.checkValidity() || !thresholdsValid));
  controls.gate_close?.setAttribute('aria-invalid', String(!controls.gate_close?.checkValidity() || !thresholdsValid));
  for (const key of ['silence_ms', 'pre_roll_ms']) {
    controls[key]?.setAttribute('aria-invalid', String(!controls[key]?.checkValidity()));
  }
  if (save) {
    save.disabled = !micCaptureWritable || micCaptureLoading || micCaptureSaving
      || !micCaptureDirty || !individuallyValid || !thresholdsValid || micCaptureNeedsReload;
    save.setAttribute('aria-busy', String(micCaptureSaving));
    save.textContent = micCaptureSaving ? 'Сохранение…' : 'Сохранить';
  }
  if (reload) {
    reload.hidden = !micCaptureNeedsReload;
    reload.disabled = !micCaptureWritable || micCaptureLoading || micCaptureSaving;
  }
}

async function waitForMicCaptureSession() {
  const deadline = Date.now() + 5_000;
  while (!API.csrf && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  return Boolean(API.csrf);
}

async function loadMicCaptureSettings() {
  const fieldset = document.querySelector('#mic-capture-fields');
  if (!fieldset) return;
  micCaptureLoading = true;
  setMicCaptureError('');
  setMicCaptureStatus('Загрузка настроек захвата…');
  updateMicCaptureControls();
  try {
    let response = await fetch('/api/voice/capture', {
      credentials: 'include', headers: API.headers(), signal: AbortSignal.timeout(5_000),
    });
    if (response.status === 403) {
      if (!API.csrf) await waitForMicCaptureSession();
      if (API.csrf) {
        response = await fetch('/api/voice/capture', {
          credentials: 'include', headers: API.headers(), signal: AbortSignal.timeout(5_000),
        });
      }
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok !== true) {
      micCaptureWritable = false;
      const reason = response.status === 503
        ? 'ConfigHub недоступен. Настройка захвата отключена.'
        : result.error || `HTTP ${response.status}`;
      setMicCaptureStatus(reason);
      if (response.status !== 503) setMicCaptureError(reason);
      return;
    }
    micCaptureWritable = result.settings_writable === true;
    micCaptureRevision = result.revision;
    const settings = result.settings || {};
    for (const [key, input] of Object.entries(micCaptureControls())) {
      if (input && settings[key] !== undefined) input.value = String(settings[key]);
    }
    micCaptureDirty = false;
    micCaptureNeedsReload = false;
    setMicCaptureError('');
    setMicCaptureStatus(micCaptureWritable
      ? 'Сохранённые значения. Изменения применяются при следующем запуске микрофона.'
      : 'ConfigHub недоступен. Параметры захвата отключены.');
  } catch (error) {
    micCaptureWritable = false;
    const reason = `Не удалось загрузить настройки захвата: ${error.message}`;
    setMicCaptureStatus(reason);
    setMicCaptureError(reason);
  } finally {
    micCaptureLoading = false;
    updateMicCaptureControls();
  }
}

async function saveMicCaptureSettings() {
  if (!micCaptureWritable || !micCaptureRevision || micCaptureSaving || !micCaptureDirty) return;
  const values = micCaptureValues();
  const controls = micCaptureControls();
  if (!Object.values(controls).every(input => input?.checkValidity())
      || values.gate_close >= values.gate_open) {
    setMicCaptureError('Проверьте диапазоны: порог закрытия должен быть ниже порога открытия.');
    updateMicCaptureControls();
    return;
  }

  micCaptureSaving = true;
  setMicCaptureError('');
  setMicCaptureStatus('Сохранение настроек…');
  updateMicCaptureControls();
  try {
    const response = await fetch('/api/voice/capture', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      signal: AbortSignal.timeout(5_000),
      body: JSON.stringify({action: 'configure', settings: values, expected_revision: micCaptureRevision}),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok !== true) {
      if (response.status === 409) micCaptureNeedsReload = true;
      throw new Error(result.error || `HTTP ${response.status}`);
    }
    micCaptureRevision = result.revision;
    micCaptureDirty = false;
    setMicCaptureStatus('Сохранено. Новые значения применятся при следующем запуске микрофона.');
  } catch (error) {
    setMicCaptureError(`Не удалось сохранить настройки захвата: ${error.message}`);
    setMicCaptureStatus('Изменения не сохранены. Черновик оставлен в полях.');
  } finally {
    micCaptureSaving = false;
    updateMicCaptureControls();
  }
}

for (const input of Object.values(micCaptureControls())) {
  input?.addEventListener('input', () => {
    micCaptureDirty = true;
    setMicCaptureError('');
    setMicCaptureStatus('Есть несохранённые изменения.');
    updateMicCaptureControls();
  });
}
document.querySelector('#mic-capture-save')?.addEventListener('click', saveMicCaptureSettings);
document.querySelector('#mic-capture-reload')?.addEventListener('click', loadMicCaptureSettings);
loadMicCaptureSettings();
`````

### `desktop/app.html`

`````html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>JAWL Companion</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script type="importmap">
{
  "imports": {
    "three": "/app/node_modules/three/build/three.module.js",
    "three/addons/": "/app/node_modules/three/examples/jsm/",
    "@pixiv/three-vrm": "/app/node_modules/@pixiv/three-vrm/lib/three-vrm.module.min.js"
  }
}
</script>
<style>
  :root {
    --bg: #0a1520;
    --bg-2: #0e1c2a;
    --card: #12222f;
    --line: #1e3a4d;
    --text: #d7f0e9;
    --muted: #7ba8a0;
    --accent: #4fd1a5;
    --accent-2: #2a7770;
    --danger: #e0705f;
    --radius: 10px;
    --rail: 52px;
    --control-target: 24px;
    --focus-width: 2px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  .ui-icon {
    width: 18px; height: 18px; display: block; flex: none;
    fill: none; stroke: currentColor; stroke-width: 1.8;
    stroke-linecap: round; stroke-linejoin: round;
  }
  .hud-dock .ui-icon { width: 16px; height: 16px; }
  html, body { height: 100%; }
  body {
    font: 14px/1.45 "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    display: flex;
    overflow: hidden;
    border-radius: 12px;
  }

  /* ---- left icon rail ---- */
  nav.rail {
    width: max(var(--rail), 60px);
    background: rgba(8, 18, 28, .9);
    border-right: 1px solid var(--line);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 10px 0;
    gap: 4px;
    flex-shrink: 0;
  }
  nav.rail button {
    width: 44px; height: 44px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: var(--muted);
    font-size: 17px;
    cursor: pointer;
    display: grid;
    place-items: center;
    transition: background .15s, color .15s;
  }
  nav.rail button:hover { background: rgba(79, 209, 165, .12); color: var(--text); }
  nav.rail button.active { background: var(--accent-2); color: #eafff8; }
  nav.rail button:focus-visible,
  button:focus-visible, input:focus-visible, select:focus-visible,
  textarea:focus-visible, [role="button"]:focus-visible {
    outline: var(--focus-width) solid var(--accent);
    outline-offset: 2px;
  }
  nav.rail .spacer { flex: 1; }
  .settings-list { max-height: 420px; overflow-y: auto; overflow-x: hidden; }
  /* V.E.G.A.-style fields: label+desc left, typed control right */
  .field { display: flex; align-items: center; gap: 12px; padding: 7px 0; border-bottom: 1px solid rgba(30,58,77,.5); }
  .field:last-child { border-bottom: 0; }
  .field .fl { flex: 1; min-width: 0; }
  .field .fn { font-size: 13px; color: var(--text); }
  .field .fd { font-size: 11px; color: var(--muted); margin-top: 1px; }
  .field .fc { display: inline-flex; align-items: center; gap: 6px; }
  .field .unit { font-size: 11px; color: var(--muted); }
  .field input[type=number], .field input[type=text] {
    width: 90px; background: var(--bg); color: var(--text);
    border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font-size: 12px;
  }
  .field input[type=range] {
    width: 110px; accent-color: var(--accent);
  }
  .field input[type=text].wide { width: 170px; }
  .field select {
    background: var(--bg); color: var(--text); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 8px; font-size: 12px; max-width: 180px;
  }
  /* toggle switch (V.E.G.A. .sw) */
  .sw {
    position: relative; width: 34px; height: 18px; flex: none;
    background: #1d3346; border: 1px solid var(--line);
    border-radius: 999px; cursor: pointer; transition: background .15s;
    padding: 0; appearance: none; font: inherit;
  }
  .sw::after {
    content: ""; position: absolute; top: 2px; left: 2px;
    width: 12px; height: 12px; border-radius: 50%;
    background: var(--muted); transition: left .15s, background .15s;
  }
  .sw[aria-checked="true"] { background: rgba(79,209,165,.18); border-color: rgba(79,209,165,.4); }
  .sw[aria-checked="true"]::after { left: 17px; background: var(--accent); }

  main { position: relative; flex: 1; display: flex; flex-direction: column; min-width: 0; }
  #connection-feedback {
    position: absolute; z-index: 20; top: 48px; right: 12px;
    max-width: min(420px, calc(100% - 24px));
    padding: 9px 12px; border: 1px solid rgba(79,209,165,.5);
    border-radius: 8px; background: rgba(10,21,32,.96); color: var(--text);
    box-shadow: 0 4px 12px rgba(0,0,0,.25); font-size: 12px;
  }
  #connection-feedback.error { border-color: rgba(224,112,95,.65); color: #ffd9d2; }

  .status-strip {
    display: flex; align-items: center; gap: 12px;
    flex: 0 0 auto; min-width: 0; min-height: 26px;
    padding: 3px 10px; border-bottom: 1px solid var(--line);
    background: rgba(10,21,32,.72); color: var(--muted);
    font-size: 11px; line-height: 1.35;
  }
  .status-strip #avatar-status,
  .status-strip #sensory-health {
    position: static; display: block; min-width: 0; max-width: none;
    padding: 0; border: 0; border-radius: 0; background: transparent;
    color: inherit; font-size: inherit; line-height: inherit;
    text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .status-strip #avatar-status { flex: 0 1 34%; }
  .status-strip #sensory-health { flex: 1 1 0; }
  .status-strip #sensory-health[data-state="warn"] { color: #f0c977; }
  .status-strip #sensory-health[data-state="error"] { color: #ffd0c8; }
  .status-strip #sensory-health-compact { display: none; }

  header.top {
    height: 40px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 12px;
    border-bottom: 1px solid var(--line);
    -webkit-app-region: drag;
  }
  header.top .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
  header.top .dot.ok { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
  header.top .dot.err { background: var(--danger); }
  header.top .title { font-weight: 600; letter-spacing: .04em; font-size: 13px; }
  header.top .status { margin-left: auto; color: var(--muted); font-size: 11px; }

  /* ---- split: stage (3D) + side panel ---- */
  .split { flex: 1; display: flex; min-height: 0; }

  .stage-wrap {
    flex: 1.25;
    min-width: 0;
    position: relative;
    background: radial-gradient(ellipse at 50% 30%, #1032447a, #0a1520 70%);
  }
  #avatar-canvas { width: 100%; height: 100%; display: block; }
  .sensor-value[data-state="warn"] { color: #f0c977; }
  .sensor-value[data-state="error"] { color: #ffd0c8; }
  .sensor-value { text-align: right; }
  #avatar-caption {
    position: absolute; left: 12px; right: 12px; bottom: 10px;
    color: var(--text); font-size: 13px;
    text-shadow: 0 1px 4px #000a;
    min-height: 18px;
    opacity: .95;
    transition: opacity .4s;
  }
  #avatar-caption.dim { opacity: 0; }

  .side {
    width: 340px;
    flex-shrink: 0;
    border-left: 1px solid var(--line);
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--bg-2);
  }
  .side .section { flex: 1; overflow-y: auto; padding: 10px; display: none; }
  .side .section.active { display: block; }
  .side .section[data-section="chat"].active {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  /* ---- chat ---- */
  #chat-log {
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow-y: auto;
    padding-right: 4px;
    flex: 1;
    min-height: 0;
  }
  .msg { max-width: 88%; padding: 7px 11px; border-radius: 12px; white-space: pre-wrap; font-size: 13px; }
  .msg.user { align-self: flex-end; background: var(--accent-2); color: #eafff8; }
  .msg.assistant { align-self: flex-start; background: var(--card); border: 1px solid var(--line); }
  .msg.system { align-self: center; color: var(--muted); font-size: 11px; background: none; }
  .composer { display: flex; gap: 8px; padding: 10px 0 0; }
  .composer textarea {
    flex: 1; resize: none; background: var(--bg); color: var(--text);
    border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
    font: inherit; min-height: 42px; max-height: 110px;
  }
  .composer button, .btn {
    background: var(--accent-2); color: #eafff8; border: 0; border-radius: 8px;
    padding: 8px 14px; font: inherit; cursor: pointer;
  }
  .composer button:disabled { opacity: .4; cursor: default; }
  .composer button[aria-busy="true"], .hud-dock button[aria-busy="true"] { cursor: progress; }
  .btn.secondary { background: transparent; border: 1px solid var(--line); color: var(--muted); padding: 6px 10px; font-size: 12px; }
  .btn.danger { background: transparent; border: 1px solid rgba(224,112,95,.4); color: var(--danger); }

  /* ---- cards/rows ---- */
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 12px 14px;
    margin-bottom: 10px;
  }
  .card h3 { font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--accent); margin-bottom: 8px; }
  .card p.note { color: var(--muted); font-size: 11px; margin-top: 6px; }
  .row { display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 1px solid rgba(30,58,77,.5); }
  .row:last-child { border-bottom: 0; }
  .row .label { flex: 1; font-size: 13px; }
  .row .value { color: var(--muted); font-size: 11px; text-align: right; }
  select, input[type=text] {
    background: var(--bg); color: var(--text); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 8px; font: inherit; font-size: 12px;
  }
  .model-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .model-tile {
    border: 1px solid var(--line); border-radius: 8px; padding: 8px;
    width: 100%; color: var(--text); font: inherit;
    text-align: center; cursor: pointer; background: var(--bg);
  }
  .model-tile:hover { border-color: var(--accent-2); }
  .model-tile:active { background: var(--card); }
  .model-tile:focus-visible { outline: var(--focus-width) solid var(--accent); outline-offset: 2px; }
  .model-tile:disabled { opacity: .58; cursor: progress; }
  .model-tile.error { border-color: var(--danger); }
  .model-tile.worn { border-color: var(--accent); background: rgba(79,209,165,.08); }
  .model-tile .nm { display: block; font-size: 10px; margin-top: 4px; overflow-wrap: anywhere; }
  .model-tile .sz { display: block; font-size: 9px; color: var(--muted); }
  .model-tile .em { display: grid; place-items: center; min-height: 28px; color: var(--accent); }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
  audio { width: 100%; margin-top: 8px; height: 32px; }
  .log {
    font-family: Consolas, monospace; font-size: 11px; color: var(--muted);
    max-height: 200px; overflow-y: auto; background: var(--bg);
    border-radius: 6px; padding: 8px; white-space: pre-wrap;
  }
  #doctor-log { max-height: 280px; white-space: normal; }
  .doctor-summary {
    color: var(--muted); font-size: 10px; letter-spacing: .08em;
    text-transform: uppercase; padding: 1px 0 7px;
  }
  .doctor-row {
    display: flex; align-items: center; gap: 8px;
    padding: 5px 0; border-bottom: 1px solid rgba(30,58,77,.4);
    font: 12px/1.35 "Segoe UI", system-ui, sans-serif;
  }
  .doctor-row:last-child { border-bottom: 0; }
  .doctor-icon { width: 28px; text-align: center; color: var(--muted); font-weight: 700; font-size: 9px; letter-spacing: .02em; }
  .doctor-row.ok .doctor-icon { color: var(--accent); }
  .doctor-row.warn .doctor-icon { color: #e2b15f; }
  .doctor-row.error .doctor-icon { color: var(--danger); }
  .doctor-name { flex: 1; color: var(--text); }
  .doctor-status { color: var(--muted); font-size: 11px; text-align: right; }

  /* settings workspace: use the full window instead of a 340px column */
  body.settings-mode .stage-wrap { display: none; }
  body.settings-mode .side { width: auto; flex: 1; border-left: 0; }
  body.settings-mode .section[data-section="settings"].active {
    width: 100%; max-width: 1120px; margin: 0 auto;
    padding: 14px 20px 24px;
  }
  .settings-toolbar { display: flex; align-items: center; gap: 20px; margin-bottom: 10px; }
  .settings-toolbar .settings-heading { flex: 1; min-width: 0; }
  .settings-toolbar .settings-heading h3 { margin-bottom: 3px; }
  .settings-toolbar #settings-search { flex: none; width: min(320px, 36vw); }
  body.settings-mode #settings-list {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 12px; max-height: none; overflow: visible;
  }
  body.settings-mode #settings-list > .card { margin-bottom: 0; min-width: 0; }
  body.settings-mode #settings-list > #settings-save {
    grid-column: 1 / -1; justify-self: end; min-width: 170px;
    margin: 2px 0 0;
  }
  body.settings-mode .settings-activity { margin-top: 12px; }
  .settings-list .field { min-width: 0; align-items: flex-start; }
  .settings-list .field .fl { overflow-wrap: anywhere; }
  .settings-list .field .fc { flex-wrap: wrap; justify-content: flex-end; }
  .settings-list .field input[type=text], .settings-list .field select { max-width: 100%; }
  /* accordion: quiet foldable group headers */
  .settings-list .group-toggle {
    display: flex; width: 100%; align-items: center; gap: 8px;
    background: none; border: 0; padding: 0; color: var(--text);
    font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; text-align: left;
  }
  .settings-list .group-toggle::after {
    content: "▾"; margin-left: auto; color: var(--muted); transition: transform .15s;
  }
  .settings-list .group-toggle[aria-expanded="false"]::after { transform: rotate(-90deg); }
  .settings-list .settings-group h3 { margin: 0; }

  /* thinking indicator */
  #thinking {
    position: absolute; right: 12px; top: 8px;
    font-size: 11px; color: var(--accent);
    display: none;
  }
  #thinking.on { display: block; animation: pulse 1.2s infinite; }
  @keyframes pulse { 50% { opacity: .4; } }

  /* chat mic state */
  #mic-state {
    overflow-wrap: anywhere;
    font-size: 11px; color: var(--muted); padding: 4px 0 0; text-align: center;
    min-height: 16px;
  }
  .avatar-controls label { cursor: pointer; }
  .section[data-section=avatar] .row { flex-wrap: wrap; }
  .avatar-controls input { accent-color: var(--accent); min-height: var(--control-target); }
  .avatar-controls input[type=checkbox] { min-width: var(--control-target); }
  .avatar-controls input[type=range] { flex: 1; min-width: 0; }
  .avatar-controls input:focus-visible { outline: var(--focus-width) solid var(--accent); }
  .avatar-controls input:disabled { cursor: not-allowed; opacity: .5; }
  .avatar-controls output { color: var(--text); font: inherit; }
  .mic-capture-settings label { cursor: pointer; }
  .mic-capture-settings input:focus-visible {
    outline: var(--focus-width) solid var(--accent); outline-offset: var(--focus-width);
  }
  .mic-capture-settings input:disabled { cursor: not-allowed; }
  .mic-capture-settings fieldset { min-width: 0; border: 0; }
  .mic-capture-settings input[aria-invalid="true"] { border-color: var(--danger); }
  .mic-capture-settings .save-row { justify-content: flex-end; }
  .mic-capture-settings button[aria-busy="true"] { cursor: progress; }
  @media (max-width: 720px) {
    .status-strip { font-size: 10px; }
    nav.rail { width: 52px; }
    .split { flex-direction: column; }
    .stage-wrap { flex: 0 0 min(38vh, 280px); min-height: 220px; }
    .side { width: auto; flex: 1; min-width: 0; border-left: 0; border-top: 1px solid var(--line); }
    header.top .status { display: none; }
    .status-strip { min-height: 22px; gap: 8px; padding-inline: 8px; }
    .status-strip #avatar-status { flex-basis: 32%; }
    body.settings-mode .section[data-section="settings"].active { padding: 14px 12px 24px; }
    body.settings-mode .settings-toolbar { flex-direction: column; align-items: stretch; gap: 10px; }
    body.settings-mode .settings-toolbar #settings-search { width: 100%; }
    body.settings-mode #settings-list { grid-template-columns: minmax(0, 1fr); }
    .field { align-items: flex-start; flex-direction: column; gap: 6px; }
    .field .fc { width: 100%; flex-wrap: wrap; }
    .field select, .field input[type="text"].wide { max-width: 100%; }
  }
  @media (max-width: 360px) {
    nav.rail { width: 48px; }
    nav.rail button { width: 40px; height: 40px; }
    header.top { gap: 6px; padding: 0 8px; }
    header.top .title { font-size: 12px; }
    header.top .win-btn { margin-left: auto; padding-inline: 8px; }
  }
  @media (max-width: 400px) {
    /* At the compact minimum size, give the conversation its vertical space;
       the same reply is already visible in chat, so don't cover the avatar. */
    .stage-wrap { flex-basis: min(34vh, 200px); min-height: 160px; }
    #avatar-caption { display: none; }
    .status-strip { gap: 0; }
    .status-strip #avatar-status,
    .status-strip #sensory-health {
      position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
      overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
    }
    .status-strip #sensory-health-compact {
      display: block; flex: 1 1 auto; min-width: 0;
      overflow: visible; white-space: normal; text-overflow: clip; line-height: 1.25;
    }
    .status-strip #sensory-health-compact[data-state="warn"] { color: #f0c977; }
    .status-strip #sensory-health-compact[data-state="error"] { color: #ffd0c8; }
  }

  /* ---- Chameleon Compact HUD & OBS mode (Project Airi / N.E.K.O. style) ---- */
  header.top .win-btn {
    -webkit-app-region: no-drag;
    background: rgba(79, 209, 165, .12);
    color: var(--accent);
    border: 1px solid rgba(79, 209, 165, .35);
    border-radius: 6px;
    padding: 3px 9px;
    min-height: 24px;
    font: inherit;
    font-size: 11px;
    line-height: 1.2;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    margin-left: 8px;
  }
  header.top .win-btn:hover { background: var(--accent-2); color: #eafff8; }

  .hud-dock {
    position: absolute;
    left: 50%;
    bottom: 12px;
    transform: translateX(-50%);
    display: none;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    border-radius: 999px;
    background: rgba(10, 21, 32, .82);
    border: 1px solid rgba(79, 209, 165, .32);
    backdrop-filter: blur(8px);
    z-index: 10;
    opacity: .88;
    transition: opacity .2s ease;
  }
  .stage-wrap:hover .hud-dock,
  .hud-dock:focus-within { opacity: 1; }
  .hud-dock button {
    width: 30px; height: 30px;
    border: 0; border-radius: 50%;
    background: rgba(255,255,255,.06);
    color: var(--text);
    font-size: 14px;
    cursor: pointer;
    display: grid;
    place-items: center;
  }
  .hud-dock button:hover { background: var(--accent-2); color: #eafff8; }
  .hud-dock button:disabled { opacity: .35; cursor: default; }
  .hud-dock button:focus-visible { outline-offset: 3px; }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      scroll-behavior: auto !important;
      animation-duration: .01ms !important;
      transition-duration: .01ms !important;
    }
  }

  body.compact-mode nav.rail,
  body.compact-mode header.top,
  body.compact-mode div.side {
    display: none !important;
  }
  body.compact-mode .stage-wrap {
    flex: 1;
    width: 100%;
    height: 100%;
  }
  body.compact-mode .hud-dock {
    display: inline-flex;
  }
  body.compact-mode #avatar-caption {
    bottom: 54px;
    background: rgba(10, 21, 32, .78);
    border: 1px solid rgba(79, 209, 165, .28);
    border-radius: 12px;
    padding: 6px 10px;
    text-align: center;
  }
  body.compact-mode #avatar-caption:empty {
    display: none;
  }
  body.obs-mode {
    background: transparent !important;
  }
  body.obs-mode nav.rail,
  body.obs-mode header.top,
  body.obs-mode .status-strip,
  body.obs-mode div.side,
  body.obs-mode .hud-dock,
  body.obs-mode #avatar-status,
  body.obs-mode #sensory-health {
    display: none !important;
  }
  body.obs-mode .stage-wrap {
    background: transparent !important;
  }
</style>
</head>
<body>
  <nav class="rail" aria-label="Разделы компаньона">
    <button data-tab="chat" class="active" type="button" aria-label="Чат" aria-current="page" title="Чат"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5 8.3 8.3 0 0 1-4-.99L3 21l1.99-5.5A8.3 8.3 0 0 1 4 11.5 8.5 8.5 0 0 1 12.5 3 8.5 8.5 0 0 1 21 11.5Z"/></svg></button>
    <button data-tab="avatar" type="button" aria-label="Аватар" title="Аватар"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg></button>
    <button data-tab="voice" type="button" aria-label="Голос" title="Голос"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/></svg></button>
    <button data-tab="memory" type="button" aria-label="Память" title="Память"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M3 5.5A2.5 2.5 0 0 1 5.5 3H12v18H5.5A2.5 2.5 0 0 0 3 23.5v-18ZM21 5.5A2.5 2.5 0 0 0 18.5 3H12v18h6.5a2.5 2.5 0 0 1 2.5 2.5v-18Z"/></svg></button>
    <button data-tab="settings" type="button" aria-label="Настройки" title="Настройки"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M14.7 6.3a5 5 0 0 0-6.4 6.4L3 18l3 3 5.3-5.3a5 5 0 0 0 6.4-6.4L14 13l-3-3 3.7-3.7Z"/><path d="m4 20 2-2"/></svg></button>
    <button data-tab="system" type="button" aria-label="Система" title="Система"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.7-.7a8 8 0 0 1-1.6.9l-.3 1.8h-2.8l-.3-1.8a8 8 0 0 1-1.6-.9l-1.7.7-1.4-2.4 1.4-1.1a8 8 0 0 1 0-1.9l-1.4-1.1 1.4-2.4 1.7.7a8 8 0 0 1 1.6-.9l.3-1.8h2.8l.3 1.8a8 8 0 0 1 1.6.9l1.7-.7 1.4 2.4-1.4 1.1a8 8 0 0 1-.1 1.8Z"/></svg></button>
  </nav>

  <main>
    <header class="top">
      <span class="dot" id="conn-dot"></span>
      <span class="title">JAWL Companion</span>
      <span class="status" id="conn-status" role="status" aria-live="polite" aria-atomic="true">подключение…</span>
      <button id="toggle-compact" class="win-btn" type="button" title="Свернуть в компактный режим компаньона (Ctrl+Shift+M)">Компактно</button>
    </header>
    <div id="connection-feedback" role="status" aria-live="assertive" aria-atomic="true" hidden></div>
    <div class="status-strip" role="group" aria-label="Состояние компаньона и сенсоров">
      <span id="avatar-status">Аватар: загрузка…</span>
      <span id="sensory-health" role="status" aria-live="off" aria-atomic="true" data-state="pending">Проверяю сенсоры…</span>
      <span id="sensory-health-compact" aria-hidden="true" data-state="pending">Проверяю сенсоры…</span>
    </div>

    <div class="split">
      <!-- 3D персонаж, всегда на виду -->
      <div class="stage-wrap">
        <canvas id="avatar-canvas"></canvas>
        <span id="thinking">думаю…</span>
        <div id="avatar-caption"></div>
        <div class="hud-dock" role="group" aria-label="Быстрое управление компаньоном">
          <button id="hud-mic" type="button" aria-label="Включить или выключить микрофон" aria-describedby="mic-state" aria-pressed="false" title="Микрофон: вкл/выкл"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/></svg></button>
          <button id="hud-stop" type="button" aria-label="Остановить речь" title="Остановить речь" disabled><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="2"/></svg></button>
          <button id="hud-senses" type="button" aria-label="Приостановить или возобновить восприятие" aria-pressed="false" title="Восприятие (Экран/Звук): вкл/пауза"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg></button>
          <button id="hud-dnd" type="button" aria-label="Включить или выключить режим Не беспокоить" aria-pressed="false" title="Режим Не беспокоить (DND): вкл/выкл"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4M4 4l16 16"/></svg></button>
          <button id="hud-ghost" type="button" aria-label="Включить или выключить прозрачность для мыши" aria-pressed="false" title="Прозрачность для мыши (Click-through / Выход: Ctrl+Shift+G)"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="m5 3 14 11-7 1-3 6L5 3Z"/><path d="m12 15 4 5"/></svg></button>
          <button id="hud-pin" type="button" aria-label="Закрепить окно поверх остальных" aria-pressed="false" title="Поверх всех окон (Always on Top)"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M16 3H8l1 6-4 4v2h6v6l1 1 1-1v-6h6v-2l-4-4 1-6Z"/></svg></button>
          <button id="hud-expand" type="button" aria-label="Открыть студию и все настройки" title="Открыть студию и все настройки"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M9 8h12"/></svg></button>
        </div>
      </div>

      <!-- боковая панель функций -->
      <div class="side">
        <section class="section active" data-section="chat">
          <div id="chat-log" role="log" aria-label="История сообщений" aria-live="polite" aria-relevant="additions text"><div class="msg system">Компаньон на связи. Напиши или включи микрофон.</div></div>
          <div class="composer">
            <textarea id="chat-input" rows="1" aria-label="Сообщение компаньону" placeholder="Сообщение…"></textarea>
            <button id="chat-send" type="button" aria-label="Отправить сообщение" title="Отправить"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13"/></svg></button>
            <button id="chat-mic" type="button" aria-label="Включить или выключить микрофон" aria-describedby="mic-state" aria-pressed="false" title="Микрофон: вкл/выкл"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/></svg></button>
          </div>
          <div id="mic-state">Микрофон выключен.</div>
          <div id="mic-live-status" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>
          <button id="speech-stop" class="btn secondary" type="button" disabled>Остановить речь</button>
        </section>

        <section class="section" data-section="avatar">
          <div class="card">
            <h3>Гардероб (VRM)</h3>
            <div class="model-grid" id="wardrobe-grid">…</div>
            <p id="wardrobe-status" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></p>
            <p class="note">Свап — только модели из гардероба (bounded). Агент тоже может менять облик в разговоре.</p>
          </div>
          <div class="card">
            <h3>Выражение</h3>
            <div class="row"><span class="label">Текущее</span><span class="value" id="avatar-current">neutral</span></div>
            <div class="row"><span class="label">Тест</span>
              <button class="btn secondary" data-emotion="happy">Радость</button>
              <button class="btn secondary" data-emotion="sad">Грусть</button>
              <button class="btn secondary" data-emotion="surprised">Удивление</button>
              <button class="btn secondary" data-emotion="relaxed">Спокойствие</button>
            </div>
          </div>
          <div class="card avatar-controls" aria-labelledby="avatar-physics-title">
            <h3 id="avatar-physics-title">Движение и физика</h3>
            <div class="row">
              <label for="avatar-physics-enabled" class="label">Инерция тела и одежды</label>
              <input id="avatar-physics-enabled" type="checkbox" checked aria-describedby="avatar-physics-help">
            </div>
            <div class="row">
              <label for="avatar-physics-intensity" class="label">Сила движения</label>
              <input id="avatar-physics-intensity" type="range" min="0" max="100" step="5" value="50" aria-valuetext="50%" aria-describedby="avatar-physics-help">
              <output id="avatar-physics-value" for="avatar-physics-intensity">50%</output>
            </div>
            <div class="row">
              <label for="avatar-reduced-motion" class="label">Уменьшить движение</label>
              <input id="avatar-reduced-motion" type="checkbox" aria-describedby="avatar-physics-help">
            </div>
            <p class="note" id="avatar-physics-help">Лёгкая инерция только у моделей с подготовленным ригом. Волосы управляются родной физикой VRM. Режим уменьшенного движения системы имеет приоритет.</p>
            <p class="note" id="avatar-physics-status" role="status">Проверяем риг модели…</p>
            <p class="note" id="avatar-preferences-status" role="status"></p>
          </div>
        </section>

        <section class="section" data-section="voice">
          <div class="card">
            <h3>Синтез речи</h3>
            <div class="row"><span class="label">Провайдер</span><span class="value" id="tts-provider">—</span></div>
            <div class="row"><span class="label">Статус</span><span class="value" id="tts-status">—</span></div>
            <div class="row"><label class="label" for="tts-preview-text">Превью</label><input type="text" id="tts-preview-text" aria-label="Текст для проверки голоса" value="Привет! Это превью голоса." style="flex:2"><button class="btn secondary" id="tts-preview" type="button" aria-label="Прослушать превью голоса" title="Прослушать превью"><svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="m7 4 13 8-13 8V4Z"/></svg></button></div>
            <p class="note">Превью использует общий поток речи. Остановить его можно в чате или новым сообщением.</p>
          </div>
          <div class="card">
            <h3>Голос компаньона</h3>
            <div class="row"><span class="label">Референс</span><span class="value">Александра</span></div>
            <p class="note">Клон-голос OmniVoice: 8 с чистого монолога.</p>
          </div>
          <div class="card">
            <h3>Микрофон</h3>
            <div class="row"><label class="label" for="mic-select">Устройство</label>
              <select id="mic-select" style="max-width:190px"><option value="">по умолчанию</option></select>
            </div>
            <div class="row"><span class="label">Активен сейчас</span><span class="value" id="mic-device">—</span></div>
            <div class="row"><span class="label">ASR</span><span class="value" id="asr-status">—</span></div>
            <p class="note">GigaAM — единственный ASR. Выбор устройства запоминается между запусками.</p>
          </div>
          <div class="card mic-capture-settings" aria-labelledby="mic-capture-title">
            <h3 id="mic-capture-title">Захват микрофона</h3>
            <p class="note" id="mic-capture-help">Порог, пауза завершения реплики и запас начала применятся при следующем запуске микрофона.</p>
            <fieldset id="mic-capture-fields" disabled aria-labelledby="mic-capture-title" aria-describedby="mic-capture-help mic-capture-disabled mic-capture-error">
              <div class="field">
                <label for="mic-gate-open" class="label fl">Порог открытия</label>
                <input id="mic-gate-open" type="number" min="0.001" max="0.25" step="any" inputmode="decimal" required>
              </div>
              <div class="field">
                <label for="mic-gate-close" class="label fl">Порог закрытия</label>
                <input id="mic-gate-close" type="number" min="0.0005" max="0.25" step="any" inputmode="decimal" required>
              </div>
              <div class="field">
                <label for="mic-silence-ms" class="label fl">Тишина до конца реплики</label>
                <span class="fc"><input id="mic-silence-ms" type="number" min="300" max="5000" step="1" inputmode="numeric" required><span class="unit">мс</span></span>
              </div>
              <div class="field">
                <label for="mic-pre-roll-ms" class="label fl">Запас начала речи</label>
                <span class="fc"><input id="mic-pre-roll-ms" type="number" min="0" max="500" step="1" inputmode="numeric" required><span class="unit">мс</span></span>
              </div>
              <div class="row save-row">
                <button class="btn secondary" id="mic-capture-reload" type="button" hidden disabled>Загрузить актуальные значения</button>
                <button class="btn" id="mic-capture-save" type="button" disabled>Сохранить</button>
              </div>
            </fieldset>
            <p class="note" id="mic-capture-disabled" role="status">Загрузка настроек захвата…</p>
            <p class="note" id="mic-capture-error" role="alert" hidden></p>
          </div>
        </section>

        <section class="section" data-section="memory">
          <div class="card">
            <h3>Журнал ходов</h3>
            <div class="log" id="journal-log">…</div>
          </div>
          <div class="card">
            <h3>Память JAWL</h3>
            <div class="log" id="memory-log">…</div>
          </div>
        </section>

        <section class="section" data-section="system">
          <div class="card" aria-labelledby="sensor-health-title">
            <h3 id="sensor-health-title">Сенсорные источники</h3>
            <div class="row"><span class="label">Микрофон</span><span class="value sensor-value" id="sensor-mic">проверка…</span></div>
            <div class="row"><span class="label">Экран</span><span class="value sensor-value" id="sensor-screen">проверка…</span></div>
            <div class="row"><span class="label">Системный звук</span><span class="value sensor-value" id="sensor-loopback">проверка…</span></div>
            <p class="note" id="sensor-loopback-device">Устройство не выбрано</p>
            <p class="note" id="sensor-asr-status" role="status" aria-live="off">ASR системного звука не проверен</p>
            <p class="note" id="sensor-history-status" role="status" aria-live="off">Сенсорная история не проверена</p>
            <p class="note" id="sensor-soundscape-status">Музыкальный анализатор не проверен</p>
            <p class="note" id="sensor-audio-description-status" role="status" aria-live="off">Описатель системного звука не проверен</p>
            <div class="row"><span class="label">Инициатива</span><span class="value sensor-value" id="sensor-attention">проверка…</span></div>
            <p class="note">Статус обновляется автоматически. «Пауза» и «Не беспокоить» не означают сбой.</p>
          </div>
          <div class="card">
            <h3>Сервисы</h3>
            <div class="row"><span class="label">Мозг JAWL</span><span class="value" id="svc-brain">—</span></div>
            <div class="row"><span class="label">Панель</span><span class="value" id="svc-panel">—</span></div>
            <div class="row"><span class="label">TTS</span><span class="value" id="svc-tts">—</span></div>
            <div class="row"><span class="label">JAWL-агент</span><span class="value" id="svc-jawl">—</span></div>
            <p class="note" id="svc-jawl-activity" role="status" aria-live="polite">Статус агента не проверен</p>
            <a class="btn secondary" href="/console/" id="jawl-console-link">Открыть консоль JAWL</a>
            <p class="note">Список процессов и портов скрыт; здесь показывается состояние сервисов.</p>
          </div>
          <div class="card">
            <h3>Диагностика (doctor)</h3>
            <div class="log" id="doctor-log">…</div>
          </div>
          <div class="card">
            <h3>Агент JAWL</h3>
            <div class="row"><span class="label">Перезапуск</span><button class="btn secondary" id="jawl-restart">перезапустить</button></div>
            <div class="row"><span class="label">Логи</span><button class="btn secondary" id="jawl-logs">открыть хвост</button></div>
            <div class="log" id="jawl-log" hidden></div>
          </div>
          <div class="card">
            <h3>Безопасность</h3>
            <div class="row"><span class="label">HostOS уровень</span><span class="value" id="hostos-level">—</span></div>
            <div class="row"><span class="label">Аварийный стоп</span><button class="btn danger" id="emergency-stop">СТОП</button></div>
            <p class="note">Full Access подтверждается через approvals, как в панели.</p>
          </div>
        </section>

        <section class="section settings-section" data-section="settings">
          <div class="card settings-toolbar">
            <div class="settings-heading">
              <h3>Настройки JAWL</h3>
              <p class="note">Config-hub с ревизиями: изменения применяются без перезапуска, секреты замаскированы.</p>
            </div>
            <label class="sr-only" for="settings-search">Поиск по настройкам JAWL</label>
            <input type="text" id="settings-search" placeholder="поиск по названию или ключу…">
          </div>
          <div id="settings-list" class="settings-list">…</div>
          <div class="card settings-activity">
            <h3>Активность</h3>
            <div class="row"><span class="label">Proactive-канал</span><span class="value" id="proactive-state">—</span></div>
            <div class="row"><span class="label">Ambient-память</span><span class="value" id="ambient-state">—</span></div>
            <div class="row"><span class="label">Quiet hours</span><span class="value" id="quiet-state">—</span></div>
          </div>
        </section>
      </div>
    </div>
  </main>

  <script src="app.js"></script>
  <script src="app-settings.js"></script>
  <script type="module" src="app-scene.js"></script>
</body>
</html>
`````

### `desktop/app.js`

`````javascript
// JAWL Companion app — single compact window (ADR-046).
// The 3D character lives in the left stage (app-scene.js, same origin: no
// BroadcastChannel/IPC bridge needed), all functions in the side rail.
// Talks to the companion server directly; no browser tabs, no ports in UI.

const API = {
  csrf: null,
  headers() {
    const h = {'Content-Type': 'application/json'};
    if (this.csrf) h['X-Companion-CSRF'] = this.csrf;
    return h;
  },
};

const state = {
  session: null,
  thinking: false,
  mic: null,
  micActive: false,
  voiceSessionId: null,
  voiceCorrelationId: null,
  voiceSequence: 0,
  speechGeneration: 0,
  speechPlayback: null,
  speechErrorNoticeKey: null,
};
let micStartGeneration = 0;
let micStarting = false;
function setMicButtonState(pressed, busy = false) {
  for (const button of document.querySelectorAll('#chat-mic, #hud-mic')) {
    button.setAttribute('aria-pressed', String(Boolean(pressed)));
    if (busy) button.setAttribute('aria-busy', 'true');
    else button.removeAttribute('aria-busy');
  }
}
function announceMicStatus(text) {
  const status = document.querySelector('#mic-live-status');
  if (status) status.textContent = text;
}
let pendingCaptureLease = null;

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------

async function boot() {
  try {
    const r = await fetch('/api/session', {credentials: 'include', cache: 'no-store'});
    const s = await r.json();
    API.csrf = s.csrf_token || null;
    window.__jcsrf = API.csrf;
    if (typeof URLSearchParams === 'function' && new URLSearchParams(globalThis.location?.search || '').get('openConsole') === '1') {
      globalThis.location.replace('/console/');
      return;
    }
    setConn('ok', '\u041f\u0430\u043d\u0435\u043b\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0430');
    refreshAll();
  } catch {
    setConn('err', '\u0421\u0435\u0440\u0432\u0435\u0440 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d');
  }
}

let managedProfileStopPending = false;
async function requestManagedProfileStop() {
  if (managedProfileStopPending) return;
  managedProfileStopPending = true;
  try {
    const response = await fetch('/api/profile/stop', {
      method: 'POST', credentials: 'include', headers: API.headers(), body: '{}',
    });
    const result = await response.json().catch(() => ({}));
    if (response.status !== 202 || result.status !== 'stop_requested') {
      managedProfileStopPending = false;
      setConn('err', result.error || 'Managed profile stop was not accepted', {announce: true});
      return;
    }
    setConn('ok', '\u0417\u0430\u043f\u0440\u043e\u0441 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d; \u0436\u0434\u0443 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f \u043b\u0430\u0443\u043d\u0447\u0435\u0440\u0430', {announce: true});
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      const statusResponse = await fetch('/api/profile/stop/status', {
        credentials: 'include', cache: 'no-store', headers: API.headers(),
      });
      if (!statusResponse.ok) continue;
      const status = await statusResponse.json().catch(() => ({}));
      if (status.status === 'stopping' && status.request_id === result.request_id) {
        setConn('ok', '\u041b\u0430\u0443\u043d\u0447\u0435\u0440 \u043f\u0440\u0438\u043d\u044f\u043b \u043e\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0443; \u0441\u043b\u0443\u0436\u0431\u044b \u0437\u0430\u0432\u0435\u0440\u0448\u0430\u044e\u0442\u0441\u044f', {announce: true});
        window.jawlDesktop?.acknowledgeProfileStop?.();
        return;
      }
    }
    managedProfileStopPending = false;
    setConn('err', '\u041b\u0430\u0443\u043d\u0447\u0435\u0440 \u043d\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u043b \u043e\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0443; \u043f\u0440\u043e\u0444\u0438\u043b\u044c \u043c\u043e\u0436\u0435\u0442 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0442\u044c \u0440\u0430\u0431\u043e\u0442\u0443', {announce: true});
  } catch {
    managedProfileStopPending = false;
    setConn('err', 'Managed profile stop request failed', {announce: true});
  }
}

window.jawlDesktop?.onProfileStopRequest?.(() => { void requestManagedProfileStop(); });

function setConn(kind, text, options) {
  const announce = Boolean(options?.announce);
  const dot = document.querySelector('#conn-dot');
  const label = document.querySelector('#conn-status');
  dot.className = 'dot ' + (kind === 'ok' ? 'ok' : kind === 'err' ? 'err' : '');
  label.textContent = text;
  const feedback = document.querySelector('#connection-feedback');
  if (feedback) {
    if (announce) {
      feedback.dataset.pinned = 'true';
      feedback.textContent = text;
      feedback.hidden = false;
      feedback.classList.toggle('error', kind === 'err');
    } else if (feedback.dataset.pinned !== 'true') {
      const visibleFeedback = kind === 'err';
      feedback.textContent = visibleFeedback ? text : '';
      feedback.hidden = !visibleFeedback;
      feedback.classList.toggle('error', kind === 'err');
    }
  }
}

function setVal(id, text) {
  const el = document.querySelector('#' + id);
  if (el) el.textContent = String(text);
}

// ---------------------------------------------------------------------------
// periodic refresh
// ---------------------------------------------------------------------------

let refreshTimer = null;
function startRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshAll, 10000);
}
async function refreshAll() {
  refreshStatuses();
  refreshJournal();
  refreshMemory();
}

async function refreshMemory() {
  const el = document.querySelector('#memory-log');
  if (!el) return;
  try {
    const r = await fetch('/api/jawl/memory', {credentials: 'include', headers: API.headers()});
    if (!r.ok) { el.textContent = 'память JAWL недоступна (агент не поднят?)'; return; }
    const d = await r.json();
    if (d.status === 'unavailable' || d.configured === false) {
      el.textContent = 'память JAWL не сконфигурирована в этом контуре';
      return;
    }
    const lines = [];
    const facts = d.facts || d.memories || d.items || [];
    if (Array.isArray(facts)) {
      for (const fact of facts.slice(0, 14)) {
        const text = typeof fact === 'string' ? fact : (fact.content || fact.text || fact.summary || JSON.stringify(fact));
        const when = fact.updated_at || fact.timestamp || '';
        lines.push(`${when ? String(when).slice(0, 16) + ' ' : ''}${String(text).slice(0, 100)}`);
      }
    }
    el.textContent = lines.length ? lines.join('\n')
      : 'записей пока нет — JAWL пополняет память из разговоров и heartbeat';
  } catch { el.textContent = 'память JAWL недоступна'; }
}

const DOCTOR_LABELS = {
  jawl: 'JAWL', voicemem: 'VoiceMem', asr: 'GigaAM ASR', tts: 'OmniVoice TTS',
  vision: 'Зрение', avatar: 'Аватар', hostos: 'HostOS',
  ambient_memory: 'Ambient-память', ambient_audio: 'Системный звук',
  resources: 'Ресурсы', streaming_asr: 'Streaming ASR', sensory_ingest: 'Сенсорика',
};
const DOCTOR_STATUS = {
  connected: 'подключено', online: 'онлайн', ready: 'готово', ok: 'работает',
  gigaam: 'GigaAM', desktop: 'в приложении', live: 'live',
  dry_run: 'dry-run · безопасно', configured: 'настроено, не активно',
  disabled: 'выключено', idle: 'ожидает', stopped: 'остановлено',
  mock: 'текстовый mock', not_configured: 'не настроено', offline: 'не запущено',
  degraded: 'деградация', error: 'ошибка',
};
const DOCTOR_ICON = {ok: 'OK', off: 'OFF', warn: '!', error: 'ERR'};

function renderDoctor(report) {
  const el = document.querySelector('#doctor-log');
  if (!el) return;
  const checks = report?.checks || [];
  el.replaceChildren();
  if (!checks.length) { el.textContent = '—'; return; }
  const active = checks.filter(c => c.state === 'ok').length;
  const attention = checks.filter(c => c.state === 'warn' || c.state === 'error').length;
  const summary = document.createElement('div');
  summary.className = 'doctor-summary';
  summary.textContent = attention
    ? `активно ${active} · требуют внимания ${attention}`
    : `активно ${active} · всё в порядке`;
  el.appendChild(summary);
  for (const check of checks) {
    const row = document.createElement('div');
    row.className = 'doctor-row ' + (check.state || (check.ready ? 'ok' : 'off'));
    if (check.summary) row.title = check.summary;
    const icon = document.createElement('span');
    icon.className = 'doctor-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = DOCTOR_ICON[check.state] || 'OFF';
    const name = document.createElement('span');
    name.className = 'doctor-name';
    name.textContent = DOCTOR_LABELS[check.id] || check.id;
    const status = document.createElement('span');
    status.className = 'doctor-status';
    status.textContent = DOCTOR_STATUS[check.status] || check.status;
    row.append(icon, name, status);
    el.appendChild(row);
  }
}

async function refreshStatuses() {
  try {
    const d = await (await fetch('/api/doctor', {credentials: 'include'})).json();
    const checks = {};
    (d.checks || []).forEach(c => { checks[c.id] = c; });
    setVal('svc-brain', checks.jawl ? checks.jawl.status : '—');
    setVal('svc-jawl', checks.jawl?.ready ? 'готов' : (checks.jawl?.status || '—'));
    const jawlActivity = await (await fetch('/api/jawl/activity', {
      credentials: 'include', cache: 'no-store', headers: API.headers(),
    })).json().catch(() => null);
    const activityNode = document.querySelector('#svc-jawl-activity');
    if (activityNode) {
      if (jawlActivity?.configured && jawlActivity.running) {
        const phase = jawlActivity.phase || 'unknown';
        const active = !['sleep', 'idle', 'off'].includes(phase);
        activityNode.textContent = active
          ? `JAWL работает · ${phase}${jawlActivity.step ? ` · шаг ${jawlActivity.step}` : ''}${jawlActivity.model ? ` · ${jawlActivity.model}` : ''}`
          : `JAWL запущен и ожидает события${jawlActivity.model ? ` · ${jawlActivity.model}` : ''}`;
      } else if (jawlActivity?.configured) {
        activityNode.textContent = 'JAWL остановлен';
      } else {
        activityNode.textContent = 'Текущая работа JAWL недоступна';
      }
    }
      setVal('svc-panel', '\u041f\u0430\u043d\u0435\u043b\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0430');
    const ts = await (await fetch('/api/tts/status', {credentials: 'include'})).json();
    setVal('tts-provider', ts.model || ts.provider || '—');
    setVal('tts-status', ts.status || '—');
    setVal('svc-tts', ts.status || '—');
    renderDoctor(d);
    // ASR status: is the voice lane armed?
    const vs = await (await fetch('/api/voice/status', {credentials: 'include'})).json().catch(() => ({}));
    setVal('asr-status', vs.asr || vs.streaming_asr || (vs.configured ? 'настроен' : 'выключен'));
    const att = await (await fetch('/api/attention', {credentials: 'include'})).json().catch(() => ({}));
    if (typeof att.dnd === 'boolean') {
      dndActive = att.dnd;
      setVal('proactive-state', dndActive ? 'Не беспокоить (DND)' : 'включён');
      setVal('quiet-state', att.quiet_hours || 'нет');
      syncHudToggles();
    }
    const amb = await (await fetch('/api/ambient-memory', {credentials: 'include', headers: API.headers()})).json().catch(() => ({}));
    if (typeof amb?.state?.enabled === 'boolean') {
      sensesActive = amb.state.enabled;
      setVal('ambient-state', amb.state.paused ? 'пауза' : (sensesActive ? `активна (${amb.state.observation_count || 0})` : 'выключена'));
      syncHudToggles();
    }
    const shell = await (await fetch('/api/shell/status', {
      credentials: 'include', headers: API.headers(), cache: 'no-store',
    })).json().catch(() => ({}));
    renderSensoryHealth(shell);
  } catch {
    setConn('err', '\u0421\u0435\u0440\u0432\u0435\u0440 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d');
  }
}

function renderSensoryHealth(shell) {
  const summary = document.querySelector('#sensory-health');
  if (shell?.ok !== true) {
    for (const id of ['sensor-mic', 'sensor-screen', 'sensor-loopback', 'sensor-attention']) {
      const element = document.querySelector(`#${id}`);
      if (!element) continue;
      element.textContent = 'статус недоступен';
      element.dataset.state = 'error';
    }
    const loopbackDeviceElement = document.querySelector('#sensor-loopback-device');
    if (loopbackDeviceElement) loopbackDeviceElement.textContent = 'Статус источника недоступен';
    const ambientAsrElement = document.querySelector('#sensor-asr-status');
    if (ambientAsrElement) {
      ambientAsrElement.textContent = 'Статус ASR системного звука недоступен';
      ambientAsrElement.dataset.state = 'error';
    }
    const historyElement = document.querySelector('#sensor-history-status');
    if (historyElement) {
      historyElement.textContent = 'Статус сенсорной истории недоступен';
      historyElement.dataset.state = 'error';
    }
    const soundscapeElement = document.querySelector('#sensor-soundscape-status');
    if (soundscapeElement) soundscapeElement.textContent = 'Статус музыкального анализатора недоступен';
    const audioDescriptionElement = document.querySelector('#sensor-audio-description-status');
    if (audioDescriptionElement) {
      audioDescriptionElement.textContent = 'Статус описателя системного звука недоступен';
      audioDescriptionElement.dataset.state = 'error';
    }
    if (summary) {
      summary.textContent = 'Статус сенсоров недоступен';
      summary.dataset.state = 'error';
    }
    const compactSummary = document.querySelector('#sensory-health-compact');
    if (compactSummary) {
      compactSummary.textContent = 'Сенсоры недоступны';
      compactSummary.dataset.state = 'error';
    }
    return;
  }
  const capture = shell?.capture || {};
  const visual = shell?.visual || {};
  const screen = shell?.screen || {};
  const attention = shell?.attention || {};
  const micOwner = capture.microphone_owner;
  const mic = state.micActive || micOwner
    ? `включён${micOwner === 'native' ? ' (задача)' : ''}`
    : 'выключен';
  const visualRunning = Boolean(visual.running);
  const screenRunning = Boolean(visualRunning || screen.running);
  const age = typeof visual.latest_age_ms === 'number' && Number.isFinite(visual.latest_age_ms)
    ? visual.latest_age_ms
    : null;
  const captionAge = typeof visual.caption_age_ms === 'number' && Number.isFinite(visual.caption_age_ms)
    ? visual.caption_age_ms
    : age;
  const confirmedAge = typeof visual.caption_confirmed_age_ms === 'number' && Number.isFinite(visual.caption_confirmed_age_ms)
    ? visual.caption_confirmed_age_ms
    : null;
  const captionFresh = visual.caption_fresh === true;
  const screenLabel = !screenRunning
    ? 'выключен'
    : !visualRunning
      ? 'наблюдатель активен'
    : visual.error_active
      ? 'ошибка захвата'
    : age === null
      ? 'ждёт описание'
      : !captionFresh || ((confirmedAge ?? captionAge) !== null && (confirmedAge ?? captionAge) > 6000)
        ? `описание устарело, ${Math.round((captionAge ?? age) / 1000)} с`
        : confirmedAge !== null
          ? `описание подтверждено, ${Math.round(confirmedAge / 1000)} с · модель ${Math.round((captionAge ?? 0) / 1000)} с`
          : `описание актуально, ${Math.round((captionAge ?? age) / 1000)} с`;
  const loopbackAge = typeof capture.loopback_last_chunk_age_ms === 'number' && Number.isFinite(capture.loopback_last_chunk_age_ms)
    ? capture.loopback_last_chunk_age_ms
    : null;
  const loopbackSignalState = ['digital_silence', 'nonzero_pcm_unclassified'].includes(capture.loopback_signal_window_state)
    ? capture.loopback_signal_window_state
    : 'unknown';
  const loopback = !capture.loopback_configured
    ? '\u043d\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d'
    : capture.loopback_paused
      ? '\u043f\u0430\u0443\u0437\u0430'
      : capture.loopback_running
        ? loopbackAge === null
          ? '\u043f\u043e\u0442\u043e\u043a \u0437\u0430\u043f\u0443\u0449\u0435\u043d, \u0436\u0434\u0451\u0442 \u0434\u0430\u043d\u043d\u044b\u0435'
          : loopbackAge > 3000
            ? `\u043d\u0435\u0442 \u043d\u043e\u0432\u044b\u0445 \u0447\u0430\u043d\u043a\u043e\u0432, ${Math.round(loopbackAge / 1000)} \u0441`
            : loopbackSignalState === 'digital_silence'
              ? '\u0437\u0430\u0445\u0432\u0430\u0442 \u0430\u043a\u0442\u0438\u0432\u0435\u043d: \u0446\u0438\u0444\u0440\u043e\u0432\u044b\u0435 \u043d\u0443\u043b\u0438'
              : loopbackSignalState === 'nonzero_pcm_unclassified'
                ? 'PCM \u043f\u043e\u0441\u0442\u0443\u043f\u0430\u0435\u0442, \u0437\u0432\u0443\u043a \u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d'
                : '\u0443\u0440\u043e\u0432\u0435\u043d\u044c \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d'
        : capture.loopback_error
          ? '\u043e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u0445\u0432\u0430\u0442\u0430'
          : capture.loopback_enabled
            ? '\u043e\u0436\u0438\u0434\u0430\u0435\u0442 \u0437\u0430\u043f\u0443\u0441\u043a'
            : '\u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d';
  const loopbackDeviceName = typeof capture.loopback_device === 'string' ? capture.loopback_device.trim() : '';
  const loopbackDeviceIndex = Number.isInteger(capture.loopback_device_index) ? capture.loopback_device_index : null;
  const loopbackHostApiIndex = Number.isInteger(capture.loopback_host_api_index) ? capture.loopback_host_api_index : null;
  const loopbackRate = Number.isFinite(capture.loopback_sample_rate) ? Math.round(capture.loopback_sample_rate / 1000) : null;
  const loopbackChannels = Number.isInteger(capture.loopback_channels) ? capture.loopback_channels : null;
  const loopbackSource = !capture.loopback_configured
    ? 'Источник не настроен'
    : capture.loopback_paused
      ? 'Захват приостановлен'
      : !capture.loopback_running
        ? capture.loopback_enabled ? 'Ожидает запуска захвата' : 'Захват выключен'
        : !loopbackDeviceName
          ? 'Устройство вывода не определено'
          : `Устройство: ${loopbackDeviceName}${loopbackHostApiIndex !== null || loopbackDeviceIndex !== null ? ` · WASAPI ${loopbackHostApiIndex ?? '—'} / ${loopbackDeviceIndex ?? '—'}` : ''}${loopbackRate !== null ? ` · ${loopbackRate} кГц` : ''}${loopbackChannels !== null ? ` · ${loopbackChannels} канала` : ''}`;
  const initiative = attention.dnd
    ? 'не беспокоить'
    : attention.quiet_hours_active
      ? 'тихие часы'
      : 'разрешена';
  const rows = [
    ['sensor-mic', mic, mic === 'выключен' ? 'off' : 'ok'],
    ['sensor-screen', screenLabel, visualRunning && visual.error_active ? 'error' : visualRunning && (age === null || !captionFresh || (captionAge !== null && captionAge > 6000)) ? 'warn' : screenRunning ? 'ok' : 'off'],
    ['sensor-loopback', loopback, capture.loopback_error ? 'error' : capture.loopback_running && loopbackAge !== null && loopbackAge <= 3000 && loopbackSignalState === 'nonzero_pcm_unclassified' ? 'warn' : capture.loopback_running ? 'warn' : 'off'],
    ['sensor-attention', initiative, attention.dnd || attention.quiet_hours_active ? 'off' : 'ok'],
  ];
  for (const [id, label, status] of rows) {
    const element = document.querySelector(`#${id}`);
    if (!element) continue;
    element.textContent = label;
    element.dataset.state = status;
  }
  const loopbackDeviceElement = document.querySelector('#sensor-loopback-device');
  if (loopbackDeviceElement) loopbackDeviceElement.textContent = loopbackSource;
  const ambientAsrElement = document.querySelector('#sensor-asr-status');
  if (ambientAsrElement) {
    const mode = String(capture.ambient_asr_mode || '');
    const transcriptCount = Number.isFinite(capture.ambient_asr_transcripts)
      ? Math.max(0, Math.round(capture.ambient_asr_transcripts)) : 0;
    const filteredCount = Number.isFinite(capture.ambient_asr_noise_filtered)
      ? Math.max(0, Math.round(capture.ambient_asr_noise_filtered)) : 0;
    const transcriptAge = Number.isFinite(capture.ambient_asr_last_age_ms)
      ? Math.max(0, Math.round(capture.ambient_asr_last_age_ms)) : null;
    const transcriptFresh = capture.ambient_asr_last_fresh === true
      && transcriptAge !== null && transcriptAge <= 120000;
    const asrName = mode === 'external_final_utterance' ? 'GigaAM ASR'
      : mode === 'voicemem_streaming' ? 'VoiceMem stream' : 'Loopback ASR';
    const asrStatus = !mode ? 'не подключён'
      : capture.loopback_paused ? 'захват приостановлен'
        : !capture.loopback_running ? 'ожидает запуска захвата'
          : transcriptFresh ? `есть результат · ${Math.round(transcriptAge / 1000)} с назад`
            : transcriptAge !== null ? `последняя расшифровка ${Math.round(transcriptAge / 1000)} с назад`
              : transcriptCount > 0 ? 'ожидает следующую речевую реплику'
                : 'ожидает первую речевую реплику';
    const stats = [`${transcriptCount} фрагм.`, filteredCount ? `отфильтровано ${filteredCount}` : '']
      .filter(Boolean).join(' · ');
    ambientAsrElement.textContent = `${asrName}: ${asrStatus} · ${stats}`;
    ambientAsrElement.dataset.state = !mode || capture.loopback_paused || !capture.loopback_running
      ? 'off' : transcriptFresh ? 'ok' : transcriptAge !== null ? 'warn' : 'off';
  }
  const historyElement = document.querySelector('#sensor-history-status');
  if (historyElement) {
    const history = capture.sensory_history && typeof capture.sensory_history === 'object'
      ? capture.sensory_history : null;
    const writes = history?.writes && typeof history.writes === 'object' ? history.writes : {};
    const countStatus = (suffix) => Object.entries(writes)
      .filter(([key]) => key.endsWith(`:${suffix}`))
      .reduce((sum, [, value]) => sum + (Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0), 0);
    const recorded = countStatus('recorded');
    const coalesced = countStatus('coalesced');
    const writeErrors = Number.isFinite(history?.write_errors) ? Math.max(0, Math.round(history.write_errors)) : 0;
    const lastStatus = String(history?.last_status || '');
    const lastModality = String(history?.last_modality || '');
    const persistence = history?.persistence && typeof history.persistence === 'object'
      ? history.persistence : null;
    const flushAge = Number.isFinite(persistence?.last_flush_age_seconds)
      ? Math.max(0, Math.round(persistence.last_flush_age_seconds)) : null;
    const persistenceError = String(persistence?.last_error || '');
    const errorStage = String(persistence?.last_error_stage || '');
    const persistenceErrorLabel = errorStage === 'load' ? 'архив не загружен'
      : errorStage === 'clear' ? 'ошибка очистки'
        : errorStage === 'telemetry' ? 'ошибка телеметрии'
          : 'ошибка записи';
    const flushText = persistenceError
      ? `${persistenceErrorLabel}: ${persistenceError}`
      : flushAge !== null ? `flush ${flushAge} с назад`
        : recorded + coalesced > 0 ? 'ожидает первого flush' : 'flush ещё не выполнялся';
    const historyText = !history || history.configured !== true
      ? 'сенсорный архив не подключён'
      : history.persistence?.enabled === false || lastStatus === 'disabled'
        ? 'сенсорный архив выключен'
        : `${recorded} записано · ${coalesced} объединено · ${writeErrors} ошибок`
          + (lastStatus ? ` · последнее: ${lastModality || 'сенсор'} ${lastStatus}` : ' · ожидает наблюдения')
          + ` · ${flushText}`;
    historyElement.textContent = `История: ${historyText}`;
    historyElement.dataset.state = !history || history.configured !== true || lastStatus === 'disabled'
      || history.persistence?.enabled === false
      ? 'off' : persistenceError || lastStatus === 'error' ? 'error'
        : writeErrors > 0 || (recorded + coalesced > 0 && flushAge === null) ? 'warn' : 'ok';
  }
  const soundscapeElement = document.querySelector('#sensor-soundscape-status');
  if (soundscapeElement) {
    const soundscapeCount = Number.isFinite(capture.soundscape_count) ? Math.max(0, Math.round(capture.soundscape_count)) : 0;
    const soundscapeErrors = Number.isFinite(capture.soundscape_errors) ? Math.max(0, Math.round(capture.soundscape_errors)) : 0;
    const soundscapeP95 = Number.isFinite(capture.soundscape_latency_ms_p95) ? `· p95 ${Math.round(capture.soundscape_latency_ms_p95)} ms` : '';
    const soundscapeAge = Number.isFinite(capture.soundscape_last_age_ms)
      ? Math.max(0, Math.round(capture.soundscape_last_age_ms))
      : null;
    const soundscapeFresh = capture.soundscape_last_fresh === true && soundscapeAge !== null && soundscapeAge <= 20000;
    const soundscapeTags = Array.isArray(capture.soundscape_last_tags)
      ? capture.soundscape_last_tags.filter(tag => typeof tag === 'string' && tag.trim()).slice(0, 2)
      : [];
    const soundscapeAgeText = soundscapeAge === null ? '' : `${Math.round(soundscapeAge / 1000)} с назад`;
    const soundscapeStatus = !capture.soundscape_configured
      ? 'Анализатор музыки не подключён'
      : capture.loopback_paused
        ? 'Анализ системного звука приостановлен'
        : !capture.loopback_running
          ? 'Анализатор готов; захват системного звука не запущен'
          : soundscapeFresh && capture.soundscape_last_kind === 'music'
            ? `Музыка обнаружена${soundscapeTags.length ? ` · повторяющийся тег: ${soundscapeTags.join(', ')}` : ''} · ${soundscapeAgeText}`
            : soundscapeFresh
              ? `Свежая проверка: музыка не подтверждена · ${soundscapeAgeText}`
              : soundscapeAge !== null
                ? `Нет свежей оценки музыки · последняя ${soundscapeAgeText}`
                : soundscapeCount > 0
                  ? 'Ожидает следующего аудиосегмента'
                  : 'Ожидает первого аудиосегмента';
    const soundscapeStats = [`${soundscapeCount} сегм.`, soundscapeP95.replace(/^·\s*/, ''), soundscapeErrors ? `ошибок ${soundscapeErrors}` : '']
      .filter(Boolean)
      .join(' · ');
    soundscapeElement.textContent = `YAMNet CPU: ${soundscapeStatus} · ${soundscapeStats}`;
    soundscapeElement.dataset.state = !capture.soundscape_configured || capture.loopback_paused || !capture.loopback_running
      ? 'off'
      : soundscapeFresh && capture.soundscape_last_kind === 'music'
        ? 'ok'
        : soundscapeFresh
          ? 'off'
          : soundscapeErrors > 0 && soundscapeAge === null
            ? 'error'
            : 'warn';
  }
  const audioDescriptionElement = document.querySelector('#sensor-audio-description-status');
  if (audioDescriptionElement) {
    const descriptionCount = Number.isFinite(capture.audio_description_count) ? Math.max(0, Math.round(capture.audio_description_count)) : 0;
    const descriptionErrors = Number.isFinite(capture.audio_description_errors) ? Math.max(0, Math.round(capture.audio_description_errors)) : 0;
    const descriptionSkipped = Number.isFinite(capture.audio_description_skipped) ? Math.max(0, Math.round(capture.audio_description_skipped)) : 0;
    const descriptionP95 = Number.isFinite(capture.audio_description_latency_ms_p95)
      ? `p95 ${Math.round(capture.audio_description_latency_ms_p95)} ms`
      : '';
    const descriptionAge = Number.isFinite(capture.audio_description_last_age_ms)
      ? Math.max(0, Math.round(capture.audio_description_last_age_ms))
      : null;
    const descriptionFresh = capture.audio_description_last_fresh === true && descriptionAge !== null;
    const provider = capture.audio_description_provider === 'qwen3-omni'
      ? 'Qwen3-Omni'
      : String(capture.audio_description_provider || 'Аудио');
    const kind = ({speech: 'речь', music: 'музыка', sound: 'звук', unknown: 'не распознано'})[capture.audio_description_last_kind] || 'неизвестный тип';
    const ageText = descriptionAge === null ? '' : `${Math.round(descriptionAge / 1000)} с назад`;
    const descriptionStatus = !capture.audio_description_configured
      ? 'описатель не подключён'
      : capture.loopback_paused
        ? 'анализ системного звука приостановлен'
        : !capture.loopback_running
          ? 'ожидает запуска захвата'
          : descriptionFresh
            ? `результат: ${kind} · ${ageText}`
            : descriptionAge !== null
              ? `нет свежего результата · последний ${ageText}`
              : descriptionCount > 0
                ? 'ожидает следующего аудиосегмента'
                : 'ожидает первого аудиосегмента';
    const stats = [`${descriptionCount} описаний`, descriptionP95, descriptionErrors ? `ошибок ${descriptionErrors}` : '', descriptionSkipped ? `пропущено ${descriptionSkipped}` : '']
      .filter(Boolean)
      .join(' · ');
    audioDescriptionElement.textContent = `${provider}: ${descriptionStatus} · ${stats}`;
    audioDescriptionElement.dataset.state = !capture.audio_description_configured || capture.loopback_paused || !capture.loopback_running
      ? 'off'
      : descriptionFresh
        ? 'ok'
        : descriptionErrors > 0 && descriptionCount === 0
          ? 'error'
          : 'warn';
  }
  if (!summary) return;
  const text = `Микрофон ${mic} · Экран ${screenLabel} · Системный звук ${loopback}`;
  if (summary.textContent !== text) summary.textContent = text;
  const freshnessAge = confirmedAge ?? captionAge;
  const visualStale = visualRunning && (age === null || !captionFresh || (freshnessAge !== null && freshnessAge > 6000));
  const loopbackStale = capture.loopback_running && (loopbackAge === null || loopbackAge > 3000 || loopbackSignalState !== 'signal_present');
  summary.dataset.state = capture.loopback_error || (visualRunning && visual.error_active)
    ? 'error'
    : (visualStale || loopbackStale ? 'warn' : 'ok');
  const compactScreen = !screenRunning
    ? 'выкл.'
    : visual.error_active
      ? 'ошибка'
      : age === null
      ? 'ждёт описания'
      : !captionFresh || (freshnessAge !== null && freshnessAge > 6000)
        ? `описание устарело ${Math.round((captionAge ?? age) / 1000)}с`
        : `описание ${Math.round((captionAge ?? age) / 1000)}с`;
  const compactLoopback = !capture.loopback_configured
    ? '\u043d\u0435\u0442 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438'
    : capture.loopback_paused
      ? '\u043f\u0430\u0443\u0437\u0430'
      : capture.loopback_running
        ? loopbackAge === null
          ? '\u0436\u0434\u0451\u0442 \u0434\u0430\u043d\u043d\u044b\u0445'
          : loopbackAge > 3000
            ? `\u043d\u0435\u0442 \u0441\u0432\u0435\u0436\u0438\u0445 \u0434\u0430\u043d\u043d\u044b\u0445 ${Math.round(loopbackAge / 1000)}\u0441`
            : loopbackSignalState === 'digital_silence'
              ? '\u0431\u0435\u0437 \u0441\u0438\u0433\u043d\u0430\u043b\u0430'
              : loopbackSignalState === 'nonzero_pcm_unclassified'
                ? 'PCM \u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d'
                : '\u0443\u0440\u043e\u0432\u0435\u043d\u044c \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d'
        : capture.loopback_error
          ? '\u043e\u0448\u0438\u0431\u043a\u0430'
          : capture.loopback_enabled
            ? '\u043e\u0436\u0438\u0434\u0430\u0435\u0442'
            : '\u0432\u044b\u043a\u043b.';
  const compactSummary = document.querySelector('#sensory-health-compact');
  if (compactSummary) {
    const compactMic = state.micActive || micOwner ? 'вкл.' : 'выкл.';
    const compactMusic = capture.soundscape_last_fresh === true
      && capture.soundscape_last_kind === 'music'
      && Number.isFinite(capture.soundscape_last_age_ms)
      && capture.soundscape_last_age_ms <= 20000
      ? ` · Музыка ${Math.round(Math.max(0, capture.soundscape_last_age_ms) / 1000)}с`
      : '';
    compactSummary.textContent = `Микр. ${compactMic}${compactMusic} · Экран ${compactScreen} · Звук ${compactLoopback}${attention.dnd ? ' · DND' : ''}`;
    compactSummary.dataset.state = summary.dataset.state;
    const musicTitle = compactMusic
      ? `Музыка обнаружена ${Math.round(Math.max(0, capture.soundscape_last_age_ms) / 1000)} с назад${Array.isArray(capture.soundscape_last_tags) && capture.soundscape_last_tags.length ? `; повторяющийся тег: ${capture.soundscape_last_tags.slice(0, 2).join(', ')}` : ''}`
      : capture.loopback_paused
        ? 'Анализ музыки приостановлен'
        : capture.soundscape_configured
          ? 'Нет свежего подтверждения музыки'
          : 'Анализ музыки не подключён';
    summary.title = `${text}. Инициатива: ${initiative}. ${musicTitle}.`;
    compactSummary.title = summary.title;
  }
}

async function refreshJournal() {
  const el = document.querySelector('#journal-log');
  if (!el) return;
  try {
    const r = await fetch('/api/jawl/journal?limit=12', {credentials: 'include', headers: API.headers()});
    if (!r.ok) { el.textContent = 'журнал недоступен'; return; }
    const d = await r.json();
    const items = d.events || d.journal || d.items || [];
    el.textContent = items.map(e => {
      const ts = e.timestamp || e.time || '';
      const kind = e.type || e.kind || e.event || '';
      const note = e.reason || e.text || e.summary || e.message || '';
      return `${String(ts).slice(11, 19)} ${kind} ${String(note).slice(0, 80)}`;
    }).reverse().join('\n') || '—';
  } catch { el.textContent = '—'; }
}

// ---------------------------------------------------------------------------
// rail navigation
// ---------------------------------------------------------------------------

document.querySelectorAll('nav.rail button[data-tab]').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('nav.rail button').forEach(b => b.classList.remove('active'));
    button.classList.add('active');
    document.querySelectorAll('nav.rail button').forEach(b => {
      if (b === button) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    const tab = button.dataset.tab;
    document.body.classList.toggle('settings-mode', tab === 'settings');
    document.querySelectorAll('.side .section').forEach(s =>
      s.classList.toggle('active', s.dataset.section === tab));
    if (tab === 'settings' && typeof loadSettings === 'function') loadSettings();
    if (tab === 'avatar') loadWardrobe();
  });
});

// ---------------------------------------------------------------------------
// chat
// ---------------------------------------------------------------------------

const chatLog = document.querySelector('#chat-log');
const chatInput = document.querySelector('#chat-input');
const chatSend = document.querySelector('#chat-send');
const chatMic = document.querySelector('#chat-mic');
const micState = document.querySelector('#mic-state');
const thinkingEl = document.querySelector('#thinking');
const captionEl = document.querySelector('#avatar-caption');

function addMessage(kind, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + kind;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function setThinking(on) {
  state.thinking = on;
  thinkingEl.classList.toggle('on', on);
  chatSend.disabled = on;
  window.__jawlScene?.setMotionState?.(on ? 'thinking' : 'idle');
}

function showCaption(text) {
  captionEl.textContent = text;
  captionEl.classList.remove('dim');
  clearTimeout(showCaption._t);
  showCaption._t = setTimeout(() => captionEl.classList.add('dim'), 9000);
}

// one place for a finished turn: text + face + voice
function handleEnvelope(envelope, {speak = true} = {}) {
  if (!envelope) return;
  if (envelope.text) {
    addMessage('assistant', envelope.text);
    showCaption(envelope.text);
  }
  if (!window.__jawlScene?.applyAvatarEnvelope?.(envelope)) {
    window.__jawlScene?.setEmotion?.(envelope.emotion?.id || 'neutral');
  }
  setVal('avatar-current', envelope.emotion?.id || 'neutral');
  if (speak && envelope.speak !== false && envelope.text) speakFinal(envelope);
}

async function sendChat() {
  const text = chatInput.value.trim();
  if (!text || state.thinking) return;
  cancelSpeechPlayback();
  chatInput.value = '';
  addMessage('user', text);
  setThinking(true);
  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({text}),
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let final = null;
    let audioIndex = 0;
    let audioChain = Promise.resolve();
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      let nl;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        try {
          const event = JSON.parse(line);
          if (event.type === 'final') final = event.response;
          else if (event.type === 'audio' && event.index === audioIndex) {
            audioIndex += 1;
            earlySpeech.streamPending = true;
            syncSelfTtsSuppression();
            audioChain = audioChain.then(() => playEarlyAudioEvent(event)).catch(() => {});
          }
        } catch { /* partial line */ }
      }
    }
    await audioChain.catch(() => {});
    if (final) handleEnvelope(final, {speak: earlySpeech.scheduled === 0});
    else addMessage('system', 'Ход завершился без ответа.');
  } catch (error) {
    addMessage('system', 'Ошибка связи: ' + error.message);
  } finally {
    earlySpeech.streamPending = false;
    syncSelfTtsSuppression();
    setThinking(false);
  }
}

chatSend.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

// ---------------------------------------------------------------------------
// speech: /api/tts/stream + lip sync from the played audio
// ---------------------------------------------------------------------------

let lipContext = null;
let selfTtsSuppressionActive = false;
let selfTtsSuppressionTimer = null;
let selfTtsSuppressionQueue = Promise.resolve();

function postSelfTtsSuppression(active) {
  selfTtsSuppressionQueue = selfTtsSuppressionQueue.catch(() => {}).then(() => fetch('/api/ambient-audio/playback', {
    method: 'POST',
    credentials: 'include',
    headers: API.headers(),
    body: JSON.stringify({active: Boolean(active), ttl_seconds: 30}),
    keepalive: true,
  })).catch(() => {});
}

function setSelfTtsSuppression(active) {
  const next = Boolean(active);
  if (next === selfTtsSuppressionActive) return;
  selfTtsSuppressionActive = next;
  postSelfTtsSuppression(next);
  if (selfTtsSuppressionTimer !== null) clearInterval(selfTtsSuppressionTimer);
  selfTtsSuppressionTimer = next
    ? setInterval(() => postSelfTtsSuppression(true), 10000)
    : null;
}

function syncSelfTtsSuppression() {
  const active = Boolean(
    earlySpeech?.streamPending
      || earlySpeech?.sources.size
      || state.speechPlayback?.markerLease,
  );
  setSelfTtsSuppression(active);
}

function publishSpeechState(playback, eventState) {
  const now = performance.now();
  window.dispatchEvent(new CustomEvent('jawl-speech-state', {detail: {
    state: eventState,
    generation: playback.generation,
    activeSources: playback.sources?.size || 0,
    sourcePeak: playback.sourcePeak || 0,
    elapsedMs: Math.max(0, Math.round(now - playback.startedAt)),
  }}));
}

function releaseSpeechPlayback(playback, eventState = null) {
  if (!playback || state.speechPlayback !== playback) return;
  state.speechPlayback = null;
  setSpeechStopEnabled(false);
  if (eventState === 'cancel' || eventState === 'error') cancelRemoteSpeech(playback);
  playback.abortController.abort();
  for (const source of playback.sources) {
    source.onended = null;
    try { source.stop(); } catch {}
    try { source.disconnect(); } catch {}
  }
  playback.sources.clear();
  if (playback.frameId !== null) cancelAnimationFrame(playback.frameId);
  playback.frameId = null;
  playback.analyser?.disconnect();
  playback.markerLease = false;
  syncSelfTtsSuppression();
  window.__jawlScene?.setLipLevel(0);
  window.__jawlScene?.setMotionState?.(state.mic?.heard ? 'listening' : 'idle');
  if (eventState) publishSpeechState(playback, eventState);
}

function cancelRemoteSpeech(playback) {
  if (!playback?.requestDispatched || playback.remoteCancelSent) return;
  playback.remoteCancelSent = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1500);
  try {
    void fetch('/api/tts/cancel', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({request_id: playback.requestId}),
      keepalive: true,
      signal: controller.signal,
    }).catch(() => {}).finally(() => clearTimeout(timeout));
  } catch {
    clearTimeout(timeout);
  }
}

function cancelSpeechPlayback(muted = false) {
  state.speechGeneration += 1;
  stopEarlySpeech(muted);
  releaseSpeechPlayback(state.speechPlayback, 'cancel');
}

// Speech-first: the server may push sentence WAVs before the turn ends.
// They are played immediately, and the full-text TTS call after `final` is
// skipped so the reply is never spoken twice.
const earlySpeech = {ctx: null, sources: new Set(), nextAt: 0, scheduled: 0, streamPending: false, muted: false};

function assistantSpeechActive() {
  return Boolean(state.speechPlayback) || earlySpeech.sources.size > 0;
}

function stopEarlySpeech(mute = false) {
  for (const source of earlySpeech.sources) {
    source.onended = null;
    try { source.stop(); } catch {}
    try { source.disconnect(); } catch {}
  }
  earlySpeech.sources.clear();
  earlySpeech.nextAt = 0;
  earlySpeech.scheduled = 0;
  earlySpeech.streamPending = false;
  earlySpeech.muted = mute;
  syncSelfTtsSuppression();
}

async function playEarlyAudioEvent(event) {
  if (earlySpeech.muted) return;
  if (!event || event.media_type !== 'audio/wav' || typeof event.data_base64 !== 'string') return;
  const binary = atob(event.data_base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  if (!earlySpeech.ctx) earlySpeech.ctx = new AudioContext();
  if (earlySpeech.ctx.state === 'suspended') await earlySpeech.ctx.resume();
  const buffer = await earlySpeech.ctx.decodeAudioData(bytes.buffer);
  if (!Number.isFinite(buffer?.duration) || buffer.duration <= 0 || buffer.duration > 30) return;
  const source = earlySpeech.ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(earlySpeech.ctx.destination);
  const startAt = Math.max(earlySpeech.ctx.currentTime + 0.05, earlySpeech.nextAt);
  source.start(startAt);
  earlySpeech.nextAt = startAt + buffer.duration;
  earlySpeech.scheduled += 1;
  earlySpeech.sources.add(source);
  syncSelfTtsSuppression();
  source.onended = () => {
    earlySpeech.sources.delete(source);
    syncSelfTtsSuppression();
  };
  setSpeechStopEnabled(true);
}

function setSpeechStopEnabled(enabled) {
  const button = document.querySelector('#speech-stop');
  if (button) button.disabled = !enabled;
  const hudStop = document.querySelector('#hud-stop');
  if (hudStop) hudStop.disabled = !enabled;
}

document.querySelector('#speech-stop')?.addEventListener('click', () => cancelSpeechPlayback(true));
document.querySelector('#hud-stop')?.addEventListener('click', () => cancelSpeechPlayback(true));
setSpeechStopEnabled(false);

async function speakFinal(envelope) {
  cancelSpeechPlayback();
  const generation = state.speechGeneration;
  const playback = {
    generation,
    requestId: crypto.randomUUID(),
    requestDispatched: false,
    remoteCancelSent: false,
    abortController: new AbortController(),
    sources: new Set(),
    sourcePeak: 0,
    analyser: null,
    frameId: null,
    startedAt: performance.now(),
  };
  state.speechPlayback = playback;
  setSpeechStopEnabled(true);
  try {
    const {consumeSpeechStream} = await import('./speech-stream.js');
    if (state.speechPlayback !== playback || generation !== state.speechGeneration) return;
    playback.requestDispatched = true;
    const response = await fetch('/api/tts/stream', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({text: envelope.text, request_id: playback.requestId}),
      signal: playback.abortController.signal,
    });
    if (state.speechPlayback !== playback || generation !== state.speechGeneration) return;
    if (!response.ok || !response.body) {
      const error = new Error('TTS_STREAM_UNAVAILABLE');
      error.code = 'TTS_STREAM_UNAVAILABLE';
      error.status = response.status;
      throw error;
    }
    if (!response.headers?.get?.('content-type')?.toLowerCase().includes('application/x-ndjson')) {
      const error = new Error('TTS_INVALID_CONTENT_TYPE');
      error.code = 'TTS_INVALID_CONTENT_TYPE';
      throw error;
    }
    if (!lipContext) lipContext = new AudioContext();
    if (lipContext.state === 'suspended') await lipContext.resume();
    if (state.speechPlayback !== playback || generation !== state.speechGeneration) return;
    const analyser = playback.analyser = lipContext.createAnalyser();
    analyser.fftSize = 256;
    analyser.connect(lipContext.destination);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const pump = () => {
      if (state.speechPlayback !== playback || generation !== state.speechGeneration) return;
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
      window.__jawlScene?.setLipLevel(Math.sqrt(sum / data.length) * 2.2);
      if (playback.sources.size) playback.frameId = requestAnimationFrame(pump);
      else window.__jawlScene?.setLipLevel(0);
    };
    const isCurrent = () => state.speechPlayback === playback && generation === state.speechGeneration;
    const promise = consumeSpeechStream(response, {
      audioContext: lipContext,
      signal: playback.abortController.signal,
      isCurrent,
      connectSource: source => source.connect(analyser),
      onSourceStart: source => {
        if (!isCurrent()) return;
        playback.sources.add(source);
        playback.sourcePeak = Math.max(playback.sourcePeak, playback.sources.size);
        playback.markerLease = true;
        syncSelfTtsSuppression();
        if (playback.sources.size === 1) {
          window.__jawlScene?.setMotionState?.('speaking');
          pump();
          publishSpeechState(playback, 'firstscheduled');
        } else if (playback.sources.size > (playback.reportedSourcePeak || 1)) {
          playback.reportedSourcePeak = playback.sources.size;
          publishSpeechState(playback, 'sourcespeak');
        }
      },
      onSourceEnd: source => playback.sources.delete(source),
      onStreamDone: () => { playback.streamDone = true; },
    });
    await promise;
    if (isCurrent()) {
      state.speechErrorNoticeKey = null;
      releaseSpeechPlayback(playback, 'done');
    }
  } catch (error) {
    if (state.speechPlayback === playback && generation === state.speechGeneration) {
      const cancelled = playback.abortController.signal.aborted || error?.code === 'TTS_CANCELLED';
      if (!cancelled) {
        const status = Number.isInteger(error?.status) ? ` Код: ${error.status}.` : '';
        const guidance = error?.status === 503
          ? 'TTS недоступен. Проверьте службу речи и повторите попытку.'
          : 'Попробуйте отправить ответ ещё раз.';
        const noticeKey = `${error?.status ?? error?.code ?? 'network'}:${guidance}`;
        if (state.speechErrorNoticeKey !== noticeKey) {
          state.speechErrorNoticeKey = noticeKey;
          addMessage('system', `Не удалось воспроизвести голосовой ответ. ${guidance}${status}`);
        }
      }
      releaseSpeechPlayback(playback, cancelled ? 'cancel' : 'error');
    }
  }
  finally {
    if (state.speechPlayback === playback && generation === state.speechGeneration && playback.abortController.signal.aborted) releaseSpeechPlayback(playback, 'cancel');
  }
}

// ---------------------------------------------------------------------------
// microphone: the panel's proven lane (ADR-044/045)
//   worklet PCM -> downsample 16 kHz -> PCM16 base64 -> POST /api/voice/audio
//   silence (2 s) -> POST /api/voice/end  -> responses envelope
// ---------------------------------------------------------------------------

function downsample(samples, fromRate, toRate) {
  if (fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const length = Math.floor(samples.length / ratio);
  const result = new Float32Array(length);
  let offset = 0;
  for (let i = 0; i < length; i++) {
    const next = Math.floor((i + 1) * ratio);
    let sum = 0, count = 0;
    for (let j = offset; j < next && j < samples.length; j++) { sum += samples[j]; count++; }
    result[i] = count ? sum / count : 0;
    offset = next;
  }
  return result;
}

function pcm16Base64(samples) {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  const bytes = new Uint8Array(pcm.buffer);
  let binary = '';
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
  }
  return btoa(binary);
}

chatMic.addEventListener('click', () => {
  if (micStarting || state.micActive) void stopMic();
  else void startMic();
});

// ---------------------------------------------------------------------------
// microphone device selection: enumerated labels need one permission grant,
// so we enumerate on first mic use and also on boot when already granted.
// ---------------------------------------------------------------------------

const micSelect = document.querySelector('#mic-select');

function preferredMicId() {
  return localStorage.getItem('jawl.app.micDeviceId') || '';
}
function setPreferredMicId(id) {
  localStorage.setItem('jawl.app.micDeviceId', id || '');
}
function selectDefaultFifineDevice(inputs) {
  const saved = localStorage.getItem('jawl.app.micDeviceId');
  if (saved !== null) return saved;
  const fifine = (inputs || []).find(d =>
    d && d.deviceId && d.deviceId !== 'default' && d.deviceId !== 'communications' &&
    String(d.label || '').toLowerCase().includes('fifine'));
  if (fifine) {
    setPreferredMicId(fifine.deviceId);
    return fifine.deviceId;
  }
  return '';
}

async function refreshMicDevices() {
  if (!micSelect || !navigator.mediaDevices?.enumerateDevices) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter(d => d.kind === 'audioinput');
    // labels are empty until permission is granted at least once
    micSelect.replaceChildren();
    const def = document.createElement('option');
    def.value = '';
    def.textContent = inputs.some(d => d.label) ? 'по умолчанию' : 'по умолчанию (метки появятся после первого включения)';
    micSelect.appendChild(def);
    for (const device of inputs) {
      const option = document.createElement('option');
      option.value = device.deviceId;
      option.textContent = device.label || `устройство ${device.deviceId.slice(0, 6)}`;
      micSelect.appendChild(option);
    }
    const wanted = preferredMicId() || selectDefaultFifineDevice(inputs);
    if (wanted && inputs.some(d => d.deviceId === wanted)) micSelect.value = wanted;
  } catch { /* enumeration optional */ }
}

micSelect?.addEventListener('change', () => setPreferredMicId(micSelect.value));
navigator.mediaDevices?.addEventListener?.('devicechange', refreshMicDevices);

async function startMic() {
  if (micStarting || state.micActive) return;
  micStarting = true;
  setMicButtonState(Boolean(state.micActive), true);
  announceMicStatus('Запускаю микрофон.');
  const startGeneration = ++micStartGeneration;
  let captureLease = null;
  let stream = null;
  let context = null;
  try {
    const micHelpers = await import('./voice-input.js');
    const {createVoiceDraftController} = await import('./voice-draft.js');
    const {CaptureLease, MicInputGate} = micHelpers;
    const captureId = getCaptureClientId();
    captureLease = new CaptureLease({
      captureId,
      headers: () => API.headers(),
      onLost: (error) => {
        if (state.mic?.lease === captureLease ||
            (pendingCaptureLease === captureLease && startGeneration === micStartGeneration)) {
          const mic = state.mic?.lease === captureLease ? state.mic : null;
          if (!mic || !mic.leaseLost) {
            if (mic) mic.leaseLost = true;
            addMessage('system', 'Захват остановлен: ' + error.message);
          }
          void stopMic();
        }
      },
    });
    pendingCaptureLease = captureLease;
    const lease = await captureLease.acquire();
    if (startGeneration !== micStartGeneration) { await captureLease.release(); return; }
    captureLease.startRenewal(lease.renewAfterMs);

    const wanted = preferredMicId();
    const constraints = {
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        ...(wanted ? {deviceId: {exact: wanted}} : {}),
      },
    };
    stream = await navigator.mediaDevices.getUserMedia(constraints);
    if (startGeneration !== micStartGeneration) {
      stream.getTracks().forEach(t => t.stop());
      await captureLease.release();
      return;
    }
    context = new AudioContext();
    await context.audioWorklet.addModule('/mic-processor.js');
    if (startGeneration !== micStartGeneration) {
      stream.getTracks().forEach(t => t.stop());
      await context.close().catch(() => {});
      await captureLease.release();
      return;
    }
    const source = context.createMediaStreamSource(stream);
    const gate = new AudioWorkletNode(context, 'jawl-mic-processor');
    const inputGate = new MicInputGate(captureLease.config);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(gate);
    source.connect(analyser);

    const track = stream.getAudioTracks()[0];
    setVal('mic-device', track?.label || '—');
    // labels are visible now: refresh the picker with real names
    refreshMicDevices();

    const firstUtterance = newVoiceUtterance();
    state.voiceSessionId = firstUtterance.sessionId;
    state.voiceCorrelationId = firstUtterance.correlationId;
    state.mic = {
      stream, context, gate, analyser, inputGate, helpers: micHelpers, lease: captureLease, utterance: firstUtterance,
      uploadQueue: {tail: Promise.resolve(), pending: 0}, finalizing: false, heard: false,
      pendingUploadFrames: [], pendingUploadSamples: 0,
      turnGeneration: 0, active: true, abortController: new AbortController(), flushWaiters: [],
      overlapPlayback: null, overlapStarted: false, overlapEarlySpeech: false,
      voicedMs: 0, bargeInConfirmed: false,
    };
    pendingCaptureLease = null;

    const micCapture = state.mic;
    micCapture.draftText = '';
    micCapture.drafts = createVoiceDraftController({
      getCurrent: () => state.mic === micCapture && micCapture.active &&
        micCapture.heard && !micCapture.finalizing ? {
          session_id: micCapture.utterance.sessionId,
          correlation_id: micCapture.utterance.correlationId,
          capture_id: micCapture.lease.leaseId,
          generation: micCapture.turnGeneration,
        } : null,
      request: async (payload, signal) => {
        const response = await fetch('/api/voice/draft', {
          method: 'POST', credentials: 'include', headers: API.headers(),
          body: JSON.stringify({
            ...payload,
            assistant_speaking: Boolean(micCapture.overlapStarted && !micCapture.bargeInConfirmed),
          }), signal,
        });
        micHelpers.requireVoiceResponseOk(response, 'voice/draft');
        return response.json();
      },
      onDecision: (response) => {
        if (state.mic !== micCapture || !micCapture.active) return;
        const required = Number(response?.required_ms);
        if (Number.isFinite(required) && required > 0) {
          micCapture.serverDecision = {
            required_ms: required,
            action: String(response?.duplex_action || ''),
          };
        }
        const gesture = String(response?.avatar_gesture || '');
        if (gesture && gesture !== micCapture.lastGesture && !micCapture.bargeInConfirmed) {
          micCapture.lastGesture = gesture;
          window.__jawlScene?.triggerMotion?.(gesture);
        }
      },
      onDraft: (text) => {
        micCapture.draftText = text;
        if (state.mic === micCapture && micCapture.active && micCapture.heard && !micCapture.finalizing) {
          micState.textContent = text ? 'Слышу (предварительно): ' + text.slice(0, 160) : 'Слушаю…';
        }
      },
    });
    micCapture.draftPoll = setInterval(() => { void micCapture.drafts.tick(); }, 350);
    gate.port.onmessage = (event) => {
      const mic = micCapture;
      if (state.mic !== mic || !mic.active) return;
      if (event.data?.type === 'flushed') {
        mic.flushWaiters.shift()?.();
        return;
      }
      if (!(event.data instanceof ArrayBuffer)) return;
      mic.workletChunks = Math.min(1000000, (mic.workletChunks || 0) + 1);
      mic.lastFrameAt = performance.now();
      const result = mic.inputGate.push(new Float32Array(event.data), context.sampleRate);
      if (result.opened) {
        if (!mic.heard) {
          mic.draftText = '';
          mic.overlapPlayback = state.speechPlayback;
          mic.overlapStarted = assistantSpeechActive();
          mic.overlapEarlySpeech = !state.speechPlayback && mic.overlapStarted;
          mic.voicedMs = 0;
          mic.bargeInConfirmed = false;
          mic.serverDecision = null;
          mic.lastGesture = '';
          mic.turnGeneration += 1;
          mic.drafts.reset();
          mic.drafts.resume();
        }
        mic.heard = true;
        if (!state.speechPlayback) window.__jawlScene?.setMotionState?.('listening');
        micState.textContent = mic.draftText ? 'Слышу (предварительно): ' + mic.draftText.slice(0, 160) : 'Слушаю…';
      }
      if (mic.heard && result.voiceActive && result.rms >= mic.inputGate.config.closeRms) {
        mic.voicedMs += event.data.byteLength / Float32Array.BYTES_PER_ELEMENT * 1000 / context.sampleRate;
      }
      updateMicTurn(mic);
      for (const frame of result.frames) {
        mic.pendingUploadFrames.push(frame);
        mic.pendingUploadSamples += frame.length;
      }
      if (mic.pendingUploadSamples >= Math.round(context.sampleRate * 60)) {
        const error = new Error('очередь распознавания не успевает обработать минутный буфер речи');
        voiceCaptureDiagnostic(mic, 'upload_buffer_exhausted', error);
        addMessage('system', 'Распознавание отстаёт более чем на минуту. Остановил захват, чтобы не потерять конец реплики.');
        void stopMic();
        return;
      }
      // The worklet emits ~43 ms blocks at 48 kHz. Uploading each block as a
      // separate HTTP request can outrun the local ASR/VoiceMem endpoint and
      // used to shut the microphone off at six queued requests. Batch speech
      // into ~250 ms requests while preserving the same PCM stream.
      if (mic.pendingUploadSamples >= Math.round(context.sampleRate * 0.25)) {
        flushPendingMicAudio(mic, context.sampleRate);
      }
    };

    state.mic.poll = setInterval(() => {
      const mic = state.mic;
      if (!mic || !mic.active || !mic.heard || mic.finalizing) return;
      const decision = updateMicTurn(mic);
      if (decision.action === 'commit_turn' || decision.action === 'finish_backchannel') {
        void finishUtterance();
      }
    }, 100);

    state.micActive = true;
    setMicButtonState(true);
    announceMicStatus('Микрофон включён.');
    chatMic.style.background = 'var(--accent)';
    if (typeof document !== 'undefined') {
      const hudMic = document.querySelector('#hud-mic');
      if (hudMic) hudMic.style.background = 'var(--accent)';
    }
    micState.textContent = 'Микрофон включён — говорите.';
    setVal('mic-state', 'Микрофон включён.');
  } catch (error) {
    stream?.getTracks().forEach(t => t.stop());
    if (context && context.state !== 'closed') await context.close().catch(() => {});
    await captureLease?.release();
    if (pendingCaptureLease === captureLease) pendingCaptureLease = null;
    if (startGeneration === micStartGeneration) {
      setMicButtonState(false);
      announceMicStatus('Микрофон недоступен. ' + error.message);
      micState.textContent = 'Микрофон недоступен: ' + error.message;
    }
  } finally {
    if (startGeneration === micStartGeneration) {
      micStarting = false;
      setMicButtonState(Boolean(state.micActive));
    }
  }
}

function updateMicTurn(mic) {
  if (!mic.heard || mic.finalizing) return {action: 'hold_turn'};
  const decision = mic.helpers.decideMicTurn({
    text: mic.draftText, overlap: mic.overlapStarted && !mic.bargeInConfirmed,
    voicedMs: mic.voicedMs, silenceMs: performance.now() - mic.inputGate.lastVoiceAt,
    normalSilenceMs: mic.serverDecision?.required_ms ?? mic.inputGate.config.silenceMs,
  });
  if (decision.action === 'cancel_tts' && !mic.bargeInConfirmed) {
    mic.bargeInConfirmed = true;
    // A late draft from this utterance must not cancel a newer playback owner.
    if (state.speechPlayback && state.speechPlayback === mic.overlapPlayback) cancelSpeechPlayback(true);
    else if (mic.overlapEarlySpeech) stopEarlySpeech(true);
    mic.overlapEarlySpeech = false;
  }
  return decision;
}

function getCaptureClientId() {
  return globalThis.crypto?.randomUUID?.() || `desktop-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function uploadChunk(samples, sampleRate) {
  const mic = state.mic;
  if (!mic) return;
  const utterance = mic.helpers.uploadUtteranceFor(mic);
  const payload = {
    session_id: utterance.sessionId,
    correlation_id: utterance.correlationId,
    owner: 'desktop',
    capture_id: mic.lease.leaseId,
    sample_rate: 16000,
    channels: 1,
    pcm16_base64: pcm16Base64(downsample(samples, sampleRate, 16000)),
  };
  const task = enqueueMicOperation(mic, async () => {
    const response = await fetch('/api/voice/audio', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify(payload),
      signal: mic.abortController.signal,
    });
    return mic.helpers.requireVoiceResponseOk(response, 'voice/audio');
  }, true);
  const fail = (error, reason = error?.code === 'VOICE_CAPTURE_HTTP_ERROR' ? 'http_failure'
    : error?.name === 'TypeError' ? 'transport_failure' : 'upload_failure') => {
    if (state.mic !== mic || !mic.active || mic.uploadFailed) return;
    mic.uploadFailed = true;
    try { voiceCaptureDiagnostic(mic, reason, error); }
    catch { /* optional diagnostics must never prevent capture teardown */ }
    addMessage('system', 'Захват остановлен: ' + error.message);
    void stopMic();
  };
  if (!task) {
    // Preserve the captured PCM and let the queue drain before sending more.
    mic.pendingUploadFrames.unshift(samples);
    mic.pendingUploadSamples += samples.length;
    return null;
  }
  else task.catch(fail);
  return task;
}

function flushPendingMicAudio(mic, sampleRate) {
  if (!mic || !mic.active || !mic.pendingUploadFrames?.length) return null;
  if (mic.uploadQueue.pending >= 6) {
    mic.backpressureActive = true;
    micState.textContent = 'Поток распознавания отстаёт — звук временно буферизуется.';
    return null;
  }
  const targetSamples = Math.max(1, Math.round(sampleRate * 2));
  const frames = [];
  let totalSamples = 0;
  while (mic.pendingUploadFrames.length && totalSamples < targetSamples) {
    const frame = mic.pendingUploadFrames.shift();
    frames.push(frame);
    totalSamples += frame.length;
  }
  const samples = new Float32Array(totalSamples);
  let offset = 0;
  for (const frame of frames) {
    samples.set(frame, offset);
    offset += frame.length;
  }
  mic.pendingUploadSamples = Math.max(0, mic.pendingUploadSamples - totalSamples);
  if (mic.uploadQueue.pending >= 5) mic.backpressureActive = true;
  const task = uploadChunk(samples, sampleRate);
  if (!task) {
    mic.pendingUploadFrames.unshift(...frames);
    mic.pendingUploadSamples += totalSamples;
  }
  return task;
}

function voiceCaptureDiagnostic(mic, reason, error) {
  if (typeof CustomEvent !== 'function' || typeof window.dispatchEvent !== 'function') return;
  const contextState = mic.context?.state;
  const errorName = error?.name;
  const age = performance.now() - mic.lastFrameAt;
  const detail = {
    schema_version: 1, reason,
    error_name: ['TypeError', 'AbortError', 'TimeoutError', 'Error'].includes(errorName) ? errorName : 'unknown',
    status: Number.isInteger(error?.status) && error.status >= 100 && error.status <= 599 ? error.status : null,
    context_state: ['running', 'suspended', 'closed'].includes(contextState) ? contextState : 'unknown',
    track_states: mic.stream.getAudioTracks().slice(0, 4).map(track =>
      ['live', 'ended'].includes(track.readyState) ? track.readyState : 'unknown'),
    upload_pending: Math.max(0, Math.min(6, mic.uploadQueue.pending)),
    worklet_chunks: mic.workletChunks || 0,
    last_frame_age_ms: Number.isFinite(age) ? Math.max(0, Math.min(3600000, Math.round(age))) : null,
    active: Boolean(mic.active), finalizing: Boolean(mic.finalizing),
  };
  try { window.dispatchEvent(new CustomEvent('jawl-voice-capture', {detail})); }
  catch { /* diagnostics must not prevent capture teardown */ }
}

function enqueueMicOperation(mic, operation, bounded = false) {
  const queue = mic.uploadQueue;
  if (bounded && queue.pending >= 6) return null;
  if (bounded) queue.pending += 1;
  const task = queue.tail.catch(() => {}).then(() => mic.active ? operation() : undefined);
  queue.tail = task.then(() => undefined, () => undefined).finally(() => {
    if (bounded) {
      queue.pending = Math.max(0, queue.pending - 1);
      if (queue.pending < 5 && mic.backpressureActive) {
        mic.backpressureActive = false;
        if (mic.active && mic.heard && !mic.finalizing) micState.textContent = 'Микрофон включён — говорите.';
      }
      if (mic.active && !mic.finalizing && mic.pendingUploadSamples >= Math.round((mic.context?.sampleRate || 48000) * 0.25)) {
        flushPendingMicAudio(mic, mic.context?.sampleRate || 48000);
      }
    }
  });
  return task;
}

async function drainPendingMicAudio(mic, sampleRate) {
  // Keep the old utterance identity until all captured PCM is accepted by ASR.
  while (mic.active && (mic.pendingUploadFrames.length || mic.uploadQueue.pending)) {
    if (mic.pendingUploadFrames.length && mic.uploadQueue.pending < 6) {
      flushPendingMicAudio(mic, sampleRate);
    }
    const pending = mic.uploadQueue.tail;
    await pending.catch(() => {});
    if (pending === mic.uploadQueue.tail && mic.uploadQueue.pending === 0 && !mic.pendingUploadFrames.length) break;
  }
}

function finalizeAfterMicUploads(mic, finalize) {
  const previousUploads = mic.uploadQueue.tail;
  mic.uploadQueue = {tail: Promise.resolve(), pending: 0};
  return previousUploads.catch(() => {}).then(() => mic.active ? finalize() : null);
}

function micTurnIsCurrent(mic, generation) {
  return Boolean(mic.active && state.mic === mic && mic.turnGeneration === generation);
}

function micCaptureIsCurrent(mic) {
  return Boolean(mic.active && state.mic === mic);
}

function newVoiceUtterance() {
  const id = `${Date.now()}-${++state.voiceSequence}`;
  return {sessionId: `app-mic-${id}`, correlationId: `turn-voice-${id}`};
}

async function finishUtterance() {
  const mic = state.mic;
  if (!mic || mic.finalizing || !mic.heard) return;
  mic.finalizing = true;
  mic.drafts?.finalize();
  const lastVoiceAt = mic.inputGate.lastVoiceAt;
  mic.flushDestination = mic.utterance;
  const turnGeneration = mic.turnGeneration;
  const suppressBackchannel = mic.overlapStarted && !mic.bargeInConfirmed;
  micState.textContent = 'Распознаю…';
  try {
    await flushMicWorklet(mic);
    if (!micTurnIsCurrent(mic, turnGeneration)) return;
    await drainPendingMicAudio(mic, mic.context.sampleRate);
    if (!micTurnIsCurrent(mic, turnGeneration)) return;
    const boundary = mic.helpers.completeMicFlushBoundary(mic, lastVoiceAt, newVoiceUtterance());
    if (boundary.resumed) return;
    const utterance = boundary.utterance;
    state.voiceSessionId = mic.utterance.sessionId;
    state.voiceCorrelationId = mic.utterance.correlationId;
    const data = await finalizeAfterMicUploads(mic, async () => {
      const response = await fetch('/api/voice/end', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify({
        session_id: utterance.sessionId,
        correlation_id: utterance.correlationId,
        owner: 'desktop',
        capture_id: mic.lease.leaseId,
        suppress_backchannel: suppressBackchannel,
      }),
      signal: mic.abortController.signal,
      });
      mic.helpers.requireVoiceResponseOk(response, 'voice/end');
      return response.json();
    });
    if (!data || !micCaptureIsCurrent(mic)) return;
    if (data.filtered === 'user_backchannel') window.__jawlScene?.triggerMotion?.('nod');
    if (data.transcript) addMessage('user', data.transcript);
    const answers = data.responses || [];
    const last = answers[answers.length - 1];
    if (last) handleEnvelope(last, {speak: !mic.heard});
    else if (data.error) addMessage('system', 'Голос: ' + data.error);
  } catch (error) {
    if (micTurnIsCurrent(mic, turnGeneration)) {
      addMessage('system', 'Голосовой ход не завершился: ' + error.message);
      await stopMic();
    }
  } finally {
    if (state.mic === mic && mic.active) {
      mic.flushDestination = null;
      mic.finalizing = false;
      mic.drafts?.reset();
      mic.drafts?.resume();
      micState.textContent = state.micActive ? 'Микрофон включён — говорите.' : 'Микрофон выключен.';
    }
  }
}

function flushMicWorklet(mic) {
  if (!mic.active || !mic.gate?.port) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = (flushed = true) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const index = mic.flushWaiters.indexOf(done);
      if (index >= 0) mic.flushWaiters.splice(index, 1);
      if (flushed) resolve();
      else reject(new Error('AudioWorklet не подтвердил границу реплики'));
    };
    const timer = setTimeout(() => done(false), 500);
    mic.flushWaiters.push(done);
    mic.gate.port.postMessage({type: 'flush'});
  });
}

async function stopMic() {
  const stopGeneration = ++micStartGeneration;
  micStarting = false;
  const mic = state.mic;
  const pendingLease = pendingCaptureLease;
  pendingCaptureLease = null;
  state.mic = null;
  state.micActive = false;
  setMicButtonState(false);
  announceMicStatus('Микрофон выключен.');
  cancelSpeechPlayback();
  chatMic.style.background = '';
  if (typeof document !== 'undefined') {
    const hudMic = document.querySelector('#hud-mic');
    if (hudMic) hudMic.style.background = '';
  }
  micState.textContent = 'Микрофон выключен.';
  if (mic) {
    mic.active = false;
    clearInterval(mic.draftPoll);
    mic.drafts?.stop();
    mic.abortController.abort();
    clearInterval(mic.poll);
    mic.stream.getTracks().forEach(t => t.stop());
    mic.flushWaiters.splice(0).forEach(done => done());
    await Promise.allSettled([mic.context.close(), mic.lease?.release(), pendingLease?.release()]);
  } else {
    await pendingLease?.release();
  }
  if (micStartGeneration === stopGeneration) micState.textContent = 'Микрофон выключен.';
}

// ---------------------------------------------------------------------------
// wardrobe
// ---------------------------------------------------------------------------

async function loadWardrobe() {
  const grid = document.querySelector('#wardrobe-grid');
  if (!grid) return;
  try {
    const r = await fetch('/api/avatar/wardrobe', {credentials: 'include', headers: API.headers()});
    const w = await r.json();
    grid.replaceChildren();
    const status = document.querySelector('#wardrobe-status');
    if (status) status.textContent = '';
    for (const model of (w.models || [])) {
      const modelName = String(model.model || 'Без названия');
      const isWorn = window.__jawlScene?.wornModel === modelName;
      const tile = document.createElement('button');
      tile.type = 'button';
      tile.className = 'model-tile' + (isWorn ? ' worn' : '');
      tile.setAttribute('aria-pressed', String(isWorn));
      const icon = document.createElement('span');
      icon.className = 'em';
      icon.setAttribute('aria-hidden', 'true');
      icon.innerHTML = '<svg class="ui-icon" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"></circle><path d="M4 21a8 8 0 0 1 16 0"></path></svg>';
      const name = document.createElement('span');
      name.className = 'nm';
      name.textContent = modelName;
      const size = document.createElement('span');
      size.className = 'sz';
      size.textContent = `${(Number(model.size_bytes) / 1048576).toFixed(1)} МБ`;
      tile.setAttribute('aria-label', `${modelName} ${size.textContent} — надеть модель`);
      tile.append(icon, name, document.createTextNode(' '), size);
      tile.addEventListener('click', async () => {
        tile.disabled = true;
        tile.setAttribute('aria-busy', 'true');
        if (status) status.textContent = `Надеваем модель ${modelName}.`;
        try {
          const worn = await window.__jawlScene?.wear(modelName);
          if (!worn) {
            tile.disabled = false;
            tile.classList.add('error');
            tile.setAttribute('aria-busy', 'false');
            if (status) status.textContent = `Не удалось надеть модель ${modelName}. Можно повторить.`;
            return;
          }
          await loadWardrobe();
        } catch (error) {
          tile.disabled = false;
          tile.classList.add('error');
          tile.setAttribute('aria-busy', 'false');
          if (status) status.textContent = `Не удалось надеть модель ${modelName}: ${String(error?.message || error)}.`;
        }
      });
      grid.appendChild(tile);
    }
    if (!w.count) grid.textContent = 'гардероб пуст — положи .vrm в runtime/vrm-models';
  } catch { grid.textContent = 'гардероб недоступен'; }
}
window.loadWardrobe = loadWardrobe;

document.querySelectorAll('[data-emotion]').forEach(button => {
  button.addEventListener('click', () => {
    window.__jawlScene?.setEmotion(button.dataset.emotion);
    setVal('avatar-current', button.dataset.emotion);
  });
});

// ---------------------------------------------------------------------------
// TTS preview
// ---------------------------------------------------------------------------

document.querySelector('#tts-preview')?.addEventListener('click', () => {
  const text = document.querySelector('#tts-preview-text')?.value.trim();
  if (text) void speakFinal({text});
});

// ---------------------------------------------------------------------------
// system
// ---------------------------------------------------------------------------

document.querySelector('#jawl-restart')?.addEventListener('click', async () => {
  if (!confirm('Перезапустить JAWL-агента?')) return;
  try {
    const r = await fetch('/api/jawl/restart', {method: 'POST', credentials: 'include', headers: API.headers(), body: '{}'});
    const d = await r.json();
    addMessage('system', 'JAWL: ' + (d.status || 'перезапуск запущен'));
  } catch (e) { alert('Не удалось: ' + e.message); }
});

document.querySelector('#jawl-logs')?.addEventListener('click', async () => {
  const el = document.querySelector('#jawl-log');
  el.hidden = !el.hidden;
  if (!el.hidden) {
    try {
      const response = await fetch('/api/logs/agent?tail=40', {credentials: 'include', headers: API.headers()});
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw new Error(payload.error || 'Log request failed');
      el.textContent = (payload.lines || []).join('\n') || 'Журнал пока пуст';
    } catch { el.textContent = 'логи недоступны'; }
  }
});

document.querySelector('#emergency-stop')?.addEventListener('click', async () => {
  if (!confirm('Аварийный стоп всей активности агента?')) return;
  try {
    await fetch('/api/emergency-stop', {method: 'POST', credentials: 'include', headers: API.headers(), body: '{}'});
    addMessage('system', 'Аварийный стоп выполнен.');
  } catch (e) { alert('Не удалось: ' + e.message); }
});

// ---------------------------------------------------------------------------
// Chameleon window modes: Compact HUD <-> Studio Drawer & OBS (?mode=obs)
// ---------------------------------------------------------------------------

let alwaysOnTop = false;
let clickThrough = false;
let dndActive = false;
let sensesActive = false;

function syncHudToggles() {
  if (typeof document === 'undefined') return;
  const dndBtn = document.querySelector('#hud-dnd');
  if (dndBtn) {
    dndBtn.style.background = dndActive ? 'rgba(224,112,95,.32)' : '';
    dndBtn.setAttribute('aria-pressed', String(dndActive));
  }
  const sensesBtn = document.querySelector('#hud-senses');
  if (sensesBtn) {
    sensesBtn.style.background = sensesActive ? 'var(--accent-2)' : '';
    sensesBtn.setAttribute('aria-pressed', String(sensesActive));
  }
  const ghostBtn = document.querySelector('#hud-ghost');
  if (ghostBtn) {
    ghostBtn.style.background = clickThrough ? 'var(--accent-2)' : '';
    ghostBtn.setAttribute('aria-pressed', String(clickThrough));
  }
}

async function toggleDndMode() {
  const next = !dndActive;
  try {
    const r = await fetch('/api/attention', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify({dnd: next}),
    });
    if (r.ok) {
      dndActive = next;
      setVal('proactive-state', dndActive ? 'Не беспокоить (DND)' : 'включён');
      syncHudToggles();
    }
  } catch {}
}

async function toggleSensesMode() {
  const next = !sensesActive;
  try {
    const r = await fetch('/api/ambient-memory/config', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify({mode: 'set', enabled: next}),
    });
    if (r.ok) {
      sensesActive = next;
      setVal('ambient-state', sensesActive ? 'активна' : 'пауза');
      syncHudToggles();
    }
  } catch {}
}

function syncDesktopWindowMode() {
  const compact = Boolean(document.body?.classList?.contains('compact-mode'));
  const pinBtn = document.querySelector('#hud-pin');
  if (pinBtn) {
    pinBtn.style.background = alwaysOnTop ? 'var(--accent-2)' : '';
    pinBtn.setAttribute('aria-pressed', String(alwaysOnTop));
  }
  syncHudToggles();
  try {
    window.__jawlDesktop?.setWindowMode?.({compact, alwaysOnTop, clickThrough});
  } catch {}
}

function setCompactMode(compact, {defaultPin = true} = {}) {
  const next = Boolean(compact);
  if (!next) clickThrough = false;
  if (next && defaultPin && localStorage.getItem('jawl.app.alwaysOnTop') === null) {
    alwaysOnTop = true;
  }
  document.body?.classList?.toggle('compact-mode', next);
  try { localStorage.setItem('jawl.app.compactMode', next ? '1' : '0'); } catch {}
  syncDesktopWindowMode();
  setTimeout(() => window.dispatchEvent?.(new Event('resize')), 30);
  // Also persist to electron userData via IPC (already done in syncDesktopWindowMode)
}

// Restore compact mode from localStorage on boot
try {
  const savedCompact = localStorage.getItem('jawl.app.compactMode');
  if (savedCompact === '1') {
    document.body?.classList?.add('compact-mode');
    alwaysOnTop = localStorage.getItem('jawl.app.alwaysOnTop') === '1' || localStorage.getItem('jawl.app.alwaysOnTop') === null;
    syncDesktopWindowMode();
    // Also notify Electron to resize window
    setTimeout(() => {
      syncDesktopWindowMode();
    }, 100);
  }
} catch (_) {}

function toggleAlwaysOnTop() {
  alwaysOnTop = !alwaysOnTop;
  try { localStorage.setItem('jawl.app.alwaysOnTop', alwaysOnTop ? '1' : '0'); } catch {}
  syncDesktopWindowMode();
}

function toggleClickThrough() {
  clickThrough = !clickThrough;
  syncDesktopWindowMode();
}

function toggleCompactMode() {
  setCompactMode(!document.body?.classList?.contains('compact-mode'));
}

document.querySelector('#toggle-compact')?.addEventListener('click', () => setCompactMode(true));
document.querySelector('#hud-expand')?.addEventListener('click', () => setCompactMode(false));
document.querySelector('#hud-pin')?.addEventListener('click', toggleAlwaysOnTop);
document.querySelector('#hud-ghost')?.addEventListener('click', toggleClickThrough);
document.querySelector('#hud-dnd')?.addEventListener('click', () => void toggleDndMode());
document.querySelector('#hud-senses')?.addEventListener('click', () => void toggleSensesMode());
document.querySelector('#hud-mic')?.addEventListener('click', () => {
  if (micStarting || state.micActive) void stopMic();
  else void startMic();
});

try {
  alwaysOnTop = localStorage.getItem('jawl.app.alwaysOnTop') === '1';
  const params = new URLSearchParams(globalThis.location?.search || '');
  const modeParam = params.get('mode');
  if (modeParam === 'obs') {
    document.body?.classList?.add('obs-mode');
    document.title = 'JAWL Avatar';
  } else if (modeParam === 'compact' || localStorage.getItem('jawl.app.compactMode') === '1') {
    setCompactMode(true, {defaultPin: false});
  } else if (alwaysOnTop) {
    syncDesktopWindowMode();
  }
  window.addEventListener?.('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && e.code === 'KeyM') {
      e.preventDefault();
      toggleCompactMode();
    } else if (e.ctrlKey && e.shiftKey && e.code === 'KeyG') {
      e.preventDefault();
      toggleClickThrough();
    }
  });
  // When hovering the HUD dock while clickThrough is on, temporarily allow mouse clicks on the dock!
  const hudDock = document.querySelector('.hud-dock');
  hudDock?.addEventListener('mouseenter', () => {
    if (clickThrough) {
      window.__jawlDesktop?.setWindowMode?.({
        compact: Boolean(document.body?.classList?.contains('compact-mode')),
        alwaysOnTop,
        clickThrough: false,
      });
    }
  });
  hudDock?.addEventListener('mouseleave', () => {
    if (clickThrough) {
      window.__jawlDesktop?.setWindowMode?.({
        compact: Boolean(document.body?.classList?.contains('compact-mode')),
        alwaysOnTop,
        clickThrough: true,
      });
    }
  });
} catch { /* non-browser test harness safe */ }

// ---------------------------------------------------------------------------
// go
// ---------------------------------------------------------------------------

boot();
startRefresh();
loadWardrobe();
refreshMicDevices();
if (typeof loadSettings === 'function') loadSettings();
`````

### `desktop/avatar-motion.js`

`````javascript
// Small additive motion layer. Restore its offsets before writing the next
// base pose; no Three.js dependency keeps the motion math testable alone.
const MODES = new Set(['idle', 'listening', 'thinking', 'speaking']);
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
  const weights = {idle: 1, listening: 0, thinking: 0, speaking: 0};
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
      ? {idle: 0, listening: 0, thinking: 0, speaking: 0}
      : {idle: mode === 'idle' && !speaking ? 1 : 0,
        listening: mode === 'listening' && !speaking ? 1 : 0,
        thinking: mode === 'thinking' && !speaking ? 1 : 0,
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
    // Thinking / working pose: thoughtful upper-body lean and raised forearm contemplation.
    add(upperChest, 'x', 0.038 * weights.thinking, LIMITS.upperChestX);
    add(upperChest, 'z', -0.028 * weights.thinking + Math.sin(elapsed * 0.9) * 0.012 * weights.thinking, LIMITS.upperChestZ);
    add(forearm, 'z', -0.32 * weights.thinking, LIMITS.forearmZ);
    add(hand, 'x', (0.06 + Math.sin(elapsed * 1.8) * 0.025) * weights.thinking, LIMITS.handX);
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
`````

### `desktop/avatar-motion.test.mjs`

`````javascript
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
`````

### `desktop/avatar-physics.js`

`````javascript
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
`````

### `desktop/avatar-physics.test.mjs`

`````javascript
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
`````

### `desktop/main.js`

`````javascript
// JAWL VoiceCompanion desktop app (ADR-046): ONE compact window.
// The 3D character, chat, all functions and settings live in app.html,
// served by the companion (same origin - no bridge needed).
// The legacy two-window shell (panel + avatar) stays available via
// --legacy-shell for OBS/verification runs.

const { app, BrowserWindow, shell, ipcMain, session, screen, globalShortcut, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const http = require('http');

const { controlPort } = require('./runtime-config');
const PORT = controlPort(path.join(__dirname, '..'));
const APP_URL = `http://127.0.0.1:${PORT}/app`;
const PANEL_URL = `http://127.0.0.1:${PORT}/`;
const APP_ORIGIN = new URL(APP_URL).origin;
const LEGACY = process.argv.includes('--legacy-shell');
const HEALTH_RETRIES = 90;
const HEALTH_RETRY_DELAY_MS = 2000;
const HEALTH_REQUEST_TIMEOUT_MS = 2000;
const RETRY_URL = 'jawl-desktop://retry';

let appWindow = null;
let avatarWindow = null;
let panelWindow = null;
let readinessAttempt = null;
let tray = null;
let allowWindowClose = false;
const internalPageUrls = new Set();

function internalPage(message, canRetry = false) {
  const retry = canRetry
    ? '<p><a href="jawl-desktop://retry">Повторить подключение</a></p>'
    : '';
  const html = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>JAWL Companion</title><body style="margin:0;background:#0a1520;color:#d7f0e9;font:16px system-ui,sans-serif;display:grid;min-height:100vh;place-items:center"><main style="max-width:36rem;padding:2rem"><h1>JAWL Companion</h1><p>${message}</p>${retry}</main></body>`;
  const url = `data:text/html;charset=utf-8,${encodeURIComponent(html)}`;
  internalPageUrls.add(url);
  return url;
}

const START_PAGE_URL = internalPage('Подключение к Companion…');

function isTrustedAppUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' && url.origin === APP_ORIGIN;
  } catch (_) {
    return false;
  }
}

function isSafeExternalUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:';
  } catch (_) {
    return false;
  }
}

function openExternalUrl(value) {
  if (isSafeExternalUrl(value)) {
    shell.openExternal(value).catch(() => {});
  }
}

function installNavigationGuards(window, onRetry) {
  window.webContents.on('will-navigate', (event, targetUrl) => {
    if (isTrustedAppUrl(targetUrl) || internalPageUrls.has(targetUrl)) return;
    event.preventDefault();
    if (targetUrl === RETRY_URL) {
      onRetry();
    } else {
      openExternalUrl(targetUrl);
    }
  });
  window.webContents.on('will-frame-navigate', (event) => {
    if (isTrustedAppUrl(event.url) || internalPageUrls.has(event.url)) return;
    if (event.isMainFrame && event.url === RETRY_URL) return;
    event.preventDefault();
  });
  window.webContents.on('will-redirect', (event, targetUrl) => {
    if (!isTrustedAppUrl(targetUrl)) event.preventDefault();
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    openExternalUrl(url);
    return { action: 'deny' };
  });
}

function isAudioOnlyMediaRequest(details) {
  const mediaTypes = details && details.mediaTypes;
  if (Array.isArray(mediaTypes)) {
    return mediaTypes.length > 0 && mediaTypes.every((mediaType) => mediaType === 'audio');
  }
  return details && details.mediaType === 'audio';
}

function isTrustedAudioRequest(origin, permission, details) {
  return permission === 'media'
    && isTrustedAppUrl(origin)
    && isAudioOnlyMediaRequest(details);
}

function installPermissionGuards() {
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details = {}) => {
    const requestingUrl = details.securityOrigin || details.requestingUrl || (webContents && webContents.getURL());
    callback(isTrustedAudioRequest(requestingUrl, permission, details));
  });
  session.defaultSession.setPermissionCheckHandler((_webContents, permission, requestingOrigin, details = {}) => (
    isTrustedAudioRequest(details.securityOrigin || requestingOrigin, permission, details)
  ));
}

function getRemoteWindow() {
  return LEGACY ? panelWindow : appWindow;
}

function remoteUrl() {
  return LEGACY ? PANEL_URL : APP_URL;
}

function createAppWindow() {
  // Restore persisted compact mode and window position from the Electron user data dir.
  let width = 1060, height = 720, x, y;
  try {
    const stateFile = path.join(app.getPath('userData'), 'jawl-window-state.json');
    if (require('fs').existsSync(stateFile)) {
      const saved = JSON.parse(require('fs').readFileSync(stateFile, 'utf8'));
      if (saved && typeof saved === 'object') {
        if (saved.compact) { width = 360; height = 540; }
        else {
          if (Number.isInteger(saved.width) && saved.width >= 320) width = saved.width;
          if (Number.isInteger(saved.height) && saved.height >= 420) height = saved.height;
        }
        if (Number.isInteger(saved.x) && Number.isInteger(saved.y)) {
          // Validate that the saved position is on a connected display.
          const displays = screen.getAllDisplays();
          const validDisplay = displays.some(d => {
            return saved.x >= d.bounds.x && saved.x < d.bounds.x + d.bounds.width &&
                   saved.y >= d.bounds.y && saved.y < d.bounds.y + d.bounds.height;
          });
          if (validDisplay) { x = saved.x; y = saved.y; }
        }
      }
    }
  } catch (_) {}
  const windowOpts = {
    width, height,
    minWidth: 320, minHeight: 420,
    title: 'JAWL Companion',
    backgroundColor: '#0a1520',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      // The app window is our own local companion origin (loopback, our
      // code). Sandbox off: GLTFLoader needs to fetch blob: texture URLs
      // that the sandboxed renderer rejects (blank untextured model).
      sandbox: false,
      preload: path.join(__dirname, 'panel-preload.js'),
    },
  };
  if (x !== undefined && y !== undefined) { windowOpts.x = x; windowOpts.y = y; }
  appWindow = new BrowserWindow(windowOpts);
  appWindow.on('close', (event) => {
    if (LEGACY || allowWindowClose || !tray) return;
    event.preventDefault();
    appWindow.hide();
  });
  // Persist position and size on move/resize (debounced).
  let saveTimer = null;
  const saveState = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try {
        if (!appWindow || appWindow.isDestroyed()) return;
        const bounds = appWindow.getBounds();
        const display = screen.getDisplayNearestPoint({x: bounds.x, y: bounds.y});
        const stateFile = path.join(app.getPath('userData'), 'jawl-window-state.json');
        require('fs').writeFileSync(stateFile, JSON.stringify({
          width: bounds.width, height: bounds.height,
          x: bounds.x, y: bounds.y,
          displayId: display.id,
        }), 'utf8');
      } catch (_) {}
    }, 500);
  };
  appWindow.on('moved', saveState);
  appWindow.on('resized', saveState);
  installNavigationGuards(appWindow, retryPanelReadiness);
  appWindow.loadURL(START_PAGE_URL);
  appWindow.on('closed', () => { appWindow = null; });
  // Register global shortcut for exiting click-through mode (Ctrl+Shift+G).
  try {
    globalShortcut.register('CommandOrControl+Shift+G', () => {
      if (appWindow && !appWindow.isDestroyed()) {
        appWindow.setIgnoreMouseEvents(false);
        try {
          const stateFile = path.join(app.getPath('userData'), 'jawl-window-state.json');
          let saved = {};
          if (require('fs').existsSync(stateFile)) saved = JSON.parse(require('fs').readFileSync(stateFile, 'utf8'));
          saved.clickThrough = false;
          require('fs').writeFileSync(stateFile, JSON.stringify(saved), 'utf8');
        } catch (_) {}
      }
    });
  } catch (_) {}
  return appWindow;
}

function createTray() {
  if (LEGACY || tray) return;
  try {
    const source = nativeImage.createFromPath(path.join(__dirname, '..', 'runtime', 'avatar-render.png'));
    const size = source.getSize();
    const icon = source.isEmpty() ? source : source.crop({
      x: Math.max(0, Math.floor(size.width * 0.32)),
      y: Math.max(0, Math.floor(size.height * 0.18)),
      width: Math.max(1, Math.floor(size.width * 0.36)),
      height: Math.max(1, Math.floor(size.height * 0.38)),
    }).resize({ width: 16, height: 16 });
    tray = new Tray(icon);
    tray.setToolTip('JAWL Voice Companion');
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: '\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c JAWL', click: () => {
        if (!appWindow || appWindow.isDestroyed()) createAppWindow();
        appWindow.show();
        appWindow.focus();
      } },
      { label: '\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c \u0432\u0435\u0441\u044c \u043f\u0440\u043e\u0444\u0438\u043b\u044c', click: () => {
        if (!appWindow || appWindow.isDestroyed()) {
          createAppWindow();
          appWindow.webContents.once('did-finish-load', () => {
            if (!appWindow || appWindow.isDestroyed()) return;
            appWindow.show();
            appWindow.focus();
            appWindow.webContents.send('jawl-profile-stop-request');
          });
          return;
        }
        appWindow.show();
        appWindow.focus();
        appWindow.webContents.send('jawl-profile-stop-request');
      } },
      { type: 'separator' },
      { label: '\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441 (\u0441\u043b\u0443\u0436\u0431\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0442 \u0440\u0430\u0431\u043e\u0442\u0443)', click: () => app.quit() },
    ]));
    tray.on('double-click', () => {
      if (!appWindow || appWindow.isDestroyed()) createAppWindow();
      appWindow.show();
      appWindow.focus();
    });
  } catch (error) {
    console.error('Unable to create JAWL tray icon:', error);
  }
}

function createLegacyWindows() {
  avatarWindow = new BrowserWindow({
    width: 480, height: 800, x: 100, y: 60,
    title: 'JAWL Companion — аватар',
    backgroundColor: '#001a2b26',
    webPreferences: {
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      preload: path.join(__dirname, 'avatar-preload.js'),
    },
  });
  avatarWindow.loadFile(path.join(__dirname, 'avatar.html'));
  avatarWindow.on('closed', () => { avatarWindow = null; });

  panelWindow = new BrowserWindow({
    width: 1280, height: 900, x: 620, y: 60,
    title: 'JAWL VoiceCompanion — панель',
    webPreferences: {
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      preload: path.join(__dirname, 'panel-preload.js'),
    },
  });
  installNavigationGuards(panelWindow, retryPanelReadiness);
  panelWindow.loadURL(START_PAGE_URL);
  panelWindow.on('closed', () => { panelWindow = null; });
}

function panelReady() {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ready) => {
      if (settled) return;
      settled = true;
      resolve(ready);
    };
    const request = http.get({
      host: '127.0.0.1',
      port: PORT,
      path: '/api/health',
      timeout: HEALTH_REQUEST_TIMEOUT_MS,
    }, (response) => {
      finish(response.statusCode === 200);
      response.resume();
    });
    request.on('error', () => finish(false));
    request.on('timeout', () => {
      request.destroy();
      finish(false);
    });
  });
}

async function waitForPanel(retries = HEALTH_RETRIES, delayMs = HEALTH_RETRY_DELAY_MS) {
  for (let attempt = 0; attempt < retries; attempt += 1) {
    if (await panelReady()) return true;
    if (attempt + 1 < retries) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }
  return false;
}

async function startPanelReadiness() {
  if (readinessAttempt) return readinessAttempt;
  const currentAttempt = (async () => {
    const ready = await waitForPanel();
    const window = getRemoteWindow();
    if (!window || window.isDestroyed()) return false;
    if (!ready) {
      const recoveryUrl = internalPage(`Companion не отвечает на порту ${PORT}. Запусти стек командой <code>powershell -File scripts\\run_local_bonsai_integrated.ps1</code>, затем повтори подключение.`, true);
      await window.loadURL(recoveryUrl).catch(() => {});
      return false;
    }
    await window.loadURL(remoteUrl()).catch(async () => {
      const recoveryUrl = internalPage('Не удалось открыть Companion. Проверь стек и повтори подключение.', true);
      await window.loadURL(recoveryUrl).catch(() => {});
    });
    return true;
  })();
  readinessAttempt = currentAttempt;
  try {
    return await currentAttempt;
  } finally {
    if (readinessAttempt === currentAttempt) readinessAttempt = null;
  }
}

function retryPanelReadiness() {
  void startPanelReadiness();
}

// Emotion/lip relay for the LEGACY two-window shell only.
ipcMain.on('jawl-avatar-event', (_event, payload) => {
  if (avatarWindow && !avatarWindow.isDestroyed()) {
    avatarWindow.webContents.send('jawl-avatar-event', payload);
  }
});

// Chameleon window resizing, Always-on-Top and Click-through toggle (Compact HUD <-> Studio Drawer).
ipcMain.on('jawl-window-mode', (_event, payload) => {
  if (!appWindow || appWindow.isDestroyed() || !payload || typeof payload !== 'object') return;
  const compact = Boolean(payload.compact);
  const alwaysOnTop = Boolean(payload.alwaysOnTop);
  const clickThrough = Boolean(payload.clickThrough);
  try {
    appWindow.setAlwaysOnTop?.(alwaysOnTop);
    appWindow.setIgnoreMouseEvents?.(clickThrough, { forward: true });
    if (compact) {
      appWindow.setSize?.(360, 540, true);
    } else {
      appWindow.setSize?.(1060, 720, true);
    }
    // Persist the compact/studio preference.
    try {
      const stateFile = path.join(app.getPath('userData'), 'jawl-window-state.json');
      let saved = {};
      if (require('fs').existsSync(stateFile)) saved = JSON.parse(require('fs').readFileSync(stateFile, 'utf8'));
      saved.compact = compact;
      require('fs').writeFileSync(stateFile, JSON.stringify(saved), 'utf8');
    } catch (_) {}
  } catch (_) {}
});

app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
// NOTE: no fake device: the app window records the owner's real microphone.
const debugPortArg = process.argv.find((arg) => arg.startsWith('--remote-debugging-port='));
if (debugPortArg) {
  const debugPort = debugPortArg.split('=', 2)[1];
  app.commandLine.appendSwitch('remote-debugging-port', debugPort);
  app.commandLine.appendSwitch('remote-allow-origins', `http://127.0.0.1:${debugPort}`);
} else if (process.argv.includes('--remote-debugging-port')) {
  const debugPort = process.env.JAWL_DESKTOP_DEBUG_PORT || '9222';
  app.commandLine.appendSwitch('remote-debugging-port', debugPort);
  app.commandLine.appendSwitch('remote-allow-origins', `http://127.0.0.1:${debugPort}`);
}

app.whenReady().then(async () => {
  installPermissionGuards();
  createTray();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      LEGACY ? createLegacyWindows() : createAppWindow();
      retryPanelReadiness();
    } else if (!LEGACY && appWindow && !appWindow.isDestroyed()) {
      appWindow.show();
      appWindow.focus();
    }
  });
  if (LEGACY) {
    createLegacyWindows();
  } else {
    createAppWindow();
  }
  await startPanelReadiness();
});

app.on('before-quit', () => { allowWindowClose = true; });

ipcMain.on('jawl-profile-stop-accepted', (event) => {
  if (event.sender === appWindow?.webContents) app.quit();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
`````

### `desktop/package-lock.json`

`````json
{
  "name": "jawl-desktop",
  "version": "0.1.0",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {
    "": {
      "name": "jawl-desktop",
      "version": "0.1.0",
      "dependencies": {
        "@pixiv/three-vrm": "^3.5.5",
        "three": "^0.186.1"
      },
      "devDependencies": {
        "electron": "^44.5.1"
      }
    },
    "node_modules/@electron-internal/extract-zip": {
      "version": "1.0.5",
      "resolved": "https://registry.npmjs.org/@electron-internal/extract-zip/-/extract-zip-1.0.5.tgz",
      "integrity": "sha512-+bqFCP98pLI0Tt0XQo1TmlXtwjWchISndDOxCkEcIuUgXWpBnLyRI+2DU+mesvnMMX6L1XDqYNA0lXNDHd/yiA==",
      "dev": true,
      "license": "BSD-2-Clause",
      "engines": {
        "node": ">=22.12.0"
      }
    },
    "node_modules/@electron/get": {
      "version": "5.1.0",
      "resolved": "https://registry.npmjs.org/@electron/get/-/get-5.1.0.tgz",
      "integrity": "sha512-3kSBtG8ObcTVfXanm5vVJ6UnBLEVmVsRk1M+vGqCuMBV+XLCbJYuWQful+yIy0GQDsSlK0kHEriEHn7SPk4EnA==",
      "dev": true,
      "license": "MIT",
      "dependencies": {
        "debug": "^4.1.1",
        "env-paths": "^3.0.0",
        "graceful-fs": "^4.2.11",
        "progress": "^2.0.3",
        "semver": "^7.6.3",
        "sumchecker": "^3.0.1"
      },
      "engines": {
        "node": ">=22.12.0"
      },
      "optionalDependencies": {
        "undici": "^7.24.4"
      }
    },
    "node_modules/@pixiv/three-vrm": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/three-vrm/-/three-vrm-3.5.5.tgz",
      "integrity": "sha512-RPXy7jYAXs704NIpZlosB0U2ENu21G9DrqGWdQgRe8dShaCo1ugpj+6BVPRCy91nt+MPMA96j5rbsSzEl0HlQA==",
      "license": "MIT",
      "dependencies": {
        "@pixiv/three-vrm-core": "3.5.5",
        "@pixiv/three-vrm-materials-hdr-emissive-multiplier": "3.5.5",
        "@pixiv/three-vrm-materials-mtoon": "3.5.5",
        "@pixiv/three-vrm-materials-v0compat": "3.5.5",
        "@pixiv/three-vrm-node-constraint": "3.5.5",
        "@pixiv/three-vrm-springbone": "3.5.5"
      },
      "peerDependencies": {
        "three": ">=0.137"
      }
    },
    "node_modules/@pixiv/three-vrm-core": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/three-vrm-core/-/three-vrm-core-3.5.5.tgz",
      "integrity": "sha512-jjaXZbMVRsk2HAGVxqDLmSJyGOJqbMcJpuTHR1TY/TN1FxiKdAzSqdr/ZUcczYipNf8IL9vDT9NX2XmWj+ybRQ==",
      "license": "MIT",
      "dependencies": {
        "@pixiv/types-vrm-0.0": "3.5.5",
        "@pixiv/types-vrmc-vrm-1.0": "3.5.5"
      },
      "peerDependencies": {
        "three": ">=0.137"
      }
    },
    "node_modules/@pixiv/three-vrm-materials-hdr-emissive-multiplier": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/three-vrm-materials-hdr-emissive-multiplier/-/three-vrm-materials-hdr-emissive-multiplier-3.5.5.tgz",
      "integrity": "sha512-XnHEqpY4ctYMucpeRcptdphOe0RrW7V5fUvojasD8Ja4MTjjrjCNFxsAvp3+HBkPZbkTM2sDCjJBJNzxN1scrA==",
      "license": "MIT",
      "dependencies": {
        "@pixiv/types-vrmc-materials-hdr-emissive-multiplier-1.0": "3.5.5"
      },
      "peerDependencies": {
        "three": ">=0.137"
      }
    },
    "node_modules/@pixiv/three-vrm-materials-mtoon": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/three-vrm-materials-mtoon/-/three-vrm-materials-mtoon-3.5.5.tgz",
      "integrity": "sha512-7lThHf4OKBOsVenD+R6L6HffNUlKO3Twnhr3+z77MnUsSzsOanjVKJtjSIly9QJ6hgl8YJmI6RnxCKqXcpplog==",
      "license": "MIT",
      "dependencies": {
        "@pixiv/types-vrm-0.0": "3.5.5",
        "@pixiv/types-vrmc-materials-mtoon-1.0": "3.5.5"
      },
      "peerDependencies": {
        "three": ">=0.137"
      }
    },
    "node_modules/@pixiv/three-vrm-materials-v0compat": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/three-vrm-materials-v0compat/-/three-vrm-materials-v0compat-3.5.5.tgz",
      "integrity": "sha512-NjsTK4P4qdcr+RoL2gEUNgF2CY/aplNvyHHxI99N7D6CxDZ2H93FQ9aIuLCABj5b+4CIvldWMCcnS7YuLIr3Lw==",
      "license": "MIT",
      "dependencies": {
        "@pixiv/types-vrm-0.0": "3.5.5",
        "@pixiv/types-vrmc-materials-mtoon-1.0": "3.5.5"
      },
      "peerDependencies": {
        "three": ">=0.137"
      }
    },
    "node_modules/@pixiv/three-vrm-node-constraint": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/three-vrm-node-constraint/-/three-vrm-node-constraint-3.5.5.tgz",
      "integrity": "sha512-+ShEXioZ5Ctf0EZ5ZViZ4n0jhV/qtJRH0Juw8nRnMNODZXDSr+B3An2lrfRoMhowCzG63GiUG4lXWV9noMXosA==",
      "license": "MIT",
      "dependencies": {
        "@pixiv/types-vrmc-node-constraint-1.0": "3.5.5"
      },
      "peerDependencies": {
        "three": ">=0.137"
      }
    },
    "node_modules/@pixiv/three-vrm-springbone": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/three-vrm-springbone/-/three-vrm-springbone-3.5.5.tgz",
      "integrity": "sha512-GWAWrIegGH/u1ZA+Es03Qzc2yafrQOrhtal9jzUIAgU8Wm2DYuqAABOY+du/9RpBRK8D4T8DBPvRGQqvfrQ/uA==",
      "license": "MIT",
      "dependencies": {
        "@pixiv/types-vrm-0.0": "3.5.5",
        "@pixiv/types-vrmc-springbone-1.0": "3.5.5",
        "@pixiv/types-vrmc-springbone-extended-collider-1.0": "3.5.5"
      },
      "peerDependencies": {
        "three": ">=0.137"
      }
    },
    "node_modules/@pixiv/types-vrm-0.0": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/types-vrm-0.0/-/types-vrm-0.0-3.5.5.tgz",
      "integrity": "sha512-2S/0jswMjJTwL9ky8YzDR0CIaP6ZmE+HFuyW/0h+SA+awELf+J7WGgC8lTLM1MXzokO7Z2YVljU2F0fEhlKDIQ==",
      "license": "MIT"
    },
    "node_modules/@pixiv/types-vrmc-materials-hdr-emissive-multiplier-1.0": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/types-vrmc-materials-hdr-emissive-multiplier-1.0/-/types-vrmc-materials-hdr-emissive-multiplier-1.0-3.5.5.tgz",
      "integrity": "sha512-IuHw9ehXt2bymqfdFV+f2cCXo8kvJUfh0Zuut8qmKXoEb7HVyLGIQyS4TcQHG5yY22UTWHI1Axo5tQv35lPTgQ==",
      "license": "MIT"
    },
    "node_modules/@pixiv/types-vrmc-materials-mtoon-1.0": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/types-vrmc-materials-mtoon-1.0/-/types-vrmc-materials-mtoon-1.0-3.5.5.tgz",
      "integrity": "sha512-GFVuksAJVhrWTXYmI/ucNsE611/d8N6BoZrzhUAAINndt98loyzapW2+DJu+GsUBO5yxd+vLsL0FB16XD9+TGg==",
      "license": "MIT"
    },
    "node_modules/@pixiv/types-vrmc-node-constraint-1.0": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/types-vrmc-node-constraint-1.0/-/types-vrmc-node-constraint-1.0-3.5.5.tgz",
      "integrity": "sha512-8EbJ1uzkn9yJQarCChmpG12+mc2c7PimHvQ8H6/tMh/hqp5NtJND0z2lR2KeVxw9A3M+TpF+xgImhLBxGjqwzQ==",
      "license": "MIT"
    },
    "node_modules/@pixiv/types-vrmc-springbone-1.0": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/types-vrmc-springbone-1.0/-/types-vrmc-springbone-1.0-3.5.5.tgz",
      "integrity": "sha512-gRQ5Y7PaGiMefvOrJ3hvoSPqpA67jiwyhwh8ItjsPi3yri/Hn3CeXplW3Cbx3ZPbfu+C3Q2MCRa2TqAUOjeMRA==",
      "license": "MIT"
    },
    "node_modules/@pixiv/types-vrmc-springbone-extended-collider-1.0": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/types-vrmc-springbone-extended-collider-1.0/-/types-vrmc-springbone-extended-collider-1.0-3.5.5.tgz",
      "integrity": "sha512-+6RxLaAvVguP7upjS/OT4viNPWvac1HBRQY1nmdvfYNQuCMdrMsCZqvy2af0Fcjnda4V9JbKFIpZDC0lrw1+uQ==",
      "license": "MIT"
    },
    "node_modules/@pixiv/types-vrmc-vrm-1.0": {
      "version": "3.5.5",
      "resolved": "https://registry.npmjs.org/@pixiv/types-vrmc-vrm-1.0/-/types-vrmc-vrm-1.0-3.5.5.tgz",
      "integrity": "sha512-WnemHHo2375BcBdumEhvrupZzsMSzTfdWlokmV9sUX2oC+OAQqJFfBjLF8ppkOhzHpl4MAPJqEfuhBJtNPm9ww==",
      "license": "MIT"
    },
    "node_modules/@types/node": {
      "version": "24.19.0",
      "resolved": "https://registry.npmjs.org/@types/node/-/node-24.19.0.tgz",
      "integrity": "sha512-zY+5tKxXdhGh1PYI0ac+7juvEu4OI6vWtVVoj5i2m42jxAY1U+zHGt6QCyOFwykdP62sM3MJ9stoYYUw5aCWew==",
      "dev": true,
      "license": "MIT",
      "dependencies": {
        "undici-types": ">=7.24.0 <7.24.7"
      }
    },
    "node_modules/debug": {
      "version": "4.4.3",
      "resolved": "https://registry.npmjs.org/debug/-/debug-4.4.3.tgz",
      "integrity": "sha512-RGwwWnwQvkVfavKVt22FGLw+xYSdzARwm0ru6DhTVA3umU5hZc28V3kO4stgYryrTlLpuvgI9GiijltAjNbcqA==",
      "dev": true,
      "license": "MIT",
      "dependencies": {
        "ms": "^2.1.3"
      },
      "engines": {
        "node": ">=6.0"
      },
      "peerDependenciesMeta": {
        "supports-color": {
          "optional": true
        }
      }
    },
    "node_modules/electron": {
      "version": "44.5.1",
      "resolved": "https://registry.npmjs.org/electron/-/electron-44.5.1.tgz",
      "integrity": "sha512-lx7AYoFIiyvEvgvpyWO9kOC60xtNPpiPZAth6Fmg9NutzpCAMLwpUlaBY2EXfZyIgUdzEmLMj9KvK0Vrokl1yQ==",
      "dev": true,
      "license": "MIT",
      "dependencies": {
        "@electron-internal/extract-zip": "^1.0.1",
        "@electron/get": "^5.0.0",
        "@types/node": "^24.9.0"
      },
      "bin": {
        "electron": "cli.js",
        "install-electron": "install.js"
      },
      "engines": {
        "node": ">= 22.12.0"
      }
    },
    "node_modules/env-paths": {
      "version": "3.0.0",
      "resolved": "https://registry.npmjs.org/env-paths/-/env-paths-3.0.0.tgz",
      "integrity": "sha512-dtJUTepzMW3Lm/NPxRf3wP4642UWhjL2sQxc+ym2YMj1m/H2zDNQOlezafzkHwn6sMstjHTwG6iQQsctDW/b1A==",
      "dev": true,
      "license": "MIT",
      "engines": {
        "node": "^12.20.0 || ^14.13.1 || >=16.0.0"
      },
      "funding": {
        "url": "https://github.com/sponsors/sindresorhus"
      }
    },
    "node_modules/graceful-fs": {
      "version": "4.2.11",
      "resolved": "https://registry.npmjs.org/graceful-fs/-/graceful-fs-4.2.11.tgz",
      "integrity": "sha512-RbJ5/jmFcNNCcDV5o9eTnBLJ/HszWV0P73bc+Ff4nS/rJj+YaS6IGyiOL0VoBYX+l1Wrl3k63h/KrH+nhJ0XvQ==",
      "dev": true,
      "license": "ISC"
    },
    "node_modules/ms": {
      "version": "2.1.3",
      "resolved": "https://registry.npmjs.org/ms/-/ms-2.1.3.tgz",
      "integrity": "sha512-6FlzubTLZG3J2a/NVCAleEhjzq5oxgHyaCU9yYXvcLsvoVaHJq/s5xXI6/XXP6tz7R9xAOtHnSO/tXtF3WRTlA==",
      "dev": true,
      "license": "MIT"
    },
    "node_modules/progress": {
      "version": "2.0.3",
      "resolved": "https://registry.npmjs.org/progress/-/progress-2.0.3.tgz",
      "integrity": "sha512-7PiHtLll5LdnKIMw100I+8xJXR5gW2QwWYkT6iJva0bXitZKa/XMrSbdmg3r2Xnaidz9Qumd0VPaMrZlF9V9sA==",
      "dev": true,
      "license": "MIT",
      "engines": {
        "node": ">=0.4.0"
      }
    },
    "node_modules/semver": {
      "version": "7.8.5",
      "resolved": "https://registry.npmjs.org/semver/-/semver-7.8.5.tgz",
      "integrity": "sha512-Y7/KDsb8LjooZpwaqGyulO6DQlksgCncchHGk+sZIY4SBvUocMBEFH5Ur1fI4dV+Jvl0w6cjvucaIi40puRioA==",
      "dev": true,
      "license": "ISC",
      "bin": {
        "semver": "bin/semver.js"
      },
      "engines": {
        "node": ">=10"
      }
    },
    "node_modules/sumchecker": {
      "version": "3.0.1",
      "resolved": "https://registry.npmjs.org/sumchecker/-/sumchecker-3.0.1.tgz",
      "integrity": "sha512-MvjXzkz/BOfyVDkG0oFOtBxHX2u3gKbMHIF/dXblZsgD3BWOFLmHovIpZY7BykJdAjcqRCBi1WYBNdEC9yI7vg==",
      "dev": true,
      "license": "Apache-2.0",
      "dependencies": {
        "debug": "^4.1.0"
      },
      "engines": {
        "node": ">= 8.0"
      }
    },
    "node_modules/three": {
      "version": "0.186.1",
      "resolved": "https://registry.npmjs.org/three/-/three-0.186.1.tgz",
      "integrity": "sha512-blFeqb49wRCSGUGj7gtpfnSGHy2lwDk94RhUmS1c/hTby70kvChbWpkJ4Pm1390LqzzvTmzgXKHPEafJwCb8jA==",
      "license": "MIT"
    },
    "node_modules/undici": {
      "version": "7.30.0",
      "resolved": "https://registry.npmjs.org/undici/-/undici-7.30.0.tgz",
      "integrity": "sha512-dkrQXeHSaoamnItlYbmzG0wFYrM0ZwDxCIg0A7aKjTyyhh9svRzCNFEzV+Vm05/yehjCzjDZ31KXfGEjYSztDQ==",
      "dev": true,
      "license": "MIT",
      "optional": true,
      "engines": {
        "node": ">=20.18.1"
      }
    },
    "node_modules/undici-types": {
      "version": "7.24.6",
      "resolved": "https://registry.npmjs.org/undici-types/-/undici-types-7.24.6.tgz",
      "integrity": "sha512-WRNW+sJgj5OBN4/0JpHFqtqzhpbnV0GuB+OozA9gCL7a993SmU+1JBZCzLNxYsbMfIeDL+lTsphD5jN5N+n0zg==",
      "dev": true,
      "license": "MIT"
    }
  }
}
`````

### `desktop/package.json`

`````json
{
  "name": "jawl-desktop",
  "version": "0.1.0",
  "description": "JAWL VoiceCompanion desktop shell: 3D VRM avatar + control panel (ADR-045).",
  "main": "main.js",
  "private": true,
  "scripts": {
    "start": "electron .",
    "start:dev": "electron . --dev"
  },
  "devDependencies": {
    "electron": "^44.5.1"
  },
  "dependencies": {
    "@pixiv/three-vrm": "^3.5.5",
    "three": "^0.186.1"
  }
}
`````

### `desktop/panel-preload.js`

`````javascript
// Small, explicit bridge for the one desktop-only lifecycle action.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jawlDesktop', {
  onProfileStopRequest(callback) {
    if (typeof callback !== 'function') return () => {};
    const listener = () => callback();
    ipcRenderer.on('jawl-profile-stop-request', listener);
    return () => ipcRenderer.removeListener('jawl-profile-stop-request', listener);
  },
  acknowledgeProfileStop() {
    ipcRenderer.send('jawl-profile-stop-accepted');
  },
});
`````

### `desktop/runtime-config.js`

`````javascript
// Electron only consumes the control-port view; model execution stays in Python.
const fs = require('node:fs');
const path = require('node:path');

function port(value) {
  if (!Number.isInteger(value) || value < 1 || value > 65535 || value === 8765) {
    throw new Error('Invalid or reserved Companion control port');
  }
  return value;
}

function controlPort(repoRoot, env = process.env, files = fs) {
  const explicit = env.JAWL_DESKTOP_CONTROL_PORT;
  if (explicit !== undefined) {
    if (!/^\d{1,5}$/.test(explicit)) throw new Error('Invalid Companion control-port override');
    return port(Number(explicit));
  }
  function read(name, optional = false) {
    try {
      const filename = path.join(repoRoot, 'config', name);
      if (files.statSync(filename).size > 128 * 1024) throw new Error();
      const raw = files.readFileSync(filename, 'utf8');
      if (Buffer.byteLength(raw, 'utf8') > 128 * 1024) throw new Error();
      const data = JSON.parse(raw);
      if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error();
      if (data.ports !== undefined && (!data.ports || Array.isArray(data.ports) || typeof data.ports !== 'object')) throw new Error();
      return data;
    } catch (error) {
      if (optional && error.code === 'ENOENT') return {};
      throw new Error('Cannot read Companion runtime manifest');
    }
  }
  const base = read('runtime.manifest.json');
  const local = read('runtime.manifest.local.json', true);
  const ports = { ...base.ports, ...local.ports };
  const selected = port(ports.control);
  if (Object.entries(ports).some(([key, value]) => key !== 'control' && key !== 'reserved' && value === selected)) {
    throw new Error('Companion control port collides with another service');
  }
  if (Array.isArray(ports.reserved) && ports.reserved.includes(selected)) throw new Error('Reserved Companion control port');
  return selected;
}

module.exports = { controlPort };
`````

### `desktop/speech-stream.js`

`````javascript
const MAX_LINE_CHARS = 12 * 1024 * 1024;
const MAX_AUDIO_BYTES = 8 * 1024 * 1024;
const MAX_TOTAL_AUDIO_BYTES = 32 * 1024 * 1024;
const MAX_TOTAL_WIRE_BYTES = 64 * 1024 * 1024;
const MAX_AUDIO_EVENTS = 512;
const MAX_CHUNK_SECONDS = 30;
const MAX_TOTAL_SECONDS = 300;
const MAX_SCHEDULED_AHEAD_SECONDS = 0.8;
const MAX_SLICE_SECONDS = 0.4;
const INITIAL_LEAD_SECONDS = 0.12;
const STREAM_DEADLINE_MS = 120_000;

function streamError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function decodeBase64(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > Math.ceil(MAX_AUDIO_BYTES * 4 / 3) + 4
      || value.length % 4 !== 0 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw streamError('TTS_INVALID_AUDIO');
  }
  const binary = atob(value);
  if (binary.length < 44 || binary.length > MAX_AUDIO_BYTES) throw streamError('TTS_INVALID_AUDIO');
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function abortableDelay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(streamError('TTS_CANCELLED'));
    const timer = setTimeout(done, ms);
    function done() {
      signal.removeEventListener('abort', abort);
      resolve();
    }
    function abort() {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      reject(streamError('TTS_CANCELLED'));
    }
    signal.addEventListener('abort', abort, {once: true});
  });
}

/** Consume sentence-WAV NDJSON with bounded memory and an actual bounded audio horizon. */
export async function consumeSpeechStream(response, {
  audioContext,
  signal,
  isCurrent = () => true,
  connectSource = source => source.connect(audioContext.destination),
  onSourceStart = () => {},
  onSourceEnd = () => {},
  onStreamDone = () => {},
  deadlineMs = STREAM_DEADLINE_MS,
} = {}) {
  if (!response?.ok || !response.body?.getReader || !audioContext?.decodeAudioData) {
    throw streamError('TTS_STREAM_UNAVAILABLE');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', {fatal: true});
  const sessionController = new AbortController();
  const sources = new Set();
  let pending = '';
  let expectedIndex = 0;
  let totalBytes = 0;
  let totalWireBytes = 0;
  let totalSeconds = 0;
  let nextStart = audioContext.currentTime + INITIAL_LEAD_SECONDS;
  let streamDone = false;
  let interrupted = false;
  let rejectInterruption;
  let deadlineTimer;
  let rejectPromise;
  const interruption = new Promise((_, reject) => { rejectInterruption = reject; });
  void interruption.catch(() => {});

  const isLive = () => !interrupted && !sessionController.signal.aborted && !signal?.aborted && isCurrent();
  const stopSources = () => {
    for (const source of sources) {
      source.onended = null;
      try { source.stop(); } catch {}
      try { source.disconnect(); } catch {}
      try { onSourceEnd(source); } catch {}
    }
    sources.clear();
  };
  const interrupt = error => {
    if (interrupted) return;
    interrupted = true;
    sessionController.abort();
    stopSources();
    void reader.cancel().catch(() => {});
    rejectInterruption(error);
    rejectPromise?.(error);
  };
  const onAbort = () => interrupt(streamError('TTS_CANCELLED'));
  signal?.addEventListener('abort', onAbort, {once: true});
  if (signal?.aborted) onAbort();
  deadlineTimer = setTimeout(() => interrupt(streamError('TTS_DEADLINE')), deadlineMs);

  const isStillCurrent = () => {
    if (!isLive()) throw streamError('TTS_CANCELLED');
  };

  const scheduleAudio = async event => {
    if (event.index !== expectedIndex || !Number.isSafeInteger(event.index)
        || event.media_type !== 'audio/wav' || typeof event.data_base64 !== 'string') {
      throw streamError('TTS_INVALID_AUDIO_EVENT');
    }
    if (++expectedIndex > MAX_AUDIO_EVENTS) throw streamError('TTS_LIMIT_EXCEEDED');
    const wav = decodeBase64(event.data_base64);
    totalBytes += wav.byteLength;
    if (totalBytes > MAX_TOTAL_AUDIO_BYTES) throw streamError('TTS_LIMIT_EXCEEDED');
    isStillCurrent();

    let buffer;
    try {
      buffer = await Promise.race([audioContext.decodeAudioData(wav), interruption]);
    } catch (error) {
      if (error?.code) throw error;
      throw streamError('TTS_INVALID_WAV');
    }
    isStillCurrent();
    if (!Number.isFinite(buffer?.duration) || buffer.duration <= 0 || buffer.duration > MAX_CHUNK_SECONDS) {
      throw streamError('TTS_INVALID_WAV');
    }
    totalSeconds += buffer.duration;
    if (totalSeconds > MAX_TOTAL_SECONDS) throw streamError('TTS_LIMIT_EXCEEDED');

    const sliceCount = Math.ceil(buffer.duration / MAX_SLICE_SECONDS);
    for (let sliceIndex = 0; sliceIndex < sliceCount; sliceIndex += 1) {
      const offset = sliceIndex * MAX_SLICE_SECONDS;
      const duration = Math.min(MAX_SLICE_SECONDS, buffer.duration - offset);
      while (nextStart - audioContext.currentTime + duration > MAX_SCHEDULED_AHEAD_SECONDS) {
        isStillCurrent();
        const excess = nextStart - audioContext.currentTime + duration - MAX_SCHEDULED_AHEAD_SECONDS;
        await abortableDelay(Math.min(100, Math.max(20, excess * 1000)), sessionController.signal);
      }
      isStillCurrent();

      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      connectSource(source);
      sources.add(source);
      source.onended = () => {
        sources.delete(source);
        try { source.disconnect(); } catch {}
        try { onSourceEnd(source); } catch {}
      };
      const startAt = Math.max(nextStart, audioContext.currentTime + 0.01);
      source.start(startAt, offset, duration);
      nextStart = startAt + duration;
      try { onSourceStart(source, startAt, duration); } catch {}
    }
  };

  const consumeLine = async line => {
    if (line.length > MAX_LINE_CHARS) throw streamError('TTS_LIMIT_EXCEEDED');
    if (!line.trim()) return;
    if (streamDone) throw streamError('TTS_EVENT_AFTER_DONE');
    let event;
    try { event = JSON.parse(line); } catch { throw streamError('TTS_INVALID_EVENT'); }
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw streamError('TTS_INVALID_EVENT');
    if (event.type === 'audio') return scheduleAudio(event);
    if (event.type === 'cancelled') throw streamError('TTS_CANCELLED');
    if (event.type === 'error') throw streamError('TTS_PROVIDER_ERROR');
    if (event.type === 'done') {
      if (event.count !== expectedIndex) throw streamError('TTS_INVALID_DONE');
      streamDone = true;
      return;
    }
    throw streamError('TTS_INVALID_EVENT');
  };

  const consume = async () => {
    try {
      while (true) {
        isStillCurrent();
        const result = await Promise.race([reader.read(), interruption]);
        isStillCurrent();
        totalWireBytes += result.value?.byteLength ?? 0;
        if (totalWireBytes > MAX_TOTAL_WIRE_BYTES) throw streamError('TTS_LIMIT_EXCEEDED');
        try {
          pending += decoder.decode(result.value || new Uint8Array(), {stream: !result.done});
        } catch {
          throw streamError('TTS_INVALID_UTF8');
        }
        if (pending.length > MAX_LINE_CHARS && !pending.includes('\n')) throw streamError('TTS_LIMIT_EXCEEDED');
        const lines = pending.split('\n');
        pending = lines.pop() || '';
        for (const line of lines) await consumeLine(line);
        if (result.done) break;
      }
      await consumeLine(pending);
      if (!streamDone) throw streamError('TTS_TRUNCATED');
      while (sources.size > 0) {
        isStillCurrent();
        await abortableDelay(25, sessionController.signal);
      }
      isStillCurrent();
      clearTimeout(deadlineTimer);
      signal?.removeEventListener('abort', onAbort);
      onStreamDone();
    } catch (error) {
      interrupt(error?.code ? error : streamError('TTS_PLAYBACK_FAILED'));
      clearTimeout(deadlineTimer);
      signal?.removeEventListener('abort', onAbort);
      throw error?.code ? error : streamError('TTS_PLAYBACK_FAILED');
    }
  };

  const result = new Promise((resolve, reject) => {
    rejectPromise = reject;
    void consume().then(resolve, reject);
  });
  return result;
}
`````

### `desktop/speech-stream.test.mjs`

`````javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {consumeSpeechStream} from './speech-stream.js';

function wavBase64(duration = 0.2) {
  const sampleRate = 32000;
  const sampleCount = Math.round(sampleRate * duration);
  const wav = new ArrayBuffer(44 + sampleCount * 2);
  const view = new DataView(wav);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint32(40, sampleCount * 2, true);
  return Buffer.from(wav).toString('base64');
}

const audio = (index, duration = 0.2, extra = {}) => ({
  type: 'audio', index, media_type: 'audio/wav', data_base64: wavBase64(duration), ...extra,
});
const done = count => ({type: 'done', count});
const line = event => Buffer.from(JSON.stringify(event));

function responseFromBytes(parts) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(new Uint8Array(part));
      controller.close();
    },
  }), {headers: {'content-type': 'application/x-ndjson; charset=utf-8'}});
}

function responseFromEvents(events, {splitAt = null, trailingNewline = false} = {}) {
  const bytes = Buffer.from(events.map(JSON.stringify).join('\n') + (trailingNewline ? '\n' : ''));
  return responseFromBytes(splitAt === null
    ? [bytes]
    : [bytes.subarray(0, splitAt), bytes.subarray(splitAt)]);
}

class FakeAudioContext {
  currentTime = 0;
  destination = {};
  sources = [];
  async decodeAudioData(wav) {
    const view = new DataView(wav);
    return {duration: view.getUint32(40, true) / view.getUint32(28, true)};
  }
  createBufferSource() {
    const source = {
      connect() {},
      disconnect() { this.disconnected = true; },
      stop() { this.stopped = true; },
      start(when, offset = 0, duration = this.buffer.duration) {
        this.when = when;
        this.offset = offset;
        this.duration = duration;
        this.context.sources.push(this);
      },
      end() { this.onended?.(); },
      context: this,
    };
    return source;
  }
}

async function waitFor(predicate) {
  for (let i = 0; i < 100; i += 1) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.fail('condition did not become true');
}

function play(response, context, options = {}) {
  return consumeSpeechStream(response, {audioContext: context, ...options});
}

test('plays first ordered audio event before server sends done', async () => {
  const context = new FakeAudioContext();
  let controller;
  const response = new Response(new ReadableStream({
    start(value) {
      controller = value;
      value.enqueue(new Uint8Array(Buffer.concat([line(audio(0)), Buffer.from('\n')])));
    },
  }), {headers: {'content-type': 'application/x-ndjson'}});
  const task = play(response, context);
  await waitFor(() => context.sources.length === 1);
  assert.equal(context.sources[0].when, 0.12);
  context.sources[0].end();
  controller.enqueue(new Uint8Array(line(done(1))));
  controller.close();
  await task;
});

test('splits NDJSON across network boundaries and accepts a trailing unterminated line', async () => {
  const context = new FakeAudioContext();
  const bytes = Buffer.concat([line(audio(0)), Buffer.from('\n'), line(done(1))]);
  const task = play(responseFromBytes([bytes.subarray(0, 19), bytes.subarray(19, 57), bytes.subarray(57)]), context);
  await waitFor(() => context.sources.length === 1);
  context.sources[0].end();
  await task;
  assert.equal(context.sources.length, 1);
});

test('preserves UTF-8 metadata split inside a multibyte character', async () => {
  const context = new FakeAudioContext();
  const bytes = Buffer.concat([line(audio(0, 0.2, {text: 'Привет'})), Buffer.from('\n'), line(done(1))]);
  const splitAt = bytes.indexOf(Buffer.from('П')) + 1;
  const task = play(responseFromBytes([bytes.subarray(0, splitAt), bytes.subarray(splitAt)]), context);
  await waitFor(() => context.sources.length === 1);
  context.sources[0].end();
  await task;
  assert.equal(context.sources.length, 1);
});

test('rejects out-of-order indexes and corrupt base64/WAV events', async t => {
  for (const [name, events, code] of [
    ['out of order', [audio(1), done(1)], 'TTS_INVALID_AUDIO_EVENT'],
    ['base64', [{...audio(0), data_base64: '%%%='}, done(1)], 'TTS_INVALID_AUDIO'],
    ['WAV decode', [{...audio(0), data_base64: Buffer.from('not a wav payload').toString('base64')}, done(1)], 'TTS_INVALID_AUDIO'],
  ]) {
    await t.test(name, async () => {
      await assert.rejects(play(responseFromEvents(events), new FakeAudioContext()), {code});
    });
  }
});

test('surfaces in-band provider errors without parsing their message as audio', async () => {
  await assert.rejects(
    play(responseFromEvents([{type: 'error', error: 'private backend detail'}]), new FakeAudioContext()),
    {code: 'TTS_PROVIDER_ERROR'},
  );
});

test('rejects audio emitted after done and cleans up prior sources', async () => {
  const context = new FakeAudioContext();
  await assert.rejects(
    play(responseFromEvents([audio(0), done(1), audio(1)]), context),
    {code: 'TTS_EVENT_AFTER_DONE'},
  );
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].stopped, true);
  assert.equal(context.sources[0].disconnected, true);
});

test('enforces line and per-chunk duration limits', async t => {
  await t.test('oversized line', async () => {
    const oversized = Buffer.alloc(12 * 1024 * 1024 + 1, 32);
    await assert.rejects(play(responseFromBytes([oversized]), new FakeAudioContext()), {code: 'TTS_LIMIT_EXCEEDED'});
  });
  await t.test('oversized whitespace line terminated by newline', async () => {
    const oversized = Buffer.alloc(12 * 1024 * 1024 + 1, 32);
    const bytes = Buffer.concat([oversized, Buffer.from('\n'), line(done(0))]);
    await assert.rejects(play(responseFromBytes([bytes]), new FakeAudioContext()), {code: 'TTS_LIMIT_EXCEEDED'});
  });
  await t.test('oversized WAV duration', async () => {
    await assert.rejects(
      play(responseFromEvents([audio(0, 30.1), done(1)]), new FakeAudioContext()),
      {code: 'TTS_INVALID_WAV'},
    );
  });
});

test('rejects an oversized wire read before UTF-8 decoding without audio', async () => {
  const context = new FakeAudioContext();
  const oversized = new Uint8Array(64 * 1024 * 1024 + 1);
  oversized[0] = 0xff; // Decoding this read would instead fail with TTS_INVALID_UTF8.
  let cancelCalled = false;
  const response = new Response(new ReadableStream({
    start(controller) { controller.enqueue(oversized); },
    cancel() { cancelCalled = true; },
  }));
  await assert.rejects(play(response, context), {code: 'TTS_LIMIT_EXCEEDED'});
  assert.equal(cancelCalled, true);
  assert.equal(context.sources.length, 0);
});

test('counts short whitespace lines cumulatively across small wire chunks', async () => {
  const context = new FakeAudioContext();
  const chunk = Buffer.from((' '.repeat(1023) + '\n').repeat(64));
  let readCount = 0;
  let cancelCalled = false;
  const response = {ok: true, body: {getReader: () => ({
    read() {
      readCount += 1;
      if (readCount <= 1024) return Promise.resolve({done: false, value: chunk});
      if (readCount === 1025) return Promise.resolve({done: false, value: Buffer.from('\n')});
      if (readCount === 1026) return Promise.resolve({done: false, value: line(done(0))});
      return Promise.resolve({done: true});
    },
    cancel() { cancelCalled = true; return Promise.resolve(); },
  })}};
  await assert.rejects(play(response, context), {code: 'TTS_LIMIT_EXCEEDED'});
  assert.equal(readCount, 1025); // Exactly 64 MiB is accepted; the next byte is rejected.
  assert.equal(cancelCalled, true);
  assert.equal(context.sources.length, 0);
});

test('cancelled event and abort stop reading and ignore late events', async () => {
  await assert.rejects(play(responseFromEvents([{type: 'cancelled'}]), new FakeAudioContext()), {code: 'TTS_CANCELLED'});

  const context = new FakeAudioContext();
  const abort = new AbortController();
  let releaseLateRead;
  let readCount = 0;
  let cancelCalled = false;
  const lateDone = new Uint8Array(line(done(1)));
  const response = {ok: true, body: {getReader: () => ({
    read() {
      readCount += 1;
      if (readCount === 1) return Promise.resolve({done: false, value: new Uint8Array(Buffer.concat([line(audio(0)), Buffer.from('\n')]))});
      return new Promise(resolve => { releaseLateRead = () => resolve({done: false, value: lateDone}); });
    },
    cancel() { cancelCalled = true; releaseLateRead?.(); return Promise.resolve(); },
  })}};
  const task = play(response, context, {signal: abort.signal});
  await waitFor(() => context.sources.length === 1);
  abort.abort();
  await assert.rejects(task, {code: 'TTS_CANCELLED'});
  assert.equal(cancelCalled, true);
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].stopped, true);
  assert.equal(context.sources[0].disconnected, true);
});

test('keeps scheduled lead bounded and applies backpressure while the clock is stationary', async () => {
  const context = new FakeAudioContext();
  const response = responseFromEvents([audio(0, 0.4), audio(1, 0.4), audio(2, 0.4), done(3)]);
  const task = play(response, context);
  await waitFor(() => context.sources.length === 1);
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(context.sources.length, 1);
  context.currentTime = 0.12;
  await waitFor(() => context.sources.length === 2);
  context.currentTime = 0.52;
  await waitFor(() => context.sources.length === 3);
  assert.ok(context.sources.every(source => source.when + source.duration - context.currentTime <= 0.8));
  for (const source of [...context.sources]) source.end();
  await task;
});

test('segments a long decoded WAV so its scheduled tail never exceeds 0.8 seconds', async () => {
  const context = new FakeAudioContext();
  const task = play(responseFromEvents([audio(0, 30), done(1)]), context);
  let scheduled = 0;
  await waitFor(() => context.sources.length > scheduled);
  for (let i = 0; i < 75; i += 1) {
    const source = context.sources[i];
    if (!source) break;
    assert.ok(source.duration <= 0.4);
    assert.ok(source.when + source.duration - context.currentTime <= 0.8);
    scheduled = context.sources.length;
    context.currentTime = source.when + source.duration;
    for (const active of context.sources) {
      if (!active.ended && active.when + active.duration <= context.currentTime) {
        active.ended = true;
        active.end();
      }
    }
    await waitFor(() => context.sources.length > scheduled || i === 74);
  }
  for (const source of context.sources) if (!source.ended) source.end();
  await task;
  assert.equal(context.sources.length, 75);
});

test('rejects a stream that exceeds the deadline', async () => {
  const response = new Response(new ReadableStream({start() {}}));
  await assert.rejects(play(response, new FakeAudioContext(), {deadlineMs: 15}), {code: 'TTS_DEADLINE'});
});

test('deadline cancels a pending read and immediately stops already scheduled audio', async () => {
  const context = new FakeAudioContext();
  let cancelCalled = false;
  let readCount = 0;
  const response = {ok: true, body: {getReader: () => ({
    read() {
      readCount += 1;
      if (readCount === 1) return Promise.resolve({
        done: false,
        value: new Uint8Array(Buffer.concat([line(audio(0)), Buffer.from('\n')])),
      });
      return new Promise(() => {});
    },
    cancel() { cancelCalled = true; return Promise.resolve(); },
  })}};
  await assert.rejects(play(response, context, {deadlineMs: 20}), {code: 'TTS_DEADLINE'});
  assert.equal(cancelCalled, true);
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].stopped, true);
  assert.equal(context.sources[0].disconnected, true);
});

test('parser errors stop earlier sources and never leave scheduled audio behind', async () => {
  const context = new FakeAudioContext();
  const body = Buffer.concat([line(audio(0)), Buffer.from('\n{bad json}\n')]);
  await assert.rejects(play(responseFromBytes([body]), context), {code: 'TTS_INVALID_EVENT'});
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].stopped, true);
  assert.equal(context.sources[0].disconnected, true);
});
`````

### `desktop/tests/app-accessibility.test.mjs`

`````javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const html = await readFile(new URL('../app.html', import.meta.url), 'utf8');

test('device selector and settings search have explicit accessible labels', () => {
  assert.match(html, /<label\b[^>]*for="mic-select"[^>]*>Устройство<\/label>/);
  assert.match(html, /<label\b[^>]*for="settings-search"[^>]*>Поиск по настройкам JAWL<\/label>/);
  assert.match(html, /#settings-search/);
  assert.match(html, /button:focus-visible, input:focus-visible, select:focus-visible/);
});

test('service status labels the JAWL brain without pinning a stale model name', () => {
  assert.match(html, /<span class="label">Мозг JAWL<\/span>\s*<span class="value" id="svc-brain">/);
  assert.doesNotMatch(html, /Мозг \(Hikari\)/);
});

test('service card explains its scope without implying that every service is healthy', () => {
  assert.match(html, /Список процессов и портов скрыт; здесь показывается состояние сервисов\./);
  assert.doesNotMatch(html, /всё работает в этом окне/);
});

test('system audio describer status is present and does not announce every polling update', () => {
  assert.match(html, /id="sensor-audio-description-status" role="status" aria-live="off"/);
});
`````

### `desktop/tests/app-voice-lifecycle.test.mjs`

`````javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const appSource = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const speechModule = await import('../speech-stream.js');
const micModule = await import('../voice-input.js');
const draftModule = await import('../voice-draft.js');

function speechHarness(fetchImpl = async () => ndjsonResponse([audioEvent(0), doneEvent(1)])) {
  const stopButton = {disabled: true, listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; }};
  const made = {sources: [], requests: [], playbackMarkers: [], disconnected: 0, lip: [], motion: [], diagnostics: [], messages: [], stopButton};
  let speechRequestId = 0;
  class FakeAudioContext {
    state = 'running';
    currentTime = 0;
    destination = {};
    async decodeAudioData(wav) {
      const view = new DataView(wav);
      return {duration: view.getUint32(40, true) / (view.getUint32(28, true) || 32000)};
    }
    createBufferSource() {
      const source = {
        connect: (node) => node,
        disconnect: () => { made.disconnected += 1; },
        start: (at) => { source.startAt = at; made.sources.push(source); },
        stop: () => { source.stopped = true; },
      };
      return source;
    }
    createAnalyser() {
      return {
        frequencyBinCount: 4,
        getByteTimeDomainData: (data) => data.fill(128),
        connect: (node) => node,
        disconnect: () => { made.disconnected += 1; },
      };
    }
  }
  const context = {
    API: {headers: () => ({})},
    state: {speechGeneration: 0, speechPlayback: null},
    fetch: async (...args) => {
      made.requests.push(args);
      if (args[0] === '/api/ambient-audio/playback') {
        made.playbackMarkers.push(JSON.parse(args[1].body));
        return new Response('{}', {status: 200});
      }
      return fetchImpl(...args);
    },
    AbortController,
    crypto: {randomUUID: () => `speech-${++speechRequestId}`},
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    atob: value => Buffer.from(value, 'base64').toString('binary'),
    document: {querySelector: selector => selector === '#speech-stop' ? stopButton : null},
    AudioContext: FakeAudioContext,
    cancelAnimationFrame: () => {},
    requestAnimationFrame: () => 1,
    performance: {now: () => 10},
    addMessage: (...args) => made.messages.push(args),
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    window: {
      dispatchEvent: event => made.diagnostics.push(event.detail),
      __jawlScene: {setLipLevel: (level) => made.lip.push(level), setMotionState: (mode) => made.motion.push(mode)},
    },
  };
  const start = appSource.indexOf('// speech: /api/tts/stream');
  const end = appSource.indexOf('// microphone: the panel', start);
  assert.ok(start >= 0 && end > start, 'speech lifecycle section exists');
  context.consumeSpeechStream = speechModule.consumeSpeechStream;
  const section = appSource.slice(start, end).replace(
    "await import('./speech-stream.js')",
    'await Promise.resolve({consumeSpeechStream: globalThis.consumeSpeechStream})',
  );
  vm.runInNewContext(`${section}\nglobalThis.speech = {speakFinal, cancelSpeechPlayback, playEarlyAudioEvent, earlySpeech, syncSelfTtsSuppression, get markerQueue() { return selfTtsSuppressionQueue; }};`, context);
  return {context, made, speech: context.speech};
}

function wavBase64(duration = 0.2) {
  const sampleRate = 32000;
  const sampleCount = Math.round(sampleRate * duration);
  const wav = new ArrayBuffer(44 + sampleCount * 2);
  const view = new DataView(wav);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint32(40, sampleCount * 2, true);
  return Buffer.from(wav).toString('base64');
}

function audioEvent(index, duration = 0.2, extra = {}) {
  return {type: 'audio', index, media_type: 'audio/wav', data_base64: wavBase64(duration), ...extra};
}
const doneEvent = count => ({type: 'done', count});
function ndjsonResponse(events, {trailing = true, splitAt = null} = {}) {
  const text = events.map(event => JSON.stringify(event)).join('\n') + (trailing ? '' : '\n');
  const bytes = Buffer.from(text);
  const chunks = splitAt === null ? [bytes] : [bytes.subarray(0, splitAt), bytes.subarray(splitAt)];
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) if (chunk.length) controller.enqueue(new Uint8Array(chunk));
      controller.close();
    },
  }), {headers: {'content-type': 'application/x-ndjson; charset=utf-8'}});
}
async function waitFor(predicate) {
  for (let i = 0; i < 100; i += 1) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('condition did not become true');
}

function appFunction(name) {
  let start = appSource.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists in app.js`);
  if (appSource.slice(start - 6, start) === 'async ') start -= 6;
  const open = appSource.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < appSource.length; i += 1) {
    if (appSource[i] === '{') depth += 1;
    if (appSource[i] === '}' && --depth === 0) return appSource.slice(start, i + 1);
  }
  throw new Error(`could not read ${name}`);
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

function jsonResponse(data = {}, status = 200) {
  return new Response(JSON.stringify(data), {status, headers: {'content-type': 'application/json'}});
}

function abortable(signal) {
  return new Promise((_resolve, reject) => {
    const abort = () => reject(signal.reason || new Error('aborted'));
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, {once: true});
  });
}

// Run the actual app function bodies, replacing only browser resources,
// module loading and the clock. Lease acquire/renew/release remain real.
function micHarness({fetchImpl, getUserMedia, closeContext} = {}) {
  const made = {requests: [], streams: [], contexts: [], nodes: [], leases: [],
    permissionRequests: [], messages: [], envelopes: [], diagnostics: [], micButtonStates: [], micStatuses: [], cancellations: 0, now: 0,
    earlyStops: []};
  const timers = new Map();
  let timerId = 0;
  const schedule = (callback, delay, interval = 0) => {
    const id = ++timerId;
    timers.set(id, {callback, at: made.now + delay, interval});
    return id;
  };
  const clock = {
    setTimeout: (callback, delay) => schedule(callback, delay),
    setInterval: (callback, delay) => schedule(callback, delay, delay),
    clear: id => timers.delete(id),
    async advance(ms) {
      const until = made.now + ms;
      for (;;) {
        const next = [...timers].filter(([, item]) => item.at <= until)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        const [id, item] = next;
        made.now = item.at;
        if (item.interval) item.at += item.interval;
        else timers.delete(id);
        item.callback();
        await new Promise(resolve => setImmediate(resolve));
      }
      made.now = until;
      await new Promise(resolve => setImmediate(resolve));
    },
  };
  const deadlineSignal = parent => {
    const controller = new AbortController();
    clock.setTimeout(() => controller.abort(new Error('voice request timed out')), 5000);
    return parent ? AbortSignal.any([parent, controller.signal]) : controller.signal;
  };
  const fallbackFetch = (_url, options) => {
    const payload = JSON.parse(options.body);
    return jsonResponse(payload.action ? {
      ok: true, owner: payload.action === 'release' ? null : 'desktop',
      capture_id: payload.capture_id, lease_ttl_ms: 15000,
      gate_open: .02, gate_close: .012, silence_ms: 1200, pre_roll_ms: 120,
    } : {});
  };
  const fetch = async (url, options) => {
    made.requests.push({url, options, payload: JSON.parse(options.body)});
    return fetchImpl ? fetchImpl(url, options, fallbackFetch) : fallbackFetch(url, options);
  };
  class Lease extends micModule.CaptureLease {
    constructor(options) {
      super({...options, fetchImpl: fetch, requestSignal: deadlineSignal});
      made.leases.push(this);
    }
    startRenewal(interval) {
      this.stopRenewal();
      this.released = false;
      this.renewTimer = clock.setInterval(() => { void this.renew(); }, interval);
    }
    stopRenewal() { clock.clear(this.renewTimer); this.renewTimer = null; }
  }
  class Gate extends micModule.MicInputGate {
    push(samples, rate) { return super.push(samples, rate, made.now); }
  }
  const stream = () => {
    const track = {label: 'test mic', stopped: false, stop() { this.stopped = true; }};
    const item = {track, getTracks: () => [track], getAudioTracks: () => [track]};
    made.streams.push(item);
    return item;
  };
  class AudioContext {
    state = 'running';
    sampleRate = 48000;
    audioWorklet = {addModule: async () => {}};
    constructor() { made.contexts.push(this); }
    createMediaStreamSource() { return {connect() {}}; }
    createAnalyser() { return {}; }
    close() { this.state = 'closed'; return closeContext?.(this) || Promise.resolve(); }
  }
  class AudioWorkletNode {
    constructor() {
      this.port = {onmessage: null, postMessage: data => { this.sent.push(data); }};
      this.sent = [];
      made.nodes.push(this);
    }
    samples(frame) { this.port.onmessage({data: frame.buffer}); }
    flushed() { this.port.onmessage({data: {type: 'flushed'}}); }
  }
  let captureId = 0;
  const context = {
    state: {mic: null, micActive: false, voiceSequence: 0}, API: {headers: () => ({})},
    micHelpers: {...micModule, CaptureLease: Lease, MicInputGate: Gate, voiceRequestSignal: deadlineSignal},
    draftHelpers: {createVoiceDraftController: options => draftModule.createVoiceDraftController({
      ...options, setTimer: clock.setTimeout, clearTimer: clock.clear,
    })},
    fetch, AudioContext, AudioWorkletNode, AbortController, AbortSignal, ArrayBuffer, Float32Array,
    performance: {now: () => made.now}, crypto: {randomUUID: () => `capture-${++captureId}`},
    setTimeout: clock.setTimeout, clearTimeout: clock.clear,
    setInterval: clock.setInterval, clearInterval: clock.clear,
    navigator: {mediaDevices: {getUserMedia: constraints => {
      made.permissionRequests.push(constraints);
      return getUserMedia ? getUserMedia(stream, made.permissionRequests.length) : Promise.resolve(stream());
    }}},
    preferredMicId: () => 'selected-device', refreshMicDevices: () => {}, setVal: () => {},
    setMicButtonState: (pressed, busy = false) => made.micButtonStates.push({pressed: Boolean(pressed), busy: Boolean(busy)}),
    announceMicStatus: text => made.micStatuses.push(String(text)),
    chatMic: {style: {}}, micState: {textContent: ''},
    cancelSpeechPlayback: () => { made.cancellations += 1; context.state.speechPlayback = null; },
    earlySpeech: {scheduled: 0, sources: new Set(), muted: false},
    stopEarlySpeech: (mute = false) => { made.earlyStops.push(mute); context.earlySpeech.scheduled = 0; context.earlySpeech.sources.clear(); },
    assistantSpeechActive: () => Boolean(context.state.speechPlayback)
      || context.earlySpeech.scheduled > 0 || context.earlySpeech.sources.size > 0,
    addMessage: (...args) => made.messages.push(args), handleEnvelope: data => made.envelopes.push(data),
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    window: {__jawlScene: {setMotionState() {}}, dispatchEvent: event => made.diagnostics.push(event.detail)},
    btoa: text => Buffer.from(text, 'binary').toString('base64'),
  };
  const names = ['startMic', 'getCaptureClientId', 'uploadChunk', 'voiceCaptureDiagnostic', 'enqueueMicOperation',
    'finalizeAfterMicUploads', 'drainPendingMicAudio', 'flushPendingMicAudio', 'micTurnIsCurrent', 'micCaptureIsCurrent', 'newVoiceUtterance', 'finishUtterance',
    'flushMicWorklet', 'stopMic', 'downsample', 'pcm16Base64', 'updateMicTurn', 'assistantSpeechActive'];
  const source = names.map(appFunction).join('\n').replace(
    "await import('./voice-input.js')", 'await Promise.resolve(globalThis.micHelpers)',
  ).replace("await import('./voice-draft.js')", 'await Promise.resolve(globalThis.draftHelpers)');
  vm.runInNewContext(`let micStartGeneration = 0, micStarting = false, pendingCaptureLease = null;
    ${source}
    globalThis.voice = {${names.join(',')},
      get controls() { return {micStartGeneration, micStarting, pendingCaptureLease}; }};`, context);
  return {context, made, clock, voice: context.voice, makeStream: stream,
    requests: (suffix) => made.requests.filter(item => item.url.endsWith(suffix))};
}

test('actual app draft wiring renders transient text and clears it on finalization and stop', async () => {
  let finishDraft;
  const harness = micHarness({fetchImpl: (url, options, fallback) => {
    if (url.endsWith('/api/voice/draft')) return new Promise(resolve => { finishDraft = resolve; });
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  assert.deepEqual(harness.made.micButtonStates.at(-1), {pressed: true, busy: false});
  assert.equal(harness.made.micStatuses.at(-1), 'Микрофон включён.');
  const mic = listeningMic(harness);
  const draft = mic.drafts.tick();
  await waitFor(() => harness.requests('/api/voice/draft').length === 1);
  const request = harness.requests('/api/voice/draft')[0];
  assert.equal(request.payload.session_id, mic.utterance.sessionId);
  assert.equal(request.payload.correlation_id, mic.utterance.correlationId);
  assert.equal(request.payload.capture_id, mic.lease.leaseId);
  finishDraft(jsonResponse({ok: true, mode: 'streaming', draft: 'Проверка '.repeat(100)}));
  await draft;
  assert.ok(harness.context.micState.textContent.startsWith('Слышу (предварительно): '));
  assert.ok(harness.context.micState.textContent.length <= 184);
  assert.equal(harness.made.messages.length, 0);
  const finishing = harness.voice.finishUtterance();
  assert.equal(mic.draftText, '');
  assert.equal(harness.context.micState.textContent, 'Распознаю…');
  await harness.voice.stopMic();
  await finishing;
  assert.equal(harness.context.micState.textContent, 'Микрофон выключен.');
  assert.deepEqual(harness.made.micButtonStates.at(-1), {pressed: false, busy: false});
  assert.equal(harness.made.micStatuses.at(-1), 'Микрофон выключен.');
  assert.equal((await mic.drafts.tick()).status, 'stopped');
});

function listeningMic(harness) {
  const mic = harness.context.state.mic;
  mic.heard = true;
  mic.turnGeneration = 1;
  // PCM acceptance is controlled here so these tests isolate the app's session
  // routing; the real gate's speech/noise behavior has its own tests.
  mic.inputGate.push = frame => ({opened: false, frames: [frame]});
  return mic;
}

function loadQueueHelper() {
  const context = {};
  vm.runInNewContext([
    appFunction('enqueueMicOperation'),
    appFunction('finalizeAfterMicUploads'),
    appFunction('micTurnIsCurrent'),
    'globalThis.helpers = {enqueueMicOperation, finalizeAfterMicUploads, micTurnIsCurrent};',
  ].join('\n'), context);
  return context.helpers;
}

test('cancel during TTS fetch aborts the owner and ignores a late stream response', async () => {
  let resolveFetch;
  const harness = speechHarness((url, options) => url === '/api/tts/cancel'
    ? Promise.resolve({ok: true}) : new Promise((resolve) => {
    resolveFetch = resolve;
    options.signal.addEventListener('abort', () => {}, {once: true});
  }));
  const pending = harness.speech.speakFinal({text: 'старый ответ'});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.made.stopButton.disabled, false);
  harness.speech.cancelSpeechPlayback();
  assert.equal(harness.made.stopButton.disabled, true);
  assert.equal(harness.made.requests[0][1].signal.aborted, true);
  resolveFetch(ndjsonResponse([audioEvent(0), doneEvent(1)]));
  await pending;
  assert.equal(harness.made.sources.length, 0);
});

test('one playback owner schedules NDJSON WAV and cancellation stops every source', async () => {
  const harness = speechHarness();
  const task = harness.speech.speakFinal({text: 'ответ'});
  await waitFor(() => harness.made.sources.length === 1);
  const source = harness.made.sources[0];
  assert.ok(source);
  assert.equal(source.startAt, 0.12);
  assert.equal(harness.made.diagnostics[0].state, 'firstscheduled');
  harness.speech.cancelSpeechPlayback();
  await task;
  assert.equal(source.stopped, true);
  assert.equal(harness.made.disconnected, 2);
  assert.equal(harness.context.state.speechPlayback, null);
  assert.deepEqual(harness.made.motion, ['speaking', 'idle']);
  assert.equal(harness.made.diagnostics.at(-1).state, 'cancel');
  assert.deepEqual(harness.made.playbackMarkers.map(item => item.active), [true, false]);
});

test('stop button uses the single speech cancellation path', async () => {
  const harness = speechHarness();
  const task = harness.speech.speakFinal({text: 'ответ'});
  await waitFor(() => harness.made.sources.length === 1);
  assert.equal(harness.made.stopButton.disabled, false);
  harness.made.stopButton.listeners.click();
  await task;
  assert.equal(harness.made.sources[0].stopped, true);
  assert.equal(harness.made.stopButton.disabled, true);
  assert.equal(harness.made.diagnostics.at(-1).state, 'cancel');
});

test('completed stream emits only bounded playback diagnostics and preview shares the stream path', async () => {
  const harness = speechHarness(() => ndjsonResponse([audioEvent(0), audioEvent(1), doneEvent(2)]));
  const task = harness.speech.speakFinal({text: 'preview text'});
  await waitFor(() => harness.made.sources.length === 2);
  assert.deepEqual(harness.made.diagnostics.map(item => item.state), ['firstscheduled', 'sourcespeak']);
  assert.ok(harness.made.diagnostics.every(item => !('text' in item) && !('audio' in item)));
  assert.equal(harness.made.diagnostics[0].generation, 1);
  for (const source of harness.made.sources) source.onended?.();
  await task;
  assert.equal(harness.made.diagnostics.at(-1).state, 'done');
  assert.equal(harness.made.requests[0][0], '/api/tts/stream');
  assert.deepEqual(harness.made.playbackMarkers.map(item => item.active), [true, false]);
  assert.ok(harness.made.playbackMarkers.every(item => item.ttl_seconds === 30));
  assert.match(appSource, /void speakFinal\(\{text\}\)/);
  assert.doesNotMatch(appSource, /\/api\/tts\/synthesize/);
});

test('early sentence audio is suppressed through the end of its last scheduled source', async () => {
  const harness = speechHarness();
  harness.speech.earlySpeech.streamPending = true;
  await harness.speech.playEarlyAudioEvent(audioEvent(0));
  assert.deepEqual(harness.made.playbackMarkers.map(item => item.active), [true]);
  harness.made.sources[0].onended?.();
  assert.deepEqual(harness.made.playbackMarkers.map(item => item.active), [true]);
  harness.speech.earlySpeech.streamPending = false;
  harness.speech.syncSelfTtsSuppression();
  await harness.speech.markerQueue;
  assert.deepEqual(harness.made.playbackMarkers.map(item => item.active), [true, false]);
});

test('repeated TTS outage shows one notice until playback recovers', async () => {
  const responses = [
    new Response(null, {status: 503}),
    new Response(null, {status: 503}),
    ndjsonResponse([audioEvent(0), doneEvent(1)]),
    new Response(null, {status: 503}),
  ];
  const harness = speechHarness(async url => (url === '/api/tts/cancel'
    ? new Response(null, {status: 200})
    : responses.shift()));

  await harness.speech.speakFinal({text: 'первый ответ'});
  await harness.speech.speakFinal({text: 'второй ответ'});
  assert.equal(harness.made.messages.length, 1);
  assert.match(harness.made.messages[0][1], /TTS недоступен/);

  const recovered = harness.speech.speakFinal({text: 'речь восстановилась'});
  await waitFor(() => harness.made.sources.length === 1);
  harness.made.sources[0].onended?.();
  await recovered;

  await harness.speech.speakFinal({text: 'четвёртый ответ'});
  assert.equal(harness.made.messages.length, 2);
});

test('queued audio uploads remain ordered ahead of utterance finalization', async () => {
  const {enqueueMicOperation, finalizeAfterMicUploads} = loadQueueHelper();
  const mic = {active: true, uploadQueue: {tail: Promise.resolve(), pending: 0}};
  const order = [];
  let releaseOldUpload;
  enqueueMicOperation(mic, () => {
    order.push('old-audio-1');
    return new Promise((resolve) => { releaseOldUpload = resolve; });
  });
  enqueueMicOperation(mic, async () => { order.push('old-audio-2'); });
  let markEndStarted;
  const endStarted = new Promise((resolve) => { markEndStarted = resolve; });
  let releaseResponse;
  const finalization = finalizeAfterMicUploads(mic, () => {
    order.push('end-start');
    markEndStarted();
    return new Promise((resolve) => { releaseResponse = resolve; });
  });
  enqueueMicOperation(mic, async () => { order.push('next-audio'); });
  await mic.uploadQueue.tail;
  assert.deepEqual(order, ['old-audio-1', 'next-audio']);
  releaseOldUpload();
  await endStarted;
  assert.deepEqual(order, ['old-audio-1', 'next-audio', 'old-audio-2', 'end-start']);
  enqueueMicOperation(mic, async () => { order.push('response-audio'); });
  await mic.uploadQueue.tail;
  assert.deepEqual(order, ['old-audio-1', 'next-audio', 'old-audio-2', 'end-start', 'response-audio']);
  releaseResponse({ok: true});
  await finalization;
});

test('audio upload backlog stays bounded', async () => {
  const {enqueueMicOperation} = loadQueueHelper();
  const mic = {active: true, uploadQueue: {tail: Promise.resolve(), pending: 0}};
  const tasks = Array.from({length: 6}, () => enqueueMicOperation(mic, async () => {}, true));
  assert.equal(mic.uploadQueue.pending, 6);
  assert.equal(enqueueMicOperation(mic, async () => {}, true), null);
  await Promise.all(tasks);
  await mic.uploadQueue.tail;
  assert.equal(mic.uploadQueue.pending, 0);
});

test('stop invalidates queued uploads, finalization, and any pending turn response', async () => {
  const {enqueueMicOperation, finalizeAfterMicUploads, micTurnIsCurrent} = loadQueueHelper();
  const mic = {active: true, turnGeneration: 4, uploadQueue: {tail: Promise.resolve(), pending: 0}};
  const context = {state: {mic}};
  const started = [];
  let markStarted;
  const firstStarted = new Promise((resolve) => { markStarted = resolve; });
  let releaseUpload;
  const first = enqueueMicOperation(mic, () => new Promise((resolve) => {
    started.push('in-flight');
    markStarted();
    releaseUpload = resolve;
  }));
  const queued = enqueueMicOperation(mic, async () => { started.push('queued'); });
  const finalization = finalizeAfterMicUploads(mic, async () => { started.push('end'); });
  await firstStarted;
  assert.deepEqual(started, ['in-flight']);
  mic.active = false;
  context.state.mic = null;
  releaseUpload();
  await Promise.all([first, queued, finalization]);
  assert.deepEqual(started, ['in-flight']);

  const currentCheck = vm.runInNewContext(
    `${appFunction('micTurnIsCurrent')}\nglobalThis.check = micTurnIsCurrent;`, context,
  );
  assert.equal(currentCheck(mic, 4), false);
});

test('actual finish flush uploads and ends the old utterance before rotating identity', async () => {
  let releaseAudio;
  const harness = micHarness({fetchImpl: (url, _options, fallback) => {
    if (url.endsWith('/api/voice/audio')) return new Promise(resolve => { releaseAudio = () => resolve(jsonResponse()); });
    return fallback(url, _options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const oldId = mic.utterance.sessionId;
  const oldCorrelation = mic.utterance.correlationId;
  const finishing = harness.voice.finishUtterance();
  await waitFor(() => mic.gate.sent.some(message => message?.type === 'flush'));
  mic.gate.samples(new Float32Array(160).fill(0.03));
  mic.gate.flushed();
  await waitFor(() => harness.requests('/api/voice/audio').length === 1);
  const chunk = harness.requests('/api/voice/audio')[0].payload;
  assert.equal(chunk.session_id, oldId);
  assert.equal(chunk.correlation_id, oldCorrelation);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.requests('/api/voice/end').length, 0);
  releaseAudio();
  await waitFor(() => harness.requests('/api/voice/end').length === 1);
  const end = harness.requests('/api/voice/end')[0].payload;
  assert.equal(end.session_id, oldId);
  assert.equal(end.correlation_id, oldCorrelation);
  assert.notEqual(mic.utterance.sessionId, oldId);
  await finishing;
  await harness.voice.stopMic();
});

test('actual finish preserves the utterance when speech resumes during worklet flush', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const utterance = mic.utterance;
  const finishing = harness.voice.finishUtterance();
  await waitFor(() => mic.gate.sent.some(message => message?.type === 'flush'));
  mic.inputGate.lastVoiceAt += 100;
  mic.gate.samples(new Float32Array(160).fill(0.03));
  mic.gate.flushed();
  await finishing;
  await mic.uploadQueue.tail;
  assert.equal(harness.requests('/api/voice/end').length, 0);
  assert.equal(mic.utterance, utterance);
  assert.equal(mic.heard, true);
  assert.equal(mic.finalizing, false);
  await harness.voice.stopMic();
});

test('actual finish keeps a completed turn when speech resumes during the endpoint response', async () => {
  let releaseEnd;
  const harness = micHarness({fetchImpl: (url, options, fallback) => {
    if (url.endsWith('/api/voice/end')) return new Promise(resolve => {
      releaseEnd = () => resolve(jsonResponse({ok: true, transcript: 'Первая часть.', responses: [{text: 'Ответ'}]}));
    });
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const finishing = harness.voice.finishUtterance();
  await waitFor(() => mic.gate.sent.some(message => message?.type === 'flush'));
  mic.gate.flushed();
  await waitFor(() => harness.requests('/api/voice/end').length === 1);
  assert.equal(mic.finalizing, true);

  mic.heard = true;
  mic.turnGeneration += 1;
  releaseEnd();
  await finishing;

  assert.deepEqual(harness.made.messages, [['user', 'Первая часть.']]);
  assert.deepEqual(harness.made.envelopes, [{text: 'Ответ'}]);
  await harness.voice.stopMic();
});

test('actual microphone barge-in cancels playback only and leaves a durable task untouched', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  const task = {status: 'running', cancelCalls: 0};
  harness.context.state.durableTask = task;
  harness.context.state.speechPlayback = {};
  const mic = harness.context.state.mic;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  mic.gate.samples(new Float32Array(160).fill(0.03));
  assert.equal(harness.made.cancellations, 0, 'onset alone does not establish an interruption');
  mic.draftText = 'Стой!';
  await harness.clock.advance(100);
  assert.equal(harness.made.cancellations, 1);
  assert.deepEqual(task, {status: 'running', cancelCalls: 0});
  assert.equal(harness.made.requests.some(item => /cancel|task/i.test(item.url)), false);
  await harness.voice.stopMic();
});

test('short overlapping acknowledgement finalizes under its own identity without cancelling speech', async () => {
  const harness = micHarness({fetchImpl: (url, options, fallback) => url.endsWith('/api/voice/end')
    ? jsonResponse({ok: true, filtered: 'user_backchannel', responses: []}) : fallback(url, options)});
  await harness.voice.startMic();
  const playback = {};
  harness.context.state.speechPlayback = playback;
  const mic = harness.context.state.mic;
  const oldSession = mic.utterance.sessionId;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  mic.gate.samples(new Float32Array(4800).fill(0.03));
  mic.draftText = 'Угу, понятно.';
  await harness.clock.advance(400);
  assert.equal(mic.finalizing, true);
  mic.gate.flushed();
  await waitFor(() => harness.requests('/api/voice/end').length === 1 && !mic.finalizing);
  assert.equal(harness.made.cancellations, 0);
  assert.equal(harness.context.state.speechPlayback, playback);
  const end = harness.requests('/api/voice/end')[0].payload;
  assert.equal(end.session_id, oldSession);
  assert.equal(end.suppress_backchannel, true);
  assert.notEqual(mic.utterance.sessionId, oldSession);
  assert.equal(harness.made.envelopes.length, 0);
  await harness.voice.stopMic();
});

test('short question during speech interrupts and is not suppressed as a backchannel', async () => {
  const harness = micHarness({fetchImpl: (url, options, fallback) => url.endsWith('/api/voice/end')
    ? jsonResponse({ok: true, transcript: 'Да?', responses: []}) : fallback(url, options)});
  await harness.voice.startMic();
  harness.context.state.speechPlayback = {};
  const mic = harness.context.state.mic;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  mic.gate.samples(new Float32Array(4800).fill(0.03));
  mic.draftText = 'Да?';
  await harness.clock.advance(500);
  assert.equal(harness.made.cancellations, 1);
  assert.equal(mic.finalizing, true);
  mic.gate.flushed();
  await waitFor(() => harness.requests('/api/voice/end').length === 1 && !mic.finalizing);
  const end = harness.requests('/api/voice/end')[0].payload;
  assert.equal(end.suppress_backchannel, false);
  await harness.voice.stopMic();
});

test('noise followed by silence cannot accumulate barge-in duration or cancel a newer playback', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  harness.context.state.speechPlayback = {};
  const mic = harness.context.state.mic;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  mic.gate.samples(new Float32Array(4800).fill(0.03));
  await harness.clock.advance(600);
  assert.equal(harness.made.cancellations, 0);
  assert.equal(mic.voicedMs, 100);
  harness.context.state.speechPlayback = {};
  mic.draftText = 'Стоп';
  await harness.clock.advance(100);
  assert.equal(harness.made.cancellations, 0, 'old draft cannot cancel replacement playback');
  await harness.voice.stopMic();
});

test('sustained voiced audio interrupts when streaming drafts are unavailable', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  harness.context.state.speechPlayback = {};
  const mic = harness.context.state.mic;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  for (let i = 0; i < 6; i += 1) mic.gate.samples(new Float32Array(4800).fill(0.03));
  assert.equal(harness.made.cancellations, 1);
  mic.gate.samples(new Float32Array(4800).fill(0.03));
  assert.equal(harness.made.cancellations, 1);
  await harness.voice.stopMic();
});

test('barge-in stops streamed early speech even without a full playback owner', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  harness.context.earlySpeech.scheduled = 2;
  harness.context.earlySpeech.sources.add({});
  const mic = harness.context.state.mic;
  mic.inputGate.push = () => ({opened: true, frames: [], voiceActive: true, rms: 0.03});
  mic.gate.samples(new Float32Array(160).fill(0.03));
  assert.equal(mic.overlapStarted, true);
  assert.equal(mic.overlapEarlySpeech, true);
  mic.draftText = 'Стой!';
  await harness.clock.advance(100);
  assert.deepEqual(harness.made.earlyStops, [true]);
  assert.equal(harness.made.cancellations, 0);
  await harness.voice.stopMic();
});

test('finished early speech chunks do not keep playback marked active', async () => {
  const harness = micHarness();
  harness.context.earlySpeech.scheduled = 2;
  assert.equal(harness.voice.assistantSpeechActive(), false);
  harness.context.earlySpeech.sources.add({});
  assert.equal(harness.voice.assistantSpeechActive(), true);
});

test('server endpoint policy shortens the actual microphone commit window', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  mic.serverDecision = {required_ms: 500, action: 'commit_turn'};
  mic.draftText = 'Открой файл';
  await harness.clock.advance(600);
  assert.equal(mic.finalizing, true);
  await harness.voice.stopMic();
});

test('Russian unfinished draft extends the actual microphone endpoint beyond the configured silence', async () => {
  const harness = micHarness();
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  mic.draftText = 'Я хотел чтобы';
  await harness.clock.advance(1300);
  assert.equal(mic.finalizing, false);
  assert.equal(harness.requests('/api/voice/end').length, 0);
  await harness.clock.advance(900);
  assert.equal(mic.finalizing, true);
  await harness.voice.stopMic();
});

test('an older stop cannot clear a replacement microphone start', async () => {
  let releaseClose;
  const harness = micHarness({closeContext: context => context === harnessContext?.made.contexts[0]
    ? new Promise(resolve => { releaseClose = resolve; }) : Promise.resolve()});
  const harnessContext = harness;
  await harness.voice.startMic();
  const oldLease = harness.context.state.mic.lease;
  const stopping = harness.voice.stopMic();
  await harness.voice.startMic();
  const replacement = harness.context.state.mic;
  assert.ok(replacement?.active);
  assert.notEqual(replacement.lease, oldLease);
  releaseClose();
  await stopping;
  assert.equal(harness.context.state.mic, replacement);
  assert.equal(harness.context.state.micActive, true);
  await harness.voice.stopMic();
});

test('lease loss while getUserMedia is pending stops visibly and rejects the late stream', async () => {
  let resolveMedia;
  const harness = micHarness({
    getUserMedia: makeStream => new Promise(resolve => { resolveMedia = () => resolve(makeStream()); }),
    fetchImpl: async (url, options, fallback) => {
      const payload = JSON.parse(options.body);
      if (url.endsWith('/api/voice/capture') && payload.action === 'renew') return jsonResponse({}, 409);
      return fallback(url, options);
    },
  });
  const starting = harness.voice.startMic();
  await waitFor(() => harness.made.permissionRequests.length === 1);
  const lease = harness.made.leases[0];
  await lease.renew();
  await waitFor(() => harness.made.requests.some(item => item.payload.action === 'release'));
  resolveMedia();
  await starting;
  assert.equal(harness.context.state.mic, null);
  assert.match(harness.made.messages.at(-1)[1], /Захват остановлен.*409/);
  assert.ok(harness.made.streams[0].track.stopped);
});

test('a lost acquire response is followed by a best-effort release', async () => {
  const harness = micHarness({fetchImpl: async (url, options, fallback) => {
    const payload = JSON.parse(options.body);
    if (url.endsWith('/api/voice/capture') && payload.action === 'acquire') throw new Error('response lost');
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  assert.deepEqual(harness.made.requests.map(item => item.payload.action), ['acquire', 'release']);
  assert.equal(harness.made.permissionRequests.length, 0);
  assert.match(harness.context.micState.textContent, /Микрофон недоступен: response lost/);
});

test('audio upload backpressure buffers captured PCM and resumes without stopping capture', async () => {
  let releaseFirst;
  let audioRequests = 0;
  const harness = micHarness({fetchImpl: (url, options, fallback) => {
    if (url.endsWith('/api/voice/audio')) {
      audioRequests += 1;
      if (audioRequests === 1) return new Promise(resolve => { releaseFirst = () => resolve(jsonResponse()); });
    }
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const batch = () => new Float32Array(12000).fill(0.03);
  harness.voice.uploadChunk(batch(), 48000);
  await waitFor(() => harness.requests('/api/voice/audio').length === 1);
  for (let i = 0; i < 6; i += 1) harness.voice.uploadChunk(batch(), 48000);
  assert.equal(mic.uploadQueue.pending, 6);
  assert.ok(mic.pendingUploadSamples >= batch().length);
  assert.equal(harness.context.state.mic, mic);
  assert.equal(harness.context.state.micActive, true);
  assert.equal(harness.made.diagnostics.length, 0);
  assert.equal(harness.made.messages.some(([, message]) => /аудиоканал не успевает/.test(message)), false);

  releaseFirst();
  await waitFor(() => mic.uploadQueue.pending === 0 && mic.pendingUploadSamples === 0, 2000);
  await mic.uploadQueue.tail;
  assert.equal(harness.requests('/api/voice/audio').length, 7);
  assert.ok(audioRequests >= 2);
  assert.equal(harness.context.state.mic, mic);
  assert.equal(mic.uploadQueue.pending, 0);
});

test('utterance finalization waits for buffered backpressure and keeps one turn identity', async () => {
  let releaseFirst;
  let audioRequests = 0;
  let audioCountAtEnd = 0;
  const harness = micHarness({fetchImpl: (url, _options, fallback) => {
    if (url.endsWith('/api/voice/audio')) {
      audioRequests += 1;
      if (audioRequests === 1) return new Promise(resolve => { releaseFirst = () => resolve(jsonResponse()); });
    }
    if (url.endsWith('/api/voice/end')) audioCountAtEnd = audioRequests;
    return fallback(url, _options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const originalSession = mic.utterance.sessionId;
  const originalCorrelation = mic.utterance.correlationId;
  const batch = () => new Float32Array(12000).fill(0.03);
  harness.voice.uploadChunk(batch(), 48000);
  await waitFor(() => harness.requests('/api/voice/audio').length === 1);
  for (let i = 0; i < 6; i += 1) harness.voice.uploadChunk(batch(), 48000);

  const finishing = harness.voice.finishUtterance();
  await waitFor(() => mic.gate.sent.some(message => message?.type === 'flush'));
  mic.gate.flushed();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.requests('/api/voice/end').length, 0);
  releaseFirst();
  await waitFor(() => harness.requests('/api/voice/end').length === 1, 2000);
  await finishing;

  assert.equal(audioCountAtEnd, 7);
  assert.ok(harness.requests('/api/voice/audio').every(item =>
    item.payload.session_id === originalSession && item.payload.correlation_id === originalCorrelation));
});

test('HTTP 409 from an actual audio chunk reports failure and stops capture', async () => {
  const harness = micHarness({fetchImpl: async (url, options, fallback) => {
    if (url.endsWith('/api/voice/audio')) return jsonResponse({error: 'capture conflict'}, 409);
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  harness.voice.uploadChunk(new Float32Array(160), 48000);
  await waitFor(() => harness.context.state.mic === null);
  assert.equal(mic.active, false);
  assert.equal(harness.context.state.micActive, false);
  assert.ok(harness.made.messages.some(([, message]) => /Захват остановлен: voice\/audio failed \(HTTP 409\)/.test(message)));
  assert.equal(harness.context.micState.textContent, 'Микрофон выключен.');
  assert.equal(harness.made.diagnostics[0].reason, 'http_failure');
  assert.equal(harness.made.diagnostics[0].status, 409);
});

test('audio fetch failure emits bounded redacted evidence before capture teardown', async () => {
  const harness = micHarness({fetchImpl: (url, options, fallback) => {
    if (url.endsWith('/api/voice/audio')) throw new TypeError('PRIVATE_CAPTURE_SENTINEL');
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  harness.voice.uploadChunk(new Float32Array(160), 48000);
  await waitFor(() => harness.context.state.mic === null);
  const evidence = harness.made.diagnostics[0];
  assert.equal(evidence.reason, 'transport_failure');
  assert.equal(evidence.context_state, 'running');
  assert.equal(evidence.active, true);
  assert.equal(evidence.status, null);
  assert.ok(!JSON.stringify(evidence).includes('PRIVATE_CAPTURE_SENTINEL'));
  for (const key of ['capture_id', 'pcm16_base64', 'transcript', 'message']) assert.ok(!(key in evidence));
  assert.equal(mic.active, false);
});

test('HTTP 409 from actual turn finalization reports failure and stops capture', async () => {
  const harness = micHarness({fetchImpl: async (url, options, fallback) => {
    if (url.endsWith('/api/voice/end')) return jsonResponse({error: 'capture conflict'}, 409);
    return fallback(url, options);
  }});
  await harness.voice.startMic();
  const mic = listeningMic(harness);
  const finishing = harness.voice.finishUtterance();
  await waitFor(() => mic.gate.sent.some(message => message?.type === 'flush'));
  mic.gate.flushed();
  await finishing;
  assert.equal(harness.context.state.mic, null);
  assert.equal(harness.context.state.micActive, false);
  assert.ok(harness.made.messages.some(([, message]) => /Голосовой ход не завершился: voice\/end failed \(HTTP 409\)/.test(message)));
  assert.equal(harness.context.micState.textContent, 'Микрофон выключен.');
});
`````

### `desktop/tests/avatar-scene-lifecycle.test.mjs`

`````javascript
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
`````

### `desktop/tests/main-startup.test.js`

`````javascript
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const mainPath = path.join(__dirname, '..', 'main.js');
const source = fs.readFileSync(mainPath, 'utf8');

function createHarness({ health = () => true, trayIconAvailable = true } = {}) {
  const state = {
    windows: [],
    requests: 0,
    externalUrls: [],
    permissionRequestHandler: null,
    permissionCheckHandler: null,
    appHandlers: new Map(),
    ipcHandlers: new Map(),
    commandLine: [],
    startup: null,
    trays: [],
    quitRequested: false,
    errors: [],
    sentMessages: [],
  };
  let healthCheck = health;

  class MockBrowserWindow {
    constructor(options) {
      this.options = options;
      this.urls = [];
      this.handlers = new Map();
      this.destroyed = false;
      this.alwaysOnTop = false;
      this.hidden = false;
      this.size = [options.width, options.height];
      this.webContents = new EventEmitter();
      this.webContents.setWindowOpenHandler = (handler) => {
        this.webContents.openHandler = handler;
      };
      this.webContents.send = (channel, ...args) => state.sentMessages.push({window: this, channel, args});
      this.webContents.getURL = () => this.urls.at(-1) || '';
      state.windows.push(this);
    }
    setAlwaysOnTop(flag) {
      this.alwaysOnTop = Boolean(flag);
    }
    setIgnoreMouseEvents(flag) {
      this.ignoreMouseEvents = Boolean(flag);
    }
    hide() { this.hidden = true; }
    show() { this.hidden = false; }
    focus() { this.focused = true; }
    setSize(w, h) {
      this.size = [w, h];
    }
    loadURL(url) {
      this.urls.push(url);
      return Promise.resolve();
    }
    loadFile(file) {
      this.file = file;
      return Promise.resolve();
    }
    on(name, handler) {
      this.handlers.set(name, handler);
    }
    isDestroyed() {
      return this.destroyed;
    }
    static getAllWindows() {
      return state.windows.filter((window) => !window.destroyed);
    }
  }

  class MockTray extends EventEmitter {
    constructor(icon) {
      super();
      if (icon.isEmpty?.()) throw new Error('empty icon');
      this.icon = icon;
      state.trays.push(this);
    }
    setToolTip(value) { this.tooltip = value; }
    setContextMenu(menu) { this.menu = menu; }
  }

  const electron = {
    app: {
      commandLine: { appendSwitch: (...args) => state.commandLine.push(args) },
      whenReady() {
        return {
          then(callback) {
            state.startup = Promise.resolve().then(callback);
            return state.startup;
          },
        };
      },
      on(name, handler) { state.appHandlers.set(name, handler); },
      quit() { state.quitRequested = true; },
    },
    BrowserWindow: MockBrowserWindow,
    Tray: MockTray,
    Menu: { buildFromTemplate: (items) => items },
    nativeImage: { createFromPath: () => ({
      isEmpty: () => !trayIconAvailable,
      getSize: () => ({ width: 480, height: 640 }),
      crop: () => ({ resize: () => ({ trayIcon: true }) }),
    }) },
    shell: { openExternal(url) { state.externalUrls.push(url); return Promise.resolve(); } },
    ipcMain: { on(name, handler) { state.ipcHandlers.set(name, handler); } },
    session: {
      defaultSession: {
        setPermissionRequestHandler(handler) { state.permissionRequestHandler = handler; },
        setPermissionCheckHandler(handler) { state.permissionCheckHandler = handler; },
      },
    },
  };
  const mockHttp = {
    get(options, callback) {
      state.requests += 1;
      const request = new EventEmitter();
      request.destroy = () => {};
      queueMicrotask(() => {
        if (healthCheck(state.requests)) {
          callback({ statusCode: 200, resume() {} });
        } else {
          request.emit('error', new Error('not ready'));
        }
      });
      assert.equal(options.path, '/api/health');
      assert.equal(options.host, '127.0.0.1');
      return request;
    },
  };
  const mockRequire = (id) => {
    if (id === 'electron') return electron;
    if (id === 'path') return path;
    if (id === 'http') return mockHttp;
    if (id === './runtime-config') return {
      controlPort: (root) => require('../runtime-config').controlPort(root, {}, {
        statSync(filename) {
          if (filename.endsWith('.local.json')) throw Object.assign(new Error(), { code: 'ENOENT' });
          return { size: 26 };
        },
        readFileSync: () => '{"ports":{"control":2367}}',
      }),
    };
    throw new Error(`Unexpected import: ${id}`);
  };
  const context = {
    require: mockRequire,
    __dirname: path.dirname(mainPath),
    process: { env: {}, argv: ['electron'], platform: 'win32' },
    URL,
    setTimeout: (callback) => { queueMicrotask(callback); return 0; },
    console: { error: (...args) => state.errors.push(args) },
  };
  vm.runInNewContext(source, context, { filename: mainPath });

  return {
    state,
    setHealth(check) { healthCheck = check; },
    async ready() { await state.startup; },
  };
}

test('waits for health before navigating the app window to the companion', async () => {
  const harness = createHarness({ health: (attempt) => attempt >= 3 });
  await harness.ready();

  const window = harness.state.windows[0];
  assert.equal(harness.state.requests, 3);
  assert.match(window.urls[0], /^data:text\/html/);
  assert.equal(window.urls[1], 'http://127.0.0.1:2367/app');
  assert.equal(window.urls.filter((url) => url === 'http://127.0.0.1:2367/app').length, 1);
});

test('keeps the daily UI in the tray when its window closes and exposes show/exit actions', async () => {
  const harness = createHarness();
  await harness.ready();

  const window = harness.state.windows[0];
  const close = window.handlers.get('close');
  let prevented = false;
  close({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(window.hidden, true);
  assert.equal(harness.state.trays.length, 1);
  assert.equal(harness.state.trays[0].tooltip, 'JAWL Voice Companion');

  const [showItem, stopItem, , exitItem] = harness.state.trays[0].menu;
  assert.equal(showItem.label, '\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c JAWL');
  assert.equal(stopItem.label, '\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c \u0432\u0435\u0441\u044c \u043f\u0440\u043e\u0444\u0438\u043b\u044c');
  assert.equal(exitItem.label, '\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441 (\u0441\u043b\u0443\u0436\u0431\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0442 \u0440\u0430\u0431\u043e\u0442\u0443)');
  showItem.click();
  assert.equal(window.hidden, false);
  assert.equal(window.focused, true);
  window.hide();
  stopItem.click();
  assert.equal(window.hidden, false);
  assert.equal(window.focused, true);
  assert.equal(harness.state.sentMessages.at(-1).channel, 'jawl-profile-stop-request');
  harness.state.ipcHandlers.get('jawl-profile-stop-accepted')({sender: {}});
  assert.equal(harness.state.quitRequested, false);
  harness.state.ipcHandlers.get('jawl-profile-stop-accepted')({sender: window.webContents});
  assert.equal(harness.state.quitRequested, true);
  exitItem.click();
  assert.equal(harness.state.quitRequested, true);

  harness.state.appHandlers.get('before-quit')();
  prevented = false;
  close({ preventDefault() { prevented = true; } });
  assert.equal(prevented, false);
});

test('does not hide the daily UI when the tray icon cannot be created', async () => {
  const harness = createHarness({ trayIconAvailable: false });
  await harness.ready();

  const window = harness.state.windows[0];
  let prevented = false;
  window.handlers.get('close')({ preventDefault() { prevented = true; } });
  assert.equal(prevented, false);
  assert.equal(window.hidden, false);
  assert.equal(harness.state.trays.length, 0);
});

test('tray stop waits for a recreated renderer to finish loading', async () => {
  const harness = createHarness();
  await harness.ready();
  const oldWindow = harness.state.windows[0];
  oldWindow.destroyed = true;

  const stopItem = harness.state.trays[0].menu[1];
  stopItem.click();
  const replacement = harness.state.windows[1];
  assert.ok(replacement);
  assert.equal(harness.state.sentMessages.length, 0);
  replacement.webContents.emit('did-finish-load');
  assert.equal(replacement.hidden, false);
  assert.equal(replacement.focused, true);
  assert.equal(harness.state.sentMessages.at(-1).channel, 'jawl-profile-stop-request');
});

test('shows bounded recovery and allows one manual retry after the service starts', async () => {
  const harness = createHarness({ health: () => false });
  await harness.ready();

  const window = harness.state.windows[0];
  assert.equal(harness.state.requests, 90);
  assert.match(decodeURIComponent(window.urls.at(-1)), /Повторить подключение/);
  assert.doesNotMatch(window.urls.at(-1), /127\.0\.0\.1:2367\/app/);

  harness.setHealth(() => true);
  let prevented = false;
  window.webContents.emit('will-navigate', { preventDefault() { prevented = true; } }, 'jawl-desktop://retry');
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(prevented, true);
  assert.equal(harness.state.requests, 91);
  assert.equal(window.urls.at(-1), 'http://127.0.0.1:2367/app');
});

test('limits renderer navigation, external links, and media permission to the local audio app', async () => {
  const harness = createHarness();
  await harness.ready();
  const window = harness.state.windows[0];

  let prevented = false;
  window.webContents.emit('will-navigate', { preventDefault() { prevented = true; } }, 'https://example.com/');
  assert.equal(prevented, true);
  assert.deepEqual(harness.state.externalUrls, ['https://example.com/']);
  let framePrevented = false;
  window.webContents.emit('will-frame-navigate', {
    url: 'https://example.com/frame',
    isMainFrame: false,
    preventDefault() { framePrevented = true; },
  });
  assert.equal(framePrevented, true);
  assert.equal(window.webContents.openHandler({ url: 'file:///secret' }).action, 'deny');
  assert.deepEqual(harness.state.externalUrls, ['https://example.com/']);

  const request = harness.state.permissionRequestHandler;
  const ask = (requestingUrl, mediaTypes) => {
    let allowed;
    request({ getURL: () => requestingUrl }, 'media', (value) => { allowed = value; }, { requestingUrl, mediaTypes });
    return allowed;
  };
  assert.equal(ask('http://127.0.0.1:2367/app', ['audio']), true);
  assert.equal(ask('http://127.0.0.1:2367/app', ['audio', 'video']), false);
  assert.equal(ask('http://localhost:2367/app', ['audio']), false);
  assert.equal(ask('https://example.com/', ['audio']), false);

  const check = harness.state.permissionCheckHandler;
  assert.equal(check(null, 'media', 'http://127.0.0.1:2367', { mediaType: 'audio' }), true);
  assert.equal(check(null, 'media', 'http://127.0.0.1:2367', { mediaType: 'video' }), false);

  const windowModeHandler = harness.state.ipcHandlers.get('jawl-window-mode');
  assert.equal(typeof windowModeHandler, 'function');
  windowModeHandler(null, { compact: true, alwaysOnTop: true, clickThrough: true });
  assert.deepEqual(window.size, [360, 540]);
  assert.equal(window.alwaysOnTop, true);
  assert.equal(window.ignoreMouseEvents, true);
  windowModeHandler(null, { compact: false, alwaysOnTop: false, clickThrough: false });
  assert.deepEqual(window.size, [1060, 720]);
  assert.equal(window.alwaysOnTop, false);
  assert.equal(window.ignoreMouseEvents, false);
});
`````

### `desktop/tests/profile-stop.test.mjs`

`````javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const appSource = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const htmlSource = await readFile(new URL('../app.html', import.meta.url), 'utf8');

function appFunction(name) {
  let start = appSource.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} exists`);
  if (appSource.slice(start - 6, start) === 'async ') start -= 6;
  const open = appSource.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < appSource.length; i += 1) {
    if (appSource[i] === '{') depth += 1;
    else if (appSource[i] === '}' && --depth === 0) return appSource.slice(start, i + 1);
  }
  throw new Error(`could not read ${name}`);
}

function profileStopHarness(fetchImpl) {
  const requests = [];
  const statuses = [];
  let now = 0;
  const context = {
    API: {headers: () => ({'Content-Type': 'application/json', 'X-Companion-CSRF': 'csrf-test'})},
    fetch: async (url, options) => {
      requests.push({url, options});
      return fetchImpl(url, options);
    },
    Date: {now: () => now},
    setTimeout: (resolve, delay) => { now += delay; resolve(); return 1; },
    setConn: (kind, text, options = {}) => statuses.push({kind, text, options}),
    window: {jawlDesktop: {acknowledgeProfileStop() { context.acknowledgements += 1; }}},
    acknowledgements: 0,
  };
  let start = appSource.indexOf('async function requestManagedProfileStop(');
  const open = appSource.indexOf('{', start);
  let depth = 0;
  let end = -1;
  for (let i = open; i < appSource.length; i += 1) {
    if (appSource[i] === '{') depth += 1;
    else if (appSource[i] === '}' && --depth === 0) { end = i + 1; break; }
  }
  assert.ok(start >= 0 && end > start, 'managed stop function exists');
  vm.runInNewContext(`let managedProfileStopPending = false;\n${appSource.slice(start, end)}\nglobalThis.invoke = requestManagedProfileStop;`, context);
  return {context, requests, statuses};
}

const jsonResponse = (status, body) => ({status, ok: status >= 200 && status < 300, json: async () => body});

test('renderer keeps UI open until exact launcher acknowledgement and sends CSRF on status GET', async () => {
  const harness = profileStopHarness(async (url) => {
    if (url === '/api/profile/stop') return jsonResponse(202, {ok: true, status: 'stop_requested', request_id: 'request-1'});
    if (harness.requests.filter(request => request.url.endsWith('/status')).length === 1) {
      return jsonResponse(200, {ok: true, status: 'stopping', request_id: 'other-request'});
    }
    return jsonResponse(200, {ok: true, status: 'stopping', request_id: 'request-1'});
  });
  await harness.context.invoke();

  const polls = harness.requests.filter(request => request.url === '/api/profile/stop/status');
  assert.equal(polls.length, 2);
  assert.equal(polls[0].options.headers['X-Companion-CSRF'], 'csrf-test');
  assert.equal(polls[0].options.credentials, 'include');
  assert.equal(harness.context.acknowledgements, 1);
  assert.equal(harness.statuses[0].options.announce, true);
  assert.match(harness.statuses.at(-1).text, /\u0441\u043b\u0443\u0436\u0431\u044b/);
});

test('renderer does not close the app when launcher acknowledgement times out', async () => {
  const harness = profileStopHarness(async (url) => url === '/api/profile/stop'
    ? jsonResponse(202, {ok: true, status: 'stop_requested', request_id: 'request-2'})
    : jsonResponse(403, {error: 'CSRF required'}));
  await harness.context.invoke();

  assert.equal(harness.requests.filter(request => request.url.endsWith('/status')).length, 80);
  assert.equal(harness.context.acknowledgements, 0);
  assert.equal(harness.statuses.at(-1).kind, 'err');
  assert.equal(harness.statuses.at(-1).options.announce, true);
  assert.match(harness.statuses.at(-1).text, /\u043c\u043e\u0436\u0435\u0442 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0442\u044c/);
});

test('connection errors stay visible in compact HUD and are announced', () => {
  assert.match(htmlSource, /id="connection-feedback" role="status" aria-live="assertive"/);
  assert.match(htmlSource, /#connection-feedback\[hidden\] \{ display: none; \}/);
  const dot = {className: ''};
  const label = {textContent: ''};
  const feedback = {textContent: '', hidden: true, dataset: {}, classes: new Set(), classList: {toggle(name, on) {
    if (on) feedback.classes.add(name);
    else feedback.classes.delete(name);
  }}};
  const context = {document: {querySelector(selector) {
    return selector === '#conn-dot' ? dot : selector === '#conn-status' ? label : feedback;
  }}};
  vm.runInNewContext(appFunction('setConn'), context);
  context.setConn('err', 'temporary connection error');
  assert.equal(feedback.hidden, false);
  assert.equal(feedback.textContent, 'temporary connection error');
  assert.equal(feedback.classes.has('error'), true);
  context.setConn('ok', 'connected');
  assert.equal(feedback.hidden, true);
  context.setConn('err', 'stop failed', {announce: true});
  context.setConn('ok', 'background refresh');
  assert.equal(feedback.hidden, false);
  assert.equal(feedback.textContent, 'stop failed');
});
`````

### `desktop/tests/runtime-config.test.js`

`````javascript
const assert = require('node:assert/strict');
const test = require('node:test');
const { controlPort } = require('../runtime-config');

function files(base = { ports: { control: 2367, presentation: 8766 } }, local) {
  function value(name) {
    if (name.endsWith('.local.json')) {
      if (local === undefined) throw Object.assign(new Error(), { code: 'ENOENT' });
      return local;
    }
    return base;
  }
  return {
    statSync(name) { value(name); return { size: 100 }; },
    readFileSync(name) { const data = value(name); return typeof data === 'string' ? data : JSON.stringify(data); },
  };
}

test('desktop uses canonical and optional partial local manifest from repo root', () => {
  assert.equal(controlPort('/different-cwd/repo', {}, files()), 2367);
  assert.equal(controlPort('/repo', {}, files(undefined, { ports: { control: 3333 } })), 3333);
  assert.equal(controlPort('/repo', {}, files(undefined, { brain: { model: 'other' } })), 2367);
});

test('explicit desktop environment override wins without reading models', () => {
  assert.equal(controlPort('/repo', { JAWL_DESKTOP_CONTROL_PORT: '3456' }, {}), 3456);
  for (const value of ['0', '8765', '65536', '-2', '1.5', '', ' 2367', '2e3']) {
    assert.throws(() => controlPort('/repo', { JAWL_DESKTOP_CONTROL_PORT: value }, {}), /Invalid/);
  }
});

test('bad local ports and collisions fail instead of silently connecting elsewhere', () => {
  for (const value of [true, null, '3333', 0, 8765, 65536, 8766]) {
    assert.throws(() => controlPort('/repo', {}, files(undefined, { ports: { control: value } })));
  }
  assert.throws(() => controlPort('/repo', {}, files(undefined, { ports: { reserved: [2367] } })), /Reserved/);
});

test('invalid/missing/oversized manifest errors are redacted', () => {
  for (const local of ['{invalid-sensitive-content', { ports: null }, [], null]) {
    assert.throws(() => controlPort('/repo', {}, files(undefined, local)), /^Error: Cannot read Companion runtime manifest$/);
  }
  assert.throws(() => controlPort('/repo', {}, { statSync() { throw new Error('private filename'); } }), /Cannot read/);
  assert.throws(() => controlPort('/repo', {}, { statSync() { return { size: 128 * 1024 + 1 }; } }), /Cannot read/);
});
`````

### `desktop/tests/sensory-health.test.mjs`

`````javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../app.js', import.meta.url), 'utf8');

function createRenderer() {
  const elements = new Map();
  const document = {
    querySelector(selector) {
      const id = selector.slice(1);
      if (!elements.has(id)) elements.set(id, {textContent: '', dataset: {}, title: ''});
      return elements.get(id);
    },
  };
  const context = {document, state: {micActive: false}};
  const start = source.indexOf('function renderSensoryHealth(');
  const end = source.indexOf('\nasync function refreshJournal()', start);
  assert.ok(start >= 0 && end > start, 'renderSensoryHealth exists in app.js');
  vm.runInNewContext(`${source.slice(start, end)}\nglobalThis.render = renderSensoryHealth;`, context);
  return {render: context.render, elements};
}

test('sensor HUD reports active sources, freshness, and DND without calling DND an error', () => {
  const {render, elements} = createRenderer();
  render({
    ok: true,
    capture: {microphone_owner: 'desktop', loopback_configured: true, loopback_enabled: true, loopback_running: true, loopback_device: 'DigitalOutput (2- NVIDIA High Definition Audio) [Loopback]', loopback_device_index: 38, loopback_host_api_index: 2, loopback_sample_rate: 48000, loopback_channels: 2, loopback_last_chunk_age_ms: 400, loopback_signal_window_state: 'nonzero_pcm_unclassified', soundscape_configured: true, soundscape_count: 4, soundscape_errors: 0, soundscape_latency_ms_p95: 31, soundscape_last_kind: 'music', soundscape_last_tags: ['Saxophone'], soundscape_last_age_ms: 1400, soundscape_last_fresh: true},
    visual: {running: true, latest_age_ms: 2300, caption_fresh: true, caption_age_ms: 1700, capture_errors: 4, error_active: false},
    screen: {running: false},
    attention: {dnd: true, quiet_hours_active: false},
  });
  assert.equal(elements.get('sensor-mic').textContent, 'включён');
  assert.equal(elements.get('sensor-screen').textContent, 'описание актуально, 2 с');
  assert.equal(elements.get('sensor-loopback').textContent, 'PCM \u043f\u043e\u0441\u0442\u0443\u043f\u0430\u0435\u0442, \u0437\u0432\u0443\u043a \u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d');
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'YAMNet CPU: Музыка обнаружена · повторяющийся тег: Saxophone · 1 с назад · 4 сегм. · p95 31 ms');
  assert.equal(elements.get('sensor-soundscape-status').dataset.state, 'ok');
  assert.equal(elements.get('sensor-attention').textContent, 'не беспокоить');
  assert.equal(elements.get('sensor-attention').dataset.state, 'off');
  assert.equal(elements.get('sensory-health').dataset.state, 'warn');
  assert.notEqual(elements.get('sensory-health-compact').textContent, '');
  assert.equal(elements.get('sensory-health-compact').textContent.includes('1'), true);
  assert.equal(elements.get('sensory-health-compact').title.includes('Saxophone'), true);
  assert.equal(elements.get('sensory-health-compact').dataset.state, 'warn');
  assert.equal(elements.get('sensory-health-compact').title, elements.get('sensory-health').title);
});

test('sensor HUD marks stale perception and unavailable status honestly', () => {
  const {render, elements} = createRenderer();
  render({
    ok: true,
    capture: {loopback_configured: false},
    visual: {running: true, latest_age_ms: 9000, caption_fresh: false, caption_age_ms: 9000, capture_errors: 0},
    screen: {running: false},
    attention: {},
  });
  assert.equal(elements.get('sensor-screen').textContent, 'описание устарело, 9 с');
  assert.equal(elements.get('sensory-health').dataset.state, 'warn');
  assert.equal(elements.get('sensory-health-compact').dataset.state, 'warn');

  render({ok: false});
  assert.equal(elements.get('sensory-health').textContent, 'Статус сенсоров недоступен');
  assert.equal(elements.get('sensor-mic').dataset.state, 'error');
  assert.equal(elements.get('sensor-loopback-device').textContent, '\u0421\u0442\u0430\u0442\u0443\u0441 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0430 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d');
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'Статус музыкального анализатора недоступен');
  assert.equal(elements.get('sensory-health-compact').dataset.state, 'error');
  assert.notEqual(elements.get('sensory-health-compact').textContent, '');
});

test('screen watcher without a caption sensor is shown as active, not stale', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {}, visual: {running: false}, screen: {running: true}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'наблюдатель активен');
  assert.equal(elements.get('sensor-screen').dataset.state, 'ok');
  assert.equal(elements.get('sensory-health').dataset.state, 'ok');
});

test('soundscape freshness abstains clearly and pause suppresses a previous music claim', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true, soundscape_configured: true,
    soundscape_count: 8, soundscape_errors: 0, soundscape_last_kind: 'unknown',
    soundscape_last_tags: [], soundscape_last_age_ms: 1200, soundscape_last_fresh: true,
  }, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'YAMNet CPU: Свежая проверка: музыка не подтверждена · 1 с назад · 8 сегм.');
  assert.equal(elements.get('sensor-soundscape-status').dataset.state, 'off');

  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true, loopback_paused: true,
    soundscape_configured: true, soundscape_count: 8, soundscape_errors: 0,
    soundscape_last_kind: 'music', soundscape_last_tags: ['Saxophone'],
    soundscape_last_age_ms: 1400, soundscape_last_fresh: true,
  }, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'YAMNet CPU: Анализ системного звука приостановлен · 8 сегм.');
  assert.equal(elements.get('sensor-soundscape-status').dataset.state, 'off');

  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true, soundscape_configured: true,
    soundscape_count: 8, soundscape_errors: 0, soundscape_last_kind: 'music',
    soundscape_last_tags: ['Saxophone'], soundscape_last_age_ms: 35000,
    soundscape_last_fresh: false,
  }, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'YAMNet CPU: Нет свежей оценки музыки · последняя 35 с назад · 8 сегм.');
  assert.equal(elements.get('sensor-soundscape-status').dataset.state, 'warn');
});

test('screen capture age does not hide an expired semantic caption', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {}, visual: {running: true, latest_age_ms: 200, caption_fresh: false, caption_age_ms: 9000}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'описание устарело, 9 с');
  assert.equal(elements.get('sensor-screen').dataset.state, 'warn');
});

test('screen HUD distinguishes model caption age from same-scene confirmation age', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {}, visual: {
    running: true, latest_age_ms: 100, caption_fresh: true,
    caption_age_ms: 9000, caption_confirmed_age_ms: 1200,
  }, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'описание подтверждено, 1 с · модель 9 с');
});

test('running loopback without fresh chunks is waiting or stale, not hearing audio', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {loopback_configured: true, loopback_running: true}, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-loopback').textContent, '\u043f\u043e\u0442\u043e\u043a \u0437\u0430\u043f\u0443\u0449\u0435\u043d, \u0436\u0434\u0451\u0442 \u0434\u0430\u043d\u043d\u044b\u0435');
  assert.equal(elements.get('sensor-loopback').dataset.state, 'warn');
  assert.equal(elements.get('sensory-health').dataset.state, 'warn');
  render({ok: true, capture: {loopback_configured: true, loopback_running: true, loopback_last_chunk_age_ms: 7000}, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-loopback').textContent, 'нет новых чанков, 7 с');
  assert.equal(elements.get('sensor-loopback').dataset.state, 'warn');
});

test('fresh loopback callbacks with a full digital-zero window do not claim sound is received', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {
    loopback_configured: true, loopback_enabled: true, loopback_running: true,
    loopback_last_chunk_age_ms: 200, loopback_signal_window_state: 'digital_silence',
    loopback_signal_window_duration_ms: 1000, loopback_signal_window_rms: 0,
  }, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-loopback').textContent, '\u0437\u0430\u0445\u0432\u0430\u0442 \u0430\u043a\u0442\u0438\u0432\u0435\u043d: \u0446\u0438\u0444\u0440\u043e\u0432\u044b\u0435 \u043d\u0443\u043b\u0438');
  assert.equal(elements.get('sensor-loopback').dataset.state, 'warn');
  assert.equal(elements.get('sensory-health-compact').textContent.includes('\u0431\u0435\u0437 \u0441\u0438\u0433\u043d\u0430\u043b\u0430'), true);
});

test('screen capture error clears when the sensor reports recovery', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {}, visual: {running: true, error_active: true}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'ошибка захвата');
  assert.equal(elements.get('sensory-health').dataset.state, 'error');

  render({ok: true, capture: {}, visual: {running: true, latest_age_ms: 400, caption_fresh: true, caption_age_ms: 300, error_active: false}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'описание актуально, 0 с');
  assert.equal(elements.get('sensory-health').dataset.state, 'ok');
});

test('Qwen Omni audio status reports fresh processed media and latency without trusting model confidence', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true,
    audio_description_configured: true, audio_description_provider: 'qwen3-omni',
    audio_description_count: 3, audio_description_errors: 1, audio_description_skipped: 0,
    audio_description_latency_ms_p95: 940, audio_description_last_kind: 'music',
    audio_description_last_age_ms: 2500, audio_description_last_fresh: true,
  }, visual: {}, screen: {}, attention: {}});
  const status = elements.get('sensor-audio-description-status');
  assert.match(status.textContent, /Qwen3-Omni/);
  assert.match(status.textContent, /\u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442: \u043c\u0443\u0437\u044b\u043a\u0430/);
  assert.match(status.textContent, /3 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0439/);
  assert.match(status.textContent, /p95 940 ms/);
  assert.match(status.textContent, /\u043e\u0448\u0438\u0431\u043e\u043a 1/);
  // A fresh successful result demonstrates recovery after a previous error.
  assert.equal(status.dataset.state, 'ok');
});

test('Qwen Omni audio status distinguishes stale results and provider errors', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true,
    audio_description_configured: true, audio_description_provider: 'qwen3-omni',
    audio_description_count: 2, audio_description_errors: 1,
    audio_description_latency_ms_p95: 1100, audio_description_last_kind: 'unknown',
    audio_description_last_age_ms: 35000, audio_description_last_fresh: false,
  }, visual: {}, screen: {}, attention: {}});
  const status = elements.get('sensor-audio-description-status');
  assert.match(status.textContent, /\u043d\u0435\u0442 \u0441\u0432\u0435\u0436\u0435\u0433\u043e \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430/);
  assert.match(status.textContent, /\u043e\u0448\u0438\u0431\u043e\u043a 1/);
  assert.equal(status.dataset.state, 'warn');
});
`````

### `desktop/voice-draft.js`

`````javascript
const DEFAULT_TIMEOUT_MS = 4000;
const MAX_TIMEOUT_MS = 30_000;
const MAX_DRAFT_CHARS = 2000;
const NO_DISPATCH = Symbol('voice-draft-no-dispatch');

function readIdentity(snapshot) {
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) return null;
  const {session_id, correlation_id, capture_id, generation} = snapshot;
  if (typeof session_id !== 'string' || !session_id.trim()
      || typeof correlation_id !== 'string' || !correlation_id.trim()
      || typeof capture_id !== 'string' || !capture_id.trim()
      || !Number.isSafeInteger(generation) || generation < 0
      || snapshot.active === false || snapshot.heard === false || snapshot.finalizing === true) {
    return null;
  }
  return Object.freeze({session_id, correlation_id, capture_id, generation});
}

function sameIdentity(left, right) {
  return Boolean(left && right
    && left.session_id === right.session_id
    && left.correlation_id === right.correlation_id
    && left.capture_id === right.capture_id
    && left.generation === right.generation);
}

/**
 * Bounded poller for POST /api/voice/draft. request(payload, signal) is supplied
 * by the caller so it can provide its normal auth headers and credentials.
 * Snapshot shape: {session_id, correlation_id, capture_id, generation};
 * getCurrent returns null unless the mic is active, heard, and not finalizing.
 *
 * Integration sketch:
 *   const drafts = createVoiceDraftController({
 *     getCurrent: () => activeHeardUtteranceSnapshotOrNull(),
 *     request: (payload, signal) => postVoiceDraft(payload, signal),
 *     onDraft: (text, identity) => renderTransientDraft(text, identity),
 *   });
 *   // Call tick from the existing bounded poll timer; pause/finalize/reset/stop
 *   // with the mic lifecycle. Draft text is transient and is never persisted.
 */
export function createVoiceDraftController({
  request,
  getCurrent,
  onDraft = () => {},
  onDecision = () => {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
} = {}) {
  if (typeof request !== 'function' || typeof getCurrent !== 'function') {
    throw new TypeError('voice draft controller requires request and getCurrent functions');
  }
  if (typeof onDraft !== 'function' || typeof onDecision !== 'function'
      || typeof setTimer !== 'function' || typeof clearTimer !== 'function') {
    throw new TypeError('invalid voice draft callback or timer functions');
  }
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > MAX_TIMEOUT_MS) {
    throw new RangeError(`timeoutMs must be a finite number between 1 and ${MAX_TIMEOUT_MS}`);
  }
  const deadlineMs = timeoutMs;

  let paused = false;
  let stopped = false;
  let epoch = 0;
  let lastIdentity = null;
  let renderedText = '';
  let inflight = null;

  function clearDraft() {
    if (!renderedText) return;
    const identity = lastIdentity;
    renderedText = '';
    try { onDraft('', identity); } catch { /* presentation failure must not stop capture */ }
  }

  function invalidate() {
    epoch += 1;
    clearDraft();
    if (inflight && !inflight.controller.signal.aborted) {
      try { inflight.controller.abort(); } catch { /* abort is best effort */ }
    }
  }

  function currentIdentity() {
    let snapshot;
    try { snapshot = getCurrent(); } catch { return null; }
    return readIdentity(snapshot);
  }

  function isEligible(attempt) {
    return !paused && !stopped && !attempt.timedOut
      && inflight === attempt && epoch === attempt.epoch
      && sameIdentity(attempt.identity, currentIdentity());
  }

  function settleAttempt(attempt) {
    if (attempt.timer !== null) {
      try { clearTimer(attempt.timer); } catch { /* timer cleanup is best effort */ }
      attempt.timer = null;
    }
    attempt.settled = true;
    if (inflight === attempt) inflight = null;
  }

  async function tick() {
    if (stopped || paused) return {status: stopped ? 'stopped' : 'paused'};

    const identity = currentIdentity();
    if (!identity) {
      if (lastIdentity || renderedText || inflight) invalidate();
      lastIdentity = null;
      return {status: 'inactive'};
    }
    if (!sameIdentity(identity, lastIdentity)) {
      invalidate();
      lastIdentity = identity;
    }
    if (inflight) return {status: 'busy'};

    const controller = new AbortController();
    const attempt = {controller, identity, epoch, timer: null, settled: false, timedOut: false};
    inflight = attempt;
    let resolveOutcome;
    const outcome = new Promise(resolve => { resolveOutcome = resolve; });
    const complete = result => {
      settleAttempt(attempt);
      resolveOutcome(result);
    };

    attempt.timer = setTimer(() => {
      if (attempt.settled || attempt.timedOut) return;
      attempt.timedOut = true;
      clearDraft();
      try { controller.abort(); } catch { /* timeout still fences the result */ }
      resolveOutcome({status: 'timeout'});
    }, deadlineMs);

    // The slot is released only by this request's actual settlement. An
    // endpoint that ignores AbortSignal therefore cannot spawn overlapping polls.
    Promise.resolve()
      .then(() => {
        // Lifecycle methods can run synchronously before this microtask. Fence
        // there as well as after the response so cancellation prevents dispatch.
        if (!isEligible(attempt) || controller.signal.aborted) {
          complete({status: 'stale'});
          return NO_DISPATCH;
        }
        return request({
          session_id: identity.session_id,
          correlation_id: identity.correlation_id,
          owner: 'desktop',
          capture_id: identity.capture_id,
        }, controller.signal);
      })
      .then(response => {
        if (response === NO_DISPATCH) return;
        if (!isEligible(attempt)) {
          clearDraft();
          if (attempt.timedOut) return;
          complete({status: 'stale'});
          return;
        }
        if (!response || response.ok !== true || response.status === 'cancelled'
            || response.mode === 'unavailable' || response.mode !== 'streaming'
            || typeof response.draft !== 'string') {
          clearDraft();
          complete({status: response?.status === 'cancelled' ? 'cancelled' : 'unavailable'});
          return;
        }
        const text = response.draft.slice(0, MAX_DRAFT_CHARS);
        try { onDecision(response, identity); } catch { /* decision failure is isolated */ }
        if (text !== renderedText) {
          renderedText = text;
          try { onDraft(text, identity); } catch { /* presentation failure is isolated */ }
        }
        complete({status: 'updated', draft: text});
      })
      .catch(() => {
        if (isEligible(attempt)) clearDraft();
        complete({status: isEligible(attempt) ? 'error' : 'stale'});
      })
      .finally(() => settleAttempt(attempt));

    return outcome;
  }

  function pause() {
    paused = true;
    invalidate();
  }

  function resume() {
    if (!stopped) paused = false;
  }

  function finalize() {
    paused = true;
    invalidate();
  }

  function reset() {
    invalidate();
    lastIdentity = null;
  }

  function stop() {
    stopped = true;
    paused = true;
    invalidate();
    lastIdentity = null;
  }

  return Object.freeze({tick, pause, resume, finalize, reset, stop, invalidate});
}

export {DEFAULT_TIMEOUT_MS as VOICE_DRAFT_TIMEOUT_MS, MAX_DRAFT_CHARS as VOICE_DRAFT_MAX_CHARS};
`````

### `desktop/voice-draft.test.mjs`

`````javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {createVoiceDraftController, VOICE_DRAFT_MAX_CHARS} from './voice-draft.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

function timers() {
  let next = 1;
  const pending = new Map();
  return {
    pending,
    setTimer(callback, delay) {
      const id = next++;
      pending.set(id, {callback, delay});
      return id;
    },
    clearTimer(id) { pending.delete(id); },
    fire(id) {
      const timer = pending.get(id);
      assert.ok(timer, `timer ${id} should be pending`);
      pending.delete(id);
      timer.callback();
    },
  };
}

function snapshot(overrides = {}) {
  return {
    session_id: 'session-1',
    correlation_id: 'utterance-1',
    capture_id: 'capture-1',
    generation: 1,
    active: true,
    heard: true,
    finalizing: false,
    ...overrides,
  };
}

function successful(draft) { return {ok: true, draft, mode: 'streaming'}; }

test('success sends the scoped desktop payload, truncates and deduplicates rendering', async () => {
  const renders = [];
  const calls = [];
  const time = timers();
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: (payload, signal) => {
      calls.push({payload, signal});
      return Promise.resolve(successful('я'.repeat(VOICE_DRAFT_MAX_CHARS + 10)));
    },
    onDraft: (text, identity) => renders.push({text, identity}),
    setTimer: time.setTimer,
    clearTimer: time.clearTimer,
  });

  assert.equal((await controller.tick()).status, 'updated');
  assert.equal((await controller.tick()).status, 'updated');
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0].payload, {
    session_id: 'session-1', correlation_id: 'utterance-1', owner: 'desktop', capture_id: 'capture-1',
  });
  assert.equal(renders.length, 1);
  assert.equal(renders[0].text.length, VOICE_DRAFT_MAX_CHARS);
  assert.deepEqual(renders[0].identity, {
    session_id: 'session-1', correlation_id: 'utterance-1', capture_id: 'capture-1', generation: 1,
  });
  assert.equal(time.pending.size, 0);
});

test('pending request blocks overlap even when later ticks run', async () => {
  const gate = deferred();
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: () => { calls += 1; return gate.promise; },
  });
  const first = controller.tick();
  await Promise.resolve();
  assert.equal((await controller.tick()).status, 'busy');
  assert.equal(calls, 1);
  gate.resolve(successful('часть фразы'));
  assert.equal((await first).status, 'updated');
});

test('generation, session, or capture changes abort and drop stale output', async t => {
  for (const change of [
    {generation: 2}, {session_id: 'session-2'}, {capture_id: 'capture-2'},
  ]) {
    await t.test(JSON.stringify(change), async () => {
      const gate = deferred();
      const renders = [];
      let current = snapshot();
      let signal;
      const controller = createVoiceDraftController({
        getCurrent: () => current,
        request: (_payload, requestSignal) => { signal = requestSignal; return gate.promise; },
        onDraft: text => renders.push(text),
      });
      const first = controller.tick();
      await Promise.resolve();
      current = snapshot(change);
      assert.equal((await controller.tick()).status, 'busy');
      assert.equal(signal.aborted, true);
      gate.resolve(successful('устаревший текст'));
      assert.equal((await first).status, 'stale');
      assert.deepEqual(renders, []);
      assert.equal((await controller.tick()).status, 'updated');
      assert.equal(renders.at(-1), 'устаревший текст');
    });
  }
});

test('stop clears the visible draft and fences a request that ignores abort', async () => {
  const firstGate = deferred();
  const renders = [];
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: () => (++calls === 1 ? Promise.resolve(successful('visible')) : firstGate.promise),
    onDraft: text => renders.push(text),
  });
  await controller.tick();
  const late = controller.tick();
  await Promise.resolve();
  controller.stop();
  assert.deepEqual(renders, ['visible', '']);
  firstGate.resolve(successful('late'));
  assert.equal((await late).status, 'stale');
  assert.deepEqual(renders, ['visible', '']);
  assert.equal((await controller.tick()).status, 'stopped');
});

test('synchronous stop before the dispatch microtask prevents the request', async () => {
  const time = timers();
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: () => { calls += 1; return Promise.resolve(successful('must not dispatch')); },
    setTimer: time.setTimer,
    clearTimer: time.clearTimer,
  });
  const pending = controller.tick();
  controller.stop();
  assert.equal((await pending).status, 'stale');
  assert.equal(calls, 0);
  assert.equal(time.pending.size, 0);
});

test('pause and finalize clear draft and abort their own pending request', async t => {
  for (const method of ['pause', 'finalize']) {
    await t.test(method, async () => {
      const gate = deferred();
      const renders = [];
      let signal;
      const controller = createVoiceDraftController({
        getCurrent: () => snapshot(),
        request: (_payload, requestSignal) => { signal = requestSignal; return gate.promise; },
        onDraft: text => renders.push(text),
      });
      const pending = controller.tick();
      await Promise.resolve();
      controller[method]();
      assert.equal(signal.aborted, true);
      assert.equal((await controller.tick()).status, 'paused');
      gate.resolve(successful('late'));
      assert.equal((await pending).status, 'stale');
      assert.deepEqual(renders, []);
    });
  }
});

test('unavailable response and request errors clear the draft without throwing', async () => {
  const renders = [];
  let next = successful('visible');
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: () => {
      if (next instanceof Error) return Promise.reject(next);
      return Promise.resolve(next);
    },
    onDraft: text => renders.push(text),
  });
  assert.equal((await controller.tick()).status, 'updated');
  next = {ok: true, mode: 'unavailable', draft: ''};
  assert.equal((await controller.tick()).status, 'unavailable');
  assert.deepEqual(renders, ['visible', '']);
  next = new Error('network down');
  assert.equal((await controller.tick()).status, 'error');
  assert.deepEqual(renders, ['visible', '']);
});

test('reset clears and aborts immediately but allows the next request only after settlement', async () => {
  const oldGate = deferred();
  const renders = [];
  let calls = 0;
  let oldSignal;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: (_payload, signal) => {
      calls += 1;
      if (calls === 1) { oldSignal = signal; return oldGate.promise; }
      return Promise.resolve(successful('new'));
    },
    onDraft: text => renders.push(text),
  });
  const old = controller.tick();
  await Promise.resolve();
  controller.reset();
  assert.equal(oldSignal.aborted, true);
  assert.equal((await controller.tick()).status, 'busy');
  assert.equal(calls, 1);
  oldGate.resolve(successful('old'));
  assert.equal((await old).status, 'stale');
  assert.equal((await controller.tick()).status, 'updated');
  assert.deepEqual(renders, ['new']);
});

test('timeout aborts, drops late output and cleans its timer without releasing a stuck slot', async () => {
  const gate = deferred();
  const time = timers();
  const renders = [];
  let signal;
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => snapshot(),
    request: (_payload, requestSignal) => { calls += 1; signal = requestSignal; return gate.promise; },
    onDraft: text => renders.push(text),
    timeoutMs: 1234,
    setTimer: time.setTimer,
    clearTimer: time.clearTimer,
  });
  const pending = controller.tick();
  await Promise.resolve();
  const [timerId] = time.pending.keys();
  assert.equal(time.pending.get(timerId).delay, 1234);
  time.fire(timerId);
  assert.equal((await pending).status, 'timeout');
  assert.equal(signal.aborted, true);
  assert.equal(time.pending.size, 0);
  assert.equal((await controller.tick()).status, 'busy');
  assert.equal(calls, 1);
  gate.resolve(successful('late'));
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(renders, []);
  assert.equal(time.pending.size, 0);
});

test('invalid or inactive identity does not issue a request and clears prior draft', async () => {
  const renders = [];
  let current = snapshot();
  let calls = 0;
  const controller = createVoiceDraftController({
    getCurrent: () => current,
    request: () => { calls += 1; return Promise.resolve(successful('draft')); },
    onDraft: text => renders.push(text),
  });
  assert.equal((await controller.tick()).status, 'updated');
  for (const invalid of [
    null, snapshot({session_id: ''}), snapshot({correlation_id: null}),
    snapshot({capture_id: undefined}), snapshot({generation: NaN}),
    snapshot({heard: false}), snapshot({active: false}), snapshot({finalizing: true}),
  ]) {
    current = invalid;
    assert.equal((await controller.tick()).status, 'inactive');
  }
  assert.equal(calls, 1);
  assert.deepEqual(renders, ['draft', '']);
});

test('timeoutMs must be finite, positive and no greater than 30 seconds', () => {
  const options = {request: () => Promise.resolve(successful('x')), getCurrent: () => snapshot()};
  for (const timeoutMs of [0, -1, NaN, Infinity, 30_001]) {
    assert.throws(() => createVoiceDraftController({...options, timeoutMs}), RangeError);
  }
  assert.doesNotThrow(() => createVoiceDraftController({...options, timeoutMs: 30_000}));
});
`````

### `desktop/voice-input.js`

`````javascript
const DEFAULT_MIC_CONFIG = Object.freeze({
  openRms: 0.02,
  closeRms: 0.012,
  silenceMs: 1200,
  preRollMs: 120,
  minSpeechMs: 60,
  releaseMs: 120,
});

function boundedNumber(value, fallback, min, max) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback;
}

export function normalizeMicConfig(input = {}) {
  const openRms = boundedNumber(input.openRms ?? input.gate_open, DEFAULT_MIC_CONFIG.openRms, 0.001, 0.25);
  const closeRms = boundedNumber(input.closeRms ?? input.gate_close, DEFAULT_MIC_CONFIG.closeRms, 0.0005, openRms * 0.95);
  return Object.freeze({
    openRms,
    closeRms,
    silenceMs: boundedNumber(input.silenceMs ?? input.silence_ms, DEFAULT_MIC_CONFIG.silenceMs, 300, 5000),
    preRollMs: boundedNumber(input.preRollMs ?? input.pre_roll_ms, DEFAULT_MIC_CONFIG.preRollMs, 0, 500),
    minSpeechMs: boundedNumber(input.minSpeechMs, DEFAULT_MIC_CONFIG.minSpeechMs, 20, 240),
    releaseMs: boundedNumber(input.releaseMs, DEFAULT_MIC_CONFIG.releaseMs, 40, 400),
  });
}

// A bounded, deterministic turn heuristic. This is not a learned duplex
// model: ASR drafts may be absent, so sustained voiced audio remains a fallback.
export function decideMicTurn({text = '', overlap = false, voicedMs = 0,
  silenceMs = 0, normalSilenceMs = DEFAULT_MIC_CONFIG.silenceMs} = {}) {
  const raw = String(text).trim().toLowerCase().replaceAll('ё', 'е');
  const words = raw.match(/[а-яa-z0-9]+(?:-[а-яa-z0-9]+)*/gu) || [];
  const joined = words.join(' ');
  const acknowledgements = new Set(['угу', 'ага', 'да', 'ясно', 'понял', 'понятно', 'окей', 'ок',
    'хорошо', 'круто', 'ого', 'вау', 'классно', 'точно', 'верно', 'ладно', 'мгм', 'хм',
    'ах', 'ох', 'ха', 'хех', 'прикольно', 'ништяк', 'супер']);
  const question = /[?？]$/.test(raw);
  const backchannel = words.length > 0 && words.length <= 2 && !question &&
    (joined === 'ну да' || words.every(word => acknowledgements.has(word)));
  const interrupt = words.some(word => ['стоп', 'стой', 'подожди', 'погоди', 'хватит',
    'тихо', 'замолчи', 'остановись', 'перестань', 'слушай', 'послушай', 'нет', 'лучше', 'давай'].includes(word));
  const thinking = /^(э+|а+|м+|э-э(?:-э)?|а-а(?:-а)?|м-м|ну|вот|типа|короче|и|или|но|что|чтобы|потому|если|когда|который|которая|которые|как|где|в|на|с|для|хотел|хочу|давай)$/.test(words.at(-1) || '')
    || /(?:как бы|то есть|потому что|я хотел|я хочу)$/.test(joined)
    || /(?:\.\.\.|…|,|[-—])$/.test(raw);
  const requiredMs = thinking ? Math.max(normalSilenceMs, 2200)
    : backchannel ? Math.min(normalSilenceMs, 380)
    : question ? Math.min(normalSilenceMs, 380) : normalSilenceMs;
  if (overlap && !backchannel && (question || interrupt || words.length >= 2 || voicedMs >= 550)) {
    return {action: 'cancel_tts', requiredMs};
  }
  if (silenceMs >= requiredMs) {
    return {action: overlap && backchannel ? 'finish_backchannel' : 'commit_turn', requiredMs};
  }
  return {action: 'hold_turn', requiredMs};
}

export function uploadUtteranceFor(mic) {
  return mic.flushDestination || mic.utterance;
}

export function completeMicFlushBoundary(mic, lastVoiceAt, nextUtterance) {
  mic.flushDestination = null;
  if (mic.inputGate.lastVoiceAt > lastVoiceAt) return {resumed: true, utterance: null};
  const utterance = mic.utterance;
  mic.utterance = nextUtterance;
  mic.heard = false;
  return {resumed: false, utterance};
}

export function detachMicState(state, mic) {
  if (state.mic !== mic) return false;
  if (mic) mic.active = false;
  state.mic = null;
  state.micActive = false;
  return true;
}

export function invalidatePendingCapture({lease, pendingLease, captureGeneration, currentGeneration, invalidate}) {
  if (lease !== pendingLease || captureGeneration !== currentGeneration) return false;
  invalidate();
  return true;
}

export function requireVoiceResponseOk(response, operation) {
  if (response.ok) return response;
  const error = new Error(`${operation} failed (HTTP ${response.status})`);
  error.code = 'VOICE_CAPTURE_HTTP_ERROR';
  error.status = response.status;
  throw error;
}

function frameRms(samples) {
  let energy = 0;
  for (let i = 0; i < samples.length; i += 1) energy += samples[i] * samples[i];
  return samples.length ? Math.sqrt(energy / samples.length) : 0;
}

// Bounded gate for one live microphone stream. Closed-gate audio is kept only
// in a short rolling pre-roll and is returned only after qualified speech.
export class MicInputGate {
  constructor(config = {}) {
    this.config = normalizeMicConfig(config);
    this.preRoll = [];
    this.preRollDurationMs = 0;
    this.onsetDurationMs = 0;
    this.releaseDurationMs = 0;
    this.open = false;
    this.lastVoiceAt = 0;
    this.lastRms = 0;
    this.peakRms = 0;
  }

  push(samples, sampleRate, nowMs = performance.now()) {
    const frame = samples instanceof Float32Array ? samples.slice() : new Float32Array(samples);
    const durationMs = sampleRate > 0 ? frame.length * 1000 / sampleRate : 0;
    const rms = frameRms(frame);
    this.lastRms = rms;
    this.peakRms = Math.max(this.peakRms, rms);

    if (!this.open) {
      this.preRoll.push({frame, durationMs});
      this.preRollDurationMs += durationMs;
      const onsetHistoryMs = this.config.preRollMs + this.config.minSpeechMs;
      while (this.preRoll.length > 1 && this.preRollDurationMs - this.preRoll[0].durationMs >= onsetHistoryMs) {
        this.preRollDurationMs -= this.preRoll.shift().durationMs;
      }
      if (rms >= this.config.openRms) this.onsetDurationMs += durationMs;
      else this.onsetDurationMs = 0;
      if (this.onsetDurationMs < this.config.minSpeechMs) {
        return {opened: false, closed: false, frames: [], rms, voiceActive: false};
      }
      this.open = true;
      this.lastVoiceAt = nowMs;
      this.releaseDurationMs = 0;
      const frames = this.preRoll.map(item => item.frame);
      this.preRoll = [];
      this.preRollDurationMs = 0;
      return {opened: true, closed: false, frames, rms, voiceActive: true};
    }

    if (rms >= this.config.closeRms) {
      this.lastVoiceAt = nowMs;
      this.releaseDurationMs = 0;
    } else {
      this.releaseDurationMs += durationMs;
    }
    if (this.releaseDurationMs >= this.config.releaseMs) {
      this.open = false;
      this.onsetDurationMs = 0;
      this.releaseDurationMs = 0;
      this.preRoll = [];
      this.preRollDurationMs = 0;
      return {opened: false, closed: true, frames: [frame], rms, voiceActive: false};
    }
    return {opened: false, closed: false, frames: [frame], rms, voiceActive: true};
  }

  reset() {
    this.preRoll = [];
    this.preRollDurationMs = 0;
    this.onsetDurationMs = 0;
    this.releaseDurationMs = 0;
    this.open = false;
    this.lastVoiceAt = 0;
    this.lastRms = 0;
    this.peakRms = 0;
  }
}

export class CaptureLease {
  constructor({captureId, fetchImpl = (...args) => globalThis.fetch(...args), headers = () => ({'Content-Type': 'application/json'}), onLost = () => {}}) {
    this.captureId = captureId;
    this.fetchImpl = fetchImpl;
    this.headers = headers;
    this.onLost = onLost;
    this.leaseId = null;
    this.config = normalizeMicConfig();
    this.renewTimer = null;
    this.renewing = false;
    this.released = false;
    this.acquirePromise = null;
    this.releasePromise = null;
  }

  async request(action) {
    const response = await this.fetchImpl('/api/voice/capture', {
      method: 'POST',
      credentials: 'include',
      headers: this.headers(),
      signal: AbortSignal.timeout(5000),
      body: JSON.stringify({
        action,
        owner: 'desktop',
        capture_id: this.captureId,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.ok === false) {
      throw new Error(data?.error || `voice capture ${action} failed (HTTP ${response.status})`);
    }
    return data;
  }

  async acquire() {
    // The caller already chose this unique capture_id, so even a lost HTTP
    // response can be followed by a safe best-effort release.
    this.leaseId = this.captureId;
    const acquirePromise = this.request('acquire');
    this.acquirePromise = acquirePromise;
    let data;
    try {
      data = await acquirePromise;
    } finally {
      if (this.acquirePromise === acquirePromise) this.acquirePromise = null;
    }
    if (data.owner !== 'desktop' || data.capture_id !== this.captureId) {
      throw new Error('voice capture lease response does not match this desktop client');
    }
    // Capture settings are a per-start snapshot. Renewal extends ownership
    // only; changes become effective on the next acquire.
    this.config = normalizeMicConfig(data);
    const ttl = boundedNumber(data.lease_ttl_ms, 15000, 3000, 120000);
    const interval = Math.min(60000, Math.max(1000, Math.floor(ttl / 3)));
    return {config: this.config, renewAfterMs: interval};
  }

  startRenewal(intervalMs) {
    this.stopRenewal();
    this.released = false;
    const interval = boundedNumber(intervalMs, 15000, 1000, 60000);
    this.renewTimer = setInterval(() => { void this.renew(); }, interval);
  }

  async renew() {
    if (this.renewing || this.released || !this.leaseId) return;
    this.renewing = true;
    try {
      const data = await this.request('renew');
      if (data.owner !== 'desktop' || data.capture_id !== this.captureId) {
        throw new Error('voice capture renewal response does not match this desktop client');
      }
    } catch (error) {
      this.stopRenewal();
      if (!this.released) this.onLost(error);
    } finally {
      this.renewing = false;
    }
  }

  stopRenewal() {
    if (this.renewTimer !== null) clearInterval(this.renewTimer);
    this.renewTimer = null;
  }

  async release() {
    this.stopRenewal();
    if (this.releasePromise) return this.releasePromise;
    if (this.released && !this.acquirePromise) return;
    this.released = true;
    this.releasePromise = (async () => {
      const acquirePromise = this.acquirePromise;
      if (acquirePromise) await acquirePromise.catch(() => {});
      if (!this.leaseId) return;
      try { await this.request('release'); } catch { /* server expiry remains bounded */ }
      this.leaseId = null;
    })();
    try { await this.releasePromise; }
    finally { this.releasePromise = null; }
  }
}

export {DEFAULT_MIC_CONFIG};
`````

### `desktop/voice-input.test.mjs`

`````javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {CaptureLease, MicInputGate, normalizeMicConfig, uploadUtteranceFor,
  completeMicFlushBoundary, detachMicState, invalidatePendingCapture,
  requireVoiceResponseOk, decideMicTurn} from './voice-input.js';

test('turn heuristic distinguishes Russian overlap, finished questions, and bounded hesitation', () => {
  assert.equal(decideMicTurn({text: 'Угу, понятно.', overlap: true, voicedMs: 300, silenceMs: 400}).action, 'finish_backchannel');
  assert.equal(decideMicTurn({text: 'Да.', overlap: true, voicedMs: 300, silenceMs: 400}).action, 'finish_backchannel');
  assert.equal(decideMicTurn({text: 'Да?', overlap: true, voicedMs: 300, silenceMs: 400}).action, 'cancel_tts');
  for (const text of ['Стой!', 'Нет, подожди', 'Открой браузер', 'Где ключи?']) {
    assert.equal(decideMicTurn({text, overlap: true}).action, 'cancel_tts');
  }
  assert.equal(decideMicTurn({text: 'И что теперь?', silenceMs: 400}).action, 'commit_turn');
  assert.equal(decideMicTurn({text: 'Я хотел сказать.', silenceMs: 400}).action, 'hold_turn');
  assert.equal(decideMicTurn({text: 'Я хотел сказать.', silenceMs: 1200}).action, 'commit_turn');
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

test('default capture lease keeps the browser fetch receiver intact', async () => {
  const original = globalThis.fetch;
  const receivers = [];
  globalThis.fetch = function (..._args) {
    receivers.push(this);
    return Promise.resolve(new Response(JSON.stringify({ok: true}), {status: 200}));
  };
  try {
    const lease = new CaptureLease({captureId: 'desk-default'});
    await lease.request('release');
    assert.equal(receivers.length, 1);
    assert.equal(receivers[0], globalThis);
  } finally {
    globalThis.fetch = original;
  }
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
`````

### `docs/UI_CONSOLIDATION_PLAN.md`

`````markdown
# UI-консолидация: монолит вместо двух интерфейсов (2026-10-30)

> Мандат владельца: «бесит, что есть 2 интерфейса — 2367 и 8766; хочется
> монолита и простоты; всё в одном месте; детальные настройки, но не
> вырвиглазно и не объёмно; просто и лаконично». Сопроводительное условие:
> **«мы не скатимся опять в наращивание слоев»**. Этот документ фиксирует
> правила (ADR-052) и пошаговый план, чтобы снятие слоёв было измеримым.

## Правила (ADR-052) — анти-наращивание

1. **Каждый слайс — net-negative.** Добавлено строк/файлов/серверов ≤ удалено.
   Если слайс даёт рост — он не принят, пока не покажет компенсирующее
   удаление. Дифф-статистика (файлы/строки/серверы/порты до-после) —
   обязательная часть каждого коммита.
2. **Никаких новых фреймворков, сборщиков и зависимостей.** Ванильный
   HTML/CSS/JS + текущий Electron. Новый слой поверх старого запрещён:
   перестраиваем существующие файлы, не кладём рядом новые модули ради UI.
3. **Один источник правды.** Состояние — существующие `/api/*` и WS; настройки
   — тот же config/API. UI не дублирует логику, не ведёт свой state-склад.
4. **Ядро не трогается.** Только presentation-слой (гибрид: capability в
   ядро, presentation наружу). Гарантии admission/receipt/delivery и
   speech-first — без изменений.
5. **Удаление, а не консервация.** Заменённый код удаляется в том же слайсе,
   не «на всякий случай» и не «потом». Legacy-ветки живут максимум один
   релиз и только как редирект (10 строк), не как слой.
6. **Ни одного нового источника правды, ни одного нового порта, ни одного
   нового окна-исключения.** Если исключение неизбежно — оно оформляется
   записью в DECISIONS.md с обоснованием, почему это не слой.

## Фактура сегодня (ветка reorg/kernel-migration-20261029)

- Основной UI: `http://127.0.0.1:2367/app` — `desktop/app.html` (736) +
  `app.js` (1890) + `app-settings.js` (508) + `app-scene.js` (706),
  Electron-клиент (`desktop/main.js`, 422) того же backend.
- Второй интерфейс: `http://127.0.0.1:8766/avatar` —
  `CompanionPresentationServer` в web.py, окно «питомца»/источник для OBS
  (`run_avatar_window.ps1`), своя страница, своя раздача ассетов, своя
  CSP-ветка (`legacy_presentation`).
- Итого: 2 сервера, 2 порта, 2 HTML-поверхности, 2 набора разрешений.

## Целевое состояние (бюджеты)

| Метрика | Было | Стало |
|---|---|---|
| HTTP-серверы UI | 2 (Companion + Presentation) | **1** (Presentation удалён) |
| Порты интерфейса | 2367 + 8766 | **2367** (8766 — редирект один релиз, потом удалить) |
| HTML-поверхности | app.html + страница презентации | **1** (app.html) + view-режим |
| Окна у пользователя | 2 разных интерфейса | 1 приложение + «сцена» как режим (OBS/питомец) |
| Зависимости | без изменений | без изменений |
| Строки desktop+presentation | текущие | ≤ текущих |

## Слайсы

**S1 — Один сервер, один порт, два режима.**
`/app` (панель) и `/avatar` (renderer-only сцена: персонаж без хрома, для
OBS/питомца) раздаёт один `CompanionServer` на 2367. Electron-«питомец» и OBS
Browser Source указывают на `http://127.0.0.1:2367/avatar`. Удаляются:
`CompanionPresentationServer`, отдельная страница презентации, дублирующая
раздача ассетов, `legacy_presentation`-ветки CSP. 8766 — редирект (10 строк).
Критерий: `grep -r 8766` в scripts/ сведён к редиректу и миграционной заметке;
тесты presentation-слоя переведены на один порт.

**S2 — Одно окно приложения: сцена + диалог + настройки.**
Внутри `app.html`: сцена персонажа и живая лента/ввод — главный экран;
настройки — компактные секции-аккордеоны с поиском, 2–3 поля в ряд,
расширенное (curiosity/mast/drives) свёрнуто; одна кнопка «Применить».
Перестройка `app-settings.js` и `app.html`, не новые модули. Удаляется
дублирующая навигация/шаблоны. Критерий: `app-settings.js` ≤ текущих 508
строк при тех же функциях (поиск + аккордеон дешевле простыни), тест
`app-settings-regression.test.js` зелёный.

**S3 — Детокс визуального языка.**
Единые токены отступов и типографики, плотность выше, никаких декоративных
элементов и градиентов-великанов. Критерий: удалённых CSS-правил ≥
добавленных; внешний вид — «тихо и дорого», не «вырвиглазно».

**S4 — Смоук и выключение старого.**
Браузерный смоук обоих режимов, прогон desktop-тестов, `run_target_jawl_smoke`
на одном порте. 8766-редирект помечен deprecated в DAILY_RUNBOOK.

## Стоп-условие (честно)

Если в ходе слайса выясняется, что «монолит» требует нового слоя (второй
state, новый роутер, новый формат конфига) — работа останавливается,
причина оформляется записью в DECISIONS.md, и решение принимается явно,
а не молчаливым наращиванием.

## Итог выполнения (30.10.2026, S1–S4 закрыты)

| Слайс | Коммиты | Дифф/результат |
|---|---|---|
| S1 | `e7781a0`, `ea4ca44`, `c519640` | +158/−600: серверы 2→1, порты 2→1, зомби-origin 8766 и run_live2d_smoke удалены |
| S2 | `8d49ee4` | +78/−77: аккордеон настроек (инженерные группы свёрнуты), поиск по названиям/описаниям/ключам; app-settings.js 508→498 строк |
| S3 | `93ab53d` | удалено 7 CSS-правил / добавлено 0 (баланс с S2 соблюдён), тени прижаты, плотность выше; app.html 736→726 |
| S4 | этот коммит | run_browser_render_smoke.ps1 → один порт, оба режима (/app и /app?mode=obs), живые маркеры; гейты: desktop node 84/84, pytest 1288/37 = env-линия |

Условия снятия one-release shim'ов (объявлены в S1): удалить no-op параметры
`-PresentationPort`/`--presentation-url` и drop-ветку `ports.presentation` в
загрузчиках — следующим релизом.

Остаток плана, признанный излишним после инвентаризации: «удаление
дублирующей навигации» — в desktop-оболочке дублей навигации нет (старое
предположение относилось к легаси index.html на 3413 строк, удалённому ещё в
ADR-045); фактические дубли (мёртвые CSS-блоки, Live2D-смоук) удалены в S3/S4.
`````

### `frontend/mic-processor.js`

`````javascript
class JawlMicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.offset = 0;
    this.port.onmessage = event => {
      if (event.data && event.data.type === 'flush') this.flush();
    };
  }

  flush() {
    if (!this.offset) {
      this.port.postMessage({type: 'flushed'});
      return;
    }
    const chunk = this.buffer.slice(0, this.offset);
    this.offset = 0;
    this.port.postMessage(chunk.buffer, [chunk.buffer]);
    this.port.postMessage({type: 'flushed'});
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    let offset = 0;
    while (offset < input.length) {
      const size = Math.min(input.length - offset, this.buffer.length - this.offset);
      this.buffer.set(input.subarray(offset, offset + size), this.offset);
      offset += size;
      this.offset += size;
      if (this.offset === this.buffer.length) {
        const chunk = this.buffer.slice();
        this.port.postMessage(chunk.buffer, [chunk.buffer]);
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor('jawl-mic-processor', JawlMicProcessor);
`````

### `README.md`

`````markdown
# JAWL Voice Companion — UI handoff

Снимок интерфейса из `main` (`b6c12b7`, 2026-10-30). Это исходники текущего единого окна компаньона для визуальной доработки.

## Главная точка входа

- `desktop/app.html` — разметка и встроенные стили приложения.
- `desktop/app.js` и `desktop/app-settings.js` — чат, голосовые элементы, навигация, состояние и поиск настроек.
- `desktop/app-scene.js`, `avatar-motion.js`, `avatar-physics.js` — 3D сцена и движение VRM.
- `desktop/speech-stream.js`, `voice-input.js`, `voice-draft.js`, `frontend/mic-processor.js` — клиентская часть речевого ввода/вывода.
- `desktop/main.js`, `panel-preload.js`, `runtime-config.js` — Electron оболочка. По умолчанию она открывает тот же `/app`; legacy-режим не используется.

Стили сейчас встроены в `app.html`, отдельного `app.css` нет. Three.js и `@pixiv/three-vrm` устанавливаются из lock-файла.

## Один UI origin

Веб-страница: `http://127.0.0.1:2367/app`.
Режим OBS: `http://127.0.0.1:2367/app?mode=obs` — тот же интерфейс с хромом сцены.
Интерфейс обращается к backend через same-origin `/api/*`; сервер и модели в этот handoff не включены. `8770` — внутренний JAWL console, не адрес пользовательского UI.

## Установка и проверки

Из папки `desktop`:

```powershell
npm ci
node --test *.test.js *.test.mjs tests/*.test.js tests/*.test.mjs
```

Для полноценного запуска нужен backend JAWL Companion из основного репозитория на порту `2367`. Без backend клиентские запросы `/api/*` не обслуживаются. Не копируйте сюда `.env` или пользовательские данные профиля.

## Содержимое

- `desktop/` — интерфейс, Electron оболочка и относящиеся к интерфейсу тесты.
- `frontend/mic-processor.js` — AudioWorklet, который отдаёт интерфейс микрофону.
- `assets/default-avatar.vrm` — текущая модель по умолчанию для просмотра сцены.
- `assets/avatar-render.png` — иконка приложения.
- `docs/UI_CONSOLIDATION_PLAN.md` — план консолидации и зафиксированные UI-ограничения S1–S4.

`node_modules`, backend, модели мозга/ASR/TTS, `.env`, память и журналы намеренно не включены.
`````
