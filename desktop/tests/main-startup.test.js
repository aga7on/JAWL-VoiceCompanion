const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const mainPath = path.join(__dirname, '..', 'main.js');
const source = fs.readFileSync(mainPath, 'utf8');

function createHarness({ health = () => true } = {}) {
  const state = {
    windows: [],
    requests: 0,
    externalUrls: [],
    permissionRequestHandler: null,
    permissionCheckHandler: null,
    appHandlers: new Map(),
    commandLine: [],
    startup: null,
  };
  let healthCheck = health;

  class MockBrowserWindow {
    constructor(options) {
      this.options = options;
      this.urls = [];
      this.handlers = new Map();
      this.destroyed = false;
      this.webContents = new EventEmitter();
      this.webContents.setWindowOpenHandler = (handler) => {
        this.webContents.openHandler = handler;
      };
      this.webContents.send = () => {};
      this.webContents.getURL = () => this.urls.at(-1) || '';
      state.windows.push(this);
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
      quit() {},
    },
    BrowserWindow: MockBrowserWindow,
    shell: { openExternal(url) { state.externalUrls.push(url); return Promise.resolve(); } },
    ipcMain: { on() {} },
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
    console,
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
});
