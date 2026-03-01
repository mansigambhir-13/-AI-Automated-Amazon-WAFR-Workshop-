"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Header from "@/components/header";
import * as backend from "@/lib/backend-api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface LogEvent {
  message: string;
  timestamp: string;
  phase: string;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */
const PHASES = [
  "Initialization",
  "Analyzing Transcript",
  "Evaluating Architecture",
  "Generating Insights",
  "Identifying Gaps",
  "Completed",
] as const;

const PHASE_DESCRIPTIONS: Record<number, string> = {
  0: "Setting up the assessment pipeline, loading AI models, and preparing the evaluation framework against all six AWS Well-Architected pillars.",
  1: "Parsing and analyzing the uploaded transcript to extract architectural decisions, technology choices, and design patterns discussed during the review session.",
  2: "Evaluating the identified architecture against AWS best practices for operational excellence, security, reliability, performance efficiency, cost optimization, and sustainability.",
  3: "Synthesizing analysis results into actionable insights, scoring each pillar, and identifying strengths in your current architecture.",
  4: "Cross-referencing findings against the Well-Architected Framework to pinpoint gaps, risks, and areas that need improvement.",
  5: "Assessment complete! Your results are ready for review. Redirecting you to the detailed findings and recommendations.",
};

/* ------------------------------------------------------------------ */
/*  Utility: format time                                               */
/* ------------------------------------------------------------------ */
function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

/** Single stepper node */
function StepNode({
  index,
  label,
  status,
  isLast,
}: {
  index: number;
  label: string;
  status: "done" | "active" | "pending";
  isLast: boolean;
}) {
  const circleBase =
    "relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold transition-all duration-500";
  const circleVariant =
    status === "done"
      ? "bg-green-500 text-white shadow-lg shadow-green-500/30"
      : status === "active"
        ? "bg-primary text-primary-foreground shadow-lg shadow-primary/40 animate-pulse"
        : "bg-gray-300 dark:bg-gray-600 text-muted-foreground";

  const labelColor =
    status === "done"
      ? "text-green-600 dark:text-green-400 font-semibold"
      : status === "active"
        ? "text-primary font-semibold"
        : "text-muted-foreground";

  const lineColor =
    status === "done"
      ? "bg-green-500"
      : "bg-gray-300 dark:bg-gray-600";

  return (
    <div className="flex items-center flex-1 min-w-0 last:flex-none">
      {/* Circle + Label */}
      <div className="flex flex-col items-center gap-2">
        <div className={`${circleBase} ${circleVariant}`}>
          {status === "done" ? (
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            index + 1
          )}
        </div>
        <span className={`text-xs text-center whitespace-nowrap ${labelColor}`}>
          {label}
        </span>
      </div>

      {/* Connecting line */}
      {!isLast && (
        <div className="flex-1 mx-2 self-start mt-5">
          <div className={`h-0.5 w-full rounded-full transition-colors duration-500 ${lineColor}`} />
        </div>
      )}
    </div>
  );
}

/** SVG circular progress ring */
function ProgressRing({ progress }: { progress: number }) {
  const SIZE = 200;
  const STROKE = 12;
  const RADIUS = (SIZE - STROKE) / 2;
  const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
  const offset = CIRCUMFERENCE - (progress / 100) * CIRCUMFERENCE;

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={SIZE} height={SIZE} className="-rotate-90">
        {/* Background ring */}
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
          className="text-gray-200 dark:text-gray-700"
        />
        {/* Progress ring */}
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
          className="stroke-primary transition-all duration-700 ease-out"
          style={{ filter: "drop-shadow(0 0 6px oklch(0.750 0.160 55 / 0.4))" }}
        />
      </svg>
      {/* Center text */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-5xl font-extrabold text-primary">
          {Math.round(progress)}%
        </span>
        <span className="text-sm text-muted-foreground mt-1">
          Complete
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Utility: map backend step string to PHASES index                   */
/* ------------------------------------------------------------------ */
function mapStepToPhase(step: string): number {
  const stepMap: Record<string, number> = {
    'understanding': 1,
    'answer_synthesis': 2,
    'confidence': 2,
    'scoring': 3,
    'gap_detection': 4,
    'report': 5,
  };
  return stepMap[step] ?? 0;
}

/* ------------------------------------------------------------------ */
/*  Main page component                                                */
/* ------------------------------------------------------------------ */
export default function ProgressPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;

  const [progress, setProgress] = useState(0);
  const [activeStep, setActiveStep] = useState(0);
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [startedAt] = useState(() => new Date().toISOString());
  const [isComplete, setIsComplete] = useState(false);

  const logContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll the log container
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [events]);

  // Stable callback to add a log event
  const addEvent = useCallback((message: string, phase: string) => {
    setEvents((prev) => [
      ...prev,
      {
        message,
        timestamp: new Date().toISOString(),
        phase,
      },
    ]);
  }, []);

  // Poll backend for real progress
  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const stateData = await backend.getSessionState(sessionId);
        if (cancelled) return;

        setProgress(stateData.progress);
        const phase = mapStepToPhase(stateData.step);
        setActiveStep(phase);

        // Add log event for step changes
        if (stateData.step) {
          addEvent(`Processing: ${stateData.step.replace(/_/g, ' ')}`, PHASES[phase]);
        }

        const status = stateData.status.toUpperCase();
        if (status === 'COMPLETED' || status === 'FINALIZED') {
          setProgress(100);
          setActiveStep(PHASES.length - 1);
          setIsComplete(true);
          return; // Stop polling
        }
        if (status === 'ERROR') {
          addEvent('Assessment encountered an error', 'Error');
          return; // Stop polling
        }
      } catch {
        // Session may not exist yet or backend unavailable, keep polling
      }

      if (!cancelled) {
        setTimeout(poll, 3000);
      }
    };

    poll();

    return () => {
      cancelled = true;
    };
  }, [sessionId, addEvent]);

  // Navigate to results when complete
  useEffect(() => {
    if (isComplete) {
      const timeout = setTimeout(() => {
        router.push(`/results/${sessionId}`);
      }, 2000);
      return () => clearTimeout(timeout);
    }
  }, [isComplete, router, sessionId]);

  // Derive step statuses
  function getStepStatus(index: number): "done" | "active" | "pending" {
    if (index < activeStep) return "done";
    if (index === activeStep) return isComplete && index === PHASES.length - 1 ? "done" : "active";
    return "pending";
  }

  // Current status label
  const statusLabel = isComplete ? "Completed" : "In Progress";

  return (
    <div className="min-h-screen bg-background">
      <Header />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page heading */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-foreground">
            Assessment in Progress
          </h1>
          <p className="mt-1 text-muted-foreground">
            Evaluating your workload against the AWS Well-Architected Framework
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* ============ LEFT / MAIN COLUMN ============ */}
          <div className="lg:col-span-2 space-y-6">
            {/* Stepper card */}
            <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-foreground mb-6">
                Assessment Pipeline
              </h2>
              <div className="flex items-start overflow-x-auto pb-2">
                {PHASES.map((label, i) => (
                  <StepNode
                    key={label}
                    index={i}
                    label={label}
                    status={getStepStatus(i)}
                    isLast={i === PHASES.length - 1}
                  />
                ))}
              </div>
            </div>

            {/* Progress ring card */}
            <div className="bg-card rounded-xl border border-border p-8 shadow-sm flex flex-col items-center gap-6">
              <ProgressRing progress={progress} />

              {/* Current phase badge */}
              <div className="flex items-center gap-3">
                {!isComplete && (
                  <span className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-primary" />
                  </span>
                )}
                <span className="text-lg font-semibold text-foreground">
                  {PHASES[activeStep]}
                </span>
              </div>

              {/* Linear progress bar */}
              <div className="w-full max-w-md">
                <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-700 ease-out"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Activity log card */}
            <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-foreground mb-4">
                Activity Log
              </h2>

              <div
                ref={logContainerRef}
                className="max-h-72 overflow-y-auto rounded-lg bg-muted border border-border divide-y divide-gray-100 dark:divide-gray-700"
              >
                {events.length === 0 ? (
                  <div className="flex items-center gap-3 px-4 py-4 text-muted-foreground">
                    <svg
                      className="h-5 w-5 animate-spin text-primary"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                      />
                    </svg>
                    <span className="text-sm">Waiting for events...</span>
                  </div>
                ) : (
                  events.map((event, index) => (
                    <div
                      key={index}
                      className="flex items-start gap-3 px-4 py-3 transition-colors duration-300 animate-fade-in"
                    >
                      {/* Check icon */}
                      <div className="mt-0.5 shrink-0">
                        <svg
                          className="h-4 w-4 text-green-500"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={3}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M5 13l4 4L19 7"
                          />
                        </svg>
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-foreground">
                          {event.message}
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {formatTime(event.timestamp)} &middot; {event.phase}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* ============ RIGHT SIDEBAR ============ */}
          <div className="space-y-6">
            {/* Session info */}
            <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
              <h3 className="text-base font-semibold text-foreground mb-4">
                Session Information
              </h3>

              <div className="space-y-4">
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">
                    Session ID
                  </p>
                  <p className="text-sm font-mono text-foreground/80 break-all">
                    {sessionId}
                  </p>
                </div>

                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">
                    Status
                  </p>
                  <span
                    className={`inline-flex items-center gap-1.5 text-sm font-semibold ${
                      isComplete
                        ? "text-green-600 dark:text-green-400"
                        : "text-primary"
                    }`}
                  >
                    {!isComplete && (
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
                      </span>
                    )}
                    {isComplete && (
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                    {statusLabel}
                  </span>
                </div>

                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">
                    Started
                  </p>
                  <p className="text-sm text-foreground/80">
                    {new Date(startedAt).toLocaleString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                </div>
              </div>
            </div>

            {/* What's happening */}
            <div className="bg-gradient-to-br from-slate-900 to-slate-950 dark:from-card dark:to-background rounded-xl p-6 shadow-sm border border-border">
              <h3 className="text-base font-semibold text-white mb-3 flex items-center gap-2">
                <svg className="h-5 w-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                What&apos;s Happening
              </h3>
              <p className="text-sm text-gray-300 leading-relaxed">
                {PHASE_DESCRIPTIONS[activeStep]}
              </p>
            </div>

            {/* Next steps */}
            <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
              <h3 className="text-base font-semibold text-foreground mb-4 flex items-center gap-2">
                <svg className="h-5 w-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
                Next Steps
              </h3>
              <ul className="space-y-3">
                {[
                  "Review assessment results",
                  "Examine insights and recommendations",
                  "Approve or reject findings",
                  "Generate comprehensive report",
                ].map((step, i) => (
                  <li key={i} className="flex items-start gap-2.5">
                    <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold">
                      {i + 1}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {step}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Completion redirect notice */}
            {isComplete && (
              <div className="bg-green-50 dark:bg-green-900/20 rounded-xl border border-green-200 dark:border-green-800 p-4 shadow-sm animate-fade-in">
                <div className="flex items-center gap-3">
                  <svg
                    className="h-6 w-6 text-green-500 shrink-0 animate-bounce"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  <div>
                    <p className="text-sm font-semibold text-green-800 dark:text-green-300">
                      Assessment Complete!
                    </p>
                    <p className="text-xs text-green-600 dark:text-green-400 mt-0.5">
                      Redirecting to results...
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}
