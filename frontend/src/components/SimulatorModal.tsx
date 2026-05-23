/**
 * What-If Simulator — modal with three modes (buy / sell / lump-sum).
 * All calculations are server-side; this is a form + results pane. Results
 * are ephemeral — nothing is written to the database.
 */
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { X, FlaskConical } from "lucide-react";
import clsx from "clsx";
import { api } from "../api";
import type { AccountType, Holding, SimulationResult } from "../types";
import { ModalPortal } from "./ModalPortal";

type Mode = "buy" | "sell" | "lump_sum";

const ACCOUNT_OPTIONS: AccountType[] = ["Margin", "TFSA", "RRSP", "RESP"];

interface Props {
  holdings: Holding[];
  onClose: () => void;
}

export default function SimulatorModal({ holdings, onClose }: Props) {
  const [mode, setMode] = useState<Mode>("buy");
  const [ticker, setTicker] = useState(holdings[0]?.ticker || "");
  const [accountType, setAccountType] = useState<AccountType>(
    (holdings[0]?.account_type as AccountType) || "Margin",
  );
  const [shares, setShares] = useState<number>(1);
  const [amount, setAmount] = useState<number>(1000);
  const [investDate, setInvestDate] = useState<string>(
    new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
  );
  const [result, setResult] = useState<SimulationResult | null>(null);

  // In Sell mode, restrict the account choices to accounts that actually
  // hold this ticker — you can't sell what you don't own.
  const accountChoices = useMemo<AccountType[]>(() => {
    if (mode !== "sell") return ACCOUNT_OPTIONS;
    return holdings
      .filter((h) => h.ticker === ticker)
      .map((h) => h.account_type as AccountType);
  }, [mode, holdings, ticker]);

  const run = useMutation({
    mutationFn: async (): Promise<SimulationResult> => {
      if (mode === "buy") return api.simulateBuy(ticker, shares, accountType);
      if (mode === "sell") return api.simulateSell(ticker, shares, accountType);
      return api.simulateLumpSum(ticker, amount, investDate);
    },
    onSuccess: (r) => setResult(r),
  });

  return (
    <ModalPortal onClose={onClose} labelledBy="simulator-modal-title">
      <div className="min-h-full flex items-center justify-center px-4 py-[60px]">
        <div
          className="card w-[34rem] max-w-[92vw] max-h-[calc(100vh-120px)] overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
        <div className="flex items-center justify-between mb-4">
          <h2 id="simulator-modal-title" className="text-lg font-semibold inline-flex items-center gap-2">
            <FlaskConical size={18} /> What-If Simulator
          </h2>
          <button className="text-text-muted hover:text-text-primary" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="flex gap-1 mb-4 bg-white/[0.04] p-1 rounded-full">
          {(["buy", "sell", "lump_sum"] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => {
                setMode(m);
                setResult(null);
              }}
              className={clsx(
                "flex-1 px-3 py-1.5 text-xs font-medium rounded-full transition-colors",
                m === mode
                  ? "bg-accent text-white"
                  : "text-text-muted hover:text-text-primary",
              )}
            >
              {m === "buy" ? "Buy" : m === "sell" ? "Sell" : "Lump-sum"}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          <Field label="Ticker">
            {mode === "lump_sum" ? (
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                placeholder="e.g. VEQT.TO"
                className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-full"
              />
            ) : (
              <select
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-full"
              >
                {holdings.map((h) => (
                  <option
                    key={`${h.ticker}-${h.account_type}`}
                    value={h.ticker}
                  >
                    {h.ticker} ({h.account_type})
                  </option>
                ))}
              </select>
            )}
          </Field>

          {mode !== "lump_sum" && (
            <>
              <Field label="Account">
                <select
                  value={accountType}
                  onChange={(e) => setAccountType(e.target.value as AccountType)}
                  className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-full"
                >
                  {accountChoices.map((a) => (
                    <option key={a} value={a}>{a}</option>
                  ))}
                </select>
              </Field>
              <Field label="Shares">
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={shares}
                  onChange={(e) => setShares(parseFloat(e.target.value || "0"))}
                  className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-full"
                />
              </Field>
            </>
          )}

          {mode === "lump_sum" && (
            <>
              <Field label="Amount (CAD)">
                <input
                  type="number"
                  min={0}
                  step={100}
                  value={amount}
                  onChange={(e) => setAmount(parseFloat(e.target.value || "0"))}
                  className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-full"
                />
              </Field>
              <Field label="Investment date">
                <input
                  type="date"
                  value={investDate}
                  onChange={(e) => setInvestDate(e.target.value)}
                  className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-full"
                />
              </Field>
            </>
          )}

          <button
            className="btn-primary w-full"
            onClick={() => run.mutate()}
            disabled={run.isPending || !ticker}
          >
            {run.isPending ? "Simulating…" : "Run simulation"}
          </button>
        </div>

        {result && (
          <div className="mt-5 pt-5 border-t border-border">
            <div className="text-sm font-semibold mb-2">{result.description}</div>
            <ul className="text-xs text-text-muted space-y-1 list-disc list-inside">
              {result.detail_lines.map((line, i) => <li key={i}>{line}</li>)}
            </ul>
            {result.tax_estimate_cad !== null && result.tax_estimate_cad > 0 && (
              <p className="mt-3 text-xs text-yellow-400">
                Tax estimate uses your saved marginal rate. Adjust in Settings if needed.
              </p>
            )}
          </div>
        )}
        </div>
      </div>
    </ModalPortal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="label-muted mb-1">{label}</div>
      {children}
    </div>
  );
}
