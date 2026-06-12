# Investment Transaction App — Claude Code Instructions
## Multi-Broker Support, Multi-Currency, Full Test Suite

> **How to use this file:** Drop it in the root of your project repo, then run
> `claude` in that directory. Claude Code will read this file automatically and
> follow all instructions below. It should implement, debug, and test freely as
> it goes — no human confirmation required for standard fixes.

---

## 0. Context & Ground Rules

You are extending an investment portfolio tracker that **already** parses
Wealthsimple and Questrade transaction exports correctly. **Do not break those
pipelines.** Every change must keep existing Wealthsimple + Questrade unit tests
green.

The goals for this session:

1. Parse **14 new broker formats** (CSV, XLSX, PDF) placed in `test_data/`.
2. Add **multi-currency support** (CAD, USD, GBP, EUR, JPY, AUD, CHF, HKD, SEK,
   NOK) with live and static FX rate handling.
3. Create **profile-based test suites** that exercise every broker across every
   feature.
4. Auto-debug any failures you find — fix them without asking.

---

## 0.5 Reference Repository Study — **Do This Before Writing Any New Code**

This app was originally built by studying the repositories below. Before
implementing any of the new parsers, FX logic, or UI features in this document,
**re-visit each repo** and extract patterns that apply to the new work. Notes
describe exactly what to look for. Don't skip this — these repos contain
battle-tested logic that prevents you from reinventing solved problems.

---

### Tier 1 — Study in Full (highest relevance to the new work)

#### 1. `tsiemens/acb` — https://github.com/tsiemens/acb

**Why it matters for this session:** Contains a working multi-currency pipeline
specifically built for Canadian brokers. The Bank of Canada exchange rate lookup
it implements is exactly what `FXService` needs for historical transaction
conversion (not today's rate — the rate on the day of the trade).

What to extract:
- `py/tx-export-convert`: Questrade XLSX parsing patterns already working in
  production — compare against the existing `parser.py` to confirm no regressions
  were introduced when Wealthsimple support was added.
- The Bank of Canada historical FX rate API call: adapt this directly into
  `FXService.rate_to_cad()` as the live-data source, replacing the static table
  when `FX_LIVE_RATES=true`. The BoC supports any date since 2017 and covers
  CAD/USD, CAD/EUR, CAD/GBP, CAD/JPY, CAD/AUD, CAD/CHF — exactly the currencies
  in the new test data.
- The ACB calculation loop: verify the existing `acb.py` follows the same
  order-of-operations. If there's any divergence, fix `acb.py` to match (the
  tsiemens implementation is CRA-validated).
- The superficial loss detection window (30-day lookback/lookahead): confirm the
  existing implementation handles this correctly for the new brokers' sell
  transactions.

#### 2. `wealthfolio/wealthfolio` — https://github.com/afadil/wealthfolio

**Why it matters for this session:** This app's `ActivityImport` feature is the
closest existing implementation of the multi-broker, multi-format import pipeline
we're building. It already handles deduplication across imports from different
brokers and is the architectural model for the parser registry.

What to extract:
- `apps/frontend/src/features/activity/`: how the import flow handles detection,
  preview, confirmation, and error states for different file formats — model the
  Upload UI changes in §6.1 on this.
- The `ActivityImport` deduplication strategy: compare to our hash-based dedup
  in `store.py` and adopt any improvements (wealthfolio uses a similar
  `sha256` approach but with additional tie-breaking fields).
- `apps/frontend/src/features/holdings/`: the HoldingCard component layout and
  the currency badge implementation — adapt the badge design for the new
  multi-currency transaction rows.
- The currency selector/converter component in the portfolio summary — this is
  exactly the "View in:" selector described in §3.3.
- The `market-data` crate: price caching strategy (in-memory + persistent) maps
  directly onto the two-tier cache in `market_data.py`.

#### 3. `dwrpayne/portfolio` — https://github.com/dwrpayne/portfolio

**Why it matters for this session:** Canadian-specific Django app that correctly
maintains the CAD value of every transaction **at the date of the transaction**
— the CRA-correct approach for multi-currency capital gains when a stock is
purchased at one exchange rate and sold at another.

What to extract:
- The currency-date logic: **do not use today's FX rate for historical
  transactions**. Each transaction must store the FX rate at the time of the
  trade. This is critical for GBP, EUR, JPY, and AUD transactions in the new
  test files — the HSBC, Scotia, and IB files all contain non-CAD/USD trades.
- The price sync scheduling approach: how it batches yfinance calls to avoid
  rate limiting when resolving many new tickers at once — the IB file adds 50
  transactions with potentially 20+ unique tickers.
- The ACB ledger model: cross-reference with the existing `acb.py` to ensure
  the per-security-per-account separation is maintained correctly for the new
  brokers.

---

### Tier 2 — Extract Specific Patterns

#### 4. Bloomberg-Inspired Dark Dashboard — GitHub search: `bloomberg-terminal stock-dashboard react recharts vite dark-theme finance-management`

**Why it matters:** The color palette and CSS variable system from this repo is
the foundation of the existing dark theme. Before adding the Currency Exposure
panel (§3.4) and the new currency filter UI (§6.4), re-examine how the CSS
variables are structured in this repo to ensure new components stay visually
consistent.

What to extract:
- The heatmap cell color interpolation logic (red → white → green) used in
  the Correlation Matrix — adapt it for the Currency Exposure bar chart.
- The dark card `box-shadow` and `border` values — match these for the new
  currency exposure widget card.

#### 5. `ghostfolio/ghostfolio` — https://github.com/ghostfolio/ghostfolio

**Why it matters:** Ghostfolio is the most mature open-source multi-currency
wealth tracker. Its data models handle stocks, ETFs, and bonds from any exchange
in any currency — directly relevant to the international broker files (HSBC,
Interactive Brokers, Fidelity).

What to extract:
- The portfolio performance API response shape for multi-currency portfolios:
  how it presents per-currency breakdowns alongside CAD totals — model the
  `GET /api/portfolio` response extension for the currency exposure panel on
  this.
- How it handles tickers from LSE (GBP), Euronext (EUR), TSE (JPY), and ASX
  (AUD) uniformly through a single resolution interface — adapt for
  `market_data.py`'s dynamic ticker resolver when handling the new international
  tickers from HSBC and IB files.
- The `PortfolioCalculator` implementation for ROAI across multiple time
  windows — useful if adding a time-weighted return display alongside Sharpe.

#### 6. Next.js SQLite Portfolio Dashboard — GitHub search: `portfolio-tracker nextjs sqlite fifo sharpe anthropic-claude ibkr polygon`

**Why it matters:** Built specifically for Interactive Brokers (ibkr in the
search), this repo handles IB's dense signed-quantity CSV format — the same
format as `InteractiveBrokers_2024.csv` in the new test data.

What to extract:
- The IB CSV parser: how it filters `DataDiscriminator == "Trade"` rows,
  normalizes signed quantities (negative = buy), and handles the 6-line
  statement header block. Port this logic directly into `InteractiveBrokersParser`.
- The idempotent SQLite import strategy: the `INSERT OR IGNORE` + hash approach
  is already in `store.py` but this repo has a cleaner implementation of the
  import result reporting UI.
- The Sharpe ratio calculation from weekly returns: verify the existing
  `portfolio.py` Sharpe implementation matches this repo's approach. The IB
  test profile (Profile 2) will exercise Sharpe with a much larger transaction
  set.

#### 7. Python ACB Package — GitHub search: `adjusted-cost-basis python capital-gains portfolio-tracker investment-tracking`

**Why it matters:** Before reimplementing ACB from scratch for the new broker
formats, check whether this package can be imported and used as a dependency in
`acb.py`. The new brokers (RBC, CIBC, TD, BMO, Scotia) all produce Canadian
securities transactions that need CRA-compliant ACB tracking.

What to extract:
- Package API: can it accept a `list[Transaction]` and return per-security
  ACB? If yes, wrap it in `acb.py` rather than extending the custom engine.
- Check if it supports superficial loss detection for the new broker
  transaction formats (the Scotia file has several sell events near 30-day
  windows).
- If the package is not suitable as a direct dependency, extract its
  `SharePool` or equivalent class for the multi-account ACB separation logic.

---

### Tier 3 — Reference for Specific Features

#### 8. Australian Bank Statement Import Tracker — GitHub search: `portfolio-tracker bank-statement-import australia react typescript wealth-tracking`

**Why it matters:** Directly analogous to our multi-broker import problem: this
repo merges transaction files from multiple Australian banks (ANZ, CBA, NAB,
Westpac) into a single portfolio — same deduplication-across-brokers challenge
as merging RBC + TD + CIBC + Scotia into one portfolio (Profile 3 in §4).

What to extract:
- The transaction deduplication strategy across different brokers: how it
  handles cases where two files contain the same trade (e.g. same dividend
  appearing in both a monthly PDF and an annual CSV).
- The import result reporting UI: "X new, Y skipped (already imported), Z
  conflicts" — adapt for the ImportResult toast to distinguish per-broker counts.

#### 9. Streamlit + yfinance Quant Dashboard — GitHub search: `portfolio-manager streamlit yfinance plotly onebuffalolabs`

**Why it matters:** Contains a tested pandas pipeline for tickers with different
history lengths — directly relevant when computing correlation matrices and
Sharpe ratios across the new international tickers (GBP, EUR, JPY, AUD
securities have shorter yfinance history than TSX/NYSE tickers).

What to extract:
- How it handles mismatched history lengths in the weekly returns correlation
  calculation — use the overlapping date range approach when the new HSBC/IB
  tickers have shorter or more recent price history.
- The volatility calculation from yfinance data when some periods have `NaN`
  closes — the `7203.T` (Toyota, JPY) ticker is a known edge case.

#### 10. FastAPI + React Full-Stack Template — https://github.com/fastapi/full-stack-fastapi-template

**Why it matters:** The official FastAPI template. The existing `main.py` was
modelled on this. Before adding the new multi-format upload endpoint, re-check
the file upload pattern in this template.

What to extract:
- The multipart file upload endpoint pattern: the existing `POST /api/import`
  only accepted `.xlsx`; it now needs to accept `.csv`, `.tsv`, `.pdf`, and
  `.xlsx` — update the endpoint's `UploadFile` validation and MIME type
  checking using the template's pattern.
- The CORS config: `app://` origin for Electron production must still be in
  the allowed origins list after the endpoint changes.

---

### How the Repos Map to This Session's Work

| Repo | Applies To |
|------|-----------|
| `tsiemens/acb` | `FXService` historical rates, `acb.py` regression check, BoC API |
| `wealthfolio/wealthfolio` | Parser registry pattern, Upload UI, dedup, currency badge, "View in:" selector |
| `dwrpayne/portfolio` | FX rate at transaction date (not today), price sync batching |
| Bloomberg dashboard | CSS variables for Currency Exposure widget, bar chart colors |
| `ghostfolio/ghostfolio` | Multi-currency portfolio API shape, international ticker resolution |
| Next.js SQLite / IB | `InteractiveBrokersParser` signed-qty handling, IB CSV header skipping |
| Python ACB package | Possibly replace custom ACB engine; superficial loss for new brokers |
| Australian import tracker | Multi-broker dedup, per-broker import result counts in UI |
| Streamlit/yfinance | Correlation matrix with mismatched history lengths, JPY edge cases |
| FastAPI template | Updated file upload endpoint for multi-format accept |

---

## 1. Test Data Files

All test files live in `test_data/` relative to the project root:

```
test_data/
├── csv/
│   ├── RBC_DirectInvesting_2024.csv          # Pipe-delim, 4-line header block, 42 rows
│   ├── CIBC_InvestorsEdge_2024.csv           # Standard comma CSV, 4-line header, 38 rows
│   ├── TD_DirectInvesting_2024.csv           # Tab-separated (TSV), no header block, 45 rows
│   ├── BMO_InvestorLine_2024.csv             # Quoted CSV, columns in different order, 36 rows
│   ├── Scotia_iTRADE_2024.csv                # Semicolon-delimited, DD/MM/YYYY dates, 40 rows
│   ├── InteractiveBrokers_2024.csv           # IB dense format, statement header rows, 50 rows
│   ├── NationalBank_DirectBrokerage_2024.csv # Bilingual FR/EN headers, 35 rows
│   └── Fidelity_2024.csv                     # US broker, zero-commission, MM/DD/YYYY, 40 rows
├── xlsx/
│   ├── BMO_InvestorLine_2024.xlsx            # Styled, merged title rows, pivot sheet, 38 rows
│   ├── Scotia_iTRADE_2024.xlsx               # Multi-sheet (trade history + account summary)
│   └── HSBC_InvestDirect_2024.xlsx           # International-heavy, GBP/EUR/JPY/AUD, 33 rows
└── pdf/
    ├── RBC_DirectInvesting_2024.pdf          # Branded PDF, 40 rows, multi-currency
    ├── TD_DirectInvesting_2024.pdf           # A4 format, green theme, 35 rows
    └── CIBC_InvestorsEdge_2024.pdf           # Dense layout, red theme, 33 rows
```

### Key parsing challenges per file (fix these proactively):

| File | Challenge |
|------|-----------|
| RBC CSV | 4-line metadata header before column row; must skip to real header |
| CIBC CSV | 4-line header; column names differ from RBC |
| TD CSV | Tab-separated; no metadata header; extra `Order ID` column |
| BMO CSV | Fully quoted CSV; `Account Type` column is first (not last); column order inverted |
| Scotia CSV | Semicolon delimiter; `DD/MM/YYYY` date format; extra `Settlement Date` column |
| IB CSV | 6 statement-info rows before data; `Quantity` is signed (negative = buy); `DataDiscriminator` column must be filtered to only `"Trade"` rows — **port the IB CSV parser from the Next.js/IB repo (§0.5, Tier 2 repo 6) rather than writing from scratch** |
| National Bank CSV | Bilingual headers with ` / ` separator; must normalize to English keys |
| Fidelity CSV | 4-line header; `MM/DD/YYYY` dates; no FX columns (USD only); zero commission |
| BMO XLSX | Merged title cells in rows 1-3; real column header is at row 5; summary formula row at bottom |
| Scotia XLSX | Two sheets — read `Trade History` sheet only |
| HSBC XLSX | ISIN column present; `Settlement CCY` may differ from `Local Currency` |
| RBC PDF | ReportLab table; extract with pdfplumber; branded header to skip |
| TD PDF | A4 page size; table starts after `HRFlowable` line |
| CIBC PDF | Dense 13-column layout; small font — ensure no column merging during extraction |

---

## 2. Architecture Requirements

### 2.1 Parser Registry Pattern

Create (or extend) a broker parser registry so new formats can be added without
touching core logic:

```python
# app/parsers/registry.py
BROKER_PARSERS = {
    "wealthsimple":     WealthsimpleParser,    # already exists — DO NOT MODIFY
    "questrade":        QuestradeParser,        # already exists — DO NOT MODIFY
    "rbc":              RBCParser,
    "cibc":             CIBCParser,
    "td":               TDParser,
    "bmo":              BMOParser,
    "scotiabank":       ScotiabankParser,
    "interactive":      InteractiveBrokersParser,
    "nationalbank":     NationalBankParser,
    "fidelity":         FidelityParser,
    "hsbc":             HSBCParser,
    "generic":          GenericParser,          # fallback heuristic parser
}
```

Each parser must implement this interface:

```python
class BaseParser:
    BROKER_NAME: str                # e.g. "RBC Direct Investing"
    SUPPORTED_FORMATS: list[str]    # e.g. ["csv", "xlsx"]

    @classmethod
    def detect(cls, file_path: str, content_sample: str) -> float:
        """Return confidence 0.0–1.0 that this parser handles the file."""
        ...

    def parse(self, file_path: str) -> list[Transaction]:
        """Return normalized Transaction objects."""
        ...
```

### 2.2 Auto-Detection Pipeline

When a user uploads a file, the app must:

1. Read the first 1 KB of the file (text) or first sheet row (XLSX).
2. Run all registered `detect()` methods.
3. Pick the parser with the highest confidence score (≥ 0.5).
4. If no parser scores ≥ 0.5, fall back to `GenericParser`.
5. Log the detected broker name + confidence to the console/debug panel.

Detection signals to implement in each parser's `detect()`:

- RBC: look for `"RBC Direct Investing"` in first 10 lines.
- CIBC: look for `"CIBC Investor"` in first 10 lines.
- TD: look for tab-delimited header with `"Company Name"` column.
- BMO: look for `"BMO InvestorLine"` in first 5 lines or quoted-CSV `"Trans. Date"`.
- Scotia: semicolon delimiter + `"iTRADE"` or `"Order Type"` column.
- IB: `"Statement,Header"` or `"BrokerName,Interactive Brokers"` row.
- National Bank: `"Banque Nationale"` or `" / "` in column headers.
- Fidelity: `"Fidelity Investments"` or `"Run Date"` + `"Amount ($)"` columns.
- HSBC: `"HSBC"` or `"InvestDirect"` in first lines; or `"ISIN"` column.

### 2.3 Transaction Data Model

Extend the existing `Transaction` model (or create it) to support multi-currency:

```python
@dataclass
class Transaction:
    # Core fields (all brokers)
    broker:          str
    date:            date
    action:          str            # "buy" | "sell" | "dividend" | "transfer" | "fee"
    ticker:          str
    name:            str
    quantity:        Decimal
    price:           Decimal
    local_currency:  str            # ISO 4217 — the currency of the trade
    gross_amount:    Decimal        # in local_currency
    commission:      Decimal        # in local_currency
    net_amount:      Decimal        # in local_currency

    # FX fields (populate if available; compute if not)
    fx_rate_to_cad:  Decimal | None  # 1 local_currency = ? CAD
    net_cad:         Decimal | None  # net_amount * fx_rate_to_cad

    # Optional / broker-specific
    account_type:    str | None     # RRSP, TFSA, Non-Reg, IRA, etc.
    reference_id:    str | None     # order/confirmation number
    settlement_date: date | None
    isin:            str | None
    exchange:        str | None     # TSX, NYSE, LSE, EURONEXT, etc.

    # Metadata
    source_file:     str
    source_broker:   str
    parsed_at:       datetime
    raw_row:         dict           # original row for debugging
```

---

## 3. Multi-Currency Implementation

### 3.1 Supported Currencies

Implement support for at minimum these currencies. The test data contains all of them:

| ISO | Name | Symbol | Decimals |
|-----|------|--------|----------|
| CAD | Canadian Dollar | $ | 2 |
| USD | US Dollar | $ | 2 |
| GBP | British Pound | £ | 2 |
| EUR | Euro | € | 2 |
| JPY | Japanese Yen | ¥ | 0 |
| AUD | Australian Dollar | A$ | 2 |
| CHF | Swiss Franc | Fr | 2 |
| HKD | Hong Kong Dollar | HK$ | 2 |
| SEK | Swedish Krona | kr | 2 |
| NOK | Norwegian Krone | kr | 2 |

### 3.2 FX Rate Service

Create `app/fx/rates.py`:

```python
class FXService:
    """
    Multi-source FX rate provider.
    Priority:
      1. Rates embedded in the transaction file (most accurate for historical)
      2. Bank of Canada historical API — see tsiemens/acb for the exact call
         pattern: https://www.bankofcanada.ca/valet/observations/<series>/json
         Series IDs: FXUSDCAD, FXGBPCAD, FXEURCAD, FXJPYCAD, FXAUDCAD, FXCHFCAD
         Returns daily rates back to 2017 — use the rate for the transaction date.
         Only active when FX_LIVE_RATES=true env var is set.
      3. Static fallback table (hardcoded approximate rates for offline/testing)

    CRITICAL: Always use the rate at the DATE OF THE TRANSACTION, not today's
    rate. dwrpayne/portfolio and tsiemens/acb both enforce this — it is the
    CRA-correct approach for capital gains reporting on multi-currency trades.
    """

    STATIC_RATES_TO_CAD = {
        "CAD": Decimal("1.00"),
        "USD": Decimal("1.36"),
        "GBP": Decimal("1.72"),
        "EUR": Decimal("1.48"),
        "JPY": Decimal("0.0091"),
        "AUD": Decimal("0.89"),
        "CHF": Decimal("1.50"),
        "HKD": Decimal("0.174"),
        "SEK": Decimal("0.126"),
        "NOK": Decimal("0.126"),
    }

    def rate_to_cad(self, currency: str, trade_date: date) -> Decimal:
        """Return FX rate for currency -> CAD on trade_date."""
        # 1. Check in-file rate cache first
        # 2. Try live API if FX_LIVE_RATES env var is set
        # 3. Fall back to STATIC_RATES_TO_CAD
        ...

    def convert_to_cad(self, amount: Decimal, currency: str, trade_date: date) -> Decimal:
        return (amount * self.rate_to_cad(currency, trade_date)).quantize(Decimal("0.01"))
```

### 3.3 Currency Display in UI

- Always display the **original local currency** amount alongside CAD equivalent.
- Format JPY with 0 decimal places; all others with 2.
- Show currency flag or ISO code badge next to each transaction.
- Add a **currency filter** to the portfolio view (checkboxes: CAD ✓ USD ✓ GBP …).
- In portfolio summary totals, convert everything to CAD.
- Add a **"View in:"** currency selector in the dashboard (CAD / USD / GBP / EUR).
  When selected, convert all CAD totals to the chosen currency at current rate.

### 3.4 Portfolio-Level Currency Report

Add a new "Currency Exposure" panel to the dashboard:

```
Currency Exposure (% of portfolio at CAD value)
────────────────────────────────────────────────
CAD  ████████████████████  52.3%   $124,500
USD  ██████████████        38.1%   $ 90,800
GBP  ███                    5.2%   $ 12,400
EUR  ██                     3.1%   $  7,390
JPY  █                      1.3%   $  3,100
```

---

## 4. Test Profiles

Create test profiles in `tests/profiles/`. Each profile represents one "user"
with a distinct set of uploaded files. Run all profiles as part of `pytest`.

### Profile 1 — Canadian Retail Investor (CSV + XLSX)
```yaml
# tests/profiles/canadian_retail.yaml
name: "Sarah Chen — Canadian Retail"
files:
  - test_data/csv/RBC_DirectInvesting_2024.csv
  - test_data/csv/TD_DirectInvesting_2024.csv
  - test_data/xlsx/BMO_InvestorLine_2024.xlsx
expected:
  total_transactions: 125   # 42 + 45 + 38
  currencies: [CAD, USD, GBP, EUR, JPY, AUD]
  brokers: [RBC, TD, BMO]
  account_types: [RRSP, TFSA, Non-Registered, Margin, RESP, RRIF]
```

### Profile 2 — Active Trader (IB + Questrade)
```yaml
name: "Marcus Webb — Active Trader"
files:
  - test_data/csv/InteractiveBrokers_2024.csv
  - test_data/csv/Questrade_2024.csv      # existing test file
expected:
  total_transactions: 110+
  currencies: [CAD, USD, GBP, EUR, JPY, AUD]
  brokers: [Interactive Brokers, Questrade]
  has_negative_quantities: true           # IB uses signed qty
```

### Profile 3 — Multi-Bank Consolidation
```yaml
name: "Priya Sharma — Multi-Bank"
files:
  - test_data/csv/CIBC_InvestorsEdge_2024.csv
  - test_data/csv/BMO_InvestorLine_2024.csv
  - test_data/csv/Scotia_iTRADE_2024.csv
  - test_data/csv/NationalBank_DirectBrokerage_2024.csv
expected:
  total_transactions: 149   # 38 + 36 + 40 + 35
  currencies: [CAD, USD, GBP, EUR, JPY, AUD]
  brokers: [CIBC, BMO, Scotiabank, National Bank]
  date_formats_mixed: true    # DD/MM/YYYY from Scotia mixed with YYYY-MM-DD others
```

### Profile 4 — International Investor (PDF + XLSX)
```yaml
name: "James O'Brien — International"
files:
  - test_data/pdf/RBC_DirectInvesting_2024.pdf
  - test_data/pdf/TD_DirectInvesting_2024.pdf
  - test_data/xlsx/HSBC_InvestDirect_2024.xlsx
expected:
  total_transactions: 108   # 40 + 35 + 33
  currencies: [CAD, USD, GBP, EUR, JPY, AUD]
  brokers: [RBC, TD, HSBC]
  has_isin: true              # HSBC file includes ISIN column
```

### Profile 5 — US Investor
```yaml
name: "Alex Rivera — US Investor"
files:
  - test_data/csv/Fidelity_2024.csv
  - test_data/csv/InteractiveBrokers_2024.csv
expected:
  total_transactions: 90    # 40 + 50
  currencies: [USD, CAD, GBP, EUR, JPY, AUD]
  brokers: [Fidelity, Interactive Brokers]
  zero_commission_transactions: 40   # all Fidelity rows
  account_types_us: [Individual, "Roth IRA", "Traditional IRA"]
```

### Profile 6 — Wealthsimple + Questrade (REGRESSION — must not break)
```yaml
name: "Regression — Existing Pipelines"
files:
  - test_data/csv/Wealthsimple_2024.csv   # existing
  - test_data/csv/Questrade_2024.csv      # existing
expected:
  all_existing_assertions_pass: true
  no_regressions: true
```

---

## 5. Test Cases to Implement

### 5.1 Parser Unit Tests  (`tests/test_parsers/`)

For **each** broker parser, write tests covering:

```python
# tests/test_parsers/test_rbc_parser.py  (repeat pattern for all brokers)

def test_rbc_detects_correctly():
    score = RBCParser.detect("test_data/csv/RBC_DirectInvesting_2024.csv", ...)
    assert score >= 0.9

def test_rbc_parse_row_count():
    txs = RBCParser().parse("test_data/csv/RBC_DirectInvesting_2024.csv")
    assert len(txs) == 42

def test_rbc_no_missing_dates():
    txs = RBCParser().parse(...)
    assert all(t.date is not None for t in txs)

def test_rbc_valid_actions():
    txs = RBCParser().parse(...)
    assert all(t.action in ("buy","sell","dividend","transfer","fee") for t in txs)

def test_rbc_currencies_valid():
    txs = RBCParser().parse(...)
    valid = {"CAD","USD","GBP","EUR","JPY","AUD","CHF","HKD","SEK","NOK"}
    assert all(t.local_currency in valid for t in txs)

def test_rbc_cad_equivalent_populated():
    txs = RBCParser().parse(...)
    assert all(t.net_cad is not None for t in txs)

def test_rbc_no_negative_amounts_for_buys():
    txs = RBCParser().parse(...)
    buys = [t for t in txs if t.action == "buy"]
    assert all(t.net_amount > 0 for t in buys)
```

### 5.2 Auto-Detection Tests  (`tests/test_detection.py`)

```python
@pytest.mark.parametrize("file,expected_broker", [
    ("test_data/csv/RBC_DirectInvesting_2024.csv",     "rbc"),
    ("test_data/csv/CIBC_InvestorsEdge_2024.csv",      "cibc"),
    ("test_data/csv/TD_DirectInvesting_2024.csv",      "td"),
    ("test_data/csv/BMO_InvestorLine_2024.csv",        "bmo"),
    ("test_data/csv/Scotia_iTRADE_2024.csv",           "scotiabank"),
    ("test_data/csv/InteractiveBrokers_2024.csv",      "interactive"),
    ("test_data/csv/NationalBank_DirectBrokerage_2024.csv", "nationalbank"),
    ("test_data/csv/Fidelity_2024.csv",                "fidelity"),
    ("test_data/xlsx/BMO_InvestorLine_2024.xlsx",      "bmo"),
    ("test_data/xlsx/Scotia_iTRADE_2024.xlsx",         "scotiabank"),
    ("test_data/xlsx/HSBC_InvestDirect_2024.xlsx",     "hsbc"),
    ("test_data/pdf/RBC_DirectInvesting_2024.pdf",     "rbc"),
    ("test_data/pdf/TD_DirectInvesting_2024.pdf",      "td"),
    ("test_data/pdf/CIBC_InvestorsEdge_2024.pdf",      "cibc"),
    # Regression — must still detect correctly
    ("test_data/csv/Wealthsimple_2024.csv",            "wealthsimple"),
    ("test_data/csv/Questrade_2024.csv",               "questrade"),
])
def test_auto_detection(file, expected_broker):
    broker = detect_broker(file)
    assert broker == expected_broker
```

### 5.3 Multi-Currency Tests  (`tests/test_fx.py`)

```python
def test_fx_usd_to_cad():
    svc = FXService()
    rate = svc.rate_to_cad("USD", date(2024, 6, 1))
    assert Decimal("1.30") <= rate <= Decimal("1.42")

def test_fx_gbp_to_cad():
    rate = FXService().rate_to_cad("GBP", date(2024, 6, 1))
    assert rate > Decimal("1.60")

def test_fx_jpy_to_cad():
    rate = FXService().rate_to_cad("JPY", date(2024, 6, 1))
    assert rate < Decimal("0.02")   # JPY is small per unit

def test_cad_net_computed_when_missing():
    """If a file has no FX column, FXService should fill it."""
    txs = FidelityParser().parse("test_data/csv/Fidelity_2024.csv")
    assert all(t.net_cad is not None for t in txs)
    assert all(t.net_cad > 0 for t in txs if t.action == "buy")

def test_in_file_fx_rate_takes_priority():
    """Rates from the file must be used if present, not the static table."""
    txs = RBCParser().parse("test_data/csv/RBC_DirectInvesting_2024.csv")
    usd_txs = [t for t in txs if t.local_currency == "USD"]
    for t in usd_txs:
        expected_cad = (t.net_amount * t.fx_rate_to_cad).quantize(Decimal("0.01"))
        assert t.net_cad == expected_cad

def test_currency_exposure_sums_to_100_pct():
    all_txs = load_all_test_transactions()
    exposure = compute_currency_exposure(all_txs)
    total = sum(exposure.values())
    assert abs(total - Decimal("100.00")) < Decimal("0.01")

def test_correlation_with_mismatched_history_lengths():
    """
    International tickers (7203.T, BHP.AX, SHEL.L) have different yfinance
    history lengths than TSX tickers. Use overlapping date range only.
    See Streamlit/yfinance repo (§0.5, Tier 3 repo 9) for the pandas approach.
    """
    txs = HSBCParser().parse("test_data/xlsx/HSBC_InvestDirect_2024.xlsx")
    tickers = list({t.ticker for t in txs if t.ticker})
    matrix = compute_correlation_matrix(tickers)
    assert matrix is not None
    assert all(-1.0 <= v <= 1.0 for row in matrix.values() for v in row.values())
```

### 5.4 Profile Integration Tests  (`tests/test_profiles.py`)

> **Note:** Model the per-broker import result counts in the toast notification
> on the Australian bank statement tracker (§0.5, Tier 3 repo 8). Model the
> deduplication logic for Profile 3 (Multi-Bank) on wealthfolio's
> `ActivityImport` dedup (§0.5, Tier 1 repo 2).

```python
@pytest.mark.parametrize("profile_file", glob("tests/profiles/*.yaml"))
def test_profile_loads_without_error(profile_file):
    profile = load_profile(profile_file)
    txs = load_transactions_for_profile(profile)
    assert txs is not None
    assert len(txs) > 0

def test_profile_canadian_retail_transaction_count():
    profile = load_profile("tests/profiles/canadian_retail.yaml")
    txs = load_transactions_for_profile(profile)
    assert len(txs) == profile["expected"]["total_transactions"]

def test_profile_no_duplicate_transactions():
    """Ensure deduplication when same file appears in multiple profiles."""
    txs = load_transactions_for_profile(load_profile("tests/profiles/canadian_retail.yaml"))
    ids = [(t.date, t.ticker, t.quantity, t.source_broker) for t in txs]
    assert len(ids) == len(set(ids))
```

### 5.5 Edge Case Tests  (`tests/test_edge_cases.py`)

```python
def test_ib_signed_quantity_normalized():
    """IB uses negative qty for buys — must be normalized to positive."""
    txs = InteractiveBrokersParser().parse("test_data/csv/InteractiveBrokers_2024.csv")
    assert all(t.quantity > 0 for t in txs)

def test_scotia_dd_mm_yyyy_dates_parsed():
    """Scotia uses DD/MM/YYYY — ensure no month/day swap."""
    txs = ScotiabankParser().parse("test_data/csv/Scotia_iTRADE_2024.csv")
    # All 2024 dates should have year 2024
    assert all(t.date.year == 2024 for t in txs)

def test_ib_data_discriminator_filter():
    """IB CSV has header rows — only 'Trade' rows should be parsed."""
    txs = InteractiveBrokersParser().parse("test_data/csv/InteractiveBrokers_2024.csv")
    assert len(txs) == 50

def test_national_bank_bilingual_headers_normalized():
    txs = NationalBankParser().parse("test_data/csv/NationalBank_DirectBrokerage_2024.csv")
    assert len(txs) == 35
    assert all(hasattr(t, 'ticker') for t in txs)

def test_bmo_xlsx_skips_title_rows():
    """BMO XLSX has merged title rows in rows 1-3; real header is row 5."""
    txs = BMOParser().parse("test_data/xlsx/BMO_InvestorLine_2024.xlsx")
    assert len(txs) == 38
    assert all(t.date.year == 2024 for t in txs)

def test_fidelity_zero_commission():
    txs = FidelityParser().parse("test_data/csv/Fidelity_2024.csv")
    assert all(t.commission == Decimal("0.00") for t in txs)

def test_pdf_extraction_row_count():
    """PDF parsers must extract the correct number of rows."""
    assert len(RBCParser().parse("test_data/pdf/RBC_DirectInvesting_2024.pdf")) == 40
    assert len(TDParser().parse("test_data/pdf/TD_DirectInvesting_2024.pdf")) == 35
    assert len(CIBCParser().parse("test_data/pdf/CIBC_InvestorsEdge_2024.pdf")) == 33

def test_hsbc_isin_captured():
    txs = HSBCParser().parse("test_data/xlsx/HSBC_InvestDirect_2024.xlsx")
    isin_txs = [t for t in txs if t.isin]
    assert len(isin_txs) > 0

def test_wealthsimple_regression():
    """REGRESSION: Wealthsimple must parse exactly as before."""
    txs = WealthsimpleParser().parse("test_data/csv/Wealthsimple_2024.csv")
    assert len(txs) > 0
    assert all(t.local_currency in ("CAD", "USD") for t in txs)

def test_questrade_regression():
    """REGRESSION: Questrade must parse exactly as before."""
    txs = QuestradeParser().parse("test_data/csv/Questrade_2024.csv")
    assert len(txs) > 0
```

---

## 6. UI Features to Implement / Extend

### 6.1 Upload Flow Changes

- Accept `.csv`, `.tsv`, `.xlsx`, `.xls`, `.pdf` in the file upload widget.
- After upload, show: **"Detected: RBC Direct Investing (confidence: 94%)"**.
- If confidence < 50%, show a broker selector dropdown for the user to confirm.
- Show a **preview table** of the first 5 parsed rows before final import.

### 6.2 Transaction Table

Add these columns (hidden by default, toggleable):

- `Local Currency`
- `Local Amount`
- `FX Rate to CAD`
- `CAD Equivalent`
- `ISIN` (shown only when data available)
- `Account Type` (RRSP / TFSA / Non-Reg / IRA / etc.)
- `Settlement Date`

### 6.3 Portfolio Dashboard

- **Currency Exposure widget** (horizontal bar chart — see §3.4).
- **"Convert to" selector** — display all monetary values in chosen currency.
- Broker breakdown pie chart (add new brokers to the legend).
- Account type breakdown (RRSP vs TFSA vs Non-Reg vs Margin vs IRA).

### 6.4 Filters & Search

- Filter by: Broker, Account Type, Currency, Ticker, Action (buy/sell/dividend).
- Date range picker (default: current year).
- Search bar: searches Ticker + Security Name.

---

## 7. Implementation Order (follow this sequence)

```
Step 0  — Reference repo study (§0.5): clone/browse all 10 repos; extract patterns
           listed in the mapping table before writing a single line of code.
           Specifically:
             • Read tsiemens/acb py/tx-export-convert + BoC FX call → note patterns
             • Read wealthfolio ActivityImport feature → note dedup + registry shape
             • Read dwrpayne/portfolio currency-date logic → confirm FXService approach
             • Read Next.js/IB repo IB CSV parser → extract for InteractiveBrokersParser
             • Check Python ACB package API → decide: import as dep or custom engine?

Step 1  — Verify existing Wealthsimple + Questrade tests still pass (baseline)
Step 2  — Extend Transaction dataclass + BaseParser interface (§2.3, §2.1)
Step 3  — Implement FXService with static rates + BoC API stub (§3.2)
           Port tsiemens/acb BoC lookup pattern for the live-rate path.
Step 4  — Implement CSV parsers in this order:
           IB first (patterns from Next.js/IB repo) → RBC → CIBC → TD →
           BMO → Scotia → National Bank → Fidelity
Step 5  — Implement XLSX parsers (BMO → Scotia → HSBC)
Step 6  — Implement PDF parsers using pdfplumber (RBC → TD → CIBC)
Step 7  — Build auto-detection pipeline (§2.2)
Step 8  — Update POST /api/import to accept .csv, .tsv, .pdf, .xlsx
           (FastAPI template multipart pattern from §0.5 repo 10)
Step 9  — Write all unit tests (§5.1 – §5.5)
Step 10 — Create test profiles (§4)
Step 11 — Run full test suite; auto-fix all failures
Step 12 — Implement UI changes (§6)
           Model currency badge + "View in:" selector on wealthfolio patterns (§0.5 repo 2)
           Model Currency Exposure widget colors on Bloomberg dashboard (§0.5 repo 4)
Step 13 — Run regression tests to confirm Wealthsimple + Questrade still pass
Step 14 — Run `pytest -v` and confirm 0 failures
```

---

## 8. Debugging Guidelines (follow these when fixing failures)

### CSV parsing failures
- Check delimiter: try `,` → `\t` → `;` → `|`
- Check for BOM (`\ufeff`) at start of file — strip it.
- Check for metadata header rows: scan first 10 lines for non-data content before the real header.
- Check date format: try `YYYY-MM-DD` → `MM/DD/YYYY` → `DD/MM/YYYY` → `MMM DD YYYY`

### XLSX parsing failures
- Use `openpyxl` (not `pandas`) to inspect merged cells and actual header row positions.
- Row 1 ≠ header if the file has title blocks. Scan for the row where the first cell looks like a column name.
- Filter out `TOTAL` / `SUMMARY` rows at the bottom.
- Use `data_only=True` when reading formula-computed cells.

### PDF parsing failures
- Use `pdfplumber` for table extraction.
- If table extraction fails (empty list), try extracting raw text and parsing with regex.
- Watch for column merging when font size is small — use explicit `table_settings` with tighter x-tolerance.
- Skip non-data pages (cover pages, footers).

### FX failures
- If `fx_rate_to_cad` column is missing from a file, call `FXService.rate_to_cad()`.
- If `net_cad` is None after parsing, compute: `net_amount * fx_rate_to_cad`.
- Treat `local_currency == "CAD"` as fx_rate = 1.0 exactly.

### Detection failures
- Lower confidence threshold to 0.3 for ambiguous formats, but prefer specificity.
- Add content fingerprinting: hash first 500 bytes to detect known formats.

---

## 9. Dependency Requirements

Ensure these are in `requirements.txt` / `pyproject.toml`:

```
pdfplumber>=0.10.0        # PDF table extraction
openpyxl>=3.1.0           # XLSX read/write
pandas>=2.0.0             # DataFrame processing
python-dateutil>=2.8.0    # Flexible date parsing
babel>=2.14.0             # Currency formatting
pytest>=8.0.0             # Test runner
pytest-asyncio>=0.23.0    # Async test support (if applicable)
```

---

## 10. Completion Checklist

Before reporting done, verify:

- [ ] `pytest tests/ -v` passes with **0 failures, 0 errors**
- [ ] Wealthsimple regression test green
- [ ] Questrade regression test green
- [ ] All 14 new test files parse without exceptions
- [ ] All 6 test profiles load without errors
- [ ] Auto-detection correctly identifies all 14 new files
- [ ] `net_cad` is non-null for every parsed transaction
- [ ] UI shows currency badge on each transaction row
- [ ] Currency Exposure panel renders correctly
- [ ] No `print()` debug statements left in parser code
- [ ] Each parser has a docstring listing: broker name, supported formats, known quirks
