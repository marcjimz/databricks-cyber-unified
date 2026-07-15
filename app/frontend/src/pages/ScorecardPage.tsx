import { DomainCard } from "@/components/dashboard/domain-card"
import { KpiCard } from "@/components/dashboard/kpi-card"
import { ErrorState, LoadingGrid } from "@/components/dashboard/loading-state"
import { PageHeader, SectionLabel } from "@/components/dashboard/page-header"
import { ReportingControls } from "@/components/dashboard/reporting-controls"
import { useConfig } from "@/config/ConfigProvider"
import { useApi } from "@/hooks/useApi"
import { useReportingPeriod } from "@/hooks/useReportingPeriod"
import { qs } from "@/lib/fetcher"
import type { ScorecardResponse } from "@/lib/contracts"

/**
 * CISO executive scorecard: top-line KPI tiles + per-domain health cards.
 * The reporting period is threaded into the metrics request as `?period=`.
 */
export function ScorecardPage() {
  const { config } = useConfig()
  const { period, setPeriod } = useReportingPeriod(30)
  const { data, loading, error } = useApi<ScorecardResponse>(
    `/api/metrics/scorecard${qs({ period })}`,
  )

  return (
    <div>
      <PageHeader
        title="CISO Executive Scorecard"
        description={`${config.org.name} cybersecurity posture at a glance`}
        actions={
          <ReportingControls
            value={{ period }}
            onChange={(next) => setPeriod(next.period)}
          />
        }
      />

      <section className="mb-10">
        <SectionLabel>Top-line KPIs</SectionLabel>
        {loading && !data ? (
          <LoadingGrid count={6} />
        ) : error ? (
          <ErrorState />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {data?.top_line_kpis.map((kpi) => (
              <KpiCard key={kpi.key} kpi={kpi} variant="compact" />
            ))}
          </div>
        )}
      </section>

      <section className="mb-10">
        <SectionLabel>Domain health</SectionLabel>
        {data ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {data.domains.map((domain) => (
              <DomainCard key={domain.key} domain={domain} />
            ))}
          </div>
        ) : (
          <LoadingGrid count={2} className="md:grid-cols-2 xl:grid-cols-2" />
        )}
      </section>
    </div>
  )
}
