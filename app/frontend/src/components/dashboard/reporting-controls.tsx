import type { ComparisonPeriod } from "@/lib/contracts"
import { cn } from "@/lib/utils"

/** The reporting-period comparison windows offered in the UI (days). */
export const COMPARISON_PERIODS: ComparisonPeriod[] = [30, 60, 90]

export interface ReportingState {
  period: ComparisonPeriod
}

/**
 * Reporting-period control shared by the CISO scorecard and Manager view: a
 * compact segmented "box" selector for the reporting period (30 / 60 / 90 days).
 * Designed to sit in the page header's top-right actions slot so it doesn't
 * push content down. State is owned by the page so it can be threaded into the
 * metric requests; each KPI then shows its target and period-over-period change.
 */
export function ReportingControls({
  value,
  onChange,
  className,
}: {
  value: ReportingState
  onChange: (next: ReportingState) => void
  className?: string
}) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">
        Reporting period
      </span>
      <div
        role="group"
        aria-label="Reporting period"
        className="inline-flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-1"
      >
        {COMPARISON_PERIODS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onChange({ ...value, period: p })}
            aria-pressed={value.period === p}
            className={cn(
              "rounded-md px-3 py-1 text-sm font-medium tabular-nums transition-colors",
              value.period === p
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {p}d
          </button>
        ))}
      </div>
    </div>
  )
}
