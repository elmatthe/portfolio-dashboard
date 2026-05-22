# Portfolio Dashboard

A local-first investment portfolio tracker for Canadian and international
investors. Import your activity from any of **11 supported brokers**, and the
app calculates your adjusted cost base, capital gains, TFSA contribution room,
multi-currency exposure, and performance attribution — all on your own
computer, with nothing sent to the cloud except a daily call to Yahoo Finance
for prices.

**Current version: 0.5.1** · See [`markdown-instructions/CHANGELOG.md`](markdown-instructions/CHANGELOG.md)
for release notes.

---

## What it does

- **Imports from 11 brokers** — Questrade, Wealthsimple, RBC Direct Investing,
  CIBC Investor's Edge, TD Direct Investing, BMO InvestorLine, Scotia iTRADE,
  Interactive Brokers, National Bank Direct Brokerage, Fidelity, HSBC
  InvestDirect. CSV, TSV, XLSX, and PDF formats. Broker is auto-detected from
  file content, so there's no broker selector to fill in.
- **10-currency support** — CAD, USD, GBP, EUR, JPY, AUD, CHF, HKD, SEK, NOK.
  FX rates are looked up at the **trade date**, not today's spot (the
  CRA-correct approach for capital-gains reporting across currencies).
- **CRA-compliant ACB engine** — per-security and per-account-type, walked
  chronologically with the superficial-loss rule applied. Commission is folded
  into cost basis. TFSA / RRSP / RESP / RRIF / FHSA / LIRA gains are flagged
  non-taxable; Margin / Non-Reg / Individual / IRA variants trip the
  taxable-event warning.
- **CAD-equivalent aggregation** — every realized gain carries both its
  native-currency total and its CAD-converted total at the transaction-date
  FX rate. The headline "Total Taxable Gain (CAD)" on the dashboard, the Excel
  export, and the Tax Report PDF all sum the CAD column.
- **SHA-256 deduplication** — re-importing the same file inserts zero rows
  (hash = date + action + symbol + qty + net + account_number).
- **Multi-account** — 14 account types tracked: TFSA, Margin, RRSP, RESP,
  Crypto, RRIF, Non-Registered, IRA, Roth IRA, Traditional IRA, Individual,
  LIRA, FHSA, Other.
- **Multi-profile** — each profile is its own SQLite database under
  `%APPDATA%\Portfolio Dashboard\profiles\<id>\`. Switching profiles
  hot-swaps the SQLAlchemy engine; no app restart needed.

## Reports

- **Excel export** — six-column-block `.xlsx` with Portfolio Summary, Holdings,
  Capital Gains (native + CAD), Transaction History, and Price History sheets,
  with green/red conditional fills on gain/loss columns.
- **CRA Tax Report PDF** — Schedule 3-style realized-gains table, superficial
  loss adjustments, TFSA activity summary (clearly labelled non-taxable),
  dividend income split eligible-Canadian vs. foreign-US. CAD subtotals.
- **Annual Portfolio Report PDF** — five pages: cover with portfolio-value
  chart, performance summary (vs SPY benchmark), best/worst contributors,
  full holdings detail, transaction history for the year, dividend calendar
  with embedded monthly bar chart.
- **JSON data export** — full backup of the active profile's transactions and
  ticker map.

## Analytics

- **Time-period selector** — 1M / 3M / 6M / YTD / 1Y / 3Y / All. Every chart
  and table updates simultaneously. Unknown values return HTTP 422 (no silent
  fallthrough).
- **Per-account performance** — value-history is reconstructed per
  account-number, so two Margin accounts at the same broker show distinct ROI
  curves rather than blending.
- **Lifetime ROI** — the "All" view computes
  `(current_value − net_deposits) / net_deposits × 100` per account, so
  buy-and-hold returns since first deposit are visible without zoom-fiddling.
- **Portfolio value history** — weekly reconstruction with a gain-vs-deposits
  overlay.
- **Performance attribution** — bar chart of each holding's contribution to
  the portfolio's period return.
- **Correlation matrix** — Pearson on weekly returns across held tickers.
- **Portfolio statistics** — annualised return, volatility, Sharpe ratio.
- **Dividend tracker** — monthly history, yield-on-cost, trailing-12-month
  total, projected upcoming payments based on each ticker's observed cadence.

## Decision tools

- **Rebalancing advisor** — set target percentages per (ticker, account_type),
  pick new-money or pure-rebalance mode. The recommender enforces three
  invariants:
  1. In `new_money` mode, total buy cost never exceeds the `new_money_cad`
     budget — overshoots are scaled down proportionally with a warning.
  2. In `rebalance` mode, total buy cost never exceeds total sell proceeds.
  3. Cross-account funding is flagged — sells in a TFSA can't fund buys in a
     Margin account, and the response surfaces a warning per account_type
     when the math implies that.
  New positions (not currently held) are supported via the live-price lookup.
- **What-If Simulator** — Buy / Sell / Lump-sum scenarios with full
  capital-gains breakdown and tax estimate at the user's marginal rate. TFSA
  sells correctly show $0 tax.
- **Price alerts** — buy-below / sell-above thresholds per ticker, evaluated
  on every price refresh.

## Canadian-specific

- **TFSA contribution room calculator** — embeds CRA's 2009–2026 annual limit
  schedule, accounts for prior-year withdrawals being added back, flags
  over-contribution. Surfaces an `is_estimate: true` flag when the user
  hasn't filled in their birth year / residency-since date (so the UI can
  warn against trusting the default-eligibility figure).
- **Schedule 3 PDF** — see Reports above.

## Privacy

Everything is stored on your computer. The app's only outbound network calls
are to **Yahoo Finance** (price + history lookups) and, optionally with
`FX_LIVE_RATES=true`, to the **Bank of Canada Valet API** (historical FX
rates). No account number, ticker symbol, or balance is sent to any service
the user didn't explicitly opt in to.

| Item | Location |
| --- | --- |
| Active profile DB | `%APPDATA%\Portfolio Dashboard\profiles\<id>\portfolio.db` |
| Profile manifest | `%APPDATA%\Portfolio Dashboard\profiles.json` |
| App preferences | `app_state` table inside each profile DB |
| Window position | `%APPDATA%\Portfolio Dashboard\window-state.json` |
| Backend log | `%APPDATA%\Portfolio Dashboard\backend.log` |

---

## Installation (Windows)

Pre-built installers will be published to the GitHub Releases page once a
signed build is available. For now, build from source or run from source —
see *For developers* below.

1. Download `Portfolio Dashboard Setup 0.5.1.exe` from the Releases page.
2. Double-click. Windows SmartScreen may warn about an unknown publisher —
   click **More info** → **Run anyway**. (Code-signing is on the roadmap.)
3. In the NSIS installer:
   - Pick an install location (defaults to
     `%LOCALAPPDATA%\Programs\Portfolio Dashboard`)
   - Optionally check **Create Desktop shortcut** and **Add to Start Menu**
   - Click **Install** (~10–20 seconds)
4. Click **Finish** to launch.

macOS and Linux builds are configured in `electron-builder.yml` but not yet
released — see *Roadmap*.

---

## How to use

### Launch

- Double-click the desktop shortcut or Start Menu entry, **or**
- Double-click `Launch Portfolio Dashboard.bat` from this repo root — the
  launcher picks the installed copy first, falling back to the unpacked
  `release\win-unpacked\` build.

On first launch a small splash window appears while the local data service
starts (typically 1–3 seconds). The backend listens on `127.0.0.1:7842` by
default; if that port is busy, the Electron main process picks any free
port via the OS and the frontend follows automatically.

### Importing transactions

1. From your broker's web interface, export your transaction history (CSV /
   XLSX / PDF — whatever they offer).
2. Drop the file onto the upload zone in the app. The broker is detected
   from the file content; you'll see a confirmation toast with the parsed
   count and detected format.

Re-importing the same file is safe — already-seen rows are deduped by their
SHA-256 hash.

### Multi-profile

The profile pill (top-right of the banner) shows the active portfolio. Click
it to switch, add a new profile (which gets its own database), or delete
one. Each profile has an accent color that retints the UI.

### Settings (gear icon)

- **Tax** — your marginal rate (used by the What-If Simulator for tax
  estimates) and province.
- **TFSA** — birth year + year you became a Canadian resident. Both are
  required for an accurate TFSA-room calculation; leave them blank and the
  calculator reports an `is_estimate` flag.
- **Display** — default time period, default currency view, light/dark theme.
- **Data** — JSON backup export, clear-all-data button (preserves settings).

### CRA Tax Report

Click **Reports** in the banner, pick **Tax Report** and the tax year, then
**Generate PDF**. The realized-gains table mirrors Schedule 3; subtotals are
in CAD using the FX rate on each disposition's transaction date.

### Reset / uninstall

Quit the app and delete the relevant folder under `%APPDATA%\Portfolio
Dashboard\profiles\<id>\`. Or use **Settings → Data → Clear all data** to
wipe transactions for the active profile while keeping your settings.

To uninstall:
- Settings → Apps → Installed apps → **Portfolio Dashboard** → **Uninstall**,
  or re-run the installer and use its uninstall flow. The uninstaller leaves
  `%APPDATA%\Portfolio Dashboard\` untouched so you can reinstall without
  losing data.

---

## For developers

<details>
<summary>Run from source</summary>

### Prerequisites

- Python 3.11+ (tested on 3.13)
- Node.js 18+ (tested on 24)
- PowerShell 5+ (for the Windows build script)

### Backend (FastAPI, port 7842 by default)

Run from the **project root**, not from inside `backend/`:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --port 7842
```

The backend reads `PORTFOLIO_PORT` from the environment, so it'll also
respect whatever port the Electron main process picked at startup. Use
`--reload` for development; the production PyInstaller binary runs uvicorn
without it.

### Frontend (Vite dev server, port 5173)

The Vite dev server proxies `/api` and `/health` to the backend on 7842.

```bash
cd frontend
npm install
npm run dev
```

Other scripts:

- `npm run typecheck` — `tsc --noEmit`
- `npm run lint` — ESLint over `src/`
- `npm run build` — type-check + Vite production build into `dist/`

### Electron shell (cross-platform `dev` script)

```bash
cd electron
npm install
npm run dev      # cross-env NODE_ENV=development electron .
```

### Run the test suite

From the project root:

```bash
python -m pytest tests/ -v
```

Suite size: 113 tests covering parser detection, parser row-counts and
CAD-equivalent population, FX service, profile loaders, and the registry
integrity assertion (which guards against the PyInstaller `KeyError:
'generic'` regression).

### Build the Windows installer end-to-end

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
```

This script:

1. Bundles the FastAPI backend with PyInstaller into
   `backend-dist\backend.exe` (~117 MB, onefile).
2. Builds the React frontend with Vite into `dist\`.
3. Installs a PyInstaller-compiled shim over
   `electron/node_modules/7zip-bin/win/x64/7za.exe` that skips the
   macOS-only `libcrypto.dylib` / `libssl.dylib` symlinks in
   `winCodeSign-2.6.0.7z` (those require Developer Mode on Windows and
   aren't relevant to win32 builds).
4. Runs `electron-builder --win`, producing
   `release\Portfolio Dashboard Setup 0.5.1.exe` (NSIS, x64, ~196 MB).

First run takes 3–5 minutes; subsequent runs are faster.

</details>

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | [FastAPI](https://fastapi.tiangolo.com/) · [SQLAlchemy](https://www.sqlalchemy.org/) · [SQLite](https://www.sqlite.org/) · [pandas](https://pandas.pydata.org/) · [openpyxl](https://openpyxl.readthedocs.io/) · [pdfplumber](https://github.com/jsvine/pdfplumber) · [reportlab](https://www.reportlab.com/) · [matplotlib](https://matplotlib.org/) |
| Market data | [yfinance](https://github.com/ranaroussi/yfinance) · [Bank of Canada Valet API](https://www.bankofcanada.ca/valet/docs) (opt-in) |
| Frontend | [React 18](https://react.dev/) · [TypeScript](https://www.typescriptlang.org/) · [Vite](https://vitejs.dev/) · [TanStack Query](https://tanstack.com/query) · [Tailwind CSS](https://tailwindcss.com/) · [Recharts](https://recharts.org/) · [lucide-react](https://lucide.dev/) |
| Desktop | [Electron 30](https://www.electronjs.org/) |
| Backend bundler | [PyInstaller](https://pyinstaller.org/) |
| Installer | [electron-builder](https://www.electron.build/) (NSIS) |
| Tests | [pytest](https://docs.pytest.org/) |

---

## Architecture notes

- **Per-security-per-account ACB ledgers** match CRA rules: TFSA, RRSP, RESP,
  RRIF, LIRA, FHSA each carry their own ledger per security. Multiple Margin
  accounts at the same broker share one ledger (also CRA-correct: identical
  property is pooled across non-registered accounts).
- **FX cascade**: `FXService` checks an in-file rate (set by parsers that
  carry FX columns — RBC, CIBC, TD, BMO, Scotia, NB, HSBC), then the SQLite
  `exchange_rates` cache, then the Bank of Canada Valet API (gated on
  `FX_LIVE_RATES=true`), then a static 2024 fallback table for offline use.
  HKD / SEK / NOK aren't published by BoC and always use the static rate.
- **Graceful Electron shutdown**: on app quit, the main process POSTs
  `/api/shutdown` and waits up to 4s for the backend to checkpoint the
  SQLite WAL before killing the child process. Without this, Windows
  TerminateProcess left multi-MB `.db-wal` files accumulating.
- **Backend port resolution**: the main process tries port 7842 first; if
  it's busy (another instance, dev server), it asks the OS for any free
  port and passes it to both the backend (via `PORTFOLIO_PORT`) and the
  renderer (via the preload bridge's `desktop.getBackendPort()`).

## Limitations

- **Equities and ETFs only** — no options, futures.
- **RRSP / RESP** accounts are tracked but ACB isn't surfaced (they're
  tax-deferred — ACB isn't a tax-reporting concern).
- **Wealthsimple Crypto** transactions import as Crypto-typed but are
  considered partial support.
- **Stock splits** must be entered manually — the SPLIT action is recognised
  by the ACB engine but parsers don't yet detect them across all brokers.
- **Windows-only** for the prebuilt installer; macOS and Linux are
  configured in `electron-builder.yml` but not yet released.

## Roadmap

- **0.6.0** — Currency-exposure widget on the dashboard, Linear-style
  per-currency breakdown panel.
- **0.7.0** — Options (calls / puts / spreads) and broker-API integrations
  (Questrade has one, Wealthsimple doesn't).
- **0.8.0** — Background daily price refresh, push-style price alerts.
- **1.0.0** — Code-signed Windows + Mac installers, App Store / Microsoft
  Store distribution.

## License

[MIT](LICENSE) — © 2026 Portfolio Dashboard contributors.

This project bundles open-source libraries listed under *Tech stack* above;
each retains its own license.
