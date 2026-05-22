/**
 * Combined modal for downloadable PDF reports — Tax Report (Task 2) and Annual
 * Report (Task 9). The modal opens from the "Reports" button in SyncStatus.
 *
 * The user picks a tab (Tax / Annual) and a year, then clicks Generate. Both
 * reports stream from the backend as `application/pdf`; we use a regular
 * `<a download>` so the browser's save dialog handles it.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, Download, FileText, BarChart3 } from "lucide-react";
import clsx from "clsx";
import { api } from "../api";

type ReportKind = "tax" | "annual";

interface Props {
  onClose: () => void;
  initialKind?: ReportKind;
}

export default function ReportsModal({ onClose, initialKind = "tax" }: Props) {
  const [kind, setKind] = useState<ReportKind>(initialKind);
  const thisYear = new Date().getFullYear();
  const defaultYear = thisYear - 1;
  const [year, setYear] = useState(defaultYear);

  // Year picker bounded by the earliest year we have transactions for.
  const portfolio = useQuery({ queryKey: ["portfolio", "all", "all"], queryFn: () => api.portfolio() });
  const earliest = inferEarliestYear(portfolio.data);
  const years: number[] = [];
  for (let y = thisYear; y >= earliest; y--) years.push(y);

  const url = kind === "tax" ? api.exportTaxReportUrl(year) : api.exportAnnualReportUrl(year);
  const filename = kind === "tax" ? `tax_report_${year}.pdf` : `annual_report_${year}.pdf`;

  return (
    <div className="fixed inset-0 z-50 bg-black/60 overflow-y-auto" onClick={onClose}>
      <div className="min-h-full flex items-center justify-center px-4 py-[60px]">
        <div
          className="card w-[28rem] max-w-[90vw] max-h-[calc(100vh-120px)] overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Generate report</h2>
            <button className="text-text-muted hover:text-text-primary" onClick={onClose}>
              <X size={16} />
            </button>
          </div>

          <div className="flex gap-1 mb-4 bg-white/[0.04] p-1 rounded-full">
            <KindButton active={kind === "tax"} onClick={() => setKind("tax")} icon={<FileText size={14} />}>
              Tax Report
            </KindButton>
            <KindButton active={kind === "annual"} onClick={() => setKind("annual")} icon={<BarChart3 size={14} />}>
              Annual Report
            </KindButton>
          </div>

          <p className="text-xs text-text-muted mb-3">
            {kind === "tax"
              ? "CRA-style Schedule 3 capital gains report for the selected tax year."
              : "Year-in-review with performance summary, holdings, and dividend calendar."}
          </p>

          <label className="block label-muted mb-1">Year</label>
          <select
            value={year}
            onChange={(e) => setYear(parseInt(e.target.value, 10))}
            className="w-full bg-white/5 border border-border rounded-md px-3 py-2 text-sm mb-4"
          >
            {years.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>

          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={onClose}>Cancel</button>
            <a className="btn-primary" href={url} download={filename}>
              <Download size={14} /> Generate PDF
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

function KindButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "flex-1 px-3 py-1.5 text-xs font-medium rounded-full transition-colors inline-flex items-center justify-center gap-1.5",
        active ? "bg-accent text-white" : "text-text-muted hover:text-text-primary",
      )}
    >
      {icon}
      {children}
    </button>
  );
}

function inferEarliestYear(p?: { holdings: Array<{ ticker: string }> } | undefined): number {
  // Conservative floor; the real range is bounded by the transaction store but
  // we don't ship it on the portfolio payload yet.
  return 2009;
}
