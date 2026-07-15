import { ArrowRight } from "lucide-react"
import { Link } from "react-router-dom"
import { ComplianceSignal, StatusIcon } from "@/components/dashboard/status-badge"
import { Progress } from "@/components/ui/progress"
import { useConfig } from "@/config/ConfigProvider"
import { domainIcon } from "@/config/icons"
import type { DomainHealth } from "@/lib/contracts"
import { cn } from "@/lib/utils"
import { statusTextClass } from "@/lib/status"

export function DomainCard({ domain }: { domain: DomainHealth }) {
  const { getDomain } = useConfig()
  const Icon = domainIcon(getDomain(domain.key)?.icon ?? "")
  return (
    <Link
      to={`/domain/${domain.key}`}
      className="group flex flex-col gap-4 rounded-2xl border border-border bg-card p-5 transition-all hover:border-primary/40 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon className="size-5" />
          </span>
          <h3 className="font-heading text-base font-semibold text-foreground">
            {domain.label}
          </h3>
        </div>
        <ComplianceSignal
          green={domain.compliance.green}
          red={domain.compliance.red}
        />
      </div>

      <dl className="space-y-2.5">
        {domain.highlights.map((h) => (
          <div key={h.label} className="flex items-center justify-between gap-2">
            <dt className="text-sm text-muted-foreground">{h.label}</dt>
            <dd
              className={cn(
                "flex items-center gap-1.5 text-sm font-semibold tabular-nums",
                statusTextClass(h.status),
              )}
            >
              <StatusIcon status={h.status} className="size-3.5" />
              {h.value}
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-auto space-y-2">
        <Progress value={domain.score} className="h-1.5" />
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            Posture score {domain.score}/100
          </span>
          <span className="flex items-center gap-1 text-xs font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
            Drill in <ArrowRight className="size-3" />
          </span>
        </div>
      </div>
    </Link>
  )
}
