"use client";

import React, { useState } from "react";
import {
  ChevronsUpDown,
  Check,
  X,
  Shield,
  Zap,
} from "lucide-react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

export interface ReviewItemData {
  id: string;
  type: string;
  content: string;
  description?: string;
  status: string;
  pillar: string;
  severity?: string;
  affected_resources?: string[];
  recommendation?: string;
  estimated_effort?: string;
  auto_remediable?: boolean;
}

interface ReviewItemProps {
  item: ReviewItemData;
  onApprove: (itemId: string, comment: string) => void;
  onReject: (itemId: string, comment: string) => void;
  comment: string;
  onCommentChange: (itemId: string, comment: string) => void;
}

function getSeverityClasses(severity?: string): string {
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

function getStatusClasses(status: string): string {
  switch (status?.toLowerCase()) {
    case "approved":
      return "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400";
    case "rejected":
      return "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400";
    default:
      return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400";
  }
}

function getCardBorderColor(status: string): string {
  switch (status?.toLowerCase()) {
    case "approved":
      return "border-green-500";
    case "rejected":
      return "border-red-500";
    default:
      return "border-border";
  }
}

export default function ReviewItem({
  item,
  onApprove,
  onReject,
  comment,
  onCommentChange,
}: ReviewItemProps) {
  const [open, setOpen] = useState(false);

  const isPending = item.status?.toLowerCase() === "pending";
  const isDecided = !isPending;

  const hasDetails =
    item.recommendation ||
    item.estimated_effort ||
    (item.affected_resources && item.affected_resources.length > 0);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className={`border-2 ${getCardBorderColor(item.status)}`}>
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 space-y-2">
              <CardTitle className="text-base leading-snug">
                {item.content}
              </CardTitle>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="text-xs">
                  {item.type}
                </Badge>
                <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
                  {item.pillar}
                </Badge>
                {item.severity && (
                  <Badge className={getSeverityClasses(item.severity)}>
                    {item.severity}
                  </Badge>
                )}
                {item.auto_remediable && (
                  <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400">
                    <Zap className="h-3 w-3 mr-1" />
                    Auto-Remediable
                  </Badge>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {isDecided && (
                <Badge className={getStatusClasses(item.status)}>
                  {item.status.toUpperCase()}
                </Badge>
              )}
              {hasDetails && (
                <CollapsibleTrigger asChild>
                  <button
                    className="p-1 rounded-md hover:bg-muted transition-colors"
                    aria-label={open ? "Collapse details" : "Expand details"}
                  >
                    <ChevronsUpDown className="h-5 w-5 text-muted-foreground" />
                  </button>
                </CollapsibleTrigger>
              )}
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-3">
          {/* Description */}
          {item.description && (
            <p className="text-sm text-muted-foreground">{item.description}</p>
          )}

          {/* Expanded details */}
          <CollapsibleContent>
            <div className="space-y-4 border-t pt-4 animate-fade-in">
              {item.recommendation && (
                <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-3">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Shield className="h-4 w-4 text-green-600 dark:text-green-400" />
                    <p className="text-sm font-semibold text-green-800 dark:text-green-300">
                      Recommendation
                    </p>
                  </div>
                  <p className="text-sm text-green-700 dark:text-green-400">
                    {item.recommendation}
                  </p>
                </div>
              )}

              {item.estimated_effort && (
                <div className="rounded-lg bg-muted p-3">
                  <p className="text-xs text-muted-foreground mb-0.5">
                    Estimated Effort
                  </p>
                  <p className="text-sm font-medium">{item.estimated_effort}</p>
                </div>
              )}

              {item.affected_resources &&
                item.affected_resources.length > 0 && (
                  <div className="rounded-lg bg-muted p-3">
                    <p className="text-sm font-semibold mb-2">
                      Affected Resources ({item.affected_resources.length})
                    </p>
                    <ul className="space-y-1">
                      {item.affected_resources.map((resource, idx) => (
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
            </div>
          </CollapsibleContent>

          {/* Action section for pending items */}
          {isPending && (
            <div className="space-y-3 border-t pt-4">
              <Textarea
                placeholder="Add comment (optional)"
                value={comment}
                onChange={(e) => onCommentChange(item.id, e.target.value)}
                rows={2}
                className="resize-none"
              />
              <div className="flex gap-2">
                <Button
                  onClick={() => onApprove(item.id, comment)}
                  className="flex-1 bg-green-600 hover:bg-green-700 text-white"
                >
                  <Check className="h-4 w-4 mr-1.5" />
                  Approve
                </Button>
                <Button
                  onClick={() => onReject(item.id, comment)}
                  variant="outline"
                  className="flex-1 border-red-300 text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-900/20"
                >
                  <X className="h-4 w-4 mr-1.5" />
                  Reject
                </Button>
              </div>
            </div>
          )}

          {/* Status display for decided items */}
          {isDecided && (
            <div className="border-t pt-4">
              <div
                className={`flex items-center gap-2 rounded-lg p-3 ${
                  item.status?.toLowerCase() === "approved"
                    ? "bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800"
                    : "bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800"
                }`}
              >
                {item.status?.toLowerCase() === "approved" ? (
                  <Check className="h-5 w-5 text-green-600 dark:text-green-400 shrink-0" />
                ) : (
                  <X className="h-5 w-5 text-red-600 dark:text-red-400 shrink-0" />
                )}
                <div>
                  <p
                    className={`text-sm font-semibold ${
                      item.status?.toLowerCase() === "approved"
                        ? "text-green-800 dark:text-green-300"
                        : "text-red-800 dark:text-red-300"
                    }`}
                  >
                    {item.status?.toLowerCase() === "approved"
                      ? "Approved"
                      : "Rejected"}
                  </p>
                  {comment && (
                    <p
                      className={`text-sm ${
                        item.status?.toLowerCase() === "approved"
                          ? "text-green-700 dark:text-green-400"
                          : "text-red-700 dark:text-red-400"
                      }`}
                    >
                      Comment: {comment}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </Collapsible>
  );
}
