import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api } from "../api";
import { useToast } from "./Toast";
import type { UnresolvedTicker } from "../types";

interface Props {
  tickers: UnresolvedTicker[];
}

export default function UnresolvedTickersPanel({ tickers }: Props) {
  const [expanded, setExpanded] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  const [edits, setEdits] = useState<Record<string, string>>({});

  const resolve = useMutation({
    mutationFn: ({ raw, resolved }: { raw: string; resolved: string }) =>
      api.resolveTicker(raw, resolved),
    onSuccess: (_, { raw, resolved }) => {
      toast.push(`Mapped ${raw} → ${resolved}`, "success");
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (e: Error) => toast.push(e.message || "Failed to save mapping", "error"),
  });

  if (tickers.length === 0) return null;

  return (
    <div className="card border-l-4 border-l-yellow-400">
      <div className="flex items-center gap-3">
        <AlertTriangle size={18} className="text-yellow-400" />
        <div className="flex-1">
          <div className="font-medium">{tickers.length} unresolved ticker(s)</div>
          <div className="text-xs text-text-muted">
            We couldn't match these symbols to a Yahoo Finance ticker — prices and history
            won't load until you map them manually.
          </div>
        </div>
        <button className="btn-ghost text-xs" onClick={() => setExpanded((e) => !e)}>
          {expanded ? "Hide" : "Show"}
        </button>
      </div>
      {expanded && (
        <div className="mt-4 space-y-2">
          {tickers.map((t) => (
            <div key={t.raw_symbol} className="flex items-center gap-3 text-sm">
              <span className="num font-medium w-24">{t.raw_symbol}</span>
              <span className="flex-1 text-text-muted truncate">{t.description}</span>
              <input
                type="text"
                placeholder="e.g. AAPL or VEQT.TO"
                value={edits[t.raw_symbol] || ""}
                onChange={(e) => setEdits({ ...edits, [t.raw_symbol]: e.target.value })}
                className="bg-white/5 border border-border rounded-md px-2 py-1 text-xs num w-40"
              />
              <button
                disabled={!edits[t.raw_symbol]}
                onClick={() =>
                  resolve.mutate({
                    raw: t.raw_symbol,
                    resolved: edits[t.raw_symbol].trim().toUpperCase(),
                  })
                }
                className="btn-primary text-xs px-2 py-1 disabled:opacity-50"
              >
                Save
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
