/**
 * J.A.R.V.I.S. — preload bridge.
 *
 * Runs in an isolated world with Node access. Exposes a tiny, audited
 * surface on `window.jarvis` so the renderer (sandboxed) can ask the main
 * process to show/hide the window, toggle widget mode, and report wake-word
 * events. No raw ipcRenderer reaches the page.
 */
const { contextBridge, ipcRenderer } = require("electron");

const ALLOWED_OUT = new Set([
  "jarvis:wake",
  "jarvis:show",
  "jarvis:hide",
  "jarvis:toggle-visibility",
  "jarvis:set-widget-mode",
  "jarvis:request-mode",
]);

contextBridge.exposeInMainWorld("jarvis", {
  // Renderer → main (fire-and-forget signal, no return).
  send: (channel, payload) => {
    if (!ALLOWED_OUT.has(channel)) return;
    ipcRenderer.send(channel, payload);
  },
  // Renderer → main with a reply (used for current mode lookup).
  invoke: (channel, payload) => {
    if (channel !== "jarvis:request-mode") return Promise.resolve(null);
    return ipcRenderer.invoke(channel, payload);
  },
  // Main → renderer subscription.
  on: (channel, cb) => {
    const valid = new Set(["jarvis:mode-changed", "jarvis:visibility-changed", "jarvis:trigger-wake"]);
    if (!valid.has(channel)) return () => {};
    const wrapped = (_evt, ...args) => cb(...args);
    ipcRenderer.on(channel, wrapped);
    return () => ipcRenderer.removeListener(channel, wrapped);
  },
});
