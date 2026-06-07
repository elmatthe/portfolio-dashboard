/**
 * Playwright E2E for the universal-import mapping editor (Item 4 Step 7).
 *
 * Requires the full app (Electron/Vite dev server + backend) running at
 * localhost:5173 — skipped otherwise, same convention as the other e2e specs.
 *
 * Assumes a reasonably clean active profile: a generic layout that was already
 * confirmed once is remembered and skips the editor by design, so re-running
 * against a profile that has imported this exact fixture before may not re-open
 * the modal. Use a fresh profile for a deterministic run.
 *
 * To run:
 *   cd frontend && npx playwright test tests/e2e/import-mapping.spec.ts
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_URL = 'http://localhost:5173';
const MESSY_CSV = path.resolve(__dirname, '..', '..', '..', 'test_data', 'generic', 'Messy_Generic_2024.csv');

test.describe('Universal import — mapping editor', () => {
  test.beforeEach(async ({ page }) => {
    try {
      await page.goto(APP_URL, { timeout: 5000 });
    } catch {
      test.skip(true, 'App not running at ' + APP_URL);
      return;
    }
    await page.waitForLoadState('domcontentloaded');
  });

  test('generic CSV opens the editor; confirm imports rows', async ({ page }) => {
    // Get to the upload screen (it's the default when a profile has no data;
    // otherwise click an "Import" affordance).
    const dropPrompt = page.getByText(/Drop your transaction export here/i);
    if (!(await dropPrompt.isVisible().catch(() => false))) {
      const importBtn = page.getByRole('button', { name: /import/i }).first();
      if (await importBtn.isVisible().catch(() => false)) {
        await importBtn.click();
      }
    }

    // Feed the messy generic fixture to the hidden dropzone input.
    await page.locator('input[type="file"]').setInputFiles(MESSY_CSV);

    // The mapping editor must open (NOT the one-shot import toast).
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByRole('heading', { name: /Review column mapping/i }),
    ).toBeVisible();

    // At least one override dropdown is present (the mapping table is the first).
    const mappingSelects = dialog.locator('table').first().locator('select');
    await expect(mappingSelects.first()).toBeVisible();
    expect(await mappingSelects.count()).toBeGreaterThan(0);

    // Change one dropdown to a different source column. The Currency row is last;
    // re-pointing it at the Quantity column (option index 4: "— ignore —" + the
    // 7 source columns) evicts only the redundant quantity mapping — buys/sells
    // still satisfy "2 of {quantity, price, net}" via price+amount, so all rows
    // still import.
    const currencySelect = mappingSelects.last();
    const before = await currencySelect.inputValue();
    await currencySelect.selectOption({ index: 4 });
    expect(await currencySelect.inputValue()).not.toBe(before);

    // Confirm → standard import result toast with a POSITIVE inserted count.
    await page.getByRole('button', { name: /Confirm Import/i }).click();
    await expect(
      page.getByText(/[1-9]\d* new transactions added/i),
    ).toBeVisible({ timeout: 20000 });

    // The app is healthy after the import.
    const resp = await page.request.get(`${APP_URL}/api/portfolio`);
    expect(resp.status()).toBe(200);
  });
});
