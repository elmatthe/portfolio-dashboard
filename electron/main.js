// Electron main process.
// Boots the bundled Python backend, waits for it to become healthy, then opens
// the BrowserWindow loading the bundled React frontend. A small splash window
// shows immediately so the user sees activity during the 1-3s backend startup.
// On quit, SIGTERMs the backend and waits for it to exit cleanly.
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const net = require("node:net");
const { spawn } = require("node:child_process");
const http = require("node:http");
const windowStateKeeper = require("electron-window-state");

const PREFERRED_BACKEND_PORT = 7842;
// Backend port is resolved at startup via `findFreePort` — if 7842 is busy
// (another instance, dev server, etc.) we fall back to an OS-assigned port
// and pass it to the backend via the PORTFOLIO_PORT env var.
let BACKEND_PORT = PREFERRED_BACKEND_PORT;
const HEALTH_TIMEOUT_MS = 30_000;
const HEALTH_POLL_MS = 200;

function healthUrl(port) {
  return `http://127.0.0.1:${port || BACKEND_PORT}/health`;
}

function findFreePort(preferred) {
  // Try the preferred port first; if it's in use, ask the OS for any free one.
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.on("error", () => {
      const fallback = net.createServer();
      fallback.unref();
      fallback.listen(0, "127.0.0.1", () => {
        const addr = fallback.address();
        const port = addr && typeof addr === "object" ? addr.port : preferred;
        fallback.close(() => resolve(port));
      });
    });
    server.listen(preferred, "127.0.0.1", () => {
      server.close(() => resolve(preferred));
    });
  });
}

/**
 * Check if a port has a live backend that responds to /health.
 * Resolves true if healthy, false otherwise. Never rejects.
 */
function isPortHealthy(port) {
  return new Promise((resolve) => {
    const req = http.get(healthUrl(port), (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(2000, () => { req.destroy(); resolve(false); });
  });
}

/**
 * Attempt to gracefully shut down a backend on `port` via POST /api/shutdown.
 * If that fails, fall back to `taskkill` on Windows to kill backend.exe
 * processes listening on that port.
 */
async function killStaleBackend(port) {
  console.log(`[electron] Attempting to shut down stale backend on port ${port}`);
  // Try the graceful shutdown endpoint first.
  const shutdownOk = await new Promise((resolve) => {
    const req = http.request(
      `http://127.0.0.1:${port}/api/shutdown`,
      { method: "POST", timeout: 3000 },
      (res) => { res.resume(); res.on("end", () => resolve(true)); },
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
    req.end();
  });
  if (shutdownOk) {
    // Give it a moment to exit.
    await new Promise((r) => setTimeout(r, 1500));
    const stillAlive = await isPortHealthy(port);
    if (!stillAlive) {
      console.log("[electron] Stale backend shut down gracefully");
      return;
    }
  }
  // Graceful shutdown failed — force-kill on Windows.
  if (process.platform === "win32") {
    console.log("[electron] Graceful shutdown failed, trying taskkill");
    const { execSync } = require("node:child_process");
    try {
      execSync("taskkill /F /IM backend.exe", { stdio: "ignore", timeout: 5000 });
      await new Promise((r) => setTimeout(r, 500));
      console.log("[electron] taskkill backend.exe completed");
    } catch (e) {
      console.warn("[electron] taskkill failed (may not have been running):", e.message);
    }
  }
}

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
    PORTFOLIO_PORT: String(BACKEND_PORT),
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
      const req = http.get(healthUrl(), (res) => {
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
    height: 280,
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
  .sub{color:#6B7280;font-size:13px;margin-bottom:24px;transition:color .3s;}
  .bar{width:220px;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;position:relative;}
  .bar::after{content:"";position:absolute;left:-40%;top:0;bottom:0;width:40%;background:#3B82F6;
    border-radius:2px;animation:slide 1.2s ease-in-out infinite;}
  @keyframes slide{0%{left:-40%}100%{left:100%}}
  .err{color:#EF4444;}
</style></head>
<body><div class="wrap">
  <div class="title">Portfolio Dashboard</div>
  <div class="sub" id="status">Starting local data service…</div>
  <div class="bar" id="bar"></div>
</div>
<script>
  const el=document.getElementById('status');
  const bar=document.getElementById('bar');
  const start=Date.now();
  const timer=setInterval(()=>{
    const elapsed=Math.round((Date.now()-start)/1000);
    if(elapsed>=25){
      el.textContent='Still waiting… this is taking longer than expected.';
      el.classList.add('err');
    } else if(elapsed>=10){
      el.textContent='Starting local data service… ('+elapsed+'s)';
    }
  },1000);
</script>
</body></html>`;
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
    // Only forward http(s) URLs to the user's default browser. Refuse anything
    // else (file://, custom schemes, javascript:, data:) so a malicious / typo
    // URL from the renderer can't be passed to `shell.openExternal`.
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "https:" || parsed.protocol === "http:") {
        shell.openExternal(url);
      } else {
        console.warn(`[electron] Refusing to openExternal for non-http(s) URL: ${url}`);
      }
    } catch (e) {
      console.warn(`[electron] Invalid URL passed to openExternal: ${url}`);
    }
    return { action: "deny" };
  });
}

app.whenReady().then(async () => {
  try {
    createSplash();

    // Check if a stale backend is already running on the preferred port.
    // This happens when the previous Electron process was force-killed
    // (Task Manager, crash) and didn't get a chance to shut down its backend.
    const staleAlive = await isPortHealthy(PREFERRED_BACKEND_PORT);
    if (staleAlive) {
      console.log(`[electron] Stale backend detected on port ${PREFERRED_BACKEND_PORT} — killing it`);
      await killStaleBackend(PREFERRED_BACKEND_PORT);
      // Brief pause for the port to be released by the OS.
      await new Promise((r) => setTimeout(r, 500));
    }

    BACKEND_PORT = await findFreePort(PREFERRED_BACKEND_PORT);
    console.log(`[electron] Backend port resolved to ${BACKEND_PORT}`);
    startBackend();
    await waitForBackend();
    await createWindow();
  } catch (err) {
    console.error("[electron] Failed to start:", err);
    closeSplash();
    const tail = stderrTail.slice(-8).join("\n") || "(no backend output captured)";
    const result = dialog.showMessageBoxSync({
      type: "error",
      title: "Couldn't start Portfolio Dashboard",
      message: "The local data service failed to start.",
      detail:
        `${err.message}\n\n` +
        `Last backend output:\n${tail}\n\n` +
        `Log file: ${backendLogPath()}`,
      buttons: ["Retry", "Quit"],
      defaultId: 0,
    });
    if (result === 0) {
      app.relaunch();
    }
    app.quit();
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Track whether the graceful shutdown handshake has already finished so the
// before-quit handler doesn't re-enter the async flow on every quit attempt.
let shutdownInitiated = false;

app.on("before-quit", (event) => {
  intentionalQuit = true;
  if (!backendProcess || shutdownInitiated) return;
  shutdownInitiated = true;
  event.preventDefault();

  // Step 1: ask FastAPI to checkpoint the SQLite WAL and stop itself. This is
  // critical on Windows where the raw kill() below is TerminateProcess — without
  // a graceful path the WAL accumulates uncheckpointed pages (we observed
  // 4.5 MB -wal files in the wild before this fix).
  const SHUTDOWN_URL = `http://127.0.0.1:${BACKEND_PORT}/api/shutdown`;
  // (Uses BACKEND_PORT resolved at app start — could be 7842 or an OS-assigned fallback.)
  const HANDSHAKE_TIMEOUT_MS = 4_000;

  const finishQuit = () => {
    if (backendProcess) {
      try {
        if (process.platform === "win32") {
          backendProcess.kill();
        } else {
          backendProcess.kill("SIGTERM");
        }
      } catch (e) {
        console.warn("[electron] kill failed:", e);
      }
    }
    app.quit();
  };

  try {
    const req = http.request(
      SHUTDOWN_URL,
      { method: "POST", timeout: HANDSHAKE_TIMEOUT_MS },
      (res) => {
        res.resume();
        res.on("end", finishQuit);
      },
    );
    req.on("error", finishQuit);
    req.on("timeout", () => {
      req.destroy();
      finishQuit();
    });
    req.end();
  } catch (e) {
    console.warn("[electron] shutdown handshake threw:", e);
    finishQuit();
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

ipcMain.handle("get-backend-port", () => BACKEND_PORT);
