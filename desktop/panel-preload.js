// Small, explicit bridge for the one desktop-only lifecycle action.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jawlDesktop', {
  onProfileStopRequest(callback) {
    if (typeof callback !== 'function') return () => {};
    const listener = () => callback();
    ipcRenderer.on('jawl-profile-stop-request', listener);
    return () => ipcRenderer.removeListener('jawl-profile-stop-request', listener);
  },
  acknowledgeProfileStop() {
    ipcRenderer.send('jawl-profile-stop-accepted');
  },
});
