/**
 * Visual diagnostic probe for the bugs reported against 0.6.3.
 * Drives the packaged Electron build, takes screenshots, and dumps
 * the computed style of representative inputs so we can SEE rather
 * than assume.
 */
import { _electron as electron, type ElectronApplication, type Page } from 'playwright';
import { test, expect } from '@playwright/test';
import * as path from 'path';
import { fileURLToPath } from 'url';
import * as fs from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const APP_PATH = path.resolve(
  __dirname,
  '..', '..', '..',
  'release', 'win-unpacked', 'Portfolio Dashboard.exe',
);
const SHOT_DIR = path.resolve(__dirname, '..', '..', '..', 'release', 'probe-shots');

if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

let app: ElectronApplication;
let page: Page;

test.beforeAll(async () => {
  app = await electron.launch({
    executablePath: APP_PATH,
    timeout: 60_000,
    args: [],
    env: { ...process.env },
  });
  // The first window is the splash, which the main process destroys once the
  // React renderer is ready. Wait for a SECOND window to appear (the dashboard).
  const splash = await app.firstWindow();
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const wins = app.windows();
    const main = wins.find((w) => !w.url().startsWith('data:'));
    if (main) {
      page = main;
      break;
    }
    await splash.waitForTimeout(250).catch(() => {});
  }
  if (!page) throw new Error('Main window never appeared');
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2_000);

  // Resolve the backend port via the preload bridge, then seed test data
  // (mixed CAD + USD holdings + deposits) so the dashboard is reachable.
  const backendPort: number = await page.evaluate(async () => {
    // @ts-ignore — preload-exposed bridge
    return (window as any).desktop?.getBackendPort?.() ?? 7842;
  });
  fs.writeFileSync(path.join(SHOT_DIR, 'backend-port.txt'), `port = ${backendPort}\n`);

  await page.evaluate(async (port) => {
    const post = (body: any) =>
      fetch(`http://localhost:${port}/api/transactions/manual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then((r) => r.json());

    // Two CAD deposits + a CAD buy
    await post({ transaction_date: '2025-01-02', action: 'DEPOSIT', currency: 'CAD',
      account_type: 'TFSA', account_number: 'TEST-TFSA-1', net_amount: 5000 });
    await post({ transaction_date: '2025-01-03', action: 'BUY', ticker: 'VEQT.TO',
      quantity: 100, price: 40.00, currency: 'CAD', commission: 0,
      account_type: 'TFSA', account_number: 'TEST-TFSA-1' });

    // USD deposit + USD buy
    await post({ transaction_date: '2025-02-01', action: 'DEPOSIT', currency: 'USD',
      account_type: 'Margin', account_number: 'TEST-MARGIN-1', net_amount: 2000 });
    await post({ transaction_date: '2025-02-02', action: 'BUY', ticker: 'AAPL',
      quantity: 10, price: 180.00, currency: 'USD', commission: 0,
      account_type: 'Margin', account_number: 'TEST-MARGIN-1' });

    // A CAD dividend so dividends end up in totals
    await post({ transaction_date: '2025-06-15', action: 'DIVIDEND', ticker: 'VEQT.TO',
      currency: 'CAD', account_type: 'TFSA', account_number: 'TEST-TFSA-1', net_amount: 45 });
  }, backendPort);

  // Reload so the React tree re-renders with data
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(4_000);
});

test.afterAll(async () => {
  if (app) await app.close();
});

test('probe: bug 2 — Add Transaction modal styling', async () => {
  // Navigate to Transactions
  const txBtn = page.locator('button', { hasText: 'Transactions' }).first();
  if (await txBtn.isVisible().catch(() => false)) {
    await txBtn.click();
    await page.waitForTimeout(1500);
  }
  // Open the Add Transaction modal
  const addBtn = page.locator('button', { hasText: 'Add Transaction' }).first();
  await addBtn.click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1500);

  await page.screenshot({ path: path.join(SHOT_DIR, 'bug2-add-transaction-modal.png'), fullPage: false });

  // Dump computed style of the inputs in the Add Transaction modal only,
  // plus the matched CSS rules so we can see what's winning the cascade.
  const dump = await page.evaluate(() => {
    const modal = document.querySelector('[role="dialog"]');
    const root = modal || document;
    const inputs = Array.from(root.querySelectorAll('input,select,textarea')) as Array<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>;
    return inputs.map((el) => {
      const cs = window.getComputedStyle(el);
      const ownStyles = el.getAttribute('style');
      return {
        tag: el.tagName,
        type: (el as HTMLInputElement).type || 'select',
        className: el.className,
        inlineStyle: ownStyles,
        bg: cs.backgroundColor,
        color: cs.color,
        borderWidth: cs.borderWidth,
        borderColor: cs.borderColor,
        borderStyle: cs.borderStyle,
        paddingTop: cs.paddingTop,
        paddingBottom: cs.paddingBottom,
        height: cs.height,
        appearance: (cs as any).appearance || (cs as any).webkitAppearance,
      };
    });
  });
  fs.writeFileSync(path.join(SHOT_DIR, 'bug2-input-styles.json'), JSON.stringify(dump, null, 2));

  // Dump all stylesheet URLs and whether each contains .input rule
  const sheetSummary = await page.evaluate(() => {
    const out: any[] = [];
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        const rules = Array.from(sheet.cssRules);
        const hasInput = rules.some((r) => r instanceof CSSStyleRule && r.selectorText === '.input');
        const hasFilter = rules.some((r) => r instanceof CSSStyleRule && r.selectorText === '.filter-input');
        out.push({ href: sheet.href, ruleCount: rules.length, hasInputRule: hasInput, hasFilterInputRule: hasFilter });
      } catch (e) {
        out.push({ href: sheet.href, error: String(e) });
      }
    }
    return out;
  });
  fs.writeFileSync(path.join(SHOT_DIR, 'bug2-stylesheets.json'), JSON.stringify(sheetSummary, null, 2));

  // Also dump all rules matching one input that's in the modal
  const matchedRules = await page.evaluate(() => {
    const modal = document.querySelector('[role="dialog"]');
    const inp = modal?.querySelector('input.input,select.input');
    if (!inp) return null;
    const rules: any[] = [];
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        for (const rule of Array.from(sheet.cssRules)) {
          if (rule instanceof CSSStyleRule) {
            try {
              if (inp.matches(rule.selectorText)) {
                rules.push({ selector: rule.selectorText, cssText: rule.style.cssText });
              }
            } catch {}
          }
        }
      } catch {}
    }
    return { tag: inp.tagName, className: inp.className, rules };
  });
  fs.writeFileSync(path.join(SHOT_DIR, 'bug2-matched-rules.json'), JSON.stringify(matchedRules, null, 2));
});

test('probe: bug 1 — per-view Period Return values', async () => {
  // Close any open modal first
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(300);
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(300);

  // Get the backend port from preload
  const port: number = await page.evaluate(async () => {
    return (window as any).desktop?.getBackendPort?.() ?? 7842;
  });

  // Hit /api/portfolio?period=all directly so we get the same shape the
  // dashboard sees, then compute Total P&L per view the same way the
  // frontend does. Assert per-view Period Return == Total P&L.
  const reportAll = await page.evaluate(async (port) => {
    const r = await fetch(`http://localhost:${port}/api/portfolio?period=all`);
    return r.json();
  }, port);
  const report3y = await page.evaluate(async (port) => {
    const r = await fetch(`http://localhost:${port}/api/portfolio?period=3y`);
    return r.json();
  }, port);

  const summarize = (data: any) => {
    const c = data.combined;
    const fx = data.exchange_rate;
    const usdToCad = fx.usd_cad || 1;
    const cadToUsd = fx.cad_usd || 1 / usdToCad;
    const pnl = {
      combined_cad: (c.total_equity_cad + c.total_equity_usd * usdToCad) - (c.cash_deposited_cad + c.cash_deposited_usd * usdToCad),
      combined_usd: (c.total_equity_usd + c.total_equity_cad * cadToUsd) - (c.cash_deposited_usd + c.cash_deposited_cad * cadToUsd),
      cad_only: c.total_equity_cad - c.cash_deposited_cad,
      usd_only: c.total_equity_usd - c.cash_deposited_usd,
    };
    const pr = {
      combined_cad: c.period_return_combined_cad,
      combined_usd: c.period_return_combined_usd,
      cad_only: c.period_return_cad_only,
      usd_only: c.period_return_usd_only,
    };
    const deltas = {
      combined_cad: Math.abs(pr.combined_cad - pnl.combined_cad),
      combined_usd: Math.abs(pr.combined_usd - pnl.combined_usd),
      cad_only: Math.abs(pr.cad_only - pnl.cad_only),
      usd_only: Math.abs(pr.usd_only - pnl.usd_only),
    };
    return {
      period: data.period,
      period_clamped: data.period_clamped,
      total_pnl: pnl,
      period_return: pr,
      delta_pr_vs_pnl: deltas,
      views_all_identical:
        Math.abs(pr.combined_cad - pr.cad_only) < 0.01 &&
        Math.abs(pr.combined_cad - pr.usd_only) < 0.01 &&
        Math.abs(pr.combined_cad - pr.combined_usd) < 0.01,
    };
  };

  const probe = {
    seed_summary: 'Mixed CAD + USD: TFSA 100×VEQT.TO @ $40, $45 dividend; Margin 10×AAPL USD @ $180; $5000 CAD + $2000 USD deposits',
    all: summarize(reportAll),
    threeY: summarize(report3y),
  };
  fs.writeFileSync(path.join(SHOT_DIR, 'bug1-per-view.json'), JSON.stringify(probe, null, 2));

  // Also screenshot the dashboard with the Combined card visible
  const dashBtn = page.locator('button', { hasText: 'Dashboard' }).first();
  if (await dashBtn.isVisible().catch(() => false)) {
    await dashBtn.click();
    await page.waitForTimeout(1500);
  }
  await page.screenshot({ path: path.join(SHOT_DIR, 'bug1-dashboard-combined-cad.png'), fullPage: false });

  // Click each currency-view button and screenshot
  for (const label of ['Combined in USD', 'CAD only', 'USD only']) {
    const btn = page.locator('button', { hasText: label }).first();
    if (await btn.isVisible().catch(() => false)) {
      await btn.click();
      await page.waitForTimeout(800);
      await page.screenshot({
        path: path.join(SHOT_DIR, `bug1-dashboard-${label.toLowerCase().replace(/\s+/g, '-')}.png`),
        fullPage: false,
      });
    }
  }
});

test('probe: bug 4 — Factory reset dialog', async () => {
  // Close any open modal first
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);

  // Open Settings (gear icon in SyncStatus)
  const settingsBtn = page.locator('button[title="Settings"]').first();
  if (await settingsBtn.isVisible().catch(() => false)) {
    await settingsBtn.click();
    await page.waitForTimeout(1500);
  }
  await page.screenshot({ path: path.join(SHOT_DIR, 'bug4-settings-open.png'), fullPage: true });

  // Scroll to the Data section and find the "Reset app to factory state" button
  const resetBtn = page.locator('button', { hasText: 'Reset app to factory state' }).first();
  const exists = await resetBtn.isVisible().catch(() => false);
  if (exists) {
    await resetBtn.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(SHOT_DIR, 'bug4-reset-button.png'), fullPage: false });

    await resetBtn.click();
    await page.waitForTimeout(1500);

    await page.screenshot({ path: path.join(SHOT_DIR, 'bug4-after-click.png'), fullPage: false });

    // Did a dialog with "Type RESET to confirm" appear?
    const confirmInput = page.locator('input[placeholder="RESET"]');
    const dialogAppeared = await confirmInput.isVisible().catch(() => false);
    fs.writeFileSync(
      path.join(SHOT_DIR, 'bug4-dialog-appeared.txt'),
      `dialog appeared after click: ${dialogAppeared}`,
    );

    if (!dialogAppeared) return;

    // Drive the reset to completion: type RESET, click confirm, then verify
    // that /api/transactions returns [] (data is gone).
    const portForReset: number = await page.evaluate(() =>
      (window as any).desktop?.getBackendPort?.() ?? 7842,
    );
    const txsBefore = await page.evaluate(async (port) =>
      (await fetch(`http://localhost:${port}/api/transactions`)).json(),
      portForReset,
    );
    fs.writeFileSync(
      path.join(SHOT_DIR, 'bug4-tx-count-before.txt'),
      `transactions before reset: ${Array.isArray(txsBefore) ? txsBefore.length : 'error'}`,
    );

    await confirmInput.fill('RESET');
    await page.waitForTimeout(300);
    // Scope to the type-to-confirm dialog (NOT the trigger button behind it).
    // The trigger's text is "Reset app to factory state"; the confirm button
    // in the dialog reads "Reset app" or "Resetting…".
    const dialog = page.locator('[role="dialog"][aria-labelledby="factory-reset-title"]');
    const confirmBtn = dialog.locator('button', { hasText: /(Reset app|Resetting)/ });
    await confirmBtn.click();
    // The handler calls window.location.reload() on success, so the page will
    // re-navigate. Wait for the new load, then re-acquire the main window.
    await page.waitForTimeout(5000);

    const wins = app.windows();
    const newMain = wins.find((w) => !w.url().startsWith('data:'));
    if (newMain) page = newMain;
    await page.waitForLoadState('domcontentloaded').catch(() => {});
    await page.waitForTimeout(2000);

    const txsAfter = await page.evaluate(async (port) =>
      (await fetch(`http://localhost:${port}/api/transactions`)).json(),
      portForReset,
    ).catch(() => null);
    fs.writeFileSync(
      path.join(SHOT_DIR, 'bug4-tx-count-after.txt'),
      `transactions after reset: ${Array.isArray(txsAfter) ? txsAfter.length : 'unreachable/' + String(txsAfter)}`,
    );

    await page.screenshot({ path: path.join(SHOT_DIR, 'bug4-after-reset.png'), fullPage: false });
  } else {
    fs.writeFileSync(
      path.join(SHOT_DIR, 'bug4-no-reset-button.txt'),
      'Reset button NOT found — likely Settings not open or label changed',
    );
  }
});
