// Bridges the renderer to a tiny, allow-listed subset of main-process APIs.
// Anything the renderer can call ends up here — never expose Node `require`.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  saveXlsx: (suggestedName) => ipcRenderer.invoke("save-xlsx", suggestedName),
  getVersion: () => ipcRenderer.invoke("get-version"),
});
