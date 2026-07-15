import { Workflow } from "lucide-react"
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card"
import type { Kpi } from "@/lib/contracts"

export function LineagePopover({ lineage }: { lineage: Kpi["lineage"] }) {
  return (
    <HoverCard>
      <HoverCardTrigger
        tabIndex={0}
        role="button"
        aria-label="View metric lineage"
        className="rounded-md p-1 text-muted-foreground/60 outline-none transition-colors hover:bg-muted hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Workflow className="size-3.5" />
      </HoverCardTrigger>
      <HoverCardContent align="end" className="w-80 text-xs">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Workflow className="size-4 text-primary" />
            <span className="font-heading text-sm font-semibold">
              Metric lineage
            </span>
          </div>
          <dl className="space-y-2">
            <div>
              <dt className="font-medium text-muted-foreground">
                Metric View measure
              </dt>
              <dd className="font-mono text-foreground">{lineage.measure}</dd>
            </div>
            <div>
              <dt className="font-medium text-muted-foreground">Meaning</dt>
              <dd className="text-foreground">{lineage.comment}</dd>
            </div>
            <div>
              <dt className="font-medium text-muted-foreground">Expression</dt>
              <dd className="mt-1 rounded-md bg-muted p-2 font-mono leading-relaxed text-foreground">
                {lineage.expression}
              </dd>
            </div>
          </dl>
          <p className="border-t border-border pt-2 text-[11px] text-muted-foreground">
            Resolved via Databricks SQL Warehouse Metric Views (currently served
            by the seed provider).
          </p>
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}
