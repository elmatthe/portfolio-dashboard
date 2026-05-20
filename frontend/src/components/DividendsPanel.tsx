import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CalendarDays } from "lucide-react";
import { api, fmt } from "../api";
import { usePeriod } from "./PeriodContext";

interface Props {
  account: string;
}

export default function DividendsPanel({ account }: Props) {
  const { period } = usePeriod();
  const q = useQuery({
    queryKey: ["dividends", account, period],
    queryFn: () => api.dividends(account, period),
    staleTime: 60_000,
  });

  if (q.isLoading) {
    return <div className="card text-sm text-text-muted">Loading dividend data…</div>;
  }
  if (q.isError || !q.data) {
    return null;
  }
  const data = q.data;
  if (data.monthly.length === 0 && data.by_holding.length === 0) {
    return null; // no dividends in this account
  }

  const monthData = data.monthly.map((m) => ({
    month: m.month,
    amount: m.amount_cad,
    label: new Date(m.month + "-01").toLocaleDateString("en-CA", { month: "short", year: "2-digit" }),
  }));

  const showPeriodCard = period !== "all";
  return (
    <div className="space-y-4">
      <div
        className={`grid grid-cols-1 gap-4 ${
          showPeriodCard ? "lg:grid-cols-4" : "lg:grid-cols-3"
        }`}
      >
        {showPeriodCard && (
          <SummaryCard
            label={`Period (${period.toUpperCase()}) dividends`}
            value={data.period_total_cad}
          />
        )}
        <SummaryCard label="Trailing 12 months" value={data.trailing_12mo_cad} />
        <SummaryCard label="Annualised income" value={data.annual_total_cad} />
        <SummaryCard
          label="Holdings paying dividends"
          value={data.by_holding.length}
          formatter={(v) => String(v)}
        />
      </div>

      {monthData.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider mb-3">
            Monthly Income
          </h3>
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={monthData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#1f2937" strokeDasharray="2 4" />
                <XAxis dataKey="label" stroke="#6B7280" fontSize={11} minTickGap={20} />
                <YAxis
                  stroke="#6B7280"
                  fontSize={11}
                  tickFormatter={(v) => `$${v.toFixed(0)}`}
                />
                <Tooltip
                  contentStyle={{
                    background: "#111827",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: "8px",
                  }}
                  formatter={(v: number) => [fmt.money(v, "CAD"), "Income"]}
                  labelFormatter={(l) => l as string}
                />
                <Bar dataKey="amount" fill="rgb(var(--accent-rgb))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {data.upcoming.length > 0 && (
          <div className="card">
            <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider mb-3 flex items-center gap-2">
              <CalendarDays size={14} /> Upcoming payments
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-text-muted text-left">
                  <th className="pb-2 font-medium">Date</th>
                  <th className="pb-2 font-medium">Security</th>
                  <th className="pb-2 font-medium text-right">Est. amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.upcoming.map((u) => (
                  <tr key={u.ticker + u.next_date}>
                    <td className="py-2">{fmt.date(u.next_date)}</td>
                    <td className="py-2 font-medium">
                      {u.ticker}
                      {u.security_name && (
                        <span className="text-xs text-text-muted ml-2 truncate">
                          {u.security_name}
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-right num">{fmt.moneyShort(u.estimated_amount_cad)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-text-muted">
              Projected from each ticker's historical payment cadence (median gap).
            </p>
          </div>
        )}

        {data.by_holding.length > 0 && (
          <div className="card">
            <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider mb-3">
              Yield on Cost
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-text-muted text-left">
                  <th className="pb-2 font-medium">Security</th>
                  <th className="pb-2 font-medium text-right">Annual</th>
                  <th className="pb-2 font-medium text-right">Yield on cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.by_holding.map((r) => (
                  <tr key={r.ticker + r.account_type}>
                    <td className="py-2 font-medium">
                      {r.ticker}
                      <span className="text-xs text-text-muted ml-2">{r.account_type}</span>
                    </td>
                    <td className="py-2 text-right num">{fmt.moneyShort(r.annual_dividends_cad)}</td>
                    <td className="py-2 text-right num text-gain">
                      {r.yield_on_cost_pct.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-text-muted">
              Annual dividends ÷ total cost basis (CAD-equivalent at the live rate).
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  formatter,
}: {
  label: string;
  value: number;
  formatter?: (v: number) => string;
}) {
  return (
    <div className="card">
      <div className="label-muted mb-1">{label}</div>
      <div className="num text-2xl font-semibold">
        {formatter ? formatter(value) : fmt.money(value, "CAD")}
      </div>
    </div>
  );
}
