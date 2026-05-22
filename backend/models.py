"""Pydantic data models — the shared contract between backend and frontend.

The TypeScript file frontend/src/types.ts mirrors these field names exactly.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------- Brokers / action vocabulary ----------

Broker = Literal[
    "questrade",
    "wealthsimple",
    "rbc",
    "cibc",
    "td",
    "bmo",
    "scotiabank",
    "interactive",
    "nationalbank",
    "fidelity",
    "hsbc",
    "generic",
]

Action = Literal[
    "BUY",
    "SELL",
    "DIVIDEND",
    "DEPOSIT",
    "WITHDRAWAL",
    "CONTRIBUTION",
    "FEE",
    "SPLIT",
    "INTEREST",
    "TRANSFER",
    "OTHER",
]

AccountType = Literal[
    "TFSA",
    "Margin",
    "RRSP",
    "Crypto",
    "RESP",
    "RRIF",
    "Non-Registered",
    "IRA",
    "Roth IRA",
    "Traditional IRA",
    "Individual",
    "LIRA",
    "FHSA",
    "Other",
]

Currency = Literal[
    "CAD",
    "USD",
    "GBP",
    "EUR",
    "JPY",
    "AUD",
    "CHF",
    "HKD",
    "SEK",
    "NOK",
]


# ---------- Transaction ----------

class Transaction(BaseModel):
    """A single normalized transaction row. Identity is the SHA-256 `hash`."""

    hash: str
    broker: Broker
    transaction_date: date
    settlement_date: date | None = None
    action: Action
    raw_symbol: str | None = None
    resolved_ticker: str | None = None
    description: str = ""
    quantity: float = 0.0
    price: float = 0.0
    gross_amount: float = 0.0
    commission: float = 0.0
    net_amount: float = 0.0
    currency: Currency = "CAD"
    account_number: str
    account_type: AccountType
    # ---- v0.3.0 multi-currency fields ----
    fx_rate_to_cad: float | None = None  # 1 unit of `currency` = X CAD on `transaction_date`
    net_cad: float | None = None         # net_amount × fx_rate_to_cad (filled by FXService if absent)
    isin: str | None = None              # international security identifier (HSBC, some IB rows)
    exchange: str | None = None          # TSX, NYSE, LSE, EURONEXT, TSE, ASX, etc.
    reference_id: str | None = None      # broker confirmation / order number


# ---------- Ticker resolution ----------

class ResolvedTicker(BaseModel):
    raw_symbol: str
    resolved_ticker: str | None
    security_name: str | None = None
    exchange: str | None = None
    currency: Currency | None = None
    resolved_from: Literal["pattern", "yfinance_search", "manual", "fallback"] = "pattern"
    status: Literal["resolved", "unresolved"] = "resolved"


class UnresolvedTicker(BaseModel):
    raw_symbol: str
    description: str | None = None
    occurrences: int = 1


# ---------- Imports ----------

class ImportResult(BaseModel):
    inserted: int
    skipped_duplicates: int
    total_in_db: int
    new_tickers_resolved: list[str] = Field(default_factory=list)
    unresolved_tickers: list[str] = Field(default_factory=list)
    import_duration_ms: int = 0
    detected_broker: Broker | None = None
    detected_format: str | None = None  # "xlsx", "csv", "pdf"


class ImportInfo(BaseModel):
    filename: str | None
    timestamp: datetime | None
    transaction_count: int


class ImportStatus(BaseModel):
    has_data: bool
    last_import: ImportInfo | None = None


# ---------- ACB / Capital gains ----------

class RealizedGain(BaseModel):
    """A single sell event with the gain it produced.

    `total_gain` is in the security's native currency. `total_gain_cad` is the
    CAD-equivalent at the transaction date FX rate — use the CAD field for any
    aggregation across the report.
    """

    transaction_date: date
    ticker: str
    security_name: str | None = None
    account_type: AccountType
    shares_sold: float
    sale_price: float
    acb_per_share: float
    gain_per_share: float
    total_gain: float
    total_gain_cad: float | None = None
    fx_rate_to_cad: float | None = None
    commission: float = 0.0
    currency: Currency = "CAD"
    taxable: bool = True
    superficial_loss_adjustment: float = 0.0
    notes: str | None = None


class SuperficialLossAdjustment(BaseModel):
    transaction_date: date
    ticker: str
    denied_loss: float
    repurchase_date: date | None = None
    note: str = ""


class AcbHolding(BaseModel):
    """ACB state for a single (ticker, account_type) pair."""

    ticker: str
    security_name: str | None = None
    account_type: AccountType
    currency: Currency = "CAD"

    total_shares: float = 0.0
    acb_per_share: float = 0.0
    total_cost: float = 0.0
    total_commission: float = 0.0
    dividends_received: float = 0.0

    realized_gains: list[RealizedGain] = Field(default_factory=list)
    total_realized_gain: float = 0.0
    superficial_loss_adjustments: list[SuperficialLossAdjustment] = Field(default_factory=list)

    is_tfsa: bool = False
    is_registered: bool = False  # TFSA, RRSP, RESP — gains not taxable in the usual sense


class CapitalGainsReport(BaseModel):
    """Capital gains aggregate. The CAD-suffixed fields are the authoritative
    figures for CRA reporting — they correctly sum across native currencies via
    each transaction's FX rate. The unsuffixed `total_*` fields sum raw native
    amounts and are kept for backward compatibility only; do not present them
    in any tax-facing UI."""

    realized_gains: list[RealizedGain]
    total_taxable_gain: float
    total_non_taxable_gain: float  # TFSA + RRSP
    total_taxable_gain_cad: float = 0.0
    total_non_taxable_gain_cad: float = 0.0
    total_superficial_loss_denied: float = 0.0
    total_superficial_loss_denied_cad: float = 0.0


# ---------- Holdings (display layer) ----------

class HistoricalDataPoint(BaseModel):
    date: date
    close: float
    weekly_return: float | None = None


class BenchmarkPoint(BaseModel):
    """One date in a normalized benchmark series (100 at start_date)."""

    date: date
    value: float  # normalized: 100 at start, scaled by cumulative return


class PortfolioValuePoint(BaseModel):
    """One date in the reconstructed portfolio value timeline."""

    date: date
    market_value_cad: float  # holdings only, converted to CAD at this week's close
    cash_cad: float          # cash balance to-date in CAD-equivalent
    total_cad: float         # market_value_cad + cash_cad
    net_deposits_cad: float  # cumulative deposits to date in CAD


class MonthlyDividend(BaseModel):
    """One month bucket on the dividend income bar chart."""

    month: str         # YYYY-MM
    amount_cad: float  # CAD-equivalent across all currencies


class UpcomingDividend(BaseModel):
    """A projected dividend payment based on historical cadence."""

    ticker: str
    security_name: str | None = None
    next_date: date
    estimated_amount_cad: float
    cadence_days: int  # average days between past payments


class DividendYieldRow(BaseModel):
    """Yield-on-cost per (ticker, account)."""

    ticker: str
    account_type: AccountType
    annual_dividends_cad: float
    total_cost_cad: float
    yield_on_cost_pct: float


class PriceAlert(BaseModel):
    id: int
    ticker: str
    alert_type: Literal["above", "below"]
    target_price: float
    currency: Currency = "CAD"
    triggered: bool = False
    triggered_at: datetime | None = None
    dismissed: bool = False
    created_at: datetime
    current_price: float | None = None  # filled in by the API for convenience


class PriceAlertCreate(BaseModel):
    ticker: str
    alert_type: Literal["above", "below"]
    target_price: float
    currency: Currency = "CAD"


class SimBuyRequest(BaseModel):
    ticker: str
    shares: float
    account_type: AccountType


class SimSellRequest(BaseModel):
    ticker: str
    shares: float
    account_type: AccountType


class SimLumpSumRequest(BaseModel):
    ticker: str
    amount_cad: float
    invest_date: date


class SimulationResult(BaseModel):
    """Generic envelope for all three simulator endpoints. Fields populated
    are mode-specific; unused ones stay None."""

    mode: Literal["buy", "sell", "lump_sum"]
    ticker: str
    description: str  # one-line headline shown above the breakdown
    detail_lines: list[str] = Field(default_factory=list)
    # buy: new position
    new_shares: float | None = None
    new_acb_per_share: float | None = None
    new_market_value_cad: float | None = None
    new_allocation_pct: float | None = None
    projected_annual_dividends_cad: float | None = None
    # sell: capital gain
    capital_gain_cad: float | None = None
    tax_estimate_cad: float | None = None
    remaining_shares: float | None = None
    remaining_market_value_cad: float | None = None
    # lump-sum
    value_today_cad: float | None = None
    cash_alternative_cad: float | None = None
    annualised_return_pct: float | None = None


class RebalanceTarget(BaseModel):
    ticker: str
    account_type: AccountType
    target_pct: float


class RebalanceAction(BaseModel):
    action: Literal["BUY", "SELL"]
    ticker: str
    account_type: AccountType
    shares: int
    price: float
    currency: Currency
    cost_cad: float
    resulting_pct: float


class RebalanceRequest(BaseModel):
    targets: list[RebalanceTarget]
    mode: Literal["rebalance", "new_money"]
    new_money_cad: float = 0.0


class RebalanceResponse(BaseModel):
    actions: list[RebalanceAction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    target_total_pct: float
    portfolio_value_cad: float
    note: str | None = None


class AttributionRow(BaseModel):
    """One holding's contribution to the portfolio's return over the period."""

    ticker: str
    account_type: AccountType
    security_name: str | None = None
    shares: float
    period_start_price: float | None
    current_price: float | None
    currency: Currency
    gain_cad: float  # CAD-equivalent gain over the period for this position
    contribution_pct: float  # gain_cad / portfolio_period_start_value × 100


class AttributionReport(BaseModel):
    period: str
    period_start_date: date | None = None
    total_return_pct: float
    portfolio_period_start_cad: float
    rows: list[AttributionRow] = Field(default_factory=list)
    top_contributor: str | None = None
    top_contributor_pct: float = 0.0
    biggest_drag: str | None = None
    biggest_drag_pct: float = 0.0


class DividendReport(BaseModel):
    monthly: list[MonthlyDividend]
    upcoming: list[UpcomingDividend]
    by_holding: list[DividendYieldRow]
    annual_total_cad: float
    trailing_12mo_cad: float
    period_total_cad: float = 0.0  # dividends within the selected period
    period_label: str = "all"


class Holding(BaseModel):
    """Display-layer holding card data."""

    ticker: str
    raw_symbol: str | None = None
    security_name: str | None = None
    account_type: AccountType
    currency: Currency = "CAD"
    exchange: str | None = None

    total_shares: float
    acb_per_share: float
    total_cost: float
    total_commission: float
    dividends_received: float

    current_price: float | None = None
    price_fetched_at: datetime | None = None
    price_is_stale: bool = False
    ticker_unresolved: bool = False

    market_value: float | None = None  # in native currency
    market_value_cad: float | None = None
    unrealized_gain: float | None = None
    roi_pct: float | None = None
    investment_weight_pct: float | None = None

    avg_weekly_return: float | None = None
    annualized_volatility: float | None = None

    # ---- period-aware (set when ?period= is active) ----
    period_return_pct: float | None = None  # price change from period start to today
    period_dividends_received: float = 0.0  # native currency, dividends in period
    period_start_price: float | None = None


# ---------- Portfolio aggregation ----------

class AccountBalances(BaseModel):
    account_type: AccountType
    account_number: str = ""    # e.g. "29171399"; empty for the combined row
    account_label: str = ""     # e.g. "Margin · 29171399"; empty for combined
    # ---- period-aware fields (set when ?period= filter is active) ----
    period_label: str = "all"
    period_start_value_cad: float = 0.0  # portfolio value at the start of the period
    period_return_cad: float = 0.0       # gain in CAD over the period
    period_return_pct: float = 0.0       # gain % over the period
    period_dividends_cad: float = 0.0    # dividends received within the period
    period_dividends_usd: float = 0.0
    cash_deposited_cad: float = 0.0
    cash_deposited_usd: float = 0.0
    cash_invested_cad: float = 0.0
    cash_invested_usd: float = 0.0
    total_fees_cad: float = 0.0
    total_fees_usd: float = 0.0
    total_dividends_cad: float = 0.0
    total_dividends_usd: float = 0.0
    cash_remaining_cad: float = 0.0
    cash_remaining_usd: float = 0.0
    total_equity_cad: float = 0.0
    total_equity_usd: float = 0.0
    unrealized_gain_cad: float = 0.0
    unrealized_gain_usd: float = 0.0
    overall_roi_pct: float = 0.0
    investment_weight_pct: float = 0.0


class PortfolioStats(BaseModel):
    max_periods_per_year: int = 52
    risk_free_rate: float = 0.0375
    observations: int = 0
    avg_period_return: float = 0.0
    std_dev_period: float = 0.0
    total_return: float = 0.0
    annualized_return: float = 0.0
    annualized_volatility: float = 0.0
    sharpe_ratio: float = 0.0


class CorrelationMatrix(BaseModel):
    tickers: list[str]
    # row-major NxN; matrix[i][j] is correlation between tickers[i] and tickers[j]
    matrix: list[list[float]]


class ExchangeRateInfo(BaseModel):
    usd_cad: float
    cad_usd: float
    fetched_at: datetime | None = None
    stale: bool = False


class AccountTab(BaseModel):
    """Identifies one selectable account in the dashboard tab bar."""

    key: str          # "all" | "<account_number>"
    label: str        # e.g. "All Accounts" | "Margin · 29171399"
    account_type: AccountType | None = None
    account_number: str | None = None


class PortfolioData(BaseModel):
    accounts: list[AccountBalances]
    combined: AccountBalances
    holdings: list[Holding]
    capital_gains: CapitalGainsReport
    stats: PortfolioStats
    exchange_rate: ExchangeRateInfo
    last_import: ImportInfo | None = None
    last_price_refresh_at: datetime | None = None
    unresolved_tickers: list[UnresolvedTicker] = Field(default_factory=list)
    tabs: list[AccountTab] = Field(default_factory=list)
    active_tab: str = "all"
    period: str = "all"
    period_start_date: date | None = None


# ---------- Settings & misc API responses ----------

class AppSettings(BaseModel):
    preferred_currency: Currency = "CAD"
    default_chart_frequency: Literal["daily", "weekly", "monthly"] = "weekly"
    risk_free_rate: float = 0.0375
    # ---- Tax (used by What-If Simulator + future tax reports) ----
    marginal_tax_rate: float = 0.26      # 26% default for an Ontario middle bracket
    tax_province: str = "ON"
    # ---- TFSA (used by Task 3 contribution-room calculator) ----
    tfsa_birth_year: int | None = None
    tfsa_resident_since: int | None = None
    # ---- Display ----
    default_period: Literal["1m", "3m", "6m", "ytd", "1y", "3y", "all"] = "all"
    default_currency_view: Literal["combined_cad", "combined_usd", "cad_only", "usd_only"] = "combined_cad"
    color_theme: Literal["dark", "light"] = "dark"
    # ---- Data ----
    price_refresh_interval_min: int = 30


class PriceRefreshResult(BaseModel):
    refreshed: int
    failed: list[str] = Field(default_factory=list)
    took_ms: int = 0


class PriceStatus(BaseModel):
    last_refresh: datetime | None = None
    age_minutes: int | None = None
    stale: bool = False


class ApiError(BaseModel):
    error: str
    detail: str = ""
    timestamp: datetime
