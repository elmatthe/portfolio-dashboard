import { useQuery } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { ChevronDown, ChevronRight, Columns3 } from "lucide-react";
import clsx from "clsx";
import { api, fmt } from "../api";
import { useProfile } from "./ProfileContext";
import { usePortfolio } from "../hooks/usePortfolio";
import { useAutoRefreshPrices } from "../hooks/useAutoRefreshPrices";
import SyncStatus from "./SyncStatus";
import type { Transaction, Broker } from "../types";

interface Props {
  onNavigate: (view: "dashboard" | "upload" | "transactions") => void;
  onImportNew: () => void;
}

const BROKER_LABELS: Record<string, string> = {
  questrade: "Questrade",
  wealthsimple: "Wealthsimple",
  rbc: "RBC Direct Investing",
  cibc: "CIBC Investor's Edge",
  td: "TD Direct Investing",
  bmo: "BMO InvestorLine",
  scotiabank: "Scotia iTRADE",
  interactive: "Interactive Brokers",
  nationalbank: "National Bank",
  fidelity: "Fidelity Investments",
  hsbc: "HSBC InvestDirect",
  generic: "Other",
  Manual: "Manual",
};

type ColumnKey =
  | "date" | "ticker" | "action" | "qty" | "price" | "currency"
  | "net" | "cad_eq" | "account_type"
  | "local_currency" | "local_amount" | "fx_rate" | "isin" | "settlement";

interface ColumnDef {
  key: ColumnKey;
  label: string;
  defaultVisible: boolean;
  align?: "left" | "right";
}

const COLUMNS: ColumnDef[] = [
  { key: "date", label: "Date", defaultVisible: true },
  { key: "ticker", label: "Ticker", defaultVisible: true },
  { key: "action", label: "Action", defaultVisible: true },
  { key: "qty", label: "Qty", defaultVisible: true, align: "right" },
  { key: "price", label: "Price", defaultVisible: true, align: "right" },
  { key: "currency", label: "Currency", defaultVisible: true },
  { key: "net", label: "Net Amount", defaultVisible: true, align: "right" },
  { key: "cad_eq", label: "CAD Equivalent", defaultVisible: true, align: "right" },
  { key: "account_type", label: "Account Type", defaultVisible: true },
  { key: "local_currency", label: "Local Currency", defaultVisible: false },
  { key: "local_amount", label: "Local Amount", defaultVisible: false, align: "right" },
  { key: "fx_rate", label: "FX Rate to CAD", defaultVisible: false, align: "right" },
  { key: "isin", label: "ISIN", defaultVisible: false },
  { key: "settlement", label: "Settlement Date", defaultVisible: false },
];

function getCellValue(tx: Transaction, col: ColumnKey): string {
  switch (col) {
    case "date": return fmt.date(tx.transaction_date);
    case "ticker": return tx.resolved_ticker || tx.raw_symbol || "—";
    case "action": return tx.action;
    case "qty": return tx.quantity ? tx.quantity.toLocaleString("en-CA", { maximumFractionDigits: 4 }) : "—";
    case "price": return tx.price ? fmt.moneyShort(tx.price) : "—";
    case "currency": return tx.currency;
    case "net": return fmt.moneyShort(tx.net_amount);
    case "cad_eq": return tx.net_cad != null ? fmt.moneyShort(tx.net_cad) : "—";
    case "account_type": return tx.account_type;
    case "local_currency": return tx.currency;
    case "local_amount": return fmt.moneyShort(tx.net_amount);
    case "fx_rate": return tx.fx_rate_to_cad != null ? tx.fx_rate_to_cad.toFixed(4) : "—";
    case "isin": return tx.isin || "—";
    case "settlement": return tx.settlement_date ? fmt.date(tx.settlement_date) : "—";
  }
}

export default function TransactionsPage({ onNavigate, onImportNew }: Props) {
  const profile = useProfile();
  const portfolio = usePortfolio("all");
  useAutoRefreshPrices(30);

  const txQuery = useQuery({
    queryKey: ["transactions", profile.activeId],
    queryFn: () => api.transactions(),
    enabled: !!profile.activeId,
  });

  const [visibleCols, setVisibleCols] = useState<Set<ColumnKey>>(
    () => new Set(COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key))
  );
  const [colMenuOpen, setColMenuOpen] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const allTxs = txQuery.data ?? [];

  const grouped = useMemo(() => {
    const map = new Map<string, Transaction[]>();
    for (const tx of allTxs) {
      const key = tx.broker;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(tx);
    }
    if (!map.has("Manual" as Broker)) {
      map.set("Manual" as Broker, []);
    }
    const sorted = [...map.entries()].sort(([a], [b]) => {
      if (a === "Manual") return 1;
      if (b === "Manual") return -1;
      return (BROKER_LABELS[a] || a).localeCompare(BROKER_LABELS[b] || b);
    });
    return sorted;
  }, [allTxs]);

  function toggleGroup(key: string) {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleColumn(key: ColumnKey) {
    setVisibleCols((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const activeCols = COLUMNS.filter((c) => visibleCols.has(c.key));

  return (
    <div className="min-h-screen">
      <SyncStatus
        lastImport={portfolio.data?.last_import ?? null}
        lastRefreshAt={portfolio.data?.last_price_refresh_at ?? null}
        onImportNew={onImportNew}
        holdings={portfolio.data?.holdings ?? []}
        onNavigate={onNavigate}
        activeView="transactions"
      />

      <main className="max-w-screen-2xl mx-auto p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Transactions</h1>
          <div className="relative">
            <button
              className="btn-ghost text-xs"
              onClick={() => setColMenuOpen((v) => !v)}
            >
              <Columns3 size={14} /> Columns
            </button>
            {colMenuOpen && (
              <div className="absolute right-0 top-full mt-1 bg-surface border border-border rounded-lg shadow-lg p-2 z-40 min-w-[180px]">
                {COLUMNS.map((col) => (
                  <label
                    key={col.key}
                    className="flex items-center gap-2 px-2 py-1 text-xs cursor-pointer hover:bg-border/30 rounded"
                  >
                    <input
                      type="checkbox"
                      checked={visibleCols.has(col.key)}
                      onChange={() => toggleColumn(col.key)}
                      className="accent-accent"
                    />
                    {col.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>

        {txQuery.isLoading && (
          <div className="card text-text-muted text-sm">Loading transactions…</div>
        )}
        {txQuery.isError && (
          <div className="card text-loss text-sm">
            Failed to load transactions: {(txQuery.error as Error)?.message}
          </div>
        )}

        {txQuery.isSuccess && (
          <div className="space-y-4">
            {grouped.map(([broker, txs]) => (
              <SourceGroup
                key={broker}
                broker={broker}
                transactions={txs}
                collapsed={collapsedGroups.has(broker)}
                onToggle={() => toggleGroup(broker)}
                columns={activeCols}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function SourceGroup({
  broker,
  transactions,
  collapsed,
  onToggle,
  columns,
}: {
  broker: string;
  transactions: Transaction[];
  collapsed: boolean;
  onToggle: () => void;
  columns: ColumnDef[];
}) {
  const label = BROKER_LABELS[broker] || broker;
  const isManual = broker === "Manual";
  const isEmpty = transactions.length === 0;

  return (
    <div className="card overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-border/20 transition-colors"
        onClick={onToggle}
      >
        {collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
        <span className="font-semibold text-sm">{label}</span>
        <span className="text-xs text-text-muted bg-border/40 rounded-full px-2 py-0.5">
          {transactions.length}
        </span>
      </button>

      {!collapsed && (
        <div className="px-4 pb-4">
          {isManual && isEmpty ? (
            <div className="text-text-muted text-sm py-4">
              No manual transactions entered yet.{" "}
              <span
                data-testid="add-transaction-empty-cta"
                className="text-accent cursor-pointer hover:underline"
              >
                Add Transaction
              </span>{" "}
              to record trades, dividends, or deposits by hand.
            </div>
          ) : isEmpty ? (
            <div className="text-text-muted text-sm py-4">
              No {label} transactions imported yet.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-text-muted text-left">
                    {columns.map((col) => (
                      <th
                        key={col.key}
                        className={clsx(
                          "pb-2 px-2 font-medium text-xs whitespace-nowrap",
                          col.align === "right" && "text-right"
                        )}
                      >
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {transactions.map((tx) => (
                    <tr key={tx.hash} className="hover:bg-border/10 transition-colors">
                      {columns.map((col) => (
                        <td
                          key={col.key}
                          className={clsx(
                            "py-2 px-2 whitespace-nowrap",
                            col.align === "right" && "text-right num",
                            col.key === "action" && actionColor(tx.action),
                            col.key === "net" && (tx.net_amount >= 0 ? "text-gain" : "text-loss"),
                            col.key === "cad_eq" && tx.net_cad != null && (tx.net_cad >= 0 ? "text-gain" : "text-loss"),
                          )}
                        >
                          {getCellValue(tx, col.key)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function actionColor(action: string): string {
  switch (action) {
    case "BUY": return "text-accent";
    case "SELL": return "text-loss";
    case "DIVIDEND": return "text-gain";
    default: return "text-text-muted";
  }
}
