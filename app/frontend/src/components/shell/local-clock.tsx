import { useEffect, useState } from "react"

function formatParts(now: Date) {
  const time = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
  // Short timezone label, e.g. "MDT", "PST", "GMT+2"
  const tz =
    new Intl.DateTimeFormat([], { timeZoneName: "short" })
      .formatToParts(now)
      .find((p) => p.type === "timeZoneName")?.value ?? ""
  return { time, tz }
}

export function LocalClock() {
  const [parts, setParts] = useState<{ time: string; tz: string } | null>(null)

  useEffect(() => {
    setParts(formatParts(new Date()))
    const id = setInterval(() => setParts(formatParts(new Date())), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <span className="font-mono text-sm tabular-nums text-muted-foreground">
      {parts ? `${parts.time} ${parts.tz}` : "--:--:--"}
    </span>
  )
}
