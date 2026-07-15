import { useEffect, useMemo, useState } from "react"
import { Navigate, useParams } from "react-router-dom"
import {
  HorizontalBarChart,
  SeverityDonut,
} from "@/components/charts/breakdown-charts"
import { ChartCard } from "@/components/charts/chart-card"
import { TrendAreaChart } from "@/components/charts/trend-area-chart"
import { AccountsTable } from "@/components/dashboard/accounts-table"
import { DrillBreadcrumb } from "@/components/dashboard/drill-breadcrumb"
import { FindingsTable } from "@/components/dashboard/findings-table"
import { KpiCard } from "@/components/dashboard/kpi-card"
import { ErrorState, LoadingGrid } from "@/components/dashboard/loading-state"
import { PageHeader, SectionLabel } from "@/components/dashboard/page-header"
import { ReportingControls } from "@/components/dashboard/reporting-controls"
import {
  ComplianceSignal,
  tallyCompliance,
} from "@/components/dashboard/status-badge"
import { GenieChatDock } from "@/components/genie/genie-chat-dock"
import { Card, CardContent } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { ChartConfig } from "@/components/ui/chart"
import { useConfig } from "@/config/ConfigProvider"
import { useApi } from "@/hooks/useApi"
import { useReportingPeriod } from "@/hooks/useReportingPeriod"
import { qs } from "@/lib/fetcher"
import type {
  AccountRow,
  ChartTrendPoint,
  ComparisonPeriod,
  DomainMetricsResponse,
  FindingRow,
  Kpi,
  Paginated,
  TrendPoint,
} from "@/lib/contracts"

/**
 * Generic, config-driven domain drill-down. Reads the `:key` route param, then
 * renders EVERYTHING from `/api/config` + `/api/metrics/:key` -- KPIs, whatever
 * trend series and breakdowns the domain returns, the Metric View definitions,
 * and a drill-down table. There is deliberately NO per-domain branching
 * (`if key === "identity"`) in this file: adding a domain in cyber360.yaml makes
 * `/domain/<newkey>` render with zero page-code changes (SKILL.md §3).
 */

/* Rotating palette so each dynamically-discovered series gets a stable color. */
const SERIES_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
]

/* Severity-ish names map onto the semantic status palette when present. */
const SEMANTIC_COLORS: Record<string, string> = {
  critical: "var(--danger)",
  high: "var(--warning)",
  medium: "var(--chart-1)",
  low: "var(--muted-foreground)",
}

function titleCase(key: string): string {
  return key
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim()
}

function seriesColor(key: string, index: number): string {
  return SEMANTIC_COLORS[key.toLowerCase()] ?? SERIES_COLORS[index % SERIES_COLORS.length]
}

/**
 * Python trends are `{ day, values: { series -> n } }`. Flatten into the
 * `{ date, <series>: n }` rows recharts consumes, and build a ChartConfig from
 * whatever series keys actually appear in the data (union across points).
 */
function buildTrend(points: TrendPoint[]): {
  data: ChartTrendPoint[]
  config: ChartConfig
} {
  const seriesKeys = new Set<string>()
  for (const p of points) {
    for (const k of Object.keys(p.values ?? {})) seriesKeys.add(k)
  }
  const keys = Array.from(seriesKeys)
  const config: ChartConfig = {}
  keys.forEach((k, i) => {
    config[k] = { label: titleCase(k), color: seriesColor(k, i) }
  })
  const data: ChartTrendPoint[] = points.map((p) => {
    const row: ChartTrendPoint = { date: p.day }
    for (const k of keys) row[k] = p.values?.[k] ?? 0
    return row
  })
  return { data, config }
}

/** Percent-shaped trends (values that never exceed 100) get a fixed 0-100 axis. */
function looksLikePercent(points: TrendPoint[]): boolean {
  let sawValue = false
  for (const p of points) {
    for (const v of Object.values(p.values ?? {})) {
      sawValue = true
      if (v > 100 || v < 0) return false
    }
  }
  return sawValue
}

/** A breakdown named like a severity split renders as a donut, else a bar chart. */
function isSeverityBreakdown(name: string, items: { name: string }[]): boolean {
  if (/sever/i.test(name)) return true
  const labels = items.map((i) => i.name.toLowerCase())
  const severityLabels = ["critical", "high", "medium", "low"]
  return labels.length > 0 && labels.every((l) => severityLabels.includes(l))
}

type TableKind = "accounts" | "findings" | "none"

/**
 * Decide which drill-down table (if any) a domain uses. Prefers an explicit
 * config hint (`domain.table`), otherwise probes the two known generic table
 * endpoints. Probing keeps the page working for the current backend, which does
 * not emit a `table` field, while the config hint lets new domains opt in with
 * zero code.
 */
function useDomainTableKind(key: string, configured?: string | null): TableKind {
  const [probed, setProbed] = useState<TableKind | null>(null)

  const explicit: TableKind | null =
    configured === "accounts" || configured === "findings"
      ? configured
      : configured === "none"
        ? "none"
        : null

  useEffect(() => {
    if (explicit) {
      setProbed(explicit)
      return
    }
    let cancelled = false
    setProbed(null)
    // Probe accounts first, then findings. HEAD-like GET with page_size=1.
    const tryProbe = async () => {
      const probe = async (kind: "accounts" | "findings") => {
        const path =
          kind === "accounts"
            ? `/api/${key}/accounts${qs({ page_size: 1 })}`
            : `/api/${key}/findings${qs({ page_size: 1 })}`
        const res = await fetch(path)
        return res.ok
      }
      try {
        if (await probe("accounts")) {
          if (!cancelled) setProbed("accounts")
          return
        }
      } catch {
        /* fall through to findings */
      }
      try {
        if (await probe("findings")) {
          if (!cancelled) setProbed("findings")
          return
        }
      } catch {
        /* no table */
      }
      if (!cancelled) setProbed("none")
    }
    void tryProbe()
    return () => {
      cancelled = true
    }
  }, [key, explicit])

  return probed ?? "none"
}

/* ----------------------------- table sections ----------------------------- */

const ACCOUNT_FILTERS = ["orphaned", "dormant", "active", "disabled"] as const

function AccountsSection({ domainKey }: { domainKey: string }) {
  const [status, setStatus] =
    useState<(typeof ACCOUNT_FILTERS)[number]>("orphaned")
  const { data } = useApi<Paginated<AccountRow>>(
    `/api/${domainKey}/accounts${qs({ status, page_size: 10 })}`,
  )
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <Tabs value={status} onValueChange={(v) => setStatus(v as typeof status)}>
          <TabsList>
            {ACCOUNT_FILTERS.map((s) => (
              <TabsTrigger key={s} value={s} className="capitalize">
                {s}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        {data ? (
          <>
            <AccountsTable rows={data.rows} />
            <p className="text-xs text-muted-foreground">
              Showing {data.rows.length} of {data.total} {status} accounts
            </p>
          </>
        ) : (
          <div className="h-48 animate-pulse rounded-lg bg-muted/50" />
        )}
      </CardContent>
    </Card>
  )
}

const FINDING_FILTERS = [
  { key: "kev", label: "KEV", params: { kevOnly: true } },
  { key: "critical", label: "Critical", params: { severity: "Critical" } },
  { key: "breached", label: "SLA breached", params: { slaBreachedOnly: true } },
  { key: "high", label: "High", params: { severity: "High" } },
] as const

function FindingsSection({ domainKey }: { domainKey: string }) {
  const [filter, setFilter] =
    useState<(typeof FINDING_FILTERS)[number]["key"]>("kev")
  const active = FINDING_FILTERS.find((f) => f.key === filter) ?? FINDING_FILTERS[0]
  const { data } = useApi<Paginated<FindingRow>>(
    `/api/${domainKey}/findings${qs({ ...active.params, page_size: 12 })}`,
  )
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
          <TabsList>
            {FINDING_FILTERS.map((f) => (
              <TabsTrigger key={f.key} value={f.key}>
                {f.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        {data ? (
          <>
            <FindingsTable rows={data.rows} />
            <p className="text-xs text-muted-foreground">
              Showing {data.rows.length} of {data.total} findings
            </p>
          </>
        ) : (
          <div className="h-48 animate-pulse rounded-lg bg-muted/50" />
        )}
      </CardContent>
    </Card>
  )
}

/* ------------------------------ metric table ------------------------------ */

function MeasureTable({ kpis }: { kpis: Kpi[] }) {
  return (
    <Card>
      <CardContent className="overflow-x-auto pt-6">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Measure</TableHead>
              <TableHead>Meaning</TableHead>
              <TableHead>Expression</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {kpis.map((k) => (
              <TableRow key={k.key}>
                <TableCell className="font-mono text-xs">
                  {k.lineage.measure}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {k.lineage.comment}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {k.lineage.expression}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

/* -------------------------------- charts ---------------------------------- */

function DomainCharts({ metrics }: { metrics: DomainMetricsResponse }) {
  const trendEntries = Object.entries(metrics.trends ?? {})
  const breakdownEntries = Object.entries(metrics.breakdowns ?? {})

  if (trendEntries.length === 0 && breakdownEntries.length === 0) return null

  return (
    <section className="mb-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
      {trendEntries.map(([name, points]) => {
        const { data, config } = buildTrend(points)
        const pct = looksLikePercent(points)
        return (
          <ChartCard
            key={`trend-${name}`}
            title={`${titleCase(name)} trend`}
            description="Daily series over the reporting period"
            legend={Object.entries(config).map(([, v]) => ({
              label: String(v.label),
              color: String(v.color),
            }))}
          >
            <TrendAreaChart
              data={data}
              config={config}
              domainMax={pct ? 100 : undefined}
              unit={pct ? "%" : undefined}
            />
          </ChartCard>
        )
      })}

      {breakdownEntries.map(([name, items]) => (
        <ChartCard
          key={`breakdown-${name}`}
          title={titleCase(name)}
          description="Current distribution"
        >
          {isSeverityBreakdown(name, items) ? (
            <SeverityDonut data={items} />
          ) : (
            <HorizontalBarChart data={items} />
          )}
        </ChartCard>
      ))}
    </section>
  )
}

/* --------------------------------- page ----------------------------------- */

export function DomainPage() {
  const { key = "" } = useParams<{ key: string }>()
  const { config, getDomain } = useConfig()
  const { period, setPeriod } = useReportingPeriod(30)

  const domain = getDomain(key)

  const { data, loading, error } = useApi<DomainMetricsResponse>(
    key ? `/api/metrics/${key}${qs({ period })}` : null,
  )

  const tableKind = useDomainTableKind(key, domain?.table)

  const compliance = useMemo(
    () => (data ? tallyCompliance(data.kpis) : null),
    [data],
  )

  // Unknown domain key -> back to the manager overview rather than a broken page.
  if (config.domains.length > 0 && !domain) {
    return <Navigate to="/manager" replace />
  }

  const title = domain?.label ?? data?.label ?? titleCase(key)

  return (
    <div>
      <DrillBreadcrumb
        items={[
          { label: "CISO Scorecard", href: "/scorecard" },
          { label: "Security Domains", href: "/manager" },
          { label: title },
        ]}
      />

      <GenieChatDock domainKey={key}>
        <PageHeader
          title={title}
          description={domain?.description ?? ""}
          actions={
            <div className="flex items-center gap-4">
              {compliance ? (
                <ComplianceSignal
                  green={compliance.green}
                  red={compliance.red}
                />
              ) : null}
              <ReportingControls
                value={{ period }}
                onChange={(next: { period: ComparisonPeriod }) =>
                  setPeriod(next.period)
                }
              />
            </div>
          }
        />

        <section className="mb-8">
          <SectionLabel>Key metrics</SectionLabel>
          {loading && !data ? (
            <LoadingGrid />
          ) : error ? (
            <ErrorState />
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
              {data?.kpis.map((kpi) => (
                <KpiCard key={kpi.key} kpi={kpi} variant="compact" />
              ))}
            </div>
          )}
        </section>

        {data ? <DomainCharts metrics={data} /> : null}

        {tableKind !== "none" ? (
          <section className="mb-8">
            <SectionLabel>
              {tableKind === "accounts" ? "Account inventory" : "Finding queue"}
            </SectionLabel>
            {tableKind === "accounts" ? (
              <AccountsSection domainKey={key} />
            ) : (
              <FindingsSection domainKey={key} />
            )}
          </section>
        ) : null}

        {data ? (
          <section className="mb-2">
            <SectionLabel>Metric View definitions</SectionLabel>
            <MeasureTable kpis={data.kpis} />
          </section>
        ) : null}
      </GenieChatDock>
    </div>
  )
}
