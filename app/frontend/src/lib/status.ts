import type { RagStatus, TrendDirection } from "@/lib/contracts"

export function statusTextClass(status: RagStatus): string {
  switch (status) {
    case "green":
      return "text-success"
    case "amber":
      return "text-warning"
    case "red":
      return "text-danger"
  }
}

export function statusBarClass(status: RagStatus): string {
  switch (status) {
    case "green":
      return "bg-success"
    case "amber":
      return "bg-warning"
    case "red":
      return "bg-danger"
  }
}

export function trendTextClass(direction: TrendDirection): string {
  switch (direction) {
    case "up":
      return "text-success"
    case "down":
      return "text-danger"
    case "flat":
      return "text-muted-foreground"
  }
}

/**
 * Color for a KPI comparison line. Unlike trends, this is keyed on whether the
 * movement is *favorable* (a rising "critical CVEs" count is bad -> danger),
 * not on the raw arrow direction.
 */
export function comparisonToneClass(
  tone: "positive" | "negative" | "neutral",
): string {
  switch (tone) {
    case "positive":
      return "text-success"
    case "negative":
      return "text-danger"
    case "neutral":
      return "text-muted-foreground"
  }
}
