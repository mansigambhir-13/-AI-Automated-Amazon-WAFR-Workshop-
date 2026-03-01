"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  LabelList,
} from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

const chartConfig = {
  score: { label: "Score", color: "var(--chart-1)" },
} satisfies ChartConfig;

interface ResultsBarChartProps {
  data: { name: string; score: number }[];
}

export default function ResultsBarChart({ data }: ResultsBarChartProps) {
  return (
    <ChartContainer config={chartConfig} className="h-[350px] w-full">
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 0, right: 48, bottom: 0, left: 0 }}
        barGap={6}
      >
        <defs>
          {/* Orange gradient: warm amber → bright orange */}
          <linearGradient id="orangeBarGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--color-score)" stopOpacity={0.7} />
            <stop offset="100%" stopColor="var(--color-score)" stopOpacity={1} />
          </linearGradient>
          {/* Subtle glow */}
          <filter id="barGlow" x="-5%" y="-20%" width="110%" height="140%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur" />
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
          tickCount={5}
        />

        <YAxis
          dataKey="name"
          type="category"
          width={150}
          tick={{ fontSize: 12, fill: "currentColor", fontWeight: 500 }}
          axisLine={false}
          tickLine={false}
        />

        <ChartTooltip
          content={<ChartTooltipContent />}
          cursor={{ fill: "var(--color-muted)", opacity: 0.3, radius: 6 }}
        />

        <Bar
          dataKey="score"
          fill="url(#orangeBarGrad)"
          radius={[0, 8, 8, 0]}
          barSize={28}
          filter="url(#barGlow)"
        >
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
