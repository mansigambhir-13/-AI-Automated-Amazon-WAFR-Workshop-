"use client";

import type { TooltipProps } from "recharts";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Tooltip,
} from "recharts";
import {
  ChartContainer,
  type ChartConfig,
} from "@/components/ui/chart";

const chartConfig = {
  score: { label: "Score", color: "var(--chart-1)" },
} satisfies ChartConfig;

interface ResultsRadarChartProps {
  data: { name: string; score: number; fullMark: number }[];
}

function RadarTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;

  // Find the "score" entry, skip "fullMark"
  const scoreEntry = payload.find((p) => p.dataKey === "score");
  if (!scoreEntry) return null;

  const pillarName = scoreEntry.payload?.name ?? label;
  const value = scoreEntry.value ?? 0;

  return (
    <div className="rounded-lg border border-border/50 bg-background px-3 py-2 text-xs shadow-xl">
      <p className="font-semibold text-foreground mb-1">{pillarName}</p>
      <div className="flex items-center gap-2">
        <span
          className="inline-block h-2.5 w-2.5 rounded-sm"
          style={{ backgroundColor: "var(--color-score)" }}
        />
        <span className="text-muted-foreground">Score</span>
        <span className="ml-auto font-mono font-semibold text-foreground tabular-nums">
          {value} / 100
        </span>
      </div>
    </div>
  );
}

export default function ResultsRadarChart({ data }: ResultsRadarChartProps) {
  return (
    <ChartContainer config={chartConfig} className="h-[400px] w-full">
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
        <defs>
          {/* Radial gradient: lighter in center, saturated at edges */}
          <radialGradient id="radarFill" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--color-score)" stopOpacity={0.08} />
            <stop offset="60%" stopColor="var(--color-score)" stopOpacity={0.15} />
            <stop offset="100%" stopColor="var(--color-score)" stopOpacity={0.3} />
          </radialGradient>
          {/* Glow on the stroke line */}
          <filter id="radarStrokeGlow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Glow on dots */}
          <filter id="dotGlow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Grid: solid lines, clearly visible */}
        <PolarGrid
          gridType="polygon"
          stroke="var(--color-muted-foreground)"
          strokeOpacity={0.2}
        />

        {/* Pillar labels — bigger, bolder, pushed outward */}
        <PolarAngleAxis
          dataKey="name"
          tick={({ x, y, payload, textAnchor, index }) => {
            const angle = (Math.PI * 2 * index) / data.length - Math.PI / 2;
            const nudge = 16;
            const nx = x + Math.cos(angle) * nudge;
            const ny = y + Math.sin(angle) * nudge;
            return (
              <text
                x={nx}
                y={ny}
                textAnchor={textAnchor}
                fill="currentColor"
                className="text-[13px] font-semibold fill-foreground"
                dy={2}
              >
                {payload.value}
              </text>
            );
          }}
        />

        {/* Radius scale — hidden */}
        <PolarRadiusAxis
          angle={90}
          domain={[0, 100]}
          tick={false}
          axisLine={false}
          stroke="transparent"
        />

        {/* Reference ring at fullMark (outer boundary) — hidden from tooltip */}
        <Radar
          name="Max"
          dataKey="fullMark"
          stroke="var(--color-muted-foreground)"
          strokeOpacity={0.12}
          fill="none"
          strokeWidth={1}
          strokeDasharray="6 4"
          legendType="none"
          tooltipType="none"
        />

        {/* Custom tooltip that only shows score */}
        <Tooltip content={<RadarTooltip />} cursor={false} />

        {/* Main radar: light radial fill so grid shows through + glowing stroke */}
        <Radar
          name="Score"
          dataKey="score"
          stroke="var(--color-score)"
          strokeWidth={2.5}
          fill="url(#radarFill)"
          fillOpacity={1}
          filter="url(#radarStrokeGlow)"
          dot={{
            r: 5,
            fill: "var(--color-score)",
            stroke: "var(--color-card)",
            strokeWidth: 2.5,
            filter: "url(#dotGlow)",
          }}
          activeDot={{
            r: 8,
            fill: "var(--color-score)",
            stroke: "var(--color-card)",
            strokeWidth: 2,
          }}
        />
      </RadarChart>
    </ChartContainer>
  );
}
