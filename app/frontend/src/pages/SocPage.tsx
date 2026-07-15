import { Activity, ShieldAlert, UserX } from "lucide-react"
import { AccountsTable } from "@/components/dashboard/accounts-table"
import { FindingsTable } from "@/components/dashboard/findings-table"
import { IncidentSeverityCard } from "@/components/dashboard/incident-tables"
import { PageHeader, SectionLabel } from "@/components/dashboard/page-header"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useApi } from "@/hooks/useApi"
import { qs } from "@/lib/fetcher"
import type {
  AccountRow,
  FindingRow,
  IncidentsResponse,
  IncidentSeverityRow,
  Paginated,
} from "@/lib/contracts"

/**
 * SOC analyst triage console. Aggregates the live OCSF event queues that a
 * front-line analyst works: KEV findings, critical SLA breaches, orphaned
 * accounts, and active incidents. Table endpoints are the same generic ones the
 * domain pages use (`/api/{domain}/{table}`) with query filters.
 */
const SEVERITY_LABELS: Record<IncidentSeverityRow["priority"], string> = {
  P1: "Critical",
  P2: "High",
  P3: "Medium",
  P4: "Low",
}

/**
 * The backend exposes incidents as parallel `open_counts` / `mttr` maps keyed by
 * priority. Fold them into the row shape the shared severity table renders.
 */
function toSeverityRows(incidents: IncidentsResponse): IncidentSeverityRow[] {
  return (["P1", "P2", "P3", "P4"] as const).map((priority) => ({
    priority,
    label: SEVERITY_LABELS[priority],
    open: incidents.open_counts[priority] ?? 0,
    mttr: incidents.mttr[priority] ?? "—",
  }))
}

export function SocPage() {
  const kev = useApi<Paginated<FindingRow>>(
    `/api/vulnerability/findings${qs({ kevOnly: true, page_size: 10 })}`,
  )
  const breached = useApi<Paginated<FindingRow>>(
    `/api/vulnerability/findings${qs({
      slaBreachedOnly: true,
      severity: "Critical",
      page_size: 10,
    })}`,
  )
  const orphaned = useApi<Paginated<AccountRow>>(
    `/api/identity/accounts${qs({ status: "orphaned", page_size: 8 })}`,
  )
  const incidents = useApi<IncidentsResponse>("/api/incidents")

  const queues = [
    {
      label: "KEV exposures",
      value: kev.data?.total ?? "—",
      icon: ShieldAlert,
      tone: "text-danger",
    },
    {
      label: "Critical SLA breaches",
      value: breached.data?.total ?? "—",
      icon: Activity,
      tone: "text-danger",
    },
    {
      label: "Orphaned accounts",
      value: orphaned.data?.total ?? "—",
      icon: UserX,
      tone: "text-warning",
    },
  ]

  return (
    <div>
      <PageHeader
        title="SOC Analyst — Triage Console"
        description="Live OCSF event queues across Identity and Vulnerability domains"
      />

      <section className="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {queues.map((q) => {
          const Icon = q.icon
          return (
            <Card key={q.label}>
              <CardContent className="flex items-center gap-4 py-5">
                <span className="flex size-11 items-center justify-center rounded-xl bg-muted">
                  <Icon className={`size-5 ${q.tone}`} />
                </span>
                <div>
                  <p className="font-heading text-2xl font-bold tabular-nums text-foreground">
                    {q.value}
                  </p>
                  <p className="text-sm text-muted-foreground">{q.label}</p>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </section>

      <section className="mb-8">
        <SectionLabel>
          Known Exploited Vulnerabilities — immediate action
        </SectionLabel>
        <Card>
          <CardContent className="pt-6">
            {kev.data ? (
              <FindingsTable rows={kev.data.rows} />
            ) : (
              <div className="h-48 animate-pulse rounded-lg bg-muted/50" />
            )}
          </CardContent>
        </Card>
      </section>

      <section className="mb-8 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div>
          <SectionLabel>Active incidents</SectionLabel>
          {incidents.data ? (
            <IncidentSeverityCard rows={toSeverityRows(incidents.data)} />
          ) : (
            <div className="h-64 animate-pulse rounded-xl bg-muted/50" />
          )}
        </div>
        <div>
          <SectionLabel>Orphaned account queue</SectionLabel>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <UserX className="size-4 text-warning" />
                Pending deactivation
              </CardTitle>
            </CardHeader>
            <CardContent>
              {orphaned.data ? (
                <AccountsTable rows={orphaned.data.rows} />
              ) : (
                <div className="h-48 animate-pulse rounded-lg bg-muted/50" />
              )}
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  )
}
