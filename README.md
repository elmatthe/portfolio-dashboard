# Portfolio Dashboard

A local-first portfolio tracker for Canadian and international investors.
Import a transaction export from any of 11 supported brokers, get ACB,
capital gains, dividends, performance attribution, a tax report ready for
Schedule 3, and more — all calculated on your own computer in 10 currencies.
No account credentials, no API keys, nothing leaves your machine except a
daily call to Yahoo Finance for stock prices.

**Current version: 0.3.0** · See [markdown-instructions/CHANGELOG.md](markdown-instructions/CHANGELOG.md) for full release
notes.

---

## Features

### Core
- ✅ **11-broker multi-format import** — Questrade, Wealthsimple, RBC,
  CIBC, TD, BMO, Scotiabank, Interactive Brokers, National Bank, Fidelity,
  HSBC. Accepts `.csv`, `.tsv`, `.xlsx`, `.xls`, `.pdf`. Broker auto-detected
  from file content — no broker dropdown to fill in.
- ✅ **10-currency support** — CAD, USD, GBP, EUR, JPY, AUD, CHF, HKD, SEK,
  NOK. FX rates at the trade date (CRA-correct for capital gains across
  currencies). Bank of Canada historical API (opt-in via `FX_LIVE_RATES=true`)
  with a static fallback table for offline use.
- ✅ **CRA-compliant ACB engine** — per-security, per-account, chronological,
  with the superficial loss rule
- ✅ **SHA-256 deduplication** — re-uploading the same file inserts zero rows
- ✅ **Multi-account** — TFSA, Margin, RRSP, RESP, Crypto, RRIF, Non-Reg,
  IRA, Roth IRA, Traditional IRA, LIRA, FHSA; per-account tabs and Combined view
- ✅ **Multi-user profiles** — each profile is its own isolated database; one
  click switches the entire dashboard

### Reporting
- ✅ **Excel export** — 5-sheet `.xlsx` (Summary, Holdings, Capital Gains,
  Transactions, Price History) with green/red conditional fills
- ✅ **CRA Tax Report PDF** — Schedule 3-style capital gains report,
  superficial-loss adjustments, TFSA section, dividend income classified
  eligible Canadian vs foreign US
- ✅ **Annual Portfolio Report PDF** — 5-page year-in-review with embedded
  charts, S&P 500 comparison, best/worst performers, transaction history
- ✅ **JSON data export** — full transaction backup for the active profile

### Analytics
- ✅ **Time-period selector** — 1M / 3M / 6M / YTD / 1Y / 3Y / All;
  every section recalculates simultaneously, period is bookmarkable
  via `#period=ytd` URL hash
- ✅ **Portfolio Balances** — 4-currency view toggle (Combined CAD,
  Combined USD, CAD only, USD only) matching Questrade's UI
- ✅ **Portfolio Value History** — weekly reconstruction from your transaction
  history, gain vs net deposits overlay
- ✅ **Performance Attribution** — bar chart of each holding's contribution
  to total portfolio return for the selected period
- ✅ **Historical price charts** — per-holding line chart with ACB reference
  line and S&P 500 (SPY) benchmark overlay
- ✅ **Correlation matrix** — Pearson correlation of weekly returns,
  heatmap rendering
- ✅ **Portfolio statistics** — annualised return, volatility, Sharpe ratio,
  observations count
- ✅ **Dividend income tracker** — monthly bar chart, upcoming-payment
  projections (from each ticker's observed cadence), yield-on-cost,
  trailing-12-month total

### Canadian-specific
- ✅ **TFSA Contribution Room tracker** — uses CRA's annual limit schedule
  (2009–2026), accounts for withdrawals returning room next year,
  flags over-contributions
- ✅ **Tax-aware sell simulator** — uses your saved marginal tax rate; TFSA
  sells correctly show $0 tax

### Decision tools
- ✅ **What-If Simulator** — Buy / Sell / Lump-sum scenarios with full
  capital-gains breakdown
- ✅ **Rebalancing Advisor** — set target % per holding, generate buy/sell
  instructions in whole shares; "new money only" mode never produces sells
- ✅ **Price alerts** — buy-below / sell-above thresholds per ticker,
  evaluated on every price refresh, in-app notifications

### Experience
- ✅ **Dark / Light theme** — sun/moon toggle, preference persisted
- ✅ **Auto price refresh** on launch if cached prices are older than 30 min
- ✅ **Live "X min ago"** labels — update every 60 seconds without reload
- ✅ **One-click desktop launch** via `.bat` from the project root

### Coming soon
- 🚧 RRSP-specific reporting (currently tracked but no contribution-room
  calculator like the TFSA one)
- 🚧 Direct broker API integration (Questrade has one, Wealthsimple doesn't)
- 🚧 macOS `.dmg` packaging (`mac:` section already in
  `electron-builder.yml`; needs a Mac to actually build)
- 🚧 Stock split handling
- 🚧 Options (calls / puts / spreads)

---

## Download

Pre-built installers will be posted to the [Releases page](#) when 0.2.0
ships publicly. The current target is **Windows x64**:

- `Portfolio Dashboard Setup 0.2.0.exe` (~196 MB NSIS installer)

macOS support is on the roadmap — see *Coming soon* above.

---

## Installation (Windows)

1. Download `Portfolio Dashboard Setup 0.2.0.exe` from the Releases page.
2. Double-click it. Windows SmartScreen may warn that the publisher is
   unknown — click **More info** → **Run anyway**. (The app is unsigned at
   the moment; code-signing is planned before any commercial release.)
3. In the NSIS installer:
   - Pick an install location (defaults to
     `%LOCALAPPDATA%\Programs\Portfolio Dashboard`)
   - Optionally check **Create Desktop shortcut** and **Add to Start Menu**
   - Click **Install**. Takes about 10–20 seconds
4. Click **Finish** to launch the app, or open it from the Start menu later.

---

## How to use

### Launch
- Double-click the desktop shortcut, OR
- Search "Portfolio Dashboard" in the Start menu, OR
- Double-click `Launch Portfolio Dashboard.bat` from the project root (the
  file picks the installed copy first, then falls back to the unpacked
  build under `release\win-unpacked\`)

On first launch a splash window appears while the local data service starts
(~1–3 seconds). Then the main window opens with a welcome / drag-drop screen.

### Import transactions

**From Questrade:**
1. Sign in at [my.questrade.com](https://my.questrade.com)
2. Click **Accounts** → **Activity**
3. Choose a date range (start with **All Time** for your first export)
4. Click **Download** → **Excel** (`.xlsx`)
5. Drop the downloaded file onto the upload zone

**From Wealthsimple:**
1. Open the Wealthsimple app or website
2. Go to **Profile** → **Documents**
3. **Request custom statement** → **Activities Export** (`.csv`)
4. Or download a monthly **Statement** (`.pdf`) — both are accepted
5. Drop the file onto the upload zone

CSV is more accurate than PDF (PDF table extraction depends on the document
layout). Prefer CSV when possible.

### Updating your data
Just export a fresh transaction file from your broker and drop it on the
app. Transactions you've already imported are skipped automatically — you'll
never see a duplicate.

### Multi-user profiles
The profile pill (top-right of the banner) shows the active portfolio.
Click it to switch, add a new profile (with its own database), or delete
one. Each profile gets a distinct accent color that retints the UI.

### Time periods
Use the pill bar below the account tabs (1M / 3M / 6M / YTD / 1Y / 3Y /
All) to scope every section of the dashboard. The selected period is
saved to the URL hash, so a bookmark of `…/#period=ytd` reopens to that
view.

### Settings (gear icon)
- **Tax**: your marginal rate (used by the What-If Simulator for tax estimates)
- **TFSA**: birth year + year you became a Canadian resident (required for
  the Room tracker)
- **Display**: default time period, default currency view, light/dark theme
- **Data**: price refresh interval, JSON backup export, clear-all-data button

### CRA Tax Report
Click the **Reports** button in the banner, pick **Tax Report** and the
tax year, then **Generate PDF**. Save it locally; it's ready to hand to an
accountant.

### Privacy
Everything is stored on your computer in a SQLite database:

| Item | Location |
| --- | --- |
| Active profile DB | `%APPDATA%\Portfolio Dashboard\profiles\<id>\portfolio.db` |
| Profile manifest | `%APPDATA%\Portfolio Dashboard\profiles.json` |
| App preferences | `%APPDATA%\Portfolio Dashboard\app_state` (per profile) |
| Window position | `%APPDATA%\Portfolio Dashboard\window-state.json` |
| Backend log | `%APPDATA%\Portfolio Dashboard\backend.log` |

The only outbound network calls the app makes are to **Yahoo Finance** for
stock prices and exchange rates. No account number, ticker symbol, or
balance is sent to any external service.

### How to reset
Quit the app, delete the relevant folder under
`%APPDATA%\Portfolio Dashboard\profiles\<id>\`, then relaunch. Or use the
"Clear all data" button in Settings → Data, which keeps your settings but
wipes transactions/holdings for the active profile.

### How to uninstall
- Settings → Apps → Installed apps → **Portfolio Dashboard** → **Uninstall**
- OR re-run `Portfolio Dashboard Setup 0.2.0.exe` and use its uninstall flow

The uninstaller removes the app binaries but leaves
`%APPDATA%\Portfolio Dashboard\` untouched, so you can reinstall without
losing data.

---

## Limitations

- **Equities and ETFs only** — no options, futures, or crypto.
- **RRSP & RESP** accounts are tracked but ACB isn't calculated for them
  (they're tax-deferred — ACB isn't a tax-reporting concern).
- **Wealthsimple Crypto** transactions are imported but flagged as partial
  support.
- **Stock splits** require manual ACB adjustment for now.
- **Windows only** for the prebuilt installer (Mac is on the roadmap).

---

## Built with

| Layer | Technology |
| --- | --- |
| Backend | [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy](https://www.sqlalchemy.org/), [SQLite](https://www.sqlite.org/), [pandas](https://pandas.pydata.org/), [openpyxl](https://openpyxl.readthedocs.io/), [reportlab](https://www.reportlab.com/), [matplotlib](https://matplotlib.org/), [pdfplumber](https://github.com/jsvine/pdfplumber) |
| Market data | [yfinance](https://github.com/ranaroussi/yfinance) |
| Frontend | [React 18](https://react.dev/), [TypeScript](https://www.typescriptlang.org/), [Vite](https://vitejs.dev/), [TanStack Query](https://tanstack.com/query), [Tailwind CSS](https://tailwindcss.com/), [Recharts](https://recharts.org/), [lucide-react](https://lucide.dev/) |
| Desktop shell | [Electron 30](https://www.electronjs.org/) |
| Backend bundler | [PyInstaller](https://pyinstaller.org/) |
| Installer | [electron-builder](https://www.electron.build/) (NSIS) |

Thanks to the maintainers of all of the above. None of this would exist
without their work.

---

## For developers

<details>
<summary>Run from source</summary>

### Prerequisites
- Python 3.11+
- Node.js 18+ (the project is tested with Node 24)
- PowerShell 5+ (for the Windows build script)

### Backend (port 7842)
Run from the **project root**, not from inside `backend/`:

```bash
python -m pip install -r backend/requirements.txt
uvicorn backend.main:app --port 7842 --reload
```

`--reload` is for development. In production (when Electron spawns the
PyInstaller binary), the entry point starts uvicorn without `--reload`.

### Frontend dev server (port 5173, proxies to 7842)
```bash
cd frontend
npm install
npm run dev
```

### Electron shell (talks to whichever backend it can find)
```bash
cd electron
npm install
NODE_ENV=development npm start
```

### Run the verification suite against the sample export
```bash
python -c "
from backend.parser import parse_file
from backend.acb import compute
txs, _ = parse_file('Questrade_Test_Transactions.xlsx')
holdings, report = compute(txs)
for k, h in sorted(holdings.items()):
    print(k, h.total_shares, h.acb_per_share, h.total_cost)
"
```

### Build the Windows installer end-to-end
```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
```

This single script:
1. Bundles the FastAPI backend with PyInstaller (`backend-dist\backend.exe`,
   ~117 MB onefile)
2. Builds the React frontend with Vite and stages it to `dist\`
3. Installs a tiny PyInstaller-compiled shim over
   `electron/node_modules/7zip-bin/win/x64/7za.exe` that skips the
   macOS-only `libcrypto.dylib` / `libssl.dylib` symlinks in
   `winCodeSign-2.6.0.7z` (those need admin / Developer Mode on Windows
   and aren't relevant to win32 builds)
4. Runs `electron-builder --win` → `release\Portfolio Dashboard Setup 0.2.0.exe`
   (NSIS, x64, ~196 MB)

First run takes about 3–5 minutes; subsequent runs are faster.

</details>

---

## Roadmap

- **0.3.0** — RRSP-specific reporting, stock split handling, macOS packaging
- **0.4.0** — Options (calls / puts) and crypto (with full Wealthsimple
  Crypto support)
- **0.5.0** — Direct broker API integration (Questrade), background daily
  price refresh
- **1.0.0** — App Store / Microsoft Store release, code-signed installer

---

## License

[MIT](LICENSE) — © 2026 Portfolio Dashboard contributors.

This project bundles open-source software listed under **Built with** above;
each of those libraries retains its own license.
