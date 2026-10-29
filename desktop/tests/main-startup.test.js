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
