const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');

const preloadPath = path.join(__dirname, '..', 'panel-preload.js');
const source = fs.readFileSync(preloadPath, 'utf8');

test('panel-preload exposes window mode, click-through, and stop actions to both jawlDesktop and __jawlDesktop', () => {
  const exposed = {};
  const sent = [];
  const rendererIpc = new EventEmitter();
  rendererIpc.send = (channel, payload) => sent.push({ channel, payload });

  const mockElectron = {
    contextBridge: {
      exposeInMainWorld(name, api) {
        exposed[name] = api;
      },
    },
    ipcRenderer: rendererIpc,
  };

  const context = {
    require: (id) => {
      if (id === 'electron') return mockElectron;
      throw new Error(`Unexpected import: ${id}`);
    },
    console,
  };

  vm.runInNewContext(source, context, { filename: preloadPath });

  assert.ok(exposed.jawlDesktop, 'jawlDesktop should be exposed');
  assert.ok(exposed.__jawlDesktop, '__jawlDesktop should be exposed');
  assert.equal(exposed.jawlDesktop, exposed.__jawlDesktop, 'both exposed APIs should share the same bridge definition');

  const api = exposed.jawlDesktop;

  // 1. setWindowMode
  assert.equal(typeof api.setWindowMode, 'function');
  api.setWindowMode({ compact: true, alwaysOnTop: true, clickThrough: false });
  assert.equal(sent.at(-1).channel, 'jawl-window-mode');
  assert.equal(sent.at(-1).payload.compact, true);
  assert.equal(sent.at(-1).payload.alwaysOnTop, true);
  assert.equal(sent.at(-1).payload.clickThrough, false);

  // setWindowMode ignores non-objects
  api.setWindowMode(null);
  assert.equal(sent.length, 1);

  // 2. acknowledgeProfileStop
  assert.equal(typeof api.acknowledgeProfileStop, 'function');
  api.acknowledgeProfileStop();
  assert.equal(sent.at(-1).channel, 'jawl-profile-stop-accepted');

  // 3. onProfileStopRequest
  let stopCalled = 0;
  const unsubscribeStop = api.onProfileStopRequest(() => { stopCalled += 1; });
  rendererIpc.emit('jawl-profile-stop-request');
  assert.equal(stopCalled, 1);
  unsubscribeStop();
  rendererIpc.emit('jawl-profile-stop-request');
  assert.equal(stopCalled, 1);

  // 4. onClickThroughChanged
  let clickThroughState = null;
  const unsubscribeClickThrough = api.onClickThroughChanged((val) => { clickThroughState = val; });
  rendererIpc.emit('jawl-click-through-changed', {}, false);
  assert.equal(clickThroughState, false);
  rendererIpc.emit('jawl-click-through-changed', {}, true);
  assert.equal(clickThroughState, true);
  unsubscribeClickThrough();
  rendererIpc.emit('jawl-click-through-changed', {}, false);
  assert.equal(clickThroughState, true); // Still true because unsubscribed
});
