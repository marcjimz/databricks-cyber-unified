import type { ReactNode } from "react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function ChartCard({
  title,
  description,
  children,
  legend,
}: {
  title: string
  description?: string
  children: ReactNode
  legend?: { label: string; color: string }[]
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="space-y-1">
          <CardTitle className="text-base">{title}</CardTitle>
          {description ? (
            <CardDescription>{description}</CardDescription>
          ) : null}
        </div>
        {legend ? (
          <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
            {legend.map((l) => (
              <span
                key={l.label}
                className="flex items-center gap-1.5 text-xs text-muted-foreground"
              >
                <span
                  className="size-2.5 rounded-full"
                  style={{ background: l.color }}
                />
                {l.label}
              </span>
            ))}
          </div>
        ) : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}
