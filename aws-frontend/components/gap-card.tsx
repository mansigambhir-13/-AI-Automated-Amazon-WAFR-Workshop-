"use client";

import React, { useState } from "react";
import { ChevronsUpDown, Shield } from "lucide-react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export interface Gap {
  id?: string;
  title: string;
  risk_level: string;
  pillar: string;
  description: string;
  current_state?: string;
  target_state?: string;
  mitigation?: string;
  business_impact?: string;
  timeline?: string;
  estimated_cost?: string;
  remediation_steps?: string[];
}

interface GapCardProps {
  gap: Gap;
}

function getRiskClasses(riskLevel: string): string {
  switch (riskLevel?.toLowerCase()) {
    case "high":
    case "critical":
      return "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400";
    case "medium":
      return "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400";
    case "low":
      return "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400";
    default:
      return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400";
  }
}

function getRiskBorderColor(riskLevel: string): string {
  switch (riskLevel?.toLowerCase()) {
    case "high":
    case "critical":
      return "border-l-red-500";
    case "medium":
      return "border-l-amber-500";
    case "low":
      return "border-l-green-500";
    default:
      return "border-l-gray-400";
  }
}

export default function GapCard({ gap }: GapCardProps) {
  const [open, setOpen] = useState(false);

  // Deduplicate: only treat mitigation as separate if it differs from description
  const uniqueMitigation = gap.mitigation && gap.mitigation !== gap.description
    ? gap.mitigation
    : undefined;

  // Extract priority score if business_impact is "Priority score: 78.0"
  const priorityMatch = gap.business_impact?.match(/^Priority\s*score:\s*([\d.]+)$/i);

  // Only show business_impact in details if it's NOT a priority score (those go in the header badge)
  const detailBusinessImpact = gap.business_impact && !priorityMatch
    ? gap.business_impact
    : undefined;

  const hasDetails =
    gap.current_state ||
    gap.target_state ||
    uniqueMitigation ||
    detailBusinessImpact ||
    gap.timeline ||
    gap.estimated_cost ||
    (gap.remediation_steps && gap.remediation_steps.length > 0);

  return (
    <Card className={`border-l-4 ${getRiskBorderColor(gap.risk_level)}`}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-base leading-snug">
            {gap.title}
          </CardTitle>
          <div className="flex items-center gap-2 shrink-0">
            {priorityMatch && (
              <Badge className="bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-400">
                Priority: {Math.round(parseFloat(priorityMatch[1]))} / 100
              </Badge>
            )}
            <Badge className={getRiskClasses(gap.risk_level)}>
              {gap.risk_level} Risk
            </Badge>
            <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
              {gap.pillar}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{gap.description}</p>

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
                {uniqueMitigation && (
                  <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-3">
                    <div className="flex items-center gap-1.5 mb-1">
                      <Shield className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                      <p className="text-sm font-semibold text-blue-800 dark:text-blue-300">
                        Mitigation Strategy
                      </p>
                    </div>
                    <p className="text-sm text-blue-700 dark:text-blue-400">
                      {uniqueMitigation}
                    </p>
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {gap.current_state && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">
                        Current State
                      </p>
                      <p className="text-sm font-medium">{gap.current_state}</p>
                    </div>
                  )}
                  {gap.target_state && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">
                        Target State
                      </p>
                      <p className="text-sm font-medium">{gap.target_state}</p>
                    </div>
                  )}
                  {detailBusinessImpact && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">
                        Business Impact
                      </p>
                      <p className="text-sm font-medium">{detailBusinessImpact}</p>
                    </div>
                  )}
                  {gap.timeline && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">
                        Timeline
                      </p>
                      <p className="text-sm font-medium">{gap.timeline}</p>
                    </div>
                  )}
                  {gap.estimated_cost && (
                    <div className="rounded-lg bg-muted p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">
                        Estimated Cost
                      </p>
                      <p className="text-sm font-medium">{gap.estimated_cost}</p>
                    </div>
                  )}
                </div>

                {gap.remediation_steps && gap.remediation_steps.length > 0 && (
                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-sm font-semibold mb-2">
                      Remediation Steps
                    </p>
                    <ol className="space-y-1.5 list-decimal list-inside">
                      {gap.remediation_steps.map((step, idx) => (
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
