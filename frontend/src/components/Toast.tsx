import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import clsx from "clsx";

type ToastVariant = "info" | "success" | "warning" | "error";

interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  push: (message: string, variant?: ToastVariant) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((message: string, variant: ToastVariant = "info") => {
    const id = ++counter;
    setToasts((t) => [...t, { id, message, variant }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-md">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "card border-l-4 px-4 py-3 shadow-lg",
              t.variant === "success" && "border-l-gain",
              t.variant === "info" && "border-l-accent",
              t.variant === "warning" && "border-l-yellow-400",
              t.variant === "error" && "border-l-loss",
            )}
          >
            <div className="text-sm">{t.message}</div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
