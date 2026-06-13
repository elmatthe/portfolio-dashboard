# Portfolio Dashboard — Project Briefing

> **Living project overview.** A new AI session should be able to read this file
> and immediately understand the full project without re-explanation. Last
> updated **2026-06-12** after the 0.7.0 post-release audit bug-fix campaign and
> Master Debug run.

---

## 1. What the project is

**Portfolio Dashboard** is a local-first Windows desktop investment tracker.
It ingests transaction exports from **11 named brokers** (plus a universal
generic lane for any other institution), tracks holdings across **10
currencies** and **14 account types**, computes **CRA-compliant Adjusted Cost
Base** and capital gains, and renders a live dashboard with per-account and
per-currency views. Everything is stored locally in SQLite; the only network
calls are opt-in price (Yahoo Finance) and FX (Bank of Canada) lookups.

- GitHub: `elmatthe/portfolio-dashboard`
- **Current version: 0.7.0** (branch `feat/item4-universal-import`, NOT yet
  merged to `main`; `main` is at 0.6.4 locally / v0.5.3 at origin)
- Installer: `release/Portfolio Dashboard Setup 0.7.0.exe` (~200 MB NSIS,
  rebuilt 2026-06-12 with all audit bug fixes included)

## 2. Tech stack

| Layer | Stack |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy Core, SQLite (one DB per profile), pandas, pdfplumber, openpyxl, rapidfuzz, reportlab, matplotlib, yfinance |
| Frontend | React 18 + TypeScript + Vite, TanStack Query, Tailwind CSS, Recharts |
| Desktop | Electron 30; PyInstaller-bundled `backend.exe`; electron-builder NSIS installer |
| Tests | pytest (446 backend + 113 root), Playwright E2E vs the packaged build, `tsc --noEmit` |

Data lives at `%APPDATA%\Portfolio Dashboard\profiles\<id>\portfolio.db`.
The backend binds to `127.0.0.1` only (port 7842 preferred, OS-assigned fallback).

## 3. Architecture in one paragraph each

**Import.** Every dropped file goes through `POST /api/import/preview`. A
scored detector runs all named parsers' `detect()`; a confident named match
(≥ 0.70) short-circuits to the one-shot import flow. Anything else falls to the
**universal generic pipeline** (`backend/import_engine/`): readers for
CSV/TSV/XLSX/XLS/PDF → header+value column classification with per-field
confidence → row bucketing (Confident / Assumptions / Partial / Unmapped) →
an editable **column-mapping editor** modal when confidence is low → confirm
applies overrides and persists. Confirmed mappings are remembered per header
fingerprint. Dedup is a SHA-256 hash of
`transaction_date | action | raw_symbol | quantity(6dp) | net_amount(4dp) | account_number`
— re-importing any file inserts 0 new rows.

**FX.** `backend/fx/rates.py` `FXService`: in-file broker rate first, then Bank
of Canada Valet historical API (only when `FX_LIVE_RATES=true`), then a static
fallback table (USD 1.36, GBP 1.72, EUR 1.48, JPY 0.0091, AUD 0.89, CHF 1.50,
HKD 0.174, SEK 0.126, NOK 0.126). **Every transaction stores its own
`fx_rate_to_cad` and `net_cad` at trade date** — the CRA-correct approach.
`populate_transaction()` only fills missing values (imports keep broker rates).

**ACB / tax.** `backend/acb.py` walks transactions chronologically, pooled per
`(ticker, account_type)` (CRA pooling). Since BUG-002 it maintains a **parallel
CAD ledger**: CAD cost basis accumulates at acquisition-date FX, CAD proceeds
at disposition-date FX, so `total_gain_cad` is CRA-correct. Superficial-loss
denial (30-day window, inclusive) is computed and added back to repurchase ACB.
Since BUG-006, a display-only `shares_by_account` side ledger attributes each
holding's equity to its owning `account_number` — it never feeds tax math.

**Portfolio.** `backend/portfolio.py` builds holdings (live prices via
yfinance two-tier cache), aggregates per account and combined, computes
Modified-Dietz period returns with clamping, and since BUG-001 converts all 10
currencies to CAD-equivalent in aggregation (native CAD/USD buckets plus
`*_other_cad` buckets for the rest). Combined-CAD Total Equity =
`total_equity_cad + total_equity_usd × usd_cad + total_equity_other_cad`.

**Manual entry.** Full CRUD on manual transactions through the same dedup, FX,
and ACB pipelines as imports. Since BUG-005, edits re-derive
gross/net/FX/`net_cad` through the exact compute path used at create; the
row's SHA-256 hash is its immutable identity and never changes on edit.

## 4. Feature surface (what exists today)

- 11 named broker parsers: Questrade, Wealthsimple, RBC, CIBC, TD, BMO,
  Scotia iTRADE, Interactive Brokers, National Bank, Fidelity, HSBC — across
  CSV/TSV/XLSX/PDF — plus the universal generic lane (0.7.0).
- 10 currencies: CAD, USD, GBP, EUR, JPY, AUD, CHF, HKD, SEK, NOK.
- 14 account types incl. TFSA, RRSP, RESP, RRIF, Margin, Non-Registered,
  IRA/Roth/Traditional, FHSA, LIRA.
- Dashboard: per-account tabs + Combined, 4 currency views (Combined CAD /
  Combined USD / CAD-only / USD-only), period selector (1M…3Y/All) with
  Modified-Dietz returns, holdings cards, currency exposure, correlation
  matrix, attribution, portfolio-value history, S&P 500 overlay, light/dark.
- Transactions page: per-source groups, filters, sorting, manual add/edit/
  delete with live derived values and over-sell guard.
- Reports: CRA capital gains PDF, annual report PDF, Excel export (5 sheets),
  TFSA contribution room, dividend calendar.
- Tools: What-If simulator, rebalancing advisor, price alerts.
- Multi-profile system with isolated DBs; factory reset; crash recovery.

## 5. The 0.7.0 audit bug-fix campaign (June 2026) — COMPLETE

An independent Codex audit of 0.7.0 found 8 bugs; all fixed, one commit each,
with stash-proven regression tests at the aggregated/API level:

| Bug | Commit | Fix |
|---|---|---|
| BUG-001 | `4d15726` | All 10 currencies → CAD-equivalent in aggregation via stored `net_cad` (was: 8 exotic currencies summed as CAD 1:1) |
| BUG-002 | `fab5726` | Parallel CAD ACB ledger — acquisition-date FX for cost, disposition-date FX for proceeds |
| BUG-003 | `764bc7b` | Generic import persists cash deposits/withdrawals (conditional schema) |
| BUG-004 | `2cc9451` | Dividend report converts at transaction-date FX; yield-on-cost on CAD cost basis |
| BUG-005 | `226aa44` | Manual edit recomputes gross/net/FX/`net_cad`; hash immutable |
| BUG-006 | `de10414` | Holdings equity attributed to owning `account_number`; CRA pooling untouched |
| BUG-007 | `cefdbc3` | Removed unused today-FX lookup that crashed strict date-keyed FX callables |
| BUG-008 | `64363cc` | README version/link hygiene |

**Master Debug run 2026-06-12 (log:
`md-instructions/build_version_test_logs/v0.7.0_20260612_194515_testlog.txt`):**
446 backend pytest + 113 root pytest + 27 Playwright vs the freshly repackaged
build, 0 failures, tsc 0 errors. Installer rebuilt 2026-06-12 19:41 so it
contains all 8 fixes.

**Gate before merging to main:** the user must manually verify the Section 6b
universal-import steps in the installed app (editor opens for unknown
institutions, override works, dedup on re-import, named brokers bypass the
editor) plus hands-on verification of the bug fixes with real test files.

## 6. Known issues / open items

- **ADD-001…ADD-007** (same audit, secondary findings — all OPEN, next pass):
  - ADD-001 Excel Portfolio Summary sheet drops the foreign (`*_other_cad`) leg.
  - ADD-002 `investment_weight_pct` denominator is the CAD-only bucket.
  - ADD-003 attribution treats non-USD gains as CAD 1:1.
  - ADD-004 annual report PDF dividends line treats non-USD as CAD 1:1.
  - ADD-005 `period_dividends_cad` buckets foreign dividends 1:1 (no UI consumer).
  - ADD-006 What-If simulator prices the 8 foreign currencies as CAD 1:1.
  - ADD-007 rebalancer prices foreign tickers 1:1; quote currency clamped CAD/USD.
  ADD-001/002 are the most user-visible; suggested first for the next pass.
- BUG-006 residual: if the same ticker is genuinely held in two same-type
  accounts simultaneously, the whole position's equity displays on the
  majority-holder's row (deterministic) instead of splitting proportionally.
  Tax math and combined totals are correct regardless.
- CAD-only / USD-only dashboard views filter by **native** currency by design;
  GBP/EUR/etc. holdings appear only under Combined views.
- Stock splits must be entered manually; code-signing not yet purchased.
- Item A (clean-machine startup hardening) lives on branch
  `fix/item-a-clean-machine-hardening` — separate, do not touch.

## 7. Repository map

```
backend/            FastAPI app — main.py (API), portfolio.py, acb.py,
                    store.py, db.py, models.py, parser.py, parsers/ (11 named),
                    import_engine/ (universal lane), fx/rates.py, tests/ (446)
frontend/           React/TS — src/components/, src/types.ts (mirrors models),
                    tests/e2e/ (Playwright)
electron/           main.js, preload.js, electron-builder.yml
scripts/            build-windows.ps1 (full release build), build-backend.ps1 …
tests/              root pytest (113): detection, parsers, fx, profiles, registry
test_data/          synthetic broker fixtures (csv/xlsx/pdf/generic)
md-instructions/    THIS FILE, CHANGELOG.md, MASTER_DEBUG_AND_TEST_RUN.md,
                    BUG_REPORT_0_7_0_CODEX_AUDIT.md, build_version_test_logs/
release/            installer + win-unpacked (gitignored)
```

## 8. Working conventions

- One bug = one commit; regression tests proven to fail on pre-fix code.
- Gates before any commit: `pytest backend/tests/` (0 fail), `pytest tests/`
  (0 fail), `npx tsc --noEmit` (0 errors).
- Author `elmatthe`, no Co-Authored-By trailers.
- A new packaged build always triggers the MASTER_DEBUG_AND_TEST_RUN.md prompt.
- Transaction-date FX (stored `fx_rate_to_cad`/`net_cad`) over live rates in
  every tax- or money-facing computation; live rates only for current market
  value display.
