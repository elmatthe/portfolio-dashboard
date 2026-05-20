/**
 * Rebalancing Advisor — three-step UI:
 *   1. Edit target % per holding (defaults to current allocation).
 *   2. Pick "Rebalance existing" or "Invest new money $___".
 *   3. Inspect generated BUY/SELL instructions.
 *
 * All calculations are server-side via POST /api/rebalance; this panel is
 * just the form + result viewer.
 */
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpFromLine, Sigma } from "lucide-react";
import clsx from "clsx";
import { api, fmt } from "../api";
import type { Holding, RebalanceResponse, RebalanceTarget } from "../types";

interface Props {
  holdings: Holding[];
  totalEquityCad: number;
}

export default function RebalancePanel({ holdings, totalEquityCad }: Props) {
  // Initial targets default to each holding's current weight, rounded so the
  // user can edit cleanly. Holdings with no weight (rare) get an even split.
  const initial = useMemo<RebalanceTarget[]>(() => {
    return holdings.map((h) => ({
      ticker: h.ticker,
      account_type: h.account_type,
      target_pct: Math.round((h.investment_weight_pct ?? 0) * 100) / 100,
    }));
  }, [holdings]);
  const [targets, setTargets] = useState<RebalanceTarget[]>(initial);
  const [mode, setMode] = useState<"rebalance" | "new_money">("new_money");
  const [newMoney, setNewMoney] = useState<number>(1000);
  const [result, setResult] = useState<RebalanceResponse | null>(null);

  // Reset to current weights if the holdings list changes (e.g. profile switch).
  if (targets.length !== initial.length) {
    setTargets(initial);
  }

  const totalPct = targets.reduce((s, t) => s + t.target_pct, 0);
  const totalValid = Math.abs(totalPct - 100) < 0.5;

  const setTarget = (idx: number, value: number) => {
    setTargets(targets.map((t, i) => (i === idx ? { ...t, target_pct: value } : t)));
  };

  const submit = useMutation({
    mutationFn: () =>
      api.rebalance({
        targets,
        mode,
        new_money_cad: mode === "new_money" ? newMoney : 0,
      }),
    onSuccess: (r) => setResult(r),
  });

  if (holdings.length === 0) {
    return (
      <div className="card text-sm text-text-muted">
        Import some holdings first — the rebalancing advisor needs an existing portfolio to work from.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Targets */}
      <div className="card">
        <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider mb-3">
          1. Set targets
        </h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-text-muted text-left">
              <th className="pb-2 font-medium">Security</th>
              <th className="pb-2 font-medium text-right">Current %</th>
              <th className="pb-2 font-medium text-right">Target %</th>
              <th className="pb-2 font-medium text-right">Drift</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {targets.map((t, i) => {
              const h = holdings.find(
                (x) => x.ticker === t.ticker && x.account_type === t.account_type,
              );
              const currentPct = h?.investment_weight_pct ?? 0;
              const drift = t.target_pct - currentPct;
              return (
                <tr key={`${t.ticker}-${t.account_type}`}>
                  <td className="py-2">
                    {t.ticker} <span className="text-xs text-text-muted">{t.account_type}</span>
                  </td>
                  <td className="py-2 text-right num text-text-muted">
                    {currentPct.toFixed(2)}%
                  </td>
                  <td className="py-2 text-right">
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      max={100}
                      value={t.target_pct}
                      onChange={(e) => setTarget(i, parseFloat(e.target.value || "0"))}
                      className="bg-white/5 border border-border rounded-md px-2 py-1 text-sm w-20 text-right num"
                    />
                    <span className="text-xs text-text-muted ml-1">%</span>
                  </td>
                  <td
                    className={clsx(
                      "py-2 text-right num text-xs",
                      Math.abs(drift) > 5
                        ? "text-loss"
                        : Math.abs(drift) > 1
                        ? "text-yellow-400"
                        : "text-text-muted",
                    )}
                  >
                    {drift >= 0 ? "+" : ""}
                    {drift.toFixed(2)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-border">
              <td className="pt-2 font-medium">
                <Sigma size={12} className="inline mr-1" /> Total
              </td>
              <td className="pt-2" />
              <td
                className={clsx(
                  "pt-2 text-right num font-medium",
                  totalValid ? "text-gain" : "text-loss",
                )}
              >
                {totalPct.toFixed(2)}%
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Mode */}
      <div className="card">
        <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider mb-3">
          2. Choose mode
        </h3>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              checked={mode === "new_money"}
              onChange={() => setMode("new_money")}
              className="accent-accent"
            />
            Invest new money
          </label>
          {mode === "new_money" && (
            <span className="inline-flex items-center gap-1">
              $
              <input
                type="number"
                min={0}
                step={100}
                value={newMoney}
                onChange={(e) => setNewMoney(parseFloat(e.target.value || "0"))}
                className="bg-white/5 border border-border rounded-md px-2 py-1 text-sm w-32 text-right num"
              />
              <span className="text-xs text-text-muted">CAD</span>
            </span>
          )}
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              checked={mode === "rebalance"}
              onChange={() => setMode("rebalance")}
              className="accent-accent"
            />
            Rebalance existing holdings (allow sells)
          </label>
        </div>
        <button
          className="btn-primary mt-4"
          onClick={() => submit.mutate()}
          disabled={!totalValid || submit.isPending || (mode === "new_money" && newMoney <= 0)}
        >
          {submit.isPending ? "Calculating…" : "Generate instructions"}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div className="card">
          <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider mb-3">
            3. Suggested instructions
          </h3>
          {result.warnings.length > 0 && (
            <div className="mb-3 space-y-1">
              {result.warnings.map((w, i) => (
                <div key={i} className="text-xs text-yellow-400">⚠️ {w}</div>
              ))}
            </div>
          )}
          {result.actions.length === 0 ? (
            <p className="text-sm text-text-muted">
              No actions needed — your portfolio is already on target.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-text-muted text-left">
                  <th className="pb-2 font-medium">Action</th>
                  <th className="pb-2 font-medium">Security</th>
                  <th className="pb-2 font-medium text-right">Shares</th>
                  <th className="pb-2 font-medium text-right">Price</th>
                  <th className="pb-2 font-medium text-right">Cost (CAD)</th>
                  <th className="pb-2 font-medium text-right">Resulting %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {result.actions.map((a, i) => (
                  <tr key={i}>
                    <td
                      className={clsx(
                        "py-2 font-medium inline-flex items-center gap-1",
                        a.action === "BUY" ? "text-gain" : "text-loss",
                      )}
                    >
                      {a.action === "BUY" ? <ArrowDownToLine size={14} /> : <ArrowUpFromLine size={14} />}
                      {a.action}
                    </td>
                    <td className="py-2">
                      {a.ticker} <span className="text-xs text-text-muted">{a.account_type}</span>
                    </td>
                    <td className="py-2 text-right num">{a.shares}</td>
                    <td className="py-2 text-right num">{fmt.money(a.price, a.currency)}</td>
                    <td className="py-2 text-right num">{fmt.money(a.cost_cad, "CAD")}</td>
                    <td className="py-2 text-right num">{a.resulting_pct.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.note && (
            <p className="mt-3 text-xs text-text-muted">{result.note}</p>
          )}
        </div>
      )}
    </div>
  );
}
