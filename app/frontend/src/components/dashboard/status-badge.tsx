import { AlertTriangle, CheckCircle2, OctagonAlert } from "lucide-react"
import { cn } from "@/lib/utils"
import type { Kpi, RagStatus } from "@/lib/contracts"
import { statusTextClass } from "@/lib/status"

/**
 * Status expressed as a distinct SHAPE per RAG level (circle / triangle /
 * octagon), not color alone — so it stays legible for color-blind users
 * (WCAG 1.4.1). Color is layered on top as a secondary cue.
 */
const STATUS_ICON: Record<RagStatus, typeof CheckCircle2> = {
  green: CheckCircle2,
  amber: AlertTriangle,
  red: OctagonAlert,
}

const STATUS_LABEL: Record<RagStatus, string> = {
  green: "On target",
  amber: "Needs attention",
  red: "At risk",
}

export function StatusIcon({
  status,
  className,
}: {
  status: RagStatus
  className?: string
}) {
  const Icon = STATUS_ICON[status]
  return (
    <Icon
      className={cn("size-4 shrink-0", statusTextClass(status), className)}
      aria-label={STATUS_LABEL[status]}
    />
  )
}

/** Tally a list of Metric View measures into green / amber / red counts. */
export function tallyCompliance(kpis: Kpi[]) {
  const c = { green: 0, amber: 0, red: 0, total: kpis.length }
  for (const k of kpis) c[k.status]++
  return c
}

/**
 * Shows how many categories are on target (green) and how many are at risk
 * (red, flagged with a caution icon) — replaces verbal "Amber/Red" labels.
 */
export function ComplianceSignal({
  green,
  red,
  className,
}: {
  green: number
  red: number
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 text-sm font-semibold tabular-nums",
        className,
      )}
    >
      <span className="flex items-center gap-1.5 text-success">
        <CheckCircle2 className="size-4" />
        {green}
        <span className="font-normal text-muted-foreground">on target</span>
      </span>
      <span
        className={cn(
          "flex items-center gap-1.5",
          red > 0 ? "text-danger" : "text-muted-foreground",
        )}
      >
        <OctagonAlert className="size-4" />
        {red}
        <span className="font-normal text-muted-foreground">at risk</span>
      </span>
    </div>
  )
}

const STATUS_STYLES: Record<RagStatus, string> = {
  green: "bg-success-muted text-success border-success/30",
  amber: "bg-warning-muted text-warning border-warning/30",
  red: "bg-danger-muted text-danger border-danger/30",
}

const STATUS_DOT: Record<RagStatus, string> = {
  green: "bg-success",
  amber: "bg-warning",
  red: "bg-danger",
}

export function StatusBadge({
  status,
  label,
  className,
}: {
  status: RagStatus
  label?: string
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold",
        STATUS_STYLES[status],
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", STATUS_DOT[status])} />
      {label ?? status}
    </span>
  )
}

export function StatusDot({
  status,
  className,
}: {
  status: RagStatus
  className?: string
}) {
  return (
    <span
      className={cn("size-2.5 rounded-full", STATUS_DOT[status], className)}
      aria-label={`status: ${status}`}
    />
  )
}
