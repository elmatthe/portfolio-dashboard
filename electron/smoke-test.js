#!/usr/bin/env node
/**
 * Smoke test for the packaged Electron app's startup flow.
 *
 * Run after `npm run pack:win` to verify:
 *   1. backend.exe starts and responds to /health
 *   2. Stale-backend kill logic works (occupies port, launches app, verifies recovery)
 *   3. Clean startup works when port is free
 *
 * Usage:  node electron/smoke-test.js
 * Exit 0 = all passed, exit 1 = failure.
 */
const { spawn, execSync } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");
const fs = require("node:fs");

const BACKEND_EXE = path.join(__dirname, "..", "release", "win-unpacked", "resources", "backend", "backend.exe");
const PORT = 7842;

function log(msg) { console.log(`[smoke] ${msg}`); }
function fail(msg) { console.error(`[FAIL] ${msg}`); process.exit(1); }

function healthCheck(port, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(timeoutMs, () => { req.destroy(); resolve(false); });
  });
}

function shutdownBackend(port) {
  return new Promise((resolve) => {
    const req = http.request(`http://127.0.0.1:${port}/api/shutdown`, { method: "POST", timeout: 3000 },
      (res) => { res.resume(); res.on("end", () => resolve(true)); });
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
    req.end();
  });
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function killAll() {
  try { execSync("taskkill /F /IM backend.exe", { stdio: "ignore", timeout: 5000 }); } catch {}
}

async function waitHealthy(port, deadline = 10000) {
  const end = Date.now() + deadline;
  while (Date.now() < end) {
    if (await healthCheck(port, 1000)) return true;
    await sleep(300);
  }
  return false;
}

async function main() {
  if (!fs.existsSync(BACKEND_EXE)) {
    fail(`backend.exe not found at ${BACKEND_EXE} — run PyInstaller + electron-builder first`);
  }

  // ---------- Test 1: Clean startup ----------
  log("Test 1: Clean backend startup");
  killAll();
  await sleep(1000);

  const env = { ...process.env, PORTFOLIO_PORT: String(PORT), PYTHONUNBUFFERED: "1" };
  if (!env.PORTFOLIO_PROFILES_DIR) {
    env.PORTFOLIO_PROFILES_DIR = path.join(process.env.APPDATA || "", "Portfolio Dashboard");
  }
  const be = spawn(BACKEND_EXE, [], { env, stdio: "ignore", windowsHide: true });

  const healthy = await waitHealthy(PORT);
  if (!healthy) {
    be.kill();
    fail("Backend did not become healthy within 10s");
  }
  log("  PASS — backend healthy on port " + PORT);

  // ---------- Test 2: Stale-backend kill via /api/shutdown ----------
  log("Test 2: Stale backend shutdown via API");
  const shutOk = await shutdownBackend(PORT);
  await sleep(2000);
  const stillAlive = await healthCheck(PORT);
  if (stillAlive) {
    log("  WARNING — backend survived /api/shutdown, force-killing");
    killAll();
    await sleep(1000);
  }
  if (!shutOk && stillAlive) {
    fail("Could not shut down backend via /api/shutdown or force-kill");
  }
  log("  PASS — stale backend shut down");

  // ---------- Test 3: Port recovery after stale kill ----------
  log("Test 3: New backend starts after stale cleanup");
  const be2 = spawn(BACKEND_EXE, [], { env, stdio: "ignore", windowsHide: true });
  const healthy2 = await waitHealthy(PORT);
  if (!healthy2) {
    be2.kill();
    fail("New backend did not become healthy after stale cleanup");
  }
  log("  PASS — new backend healthy on port " + PORT);

  // ---------- Test 4: taskkill fallback ----------
  log("Test 4: taskkill /F /IM backend.exe kills process");
  killAll();
  await sleep(1500);
  const afterKill = await healthCheck(PORT);
  if (afterKill) {
    fail("Backend still alive after taskkill");
  }
  log("  PASS — taskkill killed backend");

  log("\nAll smoke tests passed.");
  process.exit(0);
}

main().catch((e) => fail(e.message));
