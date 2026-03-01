"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { getCurrentUserInfo, isTeamUser } from "@/lib/auth";
import Header from "@/components/header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { startAssessment } from "@/lib/sse-client";
import {
  Send,
  Info,
  Clock,
  Loader2,
  AlertCircle,
  Check,
} from "lucide-react";

const STEPS = ["Workload Details", "Assessment", "Results"] as const;
const CURRENT_STEP = 0;

const PILLARS = [
  "Operational Excellence",
  "Security",
  "Reliability",
  "Performance Efficiency",
  "Cost Optimization",
  "Sustainability",
] as const;

export default function NewAssessmentPage() {
  const router = useRouter();
  const [authorized, setAuthorized] = useState(false);
  const [formData, setFormData] = useState({
    applicationName: "",
    workloadDescription: "",
    environment: "",
    owner: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<{ abort: () => void } | null>(null);

  useEffect(() => {
    getCurrentUserInfo()
      .then(info => {
        if (!isTeamUser(info.groups)) {
          router.push("/"); // Redirect clients to dashboard
        } else {
          setAuthorized(true);
        }
      })
      .catch(() => router.push("/"));
  }, [router]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const transcript = `
Application: ${formData.applicationName}
Environment: ${formData.environment}
Owner: ${formData.owner}

Workload Description:
${formData.workloadDescription}
`.trim();

      const { abort } = startAssessment(
        {
          transcript,
          clientName: formData.applicationName,
          generateReport: true,
        },
        {
          onRunStarted: (sessionId) => {
            router.push(`/progress/${sessionId}`);
          },
          onRunError: (error) => {
            setError(error);
            setLoading(false);
          },
        },
      );
      abortRef.current = { abort };
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to start assessment";
      setError(message);
    }
  };

  if (!authorized) return null;

  return (
    <>
      <Header />

      <div className="min-h-[calc(100vh-64px)]">
        <div className="max-w-6xl mx-auto px-6 py-8">
          {/* Page Title */}
          <div className="mb-8">
            <h1 className="text-3xl font-bold font-heading text-foreground mb-1">
              New Well-Architected Assessment
            </h1>
            <p className="text-muted-foreground">
              Evaluate your workload against AWS best practices
            </p>
          </div>

          {/* Main Grid: Form (8) + Sidebar (4) */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
            {/* Left Column -- Form */}
            <div className="md:col-span-8">
              <Card className="animate-fade-up">
                <CardContent className="pt-0">
                  {/* Stepper */}
                  <div className="mb-8">
                    <div className="flex items-center justify-between">
                      {STEPS.map((label, idx) => (
                        <div key={label} className="flex items-center flex-1">
                          {/* Step Circle + Label */}
                          <div className="flex flex-col items-center">
                            <div
                              className={`flex items-center justify-center h-9 w-9 rounded-full border-2 text-sm font-bold transition-colors ${
                                idx < CURRENT_STEP
                                  ? "bg-primary border-primary text-primary-foreground"
                                  : idx === CURRENT_STEP
                                    ? "bg-primary border-primary text-primary-foreground"
                                    : "border-gray-300 dark:border-gray-600 text-gray-400 dark:text-gray-500 bg-white dark:bg-gray-800"
                              }`}
                            >
                              {idx < CURRENT_STEP ? (
                                <Check className="h-4 w-4" />
                              ) : (
                                idx + 1
                              )}
                            </div>
                            <span
                              className={`mt-2 text-xs font-medium whitespace-nowrap ${
                                idx <= CURRENT_STEP
                                  ? "text-primary"
                                  : "text-gray-400 dark:text-gray-500"
                              }`}
                            >
                              {label}
                            </span>
                          </div>

                          {/* Connecting Line */}
                          {idx < STEPS.length - 1 && (
                            <div
                              className={`flex-1 h-0.5 mx-3 mt-[-1.25rem] ${
                                idx < CURRENT_STEP
                                  ? "bg-primary"
                                  : "bg-gray-300 dark:bg-gray-600"
                              }`}
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Error Alert */}
                  {error && (
                    <Alert variant="destructive" className="mb-6">
                      <AlertCircle className="h-4 w-4" />
                      <AlertTitle>Error</AlertTitle>
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}

                  {/* Form */}
                  <form onSubmit={handleSubmit}>
                    <h2 className="text-lg font-semibold text-foreground mb-2">
                      Workload Information
                    </h2>
                    <Separator className="mb-6" />

                    {/* Application Name */}
                    <div className="mb-5">
                      <Label
                        htmlFor="applicationName"
                        className="text-foreground/80 mb-1.5"
                      >
                        Application Name <span className="text-red-500">*</span>
                      </Label>
                      <Input
                        id="applicationName"
                        name="applicationName"
                        required
                        value={formData.applicationName}
                        onChange={handleChange}
                        placeholder="e.g. E-Commerce Platform"
                      />
                      <p className="mt-1.5 text-xs text-muted-foreground">
                        Enter a descriptive name for your workload
                      </p>
                    </div>

                    {/* Workload Description */}
                    <div className="mb-5">
                      <Label
                        htmlFor="workloadDescription"
                        className="text-foreground/80 mb-1.5"
                      >
                        Workload Description{" "}
                        <span className="text-red-500">*</span>
                      </Label>
                      <Textarea
                        id="workloadDescription"
                        name="workloadDescription"
                        required
                        rows={6}
                        value={formData.workloadDescription}
                        onChange={handleChange}
                        placeholder="Example: A multi-tier web application with React frontend, Node.js microservices, PostgreSQL database, and Redis cache. Deployed on AWS ECS with Application Load Balancer..."
                      />
                      <p className="mt-1.5 text-xs text-muted-foreground">
                        Describe your workload architecture, components,
                        technologies, and key characteristics
                      </p>
                    </div>

                    {/* Environment + Owner (two columns) */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-5">
                      <div>
                        <Label
                          htmlFor="environment"
                          className="text-foreground/80 mb-1.5"
                        >
                          Environment
                        </Label>
                        <Input
                          id="environment"
                          name="environment"
                          value={formData.environment}
                          onChange={handleChange}
                          placeholder="Production"
                        />
                        <p className="mt-1.5 text-xs text-muted-foreground">
                          e.g., Production, Staging, Development
                        </p>
                      </div>
                      <div>
                        <Label
                          htmlFor="owner"
                          className="text-foreground/80 mb-1.5"
                        >
                          Owner / Team
                        </Label>
                        <Input
                          id="owner"
                          name="owner"
                          value={formData.owner}
                          onChange={handleChange}
                          placeholder="Platform Team"
                        />
                        <p className="mt-1.5 text-xs text-muted-foreground">
                          Team or person responsible
                        </p>
                      </div>
                    </div>

                    {/* Divider */}
                    <Separator className="my-6" />

                    {/* Actions */}
                    <div className="flex items-center justify-end gap-3">
                      <Button
                        type="button"
                        variant="outline"
                        size="lg"
                        disabled={loading}
                        onClick={() => router.push("/")}
                      >
                        Cancel
                      </Button>
                      <Button
                        type="submit"
                        size="lg"
                        disabled={loading}
                        className="bg-primary hover:bg-primary/90 text-primary-foreground font-semibold min-w-[180px]"
                      >
                        {loading ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin mr-1" />
                            Starting Assessment...
                          </>
                        ) : (
                          <>
                            <Send className="h-4 w-4 mr-1" />
                            Start Assessment
                          </>
                        )}
                      </Button>
                    </div>
                  </form>
                </CardContent>
              </Card>
            </div>

            {/* Right Column -- Sidebar */}
            <div className="md:col-span-4 space-y-4 stagger-children">
              {/* What to Expect */}
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Info className="h-5 w-5 text-blue-500" />
                    <CardTitle className="text-base">What to Expect</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <p className="text-sm text-muted-foreground mb-3">
                    The assessment will evaluate your workload across six
                    pillars:
                  </p>
                  <ul className="space-y-1.5">
                    {PILLARS.map((pillar) => (
                      <li
                        key={pillar}
                        className="flex items-center gap-2 text-sm text-muted-foreground"
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                        {pillar}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>

              {/* Assessment Duration */}
              <Card className="border-primary/20 bg-primary/5">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Clock className="h-5 w-5 text-primary" />
                    <CardTitle className="text-base">
                      Assessment Duration
                    </CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <p className="text-sm text-muted-foreground">
                    The automated assessment typically takes{" "}
                    <span className="font-semibold text-foreground">
                      2-5 minutes
                    </span>{" "}
                    to complete. You&apos;ll see real-time progress updates
                    during the evaluation.
                  </p>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
