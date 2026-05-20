// Electron main process.
// Boots the bundled Python backend, waits for it to become healthy, then opens
// the BrowserWindow loading the bundled React frontend. A small splash window
// shows immediately so the user sees activity during the 1-3s backend startup.
// On quit, SIGTERMs the backend and waits for it to exit cleanly.
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const { spawn } = require("node:child_process");
const http = require("node:http");
const windowStateKeeper = require("electron-window-state");

const BACKEND_PORT = 7842;
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/health`;
const HEALTH_TIMEOUT_MS = 30_000;
const HEALTH_POLL_MS = 200;

let backendProcess = null;
let mainWindow = null;
let splashWindow = null;
let intentionalQuit = false;

function isDev() {
  return process.env.NODE_ENV === "development" || !app.isPackaged;
}

function backendExecutablePath() {
  // In production, electron-builder copies backend-dist/ to resources/backend/
  const exeName = process.platform === "win32" ? "backend.exe" : "backend";
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend", exeName);
  }
  // Dev: prefer the PyInstaller build if it exists, fall back to running Python directly.
  const local = path.join(__dirname, "..", "backend-dist", exeName);
  if (fs.existsSync(local)) return local;
  return null;
}

// In-memory tail of the most recent stderr lines from the backend. We surface
// the last few in the error dialog when the backend crashes so the user (and
// support) doesn't have to dig through the log file to know what happened.
const STDERR_TAIL_MAX = 50;
let stderrTail = [];

function backendLogPath() {
  return path.join(app.getPath("userData"), "backend.log");
}

function appendBackendLog(text) {
  try {
    fs.appendFileSync(backendLogPath(), text);
  } catch (e) {
    console.warn("[electron] backend.log write failed:", e.message);
  }
}

function startBackend() {
  const userData = app.getPath("userData");
  fs.mkdirSync(userData, { recursive: true });
  // PORTFOLIO_PROFILES_DIR drives multi-profile support: the backend picks the
  // active profile's DB on its own and exposes /api/profiles/* endpoints to
  // switch between them. We omit PORTFOLIO_DB_PATH so the profile-aware
  // resolver in backend.db is in charge.
  const env = {
    ...process.env,
    PORTFOLIO_PROFILES_DIR: userData,
    // PyInstaller-bundled stdio doesn't flush by default; force unbuffered so
    // stderr lines reach us promptly before a crash.
    PYTHONUNBUFFERED: "1",
  };
  const legacyDb = path.join(userData, "portfolio.db");
  if (fs.existsSync(legacyDb)) {
    console.log(`[electron] Note: legacy DB at ${legacyDb} (ignored in profile mode)`);
  }

  // Reset the rolling stderr buffer and log header on each backend launch.
  stderrTail = [];
  appendBackendLog(
    `\n===== backend start ${new Date().toISOString()} =====\n` +
      `userData=${userData}\n`,
  );

  const bin = backendExecutablePath();
  if (bin) {
    console.log(`[electron] Launching bundled backend: ${bin}`);
    console.log(`[electron] PORTFOLIO_PROFILES_DIR=${userData}`);
    appendBackendLog(`mode=bundled  bin=${bin}\n`);
    backendProcess = spawn(bin, [], {
      env,
      // Pipe both streams so we can capture stderr to disk.
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
  } else {
    // Dev fallback: run Python directly.
    console.log("[electron] No PyInstaller binary — running `python -m backend.main`");
    const cwd = path.join(__dirname, "..");
    const py = process.platform === "win32" ? "py" : "python3";
    appendBackendLog(`mode=dev      py=${py}  cwd=${cwd}\n`);
    backendProcess = spawn(py, ["-m", "backend.main"], {
      env,
      stdio: ["ignore", "pipe", "pipe"],
      cwd,
    });
  }

  // Tee both streams to backend.log and to the in-memory tail.
  const pipe = (stream, prefix) => {
    if (!stream) return;
    stream.setEncoding("utf8");
    stream.on("data", (chunk) => {
      appendBackendLog(chunk);
      // Keep the rolling tail
      const lines = chunk.split(/\r?\n/);
      for (const line of lines) {
        if (!line) continue;
        stderrTail.push(`${prefix}${line}`);
        if (stderrTail.length > STDERR_TAIL_MAX) stderrTail.shift();
      }
    });
  };
  pipe(backendProcess.stdout, "");
  pipe(backendProcess.stderr, "");

  backendProcess.on("error", (err) => {
    appendBackendLog(`spawn-error: ${err.stack || err.message}\n`);
  });

  backendProcess.on("exit", (code, signal) => {
    const msg = `[electron] Backend exited (code=${code}, signal=${signal})`;
    console.log(msg);
    appendBackendLog(`exit code=${code} signal=${signal} at ${new Date().toISOString()}\n`);
    backendProcess = null;
    if (!intentionalQuit && mainWindow && !mainWindow.isDestroyed()) {
      const tail = stderrTail.slice(-12).join("\n") || "(no output captured)";
      dialog.showErrorBox(
        "Backend stopped",
        `Exit code: ${code}  signal: ${signal || "none"}\n\n` +
          `Last log lines:\n${tail}\n\n` +
          `Full log: ${backendLogPath()}`,
      );
    }
  });
}

function waitForBackend() {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + HEALTH_TIMEOUT_MS;
    const tryOnce = () => {
      const req = http.get(HEALTH_URL, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolve();
        retry();
      });
      req.on("error", retry);
      req.setTimeout(800, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() > deadline) {
        return reject(new Error("Backend health check timed out"));
      }
      setTimeout(tryOnce, HEALTH_POLL_MS);
    };
    tryOnce();
  });
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 260,
    frame: false,
    resizable: false,
    movable: true,
    transparent: false,
    backgroundColor: "#0A0F1E",
    alwaysOnTop: true,
    skipTaskbar: true,
    show: true,
    webPreferences: { contextIsolation: true, sandbox: true },
  });
  const splashHtml = `
<!doctype html><html><head><meta charset="utf-8"><title>Portfolio Dashboard</title>
<style>
  html,body{margin:0;height:100%;background:#0A0F1E;color:#F9FAFB;font-family:-apple-system,Segoe UI,Inter,sans-serif;}
  .wrap{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:32px;}
  .title{font-size:22px;font-weight:600;letter-spacing:-0.01em;margin-bottom:8px;}
  .sub{color:#6B7280;font-size:13px;margin-bottom:24px;}
  .bar{width:220px;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;position:relative;}
  .bar::after{content:"";position:absolute;left:-40%;top:0;bottom:0;width:40%;background:#3B82F6;
    border-radius:2px;animation:slide 1.2s ease-in-out infinite;}
  @keyframes slide{0%{left:-40%}100%{left:100%}}
</style></head>
<body><div class="wrap">
  <div class="title">Portfolio Dashboard</div>
  <div class="sub">Starting local data service…</div>
  <div class="bar"></div>
</div></body></html>`;
  splashWindow.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(splashHtml));
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close();
  }
  splashWindow = null;
}

async function createWindow() {
  const state = windowStateKeeper({ defaultWidth: 1440, defaultHeight: 960 });

  mainWindow = new BrowserWindow({
    x: state.x,
    y: state.y,
    width: state.width,
    height: state.height,
    minWidth: 1280,
    minHeight: 900,
    backgroundColor: "#0A0F1E",
    title: "Portfolio Dashboard",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: false,
      nodeIntegration: false,
    },
  });
  state.manage(mainWindow);

  if (isDev()) {
    await mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    // In production, electron-builder copies the Vite dist/ into
    // resources/dist/ via extraResources. process.resourcesPath points there.
    await mainWindow.loadFile(path.join(process.resourcesPath, "dist", "index.html"));
  }

  mainWindow.once("ready-to-show", () => {
    closeSplash();
    mainWindow.show();
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

app.whenReady().then(async () => {
  try {
    createSplash();
    startBackend();
    await waitForBackend();
    await createWindow();
  } catch (err) {
    console.error("[electron] Failed to start:", err);
    closeSplash();
    dialog.showErrorBox(
      "Couldn't start Portfolio Dashboard",
      `The local data service didn't become ready in time.\n\n${err.message}`,
    );
    app.quit();
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  intentionalQuit = true;
  if (backendProcess) {
    try {
      // On Windows SIGTERM isn't deliverable; use the platform-appropriate kill.
      if (process.platform === "win32") {
        backendProcess.kill();
      } else {
        backendProcess.kill("SIGTERM");
      }
    } catch (e) {
      console.warn("[electron] kill failed:", e);
    }
  }
});

// ---- IPC: native save dialog for Excel export ----
ipcMain.handle("save-xlsx", async (_evt, suggestedName) => {
  const win = BrowserWindow.getFocusedWindow();
  const result = await dialog.showSaveDialog(win, {
    title: "Save portfolio export",
    defaultPath: suggestedName || "portfolio_export.xlsx",
    filters: [{ name: "Excel Workbook", extensions: ["xlsx"] }],
  });
  if (result.canceled || !result.filePath) return null;
  return result.filePath;
});

ipcMain.handle("get-version", () => app.getVersion());
