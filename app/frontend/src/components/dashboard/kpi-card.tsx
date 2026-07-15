import { ArrowDown, ArrowUp, Minus } from "lucide-react"
import { LineagePopover } from "@/components/dashboard/lineage-popover"
import { StatusIcon } from "@/components/dashboard/status-badge"
import type { Kpi } from "@/lib/contracts"
import { cn } from "@/lib/utils"
import {
  comparisonToneClass,
  statusTextClass,
  trendTextClass,
} from "@/lib/status"

const TREND_ICON = {
  up: ArrowUp,
  down: ArrowDown,
  flat: Minus,
}

export function KpiCard({
  kpi,
  variant = "default",
}: {
  kpi: Kpi
  variant?: "default" | "compact"
}) {
  const TrendIcon = kpi.trend ? TREND_ICON[kpi.trend.direction] : null
  const ChangeIcon = kpi.change ? TREND_ICON[kpi.change.arrow] : null

  return (
    <div className="group flex flex-col gap-1.5 rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium leading-tight text-muted-foreground text-pretty">
          {kpi.label}
        </p>
        <LineagePopover lineage={kpi.lineage} />
      </div>

      <p
        className={cn(
          "flex items-center gap-1.5 font-heading font-bold tabular-nums",
          variant === "compact" ? "text-2xl" : "text-3xl",
          statusTextClass(kpi.status),
        )}
      >
        <StatusIcon
          status={kpi.status}
          className={variant === "compact" ? "size-4" : "size-5"}
        />
        {kpi.value}
      </p>

      {kpi.caption ? (
        <p className="text-xs font-medium text-muted-foreground">
          {kpi.caption}
        </p>
      ) : null}

      {kpi.change && ChangeIcon ? (
        <p
          className={cn(
            "flex items-center gap-1 text-xs font-medium",
            comparisonToneClass(kpi.change.tone),
          )}
        >
          <ChangeIcon className="size-3" />
          Change: {kpi.change.label}
        </p>
      ) : kpi.trend && TrendIcon ? (
        <p
          className={cn(
            "flex items-center gap-1 text-xs font-medium",
            trendTextClass(kpi.trend.direction),
          )}
        >
          <TrendIcon className="size-3" />
          {kpi.trend.label}
        </p>
      ) : null}
    </div>
  )
}
