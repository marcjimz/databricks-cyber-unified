import { useState } from "react"
import type { ComparisonPeriod } from "@/lib/contracts"

/**
 * Owns the reporting-period (30/60/90d) selection for a page. The value is
 * threaded into the ReportingControls selector and appended to metrics requests
 * as `?period=`. The backend may ignore it (seed provider) but the contract is
 * fully wired end to end.
 */
export function useReportingPeriod(initial: ComparisonPeriod = 30) {
  const [period, setPeriod] = useState<ComparisonPeriod>(initial)
  return { period, setPeriod }
}
