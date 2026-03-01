"use client";

import React, { useState } from "react";
import { ChevronsUpDown } from "lucide-react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export interface Insight {
  id?: string;
  title: string;
  severity: string;
  pillar: string;
  description: string;
  recommendation?: string;
  effort?: string;
  cost_impact?: string;
  affected_resources?: string[];
  implementation_steps?: string[];
}

interface InsightCardProps {
  insight: Insight;
}

function getSeverityClasses(severity: string): string {
  switch (severity?.toLowerCase()) {
    case "high":
      return "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400";
    case "medium":
      return "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400";
    case "low":
      return "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400";
    default:
      return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400";
  }
}

function getSeverityBorderColor(severity: string): string {
  switch (severity?.toLowerCase()) {
    case "high":
      return "border-l-red-500";
    case "medium":
      return "border-l-amber-500";
    case "low":
      return "border-l-green-500";
    default:
      return "border-l-gray-400";
  }
}

export default function InsightCard({ insight }: InsightCardProps) {
  const [open, setOpen] = useState(false);

  const hasDetails =
    insight.recommendation ||
    insight.effort ||
    insight.cost_impact ||
    (insight.affected_resources && insight.affected_resources.length > 0) ||
    (insight.implementation_steps && insight.implementation_steps.length > 0);

  return (
    <Card
      className={`border-l-4 ${getSeverityBorderColor(insight.severity)}`}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-base leading-snug">
            {insight.title}
          </CardTitle>
          <div className="flex items-center gap-2 shrink-0">
            <Badge className={getSeverityClasses(insight.severity)}>
              {insight.severity}
            </Badge>
            <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
              {insight.pillar}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{insight.description}</p>

        {hasDetails && (
          <Collapsible open={open} onOpenChange={setOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1 text-sm font-medium text-primary hover:text-primary/80 transition-colors">
                {open ? "Hide details" : "Show details"}
                <ChevronsUpDown className="h-4 w-4" />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="space-y-4 border-t pt-4 animate-fade-in">
                {insight.recommendation && (
                  <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-3">
                    <p className="text-sm font-semibold text-green-800 dark:text-green-300 mb-1">
                      Recommendation
                    </p>
                    <p className="text-sm text-green-700 dark:text-green-400">
                      {insight.recommendation}
                    </p>
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {insight.effort && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">
                        Estimated Effort
                      </p>
                      <p className="text-sm font-medium">{insight.effort}</p>
                    </div>
                  )}
                  {insight.cost_impact && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">
                        Cost Impact
                      </p>
                      <p className="text-sm font-medium">{insight.cost_impact}</p>
                    </div>
                  )}
                </div>

                {insight.affected_resources &&
                  insight.affected_resources.length > 0 && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-sm font-semibold mb-2">
                        Affected Resources ({insight.affected_resources.length})
                      </p>
                      <ul className="space-y-1">
                        {insight.affected_resources.map((resource, idx) => (
                          <li
                            key={idx}
                            className="flex items-center gap-2 text-sm text-muted-foreground"
                          >
                            <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                            {resource}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                {insight.implementation_steps &&
                  insight.implementation_steps.length > 0 && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-sm font-semibold mb-2">
                        Implementation Steps
                      </p>
                      <ol className="space-y-1.5 list-decimal list-inside">
                        {insight.implementation_steps.map((step, idx) => (
                          <li
                            key={idx}
                            className="text-sm text-muted-foreground"
                          >
                            {step}
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>
    </Card>
  );
}
