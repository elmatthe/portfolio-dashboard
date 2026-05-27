import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useState, useMemo, useCallback } from "react";
import { ChevronDown, ChevronRight, Columns3, Search, X, Plus, Pencil, Trash2 } from "lucide-react";
import clsx from "clsx";
import { api, fmt } from "../api";
import { useProfile } from "./ProfileContext";
import { usePortfolio } from "../hooks/usePortfolio";
import { useAutoRefreshPrices } from "../hooks/useAutoRefreshPrices";
import SyncStatus from "./SyncStatus";
import { ModalPortal } from "./ModalPortal";
import AddTransactionForm from "./AddTransactionForm";
import { useToast } from "./Toast";
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

type SortDir = "asc" | "desc";
type SortableKey = "date" | "ticker" | "action" | "net" | "cad_eq";

const SORTABLE_COLUMNS: Set<ColumnKey> = new Set(["date", "ticker", "action", "net", "cad_eq"]);

function sortTransactions(txs: Transaction[], sortKey: SortableKey, dir: SortDir): Transaction[] {
  const sorted = [...txs];
  sorted.sort((a, b) => {
    let cmp = 0;
    switch (sortKey) {
      case "date":
        cmp = a.transaction_date.localeCompare(b.transaction_date);
        break;
      case "ticker":
        cmp = (a.resolved_ticker || a.raw_symbol || "").localeCompare(b.resolved_ticker || b.raw_symbol || "");
        break;
      case "action":
        cmp = a.action.localeCompare(b.action);
        break;
      case "net":
        cmp = Math.abs(a.net_amount) - Math.abs(b.net_amount);
        break;
      case "cad_eq":
        cmp = Math.abs(a.net_cad ?? 0) - Math.abs(b.net_cad ?? 0);
        break;
    }
    return dir === "asc" ? cmp : -cmp;
  });
  return sorted;
}

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
  const toast = useToast();
  const qc = useQueryClient();
  useAutoRefreshPrices(30);

  const txQuery = useQuery({
    queryKey: ["transactions", profile.activeId],
    queryFn: () => api.transactions(),
    enabled: !!profile.activeId,
  });

  const sourcesQuery = useQuery({
    queryKey: ["transaction-sources", profile.activeId],
    queryFn: () => api.transactionSources(),
    enabled: !!profile.activeId,
  });

  const [visibleCols, setVisibleCols] = useState<Set<ColumnKey>>(
    () => new Set(COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key))
  );
  const [colMenuOpen, setColMenuOpen] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const currentYear = new Date().getFullYear();
  const [filterBroker, setFilterBroker] = useState("");
  const [filterAccountType, setFilterAccountType] = useState("");
  const [filterCurrency, setFilterCurrency] = useState("");
  const [filterAction, setFilterAction] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState(`${currentYear}-01-01`);
  const [filterDateTo, setFilterDateTo] = useState("");
  const [searchText, setSearchText] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");

  const handleSearchChange = useCallback((val: string) => {
    setSearchText(val);
    const timeout = setTimeout(() => setSearchDebounced(val), 300);
    return () => clearTimeout(timeout);
  }, []);

  const allTxs = txQuery.data ?? [];

  const filteredTxs = useMemo(() => {
    let txs = allTxs;
    if (filterBroker) txs = txs.filter((t) => t.broker === filterBroker);
    if (filterAccountType) txs = txs.filter((t) => t.account_type === filterAccountType);
    if (filterCurrency) txs = txs.filter((t) => t.currency === filterCurrency);
    if (filterAction) txs = txs.filter((t) => t.action === filterAction);
    if (filterDateFrom) {
      txs = txs.filter((t) => t.transaction_date >= filterDateFrom);
    }
    if (filterDateTo) {
      txs = txs.filter((t) => t.transaction_date <= filterDateTo);
    }
    if (searchDebounced) {
      const q = searchDebounced.toLowerCase();
      txs = txs.filter(
        (t) =>
          (t.resolved_ticker && t.resolved_ticker.toLowerCase().includes(q)) ||
          (t.raw_symbol && t.raw_symbol.toLowerCase().includes(q)) ||
          (t.description && t.description.toLowerCase().includes(q))
      );
    }
    return txs;
  }, [allTxs, filterBroker, filterAccountType, filterCurrency, filterAction, filterDateFrom, filterDateTo, searchDebounced]);

  const grouped = useMemo(() => {
    const map = new Map<string, Transaction[]>();
    for (const tx of filteredTxs) {
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
  }, [filteredTxs]);

  const hasActiveFilters =
    !!filterBroker || !!filterAccountType || !!filterCurrency || !!filterAction ||
    filterDateFrom !== `${currentYear}-01-01` || !!filterDateTo || !!searchDebounced;

  function clearAllFilters() {
    setFilterBroker("");
    setFilterAccountType("");
    setFilterCurrency("");
    setFilterAction("");
    setFilterDateFrom(`${currentYear}-01-01`);
    setFilterDateTo("");
    setSearchText("");
    setSearchDebounced("");
  }

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

  const [addModalOpen, setAddModalOpen] = useState(false);
  const [editTx, setEditTx] = useState<Transaction | null>(null);

  function handleDeleteTx(tx: Transaction) {
    api.deleteManualTransaction(tx.hash)
      .then(() => {
        toast.push(`Transaction deleted — ${tx.resolved_ticker || tx.action}`, "success");
        qc.invalidateQueries({ queryKey: ["transactions"] });
        qc.invalidateQueries({ queryKey: ["portfolio"] });
        qc.invalidateQueries({ queryKey: ["correlation"] });
        qc.invalidateQueries({ queryKey: ["import-status"] });
      })
      .catch((err: Error) => {
        toast.push(`Delete failed: ${err.message}`, "error");
      });
  }

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
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold">Transactions</h1>
            <button
              className="btn-primary text-sm"
              onClick={() => setAddModalOpen(true)}
            >
              <Plus size={14} /> Add Transaction
            </button>
          </div>
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

        <div className="card p-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="filter-input py-1.5 px-2 w-auto"
              value={filterBroker}
              onChange={(e) => setFilterBroker(e.target.value)}
            >
              <option value="">All Sources</option>
              {(sourcesQuery.data ?? []).map((b) => (
                <option key={b} value={b}>{BROKER_LABELS[b] || b}</option>
              ))}
              <option value="Manual">Manual</option>
            </select>
            <select
              className="filter-input py-1.5 px-2 w-auto"
              value={filterAccountType}
              onChange={(e) => setFilterAccountType(e.target.value)}
            >
              <option value="">All Types</option>
              <option value="TFSA">TFSA</option>
              <option value="RRSP">RRSP</option>
              <option value="RESP">RESP</option>
              <option value="Margin">Margin</option>
              <option value="Non-Registered">Non-Registered</option>
            </select>
            <select
              className="filter-input py-1.5 px-2 w-auto"
              value={filterCurrency}
              onChange={(e) => setFilterCurrency(e.target.value)}
            >
              <option value="">All Currencies</option>
              <option value="CAD">CAD</option>
              <option value="USD">USD</option>
              <option value="GBP">GBP</option>
              <option value="EUR">EUR</option>
            </select>
            <select
              className="filter-input py-1.5 px-2 w-auto"
              value={filterAction}
              onChange={(e) => setFilterAction(e.target.value)}
            >
              <option value="">All Actions</option>
              <option value="BUY">Buy</option>
              <option value="SELL">Sell</option>
              <option value="DIVIDEND">Dividend</option>
              <option value="DEPOSIT">Deposit</option>
              <option value="WITHDRAWAL">Withdrawal</option>
              <option value="TRANSFER">Transfer</option>
              <option value="FEE">Fee</option>
            </select>
            <input
              type="date"
              className="filter-input py-1.5 px-2 w-auto"
              value={filterDateFrom}
              onChange={(e) => setFilterDateFrom(e.target.value)}
              title="From date"
            />
            <span className="text-text-muted text-xs">to</span>
            <input
              type="date"
              className="filter-input py-1.5 px-2 w-auto"
              value={filterDateTo}
              onChange={(e) => setFilterDateTo(e.target.value)}
              title="To date"
            />
            <div className="relative flex-1 min-w-[150px]">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                type="text"
                className="filter-input py-1.5 pl-6 pr-2 w-full"
                placeholder="Search ticker or description…"
                value={searchText}
                onChange={(e) => handleSearchChange(e.target.value)}
              />
            </div>
            {hasActiveFilters && (
              <button className="btn-ghost text-xs text-loss" onClick={clearAllFilters}>
                <X size={12} /> Clear
              </button>
            )}
          </div>
          <div className="text-xs text-text-muted">
            {filteredTxs.length} transaction{filteredTxs.length !== 1 ? "s" : ""} shown
            {hasActiveFilters && ` (${allTxs.length} total)`}
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
            {hasActiveFilters && filteredTxs.length === 0 && (
              <div className="card text-center py-8">
                <p className="text-text-muted text-sm mb-3">
                  No transactions match the current filters. Try clearing some filters.
                </p>
                <button className="btn-primary text-sm" onClick={clearAllFilters}>
                  Clear all filters
                </button>
              </div>
            )}
            {grouped.map(([broker, txs]) => (
              <SourceGroup
                key={broker}
                broker={broker}
                transactions={txs}
                collapsed={collapsedGroups.has(broker)}
                onToggle={() => toggleGroup(broker)}
                columns={activeCols}
                hasActiveFilters={hasActiveFilters}
                onAddTransaction={() => setAddModalOpen(true)}
                onEditTransaction={(tx) => { setEditTx(tx); setAddModalOpen(true); }}
                onDeleteTransaction={(tx) => handleDeleteTx(tx)}
              />
            ))}
          </div>
        )}
      </main>

      {addModalOpen && (
        <ModalPortal onClose={() => setAddModalOpen(false)} labelledBy="add-tx-title">
          <div
            className="max-w-lg mx-auto mt-16 mb-8 bg-surface rounded-xl shadow-2xl p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h2 id="add-tx-title" className="text-lg font-semibold">
                {editTx ? "Edit Transaction" : "Add Transaction"}
              </h2>
              <button
                className="text-text-muted hover:text-text-primary p-1"
                onClick={() => { setAddModalOpen(false); setEditTx(null); }}
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>
            <AddTransactionForm
              editTx={editTx}
              onCancel={() => { setAddModalOpen(false); setEditTx(null); }}
              onSuccess={(tx) => {
                setAddModalOpen(false);
                setEditTx(null);
                const label = editTx ? "updated" : "added";
                toast.push(
                  `Transaction ${label} — ${tx.resolved_ticker || tx.action} on ${tx.transaction_date}`,
                  "success"
                );
                qc.invalidateQueries({ queryKey: ["transactions"] });
                qc.invalidateQueries({ queryKey: ["transaction-sources"] });
                qc.invalidateQueries({ queryKey: ["portfolio"] });
                qc.invalidateQueries({ queryKey: ["correlation"] });
                qc.invalidateQueries({ queryKey: ["import-status"] });
              }}
            />
          </div>
        </ModalPortal>
      )}
    </div>
  );
}

function SourceGroup({
  broker,
  transactions,
  collapsed,
  onToggle,
  columns,
  hasActiveFilters,
  onAddTransaction,
  onEditTransaction,
  onDeleteTransaction,
}: {
  broker: string;
  transactions: Transaction[];
  collapsed: boolean;
  onToggle: () => void;
  columns: ColumnDef[];
  hasActiveFilters: boolean;
  onAddTransaction?: () => void;
  onEditTransaction?: (tx: Transaction) => void;
  onDeleteTransaction?: (tx: Transaction) => void;
}) {
  const label = BROKER_LABELS[broker] || broker;
  const isManual = broker === "Manual";
  const isEmpty = transactions.length === 0;

  const [expandedHash, setExpandedHash] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortableKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sortedTxs = useMemo(
    () => (isEmpty ? transactions : sortTransactions(transactions, sortKey, sortDir)),
    [transactions, sortKey, sortDir, isEmpty]
  );

  function handleSort(col: ColumnKey) {
    if (!SORTABLE_COLUMNS.has(col)) return;
    const key = col as SortableKey;
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "date" ? "desc" : "asc");
    }
  }

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
              No manual transactions entered yet. Use{" "}
              <button
                data-testid="add-transaction-empty-cta"
                className="text-accent font-medium hover:underline focus:outline-none focus:ring-1 focus:ring-accent rounded px-0.5"
                tabIndex={0}
                type="button"
                onClick={(e) => { e.stopPropagation(); onAddTransaction?.(); }}
              >
                Add Transaction
              </button>{" "}
              to record trades, dividends, or deposits by hand.
            </div>
          ) : isEmpty ? (
            <div className="text-text-muted text-sm py-4">
              {hasActiveFilters
                ? `No ${label} transactions match the current filters.`
                : `No ${label} transactions imported yet.`}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-text-muted text-left">
                    {columns.map((col) => {
                      const isSortable = SORTABLE_COLUMNS.has(col.key);
                      const isActive = sortKey === col.key;
                      return (
                        <th
                          key={col.key}
                          className={clsx(
                            "pb-2 px-2 font-medium text-xs whitespace-nowrap select-none",
                            col.align === "right" && "text-right",
                            isSortable && "cursor-pointer hover:text-text-primary"
                          )}
                          onClick={() => handleSort(col.key)}
                        >
                          {col.label}
                          {isActive && (
                            <span className="ml-1">{sortDir === "asc" ? "↑" : "↓"}</span>
                          )}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {sortedTxs.map((tx) => (
                    <TxRow
                      key={tx.hash}
                      tx={tx}
                      columns={columns}
                      expanded={expandedHash === tx.hash}
                      onToggle={() => setExpandedHash(expandedHash === tx.hash ? null : tx.hash)}
                      onEdit={tx.is_manual ? () => onEditTransaction?.(tx) : undefined}
                      onDelete={tx.is_manual ? () => onDeleteTransaction?.(tx) : undefined}
                    />
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

function TxRow({
  tx,
  columns,
  expanded,
  onToggle,
  onEdit,
  onDelete,
}: {
  tx: Transaction;
  columns: ColumnDef[];
  expanded: boolean;
  onToggle: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <>
      <tr
        className={clsx(
          "cursor-pointer transition-colors group",
          expanded ? "bg-accent/5" : "hover:bg-border/10"
        )}
        onClick={onToggle}
      >
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
        {(onEdit || onDelete) && (
          <td className="py-2 px-1 whitespace-nowrap w-16">
            <span className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
              {onEdit && (
                <button
                  className="p-1 text-text-muted hover:text-accent rounded"
                  onClick={(e) => { e.stopPropagation(); onEdit(); }}
                  title="Edit"
                >
                  <Pencil size={13} />
                </button>
              )}
              {onDelete && (
                <button
                  className="p-1 text-text-muted hover:text-loss rounded"
                  onClick={(e) => { e.stopPropagation(); setConfirmDelete(true); }}
                  title="Delete"
                >
                  <Trash2 size={13} />
                </button>
              )}
            </span>
          </td>
        )}
      </tr>
      {confirmDelete && (
        <tr>
          <td colSpan={columns.length + 1} className="p-0">
            <div className="bg-loss/5 border-t border-loss/20 px-4 py-3 flex items-center gap-3 text-xs">
              <span className="text-text-primary">
                Delete this {tx.action} of {tx.resolved_ticker || tx.raw_symbol || "transaction"} on {tx.transaction_date}? This cannot be undone.
              </span>
              <button
                className="btn-ghost text-xs"
                onClick={(e) => { e.stopPropagation(); setConfirmDelete(false); }}
              >
                Cancel
              </button>
              <button
                className="bg-loss text-white text-xs px-3 py-1 rounded hover:bg-loss/80"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmDelete(false);
                  onDelete?.();
                }}
              >
                Delete
              </button>
            </div>
          </td>
        </tr>
      )}
      {expanded && !confirmDelete && (
        <tr>
          <td colSpan={columns.length + ((onEdit || onDelete) ? 1 : 0)} className="p-0">
            <TxDetailPanel tx={tx} />
          </td>
        </tr>
      )}
    </>
  );
}

function TxDetailPanel({ tx }: { tx: Transaction }) {
  const details: [string, string | null | undefined][] = [
    ["Transaction Date", tx.transaction_date],
    ["Settlement Date", tx.settlement_date],
    ["Action", tx.action],
    ["Ticker (resolved)", tx.resolved_ticker],
    ["Raw Symbol", tx.raw_symbol],
    ["Description", tx.description],
    ["Quantity", tx.quantity?.toString()],
    ["Price", tx.price?.toString()],
    ["Gross Amount", tx.gross_amount?.toString()],
    ["Commission", tx.commission?.toString()],
    ["Net Amount", fmt.moneyShort(tx.net_amount)],
    ["Currency", tx.currency],
    ["FX Rate to CAD", tx.fx_rate_to_cad?.toFixed(4)],
    ["Net CAD", tx.net_cad != null ? fmt.moneyShort(tx.net_cad) : null],
    ["Account Number", tx.account_number],
    ["Account Type", tx.account_type],
    ["Broker", BROKER_LABELS[tx.broker] || tx.broker],
    ["ISIN", tx.isin],
    ["Exchange", tx.exchange],
    ["Reference ID", tx.reference_id],
    ["Hash", tx.hash],
  ];

  return (
    <div className="bg-surface/50 border-t border-border/50 px-6 py-3 ml-4">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-x-6 gap-y-1.5 text-xs">
        {details.map(([label, value]) =>
          value != null && value !== "" ? (
            <div key={label}>
              <span className="text-text-muted">{label}:</span>{" "}
              <span className="font-medium">{value}</span>
            </div>
          ) : null
        )}
      </div>
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
