# MASTER DEBUG AND TEST RUN
**Portfolio Dashboard — Full-Stack Automated QA Framework**

> **HOW THIS FILE WORKS**
>
> This file lives at `markdown-instructions/MASTER_DEBUG_AND_TEST_RUN.md`.
>
> **Claude Code must ask the user the following question every time a new versioned build
> (e.g. a new `.exe` or installer) is produced:**
>
> ```
> A new build has been packaged. Run the Master Debug and Test Run?
> This will execute the full QA suite across backend, calculations, UI, modals,
> imports, and data fetching, then write a timestamped log to
> markdown-instructions/build_version_test_logs/.
> Estimated time: 5–10 minutes.
>
> Run now? (yes / no / ask me later)
> ```
>
> - If the user answers **yes**: execute every section of this file top to bottom, then
>   write the log file as specified in the "Log File Output" section.
> - If the user answers **no** or **ask me later**: skip the run, but add a one-line
>   entry to the log directory: `SKIPPED_<version>_<timestamp>.txt` containing
>   `"Master Debug Run skipped by user for build <version> at <timestamp>."` so there
>   is an audit trail.
>
> **Claude Code must never skip this prompt after a build.** It is not optional.
> It also must never silently mark tests as passed without actually running them.
> "pytest is green" is not enough — UI tests must run in the Electron renderer.

---

## Setup — Test Infrastructure (run once, then skip if already installed)

Before the first test run on a fresh clone, confirm the following are in place.
If any are missing, install them and commit the changes before proceeding.

### Playwright for Electron UI Testing

The UI tests in this file use **Playwright** with the Electron integration.
This is the only supported way to automate the Electron renderer in this project.

```bash
# From the frontend/ directory:
npm install --save-dev @playwright/test playwright
npx playwright install
```

Add a `playwright.config.ts` in `frontend/` if one doesn't exist:

```typescript
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  use: {
    // Electron-specific launch is handled per-test via _electron.launch()
  },
});
```

Create `frontend/tests/e2e/` if it doesn't exist. All Playwright tests live there.

The Electron app is launched in each test file with:

```typescript
import { _electron as electron } from 'playwright';
import { test, expect } from '@playwright/test';

test.beforeAll(async () => {
  // Launch the built app (or dev mode with 'npm run electron:dev')
  app = await electron.launch({ args: ['electron/main.js'] });
  page = await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');
});
```

### Backend Test Dependencies

Confirm `requirements.txt` or `pyproject.toml` includes:

```
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=4.0.0
```

### Test Data Files

Confirm the following test fixture files exist in `test_data/`. If any are missing,
Claude Code must generate synthetic versions that match the real broker format exactly
(correct headers, correct column types, realistic but fake values — no real account numbers).

Required fixtures:
```
test_data/csv/Questrade_2024.csv
test_data/csv/Wealthsimple_2024.csv
test_data/csv/RBC_DirectInvesting_2024.csv
test_data/csv/CIBC_InvestorsEdge_2024.csv
test_data/csv/TD_DirectInvesting_2024.csv
test_data/csv/InteractiveBrokers_2024.csv
test_data/csv/NationalBank_2024.csv
test_data/csv/Fidelity_2024.csv
test_data/xlsx/BMO_InvestorLine_2024.xlsx
test_data/xlsx/Scotia_iTrade_2024.xlsx
test_data/xlsx/HSBC_InvestDirect_2024.xlsx
test_data/pdf/RBC_DirectInvesting_2024.pdf
test_data/pdf/TD_DirectInvesting_2024.pdf
test_data/pdf/CIBC_InvestorsEdge_2024.pdf
test_data/manual_entry_fixture.json   ← synthetic manual entries for Phase 2 tests
```

---

## Log File Output Specification

After every test run, write a log file to:

```
markdown-instructions/build_version_test_logs/v<VERSION>_<YYYYMMDD_HHMMSS>_testlog.txt
```

Example filename: `v0.5.4_20260525_143022_testlog.txt`

### Log File Format

```
========================================================
PORTFOLIO DASHBOARD — MASTER DEBUG AND TEST RUN
Build Version : <VERSION>
Run Timestamp : <YYYY-MM-DD HH:MM:SS>
Run Duration  : <X min Y sec>
Total Tests   : <N>
Passed        : <N>
Failed        : <N>
Skipped       : <N>
========================================================

SECTION 1 — BACKEND UNIT TESTS
  [✓] pytest: all existing tests pass (N passing, 0 failures, 0 errors)
  [✓] Wealthsimple regression test green
  [✓] Questrade regression test green
  [✗] <test name> — NOTE: <description of failure, traceback summary>

SECTION 2 — TYPESCRIPT COMPILATION
  [✓] npx tsc --noEmit: 0 errors

... (one entry per test as listed below)

========================================================
SUMMARY
  All tests passed. Build <VERSION> is clean.
  — OR —
  <N> test(s) failed. See FAILED items above. Do NOT release this build.
========================================================
```

Status symbols:
- `[✓]` — test passed
- `[✗]` — test failed — always followed by `NOTE:` explaining what failed and why
- `[~]` — test skipped with reason (e.g. network unavailable, test data missing)
- `[!]` — test produced a warning but did not fail (non-blocking)

---

## SECTION 0 — Crash Recovery & Reset

Verify that the app can never be permanently bricked by bad data.

### 0-A: Portfolio endpoint never returns unhandled 500
```
[  ] Import all test fixtures → GET /api/portfolio returns 200
[  ] Import file with malformed dates → valid rows only imported, summary shown
[  ] Inject bad date into price_history table → portfolio still returns 200
[  ] GET /api/portfolio with every period (1m/3m/6m/ytd/1y/3y/all) returns 200
```

### 0-B: Import validation
```
[  ] CSV with NaN quantity → row skipped, toast shows warning
[  ] CSV with Inf price → row skipped, count reflects only valid rows
[  ] Fully-malformed file → 400 with clear "No valid rows" message
[  ] Mixed valid/invalid rows → only valid rows inserted, dashboard loads
```

### 0-C: Error screen has recovery actions
```
[  ] Simulate portfolio load failure → error screen appears
[  ] Error screen shows Retry button → clicking it re-fetches
[  ] Error screen shows Open Settings → opens Settings overlay
[  ] Error screen shows Reset App Data → triggers factory reset
```

### 0-D: Factory reset
```
[  ] Settings → Data → "Reset app to factory state" visible
[  ] Type-to-confirm gate blocks accidental reset
[  ] After reset: all profiles gone, single new default profile exists
[  ] After reset: /api/transactions returns []
[  ] After reset: /api/import/status returns has_data: false
[  ] After reset: portfolio returns 200 (empty state)
```

### 0-E: Corrupt DB detection
```
[  ] /health endpoint returns db_corrupt: false on healthy DB
[  ] Frontend loads normally when DB is healthy
[  ] Manual recovery: deleting %APPDATA%/Portfolio Dashboard recovers app
```

### 0-F: Tests
```
[  ] pytest backend/tests/test_crash_recovery.py — all 15 tests pass
[  ] Full pytest suite — 118 tests pass, 0 failures
```

---

## SECTION 11b — Multi-Currency FX

Verify FX conversion across GBP, EUR, JPY, AUD, CHF using the HSBC fixture.

### Static fallback rates
```
[  ] CAD = 1.0 (identity)
[  ] USD rate in [1.30, 1.45]
[  ] GBP rate in [1.60, 1.85]
[  ] EUR rate in [1.40, 1.60]
[  ] JPY rate in [0.005, 0.015] (very small — large nominal amounts)
[  ] AUD rate in [0.80, 1.00]
[  ] CHF rate in [1.40, 1.60]
[  ] HKD, SEK, NOK have non-zero rates
```

### FX on parsed HSBC rows
```
[  ] Every row has non-null fx_rate_to_cad
[  ] Foreign-currency rows have fx_rate != 1.0
[  ] net_cad ≈ net_amount × fx_rate (within 1% — broker rounding accepted)
```

### JPY edge cases
```
[  ] JPY buy (¥325,000) converts to reasonable CAD (~$2,957)
[  ] JPY dividend (¥7,000) converts to reasonable CAD (~$63)
[  ] No overflow or precision loss on large JPY nominal amounts
```

### Foreign sell → CAD gain
```
[  ] GBP sell → positive CAD proceeds
[  ] USD sell → positive CAD proceeds
[  ] JPY sell → positive CAD proceeds
```

### Dashboard with mixed currencies
```
[  ] GET /api/portfolio returns 200 after HSBC import
[  ] Transactions include all 7 currencies (CAD, USD, GBP, EUR, JPY, AUD, CHF)
[  ] Combined totals non-zero
[  ] All period filters (1m/3m/6m/ytd/1y/all) return 200
```

### Dashboard currency view behavior (document, do not fix)
```
[  ] Combined CAD: foreign holdings converted at live/static rate
[  ] Combined USD: foreign holdings converted at CAD→USD rate
[  ] CAD only: shows only CAD-denominated holdings
[  ] USD only: shows only USD-denominated holdings
[  ] NOTE: holdings in GBP/EUR/JPY/AUD/CHF show under Combined views but
      are excluded from CAD-only and USD-only views (by design — those views
      filter by native currency, not converted currency)
```

---

## SECTION 1 — Backend Unit Tests

Run the full pytest suite and record each result.

```bash
cd backend/
pytest tests/ -v --tb=short 2>&1
```

Tests to record individually (at minimum):

```
[  ] pytest full suite — 0 failures, 0 errors (record exact passing count)
[  ] test_wealthsimple_regression — WS parser output unchanged
[  ] test_questrade_regression — QT parser output unchanged
[  ] test_rbc_csv_row_count — correct row count
[  ] test_cibc_csv_row_count
[  ] test_td_csv_row_count
[  ] test_ib_csv_signed_quantity — negative qty → buy, positive → sell
[  ] test_national_bank_csv
[  ] test_fidelity_zero_commission — all rows have commission == 0.00
[  ] test_bmo_xlsx_skips_title_rows — merged header rows handled
[  ] test_scotia_xlsx
[  ] test_hsbc_isin_captured — at least one ISIN captured
[  ] test_pdf_rbc_row_count — 40 rows
[  ] test_pdf_td_row_count — 35 rows
[  ] test_pdf_cibc_row_count — 33 rows
[  ] test_fx_population — fx_rate_to_cad non-null on all parsed rows
[  ] test_net_cad_non_null — net_cad non-null on all parsed rows
[  ] test_dedup_reimport — re-importing same file inserts 0 new rows
[  ] test_acb_walk_order — ACB walk produces correct result in chronological order
[  ] test_acb_superficial_loss — 30-day window correctly denies loss
[  ] test_modified_dietz_period_return — returns match known-good fixture
[  ] test_period_clamping — period_clamped=True and period_start_date correct
[  ] test_combined_roi_not_zero — combined ROI recalculated, not zero
[  ] test_tfsa_cad_only_metrics_non_null — net_deposits/pnl/ror all non-null in cad_only mode
[  ] test_parser_registry_integrity — all registered parsers return valid Transaction lists
[  ] test_manual_entry_insert — manual row stored with broker="Manual"
[  ] test_manual_entry_fx_at_trade_date — fx_rate_to_cad uses trade date, not today
[  ] test_manual_entry_dedup — manual entry matching an import is caught by SHA-256 dedup
[  ] test_manual_entry_edit — editing a manual entry updates FX and ACB correctly
[  ] test_manual_entry_delete_unwind — deleting a manual sell unwinds RealizedGain
[  ] test_manual_entry_oversell_blocked — sell > held qty returns error, no row inserted
[  ] test_manual_dividend_classification — manual dividend with ticker → DIVIDEND action
[  ] test_manual_deposit_classification — manual deposit, no ticker → DEPOSIT action
```

---

## SECTION 2 — TypeScript Compilation

```bash
cd frontend/
npx tsc --noEmit 2>&1
```

```
[  ] TypeScript compilation — 0 errors
```

If there are errors, list each file + line + message individually in the log.

---

## SECTION 3 — App Launch and Basic Renderer Health

Launch the Electron app and verify it comes up without crashing.

```typescript
// Playwright test: app_launch.spec.ts
app = await electron.launch({ args: ['electron/main.js'] });
page = await app.firstWindow();
await page.waitForLoadState('domcontentloaded');
```

```
[  ] App launches without crash or uncaught exception in main process
[  ] Renderer window opens (not blank / not white screen)
[  ] No console errors on initial load (log any that appear)
[  ] Backend connection established — /api/health or equivalent returns 200
[  ] Dashboard content renders (holdings cards OR empty state visible, not a spinner stuck forever)
[  ] Navigation bar renders with all expected section links/buttons visible
[  ] App title / version number visible in banner matches the built version
```

---

## SECTION 4 — Modal Positioning and Behavior

This section tests the class of bugs that existed before v0.5.2/v0.5.3. Every modal must open as a centered full-viewport overlay, not squished into the header bar.

For each modal below, the test must:
1. Click the trigger button
2. Assert the modal's bounding box top > 50px from the viewport top (i.e. it is NOT pinned in the header)
3. Assert the modal is horizontally centered (left + width/2 ≈ viewport width/2, within 20px)
4. Assert the modal is fully visible (no clipping)
5. Press Escape and assert the modal closes
6. Reopen and click the backdrop and assert the modal closes
7. Assert ARIA attributes: `role="dialog"`, `aria-modal="true"`, `aria-labelledby` present

```
[  ] Settings panel — opens centered, not in header
[  ] Settings panel — closes on Escape
[  ] Settings panel — closes on backdrop click
[  ] Settings panel — ARIA attributes present
[  ] Reports panel — opens centered, not in header
[  ] Reports panel — closes on Escape
[  ] Reports panel — closes on backdrop click
[  ] Simulator (What-If) panel — opens centered, not in header
[  ] Simulator panel — closes on Escape
[  ] Simulator panel — closes on backdrop click
[  ] Alerts panel — opens centered, not in header
[  ] Alerts panel — closes on Escape
[  ] Alerts panel — closes on backdrop click
[  ] Create New Profile modal — opens centered, not in header
[  ] Create New Profile modal — title reads "Create New Profile" (not "New profile")
[  ] Create New Profile modal — closes on Escape
[  ] Create New Profile modal — closes on backdrop click
[  ] Create New Profile modal — ARIA attributes present
[  ] Add Transaction modal (Phase 2) — opens centered, not in header
[  ] Add Transaction modal — closes on Escape
[  ] Add Transaction modal — closes on backdrop click
[  ] Add Transaction modal — ARIA attributes present
```

---

## SECTION 5 — Profile Management

```
[  ] Profile switcher pill visible in banner
[  ] Clicking profile pill opens dropdown
[  ] Dropdown lists at least one profile ("My Portfolio" or user-created)
[  ] Can create a new profile — form opens, enter name, save, profile appears in list
[  ] Switching profiles hot-swaps data without app restart (banner updates, dashboard reloads)
[  ] Each profile's accent color applies to the UI via CSS variable
[  ] Profile rename works inline in the dropdown
[  ] Deleting a profile (if supported) prompts confirmation
[  ] Switching back to original profile restores original data
```

---

## SECTION 6 — File Import (Upload Flow)

Test each supported broker format. For each, verify: correct detection, confidence display, 5-row preview table, successful import, no duplicates on re-import.

```
[  ] Upload UI accepts .csv files
[  ] Upload UI accepts .xlsx files
[  ] Upload UI accepts .xls files
[  ] Upload UI accepts .pdf files
[  ] Upload UI accepts .tsv files
[  ] Upload UI rejects unsupported formats (.docx, .png, etc.) with a clear error message
[  ] Questrade CSV — detected as "Questrade" with confidence ≥ 80%
[  ] Questrade CSV — 5-row preview table renders with correct column names
[  ] Questrade CSV — import succeeds, rows appear in the app
[  ] Questrade CSV — re-import of same file inserts 0 new rows (dedup confirmed)
[  ] Wealthsimple CSV — detected as "Wealthsimple" with confidence ≥ 80%
[  ] Wealthsimple CSV — import succeeds
[  ] Wealthsimple CSV — re-import = 0 new rows
[  ] RBC CSV — detected correctly
[  ] RBC CSV — import succeeds
[  ] CIBC CSV — detected correctly
[  ] CIBC CSV — import succeeds
[  ] TD CSV — detected correctly
[  ] TD CSV — import succeeds
[  ] Interactive Brokers CSV — detected correctly (signed quantity format)
[  ] Interactive Brokers CSV — import succeeds
[  ] National Bank CSV — detected correctly
[  ] National Bank CSV — import succeeds
[  ] Fidelity CSV — detected correctly, all rows have commission = 0.00
[  ] Fidelity CSV — import succeeds
[  ] BMO XLSX — detected correctly, merged title rows (rows 1-3) skipped
[  ] BMO XLSX — import succeeds
[  ] Scotia XLSX — detected correctly
[  ] Scotia XLSX — import succeeds
[  ] HSBC XLSX — detected correctly, at least one ISIN captured
[  ] HSBC XLSX — import succeeds
[  ] RBC PDF — detected correctly, 40 rows extracted
[  ] RBC PDF — import succeeds
[  ] TD PDF — detected correctly, 35 rows extracted
[  ] TD PDF — import succeeds
[  ] CIBC PDF — detected correctly, 33 rows extracted
[  ] CIBC PDF — import succeeds
[  ] Low-confidence file (< 50%) — broker selector dropdown is shown
[  ] FX rate to CAD is non-null on every imported row
[  ] net_cad is non-null on every imported row
```

---

## SECTION 7 — Dashboard Views and Navigation

```
[  ] Dashboard loads and renders holdings cards (or empty state if no data)
[  ] Holdings cards show: ticker, market value, ROI %, ACB/share, sparkline, exchange + currency badge
[  ] Per-account tabs render (TFSA / Margin / RRSP / RESP / Non-Reg) for each imported account
[  ] Combined tab renders and aggregates all accounts
[  ] Currency view toggle renders: Combined CAD / Combined USD / CAD-only / USD-only
[  ] Combined CAD view — total equity shows correct CAD value
[  ] Combined USD view — total equity shows correct USD value
[  ] CAD-only view — shows only CAD holdings; TFSA with all-CAD holdings shows real numbers (not "—")
[  ] USD-only view — shows only USD holdings
[  ] Switching between currency modes updates all displayed values immediately (no stale data)
[  ] Period return chips render: 1M / 3M / 6M / 1Y / 3Y / All
[  ] Period return shows correct Modified-Dietz percentage (not 0% or "—")
[  ] When window is clamped, chip shows "Since MMM YYYY" (not "3Y" etc.)
[  ] Net Deposits, Total P&L, and Simple ROR all display non-null values in every currency mode
[  ] Combined ROI is non-zero when holdings exist with gains/losses
[  ] Broker breakdown pie chart renders and includes all imported brokers
[  ] Account-type breakdown renders (TFSA / Margin / RRSP / etc.)
[  ] Currency Exposure widget renders as horizontal bar chart
[  ] "View in:" currency selector changes all monetary values
[  ] S&P 500 benchmark overlay checkbox is present on Historical Chart
[  ] S&P 500 overlay renders as dashed grey line when enabled
[  ] Portfolio Value Over Time chart renders (solid line + dashed deposits line)
[  ] Performance Attribution chart renders
[  ] Correlation Matrix renders (heatmap, not blank)
[  ] Light/dark mode toggle button is visible in banner
[  ] Toggling light/dark mode changes the theme and persists across a refresh
```

---

## SECTION 8 — Transactions Page (Phase 1)

```
[  ] "Transactions" section is reachable from the navigation
[  ] Transactions page renders under its own route (deep-link works)
[  ] Each imported broker appears as a distinct source group (Questrade ≠ Wealthsimple ≠ RBC etc.)
[  ] Manual source group is present (even if empty — shows "No manual transactions entered yet")
[  ] Each source group shows a correct transaction count
[  ] Transaction rows show correct: date, ticker, action, quantity, price, local currency, local amount, FX rate, CAD equivalent, account type, settlement date
[  ] Toggleable columns work (Local Currency, Local Amount, FX Rate, CAD Equivalent, ISIN, Account Type, Settlement Date)
[  ] Filter by broker/source works
[  ] Filter by account type works
[  ] Filter by currency works
[  ] Filter by action (buy/sell/dividend/transfer/fee) works
[  ] Filter by date range (default: current year) works
[  ] Text search on ticker + security name works
[  ] Sort by date works (ascending and descending)
[  ] Sort by amount works
[  ] Clicking a row (or source group) drills into detail view
[  ] Empty state per source renders correctly ("No Questrade transactions imported yet")
[  ] Re-importing a file produces no duplicate rows in the Transactions page
```

---

## SECTION 9 — Manual Transaction Entry (Phase 2)

```
[  ] "Add Transaction" button is visible and clickable on the Transactions page
[  ] Clicking "Add Transaction" opens the Add Transaction modal (centered, not in header)
[  ] Form fields present: date, account, account type, action, ticker, quantity, price, local currency, commission
[  ] Optional fields present: security name, settlement date, ISIN, exchange, reference id, notes
[  ] Source badge shows "Manual" as read-only
[  ] Default date = today
[  ] Default currency = profile's default-currency setting
[  ] Derived values update live: gross, net, FX rate to CAD, CAD equivalent
[  ] FX rate shown in form is the rate at the entered trade date (not today's rate for historical dates)
[  ] Save button is disabled when required fields are empty
[  ] Inline validation errors appear for invalid inputs
[  ] Saving a valid buy: row appears under Manual source group in Transactions page
[  ] Saving a valid buy: ACB updates correctly for that (ticker, account) pair
[  ] Saving a valid buy: dashboard stats update immediately
[  ] Saving a valid sell: RealizedGain record created with correct gain amount
[  ] Saving a valid sell in a TFSA: gain shows $0 tax in Simulator
[  ] Saving a dividend with ticker: classified as DIVIDEND action
[  ] Saving a deposit without ticker: classified as DEPOSIT action
[  ] Edit button is visible on manual rows (and NOT on imported rows)
[  ] Editing a manual entry and saving re-runs FX and ACB
[  ] Delete button on a manual row shows a confirmation prompt
[  ] Confirming delete removes the row and correctly unwinds ACB/RealizedGain
[  ] Attempting to sell more shares than held in that account: blocked with clear error, no row inserted
[  ] Manual entry in a currency with no live rate: falls back to static table, net_cad is non-null
[  ] Adding a manual entry that matches an existing import: dedup behavior is clear (documented in UI or note)
```

---

## SECTION 10 — Mathematical Accuracy

These tests verify that the app's financial calculations are correct against known-good fixtures.
Run against the synthetic test fixtures in `test_data/` that have pre-computed expected values.

### ACB (Adjusted Cost Base)

```
[  ] ACB after a single buy = (quantity × price) + commission
[  ] ACB after a second buy = weighted average of both buys incl. both commissions
[  ] ACB after a partial sell = ACB/share unchanged, ACB pool reduced proportionally
[  ] ACB after a full sell = ACB pool = 0
[  ] Realized gain = proceeds − (ACB/share × qty sold) − commission
[  ] Superficial loss: buy within 30 days before OR after a sell at a loss → loss denied, added back to repurchased ACB
[  ] ACB correctly separated per (ticker, account_type) — VEQT.TO in TFSA ≠ VEQT.TO in Margin
[  ] Commission included in cost basis on buys
[  ] TFSA sells: realized gain marked non-taxable
[  ] Manual entry inserted between two imported rows: ACB walk re-sorts chronologically and produces correct result
```

### FX (Foreign Exchange)

```
[  ] CAD transaction: fx_rate_to_cad = 1.0 exactly
[  ] USD transaction on a known historical date: fx_rate_to_cad matches the BoC historical rate for that date
[  ] net_cad = net_amount × fx_rate_to_cad (within 0.005 rounding tolerance)
[  ] FX at trade date: a historical USD buy does NOT use today's rate
[  ] GBP/EUR/JPY/AUD transactions: fx_rate_to_cad populated (non-null, non-zero)
[  ] Offline fallback: when BoC API unavailable, static FX table used and net_cad still non-null
[  ] FXService.populate_transaction() is idempotent: calling it twice does not change values
```

### Modified-Dietz Period Returns

```
[  ] Simple case: $10,000 start, $1,000 deposit at midpoint, $12,000 end
     → Modified Dietz ≈ (12000 - 10000 - 1000) / (10000 + 1000 × 0.5) = 9.52%
[  ] TRANSFER actions are excluded from both numerator and denominator
[  ] Period with no transactions: return = (end - start) / start
[  ] Period clamped to first transaction date: period_clamped = True, period_start_date = first tx date
[  ] Combined view return ≠ sum of individual returns (correct — Modified-Dietz doesn't add linearly)
```

### Portfolio Statistics

```
[  ] Sharpe ratio: annualized return / annualized std dev of weekly returns (risk-free rate configurable)
[  ] Sharpe is non-null when at least 52 weeks of data are present
[  ] Annualized return = (1 + total_return) ^ (365 / days) - 1
[  ] Volatility = std dev of weekly returns × sqrt(52)
[  ] Performance Attribution: sum of individual holding contributions ≈ total portfolio return (within 0.1%)
```

### TFSA Contribution Room

```
[  ] TFSA room accumulates correctly from birth year / residency year (from Settings)
[  ] Annual limits match CRA schedule (2009–2026 hardcoded schedule)
[  ] Contributions (deposits into TFSA) reduce available room
[  ] Withdrawals from prior year add back to current year's room
[  ] Over-contribution amount correctly flagged
```

---

## SECTION 11 — Data Fetching and External Services

```
[  ] yfinance price fetch: known tickers (AAPL, VEQT.TO, SPY) return non-null current prices
[  ] yfinance price fetch: graceful stale fallback when network unavailable (no crash)
[  ] Two-tier cache: second call for same ticker within cache window returns cached value (no second network call)
[  ] Price auto-refresh on launch: if cached prices are older than 30 minutes, refresh is triggered
[  ] SyncStatus banner shows a "X min ago" label that updates every 60 seconds
[  ] Dynamic ticker resolution: known Questrade internal IDs resolve to correct yfinance tickers
[  ] Resolved mappings are persisted in ticker_map (not re-fetched every session)
[  ] BoC FX API: historical rate for a known date (e.g. USD on 2024-01-15) returns the expected value
[  ] BoC FX API: dates before 2017 use the static fallback table
[  ] /api/portfolio endpoint returns 200 with non-empty data when transactions exist
[  ] /api/transactions endpoint returns 200 with correct rows
[  ] /api/import endpoint returns 200 and correct parse results for each test file
[  ] /api/attribution endpoint returns 200
[  ] Backend port 7842 is not accessible from outside localhost (local-only)
```

---

## SECTION 12 — Settings Panel

```
[  ] Settings panel opens centered (tested in Section 4, record result here too)
[  ] Profile section: current profile name editable
[  ] Tax section: marginal rate input saves and persists across app restart
[  ] Tax section: province selector saves and persists
[  ] TFSA section: birth year and residency year inputs save and persist
[  ] Display section: default period selector (1M/3M/6M/1Y/3Y/All) saves and applies on next load
[  ] Display section: default currency view selector saves and applies on next load
[  ] Display section: theme (light/dark) toggle works
[  ] Data section: price refresh interval setting saves
[  ] Data section: JSON export button produces a downloadable file
[  ] Data section: "Clear all data" button shows a confirmation prompt
[  ] "Clear all data" confirmed: all transactions, holdings, and cached prices removed; app shows empty state
[  ] "Clear all data" confirmed: any manual entries removed
[  ] Settings changes persist across an app restart (written to profile's config, not just memory)
```

---

## SECTION 13 — Reports and Export

```
[  ] Reports panel opens centered
[  ] Excel export produces a .xlsx file with 5 sheets: Summary, Holdings, Capital Gains, Transaction History, Price History
[  ] Excel export: Summary sheet contains portfolio value and top holdings
[  ] Excel export: Capital Gains sheet contains RealizedGain rows with correct gain amounts
[  ] Excel export: green/red conditional fills present on gain/loss columns
[  ] Capital Gains report in-app: per-sell breakdown with correct gain/loss per share
[  ] Capital Gains report: TFSA sells flagged as non-taxable
[  ] Capital Gains report: superficial loss adjustments shown where applicable
[  ] Annual Portfolio Report (PDF): generates a downloadable PDF without error
[  ] Annual Portfolio Report: contains portfolio value chart, performance vs S&P 500
[  ] TFSA Contribution Room Tracker: renders year-by-year breakdown
[  ] TFSA Contribution Room Tracker: over-contribution flagged visually when applicable
[  ] TFSA Contribution Tracker: prompts for birth year / residency year if not set in Settings
```

---

## SECTION 14 — Simulator and Rebalancing Advisor

```
[  ] What-If Simulator opens centered
[  ] Buy mode: entering ticker + quantity shows new portfolio total, allocation %, projected annual dividends
[  ] Sell mode: shows capital gain breakdown with step-by-step ACB math
[  ] Sell mode: shows tax estimate using marginal rate from Settings
[  ] Sell mode in TFSA: shows $0 tax
[  ] Lump-sum mode: "$X invested in Y on <date>" computes a plausible current value and annualised return
[  ] Simulator is read-only: no database writes occur when using the simulator
[  ] Rebalancing Advisor: three-step UI renders (set targets → pick mode → generate instructions)
[  ] Rebalancing Advisor: refuses to submit if target percentages don't sum to 100%
[  ] Rebalancing Advisor: warns when sells in a Margin account would trigger capital gains
[  ] Rebalancing Advisor: "invest new money $X" mode produces buy instructions only
```

---

## SECTION 15 — Price Alerts

```
[  ] Bell icon with triggered-count badge is visible in the banner
[  ] Alerts panel opens centered
[  ] Can create a new alert: buy-below threshold for a known ticker
[  ] Can create a new alert: sell-above threshold for a known ticker
[  ] Alert appears in the list with correct ticker and threshold
[  ] Alert is evaluated on the next price refresh (triggered badge increments if threshold crossed)
[  ] Can dismiss a triggered alert
[  ] Can delete an alert
[  ] Alerts persist across an app restart (stored in SQLite, not just memory)
```

---

## SECTION 16 — Dividend Calendar and Income Tracker

```
[  ] Dividend Calendar renders as a monthly bar chart
[  ] Upcoming payments are projected from observed cadence
[  ] Yield-on-cost table renders for each dividend-paying holding
[  ] Trailing-12-month dividend total is displayed
[  ] Period dividend total updates when the selected period is changed
```

---

## SECTION 17 — Privacy and Local-First Hygiene

```
[  ] git status: no __pycache__/ directories staged or tracked
[  ] git status: no *.pyc files staged or tracked
[  ] git status: no .env files staged or tracked
[  ] git status: no per-profile SQLite databases staged or tracked
[  ] git status: no backend.log staged or tracked
[  ] git status: no uploaded test files outside test_data/ staged or tracked
[  ] .gitignore contains entries for: __pycache__/, *.pyc, .env, *.db, backend.log, venv/, node_modules/
[  ] backend.log inspection: no account numbers present in log output
[  ] backend.log inspection: no real holdings or balances present in log output
[  ] backend.log inspection: no credentials or tokens present in log output
[  ] Backend API not reachable from outside 127.0.0.1 (local-only binding confirmed)
[  ] No outbound network calls during a fully offline session (except yfinance/BoC — these are expected and opt-in)
[  ] README contains a "Privacy" section documenting: what is stored, where, and how to clear it
```

---

## SECTION 18 — Regression Guard (Always Last)

These are the permanent non-negotiable gates. If any of these fail, the build must NOT be released.

```
[  ] pytest tests/ -v — 0 failures, 0 errors
[  ] npx tsc --noEmit — 0 TypeScript errors
[  ] Wealthsimple regression test green (parser output unchanged)
[  ] Questrade regression test green (parser output unchanged)
[  ] App launches without crash
[  ] Dashboard loads data correctly
[  ] No modal opens squished into the header bar
[  ] FX rates non-null on all imported rows
[  ] net_cad non-null on all imported rows
[  ] ACB engine produces correct result on canonical test fixture
[  ] Modified-Dietz returns correct on canonical test fixture
[  ] TFSA CAD-only view shows real numbers (not "—")
[  ] "Clear all data" works without crashing
```

---

## Guidance for Claude Code When a Test Fails

When a `[✗]` item is recorded:

1. **Do not skip it or mark it `[~]` just because it is inconvenient.** A failing UI test is a real bug.
2. Add a `NOTE:` that includes: what was expected, what actually happened, and the relevant file/line if known.
3. After completing the full run, **ask the user**: "The test run found N failure(s). Do you want me to attempt to fix them now, or review the log first?"
4. If the user asks for fixes: address each `[✗]` item, then re-run only the failed tests to confirm the fix. Re-run the full suite before producing a new log.
5. **Never mark a test `[✓]` without actually executing it.** Do not assume that because something was fixed in a previous version it is still working now. Run every test on every build.
