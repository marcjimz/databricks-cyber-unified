/**
 * Maps the string `icon` field from the config (YAML spec, surfaced via
 * /api/config) to a Lucide icon component. Add a mapping here when a domain
 * references a new icon name -- this is framework engine code, not per-domain
 * page code, so adding a domain in YAML still needs zero new page code.
 */
import {
  Fingerprint,
  ShieldAlert,
  ShieldCheck,
  Lock,
  Bug,
  Network,
  Cloud,
  Database,
  type LucideIcon,
} from "lucide-react"

const ICONS: Record<string, LucideIcon> = {
  fingerprint: Fingerprint,
  "shield-alert": ShieldAlert,
  "shield-check": ShieldCheck,
  lock: Lock,
  bug: Bug,
  network: Network,
  cloud: Cloud,
  database: Database,
}

export function domainIcon(name: string): LucideIcon {
  return ICONS[name] ?? ShieldCheck
}
