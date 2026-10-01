// Preload for the PANEL window (http origin, the Companion control panel).
// Bridges the panel's avatar BroadcastChannel events to the main process,
// which relays them to the file:// avatar window (different origin - the
// channel itself cannot cross origins).
//
// The panel page is the Companion's own code; we only attach a message pump
// next to it. contextIsolation keeps the page and this script in separate
// worlds, so the page's globals are untouched.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('__jawlDesktop', {
  isDesktop: true,
  forwardAvatarEvent(event) {
    ipcRenderer.send('jawl-avatar-event', event);
  },
});

// Join the panel's avatar channel and forward every event to the main
// process. Runs in the isolated world: it cannot read page variables, but
// BroadcastChannel is an origin-scoped browser API and works from here.
try {
  const channel = new BroadcastChannel('jawl-voicecompanion-avatar');
  channel.onmessage = (message) => {
    const event = message && message.data;
    if (event && typeof event === 'object' && typeof event.type === 'string') {
      ipcRenderer.send('jawl-avatar-event', event);
    }
  };
} catch (_) {
  // The channel is optional; the avatar window simply stays idle.
}