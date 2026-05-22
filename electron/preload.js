// Bridges the renderer to a tiny, allow-listed subset of main-process APIs.
// Anything the renderer can call ends up here — never expose Node `require`.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  saveXlsx: (suggestedName) => ipcRenderer.invoke("save-xlsx", suggestedName),
  getVersion: () => ipcRenderer.invoke("get-version"),
  // Expose the backend's actual port so the renderer's API client can target it.
  // Necessary because the port is now dynamic (7842 by default, OS-assigned
  // fallback when 7842 is busy — see findFreePort in main.js).
  getBackendPort: () => ipcRenderer.invoke("get-backend-port"),
});
