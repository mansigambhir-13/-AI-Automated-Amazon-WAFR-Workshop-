# WAFR Backend Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the Next.js frontend to the FastAPI backend at localhost:8000, replacing all mock data with real API calls and SSE streaming.

**Architecture:** Create an adapter layer (`lib/backend-api.ts`) that maps backend responses to existing frontend TypeScript interfaces. Add an SSE client (`lib/sse-client.ts`) for consuming the real-time event stream from `POST /api/wafr/run`. Frontend calls the backend directly via `NEXT_PUBLIC_BACKEND_URL`. Remove all mock API routes.

**Tech Stack:** Next.js 16, TypeScript, EventSource/fetch SSE, FastAPI backend at :8000

**Reference Backend:** `/home/naveensynlex/Downloads/mansi-project/Wafragents/wafr-agents/wafr/ag_ui/server.py`

---

## Task 1: Extract types from mock-data into standalone types file

**Files:**
- Create: `lib/types.ts`
- Modify: `lib/mock-data.ts` (will be deleted in Task 5, but keep for now as reference)

**Step 1: Create lib/types.ts with all interfaces**

Copy all `export interface` declarations from `lib/mock-data.ts` into `lib/types.ts`. Keep them identical — these are the contracts the frontend components already use.

```typescript
// lib/types.ts
// All WAFR frontend data types

export interface Session {
  id: string;
  name: string;
  status: 'completed' | 'in-progress' | 'pending' | 'failed';
  created_at: string;
}

export interface PillarMetrics {
  [key: string]: string | number;
}

export interface PillarDetails {
  strengths: string[];
  improvements: string[];
  metrics: PillarMetrics;
}

export interface Pillar {
  name: string;
  score: number;
  description: string;
  details: PillarDetails;
}

export interface Insight {
  id: string;
  title: string;
  severity: 'High' | 'Medium' | 'Low';
  pillar: string;
  category: string;
  description: string;
  recommendation: string;
  impact: string;
  effort: string;
  cost_impact: string;
  affected_resources: string[];
  implementation_steps: string[];
  references: string[];
}

export interface Question {
  id: string;
  pillar: string;
  category: string;
  text: string;
  status: 'Answered' | 'Pending';
  answer: string | null;
  best_practice: string;
  notes: string;
  risk_level: 'High' | 'Medium' | 'Low';
  improvement_plan: string | null;
}

export interface Gap {
  id: string;
  title: string;
  pillar: string;
  risk_level: 'High' | 'Medium' | 'Low';
  category: string;
  description: string;
  mitigation: string;
  business_impact: string;
  current_state: string;
  target_state: string;
  timeline: string;
  priority: number;
  affected_services: string[];
  remediation_steps: string[];
  estimated_cost: string;
}

export interface ReviewItem {
  id: string;
  type: string;
  content: string;
  description: string;
  status: 'pending' | 'approved' | 'rejected';
  pillar: string;
  severity: 'High' | 'Medium' | 'Low';
  affected_resources: string[];
  recommendation: string;
  estimated_effort: string;
  auto_remediable: boolean;
}

export interface ReviewSummary {
  total_items: number;
  approved_items: number;
  rejected_items: number;
  pending_items: number;
  high_risk_gaps: number;
  medium_risk_gaps: number;
  low_risk_gaps: number;
  auto_remediable_count: number;
  estimated_total_effort: string;
  potential_cost_savings: string;
  potential_cost_increase: string;
}

export interface ScoreHistoryEntry {
  date: string;
  overall_score: number;
  security: number;
  reliability: number;
  performance: number;
  cost: number;
  operational: number;
  sustainability: number;
}

export interface TrendData {
  score_history: ScoreHistoryEntry[];
  improvement_velocity: {
    monthly_improvement: number;
    projected_score_3months: number;
    projected_score_6months: number;
  };
  benchmark_comparison: {
    industry_average: number;
    top_quartile: number;
    your_score: number;
    percentile: number;
  };
}

export interface ExecutiveSummary {
  overview: string;
  key_strengths: string[];
  critical_actions: string[];
  quick_wins: string[];
  investment_required: {
    immediate: string;
    short_term: string;
    long_term: string;
  };
  expected_benefits: {
    cost_savings: string;
    risk_reduction: string;
    performance_improvement: string;
    availability_improvement: string;
  };
  timeline: {
    immediate_actions: string;
    short_term_improvements: string;
    long_term_transformation: string;
  };
}

export interface Reviewer {
  name: string;
  email: string;
  role: string;
}

export interface WorkloadDetails {
  industry: string;
  architecture_type: string;
  deployment_model: string;
  compliance_requirements: string[];
  monthly_cost: string;
  monthly_traffic: string;
  team_size: number;
  services_count: number;
}

export interface AssessmentScope {
  pillars_assessed: number;
  questions_total: number;
  questions_answered: number;
  resources_analyzed: number;
  accounts_scanned: number;
  regions_scanned: string[];
}

export interface RiskSummary {
  critical_risks: number;
  high_risks: number;
  medium_risks: number;
  low_risks: number;
  total_risks: number;
}

export interface ComplianceStatus {
  compliant_checks: number;
  non_compliant_checks: number;
  compliance_percentage: number;
}

export interface SessionMetadata {
  session_id: string;
  assessment_name: string;
  workload_name: string;
  workload_description: string;
  environment: string;
  aws_account_id: string;
  region: string;
  created_at: string;
  completed_at: string;
  duration_minutes: number;
  status: string;
  reviewer: Reviewer;
  workload_details: WorkloadDetails;
  assessment_scope: AssessmentScope;
  risk_summary: RiskSummary;
  compliance_status: ComplianceStatus;
}

// Backend-specific types (for SSE events)
export interface SSEEvent {
  type: string;
  data?: Record<string, unknown>;
  timestamp?: string;
}

export interface BackendSession {
  session_id: string;
  assessment_name: string;
  status: string;
  current_step: string;
  progress: number;
  overall_score: number;
  client_name?: string;
  workload_id?: string;
  report_file?: string;
  created_at: string;
  updated_at: string;
}

export interface BackendSessionsResponse {
  sessions: BackendSession[];
  count: number;
  metrics: {
    total_assessments: number;
    completed: number;
    in_progress: number;
    avg_score: number;
  };
}
```

**Step 2: Commit**

```bash
git add lib/types.ts
git commit -m "feat: extract TypeScript interfaces into standalone types file"
```

---

## Task 2: Update lib/api.ts to use backend URL

**Files:**
- Modify: `lib/api.ts`

**Step 1: Update api.ts to prepend backend URL**

```typescript
// lib/api.ts
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export async function apiGet<T>(path: string): Promise<T> {
  const url = path.startsWith('http') ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url);
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const url = path.startsWith('http') ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const url = path.startsWith('http') ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export { BACKEND_URL };
```

**Step 2: Create .env.local**

```bash
# .env.local
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

**Step 3: Commit**

```bash
git add lib/api.ts .env.local
git commit -m "feat: update API helpers to use backend URL from env var"
```

---

## Task 3: Create SSE client for assessment streaming

**Files:**
- Create: `lib/sse-client.ts`

**Step 1: Create the SSE client**

```typescript
// lib/sse-client.ts
import { BACKEND_URL } from './api';

export interface SSECallbacks {
  onRunStarted?: (sessionId: string, runId: string) => void;
  onStepStarted?: (step: string) => void;
  onStepFinished?: (step: string, result?: Record<string, unknown>) => void;
  onStateSnapshot?: (state: Record<string, unknown>) => void;
  onStateDelta?: (patches: Array<{ op: string; path: string; value: unknown }>) => void;
  onProgress?: (step: string, percentage: number, message: string) => void;
  onTextMessage?: (text: string) => void;
  onRunFinished?: (sessionId: string) => void;
  onRunError?: (error: string, code?: string) => void;
}

export interface StartAssessmentParams {
  transcript: string;
  clientName: string;
  generateReport?: boolean;
  threadId?: string;
}

/**
 * Start a WAFR assessment via SSE streaming.
 *
 * POST /api/wafr/run returns a text/event-stream response.
 * Each event is `data: {...json...}\n\n`.
 */
export function startAssessment(
  params: StartAssessmentParams,
  callbacks: SSECallbacks,
): { abort: () => void } {
  const controller = new AbortController();

  const url = `${BACKEND_URL}/api/wafr/run`;
  const body = JSON.stringify({
    transcript: params.transcript,
    client_name: params.clientName,
    generate_report: params.generateReport ?? true,
    thread_id: params.threadId,
  });

  // Use fetch for SSE since we need POST (EventSource only supports GET)
  (async () => {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        signal: controller.signal,
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => '');
        callbacks.onRunError?.(`HTTP ${response.status}: ${errorText || response.statusText}`);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        callbacks.onRunError?.('No response body');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events from buffer
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith(':')) continue; // Skip empty lines and comments

          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6);
            try {
              const event = JSON.parse(jsonStr);
              handleSSEEvent(event, callbacks);
            } catch {
              // Not valid JSON, might be partial — skip
            }
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name === 'AbortError') return;
      callbacks.onRunError?.(err instanceof Error ? err.message : 'SSE connection failed');
    }
  })();

  return {
    abort: () => controller.abort(),
  };
}

function handleSSEEvent(
  event: Record<string, unknown>,
  callbacks: SSECallbacks,
): void {
  const type = event.type as string;

  switch (type) {
    case 'RUN_STARTED':
      callbacks.onRunStarted?.(
        event.thread_id as string || '',
        event.run_id as string || '',
      );
      break;

    case 'STEP_STARTED':
      callbacks.onStepStarted?.(event.step as string || event.name as string || '');
      break;

    case 'STEP_FINISHED':
      callbacks.onStepFinished?.(
        event.step as string || event.name as string || '',
        event.result as Record<string, unknown> | undefined,
      );
      break;

    case 'STATE_SNAPSHOT':
      callbacks.onStateSnapshot?.(event.snapshot as Record<string, unknown> || event.state as Record<string, unknown> || event as Record<string, unknown>);
      break;

    case 'STATE_DELTA':
      callbacks.onStateDelta?.(event.delta as Array<{ op: string; path: string; value: unknown }> || []);
      break;

    case 'TEXT_MESSAGE_CONTENT':
      callbacks.onTextMessage?.(event.text as string || event.content as string || '');
      break;

    case 'RUN_FINISHED':
      callbacks.onRunFinished?.(event.thread_id as string || '');
      break;

    case 'RUN_ERROR':
      callbacks.onRunError?.(
        event.message as string || event.error as string || 'Unknown error',
        event.code as string | undefined,
      );
      break;

    default:
      // Unknown event type — log for debugging
      if (typeof window !== 'undefined') {
        console.debug('[SSE] Unknown event type:', type, event);
      }
  }
}
```

**Step 2: Commit**

```bash
git add lib/sse-client.ts
git commit -m "feat: add SSE client for real-time assessment streaming"
```

---

## Task 4: Create backend API adapter

**Files:**
- Create: `lib/backend-api.ts`

**Step 1: Create the adapter with all endpoint mappers**

This is the key file. It calls each backend endpoint and transforms the response to match the frontend's existing TypeScript interfaces.

```typescript
// lib/backend-api.ts
import { apiGet, apiPost, apiDelete, BACKEND_URL } from './api';
import type {
  Session,
  Pillar,
  Insight,
  Question,
  Gap,
  ReviewItem,
  ReviewSummary,
  ExecutiveSummary,
  TrendData,
  SessionMetadata,
  BackendSession,
  BackendSessionsResponse,
} from './types';

// ─── Pillar descriptions (backend doesn't provide these) ───
const PILLAR_DESCRIPTIONS: Record<string, string> = {
  'Operational Excellence': 'Run and monitor systems to deliver business value',
  'Security': 'Protect information and systems',
  'Reliability': 'Recover from failures and meet demand',
  'Performance Efficiency': 'Use computing resources efficiently',
  'Cost Optimization': 'Avoid unnecessary costs',
  'Sustainability': 'Minimize environmental impacts',
};

// ─── Health ───
export async function checkHealth(): Promise<{ status: string; mode: string }> {
  const data = await apiGet<{ status: string; service: string; version: string }>('/health');
  return { status: data.status, mode: 'live' };
}

// ─── Sessions ───
export async function listSessions(): Promise<{
  sessions: Session[];
  metrics: { total: number; completed: number; inProgress: number; avgScore: number };
}> {
  const data = await apiGet<BackendSessionsResponse>('/api/wafr/sessions');

  const sessions: Session[] = data.sessions.map(mapBackendSession);

  return {
    sessions,
    metrics: {
      total: data.metrics.total_assessments,
      completed: data.metrics.completed,
      inProgress: data.metrics.in_progress,
      avgScore: data.metrics.avg_score,
    },
  };
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiDelete(`/api/wafr/session/${sessionId}`);
}

function mapBackendSession(bs: BackendSession): Session {
  return {
    id: bs.session_id,
    name: bs.assessment_name || `Assessment ${bs.session_id.slice(0, 8)}`,
    status: mapStatus(bs.status),
    created_at: bs.created_at || bs.updated_at || new Date().toISOString(),
  };
}

function mapStatus(backendStatus: string): Session['status'] {
  const s = backendStatus.toUpperCase();
  if (s === 'COMPLETED' || s === 'FINALIZED') return 'completed';
  if (s === 'IN_PROGRESS' || s === 'PROCESSING' || s === 'REVIEW' || s === 'SCORING' || s === 'REPORT') return 'in-progress';
  if (s === 'PENDING' || s === 'INITIALIZED') return 'pending';
  if (s === 'ERROR' || s === 'CANCELLED') return 'failed';
  return 'pending';
}

// ─── Session State ───
export async function getSessionState(sessionId: string): Promise<{
  sessionId: string;
  status: string;
  step: string;
  progress: number;
  state: Record<string, unknown>;
}> {
  const data = await apiGet<{
    session_id: string;
    state: Record<string, unknown>;
    timestamp: string;
  }>(`/api/wafr/session/${sessionId}/state`);

  const state = data.state || {};
  const pipeline = state.pipeline as Record<string, unknown> || {};
  const session = state.session as Record<string, unknown> || {};

  return {
    sessionId: data.session_id,
    status: (session.status as string) || 'unknown',
    step: (pipeline.current_step as string) || '',
    progress: (pipeline.progress_percentage as number) || 0,
    state,
  };
}

// ─── Pillars ───
export async function getPillars(sessionId: string): Promise<Pillar[]> {
  const data = await apiGet<{
    session_id: string;
    pillars: Record<string, {
      score?: number;
      coverage?: number;
      questions_answered?: number;
      average_confidence?: number;
    }>;
    count: number;
  }>(`/api/wafr/session/${sessionId}/pillars`);

  return Object.entries(data.pillars).map(([name, info]) => ({
    name,
    score: Math.round((info.score || info.coverage || 0) * (info.score && info.score <= 1 ? 100 : 1)),
    description: PILLAR_DESCRIPTIONS[name] || name,
    details: {
      strengths: [],
      improvements: [],
      metrics: {
        questions_answered: info.questions_answered || 0,
        average_confidence: info.average_confidence || 0,
        coverage: info.coverage || 0,
      },
    },
  }));
}

// ─── Insights ───
export async function getInsights(sessionId: string): Promise<Insight[]> {
  const data = await apiGet<{
    session_id: string;
    insights: Record<string, unknown>[];
    count: number;
  }>(`/api/wafr/session/${sessionId}/insights`);

  return (data.insights || []).map((raw, idx) => ({
    id: (raw.id as string) || `insight-${idx + 1}`,
    title: (raw.title as string) || (raw.insight as string) || 'Insight',
    severity: mapSeverity(raw.severity as string || raw.criticality as string),
    pillar: (raw.pillar as string) || 'General',
    category: (raw.category as string) || '',
    description: (raw.description as string) || (raw.detail as string) || '',
    recommendation: (raw.recommendation as string) || '',
    impact: (raw.impact as string) || '',
    effort: (raw.effort as string) || '',
    cost_impact: (raw.cost_impact as string) || '',
    affected_resources: (raw.affected_resources as string[]) || [],
    implementation_steps: (raw.implementation_steps as string[]) || [],
    references: (raw.references as string[]) || [],
  }));
}

function mapSeverity(s?: string): 'High' | 'Medium' | 'Low' {
  if (!s) return 'Medium';
  const upper = s.toUpperCase();
  if (upper === 'HIGH' || upper === 'CRITICAL') return 'High';
  if (upper === 'LOW') return 'Low';
  return 'Medium';
}

// ─── Questions ───
export async function getQuestions(sessionId: string): Promise<Question[]> {
  const data = await apiGet<{
    session_id: string;
    questions: Record<string, unknown>[];
    count: number;
  }>(`/api/wafr/session/${sessionId}/questions`);

  return (data.questions || []).map((raw, idx) => {
    const answer = (raw.answer as string) || null;
    const confidence = (raw.confidence as number) || 0;

    return {
      id: (raw.question_id as string) || `q-${idx + 1}`,
      pillar: (raw.pillar as string) || '',
      category: (raw.category as string) || '',
      text: (raw.question_text as string) || (raw.text as string) || '',
      status: answer ? 'Answered' as const : 'Pending' as const,
      answer,
      best_practice: (raw.best_practice as string) || '',
      notes: (raw.notes as string) || '',
      risk_level: confidenceToRisk(confidence),
      improvement_plan: (raw.improvement_plan as string) || null,
    };
  });
}

function confidenceToRisk(confidence: number): 'High' | 'Medium' | 'Low' {
  if (confidence >= 0.8) return 'Low';
  if (confidence >= 0.5) return 'Medium';
  return 'High';
}

// ─── Gaps ───
export async function getGaps(sessionId: string): Promise<Gap[]> {
  const data = await apiGet<{
    session_id: string;
    gaps: Record<string, unknown>[];
    count: number;
  }>(`/api/wafr/session/${sessionId}/gaps`);

  return (data.gaps || []).map((raw, idx) => ({
    id: (raw.id as string) || (raw.gap_id as string) || `gap-${idx + 1}`,
    title: (raw.title as string) || (raw.gap as string) || 'Gap',
    pillar: (raw.pillar as string) || '',
    risk_level: mapSeverity(raw.risk_level as string || raw.severity as string),
    category: (raw.category as string) || '',
    description: (raw.description as string) || '',
    mitigation: (raw.mitigation as string) || (raw.recommendation as string) || '',
    business_impact: (raw.business_impact as string) || '',
    current_state: (raw.current_state as string) || '',
    target_state: (raw.target_state as string) || '',
    timeline: (raw.timeline as string) || '',
    priority: (raw.priority as number) || idx + 1,
    affected_services: (raw.affected_services as string[]) || [],
    remediation_steps: (raw.remediation_steps as string[]) || [],
    estimated_cost: (raw.estimated_cost as string) || '',
  }));
}

// ─── Review Items ───
export async function getReviewItems(sessionId: string): Promise<{
  items: ReviewItem[];
  total: number;
  byPillar: Record<string, { total: number; pending: number; approved: number }>;
}> {
  const data = await apiGet<{
    items: Record<string, unknown>[];
    total: number;
    by_pillar: Record<string, { total: number; pending: number; approved: number }>;
  }>(`/api/wafr/review/${sessionId}/items`);

  const items: ReviewItem[] = (data.items || []).map((raw) => ({
    id: (raw.review_id as string) || (raw.id as string) || '',
    type: (raw.pillar as string) || 'Finding',
    content: (raw.question_text as string) || '',
    description: (raw.generated_answer as string) || '',
    status: mapReviewStatus(raw.status as string),
    pillar: (raw.pillar as string) || '',
    severity: mapCriticalityToSeverity(raw.criticality as string),
    affected_resources: [],
    recommendation: (raw.generated_answer as string) || '',
    estimated_effort: '',
    auto_remediable: false,
  }));

  return {
    items,
    total: data.total || items.length,
    byPillar: data.by_pillar || {},
  };
}

function mapReviewStatus(s: string): 'pending' | 'approved' | 'rejected' {
  const upper = (s || '').toUpperCase();
  if (upper === 'APPROVED') return 'approved';
  if (upper === 'REJECTED' || upper === 'MODIFIED') return 'rejected';
  return 'pending';
}

function mapCriticalityToSeverity(c?: string): 'High' | 'Medium' | 'Low' {
  if (!c) return 'Medium';
  const upper = c.toUpperCase();
  if (upper === 'HIGH' || upper === 'CRITICAL') return 'High';
  if (upper === 'LOW') return 'Low';
  return 'Medium';
}

// ─── Review Actions ───
export async function submitReviewDecision(
  sessionId: string,
  itemId: string,
  decision: 'approved' | 'rejected',
  comment: string,
): Promise<void> {
  await apiPost(`/api/wafr/review/${sessionId}/decision`, {
    review_id: itemId,
    decision: decision === 'approved' ? 'APPROVE' : 'REJECT',
    reviewer_id: 'frontend-user',
    feedback: comment || undefined,
  });
}

export async function batchApprove(
  sessionId: string,
  itemIds: string[],
): Promise<void> {
  await apiPost(`/api/wafr/review/${sessionId}/batch-approve`, {
    review_ids: itemIds,
    reviewer_id: 'frontend-user',
  });
}

export async function finalizeReview(sessionId: string): Promise<void> {
  await apiPost(`/api/wafr/review/${sessionId}/finalize`, {
    approver_id: 'frontend-user',
  });
}

export async function getReviewSummary(sessionId: string): Promise<ReviewSummary> {
  const data = await apiGet<{
    total_items: number;
    pending: number;
    approved: number;
    modified: number;
    rejected: number;
  }>(`/api/wafr/review/${sessionId}/summary`);

  return {
    total_items: data.total_items,
    approved_items: data.approved,
    rejected_items: data.rejected,
    pending_items: data.pending,
    high_risk_gaps: 0,
    medium_risk_gaps: 0,
    low_risk_gaps: 0,
    auto_remediable_count: 0,
    estimated_total_effort: '',
    potential_cost_savings: '',
    potential_cost_increase: '',
  };
}

// ─── Report Downloads ───
export function getReportDownloadUrl(sessionId: string): string {
  return `${BACKEND_URL}/api/wafr/session/${sessionId}/report/download`;
}

export function getAwsReportDownloadUrl(sessionId: string): string {
  return `${BACKEND_URL}/api/wafr/session/${sessionId}/report/aws/download`;
}

export function getResultsDownloadUrl(sessionId: string): string {
  return `${BACKEND_URL}/api/wafr/session/${sessionId}/results/download`;
}
```

**Step 2: Commit**

```bash
git add lib/backend-api.ts
git commit -m "feat: add backend API adapter with response transformation"
```

---

## Task 5: Remove mock API routes and mock data

**Files:**
- Delete: `app/api/` (entire directory — all 17 route files)
- Delete: `lib/mock-data.ts`
- Delete: `lib/session-store.ts`

**Step 1: Delete mock files**

```bash
rm -rf app/api/
rm lib/mock-data.ts
rm lib/session-store.ts
```

**Step 2: Commit**

```bash
git add -A
git commit -m "chore: remove mock API routes, mock data, and session store"
```

---

## Task 6: Update Dashboard page to use backend

**Files:**
- Modify: `app/page.tsx`

**Step 1: Update imports and data fetching**

In `app/page.tsx`, replace:
- `import { apiGet, apiDelete } from '@/lib/api'` → `import * as backend from '@/lib/backend-api'`
- `import { Session } from '@/lib/mock-data'` → `import type { Session } from '@/lib/types'`
- Health check: `apiGet('/api/health')` → `backend.checkHealth()`
- Sessions: `apiGet('/api/wafr/sessions')` → `backend.listSessions()`
- Delete: `apiDelete(\`/api/wafr/session/${id}\`)` → `backend.deleteSession(id)`
- Use the `metrics` from `listSessions()` response for stat cards instead of computing from sessions array

Key changes to the data fetching:
```typescript
// Old
const healthData = await apiGet<{ status: string }>('/api/health');
const sessionsData = await apiGet<{ sessions: Session[] }>('/api/wafr/sessions');

// New
const healthData = await backend.checkHealth();
const { sessions, metrics } = await backend.listSessions();
```

Use `metrics.total`, `metrics.completed`, `metrics.inProgress`, `metrics.avgScore` for the stat cards.

**Step 2: Verify by running dev server**

```bash
npm run dev
```

Open http://localhost:3000 — should show sessions from backend (or empty list if no assessments run yet).

**Step 3: Commit**

```bash
git add app/page.tsx
git commit -m "feat: connect Dashboard to backend API"
```

---

## Task 7: Update New Assessment page for SSE

**Files:**
- Modify: `app/new-assessment/page.tsx`

**Step 1: Update form submission to use SSE**

Replace the current `apiPost('/api/wafr/run', ...)` with the SSE client.

Key changes:
```typescript
import { startAssessment } from '@/lib/sse-client';

// In handleSubmit:
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
```

Store the `abort` function in a ref so it can be called on unmount.

**Step 2: Commit**

```bash
git add app/new-assessment/page.tsx
git commit -m "feat: connect New Assessment to backend via SSE"
```

---

## Task 8: Update Live Progress page for SSE events

**Files:**
- Modify: `app/progress/[sessionId]/page.tsx`

**Step 1: Replace polling with SSE state polling**

The Live Progress page currently simulates progress. Replace with:
1. Poll `/api/wafr/session/{sessionId}/state` every 3 seconds
2. Map the backend state to the progress UI (step name, percentage, status)
3. When status becomes `finalized` or `completed`, navigate to results

Key changes:
```typescript
import * as backend from '@/lib/backend-api';

// In useEffect:
const interval = setInterval(async () => {
  try {
    const stateData = await backend.getSessionState(sessionId);
    setCurrentPhase(mapStepToPhase(stateData.step));
    setProgress(stateData.progress);

    if (stateData.status === 'finalized' || stateData.status === 'completed') {
      clearInterval(interval);
      router.push(`/results/${sessionId}`);
    }
  } catch {
    // Session may not exist yet, keep polling
  }
}, 3000);
```

Map backend pipeline steps to the 6-phase stepper:
```typescript
function mapStepToPhase(step: string): number {
  const stepMap: Record<string, number> = {
    'understanding': 0,
    'answer_synthesis': 1,
    'confidence': 2,
    'scoring': 3,
    'gap_detection': 4,
    'report': 5,
  };
  return stepMap[step] ?? 0;
}
```

**Step 2: Commit**

```bash
git add app/progress/[sessionId]/page.tsx
git commit -m "feat: connect Live Progress to backend state polling"
```

---

## Task 9: Update Results page to use backend

**Files:**
- Modify: `app/results/[sessionId]/page.tsx`

**Step 1: Update data fetching**

Replace the 4 parallel mock API calls with backend adapter calls:

```typescript
import * as backend from '@/lib/backend-api';
import type { Pillar, Insight, Question, Gap } from '@/lib/types';

// In useEffect:
const [pillarsRes, insightsRes, questionsRes, gapsRes] = await Promise.all([
  backend.getPillars(sessionId),
  backend.getInsights(sessionId),
  backend.getQuestions(sessionId),
  backend.getGaps(sessionId),
]);

setPillars(pillarsRes);
setInsights(insightsRes);
setQuestions(questionsRes);
setGaps(gapsRes);
```

Remove the mock data imports and fallbacks.

**Step 2: Commit**

```bash
git add app/results/[sessionId]/page.tsx
git commit -m "feat: connect Results page to backend API"
```

---

## Task 10: Update Review page to use backend

**Files:**
- Modify: `app/review/[sessionId]/page.tsx`
- Modify: `components/review-item.tsx` (update the `ReviewItemData` type if needed)

**Step 1: Update data fetching and actions**

```typescript
import * as backend from '@/lib/backend-api';

// Fetch items:
const data = await backend.getReviewItems(sessionId);
setItems(data.items);

// Approve:
await backend.submitReviewDecision(sessionId, itemId, 'approved', comment);

// Reject:
await backend.submitReviewDecision(sessionId, itemId, 'rejected', comment);

// Batch approve:
const pendingIds = items.filter(i => i.status === 'pending').map(i => i.id);
await backend.batchApprove(sessionId, pendingIds);

// Finalize:
await backend.finalizeReview(sessionId);
```

**Step 2: Update review-item.tsx imports**

Change `import type { ReviewItem } from '@/lib/mock-data'` to `import type { ReviewItem } from '@/lib/types'`.

**Step 3: Commit**

```bash
git add app/review/[sessionId]/page.tsx components/review-item.tsx
git commit -m "feat: connect Review page to backend API"
```

---

## Task 11: Update Reports page to use backend

**Files:**
- Modify: `app/reports/[sessionId]/page.tsx`

**Step 1: Update download handlers**

Replace mock download logic with real backend URLs:

```typescript
import * as backend from '@/lib/backend-api';

// PDF download:
const handleDownloadPdf = async () => {
  const url = backend.getReportDownloadUrl(sessionId);
  window.open(url, '_blank');
};

// JSON download:
const handleDownloadJson = async () => {
  const url = backend.getResultsDownloadUrl(sessionId);
  const response = await fetch(url);
  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = blobUrl;
  link.download = `wafr_results_${sessionId}.json`;
  link.click();
  URL.revokeObjectURL(blobUrl);
};

// AWS report download:
const handleDownloadAwsReport = async () => {
  const url = backend.getAwsReportDownloadUrl(sessionId);
  window.open(url, '_blank');
};
```

**Step 2: Update data fetching for report content**

The report page also fetches pillars, insights, gaps for display. Update to use backend adapter:

```typescript
const [pillarsRes, insightsRes, gapsRes] = await Promise.all([
  backend.getPillars(sessionId),
  backend.getInsights(sessionId),
  backend.getGaps(sessionId),
]);
```

**Step 3: Commit**

```bash
git add app/reports/[sessionId]/page.tsx
git commit -m "feat: connect Reports page to backend API with real downloads"
```

---

## Task 12: Update all remaining import paths

**Files:**
- Modify: All files that import from `@/lib/mock-data`

**Step 1: Find and replace imports**

Search all files for `from '@/lib/mock-data'` and change to `from '@/lib/types'`:

Files that likely need updating:
- `components/pillar-card.tsx`
- `components/insight-card.tsx`
- `components/gap-card.tsx`
- `components/review-item.tsx`
- `components/stat-card.tsx`

**Step 2: Verify TypeScript compiles**

```bash
cd /home/naveensynlex/Downloads/mansi-project/aws-frontend && npx tsc --noEmit
```

Expected: Zero errors.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: update all imports from mock-data to types"
```

---

## Task 13: Full build verification and test

**Step 1: Run build**

```bash
cd /home/naveensynlex/Downloads/mansi-project/aws-frontend && npm run build
```

Expected: Successful build with all pages compiling.

**Step 2: Start both services and test**

Terminal 1 (backend — should already be running):
```bash
cd /home/naveensynlex/Downloads/mansi-project/Wafragents/wafr-agents
python3 -m uvicorn wafr.ag_ui.server:app --reload --port 8000
```

Terminal 2 (frontend):
```bash
cd /home/naveensynlex/Downloads/mansi-project/aws-frontend && npm run dev
```

**Step 3: Test each page**

1. http://localhost:3000 — Dashboard loads, health badge shows "System Healthy", sessions list from backend
2. Click "New Assessment" — Form renders
3. Submit with test data — SSE stream starts, redirects to progress page
4. Progress page — Shows real backend step progress
5. Results page — Shows real pillar scores, insights, questions, gaps
6. Review page — Shows real review items, approve/reject works
7. Reports page — Downloads serve real files from backend

**Step 4: Final commit**

```bash
git add -A && git commit -m "feat: complete backend integration — all pages connected to FastAPI"
```

---

## Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Extract types to standalone file | `lib/types.ts` |
| 2 | Update API helpers for backend URL | `lib/api.ts`, `.env.local` |
| 3 | Create SSE client | `lib/sse-client.ts` |
| 4 | Create backend API adapter | `lib/backend-api.ts` |
| 5 | Remove mock files | Delete `app/api/`, `lib/mock-data.ts`, `lib/session-store.ts` |
| 6 | Connect Dashboard | `app/page.tsx` |
| 7 | Connect New Assessment (SSE) | `app/new-assessment/page.tsx` |
| 8 | Connect Live Progress | `app/progress/[sessionId]/page.tsx` |
| 9 | Connect Results | `app/results/[sessionId]/page.tsx` |
| 10 | Connect Review | `app/review/[sessionId]/page.tsx` |
| 11 | Connect Reports | `app/reports/[sessionId]/page.tsx` |
| 12 | Update import paths | All component files |
| 13 | Full build + test | All files |
