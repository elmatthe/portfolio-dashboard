/**
 * Bell icon + slide-in alerts panel.
 *
 * The bell shows the count of triggered-but-not-dismissed alerts. Clicking
 * opens a right-side panel listing every active alert with set/remove
 * controls plus a "Create alert" form.
 *
 * Each price refresh, /api/alerts/triggered surfaces newly-fired alerts; we
 * toast them once apiece, keyed by id.
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellRing, Plus, Trash2, X, Check } from "lucide-react";
import clsx from "clsx";
import { api, fmt } from "../api";
import type { Currency, Holding, PriceAlert } from "../types";
import { useToast } from "./Toast";
import { ModalPortal } from "./ModalPortal";

interface Props {
  holdings: Holding[];
}

export default function AlertsPanel({ holdings }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const seenTriggeredRef = useRef<Set<number>>(new Set());

  const all = useQuery({ queryKey: ["alerts"], queryFn: api.alerts, staleTime: 30_000 });
  // Poll triggered alerts every 60s so the bell badge updates after a refresh
  // happens elsewhere; the polling overhead is one tiny request.
  const triggered = useQuery({
    queryKey: ["alerts-triggered"],
    queryFn: api.alertsTriggered,
    refetchInterval: 60_000,
    staleTime: 0,
  });

  // Toast once per newly-fired alert.
  useEffect(() => {
    if (!triggered.data) return;
    for (const a of triggered.data) {
      if (!seenTriggeredRef.current.has(a.id)) {
        seenTriggeredRef.current.add(a.id);
        const dir = a.alert_type === "above" ? "crossed above" : "fell below";
        toast.push(
          `🔔 ${a.ticker} ${dir} ${fmt.money(a.target_price, a.currency)}${
            a.current_price ? ` — current price ${fmt.money(a.current_price, a.currency)}` : ""
          }`,
          "info",
        );
      }
    }
  }, [triggered.data, toast]);

  const triggeredCount = triggered.data?.length || 0;
  const Icon = triggeredCount > 0 ? BellRing : Bell;

  return (
    <>
      <button
        className="btn-ghost p-2 relative"
        onClick={() => setOpen(true)}
        title="Price alerts"
      >
        <Icon size={16} />
        {triggeredCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-loss text-white text-[10px] rounded-full w-4 h-4 inline-flex items-center justify-center">
            {triggeredCount}
          </span>
        )}
      </button>

      {open && (
        <Slideover
          onClose={() => setOpen(false)}
          alerts={all.data || []}
          holdings={holdings}
          onChanged={() => {
            qc.invalidateQueries({ queryKey: ["alerts"] });
            qc.invalidateQueries({ queryKey: ["alerts-triggered"] });
          }}
        />
      )}
    </>
  );
}

function Slideover({
  onClose,
  alerts,
  holdings,
  onChanged,
}: {
  onClose: () => void;
  alerts: PriceAlert[];
  holdings: Holding[];
  onChanged: () => void;
}) {
  const toast = useToast();
  const create = useMutation({
    mutationFn: ({
      ticker,
      type,
      price,
      currency,
    }: {
      ticker: string;
      type: "above" | "below";
      price: number;
      currency: Currency;
    }) => api.createAlert(ticker, type, price, currency),
    onSuccess: () => {
      toast.push("Alert created", "success");
      onChanged();
    },
    onError: (e: Error) => toast.push(e.message || "Could not create alert", "error"),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteAlert(id),
    onSuccess: () => onChanged(),
  });
  const dismiss = useMutation({
    mutationFn: (id: number) => api.dismissAlert(id),
    onSuccess: () => onChanged(),
  });

  const tickerOptions = Array.from(new Set(holdings.map((h) => h.ticker))).sort();
  const [ticker, setTicker] = useState(tickerOptions[0] || "");
  const [type, setType] = useState<"above" | "below">("above");
  const [price, setPrice] = useState<number>(0);
  const [currency, setCurrency] = useState<Currency>(
    (holdings.find((h) => h.ticker === ticker)?.currency as Currency) || "CAD",
  );

  useEffect(() => {
    const h = holdings.find((x) => x.ticker === ticker);
    if (h) {
      setCurrency(h.currency as Currency);
      if (h.current_price && !price) setPrice(Math.round(h.current_price * 100) / 100);
    }
  }, [ticker, holdings]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ModalPortal
      onClose={onClose}
      labelledBy="alerts-slideover-title"
      backdropClassName="fixed inset-0 z-50 bg-black/60"
    >
      <aside
        className="fixed top-0 right-0 bottom-0 w-[24rem] max-w-[92vw] bg-surface border-l border-border overflow-y-auto overscroll-contain pb-8"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-border sticky top-0 bg-surface">
          <div id="alerts-slideover-title" className="font-semibold inline-flex items-center gap-2">
            <Bell size={16} /> Price alerts
          </div>
          <button className="text-text-muted hover:text-text-primary" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="p-4 border-b border-border space-y-2">
          <div className="text-xs label-muted mb-1">Create alert</div>
          <div className="grid grid-cols-2 gap-2">
            <select
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              className="bg-white/5 border border-border rounded-md px-2 py-1.5 text-sm col-span-2"
            >
              {tickerOptions.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as "above" | "below")}
              className="bg-white/5 border border-border rounded-md px-2 py-1.5 text-sm"
            >
              <option value="above">Sell above</option>
              <option value="below">Buy below</option>
            </select>
            <div className="inline-flex items-center bg-white/5 border border-border rounded-md px-2">
              <span className="text-text-muted text-xs">$</span>
              <input
                type="number"
                min={0}
                step={0.01}
                value={price}
                onChange={(e) => setPrice(parseFloat(e.target.value || "0"))}
                className="bg-transparent border-0 outline-none px-1 py-1.5 text-sm w-full"
              />
              <span className="text-text-muted text-xs">{currency}</span>
            </div>
          </div>
          <button
            className="btn-primary w-full mt-2"
            disabled={create.isPending || !ticker || price <= 0}
            onClick={() => create.mutate({ ticker, type, price, currency })}
          >
            <Plus size={14} /> Add alert
          </button>
        </div>

        <div className="p-4 space-y-2">
          <div className="text-xs label-muted mb-2">Active alerts</div>
          {alerts.length === 0 && (
            <div className="text-sm text-text-muted">No alerts yet.</div>
          )}
          {alerts.map((a) => (
            <div
              key={a.id}
              className={clsx(
                "card !p-3 flex items-center gap-2",
                a.triggered && "border-l-4 border-l-yellow-400",
              )}
            >
              <div className="flex-1 text-sm">
                <div className="font-medium">{a.ticker}</div>
                <div className="text-xs text-text-muted">
                  {a.alert_type === "above" ? "Sell above" : "Buy below"}{" "}
                  {fmt.money(a.target_price, a.currency)}
                </div>
                {a.current_price !== null && (
                  <div className="text-xs text-text-muted">
                    Now: <span className="num">{fmt.money(a.current_price, a.currency)}</span>
                  </div>
                )}
                {a.triggered && (
                  <div className="text-xs text-yellow-400 mt-0.5">
                    🔔 Triggered {fmt.ago(a.triggered_at)}
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-1">
                {a.triggered && !a.dismissed && (
                  <button
                    className="btn-ghost !p-1 text-xs"
                    title="Dismiss"
                    onClick={() => dismiss.mutate(a.id)}
                  >
                    <Check size={12} />
                  </button>
                )}
                <button
                  className="btn-ghost !p-1 text-xs text-loss"
                  title="Delete"
                  onClick={() => remove.mutate(a.id)}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </aside>
    </ModalPortal>
  );
}
