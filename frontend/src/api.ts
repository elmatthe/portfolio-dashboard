// Single API client module. All fetches go through here.
import type {
  AppSettings,
  AttributionReport,
  AccountType,
  Currency,
  RebalanceResponse,
  RebalanceTarget,
  SimulationResult,
  BenchmarkPoint,
  CapitalGainsReport,
  CorrelationMatrix,
  DividendReport,
  HistoricalDataPoint,
  Holding,
  ImportResult,
  ImportStatus,
  PortfolioData,
  PortfolioStats,
  PortfolioValuePoint,
  PriceAlert,
  PriceRefreshResult,
  PriceStatus,
  Profile,
  ProfilesListResponse,
  ResolvedTicker,
  TfsaRoomReport,
  UnresolvedTicker,
} from "./types";

// In dev the Vite proxy forwards /api → :7842. In production Electron loads
// from file:// and the backend is on localhost:7842, so we use an absolute URL.
const BASE =
  // @ts-expect-error — Vite injects import.meta.env
  import.meta.env?.DEV ? "" : "http://localhost:7842";

function withAccountAndPeriod(account?: string, period?: string): string {
  const parts: string[] = [];
  if (account && account !== "all") parts.push(`account=${encodeURIComponent(account)}`);
  if (period && period !== "all") parts.push(`period=${encodeURIComponent(period)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

// Legacy single-arg helper kept for endpoints that don't take period.
function withAccount(account?: string): string {
  return withAccountAndPeriod(account);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.error || detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string; db_path: string; db_size_kb: number }>("/health"),
  importStatus: () => request<ImportStatus>("/api/import/status"),
  importFile: async (file: File): Promise<ImportResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}/api/import`, { method: "POST", body: fd });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || body.error || detail;
      } catch {
        /* */
      }
      throw new Error(detail);
    }
    return res.json();
  },
  portfolio: (account?: string, period?: string) =>
    request<PortfolioData>(`/api/portfolio${withAccountAndPeriod(account, period)}`),
  holdings: (account?: string, period?: string) =>
    request<Holding[]>(`/api/holdings${withAccountAndPeriod(account, period)}`),
  capitalGains: (account?: string, period?: string) =>
    request<CapitalGainsReport>(`/api/capital-gains${withAccountAndPeriod(account, period)}`),
  history: (ticker: string) =>
    request<HistoricalDataPoint[]>(`/api/history/${encodeURIComponent(ticker)}`),
  benchmark: (start?: string) =>
    request<BenchmarkPoint[]>(
      `/api/history/benchmark/spy${start ? `?start=${encodeURIComponent(start)}` : ""}`,
    ),
  portfolioValueHistory: (account?: string, period?: string) =>
    request<PortfolioValuePoint[]>(
      `/api/portfolio/value-history${withAccountAndPeriod(account, period)}`,
    ),
  dividends: (account?: string, period?: string) =>
    request<DividendReport>(`/api/dividends${withAccountAndPeriod(account, period)}`),
  attribution: (account?: string, period?: string) =>
    request<AttributionReport>(`/api/attribution${withAccountAndPeriod(account, period)}`),
  rebalance: (body: { targets: RebalanceTarget[]; mode: "rebalance" | "new_money"; new_money_cad: number }) =>
    request<RebalanceResponse>("/api/rebalance", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  simulateBuy: (ticker: string, shares: number, account_type: AccountType) =>
    request<SimulationResult>("/api/simulate/buy", {
      method: "POST",
      body: JSON.stringify({ ticker, shares, account_type }),
    }),
  simulateSell: (ticker: string, shares: number, account_type: AccountType) =>
    request<SimulationResult>("/api/simulate/sell", {
      method: "POST",
      body: JSON.stringify({ ticker, shares, account_type }),
    }),
  simulateLumpSum: (ticker: string, amount_cad: number, invest_date: string) =>
    request<SimulationResult>("/api/simulate/lump-sum", {
      method: "POST",
      body: JSON.stringify({ ticker, amount_cad, invest_date }),
    }),

  // ---------- price alerts ----------
  alerts: () => request<PriceAlert[]>("/api/alerts"),
  alertsTriggered: () => request<PriceAlert[]>("/api/alerts/triggered"),
  createAlert: (ticker: string, alert_type: "above" | "below", target_price: number, currency: Currency) =>
    request<PriceAlert>("/api/alerts", {
      method: "POST",
      body: JSON.stringify({ ticker, alert_type, target_price, currency }),
    }),
  deleteAlert: (id: number) =>
    request<{ success: boolean }>(`/api/alerts/${encodeURIComponent(id)}`, { method: "DELETE" }),
  dismissAlert: (id: number) =>
    request<{ success: boolean }>(`/api/alerts/${encodeURIComponent(id)}/dismiss`, { method: "POST" }),
  correlation: (account?: string, period?: string) =>
    request<CorrelationMatrix>(`/api/correlation${withAccountAndPeriod(account, period)}`),
  stats: (account?: string, period?: string) =>
    request<PortfolioStats>(`/api/stats${withAccountAndPeriod(account, period)}`),
  refreshPrices: () => request<PriceRefreshResult>("/api/prices/refresh", { method: "POST" }),
  priceStatus: () => request<PriceStatus>("/api/prices/status"),
  unresolved: () => request<UnresolvedTicker[]>("/api/tickers/unresolved"),
  resolveTicker: (raw_symbol: string, resolved_ticker: string) =>
    request<ResolvedTicker>("/api/tickers/resolve", {
      method: "POST",
      body: JSON.stringify({ raw_symbol, resolved_ticker }),
    }),
  exportXlsxUrl: (period?: string) =>
    `${BASE}/api/export/xlsx${period && period !== "all" ? `?period=${encodeURIComponent(period)}` : ""}`,
  exportTaxReportUrl: (year: number) =>
    `${BASE}/api/export/tax-report?year=${encodeURIComponent(year)}`,
  exportAnnualReportUrl: (year: number) =>
    `${BASE}/api/export/annual-report?year=${encodeURIComponent(year)}`,
  settings: () => request<AppSettings>("/api/settings"),
  saveSettings: (s: AppSettings) =>
    request<AppSettings>("/api/settings", { method: "PATCH", body: JSON.stringify(s) }),
  clearData: () =>
    request<{ success: boolean; detail: string }>("/api/data/clear", { method: "POST" }),
  exportJsonUrl: () => `${BASE}/api/data/export-json`,

  // ---------- profiles ----------
  profiles: () => request<ProfilesListResponse>("/api/profiles"),
  activeProfile: () => request<Profile>("/api/profiles/active"),
  createProfile: (name: string, color: string) =>
    request<Profile>("/api/profiles", {
      method: "POST",
      body: JSON.stringify({ name, color }),
    }),
  activateProfile: (id: string) =>
    request<Profile>(`/api/profiles/${encodeURIComponent(id)}/activate`, { method: "POST" }),
  deleteProfile: (id: string) =>
    request<{ success: boolean; active_profile_id?: string }>(
      `/api/profiles/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),
  renameProfile: (id: string, name: string, color?: string) =>
    request<Profile>(`/api/profiles/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name, color }),
    }),
  tfsaRoom: () => request<TfsaRoomReport>("/api/tfsa/room"),
};

// Per-currency display symbol. JPY uses the actual yen sign; everything else
// falls back to "$" since callers always append the ISO code as a suffix
// anyway (e.g. "$123.45 GBP"), which keeps the formatter unambiguous.
const CURRENCY_SYMBOLS: Record<Currency, string> = {
  CAD: "$",
  USD: "$",
  GBP: "£",
  EUR: "€",
  JPY: "¥",
  AUD: "$",
  CHF: "Fr ",
  HKD: "$",
  SEK: "kr ",
  NOK: "kr ",
};

// Small formatting helpers used across components.
export const fmt = {
  money(amount: number | null | undefined, currency: Currency = "CAD"): string {
    if (amount === null || amount === undefined || Number.isNaN(amount)) return "—";
    const symbol = CURRENCY_SYMBOLS[currency] ?? "$";
    const decimals = currency === "JPY" ? 0 : 2;
    const sign = amount < 0 ? "-" : "";
    const abs = Math.abs(amount).toLocaleString("en-CA", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    return `${sign}${symbol}${abs} ${currency}`;
  },
  moneyShort(amount: number | null | undefined): string {
    if (amount === null || amount === undefined) return "—";
    const sign = amount < 0 ? "-" : "";
    const abs = Math.abs(amount).toLocaleString("en-CA", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return `${sign}$${abs}`;
  },
  pct(value: number | null | undefined, digits = 2): string {
    if (value === null || value === undefined) return "—";
    return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
  },
  date(iso: string | null | undefined): string {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("en-CA", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  },
  ago(iso: string | null | undefined): string {
    if (!iso) return "never";
    const diffMs = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diffMs / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  },
};
