import clsx from "clsx";
import type { CapitalGainsReport } from "../types";
import { fmt } from "../api";

interface Props {
  report: CapitalGainsReport;
}

export default function CapitalGainsTable({ report }: Props) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-text-muted text-left">
            <th className="pb-3 pr-4 font-medium">Date</th>
            <th className="pb-3 px-3 font-medium">Security</th>
            <th className="pb-3 px-3 font-medium">Account</th>
            <th className="pb-3 px-3 font-medium text-right">Shares</th>
            <th className="pb-3 px-3 font-medium text-right">Sale Price</th>
            <th className="pb-3 px-3 font-medium text-right">ACB/Share</th>
            <th className="pb-3 px-3 font-medium text-right">Gain/Share</th>
            <th className="pb-3 px-3 font-medium text-right">Total Gain</th>
            <th className="pb-3 pl-3 font-medium">Taxable?</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {report.realized_gains.map((g, i) => (
            <tr
              key={i}
              className={clsx(g.total_gain >= 0 ? "bg-gain/[0.03]" : "bg-loss/[0.03]")}
            >
              <td className="py-2.5 pr-4">{fmt.date(g.transaction_date)}</td>
              <td className="py-2.5 px-3 font-medium">{g.ticker}</td>
              <td className="py-2.5 px-3">{g.account_type}</td>
              <td className="py-2.5 px-3 text-right num">{g.shares_sold}</td>
              <td className="py-2.5 px-3 text-right num">{fmt.money(g.sale_price, g.currency)}</td>
              <td className="py-2.5 px-3 text-right num">{fmt.money(g.acb_per_share, g.currency)}</td>
              <td
                className={clsx(
                  "py-2.5 px-3 text-right num",
                  g.gain_per_share >= 0 ? "text-gain" : "text-loss",
                )}
              >
                {fmt.money(g.gain_per_share, g.currency)}
              </td>
              <td
                className={clsx(
                  "py-2.5 px-3 text-right num font-medium",
                  g.total_gain >= 0 ? "text-gain" : "text-loss",
                )}
              >
                {fmt.money(g.total_gain, g.currency)}
              </td>
              <td className="py-2.5 pl-3">
                {g.taxable ? (
                  <span className="badge bg-yellow-500/15 text-yellow-300">Taxable</span>
                ) : (
                  <span className="badge bg-emerald-500/15 text-emerald-300">Non-Taxable</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-border">
            <td colSpan={7} className="pt-4 text-right font-medium">
              Total Taxable Gain:
            </td>
            <td
              className={clsx(
                "pt-4 px-3 text-right num font-semibold",
                report.total_taxable_gain >= 0 ? "text-gain" : "text-loss",
              )}
            >
              {fmt.money(report.total_taxable_gain, "CAD")}
            </td>
            <td className="pt-4" />
          </tr>
          <tr>
            <td colSpan={7} className="pt-1 text-right font-medium">
              Total Non-Taxable (Registered):
            </td>
            <td className="pt-1 px-3 text-right num font-semibold">
              {fmt.money(report.total_non_taxable_gain, "CAD")}
            </td>
            <td />
          </tr>
          {report.total_superficial_loss_denied > 0 && (
            <tr>
              <td colSpan={7} className="pt-1 text-right text-yellow-400 font-medium">
                Superficial Loss Denied:
              </td>
              <td className="pt-1 px-3 text-right num text-yellow-400">
                {fmt.money(report.total_superficial_loss_denied, "CAD")}
              </td>
              <td />
            </tr>
          )}
        </tfoot>
      </table>
      <p className="mt-4 text-xs text-text-muted">
        Note: a 50% inclusion rate applies to taxable capital gains per CRA. Registered accounts
        (TFSA, RRSP, RESP) are not subject to capital gains tax in the usual sense.
      </p>
    </div>
  );
}
