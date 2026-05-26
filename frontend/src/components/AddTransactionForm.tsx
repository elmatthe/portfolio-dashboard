import { useState, useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { api, fmt } from "../api";
import type { Transaction } from "../types";

interface Props {
  onSuccess: (tx: Transaction) => void;
  onCancel: () => void;
  editTx?: Transaction | null;
}

type ActionType = "BUY" | "SELL" | "DIVIDEND" | "DEPOSIT" | "WITHDRAWAL" | "TRANSFER" | "FEE";

const ACTIONS: { value: ActionType; label: string }[] = [
  { value: "BUY", label: "Buy" },
  { value: "SELL", label: "Sell" },
  { value: "DIVIDEND", label: "Dividend" },
  { value: "DEPOSIT", label: "Deposit" },
  { value: "WITHDRAWAL", label: "Withdrawal" },
  { value: "TRANSFER", label: "Transfer" },
  { value: "FEE", label: "Fee" },
];

const CURRENCIES = ["CAD", "USD", "GBP", "EUR", "JPY", "AUD", "CHF", "HKD", "SEK", "NOK"];
const ACCOUNT_TYPES = ["TFSA", "RRSP", "RESP", "Margin", "Non-Registered"];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function AddTransactionForm({ onSuccess, onCancel, editTx }: Props) {
  const isEdit = !!editTx;

  const [action, setAction] = useState<ActionType>(editTx?.action as ActionType || "BUY");
  const [transactionDate, setTransactionDate] = useState(editTx?.transaction_date || today());
  const [settlementDate, setSettlementDate] = useState(editTx?.settlement_date || "");
  const [ticker, setTicker] = useState(editTx?.resolved_ticker || editTx?.raw_symbol || "");
  const [description, setDescription] = useState(editTx?.description || "");
  const [quantity, setQuantity] = useState(editTx?.quantity?.toString() || "");
  const [price, setPrice] = useState(editTx?.price?.toString() || "");
  const [currency, setCurrency] = useState<string>(editTx?.currency || "CAD");
  const [commission, setCommission] = useState(editTx?.commission?.toString() || "0");
  const [accountType, setAccountType] = useState<string>(editTx?.account_type || "TFSA");
  const [accountNumber, setAccountNumber] = useState(editTx?.account_number || "");
  const [isin, setIsin] = useState(editTx?.isin || "");
  const [notes, setNotes] = useState(editTx?.notes || "");
  const [netAmount, setNetAmount] = useState(editTx?.net_amount?.toString() || "");

  const [preview, setPreview] = useState<{
    gross_amount: number; net_amount: number; fx_rate_to_cad: number; net_cad: number;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState("");

  const [showExtras, setShowExtras] = useState(!!editTx?.isin || !!editTx?.notes);
  const [heldQty, setHeldQty] = useState<number | null>(null);
  const [heldLoading, setHeldLoading] = useState(false);

  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const needsTicker = ["BUY", "SELL", "DIVIDEND"].includes(action);
  const needsQtyPrice = ["BUY", "SELL"].includes(action);

  useEffect(() => {
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(async () => {
      if (!transactionDate) return;
      const params: Record<string, string> = {
        transaction_date: transactionDate,
        currency,
        quantity: quantity || "0",
        price: price || "0",
        commission: commission || "0",
        action,
      };
      setPreviewLoading(true);
      try {
        const result = await api.previewManualTransaction(params);
        setPreview(result);
      } catch {
        setPreview(null);
      } finally {
        setPreviewLoading(false);
      }
    }, 500);
    return () => { if (previewTimer.current) clearTimeout(previewTimer.current); };
  }, [transactionDate, currency, quantity, price, commission, action]);

  useEffect(() => {
    if (action !== "SELL" || !ticker.trim() || !accountType) {
      setHeldQty(null);
      return;
    }
    setHeldLoading(true);
    api.heldPosition(ticker.trim().toUpperCase(), accountType)
      .then((r) => setHeldQty(r.held_quantity))
      .catch(() => setHeldQty(null))
      .finally(() => setHeldLoading(false));
  }, [action, ticker, accountType]);

  const overSell = action === "SELL" && heldQty !== null && parseFloat(quantity || "0") > heldQty;

  function validate(): boolean {
    const e: Record<string, string> = {};
    if (!transactionDate) e.transactionDate = "Required";
    if (!action) e.action = "Required";
    if (needsTicker && !ticker.trim()) e.ticker = "Required for this action";
    if (needsQtyPrice && (!quantity || parseFloat(quantity) <= 0)) e.quantity = "Must be > 0";
    if (needsQtyPrice && (!price || parseFloat(price) <= 0)) e.price = "Must be > 0";
    if (parseFloat(commission || "0") < 0) e.commission = "Must be >= 0";
    if (!accountType) e.accountType = "Required";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    setServerError("");
    if (!validate()) return;

    const body: Record<string, unknown> = {
      transaction_date: transactionDate,
      action,
      ticker: needsTicker ? ticker.trim().toUpperCase() : null,
      quantity: parseFloat(quantity || "0"),
      price: parseFloat(price || "0"),
      currency,
      commission: parseFloat(commission || "0"),
      account_type: accountType,
      account_number: accountNumber || undefined,
      settlement_date: settlementDate || null,
      isin: isin || null,
      notes: notes || null,
      description: description || null,
      net_amount: !needsQtyPrice ? parseFloat(netAmount || "0") : undefined,
    };

    setSaving(true);
    try {
      let result: Transaction;
      if (isEdit && editTx) {
        result = await api.updateManualTransaction(editTx.hash, body);
      } else {
        result = await api.createManualTransaction(body);
      }
      onSuccess(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      if (msg.includes("Duplicate") || msg.includes("409")) {
        setServerError("This transaction already exists (matched an imported record).");
      } else if (msg.includes("exceeds") || msg.includes("400")) {
        setServerError("Sell quantity exceeds your held position.");
      } else {
        setServerError(msg);
      }
    } finally {
      setSaving(false);
    }
  }

  const isFutureDate = transactionDate > today();

  return (
    <form onSubmit={handleSubmit} className="space-y-4 text-sm">
      {serverError && (
        <div className="bg-loss/10 border border-loss/30 text-loss rounded-lg px-3 py-2 text-xs">
          {serverError}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-text-muted text-xs mb-1">Date *</label>
          <input
            type="date"
            className="input w-full"
            value={transactionDate}
            onChange={(e) => setTransactionDate(e.target.value)}
            onBlur={validate}
          />
          {errors.transactionDate && <span className="text-loss text-xs">{errors.transactionDate}</span>}
          {isFutureDate && <span className="text-yellow-400 text-xs">Future date</span>}
        </div>
        <div>
          <label className="block text-text-muted text-xs mb-1">Settlement (optional)</label>
          <input
            type="date"
            className="input w-full"
            value={settlementDate}
            onChange={(e) => setSettlementDate(e.target.value)}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-text-muted text-xs mb-1">Action *</label>
          <select className="input w-full" value={action} onChange={(e) => setAction(e.target.value as ActionType)}>
            {ACTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-text-muted text-xs mb-1">Account Type *</label>
          <select className="input w-full" value={accountType} onChange={(e) => setAccountType(e.target.value)}>
            {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          {errors.accountType && <span className="text-loss text-xs">{errors.accountType}</span>}
        </div>
      </div>

      {needsTicker && (
        <div>
          <label className="block text-text-muted text-xs mb-1">Ticker *</label>
          <input
            type="text"
            className="input w-full"
            placeholder="e.g. VEQT.TO, AAPL"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onBlur={validate}
          />
          {errors.ticker && <span className="text-loss text-xs">{errors.ticker}</span>}
        </div>
      )}

      {needsQtyPrice && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-text-muted text-xs mb-1">Quantity *</label>
            <input
              type="number"
              step="any"
              className="input w-full"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              onBlur={validate}
            />
            {errors.quantity && <span className="text-loss text-xs">{errors.quantity}</span>}
            {overSell && (
              <span className="text-loss text-xs">
                You hold {heldQty} shares of {ticker.toUpperCase()} in {accountType}. Cannot sell {quantity}.
              </span>
            )}
            {heldLoading && <span className="text-text-muted text-xs">Checking position…</span>}
          </div>
          <div>
            <label className="block text-text-muted text-xs mb-1">Price *</label>
            <input
              type="number"
              step="any"
              className="input w-full"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              onBlur={validate}
            />
            {errors.price && <span className="text-loss text-xs">{errors.price}</span>}
          </div>
        </div>
      )}

      {!needsQtyPrice && (
        <div>
          <label className="block text-text-muted text-xs mb-1">Amount</label>
          <input
            type="number"
            step="any"
            className="input w-full"
            placeholder="e.g. 2000.00"
            value={netAmount}
            onChange={(e) => setNetAmount(e.target.value)}
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-text-muted text-xs mb-1">Currency</label>
          <select className="input w-full" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-text-muted text-xs mb-1">Commission</label>
          <input
            type="number"
            step="any"
            className="input w-full"
            value={commission}
            onChange={(e) => setCommission(e.target.value)}
          />
          {errors.commission && <span className="text-loss text-xs">{errors.commission}</span>}
        </div>
      </div>

      <div className="bg-border/20 rounded-lg p-3 space-y-1">
        <div className="text-xs font-medium text-text-muted mb-1">Derived Values</div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div>Gross: <span className="num font-medium">{previewLoading ? "…" : preview ? fmt.moneyShort(preview.gross_amount) : "—"}</span></div>
          <div>Net: <span className="num font-medium">{previewLoading ? "…" : preview ? fmt.moneyShort(preview.net_amount) : "—"}</span></div>
          <div>FX Rate: <span className="num font-medium">{previewLoading ? "…" : preview ? preview.fx_rate_to_cad.toFixed(4) : "—"}</span></div>
          <div>CAD Equiv: <span className="num font-medium">{previewLoading ? "…" : preview ? fmt.moneyShort(preview.net_cad) : "—"}</span></div>
        </div>
      </div>

      <div>
        <button
          type="button"
          className="text-xs text-text-muted hover:text-text-primary"
          onClick={() => setShowExtras(!showExtras)}
        >
          {showExtras ? "▾ Hide" : "▸ Show"} optional fields
        </button>
        {showExtras && (
          <div className="mt-2 space-y-2">
            <div>
              <label className="block text-text-muted text-xs mb-1">Description</label>
              <input type="text" className="input w-full" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div>
              <label className="block text-text-muted text-xs mb-1">Account Number</label>
              <input type="text" className="input w-full" value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} />
            </div>
            <div>
              <label className="block text-text-muted text-xs mb-1">ISIN</label>
              <input type="text" className="input w-full" value={isin} onChange={(e) => setIsin(e.target.value)} />
            </div>
            <div>
              <label className="block text-text-muted text-xs mb-1">Notes</label>
              <textarea className="input w-full" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
            <div className="text-xs">
              <span className="bg-accent/20 text-accent px-2 py-0.5 rounded-full font-medium">Manual</span>
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 pt-2 border-t border-border">
        <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
        <button
          type="submit"
          className="btn-primary"
          disabled={saving || overSell}
        >
          {saving && <Loader2 size={14} className="animate-spin" />}
          {isEdit ? "Update" : "Save"}
        </button>
      </div>
    </form>
  );
}
