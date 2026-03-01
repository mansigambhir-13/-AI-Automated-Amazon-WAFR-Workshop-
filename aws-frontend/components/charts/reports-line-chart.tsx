"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Area,
} from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  type ChartConfig,
} from "@/components/ui/chart";

const chartConfig = {
  overall_score: { label: "Overall", color: "var(--chart-1)" },
  security: { label: "Security", color: "var(--chart-5)" },
  reliability: { label: "Reliability", color: "var(--chart-sky)" },
  performance: { label: "Performance", color: "var(--chart-4)" },
} satisfies ChartConfig;

interface ScoreHistoryEntry {
  date: string;
  overall_score: number;
  security: number;
  reliability: number;
  performance: number;
}

interface ReportsLineChartProps {
  data: ScoreHistoryEntry[];
}

export default function ReportsLineChart({ data }: ReportsLineChartProps) {
  return (
    <ChartContainer config={chartConfig} className="h-[300px] w-full">
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          {/* Area gradient under the "Overall" line */}
          <linearGradient id="overallAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-overall_score)" stopOpacity={0.25} />
            <stop offset="100%" stopColor="var(--color-overall_score)" stopOpacity={0} />
          </linearGradient>
          {/* Glow filter */}
          <filter id="lineGlow" x="-10%" y="-20%" width="120%" height="140%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <CartesianGrid
          strokeDasharray="3 6"
          stroke="var(--color-border)"
          strokeOpacity={0.3}
        />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
          axisLine={false}
          tickLine={false}
          tickCount={5}
        />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />

        {/* Shaded area under the overall score line */}
        <Area
          type="monotone"
          dataKey="overall_score"
          fill="url(#overallAreaGrad)"
          stroke="none"
        />

        {/* Lines with glow on primary, refined dots */}
        <Line
          type="monotone"
          dataKey="overall_score"
          stroke="var(--color-overall_score)"
          strokeWidth={3}
          filter="url(#lineGlow)"
          dot={{ r: 4, fill: "var(--color-overall_score)", stroke: "var(--color-card)", strokeWidth: 2 }}
          activeDot={{ r: 6, fill: "var(--color-overall_score)", stroke: "var(--color-card)", strokeWidth: 2 }}
        />
        <Line
          type="monotone"
          dataKey="security"
          stroke="var(--color-security)"
          strokeWidth={2}
          dot={{ r: 3, fill: "var(--color-security)", stroke: "var(--color-card)", strokeWidth: 2 }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="reliability"
          stroke="var(--color-reliability)"
          strokeWidth={2}
          dot={{ r: 3, fill: "var(--color-reliability)", stroke: "var(--color-card)", strokeWidth: 2 }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="performance"
          stroke="var(--color-performance)"
          strokeWidth={2}
          dot={{ r: 3, fill: "var(--color-performance)", stroke: "var(--color-card)", strokeWidth: 2 }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ChartContainer>
  );
}
