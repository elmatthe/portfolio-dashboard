import { AreaChart, Area, ResponsiveContainer } from "recharts";
import clsx from "clsx";
import { AlertTriangle, HelpCircle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import type { Holding } from "../types";
import { api, fmt } from "../api";
import { usePeriod } from "./PeriodContext";

interface Props {
  holding: Holding;
  onClick: () => void;
  active: boolean;
}

// Map period → number of days to show on the sparkline. "all" defaults to 90.
const SPARK_DAYS: Record<string, number> = {
  "1m": 30,
  "3m": 90,
  "6m": 180,
  ytd: 180,
  "1y": 365,
  "3y": 365 * 3,
  all: 90,
};

export default function HoldingCard({ holding, onClick, active }: Props) {
  const { period } = usePeriod();
  // Lazy-load sparkline data per-card; React Query dedupes per ticker.
  const history = useQuery({
    queryKey: ["history", holding.ticker],
    queryFn: () => api.history(holding.ticker),
    staleTime: 5 * 60_000,
  });
  // Sparkline window matches the global period selector.
  const days = SPARK_DAYS[period] || 90;
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  const spark =
    history.data
      ?.filter((p) => new Date(p.date).getTime() >= cutoff)
      .map((p) => ({ date: p.date, close: p.close })) || [];
  const isUp = (holding.roi_pct ?? 0) >= 0;
  const periodActive = period !== "all";
  const periodPct = holding.period_return_pct;
  const periodUp = (periodPct ?? 0) >= 0;

  return (
    <button
      onClick={onClick}
      className={clsx(
        "card text-left transition-all hover:border-white/20 hover:bg-white/[0.03]",
        active && "ring-1 ring-accent border-accent/40",
      )}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-base">{holding.ticker}</span>
            {holding.exchange && (
              <span className="badge bg-white/5 text-text-muted">{holding.exchange}</span>
            )}
            <span
              className={clsx(
                "badge",
                holding.account_type === "TFSA"
                  ? "bg-emerald-500/15 text-emerald-300"
                  : holding.account_type === "RRSP"
                  ? "bg-blue-500/15 text-blue-300"
                  : "bg-white/5 text-text-muted",
              )}
            >
              {holding.account_type}
            </span>
            <span className="badge bg-white/5 text-text-muted">{holding.currency}</span>
            {holding.price_is_stale && (
              <span title="Price is stale">
                <AlertTriangle size={14} className="text-yellow-400" />
              </span>
            )}
            {holding.ticker_unresolved && (
              <span title="Ticker unresolved">
                <HelpCircle size={14} className="text-yellow-400" />
              </span>
            )}
          </div>
          {holding.security_name && (
            <div className="text-xs text-text-muted mt-0.5 truncate max-w-[15rem]">
              {holding.security_name}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end">
          <div className={clsx("num font-semibold text-lg", isUp ? "text-gain" : "text-loss")}>
            {fmt.pct(holding.roi_pct)}
          </div>
          {periodActive && periodPct !== null && (
            <span
              className={clsx(
                "badge num text-xs mt-1",
                periodUp ? "bg-gain/15 text-gain" : "bg-loss/15 text-loss",
              )}
              title={`Price change since the start of the selected period`}
            >
              {period.toUpperCase()}: {fmt.pct(periodPct)}
            </span>
          )}
        </div>
      </div>

      {spark.length > 0 && (
        <div className="h-12 -mx-1 mb-3">
          <ResponsiveContainer>
            <AreaChart data={spark}>
              <defs>
                <linearGradient id={`g-${holding.ticker}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={isUp ? "#10B981" : "#EF4444"} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={isUp ? "#10B981" : "#EF4444"} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="close"
                stroke={isUp ? "#10B981" : "#EF4444"}
                strokeWidth={1.5}
                fill={`url(#g-${holding.ticker})`}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid grid-cols-2 gap-y-2 text-xs">
        <Field label="Current Price" value={fmt.money(holding.current_price, holding.currency)} />
        <Field label="Avg Buy Price" value={fmt.money(holding.acb_per_share, holding.currency)} />
        <Field label="Shares" value={<span className="num">{holding.total_shares.toLocaleString()}</span>} />
        <Field label="Market Value" value={fmt.money(holding.market_value, holding.currency)} />
        <Field label="Total Cost" value={fmt.money(holding.total_cost, holding.currency)} />
        <Field label="Commission" value={fmt.money(holding.total_commission, holding.currency)} />
        <Field label="Dividends" value={fmt.money(holding.dividends_received, holding.currency)} />
        <Field label="Portfolio Weight" value={fmt.pct(holding.investment_weight_pct)} />
      </div>
    </button>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="label-muted">{label}</div>
      <div className="num text-text-primary">{value}</div>
    </div>
  );
}
