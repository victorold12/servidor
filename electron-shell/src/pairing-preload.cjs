/** Preload da janela de pareamento — ponte mínima só pro que essa tela precisa. */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("pairingBridge", {
  start: (opts) => ipcRenderer.invoke("pairing:start", opts),
  onEvent: (callback) => {
    ipcRenderer.on("pairing:event", (_evt, data) => callback(data));
  },
});
