import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { useConfig } from "@/config/ConfigProvider"
import {
  genieDomainList,
  genieDomainMap,
  type GenieDomainConfig,
  type GenieDomainKey,
} from "@/lib/genie/config"

export interface GenieSession {
  id: string
  domainKey: GenieDomainKey
  title: string
  createdAt: number
}

interface GenieContextValue {
  open: boolean
  sessions: GenieSession[]
  activeId: string | null
  activeSession: GenieSession | null
  openDrawer: () => void
  closeDrawer: () => void
  /** Open the drawer scoped to a domain: reuse its latest chat or start one. */
  openForDomain: (domainKey: GenieDomainKey) => void
  /** Always start a brand-new chat for the given domain. */
  newChat: (domainKey: GenieDomainKey) => void
  selectChat: (id: string) => void
  renameSession: (id: string, title: string) => void
}

const GenieContext = createContext<GenieContextValue | null>(null)

let counter = 0
function makeId() {
  counter += 1
  return `chat_${Date.now().toString(36)}_${counter}`
}

function defaultTitle(
  domains: Record<string, GenieDomainConfig>,
  domainKey: GenieDomainKey,
  index: number,
): string {
  return `${domains[domainKey]?.short ?? "New"} chat ${index}`
}

/**
 * Seeded historical chats so the history rail is populated. Titles are drawn
 * from each domain's configured Genie starter prompts, so the seeds follow
 * whatever domains the config defines.
 */
function seedSessions(domainList: GenieDomainConfig[]): GenieSession[] {
  const now = Date.now()
  const hour = 60 * 60 * 1000
  const sessions: GenieSession[] = []
  let age = 2
  for (const domain of domainList) {
    const starter = domain.starters[0]
    if (!starter) continue
    sessions.push({
      id: makeId(),
      domainKey: domain.key,
      title: starter.replace(/\?$/, ""),
      createdAt: now - age * hour,
    })
    age *= 12
  }
  return sessions
}

export function GenieProvider({ children }: { children: ReactNode }) {
  const { config } = useConfig()
  const domainMap = useMemo(() => genieDomainMap(config), [config])
  const [open, setOpen] = useState(false)
  const [sessions, setSessions] = useState<GenieSession[]>(() =>
    seedSessions(genieDomainList(config)),
  )
  const [activeId, setActiveId] = useState<string | null>(null)

  const openDrawer = useCallback(() => setOpen(true), [])
  const closeDrawer = useCallback(() => setOpen(false), [])

  const newChat = useCallback((domainKey: GenieDomainKey) => {
    const session: GenieSession = {
      id: makeId(),
      domainKey,
      title: "",
      createdAt: Date.now(),
    }
    setSessions((prev) => {
      const count = prev.filter((s) => s.domainKey === domainKey).length + 1
      return [
        { ...session, title: defaultTitle(domainMap, domainKey, count) },
        ...prev,
      ]
    })
    setActiveId(session.id)
    setOpen(true)
  }, [domainMap])

  const openForDomain = useCallback(
    (domainKey: GenieDomainKey) => {
      setSessions((prev) => {
        const existing = prev
          .filter((s) => s.domainKey === domainKey)
          .sort((a, b) => b.createdAt - a.createdAt)[0]
        if (existing) {
          setActiveId(existing.id)
          return prev
        }
        const count = prev.filter((s) => s.domainKey === domainKey).length + 1
        const session: GenieSession = {
          id: makeId(),
          domainKey,
          title: defaultTitle(domainMap, domainKey, count),
          createdAt: Date.now(),
        }
        queueMicrotask(() => setActiveId(session.id))
        return [session, ...prev]
      })
      setOpen(true)
    },
    [domainMap],
  )

  const selectChat = useCallback((id: string) => {
    setActiveId(id)
    setOpen(true)
  }, [])

  const renameSession = useCallback((id: string, title: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title } : s)),
    )
  }, [])

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeId) ?? null,
    [sessions, activeId],
  )

  const value = useMemo<GenieContextValue>(
    () => ({
      open,
      sessions,
      activeId,
      activeSession,
      openDrawer,
      closeDrawer,
      openForDomain,
      newChat,
      selectChat,
      renameSession,
    }),
    [
      open,
      sessions,
      activeId,
      activeSession,
      openDrawer,
      closeDrawer,
      openForDomain,
      newChat,
      selectChat,
      renameSession,
    ],
  )

  return <GenieContext.Provider value={value}>{children}</GenieContext.Provider>
}

export function useGenie() {
  const ctx = useContext(GenieContext)
  if (!ctx) throw new Error("useGenie must be used within GenieProvider")
  return ctx
}
