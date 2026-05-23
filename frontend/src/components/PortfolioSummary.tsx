import { useState } from "react";
import clsx from "clsx";
import type { AccountBalances, ExchangeRateInfo } from "../types";
import { fmt } from "../api";

interface Props {
  accounts: AccountBalances[];
  combined: AccountBalances;
  fx: ExchangeRateInfo;
  showCombinedRow: boolean;
  /** True when the requested period predated the first transaction and was clamped. */
  periodClamped?: boolean;
  /** Resolved period start date (used for the "Since MMM YYYY" label when clamped). */
  periodStartDate?: string | null;
}

type CurrencyView = "combined_cad" | "combined_usd" | "cad_only" | "usd_only";

const VIEW_OPTIONS: { value: CurrencyView; label: string }[] = [
  { value: "combined_cad", label: "Combined in CAD" },
  { value: "combined_usd", label: "Combined in USD" },
  { value: "cad_only", label: "CAD only" },
  { value: "usd_only", label: "USD only" },
];

export default function PortfolioSummary({ accounts, combined, fx, showCombinedRow, periodClamped, periodStartDate }: Props) {
  const [view, setView] = useState<CurrencyView>("combined_cad");
  // When the user filters to a single account, collapse to that one row —
  // no per-type breakdown, no Combined row.
  const rows: { label: string; account: AccountBalances }[] = accounts.map((a) => ({
    label: a.account_label || a.account_type,
    account: a,
  }));
  if (showCombinedRow) {
    rows.push({ label: "Combined", account: combined });
  }

  return (
    <div className="space-y-4">
      <CombinedGlance
        combined={combined}
        fx={fx}
        view={view}
        onChangeView={setView}
        periodClamped={periodClamped}
        periodStartDate={periodStartDate}
      />

      <div className="card overflow-x-auto">
        <h3 className="text-sm font-medium text-text-muted mb-3">By Account</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-text-muted text-left">
              <th className="font-medium pb-3 pr-4">Account</th>
              <th className="font-medium pb-3 px-3 text-right">Cash Deposited</th>
              <th className="font-medium pb-3 px-3 text-right">Cash Invested</th>
              <th className="font-medium pb-3 px-3 text-right">Fees</th>
              <th className="font-medium pb-3 px-3 text-right">Dividends</th>
              <th className="font-medium pb-3 px-3 text-right">Cash Remaining</th>
              <th className="font-medium pb-3 px-3 text-right">Total Equity</th>
              <th className="font-medium pb-3 px-3 text-right">Unrealized G/L</th>
              <th className="font-medium pb-3 pl-3 text-right">ROI %</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map(({ label, account }) => (
              <SummaryRow key={label} label={label} account={account} />
            ))}
          </tbody>
        </table>

        <div className="mt-4 flex items-center justify-end gap-4 text-xs text-text-muted">
          <span>
            USD/CAD: <span className="num text-text-primary">{fx.usd_cad.toFixed(4)}</span>
          </span>
          <span>
            CAD/USD: <span className="num text-text-primary">{fx.cad_usd.toFixed(4)}</span>
          </span>
          {fx.stale && <span className="text-yellow-400">⚠️ rate is stale</span>}
        </div>
      </div>
    </div>
  );
}

// ---------- Combined-at-a-glance card with the 4-mode currency toggle ----------

interface GlanceProps {
  combined: AccountBalances;
  fx: ExchangeRateInfo;
  view: CurrencyView;
  onChangeView: (v: CurrencyView) => void;
  periodClamped?: boolean;
  periodStartDate?: string | null;
}

function CombinedGlance({ combined, fx, view, onChangeView, periodClamped, periodStartDate }: GlanceProps) {
  const metrics = computeGlanceMetrics(combined, fx, view);
  const periodActive = combined.period_label && combined.period_label !== "all";
  // When the requested period (e.g. 3Y) predated the first transaction and
  // got clamped, show "Since MMM YYYY" instead of the requested fixed-duration
  // label so the user understands why the start value reflects a shorter
  // window than they picked.
  const periodChip =
    periodClamped && periodStartDate
      ? `Since ${new Date(periodStartDate).toLocaleString("en-CA", { month: "short", year: "numeric" })}`
      : combined.period_label?.toUpperCase();

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h3 className="text-sm font-medium text-text-muted">Combined</h3>
        <CurrencyToggle value={view} onChange={onChangeView} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-y-5 gap-x-8">
        <GlanceField label="Total Equity" value={metrics.totalEquity} ccy={metrics.ccy} />
        <GlanceField label="Cash" value={metrics.cash} ccy={metrics.ccy} />
        <GlanceField label="Market Value" value={metrics.marketValue} ccy={metrics.ccy} />
        <GlanceField label="Net Deposits" value={metrics.netDeposits} ccy={metrics.ccy} />
        <GlanceField
          label="Total P&L"
          value={metrics.pnl}
          ccy={metrics.ccy}
          tone={metrics.pnl === null ? "muted" : (metrics.pnl ?? 0) >= 0 ? "gain" : "loss"}
        />
        <GlanceField
          label="Simple Rate of Return"
          value={metrics.simpleRor}
          ccy={null}
          asPct
          tone={metrics.simpleRor === null ? "muted" : (metrics.simpleRor ?? 0) >= 0 ? "gain" : "loss"}
        />
      </div>

      {periodActive && (
        <div className="mt-5 pt-4 border-t border-border grid grid-cols-2 md:grid-cols-3 gap-y-5 gap-x-8">
          <GlanceField
            label={`Period Start Value (${periodChip})`}
            value={combined.period_start_value_cad}
            ccy="CAD"
            sublabel={periodStartDate ? `as of ${periodStartDate}` : periodStartDateHint(combined.period_label)}
          />
          <GlanceField
            label="Period Return"
            value={combined.period_return_cad}
            ccy="CAD"
            tone={combined.period_return_cad >= 0 ? "gain" : "loss"}
          />
          <GlanceField
            label="Period Return %"
            value={combined.period_return_pct}
            ccy={null}
            asPct
            tone={combined.period_return_pct >= 0 ? "gain" : "loss"}
          />
        </div>
      )}
    </div>
  );
}

interface GlanceMetrics {
  ccy: "CAD" | "USD";
  totalEquity: number;
  cash: number;
  marketValue: number;
  netDeposits: number | null;
  pnl: number | null;
  simpleRor: number | null;
}

function computeGlanceMetrics(
  c: AccountBalances,
  fx: ExchangeRateInfo,
  view: CurrencyView,
): GlanceMetrics {
  // total_equity_{cad,usd} already INCLUDE that currency's cash (Bug 2 fix).
  // Market value (holdings-only) = total_equity − cash_remaining.
  const marketCad = c.total_equity_cad - c.cash_remaining_cad;
  const marketUsd = c.total_equity_usd - c.cash_remaining_usd;
  const usdToCad = fx.usd_cad || 1;
  const cadToUsd = fx.cad_usd || (usdToCad ? 1 / usdToCad : 1);

  switch (view) {
    case "combined_cad": {
      const totalEquity = c.total_equity_cad + c.total_equity_usd * usdToCad;
      const cash = c.cash_remaining_cad + c.cash_remaining_usd * usdToCad;
      const marketValue = marketCad + marketUsd * usdToCad;
      const netDeposits = c.cash_deposited_cad + c.cash_deposited_usd * usdToCad;
      const pnl = totalEquity - netDeposits;
      const simpleRor = netDeposits > 0 ? (pnl / netDeposits) * 100 : 0;
      return { ccy: "CAD", totalEquity, cash, marketValue, netDeposits, pnl, simpleRor };
    }
    case "combined_usd": {
      const totalEquity = c.total_equity_usd + c.total_equity_cad * cadToUsd;
      const cash = c.cash_remaining_usd + c.cash_remaining_cad * cadToUsd;
      const marketValue = marketUsd + marketCad * cadToUsd;
      const netDeposits = c.cash_deposited_usd + c.cash_deposited_cad * cadToUsd;
      const pnl = totalEquity - netDeposits;
      const simpleRor = netDeposits > 0 ? (pnl / netDeposits) * 100 : 0;
      return { ccy: "USD", totalEquity, cash, marketValue, netDeposits, pnl, simpleRor };
    }
    case "cad_only": {
      // Single-currency-scope: show the CAD-leg net deposits / P&L / ROR.
      // Previously these returned null (rendering as "—"), which broke the
      // entire CAD-only view for accounts whose holdings are all CAD —
      // notably TFSA, which can only hold CAD-listed securities under CRA
      // rules (no USD-side TFSA in this app's data model).
      const netDeposits = c.cash_deposited_cad;
      const pnl = c.total_equity_cad - netDeposits;
      const simpleRor = netDeposits > 0 ? (pnl / netDeposits) * 100 : 0;
      return {
        ccy: "CAD",
        totalEquity: c.total_equity_cad,
        cash: c.cash_remaining_cad,
        marketValue: marketCad,
        netDeposits,
        pnl,
        simpleRor,
      };
    }
    case "usd_only": {
      const netDeposits = c.cash_deposited_usd;
      const pnl = c.total_equity_usd - netDeposits;
      const simpleRor = netDeposits > 0 ? (pnl / netDeposits) * 100 : 0;
      return {
        ccy: "USD",
        totalEquity: c.total_equity_usd,
        cash: c.cash_remaining_usd,
        marketValue: marketUsd,
        netDeposits,
        pnl,
        simpleRor,
      };
    }
  }
}

function CurrencyToggle({
  value,
  onChange,
}: {
  value: CurrencyView;
  onChange: (v: CurrencyView) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 bg-white/[0.04] p-1 rounded-full">
      {VIEW_OPTIONS.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={clsx(
              "px-3 py-1.5 text-xs font-medium rounded-full transition-colors whitespace-nowrap",
              active
                ? "bg-accent text-white"
                : "text-text-muted hover:text-text-primary hover:bg-white/[0.06]",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function GlanceField({
  label,
  value,
  ccy,
  asPct,
  tone,
  sublabel,
}: {
  label: string;
  value: number | null;
  ccy: "CAD" | "USD" | null;
  asPct?: boolean;
  tone?: "gain" | "loss" | "muted";
  sublabel?: string;
}) {
  const formatted =
    value === null
      ? "—"
      : asPct
      ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`
      : `${value >= 0 ? "" : "-"}$${Math.abs(value).toLocaleString("en-CA", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`;
  return (
    <div>
      <div className="label-muted">{label}</div>
      <div
        className={clsx(
          "num text-lg font-semibold",
          tone === "gain" && "text-gain",
          tone === "loss" && "text-loss",
          tone === "muted" && "text-text-muted",
        )}
      >
        {formatted}
        {value !== null && ccy && !asPct && (
          <span className="text-xs text-text-muted ml-1">{ccy}</span>
        )}
      </div>
      {sublabel && <div className="text-xs text-text-muted mt-0.5">{sublabel}</div>}
    </div>
  );
}

function periodStartDateHint(periodLabel: string): string {
  // The backend snaps to the first weekly point on/after the calendar boundary;
  // surfacing the calendar date here lets users cross-check against the chart.
  const today = new Date();
  const days: Record<string, number> = { "1m": 30, "3m": 90, "6m": 180, "1y": 365, "3y": 1095 };
  const p = periodLabel.toLowerCase();
  let start: Date;
  if (p === "ytd") {
    start = new Date(today.getFullYear(), 0, 1);
  } else if (days[p]) {
    start = new Date(today.getTime() - days[p] * 24 * 60 * 60 * 1000);
  } else {
    return "";
  }
  return `as of ~${start.toISOString().slice(0, 10)}`;
}

// ---------- Existing per-account table row (unchanged) ----------

function SummaryRow({ label, account }: { label: string; account: AccountBalances }) {
  const isCombined = label === "Combined";
  return (
    <tr className={clsx(isCombined && "font-semibold bg-white/[0.02]")}>
      <td className="py-3 pr-4">{label}</td>
      <Money cad={account.cash_deposited_cad} usd={account.cash_deposited_usd} />
      <Money cad={account.cash_invested_cad} usd={account.cash_invested_usd} />
      <Money cad={account.total_fees_cad} usd={account.total_fees_usd} />
      <Money cad={account.total_dividends_cad} usd={account.total_dividends_usd} />
      <Money cad={account.cash_remaining_cad} usd={account.cash_remaining_usd} />
      <Money cad={account.total_equity_cad} usd={account.total_equity_usd} />
      <td className="num text-right px-3 py-3">
        <ColoredAmount cad={account.unrealized_gain_cad} usd={account.unrealized_gain_usd} />
      </td>
      <td
        className={clsx(
          "num text-right pl-3 py-3 font-medium",
          account.overall_roi_pct >= 0 ? "text-gain" : "text-loss",
        )}
      >
        {fmt.pct(account.overall_roi_pct)}
      </td>
    </tr>
  );
}

function Money({ cad, usd }: { cad: number; usd: number }) {
  return (
    <td className="num text-right px-3 py-3">
      <div>
        {fmt.moneyShort(cad)}
        <span className="text-text-muted text-xs ml-1">CAD</span>
      </div>
      {usd !== 0 && (
        <div className="text-text-muted text-xs">{fmt.moneyShort(usd)} USD</div>
      )}
    </td>
  );
}

function ColoredAmount({ cad, usd }: { cad: number; usd: number }) {
  return (
    <>
      <div className={cad >= 0 ? "text-gain" : "text-loss"}>
        {fmt.moneyShort(cad)}
        <span className="text-text-muted text-xs ml-1">CAD</span>
      </div>
      {usd !== 0 && (
        <div className={clsx("text-xs", usd >= 0 ? "text-gain/70" : "text-loss/70")}>
          {fmt.moneyShort(usd)} USD
        </div>
      )}
    </>
  );
}
