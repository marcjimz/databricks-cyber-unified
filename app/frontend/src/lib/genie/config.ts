/**
 * Genie Space configuration, derived entirely from the runtime dashboard config
 * (/api/config). Every domain declares a `genie` block (space id, embed URL,
 * starter prompts); this module reshapes that into the structure the chat UI
 * consumes so adding/removing a Genie Space is a config-only change.
 */
import type { DashboardConfig, DomainConfig } from "@/lib/contracts"

/** Domain keys come from config (string-typed, not a fixed union). */
export type GenieDomainKey = string

export interface GenieDomainConfig {
  key: string
  label: string
  short: string
  spaceId?: string | null
  embedUrl?: string | null
  starters: string[]
}

function toGenieConfig(domain: DomainConfig): GenieDomainConfig {
  return {
    key: domain.key,
    label: domain.label,
    short: domain.short,
    spaceId: domain.genie.spaceId,
    embedUrl: domain.genie.embedUrl,
    starters: domain.genie.starters ?? [],
  }
}

/** Ordered list of genie domain configs from the dashboard config. */
export function genieDomainList(config: DashboardConfig): GenieDomainConfig[] {
  return config.domains.map(toGenieConfig)
}

/** Keyed map of genie domain configs. */
export function genieDomainMap(
  config: DashboardConfig,
): Record<string, GenieDomainConfig> {
  return Object.fromEntries(genieDomainList(config).map((d) => [d.key, d]))
}
