import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import type { ChartTrendPoint } from "@/lib/contracts"

export function TrendAreaChart({
  data,
  config,
  domainMax,
  unit,
}: {
  data: ChartTrendPoint[]
  config: ChartConfig
  domainMax?: number
  unit?: string
}) {
  const keys = Object.keys(config)
  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
      <AreaChart data={data} margin={{ left: 4, right: 8, top: 8 }}>
        <defs>
          {keys.map((k) => (
            <linearGradient key={k} id={`fill-${k}`} x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="5%"
                stopColor={`var(--color-${k})`}
                stopOpacity={0.3}
              />
              <stop
                offset="95%"
                stopColor={`var(--color-${k})`}
                stopOpacity={0.02}
              />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={32}
          tickFormatter={(v: string) => v.slice(5)}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={36}
          domain={domainMax ? [0, domainMax] : undefined}
          tickFormatter={(v: number) => `${v}${unit ?? ""}`}
        />
        <ChartTooltip content={<ChartTooltipContent />} />
        {keys.map((k) => (
          <Area
            key={k}
            type="monotone"
            dataKey={k}
            stroke={`var(--color-${k})`}
            fill={`url(#fill-${k})`}
            strokeWidth={2}
            stackId={undefined}
          />
        ))}
      </AreaChart>
    </ChartContainer>
  )
}
