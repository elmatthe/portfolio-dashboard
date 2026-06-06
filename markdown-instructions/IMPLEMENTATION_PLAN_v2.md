# Portfolio Dashboard — Implementation Plan v2
**Current version: 0.5.3**

> **READ THIS FIRST — Instructions for Claude Code**
>
> This plan picks up exactly where v0.5.3 left off. The codebase is mature. Your job is to:
> 1. Read this document **end-to-end** before writing any code.
> 2. Run **Phase 0 — Current-State Verification** and report findings before implementing anything. Do **not** rebuild shipped features.
> 3. Break each phase into a granular sub-task todo list. Each phase is a milestone, not a single commit.
> 4. After every logical unit of work, **run the test suite and visually verify the UI in the running app** before moving on. Compile passing is not enough — confirm the feature is reachable and usable in the Electron renderer.
> 5. Commit per sub-task with clear messages. Never bundle multiple phases into one commit. Update `CHANGELOG.md` as you land each change.
> 6. If anything in the existing codebase contradicts an assumption here, **stop and ask** before proceeding.
>
> Work phases **in order**: Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 5.

---

## What Has Already Been Shipped (do NOT rebuild)

The following are confirmed shipped as of v0.5.3. Verify each exists, then move on:

- Multi-broker import (Questrade, Wealthsimple, RBC, CIBC, TD, BMO, Scotia, Interactive Brokers, National Bank, Fidelity, HSBC, National Bank) via parser registry with auto-detection and confidence scoring.
- Multi-currency support (CAD, USD, GBP, EUR, JPY, AUD, CHF, HKD, SEK, NOK) with `FXService` (in-file rate → BoC live → static fallback). FX populated on every transaction via `FXService.populate_transaction()`.
- Multi-account model (TFSA / Margin / RRSP / RESP / Non-Reg) with per-account tabs and Combined view; currency view toggle (Combined CAD / Combined USD / CAD-only / USD-only).
- Per-profile isolated SQLite, profile switcher with accent colors, Electron desktop packaging.
- Shared `ModalPortal` at `frontend/src/components/ModalPortal.tsx` — all five modals (Settings, Reports, Simulator, Alerts, AddProfile) use it. **All modal-positioning bugs are fixed as of v0.5.3.**
- Modified-Dietz period returns, period clamping to first-tx date with `period_clamped` flag and `Since MMM YYYY` chip display. **These are fixed and working as of v0.5.3.**
- Upload flow: `.csv`, `.tsv`, `.xlsx`, `.xls`, `.pdf` accepted; auto-detection with confidence display; preview table of first 5 parsed rows.
- Transaction table with toggleable columns: Local Currency, Local Amount, FX Rate to CAD, CAD Equivalent, ISIN, Account Type, Settlement Date.
- Currency Exposure widget, broker breakdown pie, account-type breakdown, "View in" currency selector.
- Filters & search: broker, account type, currency, ticker, action, date range picker, text search on ticker + security name.
- SHA-256 dedup in `store.py` — re-importing the same file inserts zero new rows.
- CRA-compliant ACB engine — per-security per-account, superficial loss rule, commission in cost basis.
- Settings, Reports, Simulator, Alerts, Rebalancing Advisor, What-If Simulator, Price Alerts, TFSA Contribution Room Tracker, Annual PDF Report, Dividend Calendar, Portfolio Value Over Time chart, S&P 500 benchmark overlay, Correlation Matrix, Performance Attribution.
- Light/dark mode toggle.
- TFSA CAD-only view showing correct Net Deposits, Total P&L, and Simple ROR. **Fixed in v0.5.3.**

---

## Reference Repositories (study before writing new code)

These repos were used to build the existing codebase. Re-consult them for the new phases — they contain patterns directly applicable to Phases 1–3.

### Tier 1 — Highest Relevance

**`tsiemens/acb`** — https://github.com/tsiemens/acb
- For Phase 2 (manual entry): verify the existing `acb.py` walk still matches the tsiemens order-of-operations when a manually-entered buy or sell is inserted out of chronological order relative to imported rows. The superficial-loss 30-day window must hold across mixed manual + imported rows.
- The BoC historical FX rate call is the live-data source for `FXService` — manual entries at historical dates must use the date-of-trade rate, not today's rate.

**`wealthfolio/wealthfolio`** — https://github.com/afadil/wealthfolio
- `apps/frontend/src/features/activity/`: **the architectural model for Phase 1** (Transactions page). Study the import flow's source separation, filter/sort UI, and empty states.
- Deduplication strategy in `ActivityImport` — compare against `store.py` and adopt improvements for Phase 2's manual-entry dedup path.
- `apps/frontend/src/features/holdings/`: currency badge implementation — relevant if Phase 2's form needs live derived-value display.

**`dwrpayne/portfolio`** — https://github.com/dwrpayne/portfolio
- Currency-date logic for Phase 2: each manual entry must store the FX rate at the time of the trade. Never today's rate. The `net_cad` column must be non-null when the form saves.
- ACB ledger model — cross-reference with `acb.py` to confirm per-`(security, account)` separation holds when a manual row is inserted between two imported rows.

### Tier 2 — Specific Patterns

**`ghostfolio/ghostfolio`** — https://github.com/ghostfolio/ghostfolio
- For Phase 3 (combined-stats check): how it presents per-currency breakdowns alongside CAD totals — model any combined-view gaps on the `GET /api/portfolio` response shape.
- `PortfolioCalculator` ROAI across multiple time windows — useful if Modified-Dietz edge cases surface during the manual-entry integration test.

**Bloomberg-Inspired Dark Dashboard** — GitHub search: `bloomberg-terminal stock-dashboard react recharts vite dark-theme finance-management`
- CSS variable system — any new UI for Phases 1–2 (Transactions page, Add Transaction modal) must match the existing palette. Re-examine before adding new components.

---

## Guiding Principles (every phase)

- **Test continuously.** After each sub-task: run `pytest tests/ -v`, launch the app, confirm the change is visible and functional. Keep Wealthsimple + Questrade regression tests green at all times.
- **UI visibility is first-class.** A feature that exists in code but isn't reachable in the renderer is not done.
- **Don't break what works.** The dashboard, imports, ACB engine, FX, profiles, and all v0.5.x fixes must keep working at every step.
- **Reuse existing primitives.** Route everything through: `ModalPortal`, the `Transaction` dataclass, `FXService.populate_transaction()`, SHA-256 dedup in `store.py`, per-`(ticker, account_type)` grouping, dynamic ticker resolution, and the ACB engine. No parallel implementations.
- **Local-first & private.** No telemetry, no remote logging, no committing caches / credentials / user DBs.
- **Incremental & reversible.** Small commits, independently revertable.

---

## Phase 0 — Current-State Verification

Before writing any code, confirm the following and report findings:

1. Is there a **dedicated Transactions landing page** that keeps imported activity **separated by source/institution** for review? Or does transaction data today only surface inside per-account tabs / Excel export? (Phase 1 target.)
2. Is there any **manual transaction entry** path today? (Expected: no — Phase 2 target.)
3. Confirm all shipped features listed above are actually present and working in the renderer — not just in code.

**Deliverable:** a short written summary of what exists vs. what's genuinely missing, plus your proposed sub-task breakdown for Phase 1. Flag surprises before continuing.

---

## Phase 1 — Dedicated Transactions Page

**Goal:** A dedicated Transactions section where the user reviews all activity, with data **separated by source/institution** (Questrade ≠ Wealthsimple ≠ RBC ≠ … ≠ Manual). This is the detailed source-level record; the dashboard is where things combine.

> If Phase 0 finds this already exists in some form, scope this phase to "verify + extend to add a Manual source group" and move on.

### Sub-tasks

1. Add a **Transactions** section to the existing navigation. Reuse the current nav/section pattern — do not introduce a second routing system.
2. Build a clear, scannable transaction table. Reuse/extend the existing transaction columns and the toggleable column set already in the codebase (Local Currency, Local Amount, FX Rate to CAD, CAD Equivalent, ISIN, Account Type, Settlement Date).
3. **Separate by source:** group/filter transactions by source institution (tabs or a source filter). Each broker is distinct; **manual entries appear as their own "Manual" source group** (pre-wired for Phase 2).
4. Within a source: filter by account, account type, currency, ticker, action (buy/sell/dividend/transfer/fee); sort by date/amount; text search on ticker + security name; date-range picker (default current year).
5. Make rows (or source groups) **clickable to drill into detail** — this verification flow is the page's core purpose.
6. Clear empty states per source ("No Questrade transactions imported yet") and a per-source summary count.

**Reference:** model on `wealthfolio/wealthfolio` `apps/frontend/src/features/activity/` for the source-separated layout and filter UI.

### Testing

- Confirm the page is reachable from the nav and renders under its own route.
- Import sample files from multiple institutions; confirm each appears under the correct source. Re-import produces **no duplicates** (existing SHA-256 dedup).
- Confirm filters, sort, search, drill-in all work.
- Run full suite incl. Wealthsimple + Questrade regression tests.

---

## Phase 2 — Manual Transaction Entry

**Goal:** Let the user enter transactions by hand — as a third input path alongside file import. Manual entries must flow through the **same** model, storage, dedup, FX, and ACB pipeline as imported ones. They are first-class transactions, just with a `Manual` source.

### Wire into existing systems (do NOT fork them)

- **Data model:** reuse the existing `Transaction` dataclass. Set `broker`/`source_broker = "Manual"` (or the enum value) and `source_file = "manual-entry"`. Populate `parsed_at`, `raw_row` (form payload) for debugging consistency.
- **Storage + dedup:** insert via the same `store.py` path with the same SHA-256 dedup. Because manual rows are user-authored, give them a stable id and treat them as **editable/deletable** (imported rows stay read-only).
- **FX:** call `FXService.populate_transaction()` (or `rate_to_cad(currency, trade_date)`) so `fx_rate_to_cad` and `net_cad` are filled **at the transaction date** — never today's rate. Same CRA-correct rule as all other transactions.
- **Ticker resolution:** run the entered ticker through the existing dynamic resolver / `ticker_map` so prices, sparklines, and ACB work like any imported holding.
- **ACB:** manual buys/sells must enter the same per-`(security, account)` ACB walk, including commission in cost basis and the superficial-loss rule. A manual sell must produce a correct `RealizedGain`. Cross-reference `tsiemens/acb` order-of-operations to confirm insertion between existing rows doesn't break the walk.
- **UI primitive:** build the entry form as a modal using the existing **`ModalPortal`** — do not hand-roll a new overlay. That's exactly the bug class v0.5.2/v0.5.3 fixed.

### UI sub-tasks

1. Add a visible **"Add Transaction"** button on the Transactions page (and optionally on a per-account view). Opens a `ModalPortal` form.
2. Build the form with sensible grouping and defaults:
   - **Required:** date, account (existing account picker) + account type, action (buy / sell / dividend / deposit / withdrawal / transfer / fee), ticker (for security actions), quantity, price, local currency, commission.
   - **Derived/shown live:** gross, net, FX rate to CAD (looked up from the date), CAD equivalent — show these computed values before saving.
   - **Optional:** security name (auto-filled from ticker resolution), settlement date, ISIN, exchange, reference id, notes.
   - Source is fixed to **Manual** and shown as a read-only badge.
3. **Validation:** required-field checks; numeric and non-negative where appropriate; action-conditional fields; currency from the supported list; date not in the future (warn, allow override). Disable Save until valid; show inline errors.
4. **Defaults to reduce friction:** default date = today, default currency = profile's default-currency setting, default account = last-used. Remember last-used account/currency within the session.
5. On save: insert via the shared pipeline → dedup → populate FX → update ACB → refresh the Transactions table and dashboard so the new row appears immediately under the **Manual** source group.
6. **Edit & delete:** allow editing/deleting manual entries (confirm on delete). Editing re-runs FX/ACB. Deleting must correctly unwind ACB/realized-gain effects. Make clear in the UI that only manual entries are editable.
7. Optional (only if cheap): a "duplicate last entry" affordance for users entering several similar rows.

### Edge cases

- Manual sell exceeding held quantity in that account → block with a clear error.
- Manual entry in a currency with no static rate and no live rate available offline → fall back to static table / prompt; never silently store `net_cad = null`.
- Manual dividend/deposit with no ticker → classify by shape (symbol + net>0 → dividend; no symbol + net>0 → deposit) consistent with the existing parser.
- Manual entry whose date predates the active period window → still counts toward ACB and combined stats; period clamping handles display.

### Testing

- Add a manual **buy** → appears under Manual source group, correct FX/CAD, ACB and dashboard stats update.
- Add a manual **sell** → correct `RealizedGain` incl. superficial-loss; TFSA sell shows $0 tax in Simulator.
- Add a manual **dividend** and **deposit** → correct classification, Net Deposits / income tracking update.
- Edit a manual entry → FX/ACB/stats recompute. Delete one → clean unwind.
- Add a manual entry that duplicates an imported one → dedup behavior is sensible and documented.
- Confirm the form uses `ModalPortal`, opens centered (not pinned in the header), closes on Escape + backdrop, has ARIA attributes.
- Automated tests: manual-entry insert, FX population, ACB effect, dedup, edit, delete-unwind, over-sell guard.

---

## Phase 3 — Combined-Stats Integration Check

**Goal:** Confirm that all sources — every imported broker and manual entries — flow correctly into the dashboard's existing **individual / by-type / combined** views. The Transactions page keeps sources separated; the Dashboard combines. Both behaviors must coexist.

### Sub-tasks

1. Verify manual + multi-broker data aggregate correctly across all three scopes (individual, by-type, combined) and all four currency-view modes (Combined CAD / Combined USD / CAD-only / USD-only) — the v0.5.3 TFSA CAD-only fix path must still hold.
2. Verify Modified-Dietz period returns treat manual deposits/withdrawals as cash flows (and manual TRANSFERs are excluded), and that period clamping still works when a manual entry is the earliest transaction in scope.
3. Confirm the broker breakdown pie / account-type breakdown include a **Manual** slice where applicable.

### Acceptance example (reproduce as a test)

- Questrade: 2 accounts (1 TFSA + 1 Margin). Wealthsimple: 5 accounts. Plus a handful of **manual** entries in, say, the TFSA.
- All 7 accounts appear on the dashboard; manual entries are folded into their account.
- Viewing individually, by type, and combined all produce correct stats; combined totals reconcile to the sum of individuals (within currency rules).

### Testing

- Reproduce the 7-account + manual example; reconcile combined == sum of individuals.
- Confirm the Transactions page stays source-separated and unaffected by dashboard combining.
- Switching scope/currency updates the UI instantly with no stale numbers.
- Automated tests for aggregation at all three scopes including manual rows.

---

## Phase 5 — Privacy & Local-First Hygiene

The app is already local-first (Electron + per-profile SQLite). Maintain and harden it as new code lands:

1. **No remote logging / telemetry.** All financial-data processing stays local; nothing phones home.
2. **Minimize on-disk artifacts.** No unnecessary caches of sensitive data; keep the "clear all data" action in Settings working and confirm it covers all new data paths added in Phases 1–3.
3. **`.gitignore` hardening.** Ensure `__pycache__/`, `*.pyc`, venvs, `.env`, token/credential stores, per-profile DBs, uploaded files, and `backend.log` are all ignored and not already tracked.
4. **Logging discipline.** Audit `backend.log` and any console output — no account numbers, balances, holdings, or credentials should appear. Redact where logging is genuinely needed.
5. **Document the privacy model** briefly in the README: what's stored, where, how to clear it.

### Testing

- Run a full flow (import → manual entry → view) and inspect filesystem + `git status`: no sensitive data, caches, or `__pycache__` written to unexpected places or staged.
- "Clear all data" in Settings removes all user data including any new paths from Phases 1–3.
- Logs contain no sensitive values.

---

## Final Regression & Acceptance Pass

- [ ] **Transactions page**: sources separated (each broker + Manual distinct); drill-in works; no duplicates on re-import.
- [ ] **Manual entry**: add/edit/delete via `ModalPortal`; FX populated at trade date; ACB + realized gains correct; over-sell blocked; dedup vs imports sensible; row appears under Manual source and flows into the dashboard.
- [ ] **Dashboard**: 7-account + manual example satisfies — all accounts visible; individual + by-type + combined correct across all four currency modes; combined == sum of individuals.
- [ ] Transactions page stays source-separated while Dashboard combines.
- [ ] File import still works as fully as before for all 11 supported brokers.
- [ ] Privacy: local-only, no telemetry, `.gitignore` hardened, "clear all data" works end-to-end.
- [ ] `pytest tests/ -v` passes (0 failures/errors); Wealthsimple + Questrade regression green; TypeScript 0 errors.
- [ ] Every new feature is **visible and usable in the renderer**, not just present in code.
- [ ] `CHANGELOG.md` and README updated.

---

## Deferred — Direct Broker Connections (do NOT implement now)

> ⚠️ This phase has been deliberately deferred to a separate Claude Code build session. The details below are preserved for reference.

**Scope:** Optional live sync so users can connect a broker and stop manually uploading files.

**Why deferred:** Higher risk, requires significant research into API availability (especially Wealthsimple, which has no official public API), and depends on Phases 1–3 being stable first.

**When ready to implement, restore this phase and address:**

1. **Questrade:** Official API (OAuth refresh-token flow, accounts + activities endpoints, rate limits, sandbox). Reference `tsiemens/acb`'s BoC pattern for FX/account-mapping conventions.
2. **Wealthsimple:** No broadly available official public API — document what's actually feasible, flag any unofficial/ToS-risky approach and its fragility **to the user before implementing**. Do not silently depend on a brittle method.
3. **Implementation (per approved connector):**
   - A Connections area: connect / status / disconnect, "Sync now," last-synced timestamp, clear error + re-auth states.
   - Store tokens **securely and locally only** (OS keychain or encrypted local store) — never plaintext, never committed, never logged, never sent off-device.
   - Map synced accounts + activity into the **same `Transaction` model** so they flow into the Transactions page (by source) and dashboard combined views exactly like imports.
   - Apply existing SHA-256 dedup so synced rows don't double-count against manual or file-imported rows.
   - Graceful token-expiry / network-failure handling with clear UI, not crashes.
4. **Testing:**
   - Use sandbox/test credentials only; never hardcode/commit real ones.
   - Synced transactions appear under the correct source and feed combined views; dedup holds across synced + manual + imported.
   - Disconnect removes tokens; expiry triggers a clean re-auth prompt.

---

## Open Questions to Resolve Before Starting

- Should manual entry be reachable from a per-account view in addition to the Transactions page? (Confirm placement — the plan assumes Transactions page primary, per-account optional.)
- Should manual entries be flagged visually in the combined dashboard (e.g. a small "manual" marker), or only distinguished on the Transactions page?
