import { useState } from "react";
import { usePortfolio, useCorrelation } from "../hooks/usePortfolio";
import { useAutoRefreshPrices } from "../hooks/useAutoRefreshPrices";
import SyncStatus from "./SyncStatus";
import AccountTabs from "./AccountTabs";
import PortfolioSummary from "./PortfolioSummary";
import HoldingCard from "./HoldingCard";
import CapitalGainsTable from "./CapitalGainsTable";
import HistoricalChart from "./HistoricalChart";
import CorrelationMatrix from "./CorrelationMatrix";
import StatsTable from "./StatsBadge";
import UnresolvedTickersPanel from "./UnresolvedTickersPanel";
import PortfolioValueChart from "./PortfolioValueChart";
import DividendsPanel from "./DividendsPanel";
import PeriodPills from "./PeriodPills";
import { usePeriod } from "./PeriodContext";
import TfsaRoomCard from "./TfsaRoomCard";
import SettingsPage from "./SettingsPage";
import AttributionPanel from "./AttributionPanel";
import RebalancePanel from "./RebalancePanel";
import SimulatorModal from "./SimulatorModal";
import { FlaskConical } from "lucide-react";

interface Props {
  onImportNew: () => void;
}

export default function Dashboard({ onImportNew }: Props) {
  const [activeAccount, setActiveAccount] = useState<string>("all");
  const portfolio = usePortfolio(activeAccount);
  const correlation = useCorrelation(activeAccount);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  // Auto-refresh prices on dashboard mount if older than 30 min.
  useAutoRefreshPrices(30);

  const [settingsFromTfsa, setSettingsFromTfsa] = useState(false);
  const [simulatorOpen, setSimulatorOpen] = useState(false);

  if (portfolio.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-text-muted">Loading portfolio…</div>
      </div>
    );
  }
  if (portfolio.isError || !portfolio.data) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="card max-w-md">
          <div className="font-semibold mb-2">Couldn't load portfolio</div>
          <p className="text-sm text-text-muted">{(portfolio.error as Error)?.message}</p>
        </div>
      </div>
    );
  }

  const data = portfolio.data;
  const firstHoldingTicker = data.holdings[0]?.ticker || null;
  const activeTicker =
    selectedTicker && data.holdings.some((h) => h.ticker === selectedTicker)
      ? selectedTicker
      : firstHoldingTicker;
  const isFiltered = data.active_tab !== "all";
  const activeTabMeta = data.tabs.find((t) => t.key === data.active_tab);
  const isTfsaTab = activeTabMeta?.account_type === "TFSA";

  return (
    <div className="min-h-screen">
      <SyncStatus
        lastImport={data.last_import}
        lastRefreshAt={data.last_price_refresh_at}
        onImportNew={onImportNew}
        holdings={data.holdings}
      />

      <div className="max-w-screen-2xl mx-auto px-6 pt-2">
        <AccountTabs
          tabs={data.tabs}
          active={data.active_tab}
          onChange={(key) => {
            setActiveAccount(key);
            setSelectedTicker(null);
          }}
        />
      </div>
      <PeriodPills />

      <main className="max-w-screen-2xl mx-auto p-6 space-y-8">
        {data.unresolved_tickers.length > 0 && (
          <UnresolvedTickersPanel tickers={data.unresolved_tickers} />
        )}

        <section>
          <h2 className="text-lg font-semibold mb-3">Portfolio Balances</h2>
          <PortfolioSummary
            accounts={data.accounts}
            combined={data.combined}
            fx={data.exchange_rate}
            showCombinedRow={!isFiltered && data.accounts.length > 1}
          />
        </section>

        {isTfsaTab && (
          <section>
            <h2 className="text-lg font-semibold mb-3">TFSA Contribution Room</h2>
            <TfsaRoomCard onOpenSettings={() => setSettingsFromTfsa(true)} />
          </section>
        )}

        {settingsFromTfsa && <SettingsPage onClose={() => setSettingsFromTfsa(false)} />}
        {simulatorOpen && (
          <SimulatorModal holdings={data.holdings} onClose={() => setSimulatorOpen(false)} />
        )}

        <section>
          <h2 className="text-lg font-semibold mb-3">Portfolio Value History</h2>
          <PortfolioValueChart account={activeAccount} />
        </section>

        <section>
          <h2 className="text-lg font-semibold mb-3">Performance Attribution</h2>
          <AttributionPanel account={activeAccount} />
        </section>

        <section>
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-lg font-semibold">Holdings</h2>
            <span className="text-sm text-text-muted">
              {data.holdings.length} positions
              {!isFiltered && ` across ${data.accounts.length} accounts`}
            </span>
          </div>
          {data.holdings.length === 0 ? (
            <div className="card text-text-muted text-sm">No holdings in this account.</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {data.holdings.map((h) => (
                <HoldingCard
                  key={`${h.ticker}-${h.account_type}`}
                  holding={h}
                  onClick={() => setSelectedTicker(h.ticker)}
                  active={activeTicker === h.ticker}
                />
              ))}
            </div>
          )}
        </section>

        {data.capital_gains.realized_gains.length > 0 && (
          <section>
            <h2 className="text-lg font-semibold mb-3">Capital Gains</h2>
            <CapitalGainsTable report={data.capital_gains} />
          </section>
        )}

        <section>
          <h2 className="text-lg font-semibold mb-3">Dividend Income</h2>
          <DividendsPanel account={activeAccount} />
        </section>

        <section className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <div className="xl:col-span-2">
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-lg font-semibold">Historical Price</h2>
              <button className="btn-ghost text-xs" onClick={() => setSimulatorOpen(true)}>
                <FlaskConical size={14} /> What-If Simulator
              </button>
            </div>
            {activeTicker ? (
              <HistoricalChart
                ticker={activeTicker}
                acb={
                  data.holdings.find((h) => h.ticker === activeTicker)?.acb_per_share || null
                }
                holdings={data.holdings.map((h) => ({
                  ticker: h.ticker,
                  account_type: h.account_type,
                }))}
                onChangeTicker={setSelectedTicker}
              />
            ) : (
              <div className="card text-text-muted text-sm">No holdings yet.</div>
            )}
          </div>
          <div>
            <h2 className="text-lg font-semibold mb-3">Portfolio Stats</h2>
            <StatsTable stats={data.stats} />
          </div>
        </section>

        <section>
          <h2 className="text-lg font-semibold mb-3">Correlation Matrix</h2>
          <CorrelationMatrix data={correlation.data} isLoading={correlation.isLoading} />
        </section>

        <section>
          <h2 className="text-lg font-semibold mb-3">Rebalancing Advisor</h2>
          <RebalancePanel
            holdings={data.holdings}
            totalEquityCad={data.combined.total_equity_cad}
          />
        </section>

        <footer className="text-xs text-text-muted text-center py-8">
          All data stored locally · Powered by Yahoo Finance for prices
        </footer>
      </main>
    </div>
  );
}
