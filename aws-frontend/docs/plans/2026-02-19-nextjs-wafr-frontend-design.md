# WAFR Frontend Rebuild — Next.js 16 + shadcn + Tailwind

## Overview

Rebuild the existing WAFR (AWS Well-Architected Framework Review) frontend from Vite+React+MUI to Next.js 16 App Router + shadcn/ui + Tailwind CSS. The new app lives at `/home/naveensynlex/Downloads/mansi-project/aws-frontend`.

## Reference Implementation

Source: `/home/naveensynlex/Downloads/mansi-project/Wafr frontend/WAFR-ASSESMENT`
- 6 pages: Dashboard, New Assessment, Live Progress, Results, Review, Reports
- Express backend (port 3001) with mock data + AWS Bedrock Agent integration
- Vite frontend (port 3002) proxied to Express
- MUI v5 theming with AWS brand colors

## Architecture

### Stack
- **Framework**: Next.js 16 (App Router)
- **UI Library**: shadcn/ui
- **Styling**: Tailwind CSS with AWS custom theme
- **Charts**: Recharts (same as existing)
- **State**: React hooks (useState/useEffect)
- **API**: Next.js API routes (replaces Express server)

### Rendering Strategy
- Root layout: Server component (nav, theme provider)
- All pages: Client components (`"use client"`) — they're interactive with hooks, forms, charts

### Project Structure

```
aws-frontend/
├── app/
│   ├── layout.tsx                        # Root layout + providers
│   ├── page.tsx                          # Dashboard
│   ├── new-assessment/page.tsx           # Assessment form
│   ├── progress/[sessionId]/page.tsx     # Live progress
│   ├── results/[sessionId]/page.tsx      # Results + tabs
│   ├── review/[sessionId]/page.tsx       # HITL review
│   ├── reports/[sessionId]/page.tsx      # Reports + downloads
│   └── api/
│       ├── health/route.ts
│       └── wafr/
│           ├── run/route.ts
│           ├── sessions/route.ts
│           └── session/[id]/
│               ├── route.ts              # DELETE session
│               ├── state/route.ts
│               ├── pillars/route.ts
│               ├── insights/route.ts
│               ├── questions/route.ts
│               ├── gaps/route.ts
│               └── report/
│                   ├── status/route.ts
│                   ├── download/route.ts
│                   └── aws/download/route.ts
├── components/
│   ├── ui/                               # shadcn generated
│   ├── header.tsx
│   ├── stat-card.tsx
│   ├── pillar-card.tsx
│   ├── insight-card.tsx
│   ├── gap-card.tsx
│   └── review-item.tsx
├── lib/
│   ├── mock-data.ts                      # Ported from Express
│   ├── api.ts                            # Client fetch helpers
│   ├── session-store.ts                  # In-memory session store
│   └── utils.ts                          # cn() utility
├── tailwind.config.ts
├── next.config.ts
└── package.json
```

## Theme — AWS Brand Colors

```
Primary:    #232F3E (squid ink — dark blue)
Accent:     #FF9900 (AWS orange)
Light BG:   #F2F3F3 (fog)
Dark BG:    #0F1419 (ink)
Text:       #232F3E / #687078
Success:    #1D8102
Error:      #D13212
Warning:    #FF9900
Info:       #0972D3
```

Dark/light mode toggle via shadcn theme provider (next-themes).

## Pages — Functional Spec

### 1. Dashboard (`/`)
- Health status badge (green/red)
- 4 gradient stat cards (Total, Completed, In Progress, Avg Score)
- Sessions table with status chips, view/delete actions
- Empty state with CTA
- 3 info cards at bottom

### 2. New Assessment (`/new-assessment`)
- Stepper (3 steps visual)
- Form: Application Name, Workload Description (textarea), Environment, Owner
- Sidebar: "What to Expect" + "Duration" cards
- POST /api/wafr/run → navigate to /progress/:sessionId

### 3. Live Progress (`/progress/[sessionId]`)
- 6-phase stepper
- Circular progress indicator
- Activity log of events
- Session info sidebar
- Auto-navigates to /results after completion (polling /api/wafr/session/:id/state)

### 4. Results (`/results/[sessionId]`)
- Summary cards (score, insights count, gaps, questions)
- 4 tabs: Pillars (radar+bar chart), Insights, Questions, Gaps
- Navigate to Review or Reports

### 5. Review (`/review/[sessionId]`)
- Progress bar (% reviewed)
- Stats: Total, Pending, Approved, Rejected
- Review item cards with approve/reject buttons
- Comment field per item
- Batch approve + Finalize actions

### 6. Reports (`/reports/[sessionId]`)
- 3 download buttons (PDF, JSON, AWS Report)
- Executive Summary (strengths, actions, quick wins)
- Assessment Details metadata
- Review Summary stats
- Detailed Insights accordions
- Gap remediation accordions
- Pillar-by-pillar accordions
- Investment/timeline section
- Trend charts (line + bar)

## API Routes — Mock Data

All API routes serve mock data (same shapes as existing Express server). The mock data is imported from `lib/mock-data.ts`. Session store uses a module-level Map for in-memory state.

## shadcn Components Needed

card, button, badge, input, textarea, tabs, accordion, table, progress, alert, dialog, separator, tooltip, avatar, select, sheet

## Dependencies

```json
{
  "next": "^15",
  "react": "^19",
  "react-dom": "^19",
  "recharts": "^2.10",
  "next-themes": "^0.4",
  "lucide-react": "latest",
  "class-variance-authority": "latest",
  "clsx": "latest",
  "tailwind-merge": "latest"
}
```

## Out of Scope
- Real AWS backend integration (mock only for now)
- WebSocket real-time updates (use polling instead)
- PDF generation (serve HTML reports)
- Lambda deployment adapter
