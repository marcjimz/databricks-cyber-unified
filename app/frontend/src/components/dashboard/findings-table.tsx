import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { FindingRow } from "@/lib/contracts"
import { cn } from "@/lib/utils"

const SEVERITY_STYLES: Record<string, string> = {
  Critical: "bg-danger-muted text-danger",
  High: "bg-warning-muted text-warning",
  Medium: "bg-primary/10 text-primary",
  Low: "bg-muted text-muted-foreground",
}

const STATUS_STYLES: Record<string, string> = {
  New: "bg-danger-muted text-danger",
  "In Progress": "bg-primary/10 text-primary",
  Exception: "bg-warning-muted text-warning",
  Resolved: "bg-success-muted text-success",
}

function Pill({ children, className }: { children: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
        className,
      )}
    >
      {children}
    </span>
  )
}

export function FindingsTable({ rows }: { rows: FindingRow[] }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>CVE</TableHead>
            <TableHead className="text-right">CVSS</TableHead>
            <TableHead>Severity</TableHead>
            <TableHead>Host</TableHead>
            <TableHead className="text-right">Age</TableHead>
            <TableHead>SLA</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.finding_uid}>
              <TableCell className="font-mono text-xs">
                <div className="flex items-center gap-1.5">
                  {r.cve}
                  {r.is_kev ? (
                    <span className="rounded bg-danger px-1 py-0.5 text-[10px] font-bold uppercase text-danger-foreground">
                      KEV
                    </span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums font-medium">
                {r.cvss.toFixed(1)}
              </TableCell>
              <TableCell>
                <Pill className={SEVERITY_STYLES[r.severity]}>{r.severity}</Pill>
              </TableCell>
              <TableCell className="text-sm">
                <span className="text-foreground">{r.host}</span>
                <span className="block text-xs text-muted-foreground">
                  {r.asset_type}
                </span>
              </TableCell>
              <TableCell className="text-right tabular-nums text-sm">
                {r.age_days}d
              </TableCell>
              <TableCell>
                <span
                  className={cn(
                    "text-xs font-medium",
                    r.sla_breached ? "text-danger" : "text-muted-foreground",
                  )}
                >
                  {r.sla_breached ? "Breached" : "On track"}
                </span>
              </TableCell>
              <TableCell>
                <Pill className={STATUS_STYLES[r.status]}>{r.status}</Pill>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
