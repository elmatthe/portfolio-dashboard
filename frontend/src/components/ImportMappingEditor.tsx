/**
 * Editable column-mapping editor for the universal import lane (Item 4 Step 7).
 *
 * Shown ONLY for generic / low-confidence imports (detection confidence below
 * REVIEW_CONFIDENCE_THRESHOLD). Named / high-confidence imports keep the
 * existing one-shot flow and never see this modal. The user reviews how each
 * source column was mapped to a canonical field, overrides anything wrong, sees
 * a live sample of the raw data, and confirms — which POSTs to
 * /api/import/confirm with the chosen overrides.
 */
import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { ModalPortal } from "./ModalPortal";
import type { ImportPreview } from "../types";

const IGNORE = -1;

interface Props {
  preview: ImportPreview;
  busy: boolean;
  onConfirm: (mapping: Record<string, number>) => void;
  onCancel: () => void;
}

// Row-state buckets → label + a token-based colour (no new CSS variables).
const STATE_META: { key: string; label: string; cls: string }[] = [
  { key: "confident", label: "Confident", cls: "text-gain" },
  { key: "with_assumptions", label: "Assumptions", cls: "text-accent" },
  { key: "partial", label: "Partial", cls: "text-loss" },
  { key: "unmapped", label: "Unmapped", cls: "text-text-muted" },
];

function prettyField(field: string): string {
  return field
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function ImportMappingEditor({ preview, busy, onConfirm, onCancel }: Props) {
  const fields = preview.fields ?? [];
  const columns = preview.source_columns ?? [];
  const sampleRows = preview.sample_rows ?? [];
  const counts = preview.row_state_counts ?? {};
  const missing = preview.missing_required ?? [];

  const [overrides, setOverrides] = useState<Record<string, number>>(() => {
    const init: Record<string, number> = {};
    for (const f of fields) init[f.field] = f.col_index ?? IGNORE;
    return init;
  });

  const confidencePct = Math.round((preview.overall_mapping_confidence ?? 0) * 100);
  const confidenceCls =
    confidencePct >= 70 ? "text-gain" : confidencePct >= 40 ? "text-accent" : "text-loss";

  return (
    <ModalPortal onClose={onCancel} labelledBy="mapping-editor-title">
      <div className="min-h-full flex items-start justify-center px-4 py-[48px]">
        <div
          className="card w-[52rem] max-w-[94vw] max-h-[calc(100vh-96px)] overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between mb-1">
            <div>
              <h2 id="mapping-editor-title" className="text-xl font-bold">
                Review column mapping
              </h2>
              <p className="text-sm text-text-muted mt-0.5">
                {preview.detected_institution || "Unrecognised format"} — this file wasn&apos;t
                from a known broker, so confirm how its columns map before importing.
              </p>
            </div>
            <button
              className="btn-ghost text-text-muted hover:text-text-primary"
              onClick={onCancel}
              aria-label="Cancel import"
            >
              <X size={16} />
            </button>
          </div>

          {/* Confidence + row-state summary */}
          <div className="flex flex-wrap items-center gap-3 mt-3 mb-4">
            <span className="badge border border-border">
              Mapping confidence:&nbsp;
              <span className={`num font-semibold ${confidenceCls}`}>{confidencePct}%</span>
            </span>
            {STATE_META.map((s) => (
              <span key={s.key} className="badge border border-border">
                <span className={`num font-semibold ${s.cls}`}>{counts[s.key] ?? 0}</span>
                &nbsp;{s.label}
              </span>
            ))}
          </div>

          {missing.length > 0 && (
            <div className="flex items-start gap-2 text-sm text-loss mb-4">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>
                Missing required field{missing.length > 1 ? "s" : ""}:{" "}
                <span className="num">{missing.join(", ")}</span>. Map a column below, or those
                rows will be held back for review.
              </span>
            </div>
          )}

          {/* Mapping table */}
          <div className="overflow-x-auto rounded-lg border border-border mb-5">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-text-muted border-b border-border">
                  <th className="px-3 py-2 font-medium">Canonical field</th>
                  <th className="px-3 py-2 font-medium">Detected as</th>
                  <th className="px-3 py-2 font-medium">Conf.</th>
                  <th className="px-3 py-2 font-medium">Method</th>
                  <th className="px-3 py-2 font-medium">Map to column</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => {
                  const selected = overrides[f.field] ?? IGNORE;
                  const unmappedRequired = f.required && selected === IGNORE;
                  return (
                    <tr key={f.field} className="border-b border-border/60 last:border-0">
                      <td className="px-3 py-2 font-medium">
                        {prettyField(f.field)}
                        {f.required && <span className="text-loss">&nbsp;*</span>}
                      </td>
                      <td className="px-3 py-2 text-text-muted">
                        {f.col_header ?? (
                          <span className="inline-flex items-center gap-1 text-loss">
                            <AlertTriangle size={13} /> not found
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 num text-text-muted">
                        {f.col_index === null ? "—" : `${Math.round(f.confidence * 100)}%`}
                      </td>
                      <td className="px-3 py-2 text-text-muted">{f.method ?? "—"}</td>
                      <td className="px-3 py-2">
                        <select
                          className={`filter-input px-2 py-1 w-full ${
                            unmappedRequired ? "border-loss" : ""
                          }`}
                          value={selected}
                          onChange={(e) =>
                            setOverrides((o) => ({
                              ...o,
                              [f.field]: Number(e.target.value),
                            }))
                          }
                        >
                          <option value={IGNORE}>
                            {f.required ? "— not found —" : "— ignore —"}
                          </option>
                          {columns.map((c) => (
                            <option key={c.index} value={c.index}>
                              {c.header || `Column ${c.index + 1}`}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Sample data preview */}
          {sampleRows.length > 0 && (
            <div className="mb-5">
              <div className="label-muted mb-2">Sample rows (first {sampleRows.length})</div>
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-xs num">
                  <thead>
                    <tr className="text-left text-text-muted border-b border-border">
                      {columns.map((c) => (
                        <th key={c.index} className="px-2.5 py-1.5 font-medium whitespace-nowrap">
                          {c.header || `Col ${c.index + 1}`}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sampleRows.map((row, ri) => (
                      <tr key={ri} className="border-b border-border/50 last:border-0">
                        {columns.map((c) => (
                          <td key={c.index} className="px-2.5 py-1.5 whitespace-nowrap">
                            {row[c.index] ?? ""}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-2">
            <button className="btn-ghost" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => onConfirm(overrides)}
              disabled={busy}
            >
              {busy ? "Importing…" : "Confirm Import"}
            </button>
          </div>
        </div>
      </div>
    </ModalPortal>
  );
}
