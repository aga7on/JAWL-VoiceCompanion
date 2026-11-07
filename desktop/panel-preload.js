// Explicit bridge for desktop-only window lifecycle and chameleon mode actions.
const { contextBridge, ipcRenderer } = require('electron');

const desktopBridge = {
  onProfileStopRequest(callback) {
    if (typeof callback !== 'function') return () => {};
    const listener = () => callback();
    ipcRenderer.on('jawl-profile-stop-request', listener);
    return () => ipcRenderer.removeListener('jawl-profile-stop-request', listener);
  },
  acknowledgeProfileStop() {
    ipcRenderer.send('jawl-profile-stop-accepted');
  },
  setWindowMode(payload) {
    if (!payload || typeof payload !== 'object') return;
    ipcRenderer.send('jawl-window-mode', {
      compact: Boolean(payload.compact),
      alwaysOnTop: Boolean(payload.alwaysOnTop),
      clickThrough: Boolean(payload.clickThrough),
    });
  },
  onClickThroughChanged(callback) {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, clickThrough) => callback(Boolean(clickThrough));
    ipcRenderer.on('jawl-click-through-changed', listener);
    return () => ipcRenderer.removeListener('jawl-click-through-changed', listener);
  },
};

// Expose on both names so renderer code using jawlDesktop or __jawlDesktop succeeds.
contextBridge.exposeInMainWorld('jawlDesktop', desktopBridge);
contextBridge.exposeInMainWorld('__jawlDesktop', desktopBridge);
