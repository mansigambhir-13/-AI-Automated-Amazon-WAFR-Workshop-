# WAFR Frontend ↔ Backend Integration — Design

## Overview

Connect the Next.js frontend (localhost:3000) to the FastAPI backend (localhost:8000) at `/home/naveensynlex/Downloads/mansi-project/Wafragents/wafr-agents`. Replace all mock data with real backend calls. Use SSE streaming for real-time assessment progress.

## Decisions

- **SSE streaming** for `/api/wafr/run` — frontend consumes the event stream directly
- **Direct to backend** — frontend calls `NEXT_PUBLIC_BACKEND_URL` (default: `http://localhost:8000`)
- **Backend-only** — remove all mock API routes, mock data, and session store
- **Adapter layer** — `lib/backend-api.ts` maps backend responses to existing frontend interfaces

## Architecture

```
Browser → Next.js (pages/components) → lib/backend-api.ts → FastAPI :8000
                                           ↕ transforms
                                     existing TS interfaces
```

### Files to Create
- `lib/backend-api.ts` — Adapter mapping backend responses to frontend interfaces
- `lib/sse-client.ts` — SSE client for consuming `/api/wafr/run` stream

### Files to Modify
- `lib/api.ts` — Prepend `NEXT_PUBLIC_BACKEND_URL`
- All 6 page files — Use backend-api adapter instead of relative API calls
- `app/new-assessment/page.tsx` — Construct transcript from form fields, use SSE
- `app/progress/[sessionId]/page.tsx` — SSE event subscription instead of polling
- `app/review/[sessionId]/page.tsx` — Different request format for decisions
- `app/reports/[sessionId]/page.tsx` — Real PDF/JSON download handling

### Files to Remove
- `app/api/**` — All 17 mock API routes
- `lib/mock-data.ts` — Mock data and interfaces (keep interfaces, move to `lib/types.ts`)
- `lib/session-store.ts` — In-memory session store

## Data Transformations

### Sessions
Backend: `{ session_id, assessment_name, status: "COMPLETED", overall_score, created_at }`
Frontend: `{ id, name, status: "completed", created_at }`

### Pillars
Backend: `{ pillars: { "Security": { score, coverage, questions_answered, average_confidence } } }`
Frontend: `Pillar[]` array with `{ name, score, description, details: { strengths, improvements, metrics } }`
Note: Backend doesn't have strengths/improvements/description per pillar — derive or use defaults.

### Insights
Backend: `{ insights: [...] }` from `understanding.insights` step
Frontend: `Insight[]` — map available fields, fill missing ones with defaults

### Questions
Backend: `{ questions: [{ question_id, question_text, pillar, answer, confidence, source }] }`
Frontend: `Question[]` with `{ id, text, pillar, status, answer, risk_level, best_practice }`
Derive `status` from answer presence, `risk_level` from confidence.

### Gaps
Backend: `{ gaps: [...] }` from `gap_detection.gaps` step
Frontend: `Gap[]` — map available fields

### Review Items
Backend: `{ items: [{ review_id, question_text, generated_answer, confidence_score, pillar, criticality, status }] }`
Frontend: `ReviewItem` adapted to show question/answer review cards

### Review Decision
Backend expects: `{ review_id, decision: "APPROVE"/"MODIFY"/"REJECT", reviewer_id, modified_answer?, feedback? }`
Frontend sends: Map from current approve/reject to backend format

## SSE Streaming

### Event Types from Backend
- `RUN_STARTED` — Assessment begins
- `STEP_STARTED` / `STEP_FINISHED` — Pipeline steps
- `STATE_SNAPSHOT` — Full state snapshot
- `STATE_DELTA` — Incremental JSON Patch updates
- `TEXT_MESSAGE_CONTENT` — Progress messages
- `RUN_FINISHED` / `RUN_ERROR` — Completion

### SSE Client (`lib/sse-client.ts`)
```typescript
interface SSECallbacks {
  onProgress: (step: string, percentage: number, message: string) => void;
  onStepChange: (step: string, status: 'started' | 'finished') => void;
  onStateSnapshot: (state: any) => void;
  onComplete: (sessionId: string) => void;
  onError: (error: string) => void;
}

function startAssessment(params: {
  transcript: string;
  clientName: string;
  generateReport: boolean;
}, callbacks: SSECallbacks): { abort: () => void }
```

### New Assessment Flow
1. User fills form (Application Name, Description, Environment, Owner)
2. Frontend constructs `transcript` string from form fields
3. `startAssessment()` POSTs to backend `/api/wafr/run` with SSE
4. Navigate to Live Progress page with session ID from first event
5. Progress page subscribes to SSE callbacks for real-time updates
6. On `RUN_FINISHED`, navigate to Results page

## Backend Endpoints Used

| Endpoint | Method | Frontend Usage |
|---|---|---|
| `/health` | GET | Dashboard health badge |
| `/api/wafr/run` | POST (SSE) | Start assessment |
| `/api/wafr/sessions` | GET | Dashboard session list |
| `/api/wafr/session/{id}` | DELETE | Delete session |
| `/api/wafr/session/{id}/state` | GET | Session state |
| `/api/wafr/session/{id}/pillars` | GET | Results Pillars tab |
| `/api/wafr/session/{id}/insights` | GET | Results Insights tab |
| `/api/wafr/session/{id}/questions` | GET | Results Questions tab |
| `/api/wafr/session/{id}/gaps` | GET | Results Gaps tab |
| `/api/wafr/review/{id}/items` | GET | Review page items |
| `/api/wafr/review/{id}/decision` | POST | Approve/reject |
| `/api/wafr/review/{id}/batch-approve` | POST | Batch approve |
| `/api/wafr/review/{id}/finalize` | POST | Finalize review |
| `/api/wafr/review/{id}/summary` | GET | Review summary |
| `/api/wafr/session/{id}/report/download` | GET | PDF download |
| `/api/wafr/session/{id}/report/aws/download` | GET | AWS report download |
| `/api/wafr/session/{id}/results/download` | GET | JSON download |

## Environment Variables

```
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```
