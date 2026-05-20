/**
 * Performance Attribution chart — one horizontal bar per holding, scaled by
 * contribution_pct. Reads /api/attribution. Respects the global time period.
 */
import { useQuery } from "@tanstack/react-query";
import { api, fmt } from "../api";
import { usePeriod } from "./PeriodContext";

interface Props {
  account: string;
}

export default function AttributionPanel({ account }: Props) {
  const { period } = usePeriod();
  const q = useQuery({
    queryKey: ["attribution", account, period],
    queryFn: () => api.attribution(account, period),
    staleTime: 60_000,
  });

  if (q.isLoading) {
    return <div className="card text-sm text-text-muted">Loading attribution…</div>;
  }
  if (q.isError || !q.data || q.data.rows.length === 0) {
    return (
      <div className="card text-sm text-text-muted">
        Not enough data to attribute returns yet — try refreshing prices or pick a longer period.
      </div>
    );
  }

  const data = q.data;
  // Scale bars: largest absolute value sets 100% of bar width.
  const maxAbs = Math.max(...data.rows.map((r) => Math.abs(r.contribution_pct)), 0.001);
  const barColor = (pct: number) => (pct >= 0 ? "rgb(16, 185, 129)" : "rgb(239, 68, 68)");

  return (
    <div className="card space-y-3">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div>
          <div className="text-xs text-text-muted">Total contribution</div>
          <div
            className={`num text-xl font-semibold ${
              data.total_return_pct >= 0 ? "text-gain" : "text-loss"
            }`}
          >
            {fmt.pct(data.total_return_pct)}
          </div>
        </div>
        <div className="text-xs text-text-muted text-right">
          {data.top_contributor && (
            <div>
              Top: <span className="text-gain font-medium">{data.top_contributor}</span>{" "}
              ({fmt.pct(data.top_contributor_pct)})
            </div>
          )}
          {data.biggest_drag && (
            <div>
              Drag: <span className="text-loss font-medium">{data.biggest_drag}</span>{" "}
              ({fmt.pct(data.biggest_drag_pct)})
            </div>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        {data.rows.map((r) => {
          const pct = r.contribution_pct;
          const width = (Math.abs(pct) / maxAbs) * 50; // bar takes max 50% from center
          return (
            <div
              key={`${r.ticker}-${r.account_type}`}
              className="flex items-center gap-3 text-xs"
              title={`${r.ticker} (${r.account_type}): ${fmt.money(r.gain_cad, "CAD")} (${fmt.pct(
                pct,
              )} of portfolio)`}
            >
              <div className="w-32 truncate text-text-primary">
                {r.ticker} <span className="text-text-muted">{r.account_type}</span>
              </div>
              <div className="flex-1 relative h-4">
                {/* Center line for the zero axis */}
                <div className="absolute left-1/2 top-0 bottom-0 w-px bg-text-muted/30" />
                {/* Bar */}
                <div
                  className="absolute top-0 bottom-0 rounded-sm"
                  style={{
                    [pct >= 0 ? "left" : "right"]: "50%",
                    width: `${width}%`,
                    background: barColor(pct),
                  }}
                />
              </div>
              <div
                className={`w-20 text-right num ${pct >= 0 ? "text-gain" : "text-loss"}`}
              >
                {fmt.pct(pct)}
              </div>
              <div className="w-24 text-right num text-text-muted">
                {fmt.moneyShort(r.gain_cad)}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-text-muted pt-2 border-t border-border">
        Contribution = gain in CAD ÷ portfolio value at the start of the period (
        {fmt.money(data.portfolio_period_start_cad, "CAD")}).
      </p>
    </div>
  );
}
