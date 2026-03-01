"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Cell,
  LabelList,
} from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

/* Per-bar colors: industry avg → muted, your score → primary, top quartile → teal */
const BAR_COLORS = [
  "var(--chart-sky)",   // Industry Average
  "var(--chart-1)",     // Your Score (amber primary)
  "var(--chart-4)",     // Top Quartile (green)
];

const chartConfig = {
  score: { label: "Score", color: "var(--chart-1)" },
} satisfies ChartConfig;

interface ReportsBenchmarkChartProps {
  data: { name: string; score: number }[];
}

export default function ReportsBenchmarkChart({ data }: ReportsBenchmarkChartProps) {
  return (
    <ChartContainer config={chartConfig} className="h-[200px] w-full">
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 0, right: 48, bottom: 0, left: 0 }}
      >
        <defs>
          {data.map((_, i) => (
            <linearGradient
              key={`benchGrad-${i}`}
              id={`benchGrad-${i}`}
              x1="0"
              y1="0"
              x2="1"
              y2="0"
            >
              <stop offset="0%" stopColor={BAR_COLORS[i % BAR_COLORS.length]} stopOpacity={0.8} />
              <stop offset="100%" stopColor={BAR_COLORS[i % BAR_COLORS.length]} stopOpacity={1} />
            </linearGradient>
          ))}
          <filter id="benchGlow" x="-5%" y="-20%" width="110%" height="140%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="1.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <CartesianGrid
          strokeDasharray="3 6"
          horizontal={false}
          stroke="var(--color-border)"
          strokeOpacity={0.3}
        />
        <XAxis
          type="number"
          domain={[0, 100]}
          tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          dataKey="name"
          type="category"
          width={120}
          tick={{ fontSize: 12, fill: "currentColor", fontWeight: 500 }}
          axisLine={false}
          tickLine={false}
        />
        <ChartTooltip
          content={<ChartTooltipContent />}
          cursor={{ fill: "var(--color-muted)", opacity: 0.3, radius: 4 }}
        />
        <Bar
          dataKey="score"
          radius={[0, 6, 6, 0]}
          barSize={22}
          filter="url(#benchGlow)"
        >
          {data.map((_, i) => (
            <Cell key={`benchCell-${i}`} fill={`url(#benchGrad-${i})`} />
          ))}
          <LabelList
            dataKey="score"
            position="right"
            offset={8}
            className="fill-foreground text-[12px] font-semibold"
          />
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
