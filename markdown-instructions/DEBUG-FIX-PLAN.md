# Portfolio Dashboard — Debug Fix Plan
_Generated from ERROR-LOG.md audit (2026-05-21)_
_38 findings — 6 Critical · 4 High · 10 Medium · 16 Low · 2 Informational_

> **How to use this file:** Place it in `/markdown-instructions/`. Run `claude` from
> the repo root and paste the terminal prompt at the bottom of this document.
> Work through fixes in the order given — earlier fixes are prerequisites for later ones.
> After each numbered fix, run the verification command listed before moving on.
> Do NOT build or run electron-builder until §10 explicitly says to.

---

## Pre-Flight: Baseline Confirmation

Before touching any file, confirm the current test baseline is green:

```bash
cd backend
python -m pytest ../tests/ -v --tb=short 2>&1 | tail -20
```

Record the pass/fail counts. Every fix pass must end with this number equal or higher.
If baseline is already failing, fix the failing tests first before proceeding.

---

## PHASE 1 — Critical Fixes (do these first, in order)

### Fix #1 — FX Never Populated (CRITICAL)
**File:** `backend/store.py` (import call site) + `backend/parser.py` (parse pipeline)
**Finding:** `FXService.populate_transaction()` exists but is never called. Every USD
transaction has `fx_rate_to_cad = null` and `net_cad = null` in the DB.

**Steps:**

1. Open `backend/parser.py`. Find the function that calls `store.insert_transactions()`
   or wherever the parsed transaction list is finalised before DB insertion.

2. Locate or confirm the import of FXService:
   ```python
   from backend.fx.rates import FXService
   ```

3. In the parse pipeline, after the broker parser returns its transaction list and
   before `store.insert_transactions()` is called, add a population loop:
   ```python
   fx = FXService()
   for tx in transactions:
       fx.populate_transaction(tx)
   ```
   If `FXService` is a singleton (check `backend/fx/rates.py`), use the singleton getter.

4. Open `backend/fx/rates.py`. Read `populate_transaction()` to confirm its signature.
   Verify it mutates `tx.fx_rate_to_cad` and `tx.net_cad` in-place. If it returns a
   new object instead, update the loop accordingly:
   ```python
   transactions = [fx.populate_transaction(tx) for tx in transactions]
   ```

5. Also check `backend/main.py` — if there is a second code path where transactions
   are built inline (not via parser.py), apply the same FX population there.

6. **Also fix the aggregator (prerequisite for Fix #2):** Open `backend/portfolio.py`.
   Find where holdings are aggregated. Wherever `net_amount` is summed for USD
   transactions, ensure `net_cad` is used instead. Pattern to find:
   ```python
   # WRONG — sums USD and CAD amounts together
   total += tx.net_amount
   # RIGHT
   total += tx.net_cad if tx.net_cad is not None else tx.net_amount
   ```

**Verification:**
```bash
# Re-upload the Questrade XLSX (or Wealthsimple CSV)
curl -s -X POST http://localhost:7842/api/import \
  -F "file=@test-transaction-reports/Questrade_2024.xlsx" | python -m json.tool

# Then check the DB directly
python -c "
import sqlite3, json
conn = sqlite3.connect('data/profiles/084047b7/portfolio.db')
rows = conn.execute('''
  SELECT ticker, local_currency, fx_rate_to_cad, net_cad
  FROM transactions
  WHERE local_currency != \"CAD\"
  LIMIT 10
''').fetchall()
for r in rows:
    print(r)
conn.close()
"
```
Every USD row must now have a non-null `fx_rate_to_cad` and `net_cad`. If any are still
null, check the FXService static fallback table — it should at minimum return 1.35 for USD.

---

### Fix #2 — Capital Gains Aggregator Mixes CAD + USD (CRITICAL)
**File:** `backend/portfolio.py` lines ~274-310 (capital gains summary builder)
**Finding:** The aggregator sums raw `net_amount` across CAD and USD positions.
A USD gain of $26.66 is added to a CAD gain of $130.80 as if they are the same currency.
This directly corrupts the CRA Tax Report PDF.

**Steps:**

1. Open `backend/portfolio.py`. Find the capital-gains summary block — look for where
   realized gains per position are summed into a total:
   ```python
   total_realized_gain += position.realized_gain  # BUG if position is USD
   ```

2. Every realized-gain value from a USD position must be converted to CAD before
   being added to the CAD total. Use `net_cad` if available; fall back to
   `realized_gain * fx_rate_to_cad`:
   ```python
   if position.local_currency == "CAD":
       total_realized_gain_cad += position.realized_gain
   else:
       rate = position.fx_rate_to_cad or FXService().rate_to_cad(
           position.local_currency, position.transaction_date
       )
       total_realized_gain_cad += position.realized_gain * rate
   ```

3. The same conversion must be applied to the `total_proceeds` and `total_acb`
   components used to build the capital-gains aggregate. Find all three and fix all three.

4. Open `backend/tax_report.py`. Verify that it uses the corrected portfolio.py
   aggregate values rather than recomputing its own sum. If it has its own summation
   loop, apply the same CAD conversion there.

**Verification:**
```bash
curl -s http://localhost:7842/api/capital-gains | python -c "
import sys, json
d = json.load(sys.stdin)
print('Total realized CAD:', d.get('total_realized_gain_cad'))
print('Positions:', len(d.get('positions', [])))
# Manually verify: TD.TO -30.42 CAD + SHOP.TO +130.80 CAD + ... should sum correctly
"
```

---

### Fix #3 — Inter-Account Transfers Break Per-Account Returns (CRITICAL)
**File:** `backend/portfolio.py` lines ~274-294
**Finding:** When cash or positions are transferred between two accounts of the same
`account_type` (e.g., two Margin accounts), the transfer leg is treated as a gain on
the receiving account and a loss on the sending account, producing ~-92%/+360% returns.

**Steps:**

1. Open `backend/portfolio.py`. Find the per-account `period_return_pct` calculation block.

2. Locate where `net_deposits` (the denominator for return calculations) is computed.
   The fix is to exclude `TRANSFER` action transactions from the net-deposit and
   net-proceeds calculations entirely:
   ```python
   # Filter out transfers before computing deposits/proceeds
   non_transfer_txs = [tx for tx in account_txs if tx.action != "TRANSFER"]
   net_deposits = sum(tx.net_cad for tx in non_transfer_txs if tx.action == "DEPOSIT")
   ```

3. Also ensure that when computing `period_start_value` and `period_end_value`,
   transfer legs don't inflate either side. The position count should not change on a
   transfer (shares move, cash moves — net portfolio value is unchanged).

4. A simpler approach: in the `period_return_pct` formula, use total portfolio value
   change divided by net external cash flows only. Transfers are internal and must
   be excluded from both numerator and denominator:
   ```python
   # period_return_pct = (end_value - start_value - net_external_inflows) / start_value
   external_inflows = sum(
       tx.net_cad for tx in account_txs
       if tx.action in ("DEPOSIT", "BUY") and tx.action != "TRANSFER"
   )
   ```

**Verification:**
Create or identify two same-type accounts in the DB with transfers between them.
```bash
curl -s "http://localhost:7842/api/portfolio?period=ytd" | python -c "
import sys, json
d = json.load(sys.stdin)
for acct in d.get('accounts', []):
    pct = acct.get('period_return_pct', 'N/A')
    print(acct['account_type'], acct['account_number'], pct)
    assert abs(float(pct)) < 200, f'Return {pct}% is implausible — transfer bug not fixed'
"
```

---

### Fix #4 — `period=all` Always Returns 0% Return (CRITICAL)
**File:** `backend/portfolio.py`
**Finding:** `period=all` returns `period_start_value_cad: 0.0` and
`period_return_pct: 0.0`. The lifetime return — the most important view — is permanently zero.

**Steps:**

1. Open `backend/portfolio.py`. Find the period-filtering logic. It should look like:
   ```python
   if period == "all":
       from_date = None  # or datetime.min
   ```

2. The bug is in how `period_start_value` is computed when `from_date` is None.
   Likely the code does:
   ```python
   period_start_value = get_portfolio_value_at(from_date)  # returns 0 when from_date is None
   ```

3. Fix: when `period == "all"`, set `period_start_value` to the portfolio value at the
   date of the **very first transaction** in the profile:
   ```python
   if period == "all":
       first_tx_date = store.get_first_transaction_date()  # implement if missing
       period_start_value_cad = get_portfolio_value_at(first_tx_date) or 0.0
       # For an all-time view, first investment = net deposits = correct base
       period_start_value_cad = total_net_deposits_cad  # simpler and more correct
   ```

4. The cleanest fix: for `period=all`, `period_return_pct` should be computed as:
   ```python
   period_return_pct = (current_value - total_net_deposits) / total_net_deposits * 100
   ```
   This is the standard simple return formula for a buy-and-hold portfolio.

5. In `backend/store.py`, implement `get_first_transaction_date()` if it doesn't exist:
   ```python
   def get_first_transaction_date(conn) -> date | None:
       row = conn.execute(
           "SELECT MIN(transaction_date) FROM transactions"
       ).fetchone()
       return row[0] if row and row[0] else None
   ```

**Verification:**
```bash
curl -s "http://localhost:7842/api/portfolio?period=all" | python -c "
import sys, json
d = json.load(sys.stdin)
pct = d.get('period_return_pct', 0)
val = d.get('period_start_value_cad', 0)
print(f'period_return_pct={pct}, period_start_value_cad={val}')
assert pct != 0.0, 'Bug #4 not fixed — lifetime return is still 0%'
assert val != 0.0, 'period_start_value_cad is still 0'
"
```

---

### Fix #5 — Rebalancer `mode=new_money` Exceeds Budget (CRITICAL)
**File:** `backend/rebalance.py` lines ~65-90
**Finding:** $5,000 injected results in $8,600 of suggested buys. The rebalancer
does not correctly constrain total buy cost to `new_money_cad`.

**Steps:**

1. Open `backend/rebalance.py`. Find the `new_money` mode calculation block.

2. The algorithm should be:
   ```
   For each target ticker:
     target_value = (current_portfolio_value + new_money) × target_pct
     current_value = current holding value in CAD
     shortfall = target_value - current_value
     if shortfall > 0: recommend BUY of floor(shortfall / price) shares
   ```

3. The bug is almost certainly that the total of all `shortfall` values is not capped
   to `new_money_cad`. After computing all buys, enforce the budget constraint:
   ```python
   total_buy_cost = sum(action.cost_cad for action in buy_actions)
   if total_buy_cost > new_money_cad:
       # Scale down all buys proportionally
       scale = new_money_cad / total_buy_cost
       for action in buy_actions:
           action.shares = floor(action.shares * scale)
           action.cost_cad = action.shares * action.price_cad
   ```

4. Also add a post-check assertion:
   ```python
   final_cost = sum(a.cost_cad for a in buy_actions)
   assert final_cost <= new_money_cad + 1.0, \
       f"Rebalancer exceeded budget: {final_cost} > {new_money_cad}"
   ```

**Verification:**
```bash
curl -s -X POST http://localhost:7842/api/rebalance \
  -H "Content-Type: application/json" \
  -d '{"mode":"new_money","new_money_cad":5000,"targets":{"VFV.TO":0.5,"XEF.TO":0.3,"VCN.TO":0.2}}' \
  | python -c "
import sys, json
d = json.load(sys.stdin)
buys = [a for a in d.get('actions', []) if a['action'] == 'BUY']
total = sum(a['cost_cad'] for a in buys)
print(f'Total buy cost: \${total:.2f} (budget: \$5000)')
assert total <= 5000 + 1, f'Budget exceeded: \${total:.2f}'
print('PASS')
"
```

---

### Fix #6 — Rebalancer `mode=rebalance` Cash-Negative + Cross-Account (CRITICAL)
**File:** `backend/rebalance.py`
**Finding:** In pure-rebalance mode, buy totals exceed sell totals (cash-negative result).
TFSA sell proceeds are used to fund Margin account buys — illegal and incorrect.

**Steps:**

1. Open `backend/rebalance.py`. Find the `rebalance` mode block.

2. **Fix cash neutrality:** The total cost of all BUY actions must not exceed the total
   proceeds of all SELL actions plus any existing cash balance. After computing all
   actions, enforce:
   ```python
   total_sells = sum(a.proceeds_cad for a in sell_actions)
   total_buys  = sum(a.cost_cad for a in buy_actions)
   cash_gap = total_buys - total_sells
   if cash_gap > 1.0:
       # Scale down buys proportionally until cash-neutral
       scale = total_sells / total_buys
       for action in buy_actions:
           action.shares = floor(action.shares * scale)
           action.cost_cad = action.shares * action.price_cad
   ```

3. **Fix account separation:** Group actions by `account_type`. Sell proceeds from
   a TFSA can only fund buys within the same TFSA. Proceeds from a Margin account
   can only fund buys in a Margin account. Implement per-account rebalancing:
   ```python
   from itertools import groupby
   accounts = group_holdings_by_account(holdings)
   all_actions = []
   for account_id, account_holdings in accounts.items():
       account_actions = rebalance_single_account(
           account_holdings, targets, account_id
       )
       all_actions.extend(account_actions)
   ```

4. Add a warning field to the response when a target ticker is held in multiple accounts:
   ```json
   {"warnings": ["VFV.TO held in both TFSA and Margin — rebalanced independently per account"]}
   ```

5. Add TFSA capital-gains warning when a sell would not trigger gains (it should say
   "no tax impact" for TFSA sells, not the Margin warning):
   ```python
   if account_type == "TFSA":
       action.tax_note = "No capital gains tax — TFSA account"
   elif account_type in ("Margin", "Non-Registered", "Individual", "IRA"):
       action.tax_note = "May trigger capital gains — review before executing"
   ```

**Verification:**
```bash
curl -s -X POST http://localhost:7842/api/rebalance \
  -H "Content-Type: application/json" \
  -d '{"mode":"rebalance","targets":{"VFV.TO":0.6,"XEF.TO":0.4}}' \
  | python -c "
import sys, json
d = json.load(sys.stdin)
actions = d.get('actions', [])
sells = sum(a['proceeds_cad'] for a in actions if a['action']=='SELL')
buys  = sum(a['cost_cad']  for a in actions if a['action']=='BUY')
print(f'Total sells: \${sells:.2f}  Total buys: \${buys:.2f}  Gap: \${buys-sells:.2f}')
assert buys <= sells + 1.0, f'Cash-negative: buys exceed sells by \${buys-sells:.2f}'
print('PASS')
"
```

---

## PHASE 2 — High Priority Fixes

### Fix #7 — Annual Report PDF Missing Embedded Charts (HIGH)
**File:** `backend/annual_report.py`
**Finding:** PDF is ~6 KB. A 5-page PDF with embedded matplotlib PNGs should be
40–200 KB minimum. Charts are likely not being embedded or are being skipped on error.

**Steps:**

1. Open `backend/annual_report.py`. Find the chart-generation block — look for
   `matplotlib`, `plt.savefig`, or similar calls.

2. Wrap every chart generation in try/except and print the exception to stderr:
   ```python
   try:
       fig, ax = plt.subplots(...)
       # ... chart code ...
       buf = io.BytesIO()
       fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
       buf.seek(0)
       chart_png = buf.read()
       plt.close(fig)
   except Exception as e:
       import traceback
       traceback.print_exc()
       chart_png = None
   ```

3. Confirm whether `chart_png` is ever `None` in the current flow. If it is, the
   PDF section that inserts the image either silently skips it or inserts nothing.
   Add a fallback placeholder so you know when a chart is missing:
   ```python
   if chart_png is None:
       pdf_canvas.drawString(72, 500, "[Chart unavailable — see backend.log]")
   ```

4. Check `backend/requirements.txt` — confirm `matplotlib` is listed. If it was
   added as an implicit dependency, PyInstaller may have missed it. Add explicitly:
   ```
   matplotlib>=3.8.0
   ```

5. Check `backend.spec` `hiddenimports` — add `matplotlib` and its backends if missing:
   ```python
   hiddenimports=['matplotlib', 'matplotlib.backends.backend_agg', 'PIL._imagingtk']
   ```

**Verification:**
```bash
curl -s -o /tmp/annual_report.pdf http://localhost:7842/api/export/annual-report
ls -la /tmp/annual_report.pdf
python -c "
size = $(ls -la /tmp/annual_report.pdf | awk '{print \$5}')
print('Size:', size, 'bytes')
assert size > 40000, f'PDF too small ({size} bytes) — charts still missing'
print('PASS')
"
```

---

### Fix #8 — Parser Registry `KeyError: 'generic'` in Packaged Builds (HIGH)
**File:** `backend/parsers/registry.py` + `backend.spec`
**Finding:** Historical crash `KeyError: 'generic'` in `%APPDATA%\backend.log`.
PyInstaller doesn't auto-discover the `generic` parser module.

**Steps:**

1. Open `backend.spec`. Find the `hiddenimports` list. Add all 12 parser modules:
   ```python
   hiddenimports=[
       'backend.parsers.generic',
       'backend.parsers.questrade',
       'backend.parsers.wealthsimple',
       'backend.parsers.rbc',
       'backend.parsers.cibc',
       'backend.parsers.td',
       'backend.parsers.bmo',
       'backend.parsers.scotiabank',
       'backend.parsers.interactive',
       'backend.parsers.nationalbank',
       'backend.parsers.fidelity',
       'backend.parsers.hsbc',
       'backend.parsers._common',
       'backend.fx.rates',
       'matplotlib',
       'matplotlib.backends.backend_agg',
       'pdfplumber',
   ]
   ```

2. Open `backend/parsers/registry.py`. After the `BROKER_PARSERS` dict is defined,
   add a startup assertion that will cause the binary to fail-fast with a clear error
   rather than a cryptic KeyError at runtime:
   ```python
   _EXPECTED_KEYS = {
       'questrade', 'wealthsimple', 'rbc', 'cibc', 'td', 'bmo',
       'scotiabank', 'interactive_brokers', 'national_bank', 'fidelity',
       'hsbc', 'generic'
   }
   assert _EXPECTED_KEYS == set(BROKER_PARSERS.keys()), \
       f"Registry incomplete. Missing: {_EXPECTED_KEYS - set(BROKER_PARSERS.keys())}"
   ```

3. Add a pytest test so this never regresses:
   ```python
   # tests/test_registry.py
   def test_all_parsers_registered():
       from backend.parsers.registry import BROKER_PARSERS
       assert 'generic' in BROKER_PARSERS
       assert len(BROKER_PARSERS) == 12
   ```

**Verification:**
```bash
python -c "
from backend.parsers.registry import BROKER_PARSERS
assert len(BROKER_PARSERS) == 12, f'Only {len(BROKER_PARSERS)} parsers registered'
assert 'generic' in BROKER_PARSERS, 'generic parser missing'
print('Registry OK:', list(BROKER_PARSERS.keys()))
"
```

---

### Fix #9 — Electron Hard-Kills Backend, WAL Never Checkpointed (HIGH)
**File:** `electron/main.js` lines ~282-286
**Finding:** App quit uses raw `kill()` (Windows TerminateProcess). SQLite WAL
never checkpointed. Evidence: 4.5 MB `.db-wal` files in production.

**Steps:**

1. Open `electron/main.js`. Find the `app.on('before-quit')` or `app.on('will-quit')`
   handler (or the absence of one).

2. Replace the hard-kill with a graceful shutdown sequence:
   ```javascript
   app.on('before-quit', async (event) => {
     if (backendProcess && !backendProcess.killed) {
       event.preventDefault();
       try {
         // Ask FastAPI to shut down via its lifespan endpoint
         await fetch('http://127.0.0.1:7842/api/shutdown', { method: 'POST' })
           .catch(() => {}); // ignore if already dead
         // Give it 3 seconds to checkpoint WAL and close cleanly
         await new Promise(resolve => setTimeout(resolve, 3000));
       } finally {
         backendProcess.kill('SIGTERM');
         app.quit();
       }
     }
   });
   ```

3. In `backend/main.py`, add the shutdown endpoint if it doesn't exist:
   ```python
   @app.post("/api/shutdown")
   async def shutdown():
       """Called by Electron before app quit to allow clean DB checkpoint."""
       import threading
       def _shutdown():
           import time, os, signal
           time.sleep(0.5)
           os.kill(os.getpid(), signal.SIGTERM)
       threading.Thread(target=_shutdown, daemon=True).start()
       return {"status": "shutting down"}
   ```

4. In `backend/db.py`, ensure the lifespan shutdown includes a WAL checkpoint:
   ```python
   # In the FastAPI lifespan shutdown block or app teardown:
   conn.execute("PRAGMA wal_checkpoint(FULL)")
   conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
   ```

**Verification (manual):**
Launch the packaged app (after rebuild), import a file, then quit normally.
```powershell
$walFile = "$env:APPDATA\Portfolio Dashboard\profiles\*\portfolio.db-wal"
$size = (Get-Item $walFile -ErrorAction SilentlyContinue).Length
if ($size -eq $null -or $size -lt 100000) {
    Write-Host "PASS — WAL size: $size bytes (was 4.5 MB)"
} else {
    Write-Host "FAIL — WAL still large: $size bytes"
}
```

---

### Fix #10 — Unknown Account Filter Returns All Holdings Silently (HIGH)
**File:** `backend/portfolio.py` (account filter logic)
**Finding:** `GET /api/holdings?account=RRSP` on a no-RRSP portfolio returns all
holdings instead of an empty list or 404. Masquerades as a valid filter.

**Steps:**

1. Open `backend/portfolio.py` or `backend/main.py`. Find the account filtering block:
   ```python
   if account:
       holdings = [h for h in holdings if h.account_type == account]
   ```

2. Add explicit validation against the known account types in the profile:
   ```python
   if account:
       known_accounts = {h.account_type for h in all_holdings}
       if account not in known_accounts and account != "all":
           # Return 422 with a helpful error
           from fastapi import HTTPException
           raise HTTPException(
               status_code=422,
               detail=f"Account type '{account}' not found. "
                      f"Available: {sorted(known_accounts)}"
           )
       holdings = [h for h in all_holdings if h.account_type == account]
   ```

3. Do the same for the `period` parameter (fixes Medium finding #11 at the same time):
   ```python
   VALID_PERIODS = {"1m", "3m", "6m", "ytd", "1y", "3y", "all"}
   if period not in VALID_PERIODS:
       raise HTTPException(
           status_code=422,
           detail=f"Invalid period '{period}'. Valid values: {sorted(VALID_PERIODS)}"
       )
   ```

**Verification:**
```bash
# Should return 422, not all holdings
curl -s -o /dev/null -w "%{http_code}" \
  "http://localhost:7842/api/holdings?account=BOGUS"
# Expected: 422

curl -s -o /dev/null -w "%{http_code}" \
  "http://localhost:7842/api/portfolio?period=garbage"
# Expected: 422
```

---

## PHASE 3 — Medium Priority Fixes

Work through these after all 6 Critical and 4 High fixes are confirmed passing.

### Fix #11 — Unknown Period Silently Falls Through (MEDIUM)
Already covered in Fix #10 Step 3. Confirm it's done.

### Fix #12 — TFSA Birth Year Unset Overstates Room (MEDIUM)
**File:** `backend/tfsa.py` line ~94

```python
# Before
eligibility_year = settings.get('tfsa_birth_year', 2009) + 18  # silently assumes 2009
# After
birth_year = settings.get('tfsa_birth_year')
if birth_year is None:
    return {
        "error": "tfsa_birth_year not set in profile settings",
        "message": "Please set your birth year in Settings > Tax to calculate TFSA room accurately.",
        "total_room_accumulated": None
    }
eligibility_year = birth_year + 18
```

### Fix #13 — TFSA `total_room_accumulated` Misleading Name (MEDIUM)
**File:** `backend/tfsa.py` line ~157
Rename the field to `available_room` in the response and add clear field descriptions:
```python
return {
    "available_room": available_room,          # what you can contribute today
    "cumulative_limit_to_date": cumulative,    # CRA annual limits summed
    "total_contributions": total_contributions,
    "total_withdrawals_prior_year": withdrawals,
    "calculation_note": "Withdrawals from prior years restore room in the following calendar year"
}
```
Update `frontend/src/types.ts` and any component that reads `total_room_accumulated`.

### Fix #14 — USD TFSA Contributions at Hardcoded 1.0 Rate (MEDIUM)
**File:** `backend/tfsa.py` lines ~104-110
```python
# Before
contribution_cad = amt * 1.0  # BUG

# After
from backend.fx.rates import FXService
fx = FXService()
rate = fx.rate_to_cad(tx.local_currency, tx.transaction_date)
contribution_cad = amt * rate
```

### Fix #15 — Rebalancer Ignores New Tickers (MEDIUM)
**File:** `backend/rebalance.py` line ~75
The rebalancer should support targeting tickers not currently held. The current
warning-and-skip should become a BUY with 0 current value:
```python
current_value_cad = holdings_map.get(ticker, {}).get('market_value_cad', 0.0)
# Don't skip — proceed with current_value_cad = 0
```
Fetch the current price for the new ticker via `market_data.get_price(ticker)`.
If the price fetch fails (unknown ticker), return a 422 with:
```json
{"error": "Ticker 'XYZ' not found — verify the symbol before targeting"}
```

### Fix #16 — Tax Warning Hardcoded to Margin Only (MEDIUM)
**File:** `backend/rebalance.py` line ~123
```python
# Before
if account_type == "Margin":

# After
TAXABLE_ACCOUNT_TYPES = {"Margin", "Non-Registered", "Individual", "IRA", "Roth IRA", "Traditional IRA"}
if account_type in TAXABLE_ACCOUNT_TYPES:
```

### Fix #17 — Same-Day Repurchases Excluded from Superficial Loss (MEDIUM)
**File:** `backend/acb.py` line ~186
The CRA 30-day window is inclusive of the sale date itself. A same-day repurchase
qualifies as a superficial loss trigger.
```python
# Before (exclusive of sale date)
if (repurchase_date - sale_date).days > 0 and (repurchase_date - sale_date).days <= 30:

# After (inclusive — CRA rule)
if 0 <= (repurchase_date - sale_date).days <= 30:
```
Also apply the same fix to the lookback window (30 days before the sale).

### Fix #18 — `fx_rate_for_date` Parameter Dead in `acb.py` (MEDIUM)
**File:** `backend/acb.py` line ~82
Either wire it up or remove it:
```python
# Option A: wire up (preferred)
if fx_rate_for_date:
    cost_cad = shares_bought * price * fx_rate_for_date
else:
    cost_cad = shares_bought * price  # assumes CAD

# Option B: remove if unused
# Delete the parameter and update all callers
```

### Fix #19 — `/api/capital-gains` Missing `year` Filter (MEDIUM)
**File:** `backend/main.py` (capital-gains endpoint)
```python
@app.get("/api/capital-gains")
async def capital_gains(
    account: str | None = None,
    period: str | None = None,
    year: int | None = None,   # ADD THIS
):
    gains = portfolio.get_capital_gains(account=account, period=period, year=year)
    ...
```
In `backend/portfolio.py`, filter `closed_positions` by `tx.transaction_date.year == year`
when `year` is provided.

### Fix #20 — Backend Port Hardcoded, No Auto-Retry (MEDIUM)
**File:** `electron/main.js` line ~13 and `backend/main.py` line ~712

This is a medium-effort fix. Implement a simple port-finding function in Electron:
```javascript
const net = require('net');

function findFreePort(preferred = 7842) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.listen(preferred, () => {
      server.close(() => resolve(preferred));
    });
    server.on('error', () => {
      // preferred port busy — try a random one
      const s = net.createServer();
      s.listen(0, () => {
        const port = s.address().port;
        s.close(() => resolve(port));
      });
    });
  });
}
```
Pass the found port to the backend process via environment variable and to the
frontend via `window.BACKEND_PORT` set in the preload script.

---

## PHASE 4 — Low Priority & Cleanup

Do these after all Critical, High, and Medium fixes are verified.

### Fix #21 — Correlation Matrix Cold-Start Identity (LOW)
**File:** `backend/main.py` or the correlation endpoint
On first load, trigger price history fetches for all held tickers before returning
the correlation matrix. Or return an explicit `"warming_up": true` flag in the
response so the UI can show a loading state instead of a misleading identity matrix.

### Fix #22 — `datetime.utcnow()` Deprecated (LOW)
**File:** `backend/main.py` lines ~94, 323, 343 (and any others found by grep)
```bash
grep -rn "utcnow()" backend/ --include="*.py"
```
Replace every instance:
```python
# Before
datetime.datetime.utcnow()
# After
datetime.datetime.now(datetime.timezone.utc)
```

### Fix #23 — `npm run dev` Broken on PowerShell (LOW)
**File:** `electron/package.json` line ~11
```json
// Before
"dev": "NODE_ENV=development electron ."

// After (cross-platform)
"dev": "cross-env NODE_ENV=development electron ."
```
Install the dependency:
```bash
cd electron && npm install --save-dev cross-env
```

### Fix #24 — No ESLint Configured (LOW)
```bash
cd frontend
npm install --save-dev eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin eslint-plugin-react-hooks
```
Create `frontend/.eslintrc.json`:
```json
{
  "root": true,
  "parser": "@typescript-eslint/parser",
  "plugins": ["@typescript-eslint", "react-hooks"],
  "extends": [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended"
  ],
  "rules": {
    "@typescript-eslint/no-explicit-any": "warn",
    "react-hooks/exhaustive-deps": "warn"
  }
}
```
Run `npx eslint src/ --ext .ts,.tsx` and fix any errors (warnings can be deferred).

### Fix #25 — `shell.openExternal` No URL Validation (LOW)
**File:** `electron/main.js` line ~248
```javascript
// Before
shell.openExternal(url);

// After
const ALLOWED_PROTOCOLS = ['https:', 'http:'];
try {
  const parsed = new URL(url);
  if (ALLOWED_PROTOCOLS.includes(parsed.protocol)) {
    shell.openExternal(url);
  }
} catch (e) {
  console.error('Blocked invalid URL:', url);
}
```

### Fix #26 — Missing CSP (LOW)
**File:** `electron/main.js` (BrowserWindow creation)
Add a Content Security Policy to the main window:
```javascript
webPreferences: {
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  // ...existing prefs
},
```
And in the `session.defaultSession.webRequest.onHeadersReceived` handler:
```javascript
session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
  callback({
    responseHeaders: {
      ...details.responseHeaders,
      'Content-Security-Policy': [
        "default-src 'self'; script-src 'self'; connect-src 'self' http://127.0.0.1:7842"
      ]
    }
  });
});
```

### Fix #27 — Placeholder App ID and Missing Icon (LOW)
**File:** `electron/electron-builder.yml`
```yaml
# Before
appId: com.yourname.portfoliodashboard

# After
appId: com.portfoliodashboard.app
productName: Portfolio Dashboard
```
Create a proper app icon:
1. Design or source a 1024×1024 PNG logo and save as `assets/icon.png`
2. Convert to ICO for Windows (use `electron-icon-builder` or an online converter):
   ```bash
   npx electron-icon-builder --input=assets/icon.png --output=assets/
   ```
3. Reference in `electron-builder.yml`:
   ```yaml
   win:
     icon: assets/icon.ico
   mac:
     icon: assets/icon.icns
   linux:
     icon: assets/icon.png
   ```

### Fix #28 — Author Placeholder (LOW)
**File:** `electron/package.json` line ~7
Update `"author"` to your real name and email. Also update `frontend/package.json`.

### Fix #29 — Stale README References (LOW)
**File:** `README.md`
- Replace all references to `Portfolio Dashboard Setup 0.2.0.exe` with the current version
- Replace `[Releases page](#)` with your actual GitHub releases URL
- Update version numbers in installation instructions to match `package.json`
- These will be rewritten in full in the README pass (§6 below)

### Fix #30 — Version Mismatch Across Three Files (LOW)
After all fixes are done and a new version is ready to build, synchronise:
```bash
# Set to 0.5.0 (or whatever the next version is)
NEW_VERSION="0.5.0"

# backend/main.py — find the version string
sed -i "s/version=\"0\.[0-9]\+\.[0-9]\+\"/version=\"$NEW_VERSION\"/" backend/main.py

# frontend/package.json
cd frontend && npm version $NEW_VERSION --no-git-tag-version && cd ..

# electron/package.json
cd electron && npm version $NEW_VERSION --no-git-tag-version && cd ..

# CHANGELOG.md — add a new [0.5.0] section at the top (see §7 below)
```
Verify all three agree:
```bash
grep -E '"version"' frontend/package.json electron/package.json
grep -E 'version=' backend/main.py
```

### Fix #31 — `.gitignore` Violations (LOW)
Untrack the committed files that should be ignored:
```bash
git rm --cached backend.spec build-output*.log
git rm --cached -r data/ .pytest_cache/
# Add to .gitignore if not already present:
echo "backend.spec" >> .gitignore
echo "build-output*.log" >> .gitignore
echo "data/" >> .gitignore
echo ".pytest_cache/" >> .gitignore
echo "test-transaction-reports/" >> .gitignore
git add .gitignore
git commit -m "chore: untrack generated files and add to .gitignore"
```

### Fix #32 — Real Account Numbers in Committed DB (LOW / PRIVACY)
**IMPORTANT — do this before any public git push:**
```bash
# Remove the profile DB from git history
git rm --cached "data/profiles/084047b7/portfolio.db"
git rm --cached "data/profiles/084047b7/portfolio.db-shm"
git rm --cached "data/profiles/084047b7/portfolio.db-wal"
git rm --cached "data/profiles.json"
git rm --cached "data/portfolio.db"

# Ensure data/ is in .gitignore (done in Fix #31)
git commit -m "security: remove profile databases with account numbers from tracking"
```
Consider using `git filter-repo` or BFG Repo Cleaner if these files were pushed to a
remote, to purge them from history entirely.

### Fix #33 — Limited Questrade Ticker Mapping (LOW)
**File:** `backend/parser.py` lines ~261-270
No immediate code fix needed — this is a data gap. Add a comment documenting the
known limitation and a TODO to source a more complete mapping:
```python
# TODO: Expand this mapping. Current 8-entry table covers only the most common
# Questrade internal IDs. A complete mapping is available at:
# https://github.com/tsiemens/acb (see their symbol resolver).
# Fallback to yfinance.search() is unreliable for obscure symbols.
```

### Fix #34 — Missing `CurrencyExposure` Frontend Component (LOW)
**File:** `frontend/src/components/`
The CHANGELOG describes a Currency Exposure horizontal bar chart. Create the stub:
```tsx
// frontend/src/components/CurrencyExposure.tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

interface Props {
  exposures: { currency: string; value_cad: number; pct: number }[];
}

export function CurrencyExposure({ exposures }: Props) {
  if (!exposures?.length) return null;
  return (
    <div className="card">
      <h3 className="card-title">Currency Exposure</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart layout="vertical" data={exposures}>
          <XAxis type="number" tickFormatter={(v) => `${v.toFixed(0)}%`} />
          <YAxis type="category" dataKey="currency" width={40} />
          <Tooltip formatter={(v: number) => `${v.toFixed(1)}%`} />
          <Bar dataKey="pct" fill="var(--color-accent)" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```
Wire it into `Dashboard.tsx` once the backend exposure endpoint is confirmed working.

### Fixes #35, #36, #37, #38 (Informational)
- **#35** — Document in `backend/fx/rates.py` that HKD, SEK, NOK use static fallback
  only. Add a comment: `# BoC Valet does not publish these series — static 2024 rate used`
- **#36** — After Fix #8, the `backend.spec` issue is resolved. Add to build docs.
- **#37** — Add a `/api/transactions?action=OTHER` endpoint or UI note in a future pass.
- **#38** — Add UTF-8 charset headers to all FastAPI responses:
  ```python
  from fastapi.responses import JSONResponse
  # In lifespan/middleware:
  @app.middleware("http")
  async def add_charset(request, call_next):
      response = await call_next(request)
      response.headers["Content-Type"] = "application/json; charset=utf-8"
      return response
  ```
  Delete `scripts/_audit_db.py` (the read-only audit helper).

---

## PHASE 5 — Cleanup Pass

After all fixes above are complete and tests are green:

### 5.1 Delete the audit helper
```bash
rm scripts/_audit_db.py
git add -A && git commit -m "chore: remove audit helper script"
```

### 5.2 Remove the screenshot from repo root
```bash
git rm "Screenshot 2026-05-20 210633.png"
git commit -m "chore: remove screenshot from repo root"
```

### 5.3 Clean build log files
These should now be in `.gitignore` (Fix #31). Verify they are untracked:
```bash
git status | grep build-output
```

### 5.4 Simplify `assets/README.md`
If `assets/` contains only placeholder files, either delete `assets/README.md` or
populate `assets/` with the real icon files from Fix #27.

---

## PHASE 6 — README Rewrite

Rewrite `README.md` from scratch using the following structure. The tone should be
professional, clear, and portfolio-ready — a hiring manager should immediately
understand what this app does and what the builder knows.

```markdown
# Portfolio Dashboard

> A local-first investment portfolio tracker for Canadian investors.
> Import from Questrade, Wealthsimple, RBC, CIBC, TD, BMO, Scotia, Interactive Brokers, 
> and more. Tracks ACB, capital gains, TFSA room, and portfolio performance — 
> with everything stored on your machine.

![Screenshot](assets/screenshot.png)

## Features

- **11 broker parsers** — CSV, XLSX, PDF auto-detected from file content
- **CRA-compliant ACB engine** — per-security, per-account, with superficial loss detection
- **Multi-currency** — CAD, USD, GBP, EUR, JPY, AUD, CHF, HKD, SEK, NOK (FX at trade date)
- **Multi-profile** — manage your own portfolio and others from a single app
- **Capital gains reports** — taxable vs. non-taxable, by year, TFSA-aware
- **CRA Tax Report PDF** — Schedule 3 format, ready to review
- **Annual Portfolio Report PDF** — year-in-review with charts
- **Rebalancing Advisor** — buy/sell instructions with account separation
- **What-If Simulator** — model buys, sells, and lump-sum scenarios with tax estimates
- **TFSA Room Calculator** — contribution room by year, withdrawal credits tracked
- **Performance charts** — S&P 500 benchmark overlay, ACB reference line
- **Dark / light mode** — CSS-variable theme, preference persisted
- **Local-first** — SQLite per profile; no data leaves your machine

## Installation (Windows)

1. Download `Portfolio Dashboard Setup X.X.X.exe` from [Releases](https://github.com/YOUR_USERNAME/portfolio-dashboard/releases)
2. Run the installer and follow the prompts
3. Launch from Start Menu or the desktop shortcut

## Developer Setup

**Requirements:** Python 3.11+, Node 18+, npm

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 7842

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev

# 3. Electron shell (new terminal)
cd electron
npm install
npm run dev
```

## Running Tests

```bash
cd backend
python -m pytest ../tests/ -v
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11, FastAPI, SQLAlchemy, SQLite |
| Data | pandas, openpyxl, pdfplumber, yfinance |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Recharts |
| Desktop | Electron 30, PyInstaller |
| Packaging | electron-builder (NSIS for Windows) |

## Privacy

All data is stored locally in `%APPDATA%\Portfolio Dashboard\`. Nothing is sent to
any server. Market prices are fetched from Yahoo Finance (yfinance) on demand.

## License

MIT
```

---

## PHASE 7 — Final Build & Release

Only run this phase after every fix above is verified and all tests pass.

### 7.1 Run the full test suite
```bash
cd backend
python -m pytest ../tests/ -v 2>&1 | tee ../test-results-preflight.txt
```
All tests must pass. Zero failures. Zero errors.

### 7.2 TypeScript check
```bash
cd frontend && npx tsc --noEmit
```
Zero errors required.

### 7.3 Frontend build
```bash
cd frontend && npm run build
```
Zero errors required.

### 7.4 Bump version to 0.5.0
```bash
# Set the version consistently (see Fix #30)
cd frontend && npm version 0.5.0 --no-git-tag-version && cd ..
cd electron && npm version 0.5.0 --no-git-tag-version && cd ..
# Update backend/main.py version string manually
```

### 7.5 Add CHANGELOG entry
Add a `[0.5.0]` section at the top of `CHANGELOG.md` listing:
- All 6 critical fixes
- All 4 high fixes
- Summary of medium/low fixes
- "0 test regressions — 111+ tests passing"

### 7.6 Build
```bash
cd scripts
powershell -File build-windows.ps1
```

### 7.7 Verify installer
- Size should be 195–210 MB (similar to 0.4.2)
- Install and launch — confirm backend starts, health endpoint responds
- Re-import example Questrade file — confirm dedup (0 new, 46 skipped)
- Check `%APPDATA%\Portfolio Dashboard\backend.log` — zero exceptions on cold start
- Quit the app — confirm `.db-wal` file is small (< 50 KB) after clean shutdown

### 7.8 Commit and tag
```bash
git add -A
git commit -m "v0.5.0 - critical bug fixes: FX population, rebalancer math, lifetime returns"
git tag v0.5.0
git push origin main --tags
```

Create a GitHub release using the CHANGELOG entry as the release notes.

---

## Verification Checklist — Run After Every Phase

```bash
# Full test suite
python -m pytest ../tests/ -v --tb=short | tail -5

# TypeScript
cd frontend && npx tsc --noEmit && echo "TS: PASS"

# Registry integrity
python -c "from backend.parsers.registry import BROKER_PARSERS; assert len(BROKER_PARSERS)==12; print('Registry: PASS')"

# FX populated
python -c "
import sqlite3
conn = sqlite3.connect('data/profiles/084047b7/portfolio.db')
nulls = conn.execute(\"SELECT COUNT(*) FROM transactions WHERE local_currency!='CAD' AND fx_rate_to_cad IS NULL\").fetchone()[0]
print(f'FX nulls: {nulls} (expected 0)')
assert nulls == 0, 'FX bug not fixed'
conn.close()
"

# Lifetime return not zero
curl -s 'http://localhost:7842/api/portfolio?period=all' | python -c "
import sys,json; d=json.load(sys.stdin)
assert d['period_return_pct'] != 0.0, 'Lifetime return still 0'
print(f'Lifetime return: {d[\"period_return_pct\"]}% PASS')
"

# Rebalancer budget
curl -s -X POST http://localhost:7842/api/rebalance \
  -H "Content-Type: application/json" \
  -d '{"mode":"new_money","new_money_cad":5000,"targets":{"VFV.TO":0.5,"XEF.TO":0.5}}' | python -c "
import sys,json; d=json.load(sys.stdin)
cost=sum(a['cost_cad'] for a in d['actions'] if a['action']=='BUY')
assert cost<=5001, f'Budget exceeded: {cost}'
print(f'Rebalancer cost: \${cost:.2f} PASS')
"
```

---

## Terminal Prompt — Paste This Into Claude Code

```
Read markdown-instructions/DEBUG-FIX-PLAN.md in full before doing anything.

Your goal is to fix every bug catalogued in markdown-instructions/ERROR-LOG.md, working
through the phases in DEBUG-FIX-PLAN.md in order. Do not skip phases. Do not build
until Phase 7 explicitly says to.

After each individual fix, run the verification command listed for that fix before
moving to the next one. If a verification fails, debug and fix it before continuing.

Run the full pytest suite after completing each Phase (not each individual fix).
All tests must stay green throughout. If you break a test, fix it before proceeding.

Key constraints:
- Do NOT run electron-builder or npm run build until Phase 7
- Do NOT commit until Phase 5 (cleanup) or later
- Do NOT modify test-transaction-reports/ fixture files
- The data/ directory contains a real user database — do not DELETE or DROP any rows
- Phase 6 (README rewrite) is prose work — write it carefully, not as a skeleton

Start by confirming the pytest baseline, then begin Phase 1, Fix #1.
```
