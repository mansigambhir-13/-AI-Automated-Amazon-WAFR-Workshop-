"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Header from "@/components/header";
import StatCard from "@/components/stat-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import * as backend from "@/lib/backend-api";
import type { Session } from "@/lib/types";
import { getCurrentUserInfo, isTeamUser } from "@/lib/auth";
import {
  ClipboardList,
  CheckCircle,
  Zap,
  TrendingUp,
  Plus,
  Eye,
  Trash2,
  Shield,
  BarChart3,
  ArrowUpRight,
  Loader2,
} from "lucide-react";

export default function DashboardPage() {
  const router = useRouter();
  const [healthStatus, setHealthStatus] = useState<
    "healthy" | "unhealthy" | "checking"
  >("checking");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [metrics, setMetrics] = useState<{
    total: number;
    completed: number;
    inProgress: number;
    avgScore: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [isTeam, setIsTeam] = useState(true); // Default to team to avoid flash of hidden UI

  const checkHealth = useCallback(async () => {
    try {
      const data = await backend.checkHealth();
      setHealthStatus(data.status === "healthy" ? "healthy" : "unhealthy");
    } catch {
      setHealthStatus("unhealthy");
    }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const { sessions, metrics } = await backend.listSessions();
      setSessions(sessions);
      setMetrics(metrics);
    } catch (error) {
      console.error("Failed to load sessions:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
    loadSessions();
  }, [checkHealth, loadSessions]);

  useEffect(() => {
    getCurrentUserInfo()
      .then(info => {
        setIsTeam(isTeamUser(info.groups));
      })
      .catch(() => {
        setIsTeam(false);
      });
  }, []);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await backend.deleteSession(deleteTarget.id);
      loadSessions();
    } catch (error) {
      console.error("Failed to delete session:", error);
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const completedSessions = sessions.filter(
    (s) => s.status === "completed"
  ).length;
  const inProgressSessions = sessions.filter(
    (s) => s.status === "in-progress" || s.status === "pending"
  ).length;

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return (
          <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800">
            Completed
          </Badge>
        );
      case "in-progress":
        return (
          <Badge className="bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 border-amber-200 dark:border-amber-800">
            In Progress
          </Badge>
        );
      case "failed":
        return (
          <Badge className="bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 border-red-200 dark:border-red-800">
            Failed
          </Badge>
        );
      default:
        return (
          <Badge className="bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400 border-gray-200 dark:border-gray-700">
            {status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
          </Badge>
        );
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <>
      <Header />

      <div className="min-h-[calc(100vh-64px)]">
        <div className="max-w-7xl mx-auto px-6 py-8">
          {/* Page Header */}
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-8 gradient-wash">
            <div>
              <h1 className="text-3xl font-bold font-heading text-foreground mb-1 animate-fade-up">
                Well-Architected Framework Review
              </h1>
              <p className="text-muted-foreground">
                Assess your workloads against AWS best practices across six
                pillars
              </p>
            </div>
            <div className="flex items-center gap-3">
              {healthStatus === "checking" ? (
                <Badge className="bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 border-gray-300">
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                  Checking...
                </Badge>
              ) : healthStatus === "healthy" ? (
                <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800">
                  <span className="h-2 w-2 rounded-full bg-emerald-500 mr-1" />
                  System Healthy
                </Badge>
              ) : (
                <Badge className="bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 border-red-200 dark:border-red-800">
                  <span className="h-2 w-2 rounded-full bg-red-500 mr-1" />
                  System Unavailable
                </Badge>
              )}
              {isTeam && (
                <Button
                  className="bg-primary hover:bg-primary/90 text-primary-foreground font-semibold"
                  size="lg"
                  onClick={() => router.push("/new-assessment")}
                >
                  <Plus className="h-5 w-5 mr-1" />
                  New Assessment
                </Button>
              )}
            </div>
          </div>

          {/* Unhealthy Alert */}
          {healthStatus === "unhealthy" && (
            <div className="mb-6 rounded-lg border border-red-300 bg-red-50 dark:bg-red-900/20 dark:border-red-800 p-4">
              <p className="text-sm font-semibold text-red-800 dark:text-red-400">
                System health check failed
              </p>
              <p className="text-sm text-red-700 dark:text-red-400/80 mt-1">
                Please verify AWS credentials and API connectivity. Check the
                console for detailed error messages.
              </p>
            </div>
          )}

          {/* Stats Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8 stagger-children">
            <StatCard
              title="Total Assessments"
              value={metrics?.total ?? sessions.length}
              icon={<ClipboardList className="h-12 w-12" />}
              gradient="from-violet-500 to-purple-600"
            />
            <StatCard
              title="Completed"
              value={metrics?.completed ?? completedSessions}
              icon={<CheckCircle className="h-12 w-12" />}
              gradient="from-pink-500 to-rose-500"
            />
            <StatCard
              title="In Progress"
              value={metrics?.inProgress ?? inProgressSessions}
              icon={<Zap className="h-12 w-12" />}
              gradient="from-cyan-400 to-blue-500"
            />
            <StatCard
              title="Avg Score"
              value={metrics?.avgScore ?? "--"}
              icon={<TrendingUp className="h-12 w-12" />}
              gradient="from-amber-400 to-orange-500"
            />
          </div>

          {/* Sessions Table */}
          <Card className="mb-8">
            <CardHeader className="border-b">
              <CardTitle className="text-lg">Recent Assessments</CardTitle>
              <CardDescription>
                View and manage your Well-Architected Framework reviews
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {loading ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-primary mb-3" />
                  <p className="text-sm text-muted-foreground">
                    Loading assessments...
                  </p>
                </div>
              ) : sessions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 px-4">
                  <div className="rounded-full bg-muted p-4 mb-4">
                    <ClipboardList className="h-10 w-10 text-muted-foreground" />
                  </div>
                  <h3 className="text-lg font-semibold text-foreground mb-1">
                    No assessments yet
                  </h3>
                  <p className="text-sm text-muted-foreground mb-6 text-center max-w-sm">
                    Start your first Well-Architected Framework review to assess
                    your workload against AWS best practices.
                  </p>
                  {isTeam ? (
                    <Button
                      className="bg-primary hover:bg-primary/90 text-primary-foreground font-semibold"
                      onClick={() => router.push("/new-assessment")}
                    >
                      <Plus className="h-4 w-4 mr-1" />
                      Create Your First Assessment
                    </Button>
                  ) : (
                    <p className="text-sm text-muted-foreground text-center">
                      No assessments assigned to your account yet.
                    </p>
                  )}
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50">
                      <TableHead className="font-bold">
                        Assessment Name
                      </TableHead>
                      <TableHead className="font-bold">Session ID</TableHead>
                      <TableHead className="font-bold">Status</TableHead>
                      <TableHead className="font-bold">Created</TableHead>
                      <TableHead className="font-bold text-right">
                        Actions
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sessions.map((session) => (
                      <TableRow
                        key={session.id}
                        className="cursor-pointer"
                        onClick={() => router.push(`/results/${session.id}`)}
                      >
                        <TableCell className="font-semibold text-foreground">
                          {session.name}
                        </TableCell>
                        <TableCell className="font-mono text-sm text-muted-foreground">
                          {session.id}
                        </TableCell>
                        <TableCell>{getStatusBadge(session.status)}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {formatDate(session.created_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div
                            className="flex items-center justify-end gap-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              className="text-blue-600 hover:text-blue-700 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-900/30"
                              onClick={() =>
                                router.push(`/results/${session.id}`)
                              }
                              title="View Results"
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                            {isTeam && (
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                className="text-red-600 hover:text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/30"
                                onClick={() => setDeleteTarget(session)}
                                title="Delete Assessment"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Info Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 stagger-children">
            <Card className="h-full">
              <CardContent className="pt-0">
                <Shield className="h-10 w-10 text-primary mb-3" />
                <h3 className="text-lg font-semibold text-foreground mb-2">
                  Six Pillars
                </h3>
                <p className="text-sm text-muted-foreground">
                  Evaluate your architecture across Operational Excellence,
                  Security, Reliability, Performance Efficiency, Cost
                  Optimization, and Sustainability.
                </p>
              </CardContent>
            </Card>

            <Card className="h-full">
              <CardContent className="pt-0">
                <BarChart3 className="h-10 w-10 text-primary mb-3" />
                <h3 className="text-lg font-semibold text-foreground mb-2">
                  Best Practices
                </h3>
                <p className="text-sm text-muted-foreground">
                  Get actionable recommendations based on AWS Well-Architected
                  Framework best practices and real-world experience.
                </p>
              </CardContent>
            </Card>

            <Card className="h-full">
              <CardContent className="pt-0">
                <ArrowUpRight className="h-10 w-10 text-primary mb-3" />
                <h3 className="text-lg font-semibold text-foreground mb-2">
                  Continuous Improvement
                </h3>
                <p className="text-sm text-muted-foreground">
                  Track your progress over time and measure improvements as you
                  implement recommendations.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Assessment</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete{" "}
              <span className="font-semibold text-foreground">
                {deleteTarget?.name}
              </span>
              ? This action cannot be undone and all associated results will be
              permanently removed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              disabled={deleting}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {deleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                  Deleting...
                </>
              ) : (
                <>
                  <Trash2 className="h-4 w-4 mr-1.5" />
                  Delete
                </>
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
