# Changelog

All notable changes to Portfolio Dashboard. The format is loosely based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] — 2026-05-19

The multi-broker + multi-currency release. The app now ingests transaction
exports from **11 brokers** across **CSV, TSV, XLSX, and PDF** formats, and
holds positions in any of **10 currencies** (CAD, USD, GBP, EUR, JPY, AUD,
CHF, HKD, SEK, NOK). Profile 6 (regression) stays green: re-importing the
v0.2.0 Questrade and Wealthsimple files still produces 0 new / 46 skipped
and 0 new / 35 skipped respectively. The 14 v0.2.0 verification checks
continue to pass.

### Added — Broker support

- **Parser registry** under `backend/parsers/`: a `BaseParser` interface
  (`BROKER_NAME`, `BROKER_KEY`, `SUPPORTED_FORMATS`, `detect()`, `parse()`)
  and a `BROKER_PARSERS` registry. Detection runs every registered parser's
  `detect(file_path, content_sample)`, picks the highest-confidence match
  ≥ 0.5, and falls back to `GenericParser`. Patterns inspired by
  wealthfolio's `ActivityImport`.
- **9 new broker parsers** for the file formats in `test-transaction-reports/`:
  - `RBCParser`           — RBC Direct Investing (CSV, PDF)
  - `CIBCParser`          — CIBC Investor's Edge (CSV, PDF)
  - `TDParser`            — TD Direct Investing (CSV/TSV, PDF)
  - `BMOParser`           — BMO InvestorLine (CSV, XLSX)
  - `ScotiabankParser`    — Scotia iTRADE (CSV with `;` delim and DD/MM/YYYY
                            dates, XLSX with `Trade History` sheet)
  - `InteractiveBrokersParser` — IB Flex CSV with signed-quantity convention
                            (negative = buy) and `DataDiscriminator=="Trade"`
                            filter
  - `NationalBankParser`  — Bilingual FR/EN headers
  - `FidelityParser`      — US broker, USD-only, zero-commission, MM/DD/YYYY
  - `HSBCParser`          — XLSX with ISIN column; supports any of 10 currencies
- **Wealthsimple and Questrade parsers** are now `WealthsimpleParser` and
  `QuestradeParser` classes that wrap the existing v0.2.0 parsing functions.
  Their `parse()` methods call the legacy `backend/parser.py` code verbatim,
  so transaction hashes are byte-identical to v0.2.0 and the dedup contract
  is preserved.
- **`backend/parser.parse_file()`** routes through the registry instead of
  the inline `if broker == ...` dispatch. The legacy `detect_broker_and_format()`
  function is kept as a safety net.
- **Auto-detection from file content**: each `detect()` method inspects the
  first 4 KB for broker-specific signals (header strings, column names,
  delimiter character, sheet names, ISIN column presence). No user-supplied
  broker hint required.

### Added — Multi-currency (FXService)

- **`backend/fx/rates.py` — `FXService`** with three-tier rate lookup:
  1. In-file rate (when a broker export carries `Exchange Rate` / `FX Rate`
     columns — RBC, CIBC, TD, BMO CSV, Scotia, NB, HSBC all do)
  2. Bank of Canada historical Valet API (gated behind `FX_LIVE_RATES=true`
     env var). Series IDs: FXUSDCAD, FXGBPCAD, FXEURCAD, FXJPYCAD, FXAUDCAD,
     FXCHFCAD. Pattern extracted from `tsiemens/acb`.
  3. Static fallback table for CAD, USD, GBP, EUR, JPY, AUD, CHF, HKD, SEK,
     NOK — used when offline, in tests, or for currencies BoC doesn't publish.
- **FX rate at trade date, not today's rate** — the CRA-correct approach
  documented by `tsiemens/acb` and `dwrpayne/portfolio`. Each Transaction
  stores its own `fx_rate_to_cad` and `net_cad` at the moment of the trade.
- **SQLite cache** keyed on `(pair, rate_date)` via the existing
  `exchange_rates` table — historical rates persist across runs.

### Added — Model and schema

- **`Transaction` model** extended with five v0.3.0 fields (all nullable for
  backwards compat with v0.2.0 rows):
  - `fx_rate_to_cad: float | None`
  - `net_cad: float | None`
  - `isin: str | None` (HSBC, IB international rows)
  - `exchange: str | None` (TSX, NYSE, LSE, EURONEXT, TSE, ASX, …)
  - `reference_id: str | None` (broker confirmation / order number)
- **Broadened `Literal` types** in `backend/models.py` and `frontend/src/types.ts`:
  - `Broker`: 12 values (10 new brokers + `generic` fallback)
  - `Currency`: 10 values (the original CAD/USD plus 8 international codes)
  - `AccountType`: 14 values (added RRIF, Non-Registered, IRA, Roth IRA,
    Traditional IRA, Individual, LIRA, FHSA, Other)
  - `Action`: added TRANSFER
- **SQLite migration** in `db._migrate_schema()`: `PRAGMA table_info` +
  `ALTER TABLE ADD COLUMN` for each v0.3.0 field. Idempotent — safe to run
  on a v0.2.0 DB. Existing rows get NULL for the new columns; reads degrade
  gracefully via `.get()`.

### Added — Tests

- `tests/` directory created from scratch (no test infrastructure in v0.2.0):
  - `tests/test_detection.py`: 16 parametrised auto-detection cases — every
    fixture's broker is identified correctly with confidence ≥ 0.5.
  - `tests/test_parsers.py`: per-parser row-count + sanity assertions
    (valid action, valid currency, dates populated, net_cad populated) for
    all 14 fixture files; plus regression checks for Wealthsimple + Questrade
    and edge cases (IB signed qty, Scotia DD/MM/YYYY, Fidelity zero commission,
    HSBC ISIN capture, BMO XLSX title-row skipping).
  - `tests/test_fx.py`: FXService static table coverage, in-file rate
    priority, JPY edge case, CAD-is-exactly-one, singleton identity.
  - `tests/test_profiles.py`: a runner that loads each profile YAML and
    asserts inserted counts, broker set, currency floor, account-type
    floor, IB quantity normalisation, ISIN presence, zero-commission
    floor, and re-import dedup.
- **6 profile YAMLs** under `tests/profiles/`:
  `canadian_retail.yaml`, `active_trader.yaml`, `multi_bank.yaml`,
  `international.yaml`, `us_investor.yaml`, `regression.yaml`.
  Each enumerates fixture files and the assertions that must hold.
- **111 tests, all passing.**

### Added — Upload flow

- Upload widget now accepts `.csv`, `.tsv`, `.xls`, `.xlsx`, and `.pdf`. The
  broker is auto-detected from file content — no broker dropdown needed.

### Internal

- All 14 new broker parsers use a shared `_rows_to_transactions()` row
  converter in `backend/parsers/rbc.py` for the column-aligned brokers
  (RBC/CIBC/TD/BMO/Scotia/NationalBank), keyed on a single `_COL_ALIASES`
  dict that maps the canonical fields to every broker's column name variant.
  IB, Fidelity, HSBC have dedicated converters because their column
  semantics diverge (signed qty, USD-only, ISIN + dual-currency).
- Hash construction (`backend/parser.compute_hash`) is **unchanged** and
  re-exported from `backend/parsers/_common.py`. Every broker parser hashes
  using the same `transaction_date | action | raw_symbol | quantity (6dp) |
  net_amount (4dp) | account_number` recipe.

### Reference repos studied

The patterns in this release were extracted from §0.5 of
`CLAUDE_CODE_INSTRUCTIONS.md`:
- `tsiemens/acb` — BoC Valet API call shape and series IDs
- `wealthfolio/wealthfolio` — parser registry, sha256 dedup with tiebreakers
- `dwrpayne/portfolio` — FX-rate-at-trade-date enforcement
- Next.js / IBKR repo — IB CSV `DataDiscriminator=="Trade"` + signed-qty
- `ghostfolio/ghostfolio`, FastAPI template, Australian bank import
  tracker, Streamlit/yfinance, Bloomberg dashboard, Python ACB package
  (reference only for this release)

---

## [0.2.0] — 2026-05-18

The Phase 2 + Phase 3 release. Multi-user profiles, a global time-period
selector, a CRA-compliant tax report, TFSA contribution-room tracking,
performance attribution, rebalancing, what-if simulations, and a price-alert
system are now all in. The app is ready for first public release on Windows.

### Added — Phase 3 features
- **Global time-horizon selector** — sticky pill bar (1M / 3M / 6M / YTD / 1Y /
  3Y / All) below the account tabs. Every dashboard section (balances, holdings
  ROI, dividends, stats, charts, attribution) responds to it in a single
  invalidation. The selected period syncs to `#period=ytd` in the URL hash so
  views are bookmarkable.
- **CRA Capital Gains Report (PDF)** — Schedule 3-style tax document with
  cover page, realized gains/losses table, superficial-loss adjustments,
  TFSA activity summary (clearly labelled non-taxable), and dividend income
  summary split into eligible Canadian vs foreign US. Generated by `reportlab`,
  streamed as `tax_report_YYYY.pdf`.
- **TFSA Contribution Room Tracker** — embeds CRA's annual limit schedule
  (2009–2026), reads contributions and withdrawals from the active profile's
  transactions, and reports total room accumulated, used room, current-year
  usage, last year's withdrawals being added back, and any over-contribution
  amount. Year-by-year breakdown is collapsible. Requires birth year +
  residency year in Settings; gracefully prompts when missing.
- **Settings page** — full-screen overlay with five sections: Profile,
  Tax (marginal rate + province), TFSA (birth/residency), Display (default
  period, default currency view, theme), Data (refresh interval, JSON
  export, clear all data).
- **Performance Attribution** — horizontal bar chart of each holding's
  contribution to total portfolio return for the selected period. Shows top
  contributor + biggest drag in a one-line summary. Endpoint: `/api/attribution`.
- **Rebalancing Advisor** — three-step UI: set target percentages, pick mode
  ("rebalance existing" or "invest new money $X"), generate buy/sell
  instructions. Whole-share rounding; refuses to submit if targets don't sum
  to 100%; warns when sells in a Margin account would trigger capital gains.
- **What-If Simulator** — modal with three modes (Buy / Sell / Lump-sum):
  - Buy: new portfolio total, allocation %, projected annual dividends.
  - Sell: capital gain breakdown with step-by-step ACB math and tax estimate
    (using the marginal rate from Settings). TFSA sells correctly show $0 tax.
  - Lump-sum: what `$X` invested in `Y` on `<date>` would be worth today, plus
    annualised return vs holding cash at the risk-free rate.
  - Read-only — nothing writes to the database.
- **Price Alerts** — bell icon with triggered-count badge; slide-in panel for
  create / dismiss / delete. Buy-below or sell-above thresholds per ticker,
  evaluated automatically on every price refresh. Alerts persist across
  app restarts.
- **Annual Portfolio Report (PDF)** — 5-page year-in-review: cover with
  portfolio value chart, performance vs S&P 500, best/worst performers,
  holdings detail, transaction history, dividend calendar. Embeds matplotlib
  charts as PNGs inside the PDF.
- **Light / Dark mode toggle** — sun/moon button in the banner. Palette is
  driven by CSS variables; switch is a single class flip on `<html>`.
  Preference stored in localStorage so there's no flash on app launch.

### Added — Phase 2 features
- **Multi-user profile system** — each profile has its own isolated SQLite
  database under `%APPDATA%\Portfolio Dashboard\profiles\<id>\portfolio.db`.
  Profile switcher (pill + dropdown) in the banner; first launch
  auto-creates a "My Portfolio" profile so single-user flow is unchanged.
  Switching a profile hot-swaps the SQLAlchemy engine; no app restart needed.
  Each profile has an accent color that retints the entire UI via a CSS
  variable.
- **S&P 500 benchmark overlay** — checkbox on the Historical Chart adds a
  dashed grey SPY line on a right-side axis, indexed to 100 at the start of
  the visible window so the comparison reads cleanly even when the holding
  trades in USD and SPY's price scale differs by an order of magnitude.
- **Portfolio Value Over Time chart** — reconstructs weekly portfolio value
  from the full transaction history. Solid line for total value, dashed grey
  line for cumulative net deposits — the gap is your gain/loss.
- **Dividend calendar & income tracker** — monthly bar chart, upcoming
  payments projected from each ticker's observed cadence, yield-on-cost
  table, trailing-12-month total, period total.
- **Root launcher** — `Launch Portfolio Dashboard.bat` and `.ps1` in the
  project root pick the installed app first, falling back to the unpacked
  build under `release\win-unpacked\`.
- **Auto price refresh on launch** if cached prices are older than 30 minutes.
  The SyncStatus banner's "X min ago" label updates live every 60 seconds.
- **Backend crash diagnostics** — Electron pipes the bundled `backend.exe`'s
  stderr to `%APPDATA%\Portfolio Dashboard\backend.log`. The error dialog
  surfaces the exit code + last 12 stderr lines + log path, so any future
  crash report includes the actual cause.
- **Wealthsimple import** — auto-detected from `.csv` (Activities export) and
  `.pdf` (monthly statement). Same `Transaction` schema as Questrade, same
  SHA-256 dedup, same per-(ticker, account) grouping. Mixed
  Questrade+Wealthsimple imports work in the same profile.

### Added — Phase 1 features (initial release)
- **Questrade .xlsx import** with deterministic SHA-256 hashing → re-importing
  the same file inserts zero new rows.
- **Multi-account support** — TFSA, Margin, RRSP, RESP. Per-account tabs and
  a Combined view.
- **CRA-compliant ACB engine** — per-security per-account, chronological
  walk, commission included in cost basis, superficial loss rule implemented
  (loss denied + added back to repurchase ACB).
- **Live prices via yfinance** with a two-tier cache (process memo + SQLite),
  graceful stale fallback when offline.
- **Dynamic ticker resolution** — handles Questrade's internal IDs
  (`A603109` → AAPL, `V007563` → VOO) via description matching and
  `yfinance.search()` fallback. Resolved mappings cached in `ticker_map`.
- **Portfolio Balances** with a 4-currency view toggle (Combined CAD,
  Combined USD, CAD only, USD only). Matches Questrade's web app's display
  logic — total equity = market value + cash, ROI uses net deposits as the
  base.
- **Holdings cards** with sparkline, ROI %, ACB/share, dividends received,
  portfolio weight, exchange + currency badges.
- **Capital gains report** — per-sell breakdown with gain/loss per share,
  taxable/non-taxable flag, superficial loss adjustment.
- **Historical price charts** with ACB reference line and date-range buttons
  (1M / 3M / 6M / 1Y / 3Y / All).
- **Correlation matrix** — Pearson on weekly returns across held tickers,
  heatmap rendering.
- **Portfolio statistics** — observations, average period return, std dev,
  total / annualised / volatility / Sharpe.
- **Excel export** — 5-sheet `.xlsx` (Summary, Holdings, Capital Gains,
  Transaction History, Price History) with green/red conditional fills.
- **Local-first persistence** — SQLite per profile at
  `%APPDATA%\Portfolio Dashboard\` (Windows) or
  `~/Library/Application Support/Portfolio Dashboard/` (Mac).
- **Windows desktop packaging** — Electron 30 + PyInstaller-bundled
  FastAPI backend, NSIS installer. One-click double-click launch.

### Fixed (during Phase 3 pre-release testing)
- Wealthsimple account-type misclassification: labels like `TFSA-9901` and
  `Personal-4402` were falling through to `Margin`. The lookup now splits the
  label on `-` and ` ` and matches by the type prefix (`tfsa`, `personal`,
  `rrsp`, etc.) before any account-number suffix.
- Backend crash on first dashboard load: the original Electron `stdio:
  "inherit"` mode caused PyInstaller-bundled stderr writes to fail silently
  in a windowless GUI parent process. Switched to `stdio: "pipe"` with
  in-process consumption and `PYTHONUNBUFFERED=1`.
- SQLite `database is locked` errors under parallel reads: WAL mode plus
  `PRAGMA busy_timeout=5000` plus `pool_pre_ping=True` plus `check_same_thread=False`.
  One non-fatal warning may still appear during the very first parallel
  history fetch; it is caught by the existing handler in `market_data`.
- Combined ROI showing +0.00%: the combined-row builder was summing all
  fields but never recomputing `overall_roi_pct`. It now converts USD to
  CAD first so positive/negative values don't cancel.
- Total Equity excluded cash: now defined as market value + cash, matching
  Questrade's interface.
- Holdings grouping collapsed VEQT.TO across TFSA + Margin into one card.
  Now keyed by `(ticker, account_type)` with a defensive assert that fails
  loudly if the key ever degenerates.
- NaN-action dividend rows in some Questrade exports were dropped silently.
  Parser now classifies them by shape: `(symbol present, net > 0) → DIVIDEND`;
  `(no symbol, net > 0) → DEPOSIT`; else `OTHER`.

### Changed
- Bumped `electron/package.json` and `frontend/package.json` to `0.2.0`.

### Technical
- **Backend**: FastAPI on `127.0.0.1:7842`, SQLAlchemy Core, SQLite per profile.
- **Frontend**: React 18 + TypeScript + Vite, TanStack Query, Tailwind CSS,
  Recharts. Strict mode enabled.
- **Desktop**: Electron 30 (Chromium 124), spawns the bundled `backend.exe`
  on launch, pipes stderr to `backend.log`, terminates the child process on
  quit.
- **Packaging**: PyInstaller `--onefile` for the backend (~117 MB Python +
  yfinance + pandas + openpyxl + reportlab + matplotlib + pdfplumber),
  electron-builder NSIS installer (~196 MB total).

---

## [0.1.0] — 2026-05-16

Initial private build. See above — the Phase 1 feature list is now folded
into 0.2.0. Not released publicly.
