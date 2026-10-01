// Embedded 3D scene for the single-window app (ADR-046).
// Same rendering core as desktop/avatar-scene.js (presets, rest pose,
// framing, lip sync, idle), but in-page: no cross-origin bridge needed.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const canvas = document.getElementById('avatar-canvas');
const statusEl = document.getElementById('avatar-status');

const WARDROBE_ROOT = '/api/avatar/model'; // served by the companion

const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
renderer.setClearColor(0x00000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

const scene = new THREE.Scene();
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

const state = {
  vrm: null,
  expression: 'neutral',
  expressionWeight: 0,
  lipLevel: 0,
  blinkNext: 0,
  lookTarget: new THREE.Vector3(0, 1.35, 4),
  wornModel: null,
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
  const delta = clock.getDelta();
  const elapsed = clock.elapsedTime;
  const vrm = state.vrm;
  if (vrm) {
    state.expressionWeight = Math.min(1, state.expressionWeight + delta * 3.0);
    applyExpression(vrm, state.expression, state.expressionWeight);
    applyLipSync(vrm, state.lipLevel);
    applyIdle(vrm, delta, elapsed);
    vrm.lookAt?.target?.copy(state.lookTarget);
    vrm.update(delta);
  }
  renderer.render(scene, camera);
}

function applyExpression(vrm, expression, weight) {
  const manager = vrm?.expressionManager;
  if (!manager) return;
  manager.setValue('happy', expression === 'happy' ? weight : 0);
  manager.setValue('angry', expression === 'angry' ? weight : 0);
  manager.setValue('sad', expression === 'sad' ? weight : 0);
  manager.setValue('relaxed', expression === 'relaxed' ? weight : 0);
  manager.setValue('surprised', expression === 'surprised' ? weight : 0);
  manager.update();
}

function applyLipSync(vrm, level) {
  vrm?.expressionManager?.setValue('aa', level);
}

function applyIdle(vrm, delta, elapsed) {
  if (elapsed > state.blinkNext) {
    state.blinkNext = elapsed + 3 + Math.random() * 2;
    state.blinkUntil = elapsed + 0.15;
  }
  const blinking = elapsed < (state.blinkUntil || 0);
  vrm?.expressionManager?.setValue('blink', blinking ? 1 : 0);
  const breath = Math.sin(elapsed * 1.5) * 0.008;
  const spine = vrm?.humanoid?.getNormalizedBoneNode('spine');
  if (spine) spine.rotation.x = breath;
  const head = vrm?.humanoid?.getNormalizedBoneNode('head');
  if (head) head.rotation.y = Math.sin(elapsed * 0.4) * 0.03;
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

function applyRestPose(vrm) {
  const humanoid = vrm?.humanoid;
  if (!humanoid) return;
  const leftArm = humanoid.getNormalizedBoneNode('leftUpperArm');
  const rightArm = humanoid.getNormalizedBoneNode('rightUpperArm');
  const leftFore = humanoid.getNormalizedBoneNode('leftLowerArm');
  const rightFore = humanoid.getNormalizedBoneNode('rightLowerArm');
  if (leftArm) leftArm.rotation.z = -1.05;
  if (rightArm) rightArm.rotation.z = 1.05;
  if (leftFore) leftFore.rotation.z = -0.25;
  if (rightFore) rightFore.rotation.z = 0.25;
  vrm.update(0.0);
}

function frameCamera(vrm) {
  vrm.update(0.0);
  const head = vrm.humanoid?.getNormalizedBoneNode('head');
  const forward = head
    ? new THREE.Vector3(0, 0, 1).applyQuaternion(head.getWorldQuaternion(new THREE.Quaternion()))
    : new THREE.Vector3(0, 0, -1);
  const root = vrm.humanoid?.getNormalizedBoneNode('hips')?.parent;
  if (root && forward.z > 0) {
    root.rotation.y = Math.PI;
    vrm.update(0.0);
  }
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const distance = (Math.max(size.y, size.x * 1.2) / 2) / Math.tan((camera.fov * Math.PI) / 360) * 1.15;
  camera.position.set(center.x, center.y, center.z + distance);
  camera.lookAt(center.x, center.y, center.z);
  state.lookTarget.set(center.x, center.y, center.z + distance);
  resize();
}

async function loadModel(url) {
  setStatus(`Аватар: загрузка…`);
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
  VRMUtils.removeUnnecessaryJoints(gltf.scene);
  VRMUtils.combineSkeletons?.(gltf.scene);
  scene.add(vrm.scene);
  applyRestPose(vrm);
  frameCamera(vrm);
  setStatus(`Аватар: готов (${listExpressions(vrm).length} выражений)`);
  return vrm;
}

function unload(vrm) {
  if (vrm) {
    VRMUtils.deepDispose(vrm.scene);
    scene.remove(vrm.scene);
  }
}

async function swapModel(url) {
  const previous = state.vrm;
  state.vrm = null;
  try {
    state.vrm = await loadModel(url);
    unload(previous);
  } catch (error) {
    setStatus(`Аватар: ошибка загрузки: ${error}`);
    state.vrm = previous;
    return null;
  }
  return state.vrm;
}

async function wear(model) {
  const name = String(model || '').replace(/[^a-zA-Z0-9_-]/g, '');
  if (!name) return null;
  // resolve through the wardrobe API (bounded, session-gated)
  try {
    const r = await wardrobeFetch('/api/avatar/wardrobe');
    const w = await r.json();
    const known = (w.models || []).some(m => m.model === name);
    if (!known) { setStatus(`Аватар: модель ${name} не в гардеробе`); return null; }
  } catch { /* offline wardrobe: refuse */ setStatus('Аватар: гардероб недоступен'); return null; }
  const vrm = await swapModel(`${WARDROBE_ROOT}/${name}.vrm`);
  if (!vrm) { state.wornModel = null; return null; }
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
  state.expression = preset || 'neutral';
}

// public surface for app.js
window.__jawlScene = {
  setEmotion,
  setLipLevel: (level) => { state.lipLevel = Math.max(0, Math.min(1, Number(level) || 0)); },
  swapModel,
  wear,
  get currentEmotion() { return state.expression; },
  get wornModel() { return state.wornModel; },
};

resize();
tick();
// default model: the wardrobe's first, else the constraint sample.
// Waits for app.js to establish the session (csrf) first - the wardrobe
// and model endpoints are session-gated.
(async () => {
  for (let i = 0; i < 20 && !window.__jcsrf; i++) {
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  try {
    const r = await wardrobeFetch('/api/avatar/wardrobe');
    const w = await r.json();
    const first = (w.models || [])[0];
    if (first) {
      const vrm = await wear(first.model);
      if (vrm) return;
    }
  } catch { /* fall through to direct load */ }
  loadModel('/app/runtime/vrm-models/VRM1_Constraint_Twist_Sample.vrm').then(vrm => { state.vrm = vrm; });
})();