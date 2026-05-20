# Portfolio Dashboard — Phase 3 Plan

Read this entire document before writing any code. Implement tasks in the order
specified. After each task run the full verification checklist at the bottom.
The image_examples/ folder has been deleted — do not reference it.

---

## Current State (Do Not Break)

All of the following are confirmed working and must remain so after every change:

- Questrade .xlsx import with SHA-256 dedup (36 transactions, 7 holdings)
- Portfolio Balances with 4-currency toggle
- Account tabs (All / Margin / TFSA)
- Multi-user profile switching with isolated databases
- Portfolio Value History chart
- Historical charts with ACB overlay + S&P 500 benchmark toggle
- Correlation matrix + Portfolio Stats
- Dividend Income section with upcoming payments + yield on cost
- Export to Excel (5 sheets)
- Persistent SQLite per-profile database
- Windows .exe installer + root launcher .bat
- Auto price refresh on launch if prices > 30 min old
- Backend crash logging to %APPDATA%\Portfolio Dashboard\backend.log

---

## Task 1 — Global Time Horizon Selector

This is the most requested feature. A single time period toggle at the top of the
dashboard that filters ALL sections simultaneously: balances, holdings ROI, dividends,
stats, and charts.

### Time Periods

| Label | Definition |
|---|---|
| 1M | Last 30 calendar days |
| 3M | Last 90 calendar days |
| 6M | Last 180 calendar days |
| YTD | Jan 1 of current year to today |
| 1Y | Last 365 days |
| 3Y | Last 3 years |
| All | Since first transaction (default) |

### UI Placement

Add a pill toggle row immediately below the account tabs and above Portfolio Balances.
It should be always visible as the user scrolls (sticky below the SyncStatus banner).
Style matches the existing account tabs — subtle, dark, blue active state.

### What Changes Per Section

**Portfolio Balances:**
- Show performance FOR the selected period only
- "Period Return" replaces "ROI %" — gain/loss from the start of the period to today
- Cash Deposited = deposits made within the period only
- Dividends = dividends received within the period only
- Total Equity stays as current market value (point-in-time, not period-filtered)
- Add a "Period Start Value" field showing portfolio value at the start of the period

**Holdings Cards:**
- ROI % changes to show period return (price change from period start to today)
- Sparkline zooms to the selected period
- Dividends received within the period only
- Add a small "Period: +X.XX%" badge distinct from the all-time ROI

**Portfolio Value History Chart:**
- Automatically zooms to the selected period
- Keeps the existing range buttons (1M/3M/6M/1Y/3Y/All) on the chart itself in sync
  with the global selector

**Portfolio Stats:**
- Recompute all stats using only the returns within the selected period
- Observations count updates to reflect period length
- Sharpe, volatility, annualized return all recalculate for the period

**Dividend Income:**
- Monthly bar chart zooms to period
- Trailing 12M card stays as trailing 12M (not period-filtered — it is its own metric)
- Add a "Period Dividends" card showing total dividends within the selected period

**Correlation Matrix:**
- Recompute using only weekly returns within the selected period

### Backend Changes

Add an optional `period` query param to all relevant endpoints:
```
GET /api/portfolio?account=all&period=ytd
GET /api/holdings?account=all&period=1y
GET /api/stats?account=all&period=6m
GET /api/correlation?account=all&period=1y
GET /api/dividends?account=all&period=ytd
GET /api/portfolio/value-history?account=all&period=3y
```

`period` maps to a `start_date`:
```python
def period_to_start_date(period: str) -> date:
    today = date.today()
    return {
        "1m":  today - timedelta(days=30),
        "3m":  today - timedelta(days=90),
        "6m":  today - timedelta(days=180),
        "ytd": date(today.year, 1, 1),
        "1y":  today - timedelta(days=365),
        "3y":  today - timedelta(days=1095),
        "all": date(2000, 1, 1),
    }.get(period.lower(), date(2000, 1, 1))
```

### Excel Export — Period-Aware

When the user clicks "Export to Excel" while a time period is active:
- Sheet 1 title: "Portfolio Summary — YTD (Jan 1 – May 18, 2026)"
- All figures in the export reflect the selected period
- Sheet 4 (Transaction History) filters to transactions within the period
- Sheet 5 (Price History) filters to the period date range
- Add a "Period" field to Sheet 1 header row

### Frontend Changes

- Store selected period in React context (default: "all")
- All React Query hooks pass the period param — changing period invalidates and
  re-fetches all queries simultaneously
- URL param: update the window hash to `#period=ytd` so the user can bookmark/share
  a specific view (no router needed, just `window.location.hash`)

---

## Task 2 — CRA Tax Report Generator (Killer Feature)

The single most valuable feature for Canadian investors. No mainstream tool generates
a properly formatted Canadian capital gains report ready for tax filing.

### What It Produces

A PDF report (generated with `reportlab` Python library) titled:
**"Capital Gains / Losses Report — Tax Year 2025"**

Sections:

**Cover Page:**
- Profile name, tax year, generation date
- Summary: Total Taxable Gains, Total TFSA Gains (non-taxable), Net Taxable Amount,
  50% Inclusion Amount (the amount that goes on line 12700 of the T1)
- Disclaimer: "This report is for informational purposes. Verify with a qualified
  tax professional before filing."

**Section A — Realized Gains & Losses (Schedule 3 format):**
Table with CRA Schedule 3 columns:
- Description of property
- Date acquired
- Date disposed
- Proceeds of disposition
- Adjusted cost base
- Outlays and expenses (commissions)
- Gain or (loss)

One row per sell transaction. Subtotal at bottom.

**Section B — Superficial Loss Adjustments (if any):**
List any denied losses with the repurchase date and adjusted ACB.

**Section C — TFSA Activity Summary:**
All TFSA transactions for the year — clearly labelled "Non-Taxable".
Note: "Capital gains and losses within a TFSA are not reported on your tax return."

**Section D — Dividend Income Summary:**
Total dividends received per security, split by eligible vs non-eligible if known
(most Canadian ETF dividends are eligible — flag US dividends as foreign income).

**Backend:**
- Install `reportlab>=4.0` (add to requirements.txt)
- Add `GET /api/export/tax-report?year=2025` endpoint
- Year defaults to previous calendar year (tax season use case)
- Streams PDF as download: `Content-Disposition: attachment; filename="tax_report_2025.pdf"`

**Frontend:**
- Add "Tax Report" button in the SyncStatus banner (between Export to Excel and
  Import New Export)
- On click: open a small modal with a year picker (current year - 1 as default,
  allow any year from first transaction year to current year)
- "Generate PDF" button triggers the download
- Electron: use the native save dialog (via preload.js contextBridge) to let the
  user choose where to save the PDF

---

## Task 3 — TFSA Contribution Room Tracker

Uniquely Canadian and extremely useful. No investor should have to calculate this manually.

### How TFSA Room Works

- Every Canadian resident 18+ accumulates TFSA room each year (set by CRA annually)
- Room carries forward if unused
- Withdrawals add back room the following calendar year
- Over-contributions are penalized at 1% per month

### Cumulative Annual Limits (hardcode these, update each year):

```python
TFSA_ANNUAL_LIMITS = {
    2009: 5000, 2010: 5000, 2011: 5000, 2012: 5000, 2013: 5500,
    2014: 5500, 2015: 10000, 2016: 5500, 2017: 5500, 2018: 5500,
    2019: 6000, 2020: 6000, 2021: 6000, 2022: 6000, 2023: 6500,
    2024: 7000, 2025: 7000, 2026: 7000
}
```

### Implementation

**Backend — new endpoint:**
```
GET /api/tfsa/room?birth_year=1995&resident_since=2018
```

Params:
- `birth_year` — used to determine when room started accumulating (year turned 18)
- `resident_since` — year became Canadian resident (room only accumulates while resident)

Returns:
```json
{
  "total_room_accumulated": 75000,
  "total_contributions": 8000,
  "total_withdrawals": 0,
  "contribution_room_remaining": 67000,
  "current_year_limit": 7000,
  "contributions_this_year": 0,
  "withdrawals_last_year_added_back": 0,
  "over_contributed": false,
  "over_contribution_amount": 0,
  "annual_breakdown": [...]
}
```

Contributions are read from the TFSA account's `CONTRIBUTION` transactions in the DB.
Withdrawals are read from `WITHDRAWAL` transactions.

**Frontend — new "TFSA Room" card in the TFSA account tab:**

Shows:
- Large number: "Room Remaining: $67,000"
- Progress bar: contributions used vs total room (red if over-contributed)
- "You have $67,000 of TFSA room remaining" in plain English
- Current year: "You have contributed $0 of your $7,000 2026 limit"
- If over-contributed: red warning banner with the over-contribution amount

**Settings modal:**
Add a "TFSA Settings" section where the user enters their birth year and year they
became a Canadian resident. Stored in `app_state` table as `tfsa_birth_year` and
`tfsa_resident_since`. Prompted on first view of the TFSA tab if not set.

---

## Task 4 — Rebalancing Advisor

The user sets target allocation percentages. The app tells them exactly what to buy
or sell to hit those targets, given a specified investment amount or rebalance of
existing holdings.

### UI

New section at the bottom of the dashboard: "Rebalancing Advisor"

**Step 1 — Set Targets:**
A table showing each holding with an editable "Target %" column.
- Current % shown next to target %
- "Drift" column: how far off target (red if > 5% drift)
- Total must equal 100% — show a live sum with green/red indicator

**Step 2 — Choose Mode:**
- "Rebalance existing holdings" — calculate sells and buys to reach targets
- "Invest new money: $___" — calculate how to deploy new cash to move toward targets
  without selling (buy-only rebalancing)

**Step 3 — Results:**
Table showing:
- Action: BUY or SELL
- Security
- Shares: exact number (rounded down to whole shares)
- Estimated cost: shares × current price
- Resulting allocation %

Include a note: "Selling in your Margin account may trigger capital gains. Consider
selling in TFSA first where possible."

**Backend:**
```
POST /api/rebalance
Body: {
  "targets": [{"ticker": "VEQT.TO", "account_type": "TFSA", "target_pct": 60}, ...],
  "mode": "new_money" | "rebalance",
  "new_money_cad": 5000
}
```

Returns the buy/sell instructions. All math done in CAD using live prices.

---

## Task 5 — What-If Simulator

Interactive "what if" tool for scenario planning.

### Scenario Types

**"What if I buy X shares of Y today?"**
- Input: ticker, shares, account (TFSA/Margin)
- Output: new portfolio totals, new allocation %, projected annual dividends added,
  new ACB if adding to existing position

**"What if I sell X shares of Y today?"**
- Input: ticker, shares
- Output: capital gain/loss triggered (with ACB calculation shown step by step),
  tax owing estimate (if Margin account, at 50% inclusion, assuming 26% marginal rate
  as a default — user can change their marginal tax rate in settings),
  remaining position stats

**"What if I had invested $X on [date]?"**
- Input: amount, ticker, date
- Output: what that investment would be worth today, vs what leaving it as cash
  would have been worth, annualized return

**UI:** A "Simulator" button in the nav area (or as a tab on the Historical Chart section).
Opens a modal. Results shown inline — no page reload needed.

**Backend:**
```
POST /api/simulate/buy   → SimulationResult
POST /api/simulate/sell  → SimulationResult (includes capital gains breakdown)
POST /api/simulate/lump-sum → SimulationResult
```

All simulation results are ephemeral — nothing is written to the DB.

---

## Task 6 — Price Alerts

Let the user set price targets and get an in-app notification when a holding crosses them.

### How It Works

- User sets a "Buy below" or "Sell above" target price for any holding
- On each price refresh (every 30 min auto, or manual refresh), check all alerts
- If a price crosses an alert threshold, show an in-app notification badge
- Alerts persist in the DB until dismissed by the user

**Backend — new table `price_alerts`:**
```sql
price_alerts (
  id INTEGER PRIMARY KEY,
  ticker TEXT,
  alert_type TEXT,      -- "above" or "below"
  target_price REAL,
  currency TEXT,
  triggered BOOLEAN DEFAULT 0,
  triggered_at DATETIME,
  dismissed BOOLEAN DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

New endpoints:
```
GET    /api/alerts              → list active alerts
POST   /api/alerts              → create alert {ticker, type, target_price}
DELETE /api/alerts/{id}         → delete alert
POST   /api/alerts/{id}/dismiss → mark dismissed
GET    /api/alerts/triggered    → list alerts that have fired but not been dismissed
```

**Frontend:**
- Bell icon in the SyncStatus banner with a red badge count for untriggered alerts
- Alert panel slides in from the right when bell is clicked
- Each holding card has a "Set Alert" button (small bell icon, bottom right of card)
- After each price refresh, check `/api/alerts/triggered` and show a toast per alert:
  "🔔 AAPL crossed above $310.00 — current price $312.45"

---

## Task 7 — Performance Attribution

"Which holding drove my gains this month?"

A new section between Portfolio Value History and Holdings showing a horizontal
bar chart of each holding's contribution to total portfolio return for the selected
time period.

### Calculation

For each holding:
```
contribution = (gain_in_period_cad / total_portfolio_value_at_period_start) × 100
```

Where `gain_in_period_cad` = (current_price - price_at_period_start) × shares_held
(converted to CAD, using live rate for USD holdings).

### UI

Horizontal bar chart — one bar per holding:
- Green bars for positive contribution, red for negative
- Bars scaled proportionally
- Tooltip: "VEQT.TO (TFSA): +$432 (+3.24% of portfolio)"
- Summary line: "Top contributor: VEQT.TO (+3.24%). Biggest drag: T.TO (-0.89%)"
- Respects the global time horizon selector (Task 1)

**Backend:**
```
GET /api/attribution?account=all&period=ytd
```

---

## Task 8 — Dark / Light Mode Toggle

Currently dark-only. Light mode significantly broadens the potential user base and
is expected by App Store reviewers.

- Add a sun/moon toggle icon in the top-right of the SyncStatus banner
- Store preference in `app_state` as `color_theme` ("dark" | "light")
- Implement using Tailwind's `dark:` class system — set `darkMode: 'class'` in
  tailwind.config.js, toggle the `dark` class on `<html>`
- All existing colors already use Tailwind classes — audit for any hardcoded hex
  values in inline styles and replace with Tailwind equivalents
- Light mode palette:
  - Background: `#F8FAFC`
  - Card background: `#FFFFFF`
  - Border: `rgba(0,0,0,0.08)`
  - Text primary: `#0F172A`
  - Text muted: `#64748B`
  - Keep gain/loss colors the same (emerald/red are fine on both themes)

---

## Task 9 — Annual Portfolio Report PDF

A beautiful year-in-review PDF the user can share with an advisor or keep for records.

Different from the Tax Report (Task 2) — this is a performance report, not a tax document.

### Contents

**Page 1 — Cover:**
- Profile name, year, generation date
- Total portfolio value, total gain, simple rate of return
- A small portfolio value chart image (render using matplotlib, embed as PNG)

**Page 2 — Performance Summary:**
- Portfolio value at start of year vs end of year
- Benchmark comparison: portfolio vs S&P 500 for the year
- Best performing holding, worst performing holding
- Total dividends received

**Page 3 — Holdings Detail:**
- One row per holding: ticker, shares, ACB, current price, market value, ROI%, dividends

**Page 4 — Transaction History:**
- All transactions during the year in a clean table

**Page 5 — Dividend Calendar:**
- Monthly dividend income bar chart
- Upcoming projected payments

**Backend:**
```
GET /api/export/annual-report?year=2025
```

Uses `reportlab` (same dependency as Task 2). Streams as PDF download.

**Frontend:**
- "Annual Report" option in the same modal as the Tax Report (Task 2)
- Year picker, then download

---

## Task 10 — Settings Page

Currently there is no settings UI. Several features (Tasks 2, 3, 5) require user
preferences. Consolidate all settings into a proper page.

### Settings Sections

**Profile Settings:**
- Profile name (editable)
- Profile color picker
- Delete profile (with confirmation)

**Tax Settings:**
- Marginal tax rate (default 26%) — used by What-If Simulator for tax estimates
- Province (dropdown — future use for provincial tax rates)

**TFSA Settings:**
- Birth year
- Year became Canadian resident

**Display Settings:**
- Default time period (which period the dashboard opens to)
- Default currency view (Combined CAD / Combined USD / CAD only / USD only)
- Color theme (dark / light)

**Data Settings:**
- Price refresh interval (15 min / 30 min / 1 hour)
- Clear all data (nuclear option — deletes portfolio.db for active profile)
- Export all data as JSON (backup)

**Access:** Gear icon in the SyncStatus banner, top-right area.
Opens as a full-page overlay (not a modal — too much content).

---

## Task 11 — Wealthsimple Import (When Test Data Available)

The parser detection logic is already in place. When the user has a real Wealthsimple
export file, test the following:

1. Drop a Wealthsimple Activities CSV into the upload zone
2. Confirm auto-detection fires: "Detected: Wealthsimple Activities CSV"
3. Confirm all transactions parse correctly (buys, sells, dividends, deposits)
4. Confirm ACB calculates correctly for Wealthsimple holdings
5. Confirm mixed import: Questrade data + Wealthsimple data in same profile
6. Confirm dedup works correctly across both broker formats

If any parsing issues are found, fix `backend/parser.py` accordingly.

---

## Task 12 — App Store / Public Release Preparation

Before submitting to any app store or making the GitHub repo public:

### Code Quality
- Add docstrings to all backend Python functions
- Add JSDoc comments to all frontend TypeScript components
- Remove all `console.log` debug statements from frontend
- Remove any hardcoded test values or TODO comments

### Security
- Confirm no API keys, secrets, or personal data in the codebase
- Confirm `.gitignore` covers all DB files, logs, and build artifacts
- Confirm `backend.log` is never committed

### Version Bumping
- Update `electron/package.json` version to `0.2.0`
- Update `frontend/package.json` version to `0.2.0`
- Add a `CHANGELOG.md` documenting what's in each version

### Licensing
- Add `LICENSE` file (MIT recommended for open source)
- Add attribution for yfinance, SQLite, FastAPI, React, Electron in README

### README Updates
- Add screenshots of the app (capture from the running app)
- Add feature list with checkmarks
- Add "Coming soon" section for Wealthsimple, RRSP, direct broker API
- Add a "Roadmap" section

### Windows Store (future)
- electron-builder supports Windows Store (APPX) packaging
- Requires a Microsoft Developer account ($19 one-time)
- Add `win.target: ["nsis", "appx"]` to electron-builder.yml when ready

### Mac App Store (future)
- Requires Apple Developer account ($99/year)
- Requires code signing certificate
- Add `mac.target: ["dmg", "mas"]` to electron-builder.yml when ready

---

## Verification Checklist (Run After Every Task)

**Core functionality (must always pass):**
- [ ] Backend starts: `uvicorn backend.main:app --port 7842 --reload`
- [ ] Frontend compiles: `cd frontend && npm run typecheck`
- [ ] Import questrade_transactions.xlsx → 36 transactions, 7 holdings
- [ ] Re-import same file → 0 new / 36 skipped
- [ ] All 3 account tabs render (All / Margin / TFSA)
- [ ] Profile switching works, data isolated between profiles
- [ ] Export to Excel downloads a valid .xlsx file
- [ ] Packaged app launches via Launch Portfolio Dashboard.bat without crash
- [ ] No red errors in browser console (F12)
- [ ] backend.log shows no exceptions

**After Task 1 (time horizon):**
- [ ] Switching to YTD changes Holdings ROI % values
- [ ] Portfolio Stats recalculate for the selected period
- [ ] Excel export filename includes the period label
- [ ] Switching period back to "All" restores original values

**After Task 2 (tax report):**
- [ ] Tax Report PDF downloads without error
- [ ] PDF contains correct capital gains figures (verify against known values)
- [ ] PDF opens in Adobe Reader / Windows PDF viewer without corruption

**After Task 3 (TFSA room):**
- [ ] TFSA Room card appears on TFSA tab
- [ ] Room remaining = cumulative limit from resident_since year minus contributions

**After Task 4 (rebalancing):**
- [ ] Buy-only mode never produces SELL instructions
- [ ] Target % total validation prevents submission if not 100%
- [ ] Rebalance instructions use live prices

**After Task 5 (what-if):**
- [ ] Sell simulation capital gain matches manual ACB calculation
- [ ] Buy simulation does not write anything to the database
- [ ] Lump-sum simulation matches expected return for known historical prices

**After Task 6 (alerts):**
- [ ] Creating an alert persists after app restart
- [ ] Alert fires on next price refresh when price crosses threshold
- [ ] Dismissing alert removes it from the bell count

**After Task 12 (release prep):**
- [ ] `pwsh scripts/build-windows.ps1` produces a clean installer from scratch
- [ ] No secrets in `git log --all --full-history`
- [ ] README has screenshots and complete feature list

---

## Implementation Order

1. Task 1 — Global time horizon selector (highest user impact, do first)
2. Task 10 — Settings page (needed by Tasks 2, 3, 5 for user preferences)
3. Task 2 — CRA Tax Report PDF
4. Task 3 — TFSA Contribution Room Tracker
5. Task 8 — Dark / Light mode toggle
6. Task 7 — Performance Attribution chart
7. Task 4 — Rebalancing Advisor
8. Task 5 — What-If Simulator
9. Task 6 — Price Alerts
10. Task 9 — Annual Portfolio Report PDF
11. Task 11 — Wealthsimple import testing (when data available)
12. Task 12 — App Store / public release preparation (LAST)
