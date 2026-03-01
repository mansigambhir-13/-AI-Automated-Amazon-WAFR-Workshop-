"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Header from "@/components/header";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Download,
  FileDown,
  CheckCircle,
  AlertCircle,
  AlertTriangle,
  TrendingUp,
  Shield,
  DollarSign,
  Info,
  Clock,
  Target,
  Zap,
  BarChart3,
  Loader2,
  ArrowLeft,
  ChevronRight,
  Server,
  Activity,
} from "lucide-react";
import dynamic from "next/dynamic";
import * as backend from "@/lib/backend-api";

const ReportsLineChart = dynamic(() => import("@/components/charts/reports-line-chart"), { ssr: false });
const ReportsBenchmarkChart = dynamic(() => import("@/components/charts/reports-benchmark-chart"), { ssr: false });
import type {
  ExecutiveSummary,
  TrendData,
  SessionMetadata,
  Pillar,
  Insight,
  Gap,
  ReviewSummary,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Types for the API responses
// ---------------------------------------------------------------------------

interface SessionState {
  metadata: SessionMetadata;
  executive_summary: ExecutiveSummary;
  trend_data: TrendData;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function severityColor(severity: string): string {
  switch (severity) {
    case "High":
      return "bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800";
    case "Medium":
      return "bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800";
    case "Low":
      return "bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800";
    default:
      return "bg-gray-100 text-gray-800 border-gray-300 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700";
  }
}

function riskColor(risk: string): string {
  switch (risk) {
    case "High":
      return "bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800";
    case "Medium":
      return "bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800";
    case "Low":
      return "bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800";
    default:
      return "bg-gray-100 text-gray-800 border-gray-300 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700";
  }
}

function scoreColor(score: number): string {
  if (score >= 80) return "bg-green-600 text-white";
  if (score >= 60) return "bg-amber-500 text-white";
  return "bg-red-600 text-white";
}

function scoreBorderColor(score: number): string {
  if (score >= 80) return "border-green-500";
  if (score >= 60) return "border-amber-500";
  return "border-red-500";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reportStatus, setReportStatus] = useState<string>("checking");
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [sessionData, setSessionData] = useState<SessionState | null>(null);
  const [pillars, setPillars] = useState<Pillar[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [gaps, setGaps] = useState<Gap[]>([]);

  // -----------------------------------------------------------------------
  // Data fetching
  // -----------------------------------------------------------------------

  const loadAllData = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const [summaryRes, pillarsRes, insightsRes, gapsRes] =
        await Promise.all([
          backend.getReviewSummary(sessionId).catch(() => null),
          backend.getPillars(sessionId),
          backend.getInsights(sessionId),
          backend.getGaps(sessionId),
        ]);

      setReportStatus("ready");

      // Compute risk gap counts from the actual gaps data
      const highRisk = gapsRes.filter((g) => g.risk_level === "High").length;
      const mediumRisk = gapsRes.filter((g) => g.risk_level === "Medium").length;
      const lowRisk = gapsRes.filter((g) => g.risk_level === "Low").length;

      // Enrich the review summary with gap-derived counts
      const enrichedSummary: ReviewSummary = summaryRes
        ? {
            ...summaryRes,
            // Use review items count if available, otherwise fall back to gaps+insights
            total_items: summaryRes.total_items || gapsRes.length + insightsRes.length,
            high_risk_gaps: highRisk,
            medium_risk_gaps: mediumRisk,
            low_risk_gaps: lowRisk,
          }
        : {
            total_items: gapsRes.length + insightsRes.length,
            approved_items: 0,
            rejected_items: 0,
            pending_items: gapsRes.length + insightsRes.length,
            high_risk_gaps: highRisk,
            medium_risk_gaps: mediumRisk,
            low_risk_gaps: lowRisk,
            auto_remediable_count: 0,
            estimated_total_effort: "",
            potential_cost_savings: "",
            potential_cost_increase: "",
          };

      setSummary(enrichedSummary);
      setPillars(pillarsRes);
      setInsights(insightsRes);
      setGaps(gapsRes);

      // Try to get session state for metadata
      try {
        const stateData = await backend.getSessionState(sessionId);
        const state = stateData.state;
        if (state) {
          setSessionData({
            metadata: (state.session as Record<string, unknown>)?.metadata as unknown as SessionMetadata || null,
            executive_summary: (state.report as Record<string, unknown>)?.executive_summary as unknown as ExecutiveSummary || null,
            trend_data: (state.report as Record<string, unknown>)?.trend_data as unknown as TrendData || null,
          } as SessionState);
        }
      } catch {
        // No state data available — that's ok
      }
    } catch (err) {
      console.error("Failed to load data:", err);
      setError("Failed to load report data. Please try again.");
      setReportStatus("error");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

  // -----------------------------------------------------------------------
  // Download handlers
  // -----------------------------------------------------------------------

  const [downloading, setDownloading] = useState<string | null>(null);

  const viewAwsReport = async () => {
    setDownloading("aws");
    try {
      await backend.downloadAwsReport(sessionId);
    } catch (err) {
      console.error('AWS report download failed:', err);
    } finally {
      setDownloading(null);
    }
  };

  // -----------------------------------------------------------------------
  // Derived values
  // -----------------------------------------------------------------------

  const averageScore =
    pillars.length > 0
      ? Math.round(
          pillars.reduce((sum, p) => sum + p.score, 0) / pillars.length
        )
      : 0;

  // -----------------------------------------------------------------------
  // Loading state
  // -----------------------------------------------------------------------

  if (loading) {
    return (
      <>
        <Header />
        <div className="min-h-[calc(100vh-4rem)] bg-background py-8">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Loader2 className="h-10 w-10 animate-spin text-primary mb-4" />
                <h2 className="text-lg font-semibold mb-2">
                  Loading comprehensive report data...
                </h2>
                <p className="text-sm text-muted-foreground mb-4">
                  Fetching assessment results, insights, and analytics
                </p>
                <Progress className="w-64 animate-pulse" />
              </CardContent>
            </Card>
          </div>
        </div>
      </>
    );
  }

  // -----------------------------------------------------------------------
  // Error state
  // -----------------------------------------------------------------------

  if (error && !sessionData) {
    return (
      <>
        <Header />
        <div className="min-h-[calc(100vh-4rem)] bg-background py-8">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error Loading Report</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          </div>
        </div>
      </>
    );
  }

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------

  const executiveSummary = sessionData?.executive_summary;
  const metadata = sessionData?.metadata;
  const trendData = sessionData?.trend_data;

  return (
    <>
      <Header />
      <div className="min-h-[calc(100vh-4rem)] bg-background py-8">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 space-y-8">
          {/* ============================================================= */}
          {/* Page Header                                                    */}
          {/* ============================================================= */}
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold font-heading tracking-tight animate-fade-up">
                Comprehensive Assessment Report
              </h1>
              <p className="text-muted-foreground mt-1">
                Detailed analysis and recommendations for{" "}
                {metadata?.assessment_name || "your workload"}
              </p>
            </div>
            <Link href={`/results/${sessionId}`}>
              <Button variant="outline" className="gap-2">
                <ArrowLeft className="h-4 w-4" />
                Back to Results
              </Button>
            </Link>
          </div>

          {/* Report status banners */}
          {reportStatus === "generating" && (
            <Alert>
              <Loader2 className="h-4 w-4 animate-spin" />
              <AlertTitle>Generating Report</AlertTitle>
              <AlertDescription>
                Report is being generated. Please wait...
              </AlertDescription>
            </Alert>
          )}

          {reportStatus === "error" && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Report Error</AlertTitle>
              <AlertDescription>
                Failed to generate report. Please try again later.
              </AlertDescription>
            </Alert>
          )}

          {/* ============================================================= */}
          {/* Download Section                                               */}
          {/* ============================================================= */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Download className="h-5 w-5 text-primary" />
                Download Reports
              </CardTitle>
              <CardDescription>
                Export your assessment in multiple formats
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="max-w-md">
                {/* AWS Official Report */}
                <Card className="border shadow-none">
                  <CardContent className="pt-6">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                        <FileDown className="h-6 w-6 text-primary" />
                      </div>
                      <div>
                        <p className="font-semibold">AWS Official Report</p>
                        <p className="text-xs text-muted-foreground">
                          Official AWS Well-Architected Tool report
                        </p>
                      </div>
                    </div>
                    <Button
                      onClick={viewAwsReport}
                      disabled={downloading !== null}
                      className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
                    >
                      {downloading === "aws" ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Downloading...
                        </>
                      ) : (
                        <>
                          <FileDown className="h-4 w-4" />
                          Download AWS Report
                        </>
                      )}
                    </Button>
                  </CardContent>
                </Card>
              </div>
            </CardContent>
          </Card>

          {/* ============================================================= */}
          {/* Executive Summary                                              */}
          {/* ============================================================= */}
          {executiveSummary && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 className="h-5 w-5 text-primary" />
                  Executive Summary
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Overview */}
                <Alert>
                  <Info className="h-4 w-4" />
                  <AlertTitle>Overview</AlertTitle>
                  <AlertDescription className="text-sm leading-relaxed">
                    {executiveSummary.overview}
                  </AlertDescription>
                </Alert>

                {/* Strengths & Critical Actions */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Key Strengths */}
                  <div className="rounded-lg border border-green-300 bg-green-50 p-5 dark:border-green-800 dark:bg-green-950/30">
                    <h3 className="flex items-center gap-2 font-semibold text-green-800 dark:text-green-400 mb-3">
                      <CheckCircle className="h-5 w-5" />
                      Key Strengths
                    </h3>
                    <ul className="space-y-2">
                      {executiveSummary.key_strengths.map((strength, idx) => (
                        <li
                          key={idx}
                          className="flex items-start gap-2 text-sm text-green-800 dark:text-green-300"
                        >
                          <CheckCircle className="h-4 w-4 shrink-0 mt-0.5" />
                          <span>{strength}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Critical Actions */}
                  <div className="rounded-lg border border-red-300 bg-red-50 p-5 dark:border-red-800 dark:bg-red-950/30">
                    <h3 className="flex items-center gap-2 font-semibold text-red-800 dark:text-red-400 mb-3">
                      <AlertCircle className="h-5 w-5" />
                      Critical Actions Required
                    </h3>
                    <ul className="space-y-2">
                      {executiveSummary.critical_actions.map((action, idx) => (
                        <li
                          key={idx}
                          className="flex items-start gap-2 text-sm text-red-800 dark:text-red-300"
                        >
                          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                          <span>{action}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                {/* Quick Wins */}
                <div className="rounded-lg border border-amber-300 bg-amber-50 p-5 dark:border-amber-800 dark:bg-amber-950/30">
                  <h3 className="flex items-center gap-2 font-semibold text-amber-800 dark:text-amber-400 mb-3">
                    <Zap className="h-5 w-5" />
                    Quick Wins (High Impact, Low Effort)
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {executiveSummary.quick_wins.map((win, idx) => (
                      <div
                        key={idx}
                        className="flex items-start gap-2 text-sm text-amber-800 dark:text-amber-300"
                      >
                        <CheckCircle className="h-4 w-4 shrink-0 mt-0.5" />
                        <span>{win}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ============================================================= */}
          {/* Assessment Details                                             */}
          {/* ============================================================= */}
          {metadata && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Info className="h-5 w-5 text-secondary" />
                  Assessment Details
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Workload Information */}
                  <Card className="border shadow-none">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm text-muted-foreground">
                        Workload Information
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Separator className="mb-4" />
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Workload Name
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.workload_name}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Environment
                          </span>
                          <Badge variant="secondary">
                            {metadata.environment}
                          </Badge>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Industry
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.workload_details.industry}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Architecture Type
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.workload_details.architecture_type}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Team Size
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.workload_details.team_size} members
                          </span>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Assessment Scope */}
                  <Card className="border shadow-none">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm text-muted-foreground">
                        Assessment Scope
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Separator className="mb-4" />
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Resources Analyzed
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.assessment_scope.resources_analyzed}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Questions Answered
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.assessment_scope.questions_answered} /{" "}
                            {metadata.assessment_scope.questions_total}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Duration
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.duration_minutes} minutes
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Regions Scanned
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.assessment_scope.regions_scanned.join(
                              ", "
                            )}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">
                            Compliance
                          </span>
                          <span className="text-sm font-semibold">
                            {metadata.workload_details.compliance_requirements.join(
                              ", "
                            )}
                          </span>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ============================================================= */}
          {/* Assessment Summary Stats (all data from actual WAFR results)    */}
          {/* ============================================================= */}
          <Card>
            <CardHeader>
              <CardTitle>Assessment Summary</CardTitle>
              <CardDescription>
                Metrics from the Well-Architected Framework review
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                {/* Total Gaps — from actual gaps endpoint */}
                <Card className="border shadow-none text-center">
                  <CardContent className="pt-6 pb-4">
                    <p className="text-3xl font-bold text-secondary">
                      {gaps.length}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Total Gaps
                    </p>
                  </CardContent>
                </Card>

                {/* High Risk — from actual gaps data */}
                <Card className="border border-red-300 dark:border-red-800 shadow-none text-center">
                  <CardContent className="pt-6 pb-4">
                    <p className="text-3xl font-bold text-red-600 dark:text-red-400">
                      {gaps.filter((g) => g.risk_level === "High").length}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      High Risk
                    </p>
                  </CardContent>
                </Card>

                {/* Medium Risk — from actual gaps data */}
                <Card className="border border-amber-300 dark:border-amber-800 shadow-none text-center">
                  <CardContent className="pt-6 pb-4">
                    <p className="text-3xl font-bold text-amber-600 dark:text-amber-400">
                      {gaps.filter((g) => g.risk_level === "Medium").length}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Medium Risk
                    </p>
                  </CardContent>
                </Card>

                {/* Insights — from actual insights endpoint */}
                <Card className="border border-blue-300 dark:border-blue-800 shadow-none text-center">
                  <CardContent className="pt-6 pb-4">
                    <p className="text-3xl font-bold text-blue-600 dark:text-blue-400">
                      {insights.length}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Insights
                    </p>
                  </CardContent>
                </Card>

                {/* Pillars Assessed — from actual pillars endpoint */}
                <Card className="border border-green-300 dark:border-green-800 shadow-none text-center">
                  <CardContent className="pt-6 pb-4">
                    <p className="text-3xl font-bold text-green-600 dark:text-green-400">
                      {pillars.length}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Pillars Assessed
                    </p>
                  </CardContent>
                </Card>

                {/* Avg Score — computed from actual pillar scores */}
                <Card className="border shadow-none text-center">
                  <CardContent className="pt-6 pb-4">
                    <p className="text-3xl font-bold">{averageScore}</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Avg Score
                    </p>
                  </CardContent>
                </Card>
              </div>
            </CardContent>
          </Card>

          {/* ============================================================= */}
          {/* Detailed Insights (Accordion)                                  */}
          {/* ============================================================= */}
          {insights.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Shield className="h-5 w-5 text-primary" />
                  Detailed Insights & Recommendations
                </CardTitle>
                <CardDescription>
                  {insights.length} insight{insights.length !== 1 ? "s" : ""}{" "}
                  identified across all pillars
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Accordion type="multiple" className="space-y-3">
                  {insights.map((insight) => (
                    <AccordionItem
                      key={insight.id}
                      value={insight.id}
                      className="border rounded-lg px-4"
                    >
                      <AccordionTrigger className="hover:no-underline">
                        <div className="flex flex-col items-start gap-2 text-left pr-4">
                          <span className="font-semibold text-base">
                            {insight.title}
                          </span>
                          <div className="flex flex-wrap gap-2">
                            <Badge
                              className={severityColor(insight.severity)}
                            >
                              {insight.severity}
                            </Badge>
                            <Badge variant="outline">{insight.pillar}</Badge>
                            {insight.category && (
                              <Badge variant="secondary">
                                {insight.category}
                              </Badge>
                            )}
                          </div>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent>
                        <div className="space-y-4 pt-2">
                          {/* Description */}
                          <div>
                            <p className="text-sm font-medium text-muted-foreground mb-1">
                              Description
                            </p>
                            <p className="text-sm">{insight.description}</p>
                          </div>

                          {/* Recommendation */}
                          {insight.recommendation && (
                            <Alert className="border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-950/30">
                              <Target className="h-4 w-4 text-green-600 dark:text-green-400" />
                              <AlertTitle className="text-green-800 dark:text-green-400">
                                Recommendation
                              </AlertTitle>
                              <AlertDescription className="text-green-700 dark:text-green-300">
                                {insight.recommendation}
                              </AlertDescription>
                            </Alert>
                          )}

                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Impact & Effort */}
                            <div className="rounded-lg border bg-muted/50 p-4">
                              <h4 className="text-sm font-semibold mb-3">
                                Impact & Effort
                              </h4>
                              <div className="space-y-2 text-sm">
                                {insight.impact && (
                                  <p>
                                    <span className="font-medium">
                                      Impact:
                                    </span>{" "}
                                    {insight.impact}
                                  </p>
                                )}
                                {insight.effort && (
                                  <p>
                                    <span className="font-medium">
                                      Effort:
                                    </span>{" "}
                                    {insight.effort}
                                  </p>
                                )}
                                {insight.cost_impact && (
                                  <p>
                                    <span className="font-medium">
                                      Cost Impact:
                                    </span>{" "}
                                    {insight.cost_impact}
                                  </p>
                                )}
                              </div>
                            </div>

                            {/* Affected Resources */}
                            {insight.affected_resources &&
                              insight.affected_resources.length > 0 && (
                                <div className="rounded-lg border bg-muted/50 p-4">
                                  <h4 className="text-sm font-semibold mb-3">
                                    Affected Resources
                                  </h4>
                                  <ul className="space-y-1.5">
                                    {insight.affected_resources.map(
                                      (resource, ridx) => (
                                        <li
                                          key={ridx}
                                          className="flex items-center gap-2 text-sm"
                                        >
                                          <Server className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                                          {resource}
                                        </li>
                                      )
                                    )}
                                  </ul>
                                </div>
                              )}
                          </div>

                          {/* Implementation Steps */}
                          {insight.implementation_steps &&
                            insight.implementation_steps.length > 0 && (
                              <div className="rounded-lg border border-blue-300 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/30">
                                <h4 className="text-sm font-semibold text-blue-800 dark:text-blue-400 mb-3">
                                  Implementation Steps
                                </h4>
                                <ol className="space-y-2">
                                  {insight.implementation_steps.map(
                                    (step, sidx) => (
                                      <li
                                        key={sidx}
                                        className="flex items-start gap-3 text-sm text-blue-800 dark:text-blue-300"
                                      >
                                        <Badge className="bg-blue-600 text-white h-5 w-5 shrink-0 flex items-center justify-center p-0 text-xs rounded-full">
                                          {sidx + 1}
                                        </Badge>
                                        <span>{step}</span>
                                      </li>
                                    )
                                  )}
                                </ol>
                              </div>
                            )}
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </CardContent>
            </Card>
          )}

          {/* ============================================================= */}
          {/* Identified Gaps (Accordion)                                     */}
          {/* ============================================================= */}
          {gaps.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertTriangle className="h-5 w-5 text-destructive" />
                  Identified Gaps & Remediation Plans
                </CardTitle>
                <CardDescription>
                  {gaps.length} gap{gaps.length !== 1 ? "s" : ""} requiring
                  remediation
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Accordion type="multiple" className="space-y-3">
                  {gaps.map((gap) => (
                    <AccordionItem
                      key={gap.id}
                      value={gap.id}
                      className="border rounded-lg px-4"
                    >
                      <AccordionTrigger className="hover:no-underline">
                        <div className="flex flex-col items-start gap-2 text-left pr-4">
                          <span className="font-semibold text-base">
                            {gap.title}
                          </span>
                          <div className="flex flex-wrap gap-2">
                            <Badge className={riskColor(gap.risk_level)}>
                              {gap.risk_level} Risk
                            </Badge>
                            <Badge variant="outline">{gap.pillar}</Badge>
                            {gap.priority && (
                              <Badge variant="default">
                                Priority {gap.priority}
                              </Badge>
                            )}
                          </div>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent>
                        <div className="space-y-4 pt-2">
                          {/* Description */}
                          <div>
                            <p className="text-sm font-medium text-muted-foreground mb-1">
                              Description
                            </p>
                            <p className="text-sm">{gap.description}</p>
                          </div>

                          {/* Current State / Target State */}
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Current State */}
                            <div className="rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950/30">
                              <h4 className="text-sm font-semibold text-red-800 dark:text-red-400 mb-2">
                                Current State
                              </h4>
                              <p className="text-sm text-red-700 dark:text-red-300">
                                {gap.current_state}
                              </p>
                            </div>

                            {/* Target State */}
                            <div className="rounded-lg border border-green-300 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950/30">
                              <h4 className="text-sm font-semibold text-green-800 dark:text-green-400 mb-2">
                                Target State
                              </h4>
                              <p className="text-sm text-green-700 dark:text-green-300">
                                {gap.target_state}
                              </p>
                            </div>
                          </div>

                          {/* Mitigation */}
                          <Alert className="border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30">
                            <Shield className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                            <AlertTitle className="text-amber-800 dark:text-amber-400">
                              Mitigation Strategy
                            </AlertTitle>
                            <AlertDescription className="text-amber-700 dark:text-amber-300">
                              {gap.mitigation}
                            </AlertDescription>
                          </Alert>

                          {/* Business Impact / Timeline / Cost */}
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <div className="rounded-lg border bg-muted/50 p-4">
                              <h4 className="text-sm font-semibold mb-2">
                                Business Impact
                              </h4>
                              <p className="text-sm">{gap.business_impact}</p>
                            </div>
                            <div className="rounded-lg border bg-muted/50 p-4">
                              <h4 className="text-sm font-semibold mb-2">
                                Timeline
                              </h4>
                              <p className="text-sm">{gap.timeline}</p>
                            </div>
                            <div className="rounded-lg border bg-muted/50 p-4">
                              <h4 className="text-sm font-semibold mb-2">
                                Estimated Cost
                              </h4>
                              <p className="text-sm">{gap.estimated_cost}</p>
                            </div>
                          </div>

                          {/* Remediation Steps */}
                          {gap.remediation_steps &&
                            gap.remediation_steps.length > 0 && (
                              <div className="rounded-lg border border-blue-300 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/30">
                                <h4 className="text-sm font-semibold text-blue-800 dark:text-blue-400 mb-3">
                                  Remediation Steps
                                </h4>
                                <ol className="space-y-2">
                                  {gap.remediation_steps.map((step, sidx) => (
                                    <li
                                      key={sidx}
                                      className="flex items-start gap-3 text-sm text-blue-800 dark:text-blue-300"
                                    >
                                      <Badge className="bg-blue-600 text-white h-5 w-5 shrink-0 flex items-center justify-center p-0 text-xs rounded-full">
                                        {sidx + 1}
                                      </Badge>
                                      <span>{step}</span>
                                    </li>
                                  ))}
                                </ol>
                              </div>
                            )}
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </CardContent>
            </Card>
          )}

          {/* ============================================================= */}
          {/* Pillar-by-Pillar Analysis (Accordion)                          */}
          {/* ============================================================= */}
          {pillars.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Pillar-by-Pillar Analysis</CardTitle>
                <CardDescription>
                  Detailed breakdown of each Well-Architected pillar
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Accordion type="multiple" className="space-y-3">
                  {pillars.map((pillar) => (
                    <AccordionItem
                      key={pillar.name}
                      value={pillar.name}
                      className="border rounded-lg px-4"
                    >
                      <AccordionTrigger className="hover:no-underline">
                        <div className="flex items-center justify-between w-full pr-4">
                          <div className="flex flex-col items-start gap-1 text-left">
                            <span className="font-semibold text-base">
                              {pillar.name}
                            </span>
                            <span className="text-sm text-muted-foreground">
                              {pillar.description}
                            </span>
                          </div>
                          <Badge
                            className={`${scoreColor(pillar.score)} text-sm px-3 py-1 ml-4 shrink-0`}
                          >
                            {pillar.score}/100
                          </Badge>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent>
                        {pillar.details && (
                          <div className="space-y-4 pt-2">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {/* Strengths */}
                              <div className="rounded-lg border border-green-300 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950/30">
                                <h4 className="text-sm font-semibold text-green-800 dark:text-green-400 mb-3">
                                  Strengths
                                </h4>
                                <ul className="space-y-2">
                                  {pillar.details.strengths.map(
                                    (strength, sidx) => (
                                      <li
                                        key={sidx}
                                        className="flex items-start gap-2 text-sm text-green-800 dark:text-green-300"
                                      >
                                        <CheckCircle className="h-4 w-4 shrink-0 mt-0.5" />
                                        <span>{strength}</span>
                                      </li>
                                    )
                                  )}
                                </ul>
                              </div>

                              {/* Areas for Improvement */}
                              <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
                                <h4 className="text-sm font-semibold text-amber-800 dark:text-amber-400 mb-3">
                                  Areas for Improvement
                                </h4>
                                <ul className="space-y-2">
                                  {pillar.details.improvements.map(
                                    (improvement, iidx) => (
                                      <li
                                        key={iidx}
                                        className="flex items-start gap-2 text-sm text-amber-800 dark:text-amber-300"
                                      >
                                        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                                        <span>{improvement}</span>
                                      </li>
                                    )
                                  )}
                                </ul>
                              </div>
                            </div>

                            {/* Metrics */}
                            {pillar.details.metrics && (
                              <div className="rounded-lg border bg-muted/50 p-4">
                                <h4 className="text-sm font-semibold mb-3">
                                  Key Metrics
                                </h4>
                                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                                  {Object.entries(pillar.details.metrics).map(
                                    ([key, value], midx) => (
                                      <div
                                        key={midx}
                                        className="rounded-md border bg-card p-3"
                                      >
                                        <p className="text-xs uppercase text-muted-foreground tracking-wider">
                                          {key.replace(/_/g, " ")}
                                        </p>
                                        <p className="text-lg font-semibold mt-1">
                                          {String(value)}
                                        </p>
                                      </div>
                                    )
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </CardContent>
            </Card>
          )}

          {/* ============================================================= */}
          {/* Investment & Timeline Section                                   */}
          {/* ============================================================= */}
          {executiveSummary?.investment_required && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <DollarSign className="h-5 w-5 text-primary" />
                  Investment & Expected Benefits
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Investment Table */}
                  <Card className="border shadow-none">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">
                        Required Investment
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Timeframe</TableHead>
                            <TableHead className="text-right">
                              Cost
                            </TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          <TableRow>
                            <TableCell className="font-medium">
                              Immediate
                            </TableCell>
                            <TableCell className="text-right">
                              {executiveSummary.investment_required.immediate}
                            </TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell className="font-medium">
                              Short-term (1-3 months)
                            </TableCell>
                            <TableCell className="text-right">
                              {executiveSummary.investment_required.short_term}
                            </TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell className="font-medium">
                              Long-term (6-12 months)
                            </TableCell>
                            <TableCell className="text-right">
                              {executiveSummary.investment_required.long_term}
                            </TableCell>
                          </TableRow>
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>

                  {/* Expected Benefits */}
                  <div className="rounded-lg border border-green-300 bg-green-50 p-6 dark:border-green-800 dark:bg-green-950/30">
                    <h3 className="text-base font-semibold text-green-800 dark:text-green-400 mb-4">
                      Expected Benefits
                    </h3>
                    <div className="space-y-4">
                      <div>
                        <p className="text-sm font-semibold text-green-800 dark:text-green-400 flex items-center gap-2">
                          <DollarSign className="h-4 w-4" />
                          Cost Savings
                        </p>
                        <p className="text-sm text-green-700 dark:text-green-300 ml-6">
                          {executiveSummary.expected_benefits.cost_savings}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-green-800 dark:text-green-400 flex items-center gap-2">
                          <Shield className="h-4 w-4" />
                          Risk Reduction
                        </p>
                        <p className="text-sm text-green-700 dark:text-green-300 ml-6">
                          {executiveSummary.expected_benefits.risk_reduction}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-green-800 dark:text-green-400 flex items-center gap-2">
                          <Zap className="h-4 w-4" />
                          Performance
                        </p>
                        <p className="text-sm text-green-700 dark:text-green-300 ml-6">
                          {
                            executiveSummary.expected_benefits
                              .performance_improvement
                          }
                        </p>
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-green-800 dark:text-green-400 flex items-center gap-2">
                          <Activity className="h-4 w-4" />
                          Availability
                        </p>
                        <p className="text-sm text-green-700 dark:text-green-300 ml-6">
                          {
                            executiveSummary.expected_benefits
                              .availability_improvement
                          }
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Implementation Timeline */}
                <Card className="border shadow-none">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Clock className="h-4 w-4" />
                      Implementation Timeline
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {/* Immediate */}
                      <div className="rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950/30">
                        <p className="text-sm font-semibold text-red-800 dark:text-red-400">
                          Immediate Actions
                        </p>
                        <p className="text-xl font-bold text-red-700 dark:text-red-300 mt-2">
                          {executiveSummary.timeline.immediate_actions}
                        </p>
                      </div>

                      {/* Short-term */}
                      <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
                        <p className="text-sm font-semibold text-amber-800 dark:text-amber-400">
                          Short-term Improvements
                        </p>
                        <p className="text-xl font-bold text-amber-700 dark:text-amber-300 mt-2">
                          {executiveSummary.timeline.short_term_improvements}
                        </p>
                      </div>

                      {/* Long-term */}
                      <div className="rounded-lg border border-green-300 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950/30">
                        <p className="text-sm font-semibold text-green-800 dark:text-green-400">
                          Long-term Transformation
                        </p>
                        <p className="text-xl font-bold text-green-700 dark:text-green-300 mt-2">
                          {executiveSummary.timeline.long_term_transformation}
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </CardContent>
            </Card>
          )}

          {/* ============================================================= */}
          {/* Trend Analysis (Charts)                                         */}
          {/* ============================================================= */}
          {trendData && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-5 w-5 text-emerald-600" />
                  Trend Analysis & Benchmarking
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Score History + Improvement Velocity */}
                <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-4">
                  {/* Line Chart */}
                  <Card className="border shadow-none">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">
                        Score Progression Over Time
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ReportsLineChart data={trendData.score_history} />
                    </CardContent>
                  </Card>

                  {/* Improvement Velocity Sidebar */}
                  <Card className="border shadow-none">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">
                        Improvement Velocity
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                      <div>
                        <p className="text-sm text-muted-foreground">
                          Monthly Improvement
                        </p>
                        <p className="text-3xl font-bold text-emerald-600">
                          +{trendData.improvement_velocity.monthly_improvement}%
                        </p>
                      </div>
                      <Separator />
                      <div>
                        <p className="text-sm text-muted-foreground">
                          Projected (3 months)
                        </p>
                        <p className="text-2xl font-semibold">
                          {
                            trendData.improvement_velocity
                              .projected_score_3months
                          }
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-muted-foreground">
                          Projected (6 months)
                        </p>
                        <p className="text-2xl font-semibold">
                          {
                            trendData.improvement_velocity
                              .projected_score_6months
                          }
                        </p>
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Benchmark Comparison Bar Chart */}
                <Card className="border shadow-none">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">
                      Industry Benchmark Comparison
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ReportsBenchmarkChart data={[
                      { name: "Industry Average", score: trendData.benchmark_comparison.industry_average },
                      { name: "Your Score", score: trendData.benchmark_comparison.your_score },
                      { name: "Top Quartile", score: trendData.benchmark_comparison.top_quartile },
                    ]} />
                    <Alert className="mt-4">
                      <Info className="h-4 w-4" />
                      <AlertDescription>
                        Your score of{" "}
                        <strong>
                          {trendData.benchmark_comparison.your_score}
                        </strong>{" "}
                        places you in the{" "}
                        <strong>
                          {trendData.benchmark_comparison.percentile}th
                          percentile
                        </strong>{" "}
                        for your industry.
                      </AlertDescription>
                    </Alert>
                  </CardContent>
                </Card>
              </CardContent>
            </Card>
          )}

          {/* ============================================================= */}
          {/* Footer                                                         */}
          {/* ============================================================= */}
          <Separator />
          <div className="text-center py-4 space-y-1">
            <p className="text-sm text-muted-foreground">
              Session ID: {sessionId}
            </p>
            <p className="text-xs text-muted-foreground">
              Generated on {new Date().toLocaleString()} | AWS Well-Architected
              Framework Review
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
