// JAWL VoiceCompanion desktop shell (ADR-045): Electron replaces the browser
// as the product surface. Two windows:
//   - avatar: the 3D VRM scene (three.js + three-vrm), borderless, always on
//     top optional (OBS-friendly); loads avatar.html from this directory.
//   - panel: the existing Companion control panel served by the local
//     Companion server (http://127.0.0.1:<control port>). The panel's code
//     is NOT duplicated or rewritten - Electron is a shell around it.
//
// The Companion server may not be up yet when the shell starts; the panel
// window retries until it answers. The avatar window works fully offline.
//
// Mic ownership: this shell (its panel window) owns the microphone through
// getUserMedia with our flags - the rust client is retired to a
// launcher/OBS tool.

const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const http = require('http');

const MANIFEST = path.join(__dirname, '..', 'config', 'runtime.manifest.json');

function controlPort() {
  // Disposable profiles raise the stack on other ports; the smoke tests set
  // this env to point the panel window at them.
  const envPort = Number(process.env.JAWL_DESKTOP_CONTROL_PORT);
  if (Number.isInteger(envPort) && envPort > 0) return envPort;
  try {
    const manifest = JSON.parse(require('fs').readFileSync(MANIFEST, 'utf-8'));
    return manifest.ports.control || 2367;
  } catch (_) {
    return 2367;
  }
}

const PORT = controlPort();
const PANEL_URL = `http://127.0.0.1:${PORT}/`;

let panelWindow = null;
let avatarWindow = null;

// ---------------------------------------------------------------------------
// Emotion/lip relay: the panel (http origin) publishes avatar events over a
// BroadcastChannel, but the avatar window is file:// - different origin, so
// the channel never crosses. The main process bridges the two: preload in
// the avatar window asks the panel window to join the channel and forward
// every event to the main process, which delivers it to the avatar.
// Message stays one-directional (panel -> avatar): the avatar window keeps
// zero privileges.
// ---------------------------------------------------------------------------

const { ipcMain } = require('electron');

ipcMain.on('jawl-avatar-event', (_event, payload) => {
  if (avatarWindow && !avatarWindow.isDestroyed()) {
    avatarWindow.webContents.send('jawl-avatar-event', payload);
  }
});

function createAvatarWindow() {
  avatarWindow = new BrowserWindow({
    width: 480,
    height: 800,
    x: 100,
    y: 60,
    title: 'JAWL Companion — аватар',
    backgroundColor: '#001a2b26',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      // The scene is local content; no remote code runs in this window.
      sandbox: true,
      // Receives the avatar events relayed from the panel window.
      preload: path.join(__dirname, 'avatar-preload.js'),
    },
  });
  avatarWindow.loadFile(path.join(__dirname, 'avatar.html'));
  avatarWindow.on('closed', () => { avatarWindow = null; });
  return avatarWindow;
}

function createPanelWindow() {
  panelWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    x: 620,
    y: 60,
    title: 'JAWL VoiceCompanion — панель',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      // Mic access is granted by the user through the panel window, exactly
      // like in the browser, but without fake-capture or autoplay policies
      // fighting us - we set the flags in app.commandLine below.
      sandbox: true,
      // Our relay pump: forwards the panel's avatar BroadcastChannel events
      // to the main process so the file:// avatar window can follow the
      // conversation (origins differ; the channel cannot cross alone).
      preload: path.join(__dirname, 'panel-preload.js'),
    },
  });
  panelWindow.loadURL(PANEL_URL);
  // Open external links in the OS browser, never inside the shell.
  panelWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
  panelWindow.on('closed', () => { panelWindow = null; });
  return panelWindow;
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

async function waitForPanel(retries = 60, delayMs = 2000) {
  for (let attempt = 0; attempt < retries; attempt += 1) {
    if (await panelReady()) return true;
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return false;
}

app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
// NOTE: no --use-fake-device-for-media-stream and no file-fake-audio-capture:
// the panel window records the owner's real microphone.
if (process.argv.includes('--remote-debugging-port')) {
  app.commandLine.appendSwitch('remote-debugging-port', '9222');
  // The smoke test attaches from the local origin; CDP rejects WebSocket
  // handshakes without this since Chromium 111+.
  app.commandLine.appendSwitch('remote-allow-origins', 'http://127.0.0.1:9222');
}

app.whenReady().then(async () => {
  createAvatarWindow();
  createPanelWindow();
  const ready = await waitForPanel();
  if (!ready && panelWindow) {
    panelWindow.loadURL(`data:text/html,<h1 style="font-family:sans-serif">Companion не отвечает на ${PANEL_URL}</h1><p>Запусти стек: powershell -File scripts\\run_local_bonsai_integrated.ps1</p>`);
  }
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createAvatarWindow();
      createPanelWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
