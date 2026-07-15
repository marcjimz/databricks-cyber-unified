import { AlertTriangle } from "lucide-react"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { IncidentSeverityRow } from "@/lib/contracts"
import { cn } from "@/lib/utils"

const PRIORITY_STYLES: Record<string, string> = {
  P1: "bg-danger-muted text-danger",
  P2: "bg-warning-muted text-warning",
  P3: "bg-warning-muted text-warning",
  P4: "bg-muted text-muted-foreground",
}

function Pill({ children, className }: { children: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        className,
      )}
    >
      {children}
    </span>
  )
}

export function IncidentSeverityCard({
  rows,
}: {
  rows: IncidentSeverityRow[]
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="size-4 text-accent" />
          Active incidents by severity
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Priority</TableHead>
              <TableHead>Label</TableHead>
              <TableHead className="text-right">Open</TableHead>
              <TableHead className="text-right">MTTR</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.priority}>
                <TableCell>
                  <Pill className={PRIORITY_STYLES[r.priority]}>
                    {r.priority}
                  </Pill>
                </TableCell>
                <TableCell className="font-medium">{r.label}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {r.open}
                </TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">
                  {r.mttr}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

