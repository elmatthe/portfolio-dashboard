import clsx from "clsx";
import type { AccountTab } from "../types";

interface Props {
  tabs: AccountTab[] | undefined | null;
  active: string;
  onChange: (key: string) => void;
}

export default function AccountTabs({ tabs, active, onChange }: Props) {
  // Guard: data may still be loading on first render before the API responds.
  // Older backend versions may also omit `tabs` entirely.
  if (!tabs || tabs.length <= 1) return null;
  return (
    <div className="flex gap-1 border-b border-border overflow-x-auto">
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            onClick={() => onChange(tab.key)}
            className={clsx(
              "px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
              isActive
                ? "border-accent text-text-primary"
                : "border-transparent text-text-muted hover:text-text-primary hover:border-white/10",
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
