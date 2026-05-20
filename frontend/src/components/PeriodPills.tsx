/**
 * Sticky pill row directly below the account tabs. One click here changes the
 * period in PeriodContext and re-fetches every period-aware query.
 */
import clsx from "clsx";
import { PERIODS, usePeriod } from "./PeriodContext";

export default function PeriodPills() {
  const { period, setPeriod } = usePeriod();
  return (
    <div className="sticky top-[3.25rem] z-20 bg-bg/95 backdrop-blur border-b border-border">
      <div className="max-w-screen-2xl mx-auto px-6 py-2 flex items-center gap-2 flex-wrap">
        <span className="text-xs text-text-muted uppercase tracking-wider mr-1">Period</span>
        {PERIODS.map((p) => {
          const active = p.value === period;
          return (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={clsx(
                "px-3 py-1 text-xs font-medium rounded-full transition-colors whitespace-nowrap",
                active
                  ? "bg-accent text-white"
                  : "bg-white/5 text-text-muted hover:text-text-primary hover:bg-white/10",
              )}
            >
              {p.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
