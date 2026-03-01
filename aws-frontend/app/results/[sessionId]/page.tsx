"use client";

import React, { useEffect, useState, useCallback, use } from "react";
import Link from "next/link";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import dynamic from "next/dynamic";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  FileText,
  TrendingUp,
  Lightbulb,
  AlertTriangle,
  HelpCircle,
  CheckCircle2,
  Clock,
  ShieldAlert,
  BookOpen,
  Wrench,
} from "lucide-react";

import Header from "@/components/header";
import PillarCard from "@/components/pillar-card";
import InsightCard from "@/components/insight-card";
import GapCard from "@/components/gap-card";
import StatCard from "@/components/stat-card";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";

import * as backend from "@/lib/backend-api";
import type { Pillar, Insight, Question, Gap } from "@/lib/types";

const ResultsRadarChart = dynamic(() => import("@/components/charts/results-radar-chart"), { ssr: false });
const ResultsBarChart = dynamic(() => import("@/components/charts/results-bar-chart"), { ssr: false });

// ---------------------------------------------------------------------------
// Risk-level badge helper
// ---------------------------------------------------------------------------
function getRiskBadgeClasses(level: string): string {
  switch (level?.toLowerCase()) {
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

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------
export default function ResultsPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);

  const [pillars, setPillars] = useState<Pillar[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadProgress, setLoadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // -----------------------------------------------------------------------
  // Tab ↔ URL search-param sync
  // -----------------------------------------------------------------------
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const validTabs = ["pillars", "insights", "questions", "gaps"] as const;
  const tabParam = searchParams.get("tab");
  const activeTab = validTabs.includes(tabParam as (typeof validTabs)[number])
    ? tabParam!
    : "pillars";

  const handleTabChange = useCallback(
    (value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", value);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  // -----------------------------------------------------------------------
  // Data fetching
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function loadResults() {
      try {
        setLoadProgress(20);

        const [pillarsRes, insightsRes, questionsRes, gapsRes] =
          await Promise.all([
            backend.getPillars(sessionId),
            backend.getInsights(sessionId),
            backend.getQuestions(sessionId),
            backend.getGaps(sessionId),
          ]);

        if (cancelled) return;

        setLoadProgress(80);
        setPillars(pillarsRes);
        setInsights(insightsRes);
        setQuestions(questionsRes);
        setGaps(gapsRes);
        setLoadProgress(100);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load results');
        setLoadProgress(100);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadResults();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // -----------------------------------------------------------------------
  // Derived values
  // -----------------------------------------------------------------------
  const averageScore =
    pillars.length > 0
      ? Math.round(
          pillars.reduce((sum, p) => sum + p.score, 0) / pillars.length
        )
      : 0;

  const answeredCount = questions.filter(
    (q) => q.status === "Answered"
  ).length;

  // Radar chart data
  const radarData = pillars.map((p) => ({
    name: p.name.split(" ")[0],
    score: p.score,
    fullMark: 100,
  }));

  // Bar chart data
  const barData = pillars.map((p) => ({
    name: p.name,
    score: p.score,
  }));

  // -----------------------------------------------------------------------
  // Loading state
  // -----------------------------------------------------------------------
  if (loading) {
    return (
      <div className="min-h-screen bg-background">
        <Header />
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <Card className="mx-auto max-w-lg">
            <CardContent className="flex flex-col items-center gap-6 p-8">
              <div className="animate-pulse rounded-full bg-primary/20 p-4">
                <BarChart3 className="h-8 w-8 text-primary" />
              </div>
              <div className="w-full space-y-3 text-center">
                <h2 className="text-lg font-semibold">
                  Loading assessment results...
                </h2>
                <p className="text-sm text-muted-foreground">
                  Fetching pillars, insights, questions, and gaps
                </p>
                <Progress
                  value={loadProgress}
                  className="h-2 [&>[data-slot=progress-indicator]]:bg-primary"
                />
                <p className="text-xs text-muted-foreground">
                  {loadProgress}% complete
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Error state
  // -----------------------------------------------------------------------
  if (error) {
    return (
      <div className="min-h-screen bg-background">
        <Header />
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <Card className="mx-auto max-w-lg">
            <CardContent className="flex flex-col items-center gap-4 p-8">
              <AlertTriangle className="h-8 w-8 text-red-500" />
              <h2 className="text-lg font-semibold">Failed to load results</h2>
              <p className="text-sm text-muted-foreground text-center">{error}</p>
              <Link href="/">
                <Button variant="outline">Back to Dashboard</Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------
  return (
    <div className="min-h-screen bg-background">
      <Header />

      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* ----------------------------------------------------------------- */}
        {/* Page header                                                        */}
        {/* ----------------------------------------------------------------- */}
        <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-3xl font-bold font-heading tracking-tight animate-fade-up">
              Assessment Results
            </h1>
            <p className="mt-1 text-muted-foreground">
              Comprehensive evaluation across AWS Well-Architected Framework
              pillars
            </p>
          </div>
          <Link href="/">
            <Button variant="outline" className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back to Dashboard
            </Button>
          </Link>
        </div>

        {/* ----------------------------------------------------------------- */}
        {/* Summary stat cards                                                 */}
        {/* ----------------------------------------------------------------- */}
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 stagger-children">
          <StatCard
            title="Overall Score"
            value={averageScore}
            subtitle="out of 100"
            icon={<TrendingUp className="h-12 w-12" />}
            gradient="bg-gradient-to-br from-amber-500 to-orange-600"
          />
          <StatCard
            title="Total Insights"
            value={insights.length}
            subtitle={`${insights.filter((i) => i.severity === "High").length} high severity`}
            icon={<Lightbulb className="h-12 w-12" />}
            gradient="bg-gradient-to-br from-blue-500 to-blue-700"
          />
          <StatCard
            title="Identified Gaps"
            value={gaps.length}
            subtitle="requires attention"
            icon={<AlertTriangle className="h-12 w-12" />}
            gradient="bg-gradient-to-br from-red-500 to-red-700"
          />
          <StatCard
            title="Questions Answered"
            value={`${answeredCount}/${questions.length}`}
            subtitle={
              answeredCount === questions.length
                ? "all completed"
                : `${questions.length - answeredCount} pending`
            }
            icon={<HelpCircle className="h-12 w-12" />}
            gradient="bg-gradient-to-br from-green-500 to-green-700"
          />
        </div>

        {/* ----------------------------------------------------------------- */}
        {/* Tabs                                                               */}
        {/* ----------------------------------------------------------------- */}
        <Tabs value={activeTab} onValueChange={handleTabChange} className="space-y-6">
          <TabsList
            variant="line"
            className="w-full justify-start border-b pb-0"
          >
            <TabsTrigger value="pillars" className="gap-1.5">
              <BarChart3 className="h-4 w-4" />
              Pillars Overview
            </TabsTrigger>
            <TabsTrigger value="insights" className="gap-1.5">
              <Lightbulb className="h-4 w-4" />
              Key Insights
            </TabsTrigger>
            <TabsTrigger value="questions" className="gap-1.5">
              <HelpCircle className="h-4 w-4" />
              Questions
            </TabsTrigger>
            <TabsTrigger value="gaps" className="gap-1.5">
              <AlertTriangle className="h-4 w-4" />
              Identified Gaps
            </TabsTrigger>
          </TabsList>

          {/* =============================================================== */}
          {/* Tab 1: Pillars Overview                                          */}
          {/* =============================================================== */}
          <TabsContent value="pillars" className="space-y-6">
            {/* Pillar cards grid */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {pillars.map((pillar) => (
                <PillarCard
                  key={pillar.name}
                  name={pillar.name}
                  score={pillar.score}
                  description={pillar.description}
                />
              ))}
            </div>

            {/* Charts row */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {/* Radar Chart */}
              <Card className="relative overflow-hidden">
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/[0.04] via-transparent to-chart-3/[0.04]" />
                <CardHeader className="relative">
                  <CardTitle className="text-base">Radar Analysis</CardTitle>
                  <CardDescription>
                    Visual overview of pillar scores across the framework
                  </CardDescription>
                </CardHeader>
                <CardContent className="relative">
                  <ResultsRadarChart data={radarData} />
                </CardContent>
              </Card>

              {/* Bar Chart */}
              <Card className="relative overflow-hidden">
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-chart-2/[0.04] via-transparent to-chart-4/[0.04]" />
                <CardHeader className="relative">
                  <CardTitle className="text-base">
                    Score Distribution
                  </CardTitle>
                  <CardDescription>
                    Pillar scores displayed as horizontal bars
                  </CardDescription>
                </CardHeader>
                <CardContent className="relative">
                  <ResultsBarChart data={barData} />
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* =============================================================== */}
          {/* Tab 2: Key Insights                                              */}
          {/* =============================================================== */}
          <TabsContent value="insights" className="space-y-4">
            <div className="mb-4">
              <h2 className="text-lg font-semibold">
                Key Insights &amp; Recommendations
              </h2>
              <p className="text-sm text-muted-foreground">
                {insights.length} insights identified across all pillars
              </p>
            </div>

            {insights.length === 0 ? (
              <Card>
                <CardContent className="flex flex-col items-center gap-3 py-12">
                  <Lightbulb className="h-10 w-10 text-muted-foreground/40" />
                  <p className="text-muted-foreground">
                    No insights found for this assessment.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-4">
                {insights.map((insight) => (
                  <InsightCard
                    key={insight.id}
                    insight={{
                      id: insight.id,
                      title: insight.title,
                      severity: insight.severity,
                      pillar: insight.pillar,
                      description: insight.description,
                      recommendation: insight.recommendation,
                      effort: insight.effort,
                      cost_impact: insight.cost_impact,
                      affected_resources: insight.affected_resources,
                      implementation_steps: insight.implementation_steps,
                    }}
                  />
                ))}
              </div>
            )}
          </TabsContent>

          {/* =============================================================== */}
          {/* Tab 3: Questions                                                 */}
          {/* =============================================================== */}
          <TabsContent value="questions" className="space-y-4">
            <div className="mb-4">
              <h2 className="text-lg font-semibold">
                Assessment Questions by Pillar
              </h2>
              <p className="text-sm text-muted-foreground">
                {answeredCount} of {questions.length} questions answered
              </p>
            </div>

            {questions.length === 0 ? (
              <Card>
                <CardContent className="flex flex-col items-center gap-3 py-12">
                  <HelpCircle className="h-10 w-10 text-muted-foreground/40" />
                  <p className="text-muted-foreground">
                    No questions found for this assessment.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-3">
                {questions.map((question) => (
                  <Card key={question.id} className="overflow-hidden">
                    <CardContent className="p-5">
                      {/* Top row: badges */}
                      <div className="mb-3 flex flex-wrap items-center gap-2">
                        <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
                          {question.pillar}
                        </Badge>
                        <Badge variant="outline">{question.category}</Badge>
                        <Badge
                          className={
                            question.status === "Answered"
                              ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
                              : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400"
                          }
                        >
                          {question.status === "Answered" ? (
                            <CheckCircle2 className="mr-1 h-3 w-3" />
                          ) : (
                            <Clock className="mr-1 h-3 w-3" />
                          )}
                          {question.status}
                        </Badge>
                        <Badge className={getRiskBadgeClasses(question.risk_level)}>
                          <ShieldAlert className="mr-1 h-3 w-3" />
                          {question.risk_level} Risk
                        </Badge>
                      </div>

                      {/* Question text */}
                      <p className="mb-3 text-sm font-medium leading-relaxed">
                        {question.text}
                      </p>

                      {/* Answer */}
                      {question.answer ? (
                        <div className="mb-3 rounded-lg bg-muted p-3">
                          <p className="mb-1 text-xs font-semibold text-muted-foreground">
                            Answer
                          </p>
                          <p className="text-sm">{question.answer}</p>
                        </div>
                      ) : (
                        <div className="mb-3 rounded-lg border border-dashed border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-900/20">
                          <p className="text-sm text-amber-700 dark:text-amber-400">
                            Pending - This question has not been answered yet.
                          </p>
                        </div>
                      )}

                      {/* Best practice + Improvement plan */}
                      <div className="flex flex-col gap-2 sm:flex-row sm:gap-4">
                        {question.best_practice && (
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <BookOpen className="h-3.5 w-3.5 shrink-0" />
                            <span>
                              Best Practice:{" "}
                              <span className="font-medium text-foreground">
                                {question.best_practice}
                              </span>
                            </span>
                          </div>
                        )}
                        {question.improvement_plan && (
                          <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
                            <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            <span>
                              Improvement:{" "}
                              <span className="font-medium text-foreground">
                                {question.improvement_plan}
                              </span>
                            </span>
                          </div>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </TabsContent>

          {/* =============================================================== */}
          {/* Tab 4: Identified Gaps                                           */}
          {/* =============================================================== */}
          <TabsContent value="gaps" className="space-y-4">
            <div className="mb-4">
              <h2 className="text-lg font-semibold">Identified Gaps</h2>
              <p className="text-sm text-muted-foreground">
                {gaps.length} architectural gaps identified &mdash; address
                high-risk gaps immediately to improve resilience and security
              </p>
            </div>

            {gaps.length === 0 ? (
              <Card>
                <CardContent className="flex flex-col items-center gap-3 py-12">
                  <AlertTriangle className="h-10 w-10 text-muted-foreground/40" />
                  <p className="text-muted-foreground">
                    No gaps identified for this assessment.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-4">
                {gaps.map((gap) => (
                  <GapCard
                    key={gap.id}
                    gap={{
                      id: gap.id,
                      title: gap.title,
                      risk_level: gap.risk_level,
                      pillar: gap.pillar,
                      description: gap.description,
                      current_state: gap.current_state,
                      target_state: gap.target_state,
                      mitigation: gap.mitigation,
                      business_impact: gap.business_impact,
                      timeline: gap.timeline,
                      estimated_cost: gap.estimated_cost,
                      remediation_steps: gap.remediation_steps,
                    }}
                  />
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>

        {/* ----------------------------------------------------------------- */}
        {/* Bottom navigation                                                  */}
        {/* ----------------------------------------------------------------- */}
        <Card className="mt-8 border-0 bg-gradient-to-r from-slate-900 to-slate-800 dark:from-card dark:to-muted text-white">
          <CardContent className="flex flex-col items-center justify-between gap-4 p-6 sm:flex-row">
            <div>
              <h3 className="text-lg font-semibold">
                Ready for the next step?
              </h3>
              <p className="text-sm text-white/70">
                Review findings with your team, approve recommendations, and
                generate a comprehensive report.
              </p>
            </div>
            <div className="flex gap-3">
              <Link href={`/review/${sessionId}`}>
                <Button
                  variant="outline"
                  className="gap-2 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white"
                >
                  <FileText className="h-4 w-4" />
                  Start Review
                </Button>
              </Link>
              <Link href={`/reports/${sessionId}`}>
                <Button className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90">
                  View Reports
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
