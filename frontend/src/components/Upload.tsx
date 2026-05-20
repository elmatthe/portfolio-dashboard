import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useMutation } from "@tanstack/react-query";
import { Upload as UploadIcon, FileText, X } from "lucide-react";
import clsx from "clsx";
import { api } from "../api";
import { useToast } from "./Toast";
import ProfileSwitcher from "./ProfileSwitcher";
import { useProfile } from "./ProfileContext";

interface Props {
  onSuccess: () => void;
  onCancel?: () => void;
}

const ACCEPTED = {
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "application/vnd.ms-excel.sheet.macroEnabled.12": [".xlsm"],
  "application/vnd.ms-excel": [".xls"],
  "text/csv": [".csv"],
  "text/tab-separated-values": [".tsv"],
  "application/pdf": [".pdf"],
};

export default function Upload({ onSuccess, onCancel }: Props) {
  const toast = useToast();
  const profile = useProfile();
  const [progressStage, setProgressStage] = useState<string | null>(null);

  const importMut = useMutation({
    mutationFn: async (file: File) => {
      setProgressStage("Parsing transactions");
      // The backend does parsing + ticker resolution + price fetching in one call.
      // We rotate the label for user reassurance while the request is in flight.
      const id = window.setInterval(() => {
        setProgressStage((s) =>
          s === "Parsing transactions"
            ? "Resolving tickers"
            : s === "Resolving tickers"
            ? "Fetching prices"
            : "Saving to database",
        );
      }, 800);
      try {
        return await api.importFile(file);
      } finally {
        window.clearInterval(id);
        setProgressStage(null);
      }
    },
    onSuccess: (result) => {
      toast.push(`${result.inserted} new transactions added`, "success");
      if (result.skipped_duplicates > 0) {
        toast.push(`${result.skipped_duplicates} already existed — skipped`, "info");
      }
      if (result.unresolved_tickers.length > 0) {
        toast.push(
          `${result.unresolved_tickers.length} tickers couldn't be resolved`,
          "warning",
        );
      }
      onSuccess();
    },
    onError: (err: Error) => {
      toast.push(err.message || "Import failed", "error");
    },
  });

  const onDrop = useCallback(
    (files: File[]) => {
      if (files.length > 0) importMut.mutate(files[0]);
    },
    [importMut],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED,
    maxFiles: 1,
    disabled: importMut.isPending,
  });

  return (
    <div className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-2xl w-full">
        <div className="flex items-start justify-between mb-4">
          {onCancel ? (
            <button
              className="btn-ghost text-text-muted hover:text-text-primary"
              onClick={onCancel}
            >
              <X size={16} /> Back to dashboard
            </button>
          ) : (
            <div />
          )}
          <ProfileSwitcher />
        </div>

        <h1 className="text-4xl font-bold mb-2">Portfolio Dashboard</h1>
        <p className="text-text-muted mb-8">
          {profile.active
            ? `Importing into "${profile.active.name}". `
            : ""}
          Track your portfolio across Questrade, Wealthsimple, RBC, CIBC, TD, BMO, Scotia,
          Interactive Brokers, National Bank, Fidelity, and HSBC — ACB, capital gains,
          and dividends in 10 currencies, all calculated locally.
        </p>

        <div
          {...getRootProps()}
          className={clsx(
            "rounded-2xl border-2 border-dashed p-12 text-center cursor-pointer transition-colors",
            isDragActive
              ? "border-accent bg-accent/5"
              : "border-border bg-surface hover:bg-white/[0.03]",
            importMut.isPending && "pointer-events-none opacity-60",
          )}
        >
          <input {...getInputProps()} />
          <UploadIcon className="mx-auto mb-4 text-text-muted" size={48} />
          {importMut.isPending ? (
            <div>
              <div className="text-lg font-medium mb-1">{progressStage}…</div>
              <div className="text-sm text-text-muted">This usually takes a few seconds</div>
            </div>
          ) : (
            <>
              <div className="text-lg font-medium mb-2">
                {isDragActive ? "Drop your file here" : "Drop your transaction export here"}
              </div>
              <div className="text-sm text-text-muted mb-4">
                .csv, .tsv, .xlsx, or .pdf — broker auto-detected
              </div>
              <button className="btn-primary">
                <FileText size={16} /> Browse files
              </button>
            </>
          )}
        </div>

        <details className="card mt-6 cursor-pointer">
          <summary className="font-medium">How to export from Questrade</summary>
          <ol className="text-sm text-text-muted mt-3 space-y-1.5 list-decimal list-inside">
            <li>Log in to Questrade at <span className="num">my.questrade.com</span></li>
            <li>Go to Accounts → Activity</li>
            <li>Select date range: All Time (or since last export)</li>
            <li>Click Download → Excel</li>
            <li>Drag the downloaded file here</li>
          </ol>
        </details>

        <details className="card mt-3 cursor-pointer">
          <summary className="font-medium">How to export from Wealthsimple</summary>
          <ol className="text-sm text-text-muted mt-3 space-y-1.5 list-decimal list-inside">
            <li>Open Wealthsimple → Profile → Documents</li>
            <li>Request custom statement → Activities Export (CSV)</li>
            <li>Or use a monthly statement PDF — both are accepted</li>
          </ol>
        </details>

        <p className="text-xs text-text-muted mt-6 text-center">
          Re-uploading the same file is safe — duplicates are detected automatically.
        </p>
      </div>
    </div>
  );
}
