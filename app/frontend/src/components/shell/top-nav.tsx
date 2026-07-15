import { BarChart3, Gauge, LayoutGrid, MessagesSquare, Radar } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { Link, useLocation } from "react-router-dom"
import { Cyber360Logo } from "@/components/brand/cyber360-logo"
import { useGenie } from "@/components/genie/genie-provider"
import { ThemeToggle } from "@/components/shell/theme-toggle"
import { UserAvatar } from "@/components/shell/user-avatar"
import { Button } from "@/components/ui/button"
import { useConfig } from "@/config/ConfigProvider"
import { domainIcon } from "@/config/icons"
import { cn } from "@/lib/utils"

/**
 * Top navigation. Every nav target derives from the runtime config:
 * - the domain drill-down dropdown iterates config.domains (no hardcoded list),
 * - the SOC link is shown only when features.socViewEnabled is true,
 * - the Chats button and theme toggle honor feature flags.
 */
export function TopNav() {
  const { config } = useConfig()
  const { pathname } = useLocation()

  const isActive = (href: string) =>
    pathname === href || (href === "/scorecard" && pathname === "/")

  const managerActive =
    pathname === "/manager" || pathname.startsWith("/domain/")

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-card/85 backdrop-blur supports-[backdrop-filter]:bg-card/70">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-6 px-4 sm:px-6 lg:px-8">
        <Link to="/scorecard" className="shrink-0">
          <Cyber360Logo />
        </Link>

        <nav className="flex items-center gap-1">
          <NavLink
            href="/scorecard"
            label="CISO Scorecard"
            icon={LayoutGrid}
            active={isActive("/scorecard")}
          />

          {/* Manager View with a hover dropdown to jump into a domain. */}
          <div className="group relative">
            <Link
              to="/manager"
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                managerActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <BarChart3 className="size-4" />
              <span className="hidden sm:inline">Manager View</span>
            </Link>

            <div className="invisible absolute left-0 top-full z-50 pt-2 opacity-0 transition-all duration-150 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
              <div className="w-64 overflow-hidden rounded-xl border border-border bg-popover p-1.5 shadow-lg">
                <p className="px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Drill into a domain
                </p>
                {config.domains.map((d) => {
                  const Icon = domainIcon(d.icon)
                  const href = `/domain/${d.key}`
                  return (
                    <Link
                      key={d.key}
                      to={href}
                      className={cn(
                        "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
                        pathname === href
                          ? "bg-primary/10 text-primary"
                          : "text-foreground hover:bg-muted",
                      )}
                    >
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                        <Icon className="size-4" />
                      </span>
                      {d.label}
                    </Link>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Operational Performance -- not yet available. */}
          <ComingSoonLink label="Operational Performance" icon={Gauge} />

          {/* SOC Analyst -- only when the feature flag is enabled. */}
          {config.features.socViewEnabled ? (
            <NavLink
              href="/soc"
              label="SOC Analyst"
              icon={Radar}
              active={isActive("/soc")}
            />
          ) : (
            <ComingSoonLink label="SOC Analyst" icon={Radar} />
          )}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {config.features.genieEnabled ? <ChatHistoryButton /> : null}
          {config.features.themeToggle ? <ThemeToggle /> : null}
          <UserAvatar />
        </div>
      </div>
    </header>
  )
}

function ChatHistoryButton() {
  const { openDrawer, sessions } = useGenie()
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={openDrawer}
      aria-haspopup="dialog"
      aria-controls="genie-chat-panel"
      title="Open Genie chats"
      className="relative gap-2"
    >
      <MessagesSquare className="size-4" />
      <span className="hidden sm:inline">Chats</span>
      {sessions.length > 0 ? (
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-semibold text-primary-foreground tabular-nums">
          {sessions.length}
        </span>
      ) : null}
    </Button>
  )
}

function ComingSoonLink({ label, icon: Icon }: { label: string; icon: LucideIcon }) {
  return (
    <span
      aria-disabled="true"
      title="Coming soon"
      className="group/soon flex cursor-not-allowed items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground/50"
    >
      <Icon className="size-4" />
      <span className="hidden sm:inline">{label}</span>
      <span className="grid grid-cols-[0fr] transition-all duration-200 group-hover/soon:grid-cols-[1fr] group-focus-within/soon:grid-cols-[1fr]">
        <span className="overflow-hidden">
          <span className="whitespace-nowrap rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Coming soon!
          </span>
        </span>
      </span>
    </span>
  )
}

function NavLink({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string
  label: string
  icon: LucideIcon
  active: boolean
}) {
  return (
    <Link
      to={href}
      className={cn(
        "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      <Icon className="size-4" />
      <span className="hidden sm:inline">{label}</span>
    </Link>
  )
}
