import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Download, FileUp, RefreshCw, FileSpreadsheet, AlertTriangle, Settings, FileText } from "lucide-react";
import clsx from "clsx";
import { api, fmt } from "../api";
import type { ImportInfo, PriceRefreshResult } from "../types";
import { useToast } from "./Toast";
import ProfileSwitcher from "./ProfileSwitcher";
import { usePeriod } from "./PeriodContext";
import SettingsPage from "./SettingsPage";
import ReportsModal from "./ReportsModal";
import ThemeToggle from "./ThemeToggle";
import AlertsPanel from "./AlertsPanel";
import type { Holding } from "../types";

interface Props {
  lastImport: ImportInfo | null;
  lastRefreshAt: string | null;
  onImportNew: () => void;
  holdings: Holding[];
}

/**
 * Ticks every `intervalMs` to force re-renders so relative time labels
 * ("3 min ago", "1 h ago") update without requiring a page reload.
 */
function useTicker(intervalMs: number): void {
  const [, setT] = useState(0);
  useEffect(() => {
    const h = window.setInterval(() => setT((t) => t + 1), intervalMs);
    return () => window.clearInterval(h);
  }, [intervalMs]);
}

export default function SyncStatus({ lastImport, lastRefreshAt, onImportNew, holdings }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const { period } = usePeriod();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [reportsOpen, setReportsOpen] = useState(false);
  // Tick once a minute so "X min ago" advances live.
  useTicker(60_000);

  // Briefly show "✓ Refreshed" after a successful manual refresh.
  const [justRefreshed, setJustRefreshed] = useState(false);
  // If any tickers failed in the last refresh, surface them in a tooltip.
  const [failedTickers, setFailedTickers] = useState<string[]>([]);

  const refresh = useMutation<PriceRefreshResult>({
    mutationFn: api.refreshPrices,
    onSuccess: (r) => {
      toast.push(`Refreshed ${r.refreshed} prices`, "success");
      setJustRefreshed(true);
      setFailedTickers(r.failed || []);
      window.setTimeout(() => setJustRefreshed(false), 3000);
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["correlation"] });
      qc.invalidateQueries({ queryKey: ["history"] });
    },
    onError: (e: Error) => toast.push(e.message || "Refresh failed", "error"),
  });

  const ageMin = lastRefreshAt
    ? Math.max(0, Math.floor((Date.now() - new Date(lastRefreshAt).getTime()) / 60_000))
    : null;
  const priceColor =
    ageMin === null
      ? "text-text-muted"
      : ageMin > 120
      ? "text-loss"
      : ageMin > 30
      ? "text-yellow-400"
      : "text-gain";

  function downloadExport() {
    window.open(api.exportXlsxUrl(period), "_blank");
  }

  return (
    <div className="border-b border-border bg-surface/60 backdrop-blur sticky top-0 z-30">
      <div className="max-w-screen-2xl mx-auto px-6 py-2.5 flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2 text-sm">
          <FileSpreadsheet size={14} className="text-text-muted" />
          <span className="text-text-muted">Last import:</span>
          <span className="font-medium truncate max-w-[18rem]">
            {lastImport?.filename || "—"}
          </span>
          <span className="text-text-muted">·</span>
          <span className="text-text-muted">
            {fmt.date(lastImport?.timestamp)} · {lastImport?.transaction_count ?? 0} transactions
          </span>
        </div>

        <div className="flex items-center gap-2 text-sm">
          <RefreshCw size={14} className={priceColor} />
          <span className="text-text-muted">Prices refreshed</span>
          <span className={clsx("font-medium", priceColor)}>{fmt.ago(lastRefreshAt)}</span>
          {failedTickers.length > 0 && (
            <span
              title={`Failed to refresh: ${failedTickers.join(", ")}`}
              className="inline-flex items-center gap-1 text-yellow-400 text-xs"
            >
              <AlertTriangle size={12} />
              {failedTickers.length} ticker{failedTickers.length > 1 ? "s" : ""} failed
            </span>
          )}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <RefreshButton
            isPending={refresh.isPending}
            justRefreshed={justRefreshed}
            onClick={() => refresh.mutate()}
          />
          <button className="btn-ghost" onClick={onImportNew}>
            <FileUp size={14} /> Import new export
          </button>
          <button className="btn-ghost" onClick={() => setReportsOpen(true)}>
            <FileText size={14} /> Reports
          </button>
          <button className="btn-primary" onClick={downloadExport}>
            <Download size={14} /> Export to Excel
          </button>
          <AlertsPanel holdings={holdings} />
          <ThemeToggle />
          <button
            className="btn-ghost p-2"
            onClick={() => setSettingsOpen(true)}
            title="Settings"
          >
            <Settings size={16} />
          </button>
          <ProfileSwitcher />
        </div>
      </div>
      {settingsOpen && <SettingsPage onClose={() => setSettingsOpen(false)} />}
      {reportsOpen && <ReportsModal onClose={() => setReportsOpen(false)} />}
    </div>
  );
}

function RefreshButton({
  isPending,
  justRefreshed,
  onClick,
}: {
  isPending: boolean;
  justRefreshed: boolean;
  onClick: () => void;
}) {
  if (isPending) {
    return (
      <button className="btn-ghost cursor-wait" disabled>
        <RefreshCw size={14} className="animate-spin" />
        Refreshing…
      </button>
    );
  }
  if (justRefreshed) {
    return (
      <button className="btn-ghost text-gain border border-gain/30 bg-gain/10" disabled>
        <Check size={14} />
        Refreshed
      </button>
    );
  }
  return (
    <button className="btn-ghost" onClick={onClick}>
      <RefreshCw size={14} />
      Refresh prices
    </button>
  );
}
