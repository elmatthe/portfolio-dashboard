import { usePortfolio } from "../hooks/usePortfolio";
import { useAutoRefreshPrices } from "../hooks/useAutoRefreshPrices";
import SyncStatus from "./SyncStatus";

interface Props {
  onNavigate: (view: "dashboard" | "upload" | "transactions") => void;
  onImportNew: () => void;
}

export default function TransactionsPage({ onNavigate, onImportNew }: Props) {
  const portfolio = usePortfolio("all");
  useAutoRefreshPrices(30);

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
      <main className="max-w-screen-2xl mx-auto p-6">
        <h1 className="text-xl font-semibold mb-4">Transactions</h1>
        <div className="card text-text-muted text-sm">
          Transactions page coming in sub-task 3
        </div>
      </main>
    </div>
  );
}
