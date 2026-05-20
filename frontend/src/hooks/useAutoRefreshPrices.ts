import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api";

/**
 * On mount, check /api/prices/status. If prices are older than `staleAfterMinutes`
 * (default 30), kick off a background refresh and invalidate the portfolio query
 * so the UI picks up the fresh values. Runs once per session — re-mounting the
 * component does NOT trigger a second refresh.
 */
export function useAutoRefreshPrices(staleAfterMinutes = 30): void {
  const qc = useQueryClient();
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    (async () => {
      try {
        const status = await api.priceStatus();
        const ageMin = status.age_minutes;
        const needsRefresh = ageMin === null || ageMin > staleAfterMinutes;
        if (!needsRefresh) return;

        await api.refreshPrices();
        // Pull every account-scoped variant — the queryKey is ["portfolio", account]
        qc.invalidateQueries({ queryKey: ["portfolio"] });
        qc.invalidateQueries({ queryKey: ["correlation"] });
        qc.invalidateQueries({ queryKey: ["history"] });
      } catch {
        // Best-effort. A failed refresh shouldn't break the dashboard load.
      }
    })();
  }, [qc, staleAfterMinutes]);
}
