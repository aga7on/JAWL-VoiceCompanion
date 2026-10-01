// JAWL VoiceCompanion desktop app (ADR-046): ONE compact window.
// The 3D character, chat, all functions and settings live in app.html,
// served by the companion (same origin - no bridge needed).
// The legacy two-window shell (panel + avatar) stays available via
// --legacy-shell for OBS/verification runs.

const { app, BrowserWindow, shell, ipcMain } = require('electron');
const path = require('path');
const http = require('http');

const MANIFEST = path.join(__dirname, '..', 'config', 'runtime.manifest.json');

function controlPort() {
  const envPort = Number(process.env.JAWL_DESKTOP_CONTROL_PORT);
  if (Number.isInteger(envPort) && envPort > 0) return envPort;
  try {
    const manifest = JSON.parse(require('fs').readFileSync(MANIFEST, 'utf8'));
    return manifest.ports.control || 2367;
  } catch (_) {
    return 2367;
  }
}

const PORT = controlPort();
const APP_URL = `http://127.0.0.1:${PORT}/app`;
const LEGACY = process.argv.includes('--legacy-shell');

let appWindow = null;
let avatarWindow = null;
let panelWindow = null;

// Emotion/lip relay for the LEGACY two-window shell only.
ipcMain.on('jawl-avatar-event', (_event, payload) => {
  if (avatarWindow && !avatarWindow.isDestroyed()) {
    avatarWindow.webContents.send('jawl-avatar-event', payload);
  }
});

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
  appWindow.loadURL(APP_URL);
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
  panelWindow.loadURL(`http://127.0.0.1:${PORT}/`);
  panelWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
  panelWindow.on('closed', () => { panelWindow = null; });
}

function panelReady() {
  return new Promise((resolve) => {
    const request = http.get({ host: '127.0.0.1', port: PORT, path: '/api/health', timeout: 2000 }, (response) => {
      resolve(response.statusCode === 200);
      response.resume();
    });
    request.on('error', () => resolve(false));
    request.on('timeout', () => { request.destroy(); resolve(false); });
  });
}

async function waitForPanel(retries = 90, delayMs = 2000) {
  for (let attempt = 0; attempt < retries; attempt += 1) {
    if (await panelReady()) return true;
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return false;
}

app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
// NOTE: no fake device: the app window records the owner's real microphone.
if (process.argv.includes('--remote-debugging-port')) {
  app.commandLine.appendSwitch('remote-debugging-port', '9222');
  app.commandLine.appendSwitch('remote-allow-origins', 'http://127.0.0.1:9222');
}

app.whenReady().then(async () => {
  if (LEGACY) {
    createLegacyWindows();
  } else {
    createAppWindow();
  }
  const ready = await waitForPanel();
  if (!ready && appWindow) {
    appWindow.loadURL(`data:text/html,<h1 style="font-family:sans-serif;color:#d7f0e9">Companion не отвечает на порт ${PORT}</h1><p style="color:#7ba8a0">Запусти стек: powershell -File scripts\\run_local_bonsai_integrated.ps1</p>`);
  }
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      LEGACY ? createLegacyWindows() : createAppWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});