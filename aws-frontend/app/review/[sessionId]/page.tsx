"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Header from "@/components/header";
import ReviewItem, { type ReviewItemData } from "@/components/review-item";
import * as backend from "@/lib/backend-api";
import { toast } from "sonner";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  AlertTriangle,
  CheckCircle2,
  ListChecks,
  Loader2,
  CheckCheck,
  Send,
} from "lucide-react";

export default function ReviewPage() {
  const params = useParams<{ sessionId: string }>();
  const router = useRouter();
  const sessionId = params.sessionId;

  const [items, setItems] = useState<ReviewItemData[]>([]);
  const [comments, setComments] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [batchApproving, setBatchApproving] = useState(false);
  const [finalizing, setFinalizing] = useState(false);

  // Fetch review items on mount
  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;

    async function fetchItems() {
      try {
        const data = await backend.getReviewItems(sessionId);
        if (!cancelled) {
          setItems(data.items);
        }
      } catch (error) {
        console.error("Failed to load review items:", error);
        if (!cancelled) {
          toast.error("Failed to load review items");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchItems();

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Computed stats
  const totalCount = items.length;
  const pendingCount = items.filter(
    (item) => item.status?.toLowerCase() === "pending"
  ).length;
  const approvedCount = items.filter(
    (item) => item.status?.toLowerCase() === "approved"
  ).length;
  const rejectedCount = items.filter(
    (item) => item.status?.toLowerCase() === "rejected"
  ).length;
  const completionPercentage =
    totalCount > 0
      ? Math.round(((approvedCount + rejectedCount) / totalCount) * 100)
      : 0;

  // Handle individual approve
  const handleApprove = useCallback(
    async (itemId: string, comment: string) => {
      try {
        await backend.submitReviewDecision(sessionId, itemId, 'approved', comment);
        setItems((prev) =>
          prev.map((item) =>
            item.id === itemId ? { ...item, status: "approved" } : item
          )
        );
        toast.success("Item approved successfully");
      } catch (error) {
        console.error("Failed to approve item:", error);
        toast.error("Failed to approve item");
      }
    },
    [sessionId]
  );

  // Handle individual reject
  const handleReject = useCallback(
    async (itemId: string, comment: string) => {
      try {
        await backend.submitReviewDecision(sessionId, itemId, 'rejected', comment);
        setItems((prev) =>
          prev.map((item) =>
            item.id === itemId ? { ...item, status: "rejected" } : item
          )
        );
        toast.success("Item rejected successfully");
      } catch (error) {
        console.error("Failed to reject item:", error);
        toast.error("Failed to reject item");
      }
    },
    [sessionId]
  );

  // Handle comment change per item
  const handleCommentChange = useCallback(
    (itemId: string, comment: string) => {
      setComments((prev) => ({ ...prev, [itemId]: comment }));
    },
    []
  );

  // Batch approve all pending items
  const handleBatchApprove = useCallback(async () => {
    setBatchApproving(true);
    try {
      const pendingIds = items
        .filter((item) => item.status?.toLowerCase() === "pending")
        .map((item) => item.id);
      await backend.batchApprove(sessionId, pendingIds);
      setItems((prev) =>
        prev.map((item) =>
          item.status?.toLowerCase() === "pending"
            ? { ...item, status: "approved" }
            : item
        )
      );
      toast.success("All remaining items approved successfully");
    } catch (error) {
      console.error("Failed to batch approve:", error);
      toast.error("Failed to batch approve items");
    } finally {
      setBatchApproving(false);
    }
  }, [items, sessionId]);

  // Finalize review
  const handleFinalize = useCallback(async () => {
    setFinalizing(true);
    try {
      await backend.finalizeReview(sessionId);
      toast.success("Review finalized successfully");
      setTimeout(() => {
        router.push(`/reports/${sessionId}`);
      }, 2000);
    } catch (error) {
      console.error("Failed to finalize review:", error);
      toast.error("Failed to finalize review");
      setFinalizing(false);
    }
  }, [sessionId, router]);

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen bg-background">
        <Header />
        <div className="mx-auto max-w-6xl px-6 py-10">
          <div className="flex flex-col items-center justify-center gap-4 py-24">
            <Loader2 className="h-10 w-10 animate-spin text-primary" />
            <p className="text-lg font-medium text-muted-foreground">
              Loading review items...
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Header />

      <div className="mx-auto max-w-6xl px-6 py-8">
        {/* Page Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold font-heading tracking-tight">
            Review Assessment Findings
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Session:{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
              {sessionId}
            </code>
          </p>
          <p className="mt-2 text-muted-foreground">
            Review and approve or reject AI-generated recommendations before
            finalizing the assessment.
          </p>
        </div>

        {/* Progress Bar */}
        <div className="mb-6 rounded-lg border bg-card p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-semibold">
              Review Progress: {completionPercentage}%
            </p>
            <p className="text-xs text-muted-foreground">
              {approvedCount + rejectedCount} of {totalCount} items reviewed
            </p>
          </div>
          <Progress
            value={completionPercentage}
            className="h-3 bg-orange-100 dark:bg-orange-900/30 [&>[data-slot=progress-indicator]]:bg-primary"
          />
          <p className="mt-1.5 text-xs text-muted-foreground">
            {pendingCount} remaining
          </p>
        </div>

        {/* Stat Cards */}
        <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {/* Total Items */}
          <Card className="border-l-4 border-l-blue-500">
            <CardContent className="py-4 text-center">
              <p className="text-3xl font-bold text-blue-600 dark:text-blue-400">
                {totalCount}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">Total Items</p>
            </CardContent>
          </Card>

          {/* Pending */}
          <Card className="border-l-4 border-l-amber-500">
            <CardContent className="py-4 text-center">
              <p className="text-3xl font-bold text-amber-600 dark:text-amber-400">
                {pendingCount}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">Pending</p>
            </CardContent>
          </Card>

          {/* Approved */}
          <Card className="border-l-4 border-l-green-500">
            <CardContent className="py-4 text-center">
              <p className="text-3xl font-bold text-green-600 dark:text-green-400">
                {approvedCount}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">Approved</p>
            </CardContent>
          </Card>

          {/* Rejected */}
          <Card className="border-l-4 border-l-red-500">
            <CardContent className="py-4 text-center">
              <p className="text-3xl font-bold text-red-600 dark:text-red-400">
                {rejectedCount}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">Rejected</p>
            </CardContent>
          </Card>
        </div>

        {/* Alert Banner */}
        {pendingCount > 0 && (
          <Alert className="mb-6 border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-200">
            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            <AlertTitle className="font-semibold">
              {pendingCount} item{pendingCount !== 1 ? "s" : ""} pending review
            </AlertTitle>
            <AlertDescription>
              Please review each recommendation and approve or reject before
              finalizing the assessment.
            </AlertDescription>
          </Alert>
        )}

        {pendingCount === 0 && totalCount > 0 && (
          <Alert className="mb-6 border-green-300 bg-green-50 text-green-900 dark:border-green-700 dark:bg-green-900/20 dark:text-green-200">
            <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
            <AlertTitle className="font-semibold">
              All items have been reviewed!
            </AlertTitle>
            <AlertDescription>
              Click &quot;Finalize Review&quot; to complete the assessment and
              generate the final report.
            </AlertDescription>
          </Alert>
        )}

        {/* Action Buttons Row */}
        <div className="mb-6 flex flex-wrap items-center gap-3">
          {pendingCount > 0 && (
            <Button
              variant="outline"
              onClick={handleBatchApprove}
              disabled={batchApproving}
              className="border-green-300 text-green-700 hover:bg-green-50 dark:border-green-700 dark:text-green-400 dark:hover:bg-green-900/20"
            >
              {batchApproving ? (
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
              ) : (
                <CheckCheck className="h-4 w-4 mr-1.5" />
              )}
              Approve All Remaining
            </Button>
          )}
          <Button
            onClick={handleFinalize}
            disabled={pendingCount > 0 || finalizing || totalCount === 0}
            className="bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {finalizing ? (
              <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
            ) : (
              <Send className="h-4 w-4 mr-1.5" />
            )}
            Finalize Review
          </Button>
        </div>

        {/* Review Items List */}
        {totalCount === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16">
            <ListChecks className="h-12 w-12 text-muted-foreground/50" />
            <p className="mt-4 text-lg font-medium text-muted-foreground">
              No review items found
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              There are no items to review for this session.
            </p>
          </div>
        ) : (
          <div className="space-y-4 stagger-children">
            {items.map((item) => (
              <ReviewItem
                key={item.id}
                item={item}
                onApprove={handleApprove}
                onReject={handleReject}
                comment={comments[item.id] || ""}
                onCommentChange={handleCommentChange}
              />
            ))}
          </div>
        )}

        {/* Footer Finalize Section */}
        {totalCount > 0 && (
          <div className="mt-8 rounded-lg border bg-gradient-to-r from-slate-900 to-slate-800 dark:from-card dark:to-muted p-6 text-white">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-lg font-semibold">Ready to finalize?</h3>
                <p className="mt-1 text-sm text-white/80">
                  {pendingCount > 0
                    ? `Please review the remaining ${pendingCount} item${pendingCount !== 1 ? "s" : ""} before finalizing the assessment.`
                    : 'All items have been reviewed. Click "Finalize Review" to generate the comprehensive report.'}
                </p>
              </div>
              <Button
                onClick={handleFinalize}
                disabled={pendingCount > 0 || finalizing}
                size="lg"
                className="shrink-0 bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {finalizing ? (
                  <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                ) : (
                  <Send className="h-4 w-4 mr-1.5" />
                )}
                Finalize Review
              </Button>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
