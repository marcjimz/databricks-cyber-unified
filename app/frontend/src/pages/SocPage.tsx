import { ShieldAlert } from "lucide-react"
import { PageHeader } from "@/components/dashboard/page-header"
import { Card, CardContent } from "@/components/ui/card"

/**
 * SOC analyst triage console. This persona view is OFF by default
 * (`features.soc_view_enabled`) and only mounts when enabled (see App.tsx).
 *
 * The former version was hardcoded to the identity/vulnerability domains and
 * their bespoke table endpoints, which no longer exist -- the app is now fully
 * config-driven off the metric views + `detail_table` config. A config-driven
 * SOC console (assembling each domain's detail table + incidents from config)
 * is intentionally left as a follow-up rather than shipping hardcoded queues.
 */
export function SocPage() {
  return (
    <div>
      <PageHeader
        title="SOC Analyst — Triage Console"
        description="Config-driven SOC console — coming soon"
      />
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <span className="flex size-12 items-center justify-center rounded-xl bg-muted">
            <ShieldAlert className="size-6 text-muted-foreground" />
          </span>
          <p className="max-w-md text-sm text-muted-foreground">
            The SOC triage console is being rebuilt on the generic,
            config-driven data layer (each domain's <code>detail_table</code> +
            incidents). Enable it once a config-driven incident source is wired.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
