/**
 * Card shown on the TFSA tab — current contribution room remaining, a usage
 * bar, current-year status, and an over-contribution warning when applicable.
 * If birth_year + resident_since aren't set in Settings the card prompts the
 * user to fill them in.
 */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink } from "lucide-react";
import clsx from "clsx";
import { api, fmt } from "../api";

interface Props {
  onOpenSettings: () => void;
}

export default function TfsaRoomCard({ onOpenSettings }: Props) {
  const q = useQuery({ queryKey: ["tfsa-room"], queryFn: api.tfsaRoom });

  if (q.isLoading) {
    return <div className="card text-sm text-text-muted">Loading TFSA contribution room…</div>;
  }
  if (q.isError || !q.data) {
    return (
      <div className="card text-sm text-text-muted">
        Couldn't compute TFSA room ({(q.error as Error)?.message ?? "unknown error"}).
      </div>
    );
  }
  const r = q.data;
  const needsSettings = r.missing_settings.length > 0;

  if (needsSettings) {
    return (
      <div className="card border-l-4 border-l-yellow-400">
        <div className="flex items-center gap-3">
          <AlertTriangle className="text-yellow-400" size={20} />
          <div className="flex-1">
            <div className="font-medium">TFSA settings required</div>
            <div className="text-xs text-text-muted mt-1">
              Set your birth year and the year you became a Canadian resident in Settings
              to calculate your contribution room.
            </div>
          </div>
          <button className="btn-primary" onClick={onOpenSettings}>
            Open Settings
          </button>
        </div>
      </div>
    );
  }

  const currentUsedPct =
    r.current_year_limit > 0
      ? Math.min(100, (r.contributions_this_year / r.current_year_limit) * 100)
      : 0;
  const totalUsedPct =
    r.total_room_accumulated > 0
      ? Math.min(100, (r.total_contributions / r.total_room_accumulated) * 100)
      : 0;

  return (
    <div className="space-y-4">
      {r.over_contributed && (
        <div className="card border-l-4 border-l-loss bg-loss/[0.06]">
          <div className="flex items-start gap-3">
            <AlertTriangle className="text-loss flex-shrink-0 mt-0.5" size={20} />
            <div>
              <div className="font-semibold text-loss">
                Over-contributed by {fmt.moneyShort(r.over_contribution_amount)}
              </div>
              <p className="text-xs text-text-muted mt-1">
                The CRA charges a 1%-per-month penalty on over-contributions until the
                excess is withdrawn. Consider withdrawing as soon as possible.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="flex items-baseline justify-between mb-1">
          <div className="label-muted">Room Remaining</div>
          <div className="text-xs text-text-muted">
            Eligible from {r.eligibility_start_year}
          </div>
        </div>
        <div
          className={clsx(
            "num text-3xl font-semibold",
            r.over_contributed ? "text-loss" : "text-text-primary",
          )}
        >
          {fmt.money(r.contribution_room_remaining, "CAD")}
        </div>
        <p className="text-sm text-text-muted mt-1">
          You have {fmt.money(r.contribution_room_remaining, "CAD")} of TFSA room remaining.
        </p>

        <div className="mt-4">
          <div className="flex justify-between text-xs text-text-muted mb-1">
            <span>Total contributions used</span>
            <span className="num">
              {fmt.moneyShort(r.total_contributions)} of {fmt.moneyShort(r.total_room_accumulated)}
            </span>
          </div>
          <div className="h-2 rounded-full overflow-hidden bg-white/5">
            <div
              className={clsx("h-full transition-all", r.over_contributed ? "bg-loss" : "bg-accent")}
              style={{ width: `${totalUsedPct}%` }}
            />
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
          <div>
            <div className="label-muted">{new Date().getFullYear()} contributions</div>
            <div className="num font-medium">
              {fmt.money(r.contributions_this_year, "CAD")}{" "}
              <span className="text-xs text-text-muted">
                of {fmt.money(r.current_year_limit, "CAD")}
              </span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden bg-white/5 mt-1">
              <div className="h-full bg-accent" style={{ width: `${currentUsedPct}%` }} />
            </div>
          </div>
          <div>
            <div className="label-muted">Withdrawals returned this year</div>
            <div className="num font-medium">
              {fmt.money(r.withdrawals_last_year_added_back, "CAD")}
            </div>
            <div className="text-xs text-text-muted">
              From last calendar year's withdrawals.
            </div>
          </div>
        </div>

        <details className="mt-4">
          <summary className="text-xs text-text-muted cursor-pointer">Year-by-year breakdown</summary>
          <table className="w-full text-xs mt-2">
            <thead>
              <tr className="text-text-muted text-left">
                <th className="pb-1 font-medium">Year</th>
                <th className="pb-1 font-medium text-right">Limit</th>
                <th className="pb-1 font-medium text-right">Contributions</th>
                <th className="pb-1 font-medium text-right">Withdrawals</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {r.annual_breakdown.map((row) => (
                <tr key={row.year}>
                  <td className="py-1">{row.year}</td>
                  <td className="py-1 text-right num">{fmt.moneyShort(row.annual_limit_cad)}</td>
                  <td className="py-1 text-right num">{fmt.moneyShort(row.contributions_cad)}</td>
                  <td className="py-1 text-right num">{fmt.moneyShort(row.withdrawals_cad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>

        <p className="mt-4 text-xs text-text-muted">
          CRA limit schedule embedded in the app. Verify against{" "}
          <a
            className="text-accent inline-flex items-center gap-1"
            href="https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/tax-free-savings-account/contributions.html"
            target="_blank"
            rel="noreferrer"
          >
            CRA's official page <ExternalLink size={11} />
          </a>{" "}
          for the current tax year.
        </p>
      </div>
    </div>
  );
}
