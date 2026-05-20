// Mirrors backend/models.py exactly. Keep in sync when fields change.

export type Broker =
  | "questrade"
  | "wealthsimple"
  | "rbc"
  | "cibc"
  | "td"
  | "bmo"
  | "scotiabank"
  | "interactive"
  | "nationalbank"
  | "fidelity"
  | "hsbc"
  | "generic";

export type Action =
  | "BUY"
  | "SELL"
  | "DIVIDEND"
  | "DEPOSIT"
  | "WITHDRAWAL"
  | "CONTRIBUTION"
  | "FEE"
  | "SPLIT"
  | "INTEREST"
  | "TRANSFER"
  | "OTHER";

export type AccountType =
  | "TFSA"
  | "Margin"
  | "RRSP"
  | "Crypto"
  | "RESP"
  | "RRIF"
  | "Non-Registered"
  | "IRA"
  | "Roth IRA"
  | "Traditional IRA"
  | "Individual"
  | "LIRA"
  | "FHSA"
  | "Other";

export type Currency =
  | "CAD"
  | "USD"
  | "GBP"
  | "EUR"
  | "JPY"
  | "AUD"
  | "CHF"
  | "HKD"
  | "SEK"
  | "NOK";

export interface Transaction {
  hash: string;
  broker: Broker;
  transaction_date: string; // ISO date
  settlement_date?: string | null;
  action: Action;
  raw_symbol?: string | null;
  resolved_ticker?: string | null;
  description: string;
  quantity: number;
  price: number;
  gross_amount: number;
  commission: number;
  net_amount: number;
  currency: Currency;
  account_number: string;
  account_type: AccountType;
  // v0.3.0 multi-currency fields (nullable for legacy rows)
  fx_rate_to_cad?: number | null;
  net_cad?: number | null;
  isin?: string | null;
  exchange?: string | null;
  reference_id?: string | null;
}

export interface ResolvedTicker {
  raw_symbol: string;
  resolved_ticker: string | null;
  security_name?: string | null;
  exchange?: string | null;
  currency?: Currency | null;
  resolved_from: "pattern" | "yfinance_search" | "manual" | "fallback";
  status: "resolved" | "unresolved";
}

export interface UnresolvedTicker {
  raw_symbol: string;
  description?: string | null;
  occurrences: number;
}

export interface ImportInfo {
  filename: string | null;
  timestamp: string | null;
  transaction_count: number;
}

export interface ImportStatus {
  has_data: boolean;
  last_import: ImportInfo | null;
}

export interface ImportResult {
  inserted: number;
  skipped_duplicates: number;
  total_in_db: number;
  new_tickers_resolved: string[];
  unresolved_tickers: string[];
  import_duration_ms: number;
  detected_broker?: Broker | null;
  detected_format?: string | null;
}

export interface RealizedGain {
  transaction_date: string;
  ticker: string;
  security_name?: string | null;
  account_type: AccountType;
  shares_sold: number;
  sale_price: number;
  acb_per_share: number;
  gain_per_share: number;
  total_gain: number;
  commission: number;
  currency: Currency;
  taxable: boolean;
  superficial_loss_adjustment: number;
  notes?: string | null;
}

export interface SuperficialLossAdjustment {
  transaction_date: string;
  ticker: string;
  denied_loss: number;
  repurchase_date?: string | null;
  note: string;
}

export interface CapitalGainsReport {
  realized_gains: RealizedGain[];
  total_taxable_gain: number;
  total_non_taxable_gain: number;
  total_superficial_loss_denied: number;
}

export interface Holding {
  ticker: string;
  raw_symbol?: string | null;
  security_name?: string | null;
  account_type: AccountType;
  currency: Currency;
  exchange?: string | null;
  total_shares: number;
  acb_per_share: number;
  total_cost: number;
  total_commission: number;
  dividends_received: number;
  current_price: number | null;
  price_fetched_at: string | null;
  price_is_stale: boolean;
  ticker_unresolved: boolean;
  market_value: number | null;
  market_value_cad: number | null;
  unrealized_gain: number | null;
  roi_pct: number | null;
  investment_weight_pct: number | null;
  avg_weekly_return: number | null;
  annualized_volatility: number | null;
  period_return_pct: number | null;
  period_dividends_received: number;
  period_start_price: number | null;
}

export type PeriodKey = "1m" | "3m" | "6m" | "ytd" | "1y" | "3y" | "all";

export interface AccountBalances {
  account_type: AccountType;
  account_number: string;
  account_label: string;
  period_label: string;
  period_start_value_cad: number;
  period_return_cad: number;
  period_return_pct: number;
  period_dividends_cad: number;
  period_dividends_usd: number;
  cash_deposited_cad: number;
  cash_deposited_usd: number;
  cash_invested_cad: number;
  cash_invested_usd: number;
  total_fees_cad: number;
  total_fees_usd: number;
  total_dividends_cad: number;
  total_dividends_usd: number;
  cash_remaining_cad: number;
  cash_remaining_usd: number;
  total_equity_cad: number;
  total_equity_usd: number;
  unrealized_gain_cad: number;
  unrealized_gain_usd: number;
  overall_roi_pct: number;
  investment_weight_pct: number;
}

export interface PortfolioStats {
  max_periods_per_year: number;
  risk_free_rate: number;
  observations: number;
  avg_period_return: number;
  std_dev_period: number;
  total_return: number;
  annualized_return: number;
  annualized_volatility: number;
  sharpe_ratio: number;
}

export interface CorrelationMatrix {
  tickers: string[];
  matrix: number[][];
}

export interface ExchangeRateInfo {
  usd_cad: number;
  cad_usd: number;
  fetched_at: string | null;
  stale: boolean;
}

export interface AccountTab {
  key: string;
  label: string;
  account_type: AccountType | null;
  account_number: string | null;
}

export interface PortfolioData {
  accounts: AccountBalances[];
  combined: AccountBalances;
  holdings: Holding[];
  capital_gains: CapitalGainsReport;
  stats: PortfolioStats;
  exchange_rate: ExchangeRateInfo;
  last_import: ImportInfo | null;
  last_price_refresh_at: string | null;
  unresolved_tickers: UnresolvedTicker[];
  tabs: AccountTab[];
  active_tab: string;
  period: PeriodKey;
  period_start_date: string | null;
}

export interface HistoricalDataPoint {
  date: string;
  close: number;
  weekly_return: number | null;
}

export interface BenchmarkPoint {
  date: string;
  value: number; // normalized: 100 at start
}

export interface PortfolioValuePoint {
  date: string;
  market_value_cad: number;
  cash_cad: number;
  total_cad: number;
  net_deposits_cad: number;
}

export interface MonthlyDividend {
  month: string; // YYYY-MM
  amount_cad: number;
}

export interface UpcomingDividend {
  ticker: string;
  security_name: string | null;
  next_date: string;
  estimated_amount_cad: number;
  cadence_days: number;
}

export interface DividendYieldRow {
  ticker: string;
  account_type: AccountType;
  annual_dividends_cad: number;
  total_cost_cad: number;
  yield_on_cost_pct: number;
}

export interface DividendReport {
  monthly: MonthlyDividend[];
  upcoming: UpcomingDividend[];
  by_holding: DividendYieldRow[];
  annual_total_cad: number;
  trailing_12mo_cad: number;
  period_total_cad: number;
  period_label: string;
}

export interface AppSettings {
  preferred_currency: Currency;
  default_chart_frequency: "daily" | "weekly" | "monthly";
  risk_free_rate: number;
  marginal_tax_rate: number;
  tax_province: string;
  tfsa_birth_year: number | null;
  tfsa_resident_since: number | null;
  default_period: PeriodKey;
  default_currency_view: "combined_cad" | "combined_usd" | "cad_only" | "usd_only";
  color_theme: "dark" | "light";
  price_refresh_interval_min: number;
}

export interface Profile {
  id: string;
  name: string;
  created_at: string;
  last_imported_at: string | null;
  color: string;
}

export interface ProfilesListResponse {
  active_profile_id: string;
  profiles: Profile[];
}

export interface TfsaAnnualRow {
  year: number;
  annual_limit_cad: number;
  contributions_cad: number;
  withdrawals_cad: number;
}

export interface PriceAlert {
  id: number;
  ticker: string;
  alert_type: "above" | "below";
  target_price: number;
  currency: Currency;
  triggered: boolean;
  triggered_at: string | null;
  dismissed: boolean;
  created_at: string;
  current_price: number | null;
}

export interface SimulationResult {
  mode: "buy" | "sell" | "lump_sum";
  ticker: string;
  description: string;
  detail_lines: string[];
  new_shares: number | null;
  new_acb_per_share: number | null;
  new_market_value_cad: number | null;
  new_allocation_pct: number | null;
  projected_annual_dividends_cad: number | null;
  capital_gain_cad: number | null;
  tax_estimate_cad: number | null;
  remaining_shares: number | null;
  remaining_market_value_cad: number | null;
  value_today_cad: number | null;
  cash_alternative_cad: number | null;
  annualised_return_pct: number | null;
}

export interface RebalanceTarget {
  ticker: string;
  account_type: AccountType;
  target_pct: number;
}

export interface RebalanceAction {
  action: "BUY" | "SELL";
  ticker: string;
  account_type: AccountType;
  shares: number;
  price: number;
  currency: Currency;
  cost_cad: number;
  resulting_pct: number;
}

export interface RebalanceResponse {
  actions: RebalanceAction[];
  warnings: string[];
  target_total_pct: number;
  portfolio_value_cad: number;
  note: string | null;
}

export interface AttributionRow {
  ticker: string;
  account_type: AccountType;
  security_name: string | null;
  shares: number;
  period_start_price: number | null;
  current_price: number | null;
  currency: Currency;
  gain_cad: number;
  contribution_pct: number;
}

export interface AttributionReport {
  period: string;
  period_start_date: string | null;
  total_return_pct: number;
  portfolio_period_start_cad: number;
  rows: AttributionRow[];
  top_contributor: string | null;
  top_contributor_pct: number;
  biggest_drag: string | null;
  biggest_drag_pct: number;
}

export interface TfsaRoomReport {
  total_room_accumulated: number;
  total_contributions: number;
  total_withdrawals: number;
  contribution_room_remaining: number;
  current_year_limit: number;
  contributions_this_year: number;
  withdrawals_last_year_added_back: number;
  over_contributed: boolean;
  over_contribution_amount: number;
  annual_breakdown: TfsaAnnualRow[];
  eligibility_start_year: number;
  missing_settings: string[];
}

export interface PriceRefreshResult {
  refreshed: number;
  failed: string[];
  took_ms: number;
}

export interface PriceStatus {
  last_refresh: string | null;
  age_minutes: number | null;
  stale: boolean;
}
