import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
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

test('applyCameraFraming frames bust shot in compact mode and full body in standard mode', () => {
  let isCompact = false;
  const mockDocument = {
    body: {
      classList: {
        contains: (cls) => cls === 'compact-mode' && isCompact,
      },
    },
  };

  class Vector3 {
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
  }

  class Box3 {
    setFromObject() { return this; }
    getSize(target) { target.set(0.6, 1.6, 0.3); return target; }
    getCenter(target) { target.set(0, 0.8, 0); return target; }
    get max() { return { y: 1.6 }; }
  }

  const camera = {
    fov: 30,
    position: new Vector3(),
    lookAt(x, y, z) { this.target = { x, y, z }; },
  };

  const state = {
    lookTarget: new Vector3(),
  };

  const mockTHREE = { Vector3, Box3 };

  const headNode = {
    getWorldPosition(target) { target.set(0, 1.45, 0); return target; },
  };
  const chestNode = {
    getWorldPosition(target) { target.set(0, 1.25, 0); return target; },
  };

  const vrm = {
    scene: {},
    humanoid: {
      getNormalizedBoneNode(name) {
        if (name === 'head') return headNode;
        if (name === 'upperChest') return chestNode;
        return null;
      },
    },
  };

  const context = {
    THREE: mockTHREE,
    camera,
    state,
    document: mockDocument,
  };

  vm.runInNewContext(extractFunction('applyCameraFraming'), context);

  // 1. In standard / studio mode (isCompact = false)
  isCompact = false;
  context.applyCameraFraming(vrm);
  const stdDistance = camera.position.z;
  const stdY = camera.position.y;
  assert.ok(stdDistance > 3.0, `Standard distance should frame full body (~3.4m), got ${stdDistance}`);
  assert.equal(stdY, 0.8, 'Standard camera looks at center (0.8m)');

  // 2. In compact HUD mode (isCompact = true)
  isCompact = true;
  context.applyCameraFraming(vrm);
  const compactDistance = camera.position.z;
  const compactY = camera.position.y;
  assert.ok(compactDistance < stdDistance * 0.55, `Compact distance should be much closer (bust shot), got ${compactDistance} vs std ${stdDistance}`);
  assert.ok(compactY > 1.1, `Compact camera should focus on chest/head level (~1.3m), got ${compactY}`);
});

test('setRenderPaused stops requestAnimationFrame loop and resets delta on resume', () => {
  let rafCalls = 0;
  let rafIdCounter = 100;
  const mockRaf = () => { rafCalls += 1; return ++rafIdCounter; };
  let clockDeltas = 0;
  const mockClock = {
    getDelta: () => { clockDeltas += 1; return 0.016; },
    elapsedTime: 1.0,
  };

  const context = {
    requestAnimationFrame: mockRaf,
    clock: mockClock,
  };

  vm.runInNewContext([
    'var renderPaused = false;',
    'var rafId = null;',
    'function tick() {}',
    extractFunction('setRenderPaused'),
  ].join('\n'), context);

  // Pause rendering
  context.setRenderPaused(true);
  assert.equal(context.renderPaused, true);
  assert.equal(rafCalls, 0);

  // Resume rendering: calls clock.getDelta to discard elapsed pause time and starts rAF
  context.setRenderPaused(false);
  assert.equal(context.renderPaused, false);
  assert.equal(clockDeltas, 1, 'Should flush clock delta on unpause');
  assert.equal(rafCalls, 1, 'Should schedule requestAnimationFrame on unpause');
});
