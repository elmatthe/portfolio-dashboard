import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useHistory } from "../hooks/usePortfolio";
import { api, fmt } from "../api";

interface HoldingOption {
  ticker: string;
  account_type: string;
}

interface Props {
  ticker: string;
  acb: number | null;
  holdings: HoldingOption[];
  onChangeTicker: (t: string) => void;
}

const RANGES: { label: string; days: number | null }[] = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
  { label: "3Y", days: 365 * 3 },
  { label: "All", days: null },
];

export default function HistoricalChart({ ticker, acb, holdings, onChangeTicker }: Props) {
  const [range, setRange] = useState<number | null>(365);
  const [showBenchmark, setShowBenchmark] = useState(false);
  const history = useHistory(ticker);

  // Filter the holding's history to the selected range first.
  const filteredHistory = useMemo(() => {
    if (!history.data) return [];
    if (range === null) return history.data;
    const cutoff = Date.now() - range * 24 * 60 * 60 * 1000;
    return history.data.filter((p) => new Date(p.date).getTime() >= cutoff);
  }, [history.data, range]);

  // Pull SPY benchmark normalized from the same start date as our filtered window.
  const benchmarkStart = filteredHistory[0]?.date;
  const benchmark = useQuery({
    queryKey: ["benchmark", "SPY", benchmarkStart ?? "all"],
    queryFn: () => api.benchmark(benchmarkStart),
    enabled: showBenchmark && !!benchmarkStart,
    staleTime: 60 * 60_000,
  });

  // Merge into a single shape: { date, close, benchmark? } so Recharts can draw both lines.
  const data = useMemo(() => {
    if (!showBenchmark || !benchmark.data?.length) return filteredHistory;
    const bmMap = new Map<string, number>();
    benchmark.data.forEach((p) => bmMap.set(p.date, p.value));
    // Re-normalize the benchmark so it equals 100 at our chart's first date,
    // not at SPY's first available date (which may differ by a few days).
    const firstBm = benchmark.data.find((p) => p.date >= (benchmarkStart || ""))?.value || 100;
    return filteredHistory.map((p) => ({
      ...p,
      benchmark: bmMap.has(p.date) ? (bmMap.get(p.date)! / firstBm) * 100 : null,
    }));
  }, [filteredHistory, benchmark.data, benchmarkStart, showBenchmark]);

  // When the same ticker is held in multiple accounts (e.g. VEQT.TO in TFSA + Margin),
  // each option needs a unique React key — ticker + account_type. We also append the
  // account name to the label in that case so the user can tell them apart.
  const tickerCounts = useMemo(() => {
    const counts = new Map<string, number>();
    holdings.forEach((h) => counts.set(h.ticker, (counts.get(h.ticker) || 0) + 1));
    return counts;
  }, [holdings]);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <select
          className="bg-white/5 border border-border rounded-md px-3 py-1.5 text-sm"
          value={ticker}
          onChange={(e) => onChangeTicker(e.target.value)}
        >
          {holdings.map((h) => {
            const label =
              (tickerCounts.get(h.ticker) || 0) > 1
                ? `${h.ticker} (${h.account_type})`
                : h.ticker;
            return (
              <option key={`${h.ticker}-${h.account_type}`} value={h.ticker}>
                {label}
              </option>
            );
          })}
        </select>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="inline-flex items-center gap-1.5 text-xs text-text-muted cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showBenchmark}
              onChange={(e) => setShowBenchmark(e.target.checked)}
              className="accent-accent"
            />
            Show S&amp;P 500 benchmark
          </label>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r.label}
                onClick={() => setRange(r.days)}
                className={`px-2.5 py-1 text-xs rounded-md ${
                  range === r.days
                    ? "bg-accent text-white"
                    : "bg-white/5 text-text-muted hover:text-text-primary"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="h-72">
        {history.isLoading ? (
          <div className="h-full flex items-center justify-center text-text-muted text-sm">
            Loading…
          </div>
        ) : data.length === 0 ? (
          <div className="h-full flex items-center justify-center text-text-muted text-sm">
            No price history yet — try refreshing prices.
          </div>
        ) : (
          <ResponsiveContainer>
            <ComposedChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#1f2937" strokeDasharray="2 4" />
              <XAxis
                dataKey="date"
                stroke="#6B7280"
                fontSize={11}
                tickFormatter={(d) =>
                  new Date(d).toLocaleDateString("en-CA", { month: "short", year: "2-digit" })
                }
              />
              <YAxis
                yAxisId="price"
                stroke="#6B7280"
                fontSize={11}
                domain={["auto", "auto"]}
                tickFormatter={(v) => `$${v.toFixed(0)}`}
              />
              {showBenchmark && (
                <YAxis
                  yAxisId="bench"
                  orientation="right"
                  stroke="#94A3B8"
                  fontSize={11}
                  domain={["auto", "auto"]}
                  tickFormatter={(v) => `${v.toFixed(0)}`}
                />
              )}
              <Tooltip
                contentStyle={{
                  background: "#111827",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: "8px",
                }}
                formatter={(value: number, name: string) => {
                  if (name === "S&P 500 (SPY)") return [`${value.toFixed(2)}`, "S&P 500 (SPY)"];
                  return [fmt.moneyShort(value), "Close"];
                }}
                labelFormatter={(d) => fmt.date(d as string)}
              />
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="close"
                name="Close"
                stroke="rgb(var(--accent-rgb))"
                strokeWidth={1.5}
                dot={false}
              />
              {showBenchmark && (
                <Line
                  yAxisId="bench"
                  type="monotone"
                  dataKey="benchmark"
                  name="S&P 500 (SPY)"
                  stroke="#94A3B8"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls
                />
              )}
              {acb && (
                <ReferenceLine
                  yAxisId="price"
                  y={acb}
                  stroke="#10B981"
                  strokeDasharray="4 4"
                  label={{
                    value: `ACB ${fmt.moneyShort(acb)}`,
                    fill: "#10B981",
                    fontSize: 10,
                    position: "left",
                  }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {showBenchmark && (
        <div className="mt-2 text-xs text-text-muted">
          Right axis: S&amp;P 500 indexed to 100 at the start of the visible range. Hover over a point
          to see both values.
        </div>
      )}
    </div>
  );
}
