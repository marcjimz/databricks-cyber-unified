import { ErrorState, LoadingGrid } from "@/components/dashboard/loading-state"
import { ManagerDomainSection } from "@/components/dashboard/manager-domain-section"
import { PageHeader, SectionLabel } from "@/components/dashboard/page-header"
import { ReportingControls } from "@/components/dashboard/reporting-controls"
import { useConfig } from "@/config/ConfigProvider"
import { useApi } from "@/hooks/useApi"
import { useReportingPeriod } from "@/hooks/useReportingPeriod"
import { qs } from "@/lib/fetcher"
import type { ComparisonPeriod, DomainMetricsResponse } from "@/lib/contracts"

/**
 * One section per domain. Iterates config.domains, so adding a domain in YAML
 * automatically adds it to the manager view -- no per-domain page code.
 */
function DomainMetricsSection({
  domainKey,
  period,
}: {
  domainKey: string
  period: ComparisonPeriod
}) {
  const { data, loading, error } = useApi<DomainMetricsResponse>(
    `/api/metrics/${domainKey}${qs({ period })}`,
  )

  if (loading && !data) return <LoadingGrid />
  if (error) return <ErrorState />
  if (!data) return null
  return <ManagerDomainSection metrics={data} />
}

export function ManagerPage() {
  const { config } = useConfig()
  const { period, setPeriod } = useReportingPeriod(30)

  return (
    <div>
      <PageHeader
        title="Manager — Domain Deep Dive"
        description="Detailed Metric View measures for the in-scope cybersecurity domains"
        actions={
          <ReportingControls
            value={{ period }}
            onChange={(next) => setPeriod(next.period)}
          />
        }
      />

      <SectionLabel>Security domains</SectionLabel>

      <div className="space-y-6">
        {config.domains.map((domain) => (
          <DomainMetricsSection
            key={domain.key}
            domainKey={domain.key}
            period={period}
          />
        ))}
      </div>
    </div>
  )
}
