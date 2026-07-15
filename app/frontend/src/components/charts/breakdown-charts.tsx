import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  Pie,
  PieChart,
  XAxis,
  YAxis,
} from "recharts"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"

type Datum = { name: string; value: number }

export function HorizontalBarChart({
  data,
  color = "var(--chart-1)",
}: {
  data: Datum[]
  color?: string
}) {
  const config: ChartConfig = { value: { label: "Count", color } }
  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
      <BarChart
        data={data}
        layout="vertical"
        margin={{ left: 8, right: 24 }}
      >
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="name"
          tickLine={false}
          axisLine={false}
          width={110}
          tickMargin={4}
        />
        <ChartTooltip content={<ChartTooltipContent />} />
        <Bar dataKey="value" fill="var(--color-value)" radius={4}>
          <LabelList
            dataKey="value"
            position="right"
            className="fill-foreground text-xs"
          />
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}

export function SeverityDonut({
  data,
}: {
  data: Datum[]
}) {
  // Map severity names to status colors.
  const COLORS: Record<string, string> = {
    Critical: "var(--danger)",
    High: "var(--warning)",
    Medium: "var(--chart-1)",
    Low: "var(--muted-foreground)",
  }
  const config: ChartConfig = data.reduce((acc, d) => {
    acc[d.name] = { label: d.name, color: COLORS[d.name] ?? "var(--chart-1)" }
    return acc
  }, {} as ChartConfig)

  return (
    <ChartContainer
      config={config}
      className="mx-auto aspect-square h-64"
    >
      <PieChart>
        <ChartTooltip content={<ChartTooltipContent />} />
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius={58}
          outerRadius={92}
          paddingAngle={2}
        >
          {data.map((d) => (
            <Cell key={d.name} fill={COLORS[d.name] ?? "var(--chart-1)"} />
          ))}
        </Pie>
      </PieChart>
    </ChartContainer>
  )
}
