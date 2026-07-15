/**
 * Cyber360 API contracts.
 *
 * These types are the canonical interface between the SPA and the FastAPI
 * backend (`app/api/*.py`, `app/models/*.py`). They MUST match the actual
 * Python responses:
 *   - `/api/config` is camelCase (serialized by hand in api/config.py).
 *   - metrics / tables / incidents data payloads are snake_case (Pydantic
 *     models serialized with their python field names).
 * Every endpoint returns an envelope: `{ data, meta }`.
 */

export type RagStatus = "green" | "amber" | "red"
export type TrendDirection = "up" | "down" | "flat"

/** Reporting-period length selectable on the scorecard & domain views. */
export type ComparisonPeriod = 30 | 60 | 90

/**
 * Period-over-period change for a KPI. Not currently emitted by the seed
 * provider, but kept as a first-class contract so the reporting-period UI is
 * fully wired; rendered as the "Change: ..." line beneath a target when present.
 */
export interface KpiChange {
  label: string
  arrow: TrendDirection
  tone: "positive" | "negative" | "neutral"
}

/* --------------------------------- envelope --------------------------------- */

export interface ResponseMeta {
  generated_at: string
  source: string // "seed" | "databricks"
  metric_views: string[]
  measures: string[]
}

export interface ApiResponse<T> {
  data: T
  meta: ResponseMeta
}

/* ----------------------------------- KPI ------------------------------------ */

export interface TrendInfo {
  direction: TrendDirection
  label: string
}

export interface Kpi {
  key: string
  label: string
  /** Pre-formatted display value, e.g. "99.2%", "142", "12.3d". */
  value: string
  raw: number
  status: RagStatus
  caption?: string
  trend?: TrendInfo | null
  /** Optional period-over-period change (see KpiChange). */
  change?: KpiChange
  lineage: {
    measure: string
    expression: string
    comment: string
  }
}

/* ------------------------------- /api/config -------------------------------- */

export interface ConfigMeasure {
  name: string
  label: string
  expression: string
  comment: string
  format: string
  percentDigits?: number | null
  goal: string
  green?: number | null
  amber?: number | null
  fixedStatus?: string | null
  caption?: string | null
  trend?: TrendInfo | null
}

export interface DomainGenieConfig {
  spaceId?: string | null
  embedUrl?: string | null
  starters: string[]
}

export interface DomainConfig {
  key: string
  label: string
  short: string
  icon: string
  description: string
  genie: DomainGenieConfig
  health: {
    scoreMeasures: string[]
    highlights: string[]
  }
  metricView: {
    name: string
    comment: string
    measures: ConfigMeasure[]
  }
  /**
   * Optional drill-down table type. The current backend does not emit this,
   * so the generic domain page falls back to endpoint probing; declaring it
   * here (e.g. "accounts" | "findings") lets a new domain opt into a table
   * shape with zero page-code changes.
   */
  table?: string | null
}

export interface TopLineKpiRef {
  domain: string
  measure: string
  caption: string
  trend?: TrendInfo | null
}

export interface DashboardConfig {
  org: { name: string; logoPath: string }
  features: {
    genieEnabled: boolean
    socViewEnabled: boolean
    themeToggle: boolean
    lineagePopover: boolean
  }
  topLineKpis: TopLineKpiRef[]
  domains: DomainConfig[]
}

/* -------------------------- /api/metrics/scorecard -------------------------- */

export interface DomainHealthHighlight {
  label: string
  value: string
  status: RagStatus
}

export interface ComplianceCounts {
  green: number
  amber: number
  red: number
  total: number
}

export interface DomainHealth {
  key: string
  label: string
  status: RagStatus
  highlights: DomainHealthHighlight[]
  score: number
  compliance: ComplianceCounts
}

export interface ScorecardResponse {
  org: { name: string; caregivers: number; cyber_staff: number }
  top_line_kpis: Kpi[]
  domains: DomainHealth[]
}

/* ------------------------- /api/metrics/{domainKey} ------------------------- */

/** Python TrendPoint: { day, values: { measure -> value } }. */
export interface TrendPoint {
  day: string
  values: Record<string, number>
}

/** Flattened point consumed by the recharts trend chart. */
export interface ChartTrendPoint {
  date: string
  [seriesKey: string]: string | number
}

export interface BreakdownItem {
  name: string
  value: number
}

export interface DomainMetricsResponse {
  key: string
  label: string
  status: RagStatus
  kpis: Kpi[]
  trends: Record<string, TrendPoint[]>
  breakdowns: Record<string, BreakdownItem[]>
}

/* ------------------------------ table endpoints ----------------------------- */

export interface Paginated<T> {
  rows: T[]
  total: number
  page: number
  page_size: number
}

export interface AccountRow {
  uid: string
  name: string
  org_unit: string
  privileged: boolean
  sso_enrolled: boolean
  in_pam_vault: boolean
  last_activity: string | null
  status: "active" | "dormant" | "orphaned" | "disabled"
}

export interface FindingRow {
  finding_uid: string
  cve: string
  cvss: number
  severity: "Low" | "Medium" | "High" | "Critical"
  is_kev: boolean
  host: string
  asset_type: string
  first_seen: string
  age_days: number
  sla_due: string
  sla_breached: boolean
  fix_available: boolean
  status: "New" | "In Progress" | "Exception" | "Resolved"
}

/* -------------------------------- incidents --------------------------------- */

export interface IncidentRecord {
  uid: string
  priority: "P1" | "P2" | "P3" | "P4"
  label: "Critical" | "High" | "Medium" | "Low"
  domain: string
  status: "open" | "investigating" | "contained" | "resolved"
  mttr_hours: number
  opened_time: number
  title: string
}

export interface IncidentsResponse {
  active: IncidentRecord[]
  open_counts: { P1: number; P2: number; P3: number; P4: number }
  mttr: { P1: string; P2: string; P3: string; P4: string }
}

/** Derived row shape used by the shared severity table component. */
export interface IncidentSeverityRow {
  priority: "P1" | "P2" | "P3" | "P4"
  label: string
  open: number
  mttr: string
}
