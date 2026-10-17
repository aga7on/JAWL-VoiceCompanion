// Preload for the AVATAR window (file:// origin, local scene content).
// Receives avatar events relayed by the main process (they originate in the
// panel window's BroadcastChannel - a different origin, so the channel
// cannot deliver directly) and re-dispatches them on the shared DOM window.
// Isolated worlds share the DOM but not JS globals: dispatchEvent is visible
// to the page, while this script's own state is not.

const { ipcRenderer } = require('electron');

ipcRenderer.on('jawl-avatar-event', (_event, payload) => {
  if (payload && typeof payload === 'object') {
    window.dispatchEvent(new CustomEvent('jawl-avatar-event', { detail: payload }));
  }
});

// Let the page know the desktop bridge exists (feature detection).
window.dispatchEvent(new CustomEvent('jawl-desktop-bridge', { detail: { bridge: true } }));