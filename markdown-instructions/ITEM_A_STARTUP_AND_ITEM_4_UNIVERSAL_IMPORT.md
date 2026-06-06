# Portfolio Dashboard — Item A (Clean-Machine Startup) + Item 4 (Universal Import)
**Current shipped version (local): 0.6.4 → target: 0.7.0**
**Public GitHub "Latest" release: v0.5.3 — this is what external users actually download, and it predates the 0.6.1 startup fixes.**

> **ORDER OF WORK: Item A FIRST (clean-machine startup), then Item 4.**
> An external tester on a clean PC could not get past the splash screen on the public v0.5.3
> build. There is no point shipping a universal importer on top of an app that won't launch on
> other people's machines. **Item A is the gate; do it, ship a fixed public release, then Item 4.**

---

## Item A — CRITICAL: Clean-Machine Startup Failure (external tester could not launch)

**Source:** an external tester installed the **public v0.5.3** release on a clean Windows PC and
never reached the dashboard. This is the most trustworthy bug report the project has had, because
it's a real third-party machine with none of the dev-box workarounds (Defender exclusions, manual
`%APPDATA%` deletes, Task Manager kills) that have masked these issues during local testing.

**Important framing:** the 0.6.1 startup work (kill stale backend on port 7842; 30s splash timeout
with Retry/Quit; elapsed-seconds feedback) is **already in the 0.6.4 local build but is NOT in the
public v0.5.3 release.** Do **not** assume the 0.6.1 fix already covers this — the tester's report
contains failure modes the 0.6.1 fix does **not** address (see A2 and A3). Treat Item A as a fresh
clean-machine investigation, then re-cut a public release that actually contains the fixes.

---

### ⚑ INVESTIGATION FINDINGS — 2026-06-06 (Claude Code, dev box, 0.6.4)

Static + direct-`backend.exe` investigation on the HOME-PC dev box. Several of the plan's named
leads are **already fixed or factually absent in 0.6.4** — recorded here so the doc reflects reality.
The clean-machine repro itself could not be run from the dev box (no VM; Defender exclusions mask the
condition), so the one real open item (A2) is pending an artifact from the tester's machine.

- **Infinite hang — ALREADY FIXED in 0.6.4 (commit `3db14a5`).** Root cause traced: v0.5.3's splash
  used `alwaysOnTop: true` and an async `close()`, so the 30 s health-timeout error dialog rendered
  *behind* the splash — looking like an eternal "Starting local data service…". v0.5.3 *did* have the
  30 s `waitForBackend` deadline; the dialog was just masked. 0.6.4 fixes this: splash
  `alwaysOnTop:false`, synchronous `destroy()`, `closeSplash()` before the dialog, an 8 s
  `ready-to-show` failsafe, and a `Retry/Quit` error dialog with the captured stderr tail + log path.
  → On the tester's clean machine, **0.6.4 surfaces the real backend error after 30 s instead of
  hanging.** That is the lever that lets us diagnose A2 remotely.

- **A3 (location/geolocation/region dependency) — PREMISE IS FALSE.** `git grep` across all tracked
  source + both dependency manifests (`backend/requirements.txt`, `electron/package.json`) finds
  **zero** geolocation / geoip / region / locale / `navigator.geolocation` / permission-handler code.
  The only `location` hits are `window.location.reload()` and URL-hash routing. The backend binds
  **only** to `127.0.0.1`. **Our code never requests OS location — there is nothing to remove or
  de-block.** The Windows location prompt the tester saw is an unrelated first-run Windows dialog
  (likely SmartScreen / Defender / Firewall) they associated with the hang. *Action:* tester to
  screenshot/transcribe the exact prompt wording on the next run; then decide if any README/installer
  note is warranted. **No A3 code changes.**

- **A1 (no desktop / Start-Menu shortcut) — NOT A CONFIG BUG.** v0.5.3's `electron-builder.yml`
  **already** had `createDesktopShortcut: true` and `createStartMenuShortcut: true` (unchanged in
  0.6.4). So "no shortcuts appeared" is *not* explained by a missing flag. Real cause needs the
  clean-machine repro (NSIS per-user quirk, a custom install dir, or the tester not spotting them).
  **Left open pending the tester artifact — no speculative config edits.**

- **A2 (backend fails to start on a clean box) — THE ONLY REAL OPEN ITEM.** The bundled 0.6.4
  `backend.exe`, run directly against a *fresh empty* profile dir on the dev box, starts cleanly:
  binds `7842`, serves `/health` 200, registers all 12 parsers, creates the profile DB. It does **not**
  reproduce here (Defender exclusions). True root cause (Defender quarantine of the unsigned 122 MB
  onefile, first-run extraction, AV interference) is only observable on a clean target. **Pending:
  tester runs the current 0.6.4 build and relays the error-dialog text +
  `%APPDATA%\Portfolio Dashboard\backend.log`.**

**Hardening shipped this session (valuable regardless of A2 root cause):**
- **A4** — `profiles.factory_reset()` now also wipes top-level `backend.log` + `window-state.json`
  (not just profile DBs); a new NSIS `customUnInstall` hook (`assets/installer.nsh`) offers to remove
  `%APPDATA%\Portfolio Dashboard` on a genuine uninstall (guarded by `${isUpdated}` so upgrades never
  lose data; defaults to keep). This directly addresses the tester's "uninstall + reinstall didn't
  re-prompt / still hung" = stale `%APPDATA%` surviving uninstall.
- Regression tests: `backend/tests/test_clean_start.py` (clean first-run → `/health` 200, 12 parsers,
  DB created; factory_reset removes top-level artifacts) + smoke-test Test 5 (readiness poll is
  bounded → no infinite hang when the backend never starts). `pytest` 126 passed; `tsc` 0 errors.

**Still pending (needs tester / clean machine + your GitHub):** A2 root-cause fix, A1 real cause,
location-prompt wording, and the re-cut public release verified on the clean target.

---

### Reported symptoms (verbatim signal to investigate)
1. Installer ran, but gave **no desktop shortcut / Start Menu entry**, contrary to the instructions.
2. First launch raised a **Windows location-permission prompt**; tester clicked **No**; splash then
   **stuck on "Starting local data service."**
3. Uninstall + reinstall: the location prompt **did not appear again**, and it **still hung**.
4. Manually enabling Windows location later let the app access location, but it **still hung**.
5. Tester **ended `backend.exe` in Task Manager** before relaunching — **did not help.**

### What each symptom most likely means (leads, not conclusions — verify each)
- **A1 — Missing shortcuts (installer config).** electron-builder/NSIS not creating shortcuts.
  Check `electron-builder.yml` `nsis` block: `createDesktopShortcut`, `createStartMenuShortcut`,
  `shortcutName`, `oneClick` vs `perMachine`, `allowToChangeInstallationDirectory`. Minor severity,
  but it's the user's first impression and the instructions promise it — fix it.
- **A2 — Backend fails to start on a clean machine (the core hang).** Symptom 5 is the key clue:
  the tester killed `backend.exe` and it still hung, so on his machine the cause was **NOT a zombie
  process holding port 7842** (that's the case the 0.6.1 fix targets). The backend is **failing to
  start at all** on a clean box. The 0.6.1 fix would still strand him (now with a Retry button that
  re-hangs). Likely causes to test on a clean VM:
    - PyInstaller `backend.exe` missing a hidden import / data file / DLL (e.g. a `pandas`/`numpy`/
      `pdfplumber`/`yfinance` runtime dependency) that's present on your dev machine but absent on a
      clean install. Run the bundled `backend.exe` directly on a clean machine and capture stderr.
    - Backend writes its DB/log under a path that doesn't exist or isn't writable on first run for a
      standard (non-admin) user — fails silently before binding 7842. Confirm the data dir is created
      under `%APPDATA%` with correct permissions before first DB open.
    - Windows Defender / SmartScreen quarantining the freshly-extracted bundle on a machine with no
      exclusion (the real-user condition). Detect and surface this rather than hanging.
    - Hard-coded port 7842 already in use by something unrelated → no fallback. Confirm the
      OS-assigned-fallback path actually works when 7842 is taken.
- **A3 — The location-permission prompt (strong, unexplained lead — investigate directly).** A
  local-first desktop portfolio app should **never** need OS location. Symptom 2 ties the prompt
  directly to the hang. Investigate:
    - Find what triggers geolocation. Grep the Electron main/renderer for `geolocation`,
      `navigator.geolocation`, `setPermissionRequestHandler`, and any default permission handler.
      Grep the backend/deps for IP-geolocation / region / locale calls made on startup.
    - Determine whether a **denied** location permission **blocks** startup (a synchronous/awaited
      geolocation or region call that never resolves when denied could stall the `/health` readiness
      the splash polls). If anything on the startup path awaits location, make it non-blocking and
      independent of the permission outcome.
    - The app must launch fully whether location is allowed, denied, or never prompted. Ideally
      **remove the location dependency entirely** unless there's a real feature need; if there is,
      defer it and never block startup on it.
- **A4 — Persisted state survives uninstall (ties to factory-reset / clean-uninstall).** Symptom 3
  (no re-prompt, still hung after reinstall) means state persisted across uninstall — `%APPDATA%\
  Portfolio Dashboard`, a registry permission cache, or similar — and the uninstaller doesn't clear
  it. This is the **clean-uninstall / reset-to-factory** capability already wanted. Add:
    - An **in-app "Reset to factory state"** (extend/confirm Item 0's reset) that wipes all profiles,
      data, caches, and any persisted permission/region state — verified on a clean machine.
    - An **uninstaller that fully removes app data** (NSIS uninstall hook clearing `%APPDATA%`),
      OR clear in-app guidance + a documented manual path. Goal: uninstall → reinstall returns to a
      true first-run state (location prompt reappears, no stale data, no hang).

### Item A sub-tasks
1. **Reproduce on a clean target**, not the dev box. Use a fresh Windows VM / the tester's described
   conditions (standard user, no Defender exclusion, deny location). Install the **public v0.5.3**
   asset first to reproduce the exact report, then the current 0.6.4 build to see which symptoms the
   0.6.1 fixes already resolve and which remain.
2. **A2:** run the bundled `backend.exe` directly on the clean target; capture stderr/crash. Identify
   why it doesn't bind 7842 on a clean machine. Fix the bundle (hidden imports / data dir / perms).
   Add a regression: backend starts and `/health` returns 200 from a clean profile dir.
3. **A3:** trace and eliminate (or fully de-block) the location/geolocation/region dependency. Prove
   the app launches with location allowed, denied, and never-prompted.
4. **A1:** fix the NSIS config so install creates the desktop + Start Menu shortcuts the instructions
   promise.
5. **A4:** implement/verify reset-to-factory wiping ALL state (incl. permission/region cache); make
   the uninstaller remove app data (or document + surface the manual step). Verify the reinstall →
   clean first-run loop on the clean target.
6. **Harden the splash** beyond 0.6.1: the timeout screen must distinguish "backend failed to start"
   (show captured backend error + log tail + Retry/Quit/Reset) from "still starting," and must never
   hang infinitely regardless of the failure mode.
7. **Re-cut and publish a new public release** containing all of the above (supersede v0.5.3 as
   Latest). Verify the published asset on the clean target before calling Item A done.
8. **Also note (separate, lower priority — log but don't fix under Item A):** the tester thread
   mentions **some stocks not calculating dividends correctly.** Capture a repro (which tickers,
   expected vs actual) and add it to the backlog; do not let it expand Item A's scope.

### Item A verification (the gate before Item 4)
- [ ] Public v0.5.3 hang reproduced on a clean machine; root cause(s) for A2 + A3 identified.
- [ ] Backend starts and serves `/health` 200 on a clean install as a standard (non-admin) user.
- [ ] App launches fully with location allowed, denied, OR never prompted — no startup dependency on it.
- [ ] Desktop + Start Menu shortcuts created by the installer.
- [ ] Reset-to-factory wipes all state incl. permission/region cache; uninstall removes app data;
      reinstall returns to true first-run.
- [ ] Splash never hangs infinitely; backend-failure path shows a real error + Retry/Quit/Reset.
- [ ] A new public release is published and verified on a clean machine.
- [ ] Dividend-calculation bug captured in the backlog with a repro (not fixed here).

> Only after Item A is verified and a fixed public release is out should you proceed to Item 4 below.

---

# Item 4: Universal / Intelligent Transaction Import
**Status: Item 4 is at Step 0 (research). No Item 4 code has been written yet. Begin Item 4 only after Item A ships.**

> **READ THIS FIRST — Instructions for Claude Code**
>
> This file contains **two work items in strict order: Item A (clean-machine startup) FIRST,
> then Item 4 (universal import).** Items 0, 1, 2, 3, 5 from
> `markdown-instructions/POLISH_AND_IMPROVEMENTS_v0.6.1.md` are **already shipped and verified in
> the local v0.6.4 build — do NOT revisit them.** The Item 4 section below also **replaces the thin
> `## Item 4` stub** at the bottom of that polish file.
>
> **Resume point:** Start with **Item A** — reproduce the external tester's clean-machine launch
> failure, fix it, and publish a fixed public release (the current public "Latest" is v0.5.3, which
> predates the 0.6.1 startup fixes). **Only after Item A is verified and shipped publicly** do you
> move to **Item 4 / Step 0** (research only): write the research summary + proposed architecture,
> then **STOP and wait for my approval** before writing any Step 1+ code.
>
> **Rules for this plan (same discipline as the rest of the project):**
> 1. Read this document end-to-end, plus the four files listed in §0, before doing anything.
> 2. **Write an "Approach" note before each step** — files you'll touch, tradeoffs, how you'll test.
> 3. Build in the layered steps below, **one commit per step**, with tests. `pytest backend/tests/ -v`
>    and `npx tsc --noEmit` must both pass after every commit.
> 4. After each step, **visually verify in the running app** (Playwright probe or screenshot).
>    Compile/unit-pass is necessary but NOT sufficient — see the 0.6.3 stale-bundle lesson in §0.
> 5. **Named parsers must NEVER be regressed.** The generic layer is the lowest-priority fallback.
> 6. **Generic imports must pass Item 0 pre-insert validation** — they can never brick the app.
> 7. The **editable column-mapping preview (Step 7)** is the safety net and is **not optional**.
> 8. If anything here conflicts with the actual codebase, **stop and ask** before proceeding.

---

## §0 — Required Reading & Current-State Facts (do this before Step 0)

Read these in full first:
```
markdown-instructions/POLISH_AND_IMPROVEMENTS_v0.6.1.md   (Items 0–5; Item 0's validation gate applies here)
markdown-instructions/IMPLEMENTATION_PLAN_v2.md           (Transactions page, manual entry, combined-stats model)
markdown-instructions/MASTER_DEBUG_AND_TEST_RUN.md        (you will ADD a Section to this in Step 8)
CHANGELOG.md                                              (confirm 0.6.4 is the head; you bump to 0.7.0)
AI-WORKSPACE.md  (repo root)                               (my global workflow, skills, research, and verify conventions)
README.md        (repo root)                               (privacy model + supported-broker list to update at the end)
```

**Confirmed already-shipped (verify exists, then build ON it — never reimplement):**
- **Parser registry + auto-detection with confidence scoring** (`backend/.../parsers/registry.py`).
  11 named parsers: Wealthsimple, Questrade, RBC, CIBC, TD, BMO, Scotiabank, Interactive Brokers,
  National Bank, Fidelity, HSBC. Wealthsimple + Questrade have hard regression tests — keep green.
- **`Transaction` dataclass** (multi-currency: `local_currency`, `gross_amount`, `commission`,
  `net_amount`, `fx_rate_to_cad`, `net_cad`, plus `account_type`, `isin`, `exchange`, `source_file`,
  `source_broker`, `raw_row`). **Reuse this exact model** — generic rows are ordinary `Transaction`s.
- **`FXService.populate_transaction()`** — in-file rate → BoC live → static fallback. Route generic rows
  through it; never write `net_cad = null`.
- **SHA-256 dedup in `store.py`** (`date + action + raw_symbol + qty + net_amount + account_number`,
  `INSERT OR IGNORE`). Generic rows dedupe identically.
- **Item 0 pre-insert validation** — coerces dates with `pd.to_datetime(errors="coerce")`, rejects
  NaN/Inf/NaT numerics, imports only valid rows, returns a skipped-rows summary, and guarantees
  `/api/portfolio` never 500s. **Generic imports MUST pass through this same gate.**
- **Upload flow** already accepts `.csv .tsv .xlsx .xls .pdf`, shows detected broker + confidence,
  and previews the first 5 parsed rows. Step 7 extends this preview into an *editable* mapping editor
  for the low-confidence / generic path only.
- **Crash recovery / factory reset** (Item 0) — never lock the user out.

**Critical build lessons (from 0.6.3 / 0.6.4 — apply to every step):**
- `electron-builder.yml` packs `frontend/dist/` directly. **Always `npm run build` in `frontend/`
  before packaging.** Never trust a stale repo-root `dist/`.
- A passing unit suite is not proof. 0.6.3 shipped 120 green tests with 3 bugs still live in the
  packaged app. **Verify the actual running app.**
- On Windows, SQLite file handles must be released before deleting DB files:
  `checkpoint_wal → dispose_engine → gc.collect() → _force_rmtree (retry/backoff)`.

---

## §1 — What "Universal Import" Means Here

The importer today handles 11 *named* institutions. Anything else either fails or mis-detects.
The goal: a user (you) can export a transaction report from **any** brokerage or bank — Questrade,
CIBC, Wealthsimple, RBC, or something never seen — **or hand-build a CSV/XLSX with real or fictitious
rows**, and the app will locate the table, recognize the columns, map them to the canonical schema,
import accurately, and **clearly surface anything missing or uncertain** rather than silently dropping
or misclassifying it.

Design priorities, in order: **correctness → resilience → modularity → traceability → graceful
fallback → maintainability → extensibility.** Favor deterministic mapping where possible; route
everything uncertain to human review rather than guessing silently.

**Scope guardrail:** Make **CSV and Excel** rock-solid first. PDF is a lower-priority later sub-module
(Step 6 wires `pdfplumber` table extraction into the same pipeline; do not let PDF edge cases stall
CSV/XLSX). QIF/OFX/QFX/CAMT are explicitly **out of scope** for 0.7.0 (noted only as a possible future
extension — see §9).

---

## §2 — Refined Layered Architecture

Keep the named-parser fast path exactly as-is. Add the generic pipeline as a parallel, lowest-priority
lane that shares the canonical schema, FX, dedup, validation, and persistence with the named lane.

```
                         ┌────────────────────────────────────────────┐
  Uploaded file ───────► │  Auto-detection (existing)                  │
                         │  run all named detect(); pick max ≥ 0.50    │
                         └───────────────┬─────────────────┬───────────┘
                              high conf  │                 │  no named parser ≥ 0.50
                              (named)    ▼                 ▼  (generic lane)
                    ┌──────────────────────────┐   ┌─────────────────────────────────────┐
                    │ Named parser (UNCHANGED)  │   │ 1. File-reader adapter              │
                    │  → list[Transaction]      │   │    csv/tsv/xls/xlsx/xlsm (+pdf S6)  │
                    └────────────┬──────────────┘   │ 2. Table extractor                  │
                                 │                   │    (sheet/table boundaries)         │
                                 │                   │ 3. Header detector                  │
                                 │                   │    (score rows vs alias dict)       │
                                 │                   │ 4. Column classifier                │
                                 │                   │    (alias + fuzzy + value profiling)│
                                 │                   │ 5. Row normalizer                   │
                                 │                   │    (dates/signs/tickers/ccy/qty)    │
                                 │                   │ 6. Transaction classifier           │
                                 │                   │    (map/infer action; confidence)   │
                                 │                   │ 7. Validator (min-schema + Item 0)  │
                                 │                   │ 8. Import-preview generator         │
                                 │                   │    (mapping + sample + confidence)  │
                                 │                   └──────────────┬──────────────────────┘
                                 │                                  │ (editable mapping preview, Step 7)
                                 ▼                                  ▼
                    ┌───────────────────────────────────────────────────────────────────┐
                    │  Shared back half (EXISTING — reused by both lanes):               │
                    │  FXService.populate_transaction → Item 0 validation → SHA-256       │
                    │  dedup → store (persistence) → diagnostics/error reporter           │
                    └───────────────────────────────────────────────────────────────────┘
```

This **keeps the project's existing 10-stage mental model** (file reader → table extractor → header
detector → column classifier → row normalizer → transaction classifier → validator → preview
generator → persistence writer → diagnostics reporter) but explicitly forks it from auto-detection so
the named lane is untouched and the generic lane is a clean, testable module set. No better layering was
found that justifies disrupting the shipped named lane.

**New module layout (suggested):**
```
backend/.../import_engine/
  canonical.py        # canonical field enum + minimum-schema ruleset (§4)
  aliases.py          # bilingual EN/FR header alias dictionary (data-driven)
  readers.py          # file-reader adapters: csv/tsv/xls/xlsx/xlsm (+pdf in S6)
  table_extract.py    # find-the-table + find-the-header-row scoring
  classify_columns.py # alias + fuzzy + value-profiling → {canonical: col_index} + confidence
  normalize.py        # date/sign/ticker/currency/quantity/price normalization helpers
  classify_tx.py      # action mapping + inference + per-row confidence + flags
  generic_parser.py   # GenericParser(BaseParser): orchestrates the above; lowest registry priority
  diagnostics.py      # ImportDiagnostics dataclass + summary builder (§5)
backend/tests/
  test_universal_*.py # one file per layer + an integration file
test_data/generic/    # NEW messy/unknown fixtures (§6)
```

---

## §3 — Mapping Strategy for Unknown Institutions & Malformed Files

**Header recognition (deterministic first, fuzzy second):**
1. **Alias dictionary (`aliases.py`)** — data-driven `{canonical_field: [labels...]}`, bilingual EN/FR,
   case/space/punct-insensitive. Seed from the synonyms in §4 and from what the named parsers already
   key off. Exact/normalized alias hit = highest-confidence mapping.
2. **Fuzzy matching** — when no exact alias, score candidate↔alias with token-set ratio + Levenshtein
   (use `rapidfuzz`; pure-Python, fast, MIT — confirm/add to requirements). Accept above a tuned
   threshold; otherwise leave the column unmapped and flag it.
3. **Value profiling (the tie-breaker)** — independent of the header text, profile each column's *values*:
   date-like (parseable dates), currency/amount-like (numeric with `$`, commas, brackets, debit/credit),
   quantity-like (small signed numerics), ticker-like (1–6 uppercase, optional `.TO`/exchange suffix),
   enum-like (small set of repeated text → likely `action`), ISIN-like (`[A-Z]{2}[A-Z0-9]{9}[0-9]`).
   Profiling **confirms or overrides** a weak header guess and is what lets a header-less or garbled file
   still map.

**Find-the-header-row:** never assume row 1. Score each of the first N rows by how many cells match
aliases/value-profiles; the best-scoring row is the header, everything above it is preamble to skip.
Suppress repeated header rows mid-file; drop subtotal/disclaimer/footer rows.

**Find-the-table:** Excel → pick the sheet whose densest rectangular region best matches a transaction
table (prefer a sheet named like Activities/Transactions/Trade History; ignore summary/pivot sheets).
CSV → strip BOM, sniff delimiter (`,` `\t` `;` `|`), skip leading metadata lines.

**When the institution is unidentifiable:** still run the full generic lane. Set
`broker = <detected name from file text if any> else "Imported (Generic)"`. The rows import under a
**"Imported (Generic)"** source group on the Transactions page, visually distinct from named brokers.

**When columns are missing:** compute the **minimum viable record shape** (§4), derive what can be
derived (e.g. `net_amount = quantity × price ± commission`), and for anything that blocks downstream
math, **store the row in a recoverable flagged state** and report exactly which field is missing — never
silently drop.

---

## §4 — Canonical Schema & Per-Transaction-Type Minimum Fields

**Canonical action set** (map every source label into one of these; preserve `raw_row` for traceability):
`contribution, withdrawal, buy, sell, dividend, fee, interest, transfer_in, transfer_out,
reinvest_drip, split, corporate_action, journal, return_of_capital, tax_withholding,
cash_adjustment`.

**Header synonyms to seed `aliases.py` (bilingual):**
- `transaction_date` ← date, trade date, transaction date, settlement date, run date,
  date d'exécution, date de règlement, date de transaction
- `action` ← action, activity, activity type, transaction type, type, type d'opération
- `ticker` ← symbol, ticker, security, security symbol, titre, symbole
- `security_name` ← description, security name, name, désignation, description du titre
- `quantity` ← qty, quantity, shares, units, quantité, parts
- `price` ← price, trade price, unit price, prix, cours
- `gross_amount` ← gross amount, gross, principal, montant brut
- `commission` ← commission, fee, fees, comm, frais, commission/fee
- `net_amount` ← amount, net amount, net, net settlement, proceeds, value, montant net, montant
- `debit` / `credit` ← debit/débit, credit/crédit  (→ combine into signed `net_amount`)
- `currency` ← currency, ccy, devise
- `account` ← account, account #, account number, compte, n° de compte
- `account_type` ← account type, registered account, type de compte
- `settlement_date` ← settlement date, date de règlement
- `isin` ← isin, security id

**Global minimum (every row):** a parseable **`transaction_date`** AND **either** an explicit
**`action`** (mapped) **or** enough signal to infer one with strong confidence (signed amount +
quantity + symbol presence). A row missing both date and any inferable type → **unmapped / review**.

**Per-type minimum-field ruleset** (Required / Derivable / Recommended / Triggers review-if-absent):

| Canonical action | Required | Derivable | Recommended | Review if absent |
|---|---|---|---|---|
| contribution / withdrawal | date, net_amount (signed) | action from amount sign | account, currency | net_amount unparseable |
| buy / sell | date, ticker **or** security_name, and 2 of {quantity, price, net_amount} | the 3rd of {qty, price, amount}; action from amount sign | commission, account_type, currency, settlement_date | only one of {qty,price,amount}; no security identifier |
| dividend / distribution | date, net_amount (>0) | ticker from security_name if resolvable | ticker, currency | no amount |
| reinvest / DRIP | date, ticker **or** name, quantity | price/amount if the other exists | commission | no quantity AND no amount |
| fee / commission | date, net_amount (<0) | — | ticker (if security-specific) | no amount |
| interest | date, net_amount (>0) | — | currency | no amount |
| transfer_in / transfer_out | date, and (ticker+quantity) **or** net_amount | direction from sign/label | account, account_type | neither security+qty nor amount |
| split / reverse split | date, ticker **or** name, and split ratio **or** pre/post quantity clue | ratio from pre/post qty | exchange | no ratio AND no qty clue |
| corporate_action | date, ticker **or** name | — | description | no security identifier |
| journal / share transfer | date, ticker **or** name, quantity | — | account_type, counter-account | no quantity |
| return_of_capital | date, ticker **or** name, net_amount | — | — | no amount |
| tax / withholding | date, net_amount (<0) | — | ticker, currency | no amount |
| cash_adjustment / misc | date, net_amount | action = cash_adjustment fallback | description | no amount AND no date |

**Derivation rules (apply in normalizer, log every derivation in diagnostics):**
- amount missing, qty & price present → `net_amount = qty × price` (± commission if known)
- price missing, qty & amount present → `price = (amount ∓ commission) / qty`
- action missing → infer from signed amount + symbol/qty presence + memo keywords
- ticker missing, security_name present → attempt resolution via existing dynamic ticker resolver; if
  unresolved, keep `security_name`, leave `ticker` empty, flag as "mapped with assumption"
- quantity missing on contribution/withdrawal/fee/interest/dividend/tax → **valid**, not an error

---

## §5 — Confidence Scoring & Diagnostics Strategy

**Two confidence layers:**
1. **Mapping confidence** (per file): function of how many canonical fields were resolved, the strength
   of each match (exact alias > fuzzy > value-profile-only), and header-row score. One overall 0–1 plus
   per-column scores.
2. **Row classification confidence** (per row): how cleanly the row maps to a canonical action and meets
   that type's minimum fields.

**Four-state per-row outcome (surface all four, never collapse silently):**
- **confidently mapped** — all required fields present, action certain.
- **mapped with assumptions** — imported, but ≥1 field inferred/derived (e.g. action inferred from sign,
  ticker resolved from name). Record exactly which assumptions.
- **partially mapped** — imported in a recoverable flagged state; identifies which missing field blocks
  which downstream calc (ACB, capital gains, period return).
- **unmapped** — could not classify; **kept** in a quarantine/recoverable state, never dropped.

**`ImportDiagnostics` (returned to the UI, answers the four required questions):**
1. *What was confidently identified?* — counts per state, detected institution, header row index,
   `{canonical_field → source column}` map with per-field confidence.
2. *What was inferred?* — per-row list of assumptions/derivations.
3. *What is missing?* — per-row list of absent required fields and the downstream calc each blocks.
4. *Minimum user correction needed?* — the smallest set of column re-assignments / field fills that
   would move rows from partial/unmapped → mapped (drives the Step 7 editor).

Make it **auditable and repeatable**: same file in → same mapping + same diagnostics out (deterministic;
fuzzy thresholds fixed, no randomness). Persist the chosen mapping per (institution-fingerprint) so a
re-import of the same layout reuses the confirmed mapping.

---

## §6 — Implementation Steps (one commit each; test + visually verify after each)

> Step 0 is research only — STOP for approval after it. Steps 1–8 proceed after approval.

**Step 0 — Research (NO CODE).** Per AI-WORKSPACE: **check `.claude/skills/` first** (use §7's list),
then study: `afadil/wealthfolio` CSV column-mapping UI + field-alias logic (primary reference);
`ghostfolio/ghostfolio` header normalization; `pdfplumber` table extraction (already bundled — prefer
it over camelot/tabula which need Java/Ghostscript); GitHub searches `bank statement parser python`,
`csv column mapping fuzzy header`, `transaction importer header detection`; and evaluate `rapidfuzz`
and `Actual Budget`'s field-mapping/dedup approach (reference only — see §8). Deliverable: a research
summary + the concrete architecture you'll build (confirm or adjust §2–§5). **Then stop and wait.**
*No commit (or `docs:` commit for the research note only).*

**Step 1 — Canonical schema + alias dictionary.** `canonical.py` (action enum + §4 min-schema ruleset)
and `aliases.py` (bilingual dict). Pure data + helpers; unit-test alias normalization (case/space/FR).
Commit: `feat(import): canonical schema, min-schema ruleset, and bilingual header alias dictionary`

**Step 2 — File-reader adapters + table extraction.** `readers.py` + `table_extract.py`: BOM strip,
delimiter sniff, leading-metadata skip, Excel sheet selection, **find-the-header-row** scoring, repeated-
header suppression, subtotal/footer drop. Test against ALL existing fixtures + new messy ones.
Commit: `feat(import): universal file readers and table/header extraction for csv/tsv/xls/xlsx`

**Step 3 — Column classifier + confidence.** `classify_columns.py`: alias → fuzzy (`rapidfuzz`) →
value-profiling → `{canonical: col_index}` + per-column + overall confidence. Enforce the §4 minimum
viable mapping. Unit-test on headers that are renamed, reordered, bilingual, and partly missing.
Commit: `feat(import): column mapping via alias + fuzzy + value profiling with confidence scores`

**Step 4 — Row normalizer + transaction classifier.** `normalize.py` + `classify_tx.py`: standardize
dates, sign conventions, tickers, currencies, qty precision, prices; handle debit/credit, single-net,
bracketed/negative; map+infer action; apply derivations; assign the four-state outcome + flags.
Commit: `feat(import): row normalization, action inference, and per-row confidence classification`

**Step 5 — GenericParser (lowest-priority fallback).** `generic_parser.py` implementing `BaseParser`,
registered **last** so named parsers always win. Outputs ordinary `Transaction`s; `broker` =
detected-name-or-"Imported (Generic)"; routes through `FXService.populate_transaction` → **Item 0
validation** → SHA-256 dedup → store. Build `ImportDiagnostics` (§5). Tests: an unknown fixture parses;
**every named fixture is NOT hijacked** (registry-priority regression).
Commit: `feat(import): generic fallback parser for unknown institutions`

**Step 6 — PDF into the same pipeline (lower priority).** `pdfplumber` table extraction feeding the same
table-extract → classify → normalize path; concatenate matching-header tables; multi-page; text+regex
fallback when table extraction yields nothing. Test against the existing RBC/TD/CIBC PDF fixtures via
the *generic* lane (named PDF parsers still own them).
Commit: `feat(import): pdf table extraction wired into the universal pipeline`

**Step 7 — Editable column-mapping preview (THE safety net).** For generic / low-confidence imports
only: show detected `{canonical → column}`, a 5–10 row preview, the four-state per-row badges, and the
ImportDiagnostics summary; let the user reassign/ignore columns via dropdowns and **confirm before
import**. Reuse `ModalPortal` + existing upload-preview components; match the Bloomberg-derived dark/light
tokens. Named/high-confidence imports keep the current one-click flow. Playwright E2E: unknown fixture →
mapping editor → fix a wrong guess → confirm → rows land under "Imported (Generic)".
Commit: `feat(import): editable column-mapping preview and import diagnostics UI`

**Step 8 — Integration, regression, master-debug section, release.** All 11 named fixtures still route to
named parsers; generic rows feed dashboard combined views, ACB, capital gains, currency exposure; dedup
holds across generic + named + manual. Add **Section 6b — Universal / Generic Import** to
`MASTER_DEBUG_AND_TEST_RUN.md`. Bump to **0.7.0**, update `CHANGELOG.md` and the README supported-import
section, rebuild `frontend/dist`, package the installer, run a Playwright probe against the **packaged**
app confirming the generic flow end-to-end, then prompt me to run the full Master Debug Test.
Commit: `test(import): universal-import integration + regression; docs + 0.7.0 release`

---

## §7 — Claude Skills to Pull (from `claude-skills-main`)

Source: local clone at `C:\Users\ematthew\Desktop\Apps\Coding\claude-skills-main`
(= https://github.com/alirezarezvani/claude-skills, ~338 skills / 16 domains). Per AI-WORKSPACE,
**check `.claude/skills/` first and prefer skills already added.** The finance area there is small;
prioritize engineering/testing/data-reliability skills.

In Step 0, **inventory the repo** (`ls` the skill folders, read each candidate `SKILL.md`) and copy the
genuinely useful ones into `.claude/skills/`. Target capabilities (match to whatever the repo actually
names them — don't assume exact titles):
- **Data import / parsing reliability** — CSV/Excel ingestion, schema inference, messy-data cleaning,
  encoding/delimiter handling. (Highest priority — core to Item 4.)
- **Fuzzy matching / string similarity** — anything wrapping `rapidfuzz`/Levenshtein/token-set.
- **PDF table extraction** — `pdfplumber`-oriented skills for Step 6.
- **Python testing / pytest / fixtures** — fixture design, regression-suite structure, edge-case tables.
- **Playwright / E2E** — for the Step 7 mapping-editor probe and packaged-app verification.
- **Backend/API architecture** — FastAPI endpoint + Pydantic/response-shape patterns for the import route.
- **Frontend/React component architecture** — form/table/modal patterns for the mapping editor.
- **Observability / structured logging** — for the diagnostics reporter (local-only; no telemetry).
- **Code review / refactoring discipline** — to keep the generic lane from leaking into the named lane.

Already-added skills: **use them where they apply** rather than re-pulling or reinventing. In the Step 0
note, list (a) skills already present that you'll use, and (b) skills you pulled from `claude-skills-main`
and why. If a needed capability is missing and likely to recur, create a new skill under `.claude/skills/`.

---

## §8 — External GitHub Repos / Libraries / Patterns to Review

Reference only — borrow patterns, do not copy wholesale; note provenance in commit + CHANGELOG.
- **`afadil/wealthfolio`** — *primary.* User-driven CSV column-mapping UI + field-alias logic → models
  Steps 3 and 7. Also its `ActivityImport` dedup (cross-check `store.py`).
- **`ghostfolio/ghostfolio`** — flexible CSV import with header normalization; arbitrary column → internal
  schema mapping.
- **`pdfplumber`** (already bundled) — table extraction for Step 6; prefer over `camelot-py`/`tabula-py`
  (Java/Ghostscript deps — bad for a portable local `.exe`).
- **`rapidfuzz`** — fast MIT fuzzy matching for Step 3 (confirm in `requirements.txt`).
- **`actualbudget/actual`** — its importer maps fields, handles date-format/delimiter/inflow-outflow
  splits, and dedupes via imported IDs or date/amount/payee matching. Study the **mapping + dedup UX**;
  do not adopt its budgeting architecture.
- **GitHub searches:** `bank statement parser python`, `csv column mapping fuzzy header`,
  `transaction importer header detection`, `statement normalization brokerage python`.
- **`tsiemens/acb`, `dwrpayne/portfolio`** — already-used references; only to confirm generic rows feed
  ACB / FX-at-trade-date correctly (no new work).

---

## §9 — Integration Notes (clean fit into the existing Transactions section)

- **One ingestion contract.** Generic output is the same `Transaction` dataclass; everything downstream
  (FX, validation, dedup, ACB, dashboard, currency exposure) is untouched and just works.
- **Registry priority is the safety boundary.** `GenericParser` is registered **last**; a named
  `detect() ≥ 0.50` always wins. Add a registry-order regression test so a future edit can't reorder it.
- **New source group only.** Generic rows surface under **"Imported (Generic)"** on the Transactions page
  (which already separates by source), visually distinct from named brokers and from "Manual". On the
  dashboard they combine like any other source — no dashboard changes needed.
- **Validation gate is mandatory.** Generic rows pass Item 0 pre-insert validation; a malformed generic
  file can never persist portfolio-breaking rows or 500 `/api/portfolio`.
- **Dedup unchanged.** Same SHA-256 key; importing the same unknown file twice adds zero rows; an unknown
  export overlapping a named one dedupes correctly.
- **No new routing / no parallel pipeline.** Extend the existing `POST /api/import` and upload UI; the
  mapping editor is an additional state of the existing preview, not a second importer.
- **Future extension (out of scope for 0.7.0):** QIF/OFX/QFX/CAMT readers and direct broker connections
  (the latter is already deferred in IMPLEMENTATION_PLAN_v2). Leave clean seams; build neither now.

---

## §10 — Item 4 Verification (the gate to call 0.7.0 done)
- [ ] Unknown-institution CSV imports correctly after mapping confirmation; a hand-built CSV with
      fictitious rows imports and is correctly classified.
- [ ] Unknown XLSX/XLSM (preamble rows, merged headers, multi-sheet) imports; header row found, not assumed.
- [ ] PDF generic path extracts an unknown statement (Step 6) — lower priority but functional.
- [ ] All 11 named brokers unchanged — registry-priority + Wealthsimple/Questrade regression tests green.
- [ ] Missing-field handling: a file lacking a column reports exactly what's missing and what it blocks;
      rows are flagged/recoverable, never silently dropped.
- [ ] Derivations work: amount from qty×price; action from sign; ticker from name where resolvable.
- [ ] Four-state diagnostics surface in the UI; the mapping editor corrects a wrong guess and re-imports.
- [ ] Generic imports pass Item 0 validation — a malformed generic file never bricks the app.
- [ ] `pytest backend/tests/ -v` 0 failures; `npx tsc --noEmit` 0 errors; verified in the **packaged** app.
- [ ] `CHANGELOG.md` → 0.7.0; README supported-import section updated; `frontend/dist` rebuilt before packaging.

## Reminders
- Step 0 research first — **stop for approval** before any Step 1+ code.
- Approach note before each step; commit per step; test + visually verify after each.
- Named parsers are sacred — generic is the lowest-priority fallback.
- Never persist data that can later 500 the portfolio endpoint; never drop a row silently.
- The editable mapping preview is the guard against silent mis-parsing — not optional.
- Do NOT implement direct broker connections — still deferred.
