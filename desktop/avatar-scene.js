// JAWL 3D avatar scene (ADR-045): three.js + three-vrm.
//
// Responsibilities:
//   - render the VRM character (model swapped at runtime = agent-side
//     appearance customization);
//   - emotion bridge: JAWL envelope emotion -> VRM expression presets
//     (happy / angry / sad / relaxed / surprised) with smooth fades;
//   - lip sync: an RMS level (0..1) drives the 'aa' expression;
//   - idle life: blink + subtle breathing sway so the character is never
//     frozen.
//
// The scene is self-contained local content: no network, no remote code.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const canvas = document.getElementById('scene');
const statusEl = document.getElementById('status');

const DEFAULT_MODEL = '../runtime/vrm-models/VRM1_Constraint_Twist_Sample.vrm';

// ---------------------------------------------------------------------------
// Renderer / scene / camera
// ---------------------------------------------------------------------------

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setClearColor(0x001a2b26, 1);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 40);
// Initial position is provisional; frameCamera() measures the loaded model
// and places the camera for a full-body frontal shot.

scene.add(new THREE.DirectionalLight(0xffffff, Math.PI).translateY(3).translateX(2));
scene.add(new THREE.AmbientLight(0xffffff, 0.6));

const clock = new THREE.Clock();

// ---------------------------------------------------------------------------
// Avatar state
// ---------------------------------------------------------------------------

const state = {
  vrm: null,
  expression: 'neutral',
  expressionWeight: 0,
  lipLevel: 0,
  blinkNext: 0,
  lookTarget: new THREE.Vector3(0, 1.35, 4),
};

// Diagnostic probes (read by the smoke test through CDP): live values of the
// emotion bridge and the scene composition. window.__scene is the three.js
// scene so tests can assert the swap does not leak instances.
window.__scene = scene;
window.__jawlSceneVersion = 'v3-framing-probe';
function tick() {
  requestAnimationFrame(tick);
  const delta = clock.getDelta();
  const elapsed = clock.elapsedTime;
  const vrm = state.vrm;
  window.__jawlEmotion = state.expression;
  window.__jawlLipLevel = state.lipLevel;
  if (vrm) {
    state.expressionWeight = Math.min(1, state.expressionWeight + delta * 3.0);
    applyExpression(vrm, state.expression, state.expressionWeight);
    applyLipSync(vrm, state.lipLevel);
    applyIdle(vrm, delta, elapsed);
    vrm.lookAt?.target?.copy(state.lookTarget);
    vrm.update(delta);
    // Live blendshape weights for diagnostics.
    const manager = vrm.expressionManager;
    if (manager) {
      window.__jawlEmotionWeight = manager.getValue(state.expression === 'neutral'
        ? 'relaxed' : state.expression) || 0;
      window.__jawlAaWeight = manager.getValue('aa') || 0;
    }
  }
  renderer.render(scene, camera);
}

function setStatus(text) {
  statusEl.textContent = text;
}

async function loadModel(url) {
  setStatus(`Аватар: загрузка модели… (${url.split('/').pop()})`);
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync(url);
  const vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryJoints(gltf.scene);
  VRMUtils.combineSkeletons?.(gltf.scene);
  scene.add(vrm.scene);
  try {
    frameCamera(vrm);
    window.__jawlHeadProbe = probeHead(vrm);
  } catch (error) {
    setStatus(`Аватар: ошибка кадрирования: ${error}`);
    window.__jawlFramingError = String(error);
  }
  setStatus(`Аватар: готов (${listExpressions(vrm).length} выражений)`);
  return vrm;
}

// Auto-framing: measure the model's real bounding box and place the camera
// so the full body fits regardless of the model's scale/origin. The heading
// (front/back) is fixed through the humanoid ROOT node - vrm.update()
// re-evaluates the pose from the normalized rig, so rotating vrm.scene
// directly gets overwritten every frame.
function frameCamera(vrm) {
  vrm.update(0.0);
  // Face direction, measured (not guessed): the head's world +Z. The
  // constraint-sample model looks toward +Z, so to face the camera at +Z we
  // rotate the rig ROOT by PI. The hips' parent is the node vrm.update()
  // does not overwrite every frame (unlike vrm.scene.rotation).
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
  window.__jawlFraming = { height: Math.round(size.y * 100) / 100,
                            distance: Math.round(distance * 100) / 100,
                            turned: Boolean(root && forward.z > 0) };
  resize();
}

// Diagnostic: world-space head/eye positions and the model's forward
// direction, so the framing decision is data, not guesswork.
function probeHead(vrm) {
  const head = vrm.humanoid?.getNormalizedBoneNode('head');
  if (!head) return null;
  const world = head.getWorldPosition(new THREE.Vector3());
  // The face direction: the local +Z of the head node after world transform.
  const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(head.getWorldQuaternion(new THREE.Quaternion()));
  return { world: [world.x, world.y, world.z], forward: [forward.x, forward.y, forward.z] };
}

function listExpressions(vrm) {
  const manager = vrm?.expressionManager;
  if (!manager) return [];
  return manager.expressions.map((expression) => expression.expressionName);
}

function unloadCurrent() {
  if (state.vrm) {
    VRMUtils.deepDispose(state.vrm.scene);
    scene.remove(state.vrm.scene);
    state.vrm = null;
  }
}

async function swapModel(url) {
  const previous = state.vrm;
  state.vrm = null;
  try {
    state.vrm = await loadModel(url);
    unload(previous);
  } catch (error) {
    setStatus(`Аватар: ошибка загрузки ${url}: ${error}`);
    state.vrm = previous;
  }
  return state.vrm;
}

function unload(vrm) {
  if (vrm) {
    VRMUtils.deepDispose(vrm.scene);
    scene.remove(vrm.scene);
  }
}

// ---------------------------------------------------------------------------
// Emotion bridge: JAWL emotions -> VRM presets
// ---------------------------------------------------------------------------

const EMOTION_PRESETS = {
  happy: 'happy',
  joyful: 'happy',
  angry: 'angry',
  sad: 'sad',
  calm: 'relaxed',
  neutral: null,
  surprised: 'surprised',
  error: 'sad',
};

function setEmotion(emotionId) {
  const preset = EMOTION_PRESETS[emotionId] || null;
  state.expression = preset || 'neutral';
  setStatus(`Аватар: ${state.expression}`);
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

// ---------------------------------------------------------------------------
// Lip sync: level 0..1 -> 'aa'
// ---------------------------------------------------------------------------

function setLipLevel(level) {
  state.lipLevel = Math.max(0, Math.min(1, Number(level) || 0));
}

function applyLipSync(vrm, level) {
  vrm?.expressionManager?.setValue('aa', level);
}

// ---------------------------------------------------------------------------
// Idle life: blink + breathing
// ---------------------------------------------------------------------------

function applyIdle(vrm, delta, elapsed) {
  // Blink: roughly every 3-5 s, 0.15 s long.
  if (elapsed > state.blinkNext) {
    state.blinkNext = elapsed + 3 + Math.random() * 2;
    state.blinkUntil = elapsed + 0.15;
  }
  const blinking = elapsed < (state.blinkUntil || 0);
  vrm?.expressionManager?.setValue('blink', blinking ? 1 : 0);
  // Breathing: chest + slight head sway.
  const breath = Math.sin(elapsed * 1.5) * 0.008;
  const spine = vrm?.humanoid?.getNormalizedBoneNode('spine');
  if (spine) spine.rotation.x = breath;
  const head = vrm?.humanoid?.getNormalizedBoneNode('head');
  if (head) head.rotation.y = Math.sin(elapsed * 0.4) * 0.03;
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------

function resize() {
  const width = canvas.clientWidth || 1;
  const height = canvas.clientHeight || 1;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

// ---------------------------------------------------------------------------
// Control surface: the panel window (or tests) drive the avatar through
// window events; ADR-045 keeps the avatar window unprivileged local content.
// ---------------------------------------------------------------------------

window.__jawlAvatar = {
  setEmotion,
  setLipLevel,
  swapModel,
  listExpressions: () => listExpressions(state.vrm),
  setLookTarget(x, y, z) {
    state.lookTarget.set(Number(x) || 0, Number(y) || 1.35, Number(z) || 4);
  },
};

window.addEventListener('message', (event) => {
  const data = event.data;
  if (!data || typeof data !== 'object' || data.channel !== 'jawl-avatar') return;
  if (data.type === 'emotion') window.__jawlAvatar.setEmotion(data.emotion);
  if (data.type === 'lip') window.__jawlAvatar.setLipLevel(data.level);
  if (data.type === 'swap') window.__jawlAvatar.swapModel(data.url);
});

resize();
tick();
loadModel(DEFAULT_MODEL).then((vrm) => { state.vrm = vrm; });
