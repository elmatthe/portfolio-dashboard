# Portfolio Dashboard — Pre-Release Testing & Bug Hunt

Run this entire document before Task 12 (release preparation). The goal is to
exercise every feature of the app using the two test transaction files, catch any
bugs, fix them immediately, and produce a written summary report at the end.

The two test files are in the project root:
- `Questrade_Test_Transactions.xlsx` — 46 transactions, 2 accounts (Margin + TFSA)
- `Wealthsimple_Test_Transactions.csv` — 35 transactions, 2 accounts (TFSA + Personal)

Do not skip any section. Fix every bug found before moving to the next section.
At the end, write the full summary report exactly as specified in the Report Format
section at the bottom of this document.

---

## Setup — Start the App in Dev Mode

Run both servers from the project root:

Terminal 1:
```
uvicorn backend.main:app --port 7842 --reload
```

Terminal 2:
```
cd frontend && npm run dev
```

Open http://localhost:5173 in the browser.

Also open the browser DevTools console (F12) and keep it visible throughout testing.
Any red error that appears must be investigated and fixed before continuing.

---

## Phase A — Profile Setup

### A1 — Create "Test - Questrade" Profile
1. Click the profile pill (top-right)
2. Click "Add new profile"
3. Name: `Test - Questrade`, Color: Green (#10B981)
4. Confirm the app navigates to a fresh upload/welcome screen
5. Verify: profile pill now shows "Test - Questrade" in green

**Expected:** Fresh empty dashboard, no data from the default "My Portfolio" profile visible.
**Bug check:** If any holdings from My Portfolio appear, that is a profile isolation bug — fix it.

### A2 — Create "Test - Wealthsimple" Profile
1. Click profile pill → Add new profile
2. Name: `Test - Wealthsimple`, Color: Purple (#8B5CF6)
3. Verify fresh empty dashboard

### A3 — Verify Profile List
Click profile pill and confirm 3 profiles appear:
- My Portfolio (blue)
- Test - Questrade (green)
- Test - Wealthsimple (purple)

---

## Phase B — Questrade Import Testing

Switch to the "Test - Questrade" profile.

### B1 — First Import
1. Drag `Questrade_Test_Transactions.xlsx` into the upload zone
2. Confirm auto-detection fires: should show "Detected: Questrade Activities (.xlsx)"
3. Confirm the import result toast shows:
   - Inserted: 46 (not 0, not error)
   - Skipped duplicates: 0
   - New tickers resolved (should include XIU.TO, TD.TO, RY.TO, BNS.TO, CNR.TO, XEF.TO, MSFT, AMZN)
4. Confirm dashboard loads with holdings

**Expected holdings after import:**
| Ticker | Account | Shares | Notes |
|---|---|---|---|
| XIU.TO | Margin | 40 | Bought 30+20, sold 10 |
| TD.TO | Margin | 5 | Bought 10, sold 5 |
| RY.TO | Margin | 8 | All buys, no sells |
| BNS.TO | Margin | 5 | Bought 15, sold 10 |
| CNR.TO | Margin | 5 | No sells |
| MSFT | Margin | 3 | Bought 2+1 |
| AMZN | Margin | 0 | Bought 3, sold all 3 — should NOT appear as a holding |
| XIU.TO | TFSA | 125 | Bought 50+40+35 |
| XEF.TO | TFSA | 65 | Bought 30+25+30, sold 20, rebought 20 |

Verify share counts match the table above.
If AMZN appears as a holding with 0 shares, that is a bug — zero-share holdings
should not display as cards. Fix it.

### B2 — Deduplication Test
1. Drag `Questrade_Test_Transactions.xlsx` into the upload zone again
2. Confirm import result shows:
   - Inserted: 0
   - Skipped duplicates: 46
3. Confirm the dashboard is unchanged

**Bug check:** If inserted > 0 on the second import, the dedup hash is broken — fix it.

### B3 — ACB Verification

Check the following ACB values in the Holdings cards:

**XIU.TO (Margin):**
- Bought 30 @ 30.64 on 2023-01-20... wait, XIU.TO Margin was: 30 shares @ 30.64 (2023-02-05),
  then 20 @ ~33.20 (2024-01-15), then sold 10 @ ~34.5 (2024-11-20)
- ACB per share after all transactions should be approximately:
  (30×30.64 + 20×33.20) / 50 = (919.2 + 664.0) / 50 = $31.66/share (before commission)
  With commissions factored in, ACB ≈ $31.86/share
- Verify dashboard shows Avg Buy Price approximately in this range

**TD.TO (Margin):**
- Bought 10 @ 88.0 + $4.95 commission = total cost $884.95
- Sold 5 @ 82.72 (2023-09-15) — this is a LOSS (sold below buy price)
- Remaining 5 shares, ACB per share = $88.99/share (884.95 / 10 = 88.495 + commission portion)
- Verify capital gains table shows a LOSS entry for the TD.TO sell

**BNS.TO (Margin):**
- Bought 15 @ 68.0 = $1020 + $4.95 commission
- Sold 10 @ ~63.0 (2024-04-10) — this is a LOSS
- Remaining 5 shares
- Verify capital gains table shows a LOSS entry

**AMZN (Margin):**
- Bought 3 @ 153.0 = $459 USD
- Sold 2 @ ~210.0 (2025-06-01) — GAIN on partial sell... 
  wait, sold all 3 via add_sell(date(2025,6,1), "AMZN", 2) — only 2 sold
  Actually check: bought 3, sold 2 — 1 share remains
  Verify AMZN appears with 1 share remaining OR if the generation sold all 3 check again

**XEF.TO (TFSA) — superficial loss test:**
- Bought 30 (2023-01-20) + 25 (2024-01-20) + 30 (2025-01-20) = 85 shares total
- Sold 20 (2024-06-15)
- Rebought 20 (2024-07-05) — this is within 30 days of the sell → superficial loss rule applies
- Verify the capital gains section shows a superficial loss flag or adjustment note for this transaction
- After repurchase, total shares = 85 - 20 + 20 = 85... wait check: 30+25=55, sell 20 = 35, rebuy 20 = 55, then +30 = 85
  Actually: 30 (2023) + 25 (2024-01) + sell 20 (2024-06) + rebuy 20 (2024-07) + 30 (2025) = 85 shares
- Verify XEF.TO TFSA shows 85 shares

If share counts do not match, trace through the transaction log and fix the ACB engine.

### B4 — Capital Gains Report
Navigate to the Capital Gains section. Verify:
1. Sell events appear (should be 4 sells: XIU.TO Margin, TD.TO Margin, BNS.TO Margin, AMZN Margin)
2. TD.TO and BNS.TO show as LOSSES (red)
3. XIU.TO and AMZN show as GAINS (green)
4. All TFSA sells (XEF.TO) show "Non-Taxable" badge
5. Total Taxable Gain = sum of Margin gains minus Margin losses (net amount)
6. Manually verify one row: XIU.TO sell — 10 shares @ ~34.5, ACB ~31.66 = gain of ~$28.40
   Verify the table shows approximately this figure

**Bug check:** If TFSA sells show as taxable, that is a bug — fix it.

### B5 — Dividend Verification
Verify the following dividend totals in the Holdings cards:
- TD.TO (Margin): $8.80 + $8.80 + $4.40 + $4.40 = $26.40 CAD
- RY.TO (Margin): $10.32 + $10.32 + $10.72 = $31.36 CAD
- BNS.TO (Margin): $14.55 CAD
- XIU.TO (Margin): $6.50 + $7.80 = $14.30 CAD
- MSFT (Margin): $1.64 USD
- XIU.TO (TFSA): $7.65 + $14.40 + $22.75 = $44.80 CAD
- XEF.TO (TFSA): $9.90 + $12.35 + $17.10 = $39.35 CAD

If any figure is off by more than $0.05, investigate parser.py dividend attribution.

---

## Phase C — Wealthsimple Import Testing

Switch to "Test - Wealthsimple" profile.

### C1 — First Import
1. Drag `Wealthsimple_Test_Transactions.csv` into the upload zone
2. Confirm auto-detection: "Detected: Wealthsimple Activities (.csv)"
3. Confirm import result:
   - Inserted: 35
   - Skipped: 0
   - Tickers resolved: XEQT.TO, VFV.TO, SHOP.TO, ZSP.TO, GOOGL

**Expected holdings:**
| Ticker | Account | Shares | Notes |
|---|---|---|---|
| XEQT.TO | TFSA | 210 | 80+60+55+15 (repurchase after sell) |
| VFV.TO | TFSA | 40 | 20+15+15, sold 10 |
| ZSP.TO | Personal | 23 | 15+10+10, sold 12 |
| SHOP.TO | Personal | 5 | Bought 10, sold 5 |
| GOOGL | Personal | 2 | Bought 5, sold 3 |

Verify share counts match.

### C2 — Deduplication Test
Re-import `Wealthsimple_Test_Transactions.csv` — confirm 0 inserted, 35 skipped.

### C3 — Account Type Mapping
Verify the Wealthsimple account types mapped correctly:
- TFSA-9901 → TFSA account tab
- Personal-4402 → Margin account tab (Personal = non-registered = taxable)

Verify the account tabs show:
- All Accounts
- TFSA · TFSA-9901
- Margin · Personal-4402

### C4 — Capital Gains (Wealthsimple)
Verify SHOP.TO, ZSP.TO, GOOGL sells appear in Capital Gains:
- SHOP.TO sell (2023-11-15): 5 shares @ 106.17, ACB ~72.00 = GAIN ~$170
- ZSP.TO sell (2024-10-01): 12 shares, ACB ~$76.50 (blended 15+10 buys), GAIN expected
- GOOGL sell (2025-08-01): 3 shares @ ~192.0 USD, ACB 192.0 (bought at same price level), small gain/loss
- All Personal account sells should show as Taxable

---

## Phase D — Feature Testing (Both Profiles)

Switch back to "My Portfolio" (your real data) for D1-D5.
Then repeat D1-D5 for "Test - Questrade" to confirm features work with synthetic data.

### D1 — Time Period Selector
1. Click each period pill: 1M, 3M, 6M, YTD, 1Y, 3Y, All
2. For each period verify:
   - Holdings ROI % values change
   - Portfolio Stats "Observations" count changes
   - Portfolio Value History chart zooms to the period
   - Dividend Income chart zooms to the period
   - URL hash updates (e.g. #period=ytd)
3. Reload the page with #period=ytd in the URL — verify it loads with YTD pre-selected
4. Switch to a holding's Historical Chart — verify it also zooms

**Bug check:** If any period shows the same stats as "All", the period param is not
being passed. Check api.ts and usePortfolio hook.

### D2 — Excel Export (Period-Aware)
1. Select YTD period
2. Click "Export to Excel"
3. Open the downloaded file and verify:
   - Filename contains "ytd" and today's date
   - Sheet 1 title says "Year to date (2026-01-01 – [today])"
   - Sheet 4 (Transactions) only contains transactions from Jan 1 2026 onwards
   - Sheet 5 (Price History) only contains dates from Jan 1 2026 onwards
4. Select "All" period, export again
5. Verify Sheet 1 title says "All time" and Sheet 4 contains all transactions

### D3 — Settings Page
1. Click the gear icon → Settings page opens
2. Test each section:

**Profile Settings:**
- Change profile name → save → verify pill updates
- Change profile color → save → verify pill color changes
- Change name back to original

**Tax Settings:**
- Set marginal tax rate to 33% → save
- Open What-If Simulator → sell scenario → verify tax estimate uses 33%
- Reset to 26%

**TFSA Settings:**
- Set birth year to 1995, resident since 2015 → save
- Navigate to TFSA tab → verify TFSA Room card shows correct room:
  - Cumulative room from 2015 (age 18 check: born 1995, turned 18 in 2013, so resident since 2015 means room starts 2015)
  - 2015–2026 room = 10000+5500+5500+5500+6000+6000+6000+6000+6500+7000+7000+7000 = $77,500 total room
  - Minus contributions from the profile's TFSA transactions
  - Verify the math is approximately correct

**Display Settings:**
- Toggle light mode → verify entire app switches to light theme
- Toggle back to dark mode
- Change default period to "1Y" → save → reload page → verify 1Y is pre-selected

**Data Settings:**
- Do NOT click "Clear all data" during this test (would wipe the test profile)

### D4 — CRA Tax Report PDF
1. Click "Tax Report" button
2. Select year 2024 (the test data has sells in 2024)
3. Click "Generate PDF"
4. Open the downloaded PDF and verify:
   - Cover page shows profile name and year 2024
   - Section A shows the sell transactions from 2024
   - Gains are positive numbers, losses are shown in parentheses
   - TFSA sells appear in Section C (non-taxable), NOT in Section A
   - PDF is not corrupted (opens without error)
   - 50% inclusion amount is shown (total gain × 0.5)

### D5 — Annual Report PDF
1. Click "Annual Report" button
2. Select year 2025
3. Verify:
   - PDF downloads without error
   - Contains portfolio value chart image (not blank/broken)
   - Holdings table is present
   - Dividend calendar section is present

### D6 — TFSA Contribution Room Tracker
1. Switch to a profile with TFSA contributions
2. Navigate to TFSA account tab
3. Verify TFSA Room card shows:
   - A "Room Remaining" dollar figure
   - A progress bar
   - Current year contribution limit and how much used
4. If birth year / resident since not set, verify it prompts for these via settings

### D7 — Performance Attribution Chart
1. Select "All" period
2. Verify the Performance Attribution section shows a horizontal bar chart
3. Each holding has a bar (green positive, red negative)
4. Switch to YTD — verify bars update
5. Verify "Top contributor" and "Biggest drag" callout lines update

### D8 — Rebalancing Advisor
1. Scroll to Rebalancing Advisor section
2. Set target allocations (make them sum to 100%):
   - Set targets for each holding, e.g. 40% / 30% / 20% / 10%
3. Try to submit with total ≠ 100% → verify validation error appears
4. Set total to exactly 100% → submit
5. Test "Rebalance existing" mode → verify BUY and SELL instructions appear
6. Test "Invest new money: $5000" mode → verify only BUY instructions appear (no SELL)
7. Verify share counts are whole numbers (no fractional shares)

### D9 — What-If Simulator
Test all three modes:

**Buy simulation:**
- Ticker: VEQT.TO (or any held ticker), Shares: 10, Account: TFSA
- Verify: new portfolio total, new allocation %, projected dividends
- Confirm nothing was written to DB (holdings count unchanged after closing)

**Sell simulation:**
- Ticker: T.TO (or any Margin holding), Shares: 5
- Verify: capital gain/loss shown with step-by-step ACB breakdown
- Verify: tax estimate shown in dollars (at the marginal rate from settings)
- Verify: TFSA sell shows "Non-Taxable — no tax owing"
- Confirm nothing written to DB

**Lump-sum simulation:**
- Amount: $5000, Ticker: VEQT.TO, Date: 2024-01-01
- Verify: shows what $5000 invested on that date would be worth today
- Verify: shows annualized return
- Cross-check manually: VEQT was ~$27.20 on 2024-01-01, now ~$31.90
  $5000 / $27.20 = 183.8 shares × $31.90 = ~$5,866 today
  Verify simulator shows approximately $5,866

### D10 — Price Alerts
1. Click the bell icon → panel opens
2. Click "Set Alert" on any holding card
3. Create an alert: "VEQT.TO above $100.00" (a price that will never trigger)
4. Create another alert: "T.TO below $100.00" (a price that should already be triggered since T.TO is ~$16)
5. Click "Refresh Prices" → verify the T.TO alert fires and appears as a notification
6. Bell icon shows a badge count of 1
7. Dismiss the alert → badge count goes to 0
8. Restart the backend → reload app → verify the undismissed alert still exists (persisted in DB)

**Bug check:** If alerts disappear on restart, the DB persistence is broken — fix it.

### D11 — S&P 500 Benchmark Overlay
1. Navigate to Historical Price chart section
2. Select any holding (e.g. VEQT.TO)
3. Tick "Show S&P 500 benchmark" checkbox
4. Verify a grey dashed line appears on the chart
5. Hover tooltip shows both the holding price and the benchmark value
6. Switch date ranges (1M, 3M, 1Y) — verify benchmark updates
7. Untick checkbox → benchmark line disappears

### D12 — Correlation Matrix
1. In All Accounts view, verify the correlation matrix shows all 6 tickers (for My Portfolio)
2. Switch to Margin tab → matrix updates to Margin-only tickers
3. Switch to TFSA tab → matrix shows only TFSA tickers (may be 1×1 if single holding)
4. Switch time period to 1Y → matrix recalculates
5. Verify diagonal is always 1.00
6. Verify no NaN values appear in cells

### D13 — Portfolio Value History Chart
1. Verify the chart shows a continuous line from first deposit to today
2. The dashed grey line (net deposits) should always be below the solid line if portfolio is profitable
3. Switch time periods — chart zooms correctly
4. The headline "Portfolio Value: $XX,XXX CAD" matches Total Equity in the balances section
5. Hover over the chart — tooltip shows date and value

### D14 — Dividend Income Section
1. Verify monthly bar chart shows bars for months where dividends were received
2. "Upcoming Payments" table shows projected future dividends
3. "Yield on Cost" table shows all holdings that have paid dividends
4. Switch account tabs — dividends filter to the selected account
5. Switch time period — "Period Dividends" card updates

### D15 — Light/Dark Mode
1. Toggle to light mode via settings or sun icon
2. Scroll through the entire dashboard — no section should have white text on white background
   or dark text on dark background
3. All charts should remain readable in light mode
4. PDFs generated in light mode should still be dark/professional (PDF styling is backend only)
5. Reload the app — light mode should persist (stored in localStorage)
6. Toggle back to dark mode

### D16 — Profile Isolation Verification
1. Note the total equity shown in "Test - Questrade" profile
2. Switch to "Test - Wealthsimple" profile
3. Verify the total equity is completely different and only shows Wealthsimple holdings
4. Switch to "My Portfolio" — verify your real data is exactly as before
5. Verify no cross-contamination in any section

---

## Phase E — Packaged App Verification

Build the installer and run the same core tests in the packaged app (not dev mode).

```powershell
pwsh scripts\build-windows.ps1
```

After build completes:
1. Double-click `Launch Portfolio Dashboard.bat` from the project root
2. Confirm splash screen appears, then dashboard loads (no terminal required)
3. Confirm all 3 profiles are still present (DB persisted at %APPDATA%)
4. Run through this abbreviated checklist in the packaged app:
   - [ ] Import Wealthsimple CSV (in Test - Wealthsimple profile)
   - [ ] Time period selector works
   - [ ] Export to Excel downloads
   - [ ] CRA Tax Report PDF downloads and opens
   - [ ] Annual Report PDF downloads and opens
   - [ ] What-If Simulator opens and returns results
   - [ ] Price alert persists after closing and reopening the app
   - [ ] No "Backend stopped" dialog appears during 5 minutes of normal use
   - [ ] Check %APPDATA%\Portfolio Dashboard\backend.log — no exceptions

---

## Phase F — Browser Console Audit

With the dev server running, do a final pass:
1. Open DevTools → Console → enable "All levels"
2. Navigate through every section of the dashboard
3. Switch profiles, periods, account tabs
4. Open and close Settings, Simulator, Rebalancing Advisor, Alerts panel
5. Generate both PDFs

Any red error must be fixed. Yellow warnings are acceptable but should be noted.
List all console warnings found in the summary report.

---

## Bug Fix Protocol

When a bug is found during any phase:
1. Fix it immediately in the relevant file (backend or frontend)
2. If backend fix: restart uvicorn and re-run the failed test step
3. If frontend fix: Vite HMR will hot-reload; verify the fix
4. Note the bug and fix in the summary report
5. Continue to the next test step

Do not accumulate bugs and fix them all at the end — fix each one before continuing.

---

## Report Format

After all phases are complete, write a file called `TEST_REPORT.md` in the project
root with the following exact structure:

```markdown
# Portfolio Dashboard — Pre-Release Test Report
Generated: [date and time]
App version: 0.1.0 (pre-release)
Test files: Questrade_Test_Transactions.xlsx (46 rows), Wealthsimple_Test_Transactions.csv (35 rows)

## Test Environment
- OS: Windows [version]
- Node: [version]
- Python: [version]
- Dev mode: PASS/FAIL
- Packaged app: PASS/FAIL

## Phase A — Profile Setup
[PASS/FAIL for each test step with notes]

## Phase B — Questrade Import
[PASS/FAIL for each step]
### ACB Verification Results
- XIU.TO (Margin) ACB: $[actual] vs expected ~$31.86 → [PASS/FAIL]
- TD.TO (Margin) ACB: $[actual] vs expected ~$88.99 → [PASS/FAIL]
- [etc.]
### Share Count Results
- [ticker]: [actual shares] vs [expected shares] → [PASS/FAIL]

## Phase C — Wealthsimple Import
[PASS/FAIL for each step]
### Share Count Results
- [ticker]: [actual shares] vs [expected shares] → [PASS/FAIL]

## Phase D — Feature Testing
| Feature | Status | Notes |
|---|---|---|
| D1 — Time Period Selector | PASS/FAIL | |
| D2 — Excel Export | PASS/FAIL | |
| D3 — Settings Page | PASS/FAIL | |
| D4 — CRA Tax Report PDF | PASS/FAIL | |
| D5 — Annual Report PDF | PASS/FAIL | |
| D6 — TFSA Room Tracker | PASS/FAIL | |
| D7 — Performance Attribution | PASS/FAIL | |
| D8 — Rebalancing Advisor | PASS/FAIL | |
| D9 — What-If Simulator | PASS/FAIL | |
| D10 — Price Alerts | PASS/FAIL | |
| D11 — S&P 500 Benchmark | PASS/FAIL | |
| D12 — Correlation Matrix | PASS/FAIL | |
| D13 — Portfolio Value History | PASS/FAIL | |
| D14 — Dividend Income | PASS/FAIL | |
| D15 — Light/Dark Mode | PASS/FAIL | |
| D16 — Profile Isolation | PASS/FAIL | |

## Phase E — Packaged App
[PASS/FAIL for each step]

## Phase F — Console Audit
Errors found and fixed: [list]
Warnings remaining: [list]

## Bugs Found & Fixed
| # | Phase | Description | Root Cause | Fix Applied |
|---|---|---|---|---|
| 1 | B3 | [description] | [cause] | [fix] |
[etc. — list every bug found, even if minor]

## Bugs Outstanding (not fixed)
[List any bugs that could not be fixed, with reason]

## Data Accuracy Summary
- Questrade profile total equity: $[amount] CAD
- Questrade taxable capital gains (2024): $[amount] CAD
- Questrade taxable capital losses (2024): $[amount] CAD
- Wealthsimple profile total equity: $[amount] CAD
- All ACB calculations verified: YES/NO
- Superficial loss rule triggered on XEF.TO: YES/NO

## Overall Result
[READY FOR RELEASE / NOT READY — reason]
```

Save `TEST_REPORT.md` to the project root when complete.
```
