import { ChevronDown, MessagesSquare, Plus, Sparkles, X } from "lucide-react"
import { useEffect, useMemo } from "react"
import { useGenie, type GenieSession } from "@/components/genie/genie-provider"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useConfig } from "@/config/ConfigProvider"
import {
  genieDomainList,
  genieDomainMap,
  type GenieDomainConfig,
} from "@/lib/genie/config"
import { cn } from "@/lib/utils"

function timeAgo(ts: number): string {
  const diff = Date.now() - ts
  const min = Math.round(diff / 60000)
  if (min < 1) return "just now"
  if (min < 60) return `${min}m ago`
  const hrs = Math.round(min / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  return `${days}d ago`
}

export function GenieDrawer() {
  const { config } = useConfig()
  const domainList = useMemo(() => genieDomainList(config), [config])
  const {
    open,
    closeDrawer,
    sessions,
    activeId,
    activeSession,
    selectChat,
  } = useGenie()

  // Close on Escape for a natural drawer experience.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDrawer()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, closeDrawer])

  return (
    <>
      {/* Backdrop */}
      {open ? (
        <button
          type="button"
          aria-label="Close chat"
          onClick={closeDrawer}
          className="fixed inset-0 z-[60] bg-foreground/40 backdrop-blur-sm"
        />
      ) : null}

      {/* Full-height side drawer over the entire screen, header included. */}
      <aside
        id="genie-chat-panel"
        aria-hidden={!open}
        className={cn(
          "fixed inset-y-0 right-0 z-[70] flex w-full max-w-[820px] flex-col border-l border-border bg-card shadow-2xl transition-transform duration-300 ease-in-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex size-7 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Sparkles className="size-4" />
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold text-foreground">
                Genie · Chat on this Data
              </p>
              <p className="text-xs text-muted-foreground">
                Chat on Your Domain
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close chat"
            onClick={closeDrawer}
            className="size-8 text-muted-foreground"
          >
            <X className="size-4" />
          </Button>
        </header>

        <div className="flex min-h-0 flex-1">
          {/* History rail */}
          <div className="flex w-[240px] shrink-0 flex-col border-r border-border bg-muted/30">
            <div className="flex items-center justify-between gap-2 px-3 py-2.5">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <MessagesSquare className="size-3.5" />
                Chat history
              </span>
              <NewChatMenu />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
              {domainList.map((domain) => {
                const domainSessions = sessions
                  .filter((s) => s.domainKey === domain.key)
                  .sort((a, b) => b.createdAt - a.createdAt)
                return (
                  <div key={domain.key} className="mb-2">
                    <div className="px-2 py-1.5">
                      <span className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {domain.short}
                      </span>
                    </div>
                    {domainSessions.length === 0 ? (
                      <p className="px-2 py-1 text-xs text-muted-foreground/70">
                        No chats yet
                      </p>
                    ) : (
                      domainSessions.map((s) => (
                        <SessionRow
                          key={s.id}
                          session={s}
                          active={s.id === activeId}
                          onSelect={() => selectChat(s.id)}
                        />
                      ))
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Active chat pane */}
          <div className="min-h-0 min-w-0 flex-1">
            {activeSession ? (
              <ChatPane key={activeSession.id} session={activeSession} />
            ) : (
              <EmptyChatState />
            )}
          </div>
        </div>
      </aside>
    </>
  )
}

function SessionRow({
  session,
  active,
  onSelect,
}: {
  session: GenieSession
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full flex-col gap-0.5 rounded-lg px-2 py-1.5 text-left transition-colors",
        active
          ? "bg-primary/10 text-primary"
          : "text-foreground hover:bg-muted",
      )}
    >
      <span className="truncate text-sm font-medium">{session.title}</span>
      <span
        className={cn(
          "text-[11px]",
          active ? "text-primary/70" : "text-muted-foreground",
        )}
      >
        {timeAgo(session.createdAt)}
      </span>
    </button>
  )
}

function NewChatMenu({
  variant = "icon",
}: {
  variant?: "icon" | "full"
}) {
  const { config } = useConfig()
  const domainList = useMemo(() => genieDomainList(config), [config])
  const { newChat } = useGenie()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          buttonVariants({
            variant: variant === "full" ? "default" : "outline",
            size: "sm",
          }),
          variant === "full" ? "gap-2" : "h-7 gap-1.5 px-2 text-xs",
        )}
      >
        <Plus className="size-3.5" />
        New chat
        {variant === "full" ? (
          <ChevronDown className="size-3.5 opacity-70" />
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Start a chat on
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {domainList.map((d) => (
            <DropdownMenuItem
              key={d.key}
              onClick={() => newChat(d.key)}
              className="gap-2"
            >
              <span className="flex size-5 items-center justify-center rounded bg-primary/10 text-primary">
                <Plus className="size-3" />
              </span>
              {d.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ChatPane({ session }: { session: GenieSession }) {
  const { config } = useConfig()
  const domain = genieDomainMap(config)[session.domainKey]
  if (!domain) return <EmptyChatState />
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
          {domain.short}
        </span>
        <p className="truncate text-sm font-medium text-foreground">
          {session.title}
        </p>
      </div>
      <div className="min-h-0 flex-1">
        {domain.embedUrl ? (
          <iframe
            title={`Databricks Genie Space — ${domain.label}`}
            src={domain.embedUrl}
            className="h-full w-full border-0"
            allow="clipboard-write; clipboard-read"
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <GenieConfigState domain={domain} />
        )}
      </div>
    </div>
  )
}

function EmptyChatState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <span className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Sparkles className="size-6" />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-semibold text-foreground">
          Start a conversation
        </p>
        <p className="max-w-xs text-pretty text-xs leading-relaxed text-muted-foreground">
          Pick a past chat from the history, or start a new Genie chat scoped to
          a security domain.
        </p>
      </div>
      <NewChatMenu variant="full" />
    </div>
  )
}

function GenieConfigState({ domain }: { domain: GenieDomainConfig }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <span className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Sparkles className="size-6" />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-semibold text-foreground">
          Connect the {domain.short} Genie Space
        </p>
        <p className="max-w-sm text-pretty text-xs leading-relaxed text-muted-foreground">
          This pane embeds the{" "}
          <span className="font-medium text-foreground">{domain.label}</span>{" "}
          Genie Space so analysts can ask natural-language questions against the
          same Metric Views powering these metrics.
        </p>
      </div>
      <div className="w-full max-w-sm rounded-lg border border-dashed border-border bg-muted/40 p-3 text-left">
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Set the embed URL
        </p>
        <code className="block break-all font-mono text-[11px] text-foreground">
          {domain.spaceId ? `Genie Space ${domain.spaceId}` : "genie.embed_url (cyber360.yaml)"}
        </code>
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          Configure this domain&apos;s <code className="font-mono">genie.embed_url</code>{" "}
          in <code className="font-mono">cyber360.yaml</code> (Genie Space &rarr;
          Share &rarr; Embed URL). The workspace must allow framing this app&apos;s
          origin.
        </p>
      </div>
      <div className="w-full max-w-sm text-left">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Try asking
        </p>
        <ul className="space-y-1">
          {domain.starters.map((s) => (
            <li
              key={s}
              className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-muted-foreground"
            >
              {s}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
