"use client";

import React from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

interface PillarCardProps {
  name: string;
  score: number;
  description: string;
}

export default function PillarCard({ name, score, description }: PillarCardProps) {
  const scoreColor =
    score >= 80
      ? "text-green-500"
      : score >= 60
        ? "text-amber-500"
        : "text-red-500";

  const barColor =
    score >= 80
      ? "from-green-500 to-emerald-400"
      : score >= 60
        ? "from-amber-500 to-yellow-400"
        : "from-red-500 to-rose-400";

  return (
    <Card className="h-full overflow-hidden">
      {/* Thin gradient top bar */}
      <div className={`h-1 bg-gradient-to-r ${barColor}`} />
      <CardHeader className="pb-2">
        <div className="flex items-baseline justify-between">
          <CardTitle className="text-base">{name}</CardTitle>
          <div className="flex items-baseline gap-1">
            <span className={`text-3xl font-bold font-heading ${scoreColor}`}>{score}</span>
            <span className="text-sm text-muted-foreground">/ 100</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Progress
            value={score}
            className="h-2 [&>[data-slot=progress-indicator]]:bg-primary"
          />
        </div>
        <CardDescription>{description}</CardDescription>
      </CardContent>
    </Card>
  );
}
