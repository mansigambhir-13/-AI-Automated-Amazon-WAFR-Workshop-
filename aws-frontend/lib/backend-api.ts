import { apiGet, apiPost, authHeaders, BACKEND_URL } from './api';
import { getCurrentUserInfo } from './auth';
import type {
  Session,
  Pillar,
  Insight,
  Question,
  Gap,
  ReviewItem,
  ReviewSummary,
  BackendSession,
  BackendSessionsResponse,
} from './types';
import { getAllSessions, putManySessions, deleteSessionFromDB } from './session-db';

// --- Pillar descriptions (backend doesn't provide these) ---
const PILLAR_DESCRIPTIONS: Record<string, string> = {
  'Operational Excellence': 'Run and monitor systems to deliver business value',
  'Security': 'Protect information and systems',
  'Reliability': 'Recover from failures and meet demand',
  'Performance Efficiency': 'Use computing resources efficiently',
  'Cost Optimization': 'Avoid unnecessary costs',
  'Sustainability': 'Minimize environmental impacts',
};

// --- Health ---
export async function checkHealth(): Promise<{ status: string; mode: string }> {
  const data = await apiGet<{ status: string; service: string; version: string }>('/health');
  return { status: data.status, mode: 'live' };
}

// --- Sessions (IndexedDB-backed) ---
export async function listSessions(): Promise<{
  sessions: Session[];
  metrics: { total: number; completed: number; inProgress: number; avgScore: number };
}> {
  // 1. Try to fetch fresh sessions from backend and upsert into IndexedDB
  let backendAvgScore: number | null = null;
  try {
    const data = await apiGet<BackendSessionsResponse>('/api/wafr/sessions');
    const backendSessions: Session[] = data.sessions.map(mapBackendSession);
    await putManySessions(backendSessions);

    // Capture avg_score from backend metrics
    if (data.metrics?.avg_score != null) {
      backendAvgScore = data.metrics.avg_score;
    }
  } catch (error) {
    console.warn('Backend fetch failed, falling back to IndexedDB:', error);
  }

  // 2. Read all sessions from IndexedDB (excludes previously deleted ones)
  const sessions = await getAllSessions();

  // 3. Compute metrics from IndexedDB data
  const completed = sessions.filter((s) => s.status === 'completed').length;
  const inProgress = sessions.filter((s) => s.status === 'in-progress' || s.status === 'pending').length;

  // Use backend avg_score when available; otherwise compute from cached sessions
  let avgScore = backendAvgScore ?? 0;
  if (avgScore === 0 && sessions.length > 0) {
    // Fallback: compute from sessions that have been fetched with overall_score
    // (scores are not stored in IndexedDB, so this only works when backend is available)
  }

  return {
    sessions,
    metrics: {
      total: sessions.length,
      completed,
      inProgress,
      avgScore,
    },
  };
}

export async function deleteSession(sessionId: string): Promise<void> {
  await deleteSessionFromDB(sessionId);
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

// --- Session State ---
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

// --- Pillars ---
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

  return Object.entries(data.pillars).map(([name, info]) => {
    const raw = info as Record<string, unknown>;
    return {
      name,
      score: Math.round(
        (info.score != null ? info.score : info.coverage ?? 0) *
        (info.score != null && info.score <= 1 ? 100 : 1)
      ),
      // Use backend description when available; fall back to hardcoded
      description: (raw.description as string) || PILLAR_DESCRIPTIONS[name] || name,
      details: {
        // Use backend strengths/improvements when available; fall back to empty arrays
        strengths: Array.isArray(raw.strengths) ? (raw.strengths as string[]) : [],
        improvements: Array.isArray(raw.improvements) ? (raw.improvements as string[]) : [],
        metrics: {
          questions_answered: info.questions_answered || 0,
          average_confidence: info.average_confidence || 0,
          coverage: info.coverage || 0,
        },
      },
    };
  });
}

// --- Insights ---
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

// --- Questions ---
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

// --- Gaps ---

/**
 * Sanitize a field value that may contain raw Python dict/list repr strings
 * from the backend. Extracts the 'text' fields into clean readable text.
 */
function cleanGapField(value: unknown): string {
  if (value == null) return '';

  // If it's an array of objects, extract text from each
  if (Array.isArray(value)) {
    const texts = value
      .map((item) => {
        if (typeof item === 'string') return item;
        if (typeof item === 'object' && item !== null) {
          return (item as Record<string, unknown>).text as string || JSON.stringify(item);
        }
        return String(item);
      })
      .filter(Boolean);
    return texts.join('\n');
  }

  // If it's an object, try to extract its text
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    if (obj.text) return String(obj.text);
    return JSON.stringify(value);
  }

  const str = String(value);

  // Detect Python-serialized dict strings: {'id': '...', 'text': '...', ...}
  if (str.includes("'id':") && str.includes("'text':")) {
    const textMatches = [...str.matchAll(/'text':\s*'([^']+)'/g)];
    if (textMatches.length > 0) {
      return textMatches.map((m) => m[1]).join('. ');
    }
  }

  // Detect Python-serialized strings with double quotes
  if (str.includes('"id":') && str.includes('"text":')) {
    const textMatches = [...str.matchAll(/"text":\s*"([^"]+)"/g)];
    if (textMatches.length > 0) {
      return textMatches.map((m) => m[1]).join('. ');
    }
  }

  // Strip leading labels like "Best practices: " before the dict
  const labelStripped = str.replace(/^[A-Za-z\s]+:\s*(?=[\[{(])/, '');
  if (labelStripped !== str && labelStripped.includes("'text':")) {
    const textMatches = [...labelStripped.matchAll(/'text':\s*'([^']+)'/g)];
    if (textMatches.length > 0) {
      return textMatches.map((m) => m[1]).join('. ');
    }
  }

  return str;
}

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
    description: cleanGapField(raw.description),
    mitigation: cleanGapField(raw.mitigation) || cleanGapField(raw.recommendation),
    business_impact: cleanGapField(raw.business_impact),
    current_state: cleanGapField(raw.current_state),
    target_state: cleanGapField(raw.target_state),
    timeline: (raw.timeline as string) || '',
    priority: (raw.priority as number) || idx + 1,
    affected_services: (raw.affected_services as string[]) || [],
    remediation_steps: Array.isArray(raw.remediation_steps)
      ? (raw.remediation_steps as unknown[]).map((s) => cleanGapField(s))
      : [],
    estimated_cost: (raw.estimated_cost as string) || '',
  }));
}

// --- Review Items ---
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

// --- Review Actions ---
export async function submitReviewDecision(
  sessionId: string,
  itemId: string,
  decision: 'approved' | 'rejected',
  comment: string,
): Promise<void> {
  const user = await getCurrentUserInfo();
  await apiPost(`/api/wafr/review/${sessionId}/decision`, {
    review_id: itemId,
    decision: decision === 'approved' ? 'APPROVE' : 'REJECT',
    reviewer_id: user.username,
    feedback: comment || undefined,
  });
}

export async function batchApprove(
  sessionId: string,
  itemIds: string[],
): Promise<void> {
  const user = await getCurrentUserInfo();
  await apiPost(`/api/wafr/review/${sessionId}/batch-approve`, {
    review_ids: itemIds,
    reviewer_id: user.username,
  });
}

export async function finalizeReview(sessionId: string): Promise<void> {
  const user = await getCurrentUserInfo();
  await apiPost(`/api/wafr/review/${sessionId}/finalize`, {
    approver_id: user.username,
  });
}

export async function getReviewSummary(sessionId: string): Promise<ReviewSummary> {
  const data = await apiGet<Record<string, unknown>>(`/api/wafr/review/${sessionId}/summary`);

  return {
    total_items: (data.total_items as number) ?? 0,
    approved_items: (data.approved as number) ?? 0,
    rejected_items: (data.rejected as number) ?? 0,
    pending_items: (data.pending as number) ?? 0,
    // Pass through backend risk breakdowns when available
    high_risk_gaps: (data.high_risk_gaps as number) ?? 0, // TODO: backend does not yet provide this field
    medium_risk_gaps: (data.medium_risk_gaps as number) ?? 0, // TODO: backend does not yet provide this field
    low_risk_gaps: (data.low_risk_gaps as number) ?? 0, // TODO: backend does not yet provide this field
    auto_remediable_count: (data.auto_remediable_count as number) ?? 0, // TODO: backend does not yet provide this field
    estimated_total_effort: (data.estimated_total_effort as string) ?? '', // TODO: backend does not yet provide this field
    potential_cost_savings: (data.potential_cost_savings as string) ?? '', // TODO: backend does not yet provide this field
    potential_cost_increase: (data.potential_cost_increase as string) ?? '', // TODO: backend does not yet provide this field
  };
}

// --- Report Downloads ---

/**
 * @deprecated Use downloadReport() instead — returns an auth-aware fetch that includes the Bearer token.
 * Direct URL links fail because the browser cannot attach Authorization headers to navigation requests.
 */
export function getReportDownloadUrl(sessionId: string): string {
  return `${BACKEND_URL}/api/wafr/session/${sessionId}/report/download`;
}

/**
 * @deprecated Use downloadAwsReport() instead — returns an auth-aware fetch that includes the Bearer token.
 * Direct URL links fail because the browser cannot attach Authorization headers to navigation requests.
 */
export function getAwsReportDownloadUrl(sessionId: string): string {
  return `${BACKEND_URL}/api/wafr/session/${sessionId}/report/aws/download`;
}

/**
 * @deprecated Use downloadResults() instead — returns an auth-aware fetch that includes the Bearer token.
 * Direct URL links fail because the browser cannot attach Authorization headers to navigation requests.
 */
export function getResultsDownloadUrl(sessionId: string): string {
  return `${BACKEND_URL}/api/wafr/session/${sessionId}/results/download`;
}

/**
 * Download the WAFR PDF report for a session using an auth-aware fetch.
 * Triggers a browser download via a temporary object URL.
 */
export async function downloadReport(sessionId: string): Promise<void> {
  const headers = await authHeaders();
  const url = `${BACKEND_URL}/api/wafr/session/${sessionId}/report/download`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `wafr-report-${sessionId}.pdf`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/**
 * Download the AWS-format WAFR report for a session using an auth-aware fetch.
 * Triggers a browser download via a temporary object URL.
 */
export async function downloadAwsReport(sessionId: string): Promise<void> {
  const headers = await authHeaders();
  const url = `${BACKEND_URL}/api/wafr/session/${sessionId}/report/aws/download`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `wafr-aws-report-${sessionId}.pdf`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/**
 * Download the results export for a session using an auth-aware fetch.
 * Triggers a browser download via a temporary object URL.
 */
export async function downloadResults(sessionId: string): Promise<void> {
  const headers = await authHeaders();
  const url = `${BACKEND_URL}/api/wafr/session/${sessionId}/results/download`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `wafr-results-${sessionId}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}
