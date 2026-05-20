import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";
import Upload from "./components/Upload";
import Dashboard from "./components/Dashboard";
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

function AppInner() {
  const [forceUpload, setForceUpload] = useState(false);
  const profile = useProfile();
  const qc = useQueryClient();
  // Re-fetch import-status whenever the active profile changes so we route to
  // Upload vs Dashboard correctly for the newly selected profile.
  const status = useQuery({
    queryKey: ["import-status", profile.activeId],
    queryFn: api.importStatus,
    enabled: !!profile.activeId,
  });

  // When a new profile is activated, reset the forceUpload flag and refresh
  // all dashboard queries (already invalidated in the switcher, but redundant
  // is cheap).
  useEffect(() => {
    if (profile.activeId) {
      setForceUpload(false);
      qc.invalidateQueries({ queryKey: ["import-status"] });
    }
  }, [profile.activeId, qc]);

  // First-load gate. Once we know there's data, we show the dashboard immediately —
  // no re-upload required. The plan's #2 non-negotiable UX requirement.
  if (profile.isLoading || status.isLoading) {
    return <LoadingSplash />;
  }
  if (status.isError) {
    return <BackendError onRetry={() => status.refetch()} />;
  }

  const hasData = !!status.data?.has_data && !forceUpload;

  return hasData ? (
    <Dashboard onImportNew={() => setForceUpload(true)} />
  ) : (
    <Upload
      onSuccess={() => {
        setForceUpload(false);
        status.refetch();
      }}
      onCancel={status.data?.has_data ? () => setForceUpload(false) : undefined}
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
