# Portfolio Dashboard — Polish & Improvements Plan
**Target version: 0.6.1 (critical fix + UI fixes + FX testing) → 0.7.0 (universal import)**
**Current version: 0.6.0**

> **READ THIS FIRST — Instructions for Claude Code**
>
> This plan contains six items. **Item 0 is a CRITICAL crash + lockout fix and must be
> done FIRST, verified, and shipped before anything else.** The app is currently
> bricking itself: a bad import crashes the portfolio endpoint, and there is no recovery
> path, so the app is stuck on an error screen on every relaunch.
>
> **Order of work: Item 0 (critical) → 1 → 2 → 3 → 5 → 4.**
>
> **Rules for this plan:**
> 1. Read this document end-to-end before writing any code.
> 2. **For every item, before writing code, write a short "Approach" note** explaining how
>    you intend to solve it, which files you'll touch, and any tradeoffs. Think first.
> 3. Break each item into the listed sub-tasks (or finer). Commit per sub-task. Run
>    `pytest backend/tests/ -v` and `npx tsc --noEmit` after each commit — both must pass.
> 4. After each item, visually verify in the running app before moving on.
> 5. **Do not rush Item 0 or Item 4.** Item 0 is about correctness and never locking the
>    user out again. Item 4 is the large universal-import feature. Both need care.
> 6. If anything here conflicts with the existing codebase, stop and ask.
>
> Suggested version flow: ship **Item 0 alone as 0.6.1** so the user can confirm the app
> is no longer bricked; then Items 1, 2, 3, 5 as **0.6.2**; then Item 4 as **0.7.0**.
> (You may bundle 0 + 1 + 2 + 3 + 5 into one 0.6.1 if all verify cleanly — your call, but
> Item 0 must be verified working first regardless.) Do NOT implement direct broker
> connections — still deferred.

---

## Item 0 — CRITICAL: Import Robustness, Crash Recovery & App Reset

**What happened (from user-reported screenshots):**
- Uploading several of the synthetic test files caused the dashboard to fail with
  **"Couldn't load portfolio — '>=' not supported between instances of 'numpy.ndarray'
  and 'Timestamp'"**.
- The browser console shows `GET localhost:7842/api/portfolio` returning **500 Internal
  Server Error**.
- After closing and reopening the app, it loads straight back into the "Couldn't load
  portfolio" screen every time. **There is no way out** — the user is locked out because
  the dashboard never renders, so Settings (and its "Clear all data") is unreachable.

There are three distinct defects here, plus two new capabilities to add. Fix all five.

### 0A — Root-cause and fix the portfolio crash

**The error** `'>=' not supported between instances of 'numpy.ndarray' and 'Timestamp'`
is a pandas/numpy type-mismatch on a date comparison. Somewhere in the portfolio
computation, a **numpy array** is being compared with `>=` against a **pandas Timestamp**,
which numpy refuses.

**Research / investigation guidance (spend real time here):**
- Reproduce it first. Import the EXACT file(s) that triggered it (the user said "many of
  the created test files"). Note: some synthetic fixtures generated earlier had visibly
  malformed rows (e.g. the TD tab-separated fixture looked corrupted during creation), so
  the fixtures themselves are likely part of the problem — which is GOOD to find, because
  real-world messy files would crash the same way.
- Grep `backend/portfolio.py` (and any module it calls) for date comparisons:
  `>=`, `<=`, `>`, `<`, `.between(`, `.searchsorted(`, `np.where(` involving dates.
  Likely locations: period-return / Modified-Dietz windowing, period clamping
  (min/max date), benchmark (S&P 500) date alignment, and price-history reindexing.
- The usual culprits:
  - A date column was never coerced with `pd.to_datetime(...)` so it's object/string,
    then `.values` or `.to_numpy()` turned it into an `object`/`datetime64` ndarray that's
    then compared to a scalar `Timestamp`.
  - A comparison written as `array >= timestamp` (numpy raises) instead of
    `timestamp <= array` or a properly-typed `pd.Series`/`DatetimeIndex` comparison.
  - Mixed tz-aware / tz-naive timestamps.
- **The fix is defensive typing at the boundary:** ensure every date column that feeds the
  portfolio math is converted with `pd.to_datetime(col, errors="coerce")` immediately on
  load, drop or flag rows where the date is `NaT`, and make all date comparisons
  scalar-to-`Series`/`DatetimeIndex` (never raw ndarray vs Timestamp). Do not patch only
  the one line that threw — find every comparable site and normalize date handling once,
  centrally, so this class of bug can't recur from a different file.

**Sub-tasks:**
1. Reproduce the crash with the offending file(s). Capture the full traceback (run the
   backend directly, hit `/api/portfolio`, read the stack). Identify the exact line.
2. Write a regression test that imports the offending file (or a minimal fixture that
   reproduces the same bad shape) and asserts `/api/portfolio` returns 200 (currently 500).
3. Centralize date coercion: wherever transactions/prices enter the portfolio computation,
   coerce dates to proper pandas datetimes once, with `errors="coerce"`, and handle `NaT`.
4. Fix all date-comparison sites to be type-safe (no ndarray-vs-Timestamp).
5. Confirm the regression test now passes and the full suite is green.

Commit message: `fix(portfolio): defensive date coercion; resolve ndarray vs Timestamp 500`

### 0B — Validate imports so bad data can't enter the database

The deeper problem: a file that parses "successfully" but contains malformed dates/numbers
was written to SQLite, and only later crashed the dashboard. Imports must validate BEFORE
committing rows.

**Sub-tasks:**
1. Add a validation pass in the import pipeline (after parsing, before `store` insert):
   - Every row's `transaction_date` must parse to a real date; reject/flag rows where it
     doesn't.
   - Numeric fields (quantity, price, amount, commission) must coerce to numbers; reject
     rows where required numerics are non-numeric.
   - Currency must be a recognized code (or default sensibly with a warning).
2. If a file has unrecoverable rows, do NOT silently import the good ones into a state that
   crashes the app. Instead: import only valid rows AND return a clear summary to the UI
   ("Imported 30 of 35 rows. 5 rows skipped: invalid date on rows 12, 19, 24, 28, 33"),
   OR reject the file with a clear error if too many rows are invalid. Use your judgment;
   the rule is **never store data that will later 500 the portfolio endpoint.**
3. Surface the validation summary in the upload preview/result UI so the user knows what
   happened.
4. Add tests: a fixture with some malformed rows imports only the valid rows and reports
   the skipped ones; a fully-malformed file is rejected with a clear message; the
   dashboard still loads (200) after such an import.

Commit message: `feat(import): pre-insert validation; never persist portfolio-breaking rows`

### 0C — Crash recovery: the app must NEVER lock the user out

Even with 0A and 0B, a future edge case must not brick the app. The "Couldn't load
portfolio" screen needs an escape hatch.

**Sub-tasks:**
1. On the "Couldn't load portfolio" error screen, add visible recovery actions:
   - **"Open Settings"** (or directly expose the reset controls here) so the user can
     clear data even when the dashboard can't render.
   - **"Reset app data"** button that triggers the factory reset from 0D.
   - **"Retry"** button that re-attempts the portfolio load.
2. Make the error screen show the underlying error message (already shown) PLUS a plain-
   language line: "This can happen after importing a file with unexpected data. You can
   reset the app's data below to recover."
3. Ensure Settings (and the reset controls) are reachable independently of whether
   `/api/portfolio` succeeds — i.e. the Settings panel must not depend on a successful
   portfolio load to open.
4. Harden the backend: `/api/portfolio` should catch computation errors and return a
   structured 200 with an `error` field (or a 4xx with a clear payload) rather than an
   unhandled 500, so the frontend can always render a usable recovery state.

Commit message: `fix(app): recovery actions on portfolio error; Settings reachable when load fails`

### 0D — User-facing "Reset App to Factory State" in Settings

Add a clearly-labeled, confirmation-gated option in the Settings panel that wipes
**everything** and returns the app to its fresh-install state.

**Distinguish from existing "Clear all data":**
- Existing "Clear all data" clears the *current profile's* transactions/holdings.
- New **"Reset app to factory state"** deletes **ALL** profiles, **ALL** per-profile
  databases, **ALL** cached prices/FX, alerts, settings, and any other app-generated state
  — leaving the app exactly as it is on first download (no data, no profiles, default
  settings). Keep both options; label them distinctly so users don't confuse them.

**Sub-tasks:**
1. Add a backend endpoint (e.g. `POST /api/app/reset`) that deletes all profile databases,
   all cache files, all config/settings, and recreates the clean first-launch state.
   Be exhaustive — enumerate every on-disk artifact the app creates (profile DBs, price
   cache, FX cache, ticker_map, alerts, logs, settings/config) and remove them all.
2. Add the "Reset app to factory state" control in Settings with a strong confirmation
   (e.g. type-to-confirm or a two-step "Are you absolutely sure? This deletes all profiles
   and data and cannot be undone." dialog).
3. After reset, the app should return to the initial onboarding/upload state without
   needing a manual restart (or prompt a clean restart if that's simpler and reliable).
4. Make this reset control ALSO reachable from the 0C error-screen recovery actions.
5. Add tests: reset removes all profiles and data; after reset, the app reports a clean
   first-launch state; `/api/portfolio` and the profile list reflect the empty state.

Commit message: `feat(settings): factory-reset option to wipe all profiles, data, and cache`

### 0E — Wipe all app data as part of THIS rebuild

The user's current installation is in a corrupted/locked state. As part of producing the
0.6.1 build, ensure a clean slate:

**Sub-tasks:**
1. Identify every location the app writes user data at runtime (the Electron `userData`
   path — typically `%APPDATA%/Portfolio Dashboard` on Windows — plus any cache/log dirs).
   Document these paths in the README so they're known.
2. Provide a clear instruction (in the build/release notes and to the user) on how the
   corrupted state is cleared. Two acceptable approaches — pick the safer one and explain:
   - (a) Document the manual folder-delete path for the user (lowest risk, no code that
     could wipe real data unexpectedly), OR
   - (b) Add a one-time migration/cleanup on first launch of 0.6.1 that detects an
     unreadable/corrupt database and offers to reset it (more user-friendly, but must be
     extremely careful not to delete healthy data — only trigger on an actual
     corruption/load failure).
   Recommendation: implement (b) as a safe "corrupt DB detected → offer reset" path
   (it dovetails with 0C/0D), and also document (a) as the manual fallback.
3. Do NOT hardcode a destructive wipe that runs unconditionally on every launch — that
   would delete healthy user data. Any automatic cleanup must be gated on actual detected
   corruption or explicit user action.

Commit message: `feat(app): safe corrupt-database detection with guided reset on launch`

### 0F — Tests + Master Debug coverage

**Sub-tasks:**
1. Add backend tests covering 0A–0D (crash regression, import validation, factory reset,
   recovery-state behavior).
2. Add a Playwright E2E test: simulate a failed portfolio load → confirm the recovery
   actions appear and the reset control works → app returns to clean state.
3. Add a **Section 0 — Crash Recovery & Reset** block to
   `markdown-instructions/MASTER_DEBUG_AND_TEST_RUN.md` covering: import validation,
   portfolio endpoint never returns unhandled 500, error screen has recovery actions,
   factory reset wipes all profiles/data/cache, app recovers to clean state.

Commit message: `test(recovery): crash-recovery, import-validation, and factory-reset tests`

### Item 0 Verification
- Re-import the file(s) that originally crashed → dashboard loads (200), no 500.
- Import a file with some malformed rows → only valid rows import, user sees a clear
  skipped-rows summary, dashboard still loads.
- Force/simulate a portfolio load failure → the error screen offers Retry / Open Settings
  / Reset, and Reset recovers the app to a clean state.
- "Reset app to factory state" in Settings removes ALL profiles, data, and cache; app
  returns to first-launch onboarding.
- Relaunching the app after a reset starts clean — never stuck on the error screen.

---

## Item 1 — Fix Filter Bar Contrast in Dark Mode

**Problem:** On the Transactions page, the top filter bar inputs (All Sources, All Types,
All Currencies, All Actions dropdowns, both date inputs, search box) blend into the dark
background; text is nearly invisible in dark mode, and only marginally better in light mode.

**Goal:** Filter inputs must clearly match the existing UI design tokens — readable text,
visible borders, legible placeholders, distinct backgrounds — in BOTH themes.

### Approach note (write before coding)
Identify the input styling the Settings panel / Add Transaction form / Upload component
already use correctly in dark mode, and reuse those exact tokens. Do not invent new colors.

### Sub-tasks
1. Locate the filter bar component; inspect why its inputs are low-contrast (likely a
   transparent/near-background `bg-*` and an over-dim placeholder color).
2. Find the canonical correctly-rendering input styling elsewhere in the app.
3. Apply it to all filter controls: four dropdowns, both date inputs, search box. Ensure
   distinct background, strong text contrast, legible (dimmed but visible) placeholders,
   visible borders, visible chevrons/search icon.
4. Verify in BOTH dark and light mode.

Commit message: `fix(transactions): filter bar contrast and readability in dark mode`

---

## Item 2 — Default Date Range to Full Transaction History

**Problem:** The Transactions date range defaults to Jan 1 of the current year → today,
so older transactions show "0 transactions shown" until the user manually changes it.

**Goal:** On load, default the range to earliest → latest transaction date across all
sources (including manual) so everything is visible immediately.

### Approach note (write before coding)
Prefer computing min/max client-side from the already-fetched transaction list (no backend
change needed). Explain your choice.

### Sub-tasks
1. After transactions are fetched, compute min/max `transaction_date` across all sources.
2. Initialize the date range to `[min, max]` instead of `[Jan 1 current year, today]`.
3. Edge cases: no transactions → empty/disabled inputs with placeholder, no crash; single
   transaction → min == max; "Clear" resets to the full `[min, max]` span, not current year.
4. Manual narrowing of the range must still work.

Commit message: `fix(transactions): default date range to full transaction history`

---

## Item 3 — Add "Back to Dashboard" Navigation

**Problem:** Once on the Transactions page, there's no top-bar control to return to the
Portfolio Dashboard; the user can get stuck.

**Goal:** A clear, always-visible toggle between Dashboard and Transactions, with the
active view indicated.

### Approach note (write before coding)
Prefer adding a distinct "Dashboard" control next to "Transactions" (clearer than a single
two-state toggle). Reuse the existing view-state mechanism — no new routing system.

### Sub-tasks
1. Identify the current Dashboard/Transactions view-state switch.
2. Add a visible "Dashboard" control reachable from the Transactions page.
3. Indicate the active view (reuse the existing purple-accent highlight).
4. Keyboard accessible (tab + Enter/Space).
5. Confirm switching views preserves sensible state; note the behavior.

Commit message: `feat(nav): add Dashboard/Transactions view toggle with active-state indicator`

---

## Item 5 — Multi-Currency FX Testing (Dashboard Verification)

**Problem:** All fixtures are CAD/USD only; the dashboard's FX features (Combined CAD/USD,
Currency Exposure, four currency view modes) have never been tested with GBP/EUR/JPY/etc.

**Goal:** Add multi-currency fixtures + tests verifying FX behavior, and wire them into the
Master Debug framework.

### Approach note (write before coding)
Cover at least GBP, EUR, JPY (JPY for its large-nominal / decimal edge case). Confirm the
`FXService` static fallback has rates for these before relying on them.

### Sub-tasks
1. Confirm/extend `FXService` static fallback rates for GBP, EUR, JPY, AUD, CHF, HKD, SEK,
   NOK (add clearly-commented fallback values where missing).
2. Create `test_data/csv/MultiCurrency_2024.csv` with CAD, USD, GBP, EUR, and JPY holdings,
   including a foreign-currency dividend and a foreign-currency sell.
3. Add `backend/tests/test_fx_multicurrency.py`: non-null non-1.0 FX per foreign currency;
   `net_cad = net_amount × fx_rate_to_cad`; JPY converts without breaking totals; foreign
   sell → correct CAD realized gain; Combined CAD/USD totals correct for mixed currencies;
   CAD-only view excludes foreign holdings; currency-exposure weights correct.
4. **Investigate & document** what the dashboard shows for a foreign holding in each
   currency mode. If you find a real bug (foreign holding dropped, wrong conversion), STOP
   and report it.
5. Add a **Section 11b — Multi-Currency FX** block to `MASTER_DEBUG_AND_TEST_RUN.md`.

Commit messages:
- `test(fx): multi-currency fixture and FX conversion tests (GBP, EUR, JPY)`
- `docs(testing): add multi-currency FX section to master debug framework`

---

### Step 1 — Canonical schema + header alias dictionary
Data-driven dict mapping each canonical field to its many labels (bilingual EN/FR):
`transaction_date` ← date / trade date / settlement date / date d'exécution / run date;
`action` ← action / activity / transaction type / type d'opération; `ticker` ← symbol /
ticker / security / titre; `quantity` ← qty / shares / units; `price` ← price / trade price
/ prix; `net_amount` ← amount / net amount / net settlement / proceeds / montant net;
`currency` ← currency / ccy / devise; `commission` ← commission / fees / comm/fee;
`account_type` ← account type / registered account.
Commit: `feat(import): canonical schema and header alias dictionary`

### Step 2 — Universal table extraction (csv/tsv/xlsx/xlsm/xls/pdf)
Return clean rows + detected header row for any file. Core primitive: **find-the-header-row**
by scoring each row on how many cells fuzzy-match known aliases. CSV: detect delimiter, skip
leading metadata. Excel: pick the transaction sheet, skip merged/title rows. PDF: pdfplumber
tables, concatenate matching-header tables, handle multi-page. Test with all existing
fixtures + a new unknown-format fixture.
Commit: `feat(import): universal table extraction for csv/xlsx/xlsm/pdf`

### Step 3 — Column mapping + confidence scoring
Produce `{canonical_field: source_column_index}` via alias dict + fuzzy matching
(token-set/Levenshtein) and an overall confidence score. Define minimum viable mapping
(date + action-or-amount-sign + ticker/qty/price-or-amount).
Commit: `feat(import): column mapping with fuzzy header matching and confidence`

### Step 4 — Generic fallback parser
`GenericParser` using Steps 2–3, registered as **lowest priority** (named parsers always
win). Same `Transaction` output; infer action from amount sign when no action column; set
`broker` from any detected institution name else `"Imported (Generic)"`; run FX + dedup +
**Item 0 validation**. Tests: unknown fixture parses; named fixtures NOT hijacked.
Commit: `feat(import): generic fallback parser for unknown institutions`

### Step 5 — Editable column-mapping preview (the safety net)
When generic/low-confidence: show detected mapping + 5–10 row preview + editable dropdowns
to reassign/ignore columns + a "confirm this is correct" step before import. Named/high-
confidence imports keep the existing flow. Playwright E2E: unknown fixture → mapping editor
→ confirm → rows import under the generic source group.
Commit: `feat(import): editable column-mapping preview for generic imports`

### Step 6 — Integration + regression
All 11 named fixtures still route to named parsers (no regression). Generic rows feed
dashboard combined views, ACB, capital gains, currency exposure. Dedup holds. Add a
**Section 6b — Universal/Generic Import** block to `MASTER_DEBUG_AND_TEST_RUN.md`.
Commit: `test(import): universal import integration tests and master-debug section`

### Item 4 Verification
- Unknown-institution CSV/XLSM/PDF import correctly (after mapping confirmation).
- All 11 named brokers unchanged (no regression).
- Generic rows feed all dashboard stats; mapping editor corrects wrong guesses.
- Generic imports pass Item 0 validation (can't brick the app).

---

## Final Regression & Acceptance (after all items)
- [ ] **Item 0:** crash fixed; bad imports validated/rejected; app never locks out; factory
      reset works; corrupt-DB recovery works; app recovers to clean state
- [ ] Item 1: filter bar readable in dark AND light mode
- [ ] Item 2: all transactions shown on load, no manual date entry
- [ ] Item 3: Dashboard/Transactions toggle works both ways with active indicator
- [ ] Item 5: multi-currency FX fixtures + tests pass; master-debug FX section added; any
      dashboard FX bug reported
- [ ] Item 4: universal import handles unknown CSV/XLSM/XLS/XLSX/PDF; mapping editor works;
      11 named parsers non-regressed; generic rows feed all stats and pass validation
- [ ] `pytest backend/tests/ -v` — 0 failures; `npx tsc --noEmit` — 0 errors
- [ ] Wealthsimple + Questrade regression tests green
- [ ] CHANGELOG updated per version bump
- [ ] Every fix visually verified in the running app

## Reminders
- Item 0 first, verified, ideally shipped as 0.6.1 before other items pile on.
- Write an Approach note before coding each item. Think first.
- Commit per sub-task; test after every commit.
- Never persist data that can later 500 the portfolio endpoint.
- Never leave the user with no recovery path.
- Keep the editable mapping preview as the guard against silent mis-parsing.
- Do NOT implement direct broker connections — still deferred.
