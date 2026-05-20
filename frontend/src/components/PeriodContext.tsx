/**
 * Global time-horizon state. One context drives every period-aware query in
 * the app, so toggling the pill once invalidates every dependent React Query
 * key at the same time.
 *
 * Also syncs `#period=ytd` into `window.location.hash` so a particular view
 * is bookmarkable without pulling in a router.
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { PeriodKey } from "../types";

export const PERIODS: { value: PeriodKey; label: string }[] = [
  { value: "1m",  label: "1M"  },
  { value: "3m",  label: "3M"  },
  { value: "6m",  label: "6M"  },
  { value: "ytd", label: "YTD" },
  { value: "1y",  label: "1Y"  },
  { value: "3y",  label: "3Y"  },
  { value: "all", label: "All" },
];

interface PeriodContextValue {
  period: PeriodKey;
  setPeriod: (p: PeriodKey) => void;
}

const PeriodContext = createContext<PeriodContextValue>({
  period: "all",
  setPeriod: () => {},
});

function readPeriodFromHash(): PeriodKey {
  if (typeof window === "undefined") return "all";
  const m = /(?:^|[#&])period=([a-z0-9]+)/i.exec(window.location.hash || "");
  const v = (m?.[1] || "").toLowerCase();
  return (PERIODS.some((p) => p.value === v) ? v : "all") as PeriodKey;
}

function writePeriodToHash(p: PeriodKey): void {
  if (typeof window === "undefined") return;
  const current = window.location.hash || "";
  // Replace existing period=… or append a new one.
  const next = current.includes("period=")
    ? current.replace(/period=[^&]*/, `period=${p}`)
    : current
    ? `${current}&period=${p}`
    : `#period=${p}`;
  // Use replaceState so the back button doesn't fill with period toggles.
  history.replaceState(null, "", `${window.location.pathname}${window.location.search}${next}`);
}

export function PeriodProvider({ children }: { children: ReactNode }) {
  const [period, setPeriodState] = useState<PeriodKey>(() => readPeriodFromHash());

  // Keep hash in sync when the user clicks a different pill.
  useEffect(() => {
    writePeriodToHash(period);
  }, [period]);

  // Respond to manual hash edits / browser navigation.
  useEffect(() => {
    const onHash = () => {
      const next = readPeriodFromHash();
      setPeriodState((cur) => (cur === next ? cur : next));
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const setPeriod = useCallback((p: PeriodKey) => setPeriodState(p), []);
  return <PeriodContext.Provider value={{ period, setPeriod }}>{children}</PeriodContext.Provider>;
}

export function usePeriod(): PeriodContextValue {
  return useContext(PeriodContext);
}
