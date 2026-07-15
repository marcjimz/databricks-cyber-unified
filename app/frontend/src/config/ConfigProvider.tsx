import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import type { DashboardConfig, DomainConfig } from "@/lib/contracts"
import { fetchData } from "@/lib/fetcher"

interface ConfigContextValue {
  config: DashboardConfig
  /** Look up a domain by key. */
  getDomain: (key: string) => DomainConfig | undefined
}

const ConfigContext = createContext<ConfigContextValue | null>(null)

/**
 * Fetches `/api/config` exactly once at app startup and exposes it via context.
 * Everything the UI renders -- nav items, domains, KPIs, thresholds, labels,
 * genie embeds, feature flags -- derives from this single source. Renders a
 * loading state until the config is ready and a friendly error otherwise.
 */
export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<DashboardConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchData<DashboardConfig>("/api/config")
      .then((c) => {
        if (!cancelled) setConfig(c)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const value = useMemo<ConfigContextValue | null>(() => {
    if (!config) return null
    const byKey = new Map(config.domains.map((d) => [d.key, d]))
    return {
      config,
      getDomain: (key: string) => byKey.get(key),
    }
  }, [config])

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="max-w-md rounded-xl border border-danger/30 bg-danger-muted p-6 text-center">
          <p className="mb-1 font-heading text-lg font-semibold text-danger">
            Unable to load dashboard configuration
          </p>
          <p className="text-sm text-danger/90">{error}</p>
          <p className="mt-3 text-xs text-muted-foreground">
            Ensure the Cyber360 API is running and reachable at{" "}
            <code className="font-mono">/api/config</code>.
          </p>
        </div>
      </div>
    )
  }

  if (!value) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="size-8 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
          <p className="text-sm text-muted-foreground">Loading Cyber360...</p>
        </div>
      </div>
    )
  }

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>
}

export function useConfig(): ConfigContextValue {
  const ctx = useContext(ConfigContext)
  if (!ctx) throw new Error("useConfig must be used within a ConfigProvider")
  return ctx
}
