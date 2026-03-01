# WAFR Next.js Frontend — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the WAFR Assessment frontend using Next.js 16 + shadcn/ui + Tailwind CSS with full mock data API routes.

**Architecture:** Next.js App Router with client-side pages (interactive), API routes serving mock data from lib/mock-data.ts, AWS-branded theme via Tailwind custom colors + shadcn theming with next-themes for dark/light toggle.

**Tech Stack:** Next.js 16, React 19, shadcn/ui, Tailwind CSS, Recharts, next-themes, Lucide icons

**Reference:** `/home/naveensynlex/Downloads/mansi-project/Wafr frontend/WAFR-ASSESMENT/`

---

## Task 1: Scaffold Next.js project and install dependencies

**Files:**
- Create: `package.json`, `next.config.ts`, `tsconfig.json`, `tailwind.config.ts`, `app/layout.tsx`, `app/globals.css`

**Step 1: Create Next.js app**

```bash
cd /home/naveensynlex/Downloads/mansi-project/aws-frontend
npx create-next-app@latest . --typescript --tailwind --eslint --app --src=no --import-alias="@/*" --turbopack
```

Accept defaults. This scaffolds the project with App Router + Tailwind.

**Step 2: Install additional dependencies**

```bash
npm install recharts next-themes lucide-react
```

**Step 3: Initialize shadcn/ui**

```bash
npx shadcn@latest init
```

Choose: New York style, Zinc base color, CSS variables: yes.

**Step 4: Add shadcn components**

```bash
npx shadcn@latest add card button badge input textarea tabs accordion table progress alert separator tooltip avatar select sheet dialog
```

**Step 5: Commit**

```bash
git init && git add -A && git commit -m "chore: scaffold Next.js 16 + shadcn + Tailwind project"
```

---

## Task 2: Configure AWS theme and global styles

**Files:**
- Modify: `tailwind.config.ts`
- Modify: `app/globals.css`
- Modify: `app/layout.tsx`

**Step 1: Update tailwind.config.ts with AWS colors**

Add to `theme.extend.colors`:
```typescript
aws: {
  squid: '#232F3E',
  orange: '#FF9900',
  smile: '#FFB84D',
  ink: '#16191F',
  fog: '#F2F3F3',
  stone: '#687078',
  success: '#1D8102',
  error: '#D13212',
  info: '#0972D3',
}
```

**Step 2: Update globals.css**

Add CSS variables for light/dark themes matching AWS palette. Set `--primary: 232F3E` for light, `--primary: FF9900` for dark mode.

**Step 3: Update root layout**

Configure `app/layout.tsx` with:
- next-themes ThemeProvider (attribute="class", defaultTheme="light")
- Font: Inter (from next/font/google)
- Metadata: title "AWS Well-Architected Tool", description

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: configure AWS theme colors and dark mode"
```

---

## Task 3: Create mock data and session store

**Files:**
- Create: `lib/mock-data.ts`
- Create: `lib/session-store.ts`
- Create: `lib/api.ts`

**Step 1: Create lib/mock-data.ts**

Port all mock data from `/home/naveensynlex/Downloads/mansi-project/Wafr frontend/WAFR-ASSESMENT/server/mock-data.ts`:
- `mockPillars` (6 pillars with scores, details)
- `mockInsights` (6 insights with severity, recommendations)
- `mockQuestions` (15 questions)
- `mockGaps` (5 gaps with risk levels)
- `mockReviewItems` (6 review items)
- `mockReviewSummary`
- `mockExecutiveSummary`
- `mockTrendData`
- `getSessionMetadata(sessionId)` function

Add TypeScript interfaces for all data shapes.

**Step 2: Create lib/session-store.ts**

In-memory session store using module-level Map:
```typescript
interface Session { id: string; name: string; status: string; created_at: string; }
const sessions = new Map<string, Session>();
// Pre-populate with 2 demo sessions
export function getSessions(): Session[]
export function addSession(session: Session): void
export function deleteSession(id: string): boolean
export function getSession(id: string): Session | undefined
export function generateSessionId(): string
```

**Step 3: Create lib/api.ts**

Client-side fetch helpers:
```typescript
const API_BASE = '';
export async function apiGet<T>(path: string): Promise<T>
export async function apiPost<T>(path: string, body: any): Promise<T>
export async function apiDelete<T>(path: string): Promise<T>
```

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: add mock data, session store, and API helpers"
```

---

## Task 4: Create all API routes

**Files:**
- Create: `app/api/health/route.ts`
- Create: `app/api/wafr/run/route.ts`
- Create: `app/api/wafr/sessions/route.ts`
- Create: `app/api/wafr/session/[id]/route.ts`
- Create: `app/api/wafr/session/[id]/state/route.ts`
- Create: `app/api/wafr/session/[id]/pillars/route.ts`
- Create: `app/api/wafr/session/[id]/insights/route.ts`
- Create: `app/api/wafr/session/[id]/questions/route.ts`
- Create: `app/api/wafr/session/[id]/gaps/route.ts`
- Create: `app/api/wafr/session/[id]/report/status/route.ts`
- Create: `app/api/wafr/session/[id]/report/download/route.ts`
- Create: `app/api/wafr/session/[id]/report/aws/download/route.ts`
- Create: `app/api/wafr/review/[id]/items/route.ts`
- Create: `app/api/wafr/review/[id]/decision/route.ts`
- Create: `app/api/wafr/review/[id]/batch-approve/route.ts`
- Create: `app/api/wafr/review/[id]/finalize/route.ts`
- Create: `app/api/wafr/review/[id]/summary/route.ts`

**Step 1: Create health endpoint**

```typescript
// app/api/health/route.ts
export async function GET() {
  return Response.json({ status: 'healthy', mode: 'mock' });
}
```

**Step 2: Create WAFR core routes**

Each route imports from `lib/mock-data.ts` and `lib/session-store.ts`:
- `POST /api/wafr/run` — Creates session, returns `{ session_id, status }`, auto-completes after 5s via setTimeout
- `GET /api/wafr/sessions` — Returns all sessions from store
- `DELETE /api/wafr/session/[id]` — Removes session from store
- `GET /api/wafr/session/[id]/state` — Returns session metadata + executive summary + trend data
- `GET /api/wafr/session/[id]/pillars` — Returns `{ pillars: mockPillars }`
- `GET /api/wafr/session/[id]/insights` — Returns `{ insights: mockInsights }`
- `GET /api/wafr/session/[id]/questions` — Returns `{ questions: mockQuestions }`
- `GET /api/wafr/session/[id]/gaps` — Returns `{ gaps: mockGaps }`

**Step 3: Create review routes**

- `GET /api/wafr/review/[id]/items` — Returns `{ items: mockReviewItems }`
- `POST /api/wafr/review/[id]/decision` — Returns `{ success: true }`
- `POST /api/wafr/review/[id]/batch-approve` — Returns `{ success: true }`
- `POST /api/wafr/review/[id]/finalize` — Returns `{ success: true }`
- `GET /api/wafr/review/[id]/summary` — Returns mockReviewSummary

**Step 4: Create report routes**

- `GET /api/wafr/session/[id]/report/status` — Returns `{ status: 'ready' }`
- `GET /api/wafr/session/[id]/report/download` — Returns mock HTML report string
- `GET /api/wafr/session/[id]/report/aws/download` — Returns mock HTML report string

**Step 5: Verify all routes**

```bash
npm run dev &
curl http://localhost:3000/api/health
curl http://localhost:3000/api/wafr/sessions
```

**Step 6: Commit**

```bash
git add -A && git commit -m "feat: add all mock API routes"
```

---

## Task 5: Build Header component and root layout

**Files:**
- Create: `components/header.tsx`
- Modify: `app/layout.tsx`

**Step 1: Build Header component**

AWS-branded header with:
- Left: AWS logo icon + "AWS Well-Architected Tool" title + "Framework Review & Assessment" subtitle
- Right: Breadcrumb nav links (Dashboard, current page) + theme toggle button (Sun/Moon icons)
- Background: `bg-aws-squid` (#232F3E), orange accent border bottom
- Use shadcn Button for theme toggle, lucide-react Sun/Moon icons
- Use `next-themes` useTheme() hook

**Step 2: Update root layout**

Wire Header into layout above `{children}`. Add ThemeProvider wrapping.

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add AWS-branded header with dark mode toggle"
```

---

## Task 6: Build Dashboard page

**Files:**
- Create: `app/page.tsx`
- Create: `components/stat-card.tsx`

**Step 1: Create stat-card component**

Gradient background card showing a number + label. Props: `{ title, value, icon, gradient }`. Use Tailwind gradient classes.

**Step 2: Build Dashboard page**

Port from reference `Dashboard.tsx`. Use `"use client"` directive. Sections:
- Health status badge (shadcn Badge, green/red)
- 4 StatCards in a grid (Total, Completed, In Progress, Avg Score)
- Sessions table using shadcn Table (name, session ID, status chip, date, actions)
- Empty state with CTA button
- 3 info cards at bottom (Six Pillars, Best Practices, Continuous Improvement)
- Uses `apiGet` to fetch `/api/health` and `/api/wafr/sessions`
- "New Assessment" button navigates to `/new-assessment` via `useRouter()`

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add Dashboard page with session list and stats"
```

---

## Task 7: Build New Assessment page

**Files:**
- Create: `app/new-assessment/page.tsx`

**Step 1: Build New Assessment page**

Port from reference `NewAssessment.tsx`. Sections:
- Visual stepper (3 steps) — use custom div styling or shadcn Progress
- Form with shadcn Input (App Name), Textarea (Workload Description, 6 rows), Input (Environment), Input (Owner)
- Right sidebar: "What to Expect" card (6 pillar list) + "Duration" card
- Submit handler: POST `/api/wafr/run` with form data, navigate to `/progress/{session_id}`
- Loading state on submit button
- Error alert display

**Step 2: Commit**

```bash
git add -A && git commit -m "feat: add New Assessment form page"
```

---

## Task 8: Build Live Progress page

**Files:**
- Create: `app/progress/[sessionId]/page.tsx`

**Step 1: Build Live Progress page**

Port from reference `LiveProgress.tsx`. Sections:
- 6-phase stepper (Initialization, Analyzing, Evaluating, Generating Insights, Identifying Gaps, Completed) — custom step indicators
- Large circular progress display (percentage in center)
- Activity log — list of events with timestamps
- Right sidebar: Session info card + context + next steps
- Poll `/api/wafr/session/{id}/state` every 2 seconds using useEffect + setInterval
- Auto-navigate to `/results/{sessionId}` when status becomes "completed" (after ~10s in mock mode)

**Step 2: Commit**

```bash
git add -A && git commit -m "feat: add Live Progress page with polling"
```

---

## Task 9: Build Results page

**Files:**
- Create: `app/results/[sessionId]/page.tsx`
- Create: `components/pillar-card.tsx`
- Create: `components/insight-card.tsx`
- Create: `components/gap-card.tsx`

**Step 1: Create reusable components**

- `pillar-card.tsx` — Shows pillar name, score (big number), progress bar, description
- `insight-card.tsx` — Title, severity badge, pillar badge, description, recommendation. Expandable details.
- `gap-card.tsx` — Title, risk level badge, pillar badge, description, mitigation. Expandable.

**Step 2: Build Results page**

Port from reference `Results.tsx`. Sections:
- 4 summary cards at top (Overall Score, Total Insights, Gaps, Questions)
- shadcn Tabs with 4 tabs:
  1. **Pillars**: 6 PillarCards in 2-col grid + Recharts RadarChart + BarChart
  2. **Insights**: InsightCards list
  3. **Questions**: Table rows with status badges, answers, risk levels
  4. **Gaps**: GapCards list
- Navigation buttons to Review and Reports pages
- Fetches 4 endpoints in parallel: pillars, insights, questions, gaps

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add Results page with tabs, charts, and data cards"
```

---

## Task 10: Build Review page

**Files:**
- Create: `app/review/[sessionId]/page.tsx`
- Create: `components/review-item.tsx`

**Step 1: Create review-item component**

Card with:
- Type chip, pillar badge, severity badge
- Auto-remediable indicator
- Content title + description
- Expandable section: recommendation, effort, affected resources
- Comment textarea
- Approve (green) / Reject (red) buttons
- Status indicator after decision

**Step 2: Build Review page**

Port from reference `Review.tsx`. Sections:
- Progress bar showing review completion %
- 4 stat cards (Total, Pending, Approved, Rejected)
- Alert showing pending count
- List of ReviewItem components
- "Approve All" batch button
- "Finalize Review" button (enabled when all reviewed)
- Snackbar/toast for action feedback
- Local state management for review decisions (no real persistence needed)

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add Review page with approve/reject workflow"
```

---

## Task 11: Build Reports page

**Files:**
- Create: `app/reports/[sessionId]/page.tsx`

**Step 1: Build Reports page**

Port from reference `Reports.tsx`. This is the largest page. Sections:
- 3 download cards (PDF Report, JSON Results, AWS Official Report) using shadcn Card + Button
- Executive Summary: overview text, strengths list (green card), critical actions (red card), quick wins (amber card)
- Assessment Details: 2 cards (Workload Info + Assessment Scope) with key-value rows
- Review Summary: 6 stat cards
- Detailed Insights: shadcn Accordion per insight with nested impact/effort cards
- Identified Gaps: Accordion per gap with current state/target state/mitigation
- Pillar-by-Pillar: Accordion per pillar with strengths + improvements lists
- Investment & Timeline: cost table + benefits card + timeline cards
- Trend Analysis: Recharts LineChart (score history) + BarChart (benchmark comparison) + improvement velocity stats
- Footer with session ID and timestamp

Download handlers:
- PDF: fetch HTML from API, open in new window, trigger print
- JSON: fetch JSON, create blob, trigger download
- AWS: fetch from local API route (not hardcoded remote URL)

**Step 2: Commit**

```bash
git add -A && git commit -m "feat: add Reports page with charts, downloads, and full details"
```

---

## Task 12: Final polish and verification

**Files:**
- Review all pages for consistent styling

**Step 1: Test full flow**

```bash
npm run dev
```

1. Open http://localhost:3000 — Dashboard loads, health green, 2 demo sessions
2. Click "New Assessment" — Form renders, fill in, submit
3. Progress page — Shows polling, auto-redirects to results
4. Results page — 4 tabs work, charts render, data displays
5. Review page — Approve/reject items, batch approve, finalize
6. Reports page — All sections render, downloads work

**Step 2: Fix any styling inconsistencies**

Ensure AWS branding is consistent: orange accents, dark blue nav, proper dark mode.

**Step 3: Final commit**

```bash
git add -A && git commit -m "feat: complete WAFR Next.js frontend with all 6 pages"
```

---

## Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Scaffold + dependencies | package.json, shadcn init |
| 2 | AWS theme + globals | tailwind.config.ts, globals.css |
| 3 | Mock data + stores | lib/mock-data.ts, lib/session-store.ts |
| 4 | All API routes (17) | app/api/wafr/**/*.ts |
| 5 | Header + layout | components/header.tsx |
| 6 | Dashboard page | app/page.tsx |
| 7 | New Assessment page | app/new-assessment/page.tsx |
| 8 | Live Progress page | app/progress/[sessionId]/page.tsx |
| 9 | Results page + charts | app/results/[sessionId]/page.tsx |
| 10 | Review page + HITL | app/review/[sessionId]/page.tsx |
| 11 | Reports page + downloads | app/reports/[sessionId]/page.tsx |
| 12 | Final polish + test | All files |
