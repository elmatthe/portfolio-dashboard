import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ComposedChart,
} from "recharts";
import { api, fmt } from "../api";
import { usePeriod } from "./PeriodContext";

interface Props {
  account: string;
}

export default function PortfolioValueChart({ account }: Props) {
  const { period } = usePeriod();
  const q = useQuery({
    queryKey: ["portfolio-value", account, period],
    queryFn: () => api.portfolioValueHistory(account, period),
    staleTime: 5 * 60_000,
  });

  if (q.isLoading) {
    return <div className="card text-sm text-text-muted">Loading portfolio value history…</div>;
  }
  if (q.isError || !q.data || q.data.length === 0) {
    return (
      <div className="card text-sm text-text-muted">
        Not enough price history to build the portfolio-value timeline yet —
        refresh prices and try again.
      </div>
    );
  }

  const data = q.data;
  const latest = data[data.length - 1];
  const first = data[0];
  const totalChange = latest.total_cad - first.net_deposits_cad;
  const trendUp = totalChange >= 0;

  return (
    <div className="card">
      <div className="flex items-baseline justify-between flex-wrap gap-3 mb-3">
        <div>
          <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider">
            Portfolio Value
          </h3>
          <div className="num text-2xl font-semibold">{fmt.money(latest.total_cad, "CAD")}</div>
        </div>
        <div className="text-right">
          <div className="text-xs text-text-muted">vs. net deposits</div>
          <div
            className={`num text-base font-medium ${trendUp ? "text-gain" : "text-loss"}`}
          >
            {trendUp ? "+" : ""}
            {fmt.moneyShort(totalChange)} CAD
          </div>
        </div>
      </div>

      <div className="h-64">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="pv-area" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="rgb(var(--accent-rgb))" stopOpacity={0.4} />
                <stop offset="100%" stopColor="rgb(var(--accent-rgb))" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1f2937" strokeDasharray="2 4" />
            <XAxis
              dataKey="date"
              stroke="#6B7280"
              fontSize={11}
              tickFormatter={(d) =>
                new Date(d).toLocaleDateString("en-CA", { month: "short", year: "2-digit" })
              }
              minTickGap={36}
            />
            <YAxis
              stroke="#6B7280"
              fontSize={11}
              tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
              domain={["auto", "auto"]}
            />
            <Tooltip
              contentStyle={{
                background: "#111827",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: "8px",
              }}
              labelFormatter={(d) => fmt.date(d as string)}
              formatter={(value: number, name: string) => {
                const labels: Record<string, string> = {
                  total_cad: "Portfolio Value",
                  net_deposits_cad: "Net Deposits",
                };
                return [fmt.money(value, "CAD"), labels[name] ?? name];
              }}
            />
            <Area
              type="monotone"
              dataKey="total_cad"
              name="total_cad"
              stroke="rgb(var(--accent-rgb))"
              strokeWidth={1.8}
              fill="url(#pv-area)"
            />
            <Line
              type="monotone"
              dataKey="net_deposits_cad"
              name="net_deposits_cad"
              stroke="#6B7280"
              strokeDasharray="3 3"
              strokeWidth={1.2}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-2 text-xs text-text-muted">
        Weekly reconstruction. Solid: total portfolio value (holdings at week-close + cash).
        Dashed grey: cumulative net deposits — the gap is your gain/loss.
      </p>
    </div>
  );
}
