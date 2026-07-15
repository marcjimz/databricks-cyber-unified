import { Check, X } from "lucide-react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { AccountRow } from "@/lib/contracts"
import { cn } from "@/lib/utils"

const STATUS_STYLES: Record<string, string> = {
  active: "bg-success-muted text-success",
  dormant: "bg-warning-muted text-warning",
  orphaned: "bg-danger-muted text-danger",
  disabled: "bg-muted text-muted-foreground",
}

function Pill({ children, className }: { children: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold capitalize",
        className,
      )}
    >
      {children}
    </span>
  )
}

function Bool({ value }: { value: boolean }) {
  return value ? (
    <Check className="size-4 text-success" />
  ) : (
    <X className="size-4 text-muted-foreground/50" />
  )
}

export function AccountsTable({ rows }: { rows: AccountRow[] }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Account</TableHead>
            <TableHead>Org unit</TableHead>
            <TableHead className="text-center">Privileged</TableHead>
            <TableHead className="text-center">SSO</TableHead>
            <TableHead className="text-center">PAM vault</TableHead>
            <TableHead>Last activity</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.uid}>
              <TableCell className="font-mono text-xs text-foreground">
                {r.name}
              </TableCell>
              <TableCell className="text-sm">{r.org_unit}</TableCell>
              <TableCell>
                <div className="flex justify-center">
                  <Bool value={r.privileged} />
                </div>
              </TableCell>
              <TableCell>
                <div className="flex justify-center">
                  <Bool value={r.sso_enrolled} />
                </div>
              </TableCell>
              <TableCell>
                <div className="flex justify-center">
                  <Bool value={r.in_pam_vault} />
                </div>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {r.last_activity
                  ? new Date(r.last_activity).toISOString().slice(0, 10)
                  : "—"}
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
