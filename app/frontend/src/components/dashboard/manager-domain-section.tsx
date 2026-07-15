import { ArrowRight } from "lucide-react"
import { Link } from "react-router-dom"
import { KpiCard } from "@/components/dashboard/kpi-card"
import {
  ComplianceSignal,
  tallyCompliance,
} from "@/components/dashboard/status-badge"
import { useConfig } from "@/config/ConfigProvider"
import { domainIcon } from "@/config/icons"
import type { DomainMetricsResponse } from "@/lib/contracts"

export function ManagerDomainSection({
  metrics,
}: {
  metrics: DomainMetricsResponse
}) {
  const { getDomain } = useConfig()
  const Icon = domainIcon(getDomain(metrics.key)?.icon ?? "")
  const tally = tallyCompliance(metrics.kpis)
  return (
    <section className="rounded-2xl border border-border bg-card p-5 sm:p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon className="size-5" />
          </span>
          <h2 className="font-heading text-lg font-semibold text-foreground">
            {metrics.label}
          </h2>
          <ComplianceSignal green={tally.green} red={tally.red} />
        </div>
        <Link
          to={`/domain/${metrics.key}`}
          className="flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          Open deep dive <ArrowRight className="size-4" />
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        {metrics.kpis.map((kpi) => (
          <KpiCard key={kpi.key} kpi={kpi} variant="compact" />
        ))}
      </div>
    </section>
  )
}
