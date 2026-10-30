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
