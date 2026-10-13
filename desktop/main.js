// JAWL VoiceCompanion desktop app (ADR-046): ONE compact window.
// The 3D character, chat, all functions and settings live in app.html,
// served by the companion (same origin - no bridge needed).
// The legacy two-window shell (panel + avatar) stays available via
// --legacy-shell for OBS/verification runs.

const { app, BrowserWindow, shell, ipcMain, session } = require('electron');
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
  appWindow = new BrowserWindow({
    width: 1060,
    height: 720,
    minWidth: 720,
    minHeight: 480,
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
    },
  });
  installNavigationGuards(appWindow, retryPanelReadiness);
  appWindow.loadURL(START_PAGE_URL);
  appWindow.on('closed', () => { appWindow = null; });
  return appWindow;
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

app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
// NOTE: no fake device: the app window records the owner's real microphone.
if (process.argv.includes('--remote-debugging-port')) {
  app.commandLine.appendSwitch('remote-debugging-port', '9222');
  app.commandLine.appendSwitch('remote-allow-origins', 'http://127.0.0.1:9222');
}

app.whenReady().then(async () => {
  installPermissionGuards();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      LEGACY ? createLegacyWindows() : createAppWindow();
      retryPanelReadiness();
    }
  });
  if (LEGACY) {
    createLegacyWindows();
  } else {
    createAppWindow();
  }
  await startPanelReadiness();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
