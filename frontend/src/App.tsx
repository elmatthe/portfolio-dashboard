import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";
import Upload from "./components/Upload";
import Dashboard from "./components/Dashboard";
import TransactionsPage from "./components/TransactionsPage";
import { ToastProvider } from "./components/Toast";
import { ProfileProvider, useProfile } from "./components/ProfileContext";
import { PeriodProvider } from "./components/PeriodContext";

export default function App() {
  return (
    <ProfileProvider>
      <PeriodProvider>
        <ToastProvider>
          <AppInner />
        </ToastProvider>
      </PeriodProvider>
    </ProfileProvider>
  );
}

type AppView = "dashboard" | "upload" | "transactions";

function AppInner() {
  const [view, setView] = useState<AppView>("dashboard");
  const profile = useProfile();
  const qc = useQueryClient();

  const healthCheck = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    retry: 2,
    staleTime: Infinity,
  });

  const status = useQuery({
    queryKey: ["import-status", profile.activeId],
    queryFn: api.importStatus,
    enabled: !!profile.activeId && !healthCheck.data?.db_corrupt,
  });

  useEffect(() => {
    if (profile.activeId) {
      setView("dashboard");
      qc.invalidateQueries({ queryKey: ["import-status"] });
    }
  }, [profile.activeId, qc]);

  if (profile.isLoading || healthCheck.isLoading || status.isLoading) {
    return <LoadingSplash />;
  }
  if (healthCheck.isError || status.isError) {
    return <BackendError onRetry={() => { healthCheck.refetch(); status.refetch(); }} />;
  }

  if (healthCheck.data?.db_corrupt) {
    return <CorruptDbScreen detail={healthCheck.data.db_corrupt_detail} />;
  }

  const hasData = !!status.data?.has_data && view !== "upload";

  if (!hasData) {
    return (
      <Upload
        onSuccess={() => {
          setView("dashboard");
          status.refetch();
        }}
        onCancel={status.data?.has_data ? () => setView("dashboard") : undefined}
      />
    );
  }

  if (view === "transactions") {
    return (
      <TransactionsPage
        onNavigate={setView}
        onImportNew={() => setView("upload")}
      />
    );
  }

  return (
    <Dashboard
      onImportNew={() => setView("upload")}
      onNavigate={setView}
    />
  );
}

function LoadingSplash() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const i = window.setInterval(() => setTick((t) => t + 1), 400);
    return () => window.clearInterval(i);
  }, []);
  const dots = ".".repeat((tick % 3) + 1);
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <div className="text-center">
        <div className="text-2xl font-semibold mb-2">Portfolio Dashboard</div>
        <div className="text-text-muted text-sm">Connecting to local server{dots}</div>
      </div>
    </div>
  );
}

function CorruptDbScreen({ detail }: { detail?: string | null }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg p-8">
      <div className="card max-w-lg">
        <div className="text-xl font-semibold mb-2">Database issue detected</div>
        <p className="text-text-muted text-sm mb-2">
          The app's database appears to be corrupted or unreadable. This can
          happen after importing a file with unexpected data.
        </p>
        {detail && (
          <p className="text-xs text-text-muted bg-white/5 rounded p-2 mb-4 font-mono break-all">
            {detail}
          </p>
        )}
        <p className="text-text-muted text-sm mb-4">
          You can reset the app to its factory state to recover. All profiles
          and data will be deleted.
        </p>
        <p className="text-xs text-text-muted mb-4">
          Manual recovery: delete the folder at <code>%APPDATA%/Portfolio Dashboard</code> and
          relaunch the app.
        </p>
        <div className="flex gap-2">
          <button
            className="btn-primary"
            onClick={() => window.location.reload()}
          >
            Retry
          </button>
          <button
            className="btn-ghost border border-red-500/30 text-red-400 hover:bg-red-500/10"
            onClick={async () => {
              if (
                !window.confirm(
                  "This will delete ALL data and return to factory state. Continue?",
                )
              )
                return;
              try {
                await api.factoryReset();
              } catch {
                // best-effort
              }
              window.location.reload();
            }}
          >
            Reset App Data
          </button>
        </div>
      </div>
    </div>
  );
}

function BackendError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg p-8">
      <div className="card max-w-md">
        <div className="text-xl font-semibold mb-2">Backend isn't responding</div>
        <p className="text-text-muted text-sm mb-4">
          The local data service couldn't be reached. If you launched this from the installer, try
          quitting and reopening. In dev, make sure the backend is running on port 7842.
        </p>
        <button className="btn-primary" onClick={onRetry}>
          Try again
        </button>
      </div>
    </div>
  );
}
