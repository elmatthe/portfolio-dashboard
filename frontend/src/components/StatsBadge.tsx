import type { PortfolioStats } from "../types";
import { fmt } from "../api";

interface Props {
  stats: PortfolioStats;
}

export default function StatsTable({ stats }: Props) {
  const rows: { label: string; value: string }[] = [
    { label: "Max Periods/Year", value: String(stats.max_periods_per_year) },
    { label: "Risk-Free Rate", value: fmt.pct(stats.risk_free_rate * 100) },
    { label: "Observations", value: String(stats.observations) },
    { label: "Avg Period Return", value: fmt.pct(stats.avg_period_return * 100, 3) },
    { label: "Std Dev (Period)", value: fmt.pct(stats.std_dev_period * 100, 3) },
    { label: "Total Return", value: fmt.pct(stats.total_return * 100) },
    { label: "Annualized Return", value: fmt.pct(stats.annualized_return * 100) },
    { label: "Annualized Volatility", value: fmt.pct(stats.annualized_volatility * 100) },
    { label: "Sharpe Ratio", value: stats.sharpe_ratio.toFixed(2) },
  ];

  return (
    <div className="card">
      <table className="w-full text-sm">
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={r.label}>
              <td className="py-2 text-text-muted">{r.label}</td>
              <td className="py-2 text-right num font-medium">{r.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-text-muted">
        Based on weekly returns. Risk-free rate sourced from Bank of Canada overnight rate.
      </p>
    </div>
  );
}
