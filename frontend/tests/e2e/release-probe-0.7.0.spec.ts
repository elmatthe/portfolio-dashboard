/**
 * Packaged-app release probe for 0.7.0 (Item 4 — universal import).
 *
 * Drives the PACKAGED Electron build at release/win-unpacked/ — NOT the dev
 * server — and confirms the shipped installer actually works end-to-end:
 *   - app launches without crash and the renderer (not a blank screen) appears
 *   - the upload zone renders and accepts a file drop
 *   - /api/portfolio returns 200 from inside the packaged app
 *   - the GENERIC import flow works in the real bundle: drop the messy CSV,
 *     the mapping editor opens, confirm, and rows are inserted (> 0)
 *
 * Runs against a freshly-created profile so the header-fingerprint memory from
 * any prior run can't suppress the editor — the editor-opens assertion is then
 * deterministic on every run.
 *
 * To run (after building the installer / win-unpacked):
 *   cd frontend && npx playwright test tests/e2e/release-probe-0.7.0.spec.ts
 */
import { _electron as electron, type ElectronApplication, type Page } from 'playwright';
import { test, expect } from '@playwright/test';
import * as path from 'path';
import { fileURLToPath } from 'url';
import * as fs from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ROOT = path.resolve(__dirname, '..', '..', '..');
const APP_PATH = path.resolve(ROOT, 'release', 'win-unpacked', 'Portfolio Dashboard.exe');
const MESSY_CSV = path.resolve(ROOT, 'test_data', 'generic', 'Messy_Generic_2024.csv');
const SHOT_DIR = path.resolve(ROOT, 'release', 'probe-shots');

if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

let app: ElectronApplication;
let page: Page;
let backendPort = 7842;

test.beforeAll(async () => {
  expect(fs.existsSync(APP_PATH), `packaged app missing at ${APP_PATH}`).toBe(true);

  app = await electron.launch({ executablePath: APP_PATH, timeout: 60_000, env: { ...process.env } });

  // The first window is the splash; the main process destroys it once the
  // React renderer is ready. Wait for the real (non data:) window.
  await app.firstWindow();
  const deadline = Date.now() + 40_000;
  while (Date.now() < deadline) {
    const main = app.windows().find((w) => !w.url().startsWith('data:'));
    if (main) {
      page = main;
      break;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!page) throw new Error('Main window never appeared — app may have crashed on launch');
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2_000);

  backendPort = await page.evaluate(() => (window as any).desktop?.getBackendPort?.() ?? 7842);

  // Fresh profile → no remembered mapping fingerprint → editor is guaranteed to open.
  await page.evaluate(async (port) => {
    const created = await fetch(`http://localhost:${port}/api/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: `Probe 0.7.0 ${Date.now()}`, color: '#10B981' }),
    }).then((r) => r.json());
    await fetch(`http://localhost:${port}/api/profiles/${created.id}/activate`, { method: 'POST' });
  }, backendPort);

  // Reload so the renderer binds to the fresh, empty profile (→ Upload screen).
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2_500);
});

test.afterAll(async () => {
  if (app) await app.close();
});

test('packaged app launches and renders the upload zone', async () => {
  // Not a blank/stuck screen: the renderer painted real content.
  const body = await page.evaluate(() => document.body.innerText || '');
  expect(body.trim().length).toBeGreaterThan(0);

  // Reach the upload screen (default for an empty profile; otherwise click Import).
  const dropPrompt = page.getByText(/Drop your transaction export here/i);
  if (!(await dropPrompt.isVisible().catch(() => false))) {
    const importBtn = page.getByRole('button', { name: /import/i }).first();
    if (await importBtn.isVisible().catch(() => false)) await importBtn.click();
  }
  await expect(page.getByText(/Drop your transaction export here/i)).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('input[type="file"]')).toBeAttached();
  await page.screenshot({ path: path.join(SHOT_DIR, 'release-0.7.0-upload.png'), fullPage: false });
});

test('/api/portfolio returns 200 from the packaged app', async () => {
  const status = await page.evaluate(
    async (port) => (await fetch(`http://localhost:${port}/api/portfolio`)).status,
    backendPort,
  );
  expect(status).toBe(200);
});

test('generic import: editor opens, confirm inserts rows (> 0)', async () => {
  await page.locator('input[type="file"]').setInputFiles(MESSY_CSV);

  // Generic / low-confidence → the mapping editor must open (not a silent import).
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('heading', { name: /Review column mapping/i })).toBeVisible();
  await page.screenshot({ path: path.join(SHOT_DIR, 'release-0.7.0-editor.png'), fullPage: false });

  // Accept the auto-mapping and confirm.
  await page.getByRole('button', { name: /Confirm Import/i }).click();
  await expect(page.getByText(/[1-9]\d* new transactions added/i)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, 'release-0.7.0-imported.png'), fullPage: false });

  // The generic rows are really persisted, tagged broker="generic".
  const generic = await page.evaluate(
    async (port) => (await fetch(`http://localhost:${port}/api/transactions?broker=generic`)).json(),
    backendPort,
  );
  expect(Array.isArray(generic)).toBe(true);
  expect(generic.length).toBeGreaterThan(0);

  // App is still healthy after the generic import.
  const status = await page.evaluate(
    async (port) => (await fetch(`http://localhost:${port}/api/portfolio`)).status,
    backendPort,
  );
  expect(status).toBe(200);
});
