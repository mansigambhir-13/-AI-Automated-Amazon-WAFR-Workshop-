---
phase: 04-frontend-auth-integration
plan: 01
subsystem: auth
tags: [amplify, cognito, nextjs, jwt, bearer-token, sse]

# Dependency graph
requires:
  - phase: 03-backend-auth-and-api-security
    provides: JWT middleware that validates Cognito Bearer tokens on all API endpoints
  - phase: 01-infrastructure-foundation
    provides: Cognito User Pool and App Client IDs (NEXT_PUBLIC_COGNITO_USER_POOL_ID, NEXT_PUBLIC_COGNITO_CLIENT_ID)
provides:
  - Amplify v6 installed and configured in Next.js 16 frontend
  - AmplifyProvider component wrapping entire app in Cognito authentication gate
  - Auth helpers: getAccessToken, getCurrentUserInfo, isTeamUser, signOutUser
  - All API requests (GET/POST/DELETE) carry Authorization: Bearer token
  - SSE streaming fetch includes Authorization header
  - Session persists only in sessionStorage (tab close clears session)
  - Dockerfile ready with Cognito build ARGs
  - Reports page download handlers use auth-aware async fetch
affects: [05-deployment, frontend-components, review-workflow]

# Tech tracking
tech-stack:
  added:
    - aws-amplify@6.16.2
    - "@aws-amplify/ui-react@6.15.1"
    - "@aws-amplify/adapter-nextjs@1.7.2"
  patterns:
    - Amplify.configure() called at module scope in client component (not useEffect) to avoid re-configuration on renders
    - cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage) for tab-scoped sessions
    - authHeaders() helper in api.ts exported for reuse across api.ts, sse-client.ts, backend-api.ts
    - 401 responses trigger window.location.href = '/' to force re-authentication through Authenticator gate
    - Authenticator render props pattern: {({ signOut, user }) => <>{children}</>}

key-files:
  created:
    - aws-frontend/lib/auth.ts
    - aws-frontend/components/amplify-provider.tsx
  modified:
    - aws-frontend/package.json
    - aws-frontend/package-lock.json
    - aws-frontend/Dockerfile
    - aws-frontend/app/globals.css
    - aws-frontend/app/layout.tsx
    - aws-frontend/lib/api.ts
    - aws-frontend/lib/sse-client.ts
    - aws-frontend/lib/backend-api.ts
    - aws-frontend/app/reports/[sessionId]/page.tsx

key-decisions:
  - "Amplify.configure() at module scope in amplify-provider.tsx — avoids re-configuration on re-renders; Next.js only loads the module once per tab session"
  - "cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage) — clears tokens on tab close, satisfying the session-not-persisting requirement"
  - "authHeaders() exported from api.ts — single source of truth for Bearer token injection, reused by sse-client.ts and backend-api.ts"
  - "Auth-aware downloadReport/downloadAwsReport/downloadResults functions added to backend-api.ts — direct URL hrefs cannot carry Authorization headers; blob-download pattern required"
  - "Toaster kept outside AmplifyProvider in layout.tsx — toast notifications must work on the login screen before authentication"
  - "Authenticator hideSignUp prop enabled — admin-only user creation via Cognito console, no self-registration"

patterns-established:
  - "Pattern: authHeaders() — call before any fetch, merge into headers object"
  - "Pattern: 401 redirect — check res.status === 401 after fetch, redirect window.location.href = '/' to re-enter Authenticator gate"
  - "Pattern: auth-aware file downloads — use fetch + authHeaders() + blob URL creation instead of window.open(url)"

requirements-completed: [AUTH-03, AUTH-04]

# Metrics
duration: 8min
completed: 2026-02-28
---

# Phase 4 Plan 01: Frontend Auth Integration Summary

**Amplify v6 Cognito login gate with sessionStorage persistence, Bearer token on all API/SSE requests, and auth-aware file downloads**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-28T15:36:11Z
- **Completed:** 2026-02-28T15:44:00Z
- **Tasks:** 2
- **Files modified:** 9 (plus 2 created)

## Accomplishments

- Entire Next.js app gated behind Cognito Authenticator — unauthenticated users see the login form with WAFR branding (Settings icon, app name, subtitle), no signup tab
- All API requests (apiGet/apiPost/apiDelete) and SSE streaming fetch now carry `Authorization: Bearer <token>` header via the shared `authHeaders()` helper
- Session clears on tab close via sessionStorage — re-opening the browser shows the login form again
- Hardcoded `'frontend-user'` reviewer/approver IDs replaced with real Cognito username from `getCurrentUserInfo()` in all three review action functions
- Auth-aware download functions added for reports/results — blob-download pattern ensures the Bearer token is included

## Task Commits

Each task was committed atomically (in the aws-frontend git repository):

1. **Task 1: Install Amplify packages, create auth helpers + AmplifyProvider, update Dockerfile and globals.css** - `a1fddc9` (feat)
2. **Task 2: Add Bearer token to all API calls and SSE streaming, replace hardcoded reviewer_id** - `968ecfd` (feat)

## Files Created/Modified

- `aws-frontend/lib/auth.ts` — Auth helper functions: getAccessToken, getCurrentUserInfo, isTeamUser, signOutUser (imports from aws-amplify/auth tree-shakeable sub-export)
- `aws-frontend/components/amplify-provider.tsx` — Client component: Amplify.configure() at module scope, sessionStorage token persistence, Authenticator with hideSignUp and WAFR branding header
- `aws-frontend/app/layout.tsx` — Wrapped children with AmplifyProvider inside ThemeProvider; Toaster stays outside
- `aws-frontend/Dockerfile` — Added ARG/ENV for NEXT_PUBLIC_COGNITO_USER_POOL_ID and NEXT_PUBLIC_COGNITO_CLIENT_ID
- `aws-frontend/app/globals.css` — Added Amplify Authenticator CSS theme overrides (orange/amber primary, dark mode variants)
- `aws-frontend/lib/api.ts` — Added authHeaders() export, updated apiGet/apiPost/apiDelete to include Bearer token, 401 redirect handling
- `aws-frontend/lib/sse-client.ts` — SSE fetch now includes Authorization header via authHeaders(); 401 triggers onRunError callback + redirect
- `aws-frontend/lib/backend-api.ts` — submitReviewDecision/batchApprove/finalizeReview use real Cognito username; added downloadReport/downloadAwsReport/downloadResults async auth-aware download functions; deprecated URL-returning functions
- `aws-frontend/package.json` — Added aws-amplify, @aws-amplify/ui-react, @aws-amplify/adapter-nextjs

## Decisions Made

- Amplify.configure() at module scope — not inside useEffect — per Amplify v6 documentation to avoid multiple initializations
- sessionStorage used for token persistence (not localStorage) so closing the browser tab clears the session
- authHeaders() exported from api.ts to be the single source of truth, reused in sse-client.ts and backend-api.ts
- Toaster component placed outside AmplifyProvider so toast notifications work on the login screen
- hideSignUp on Authenticator — no self-registration (admin-only user creation per locked decision)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Updated reports page download handlers to use auth-aware fetch**
- **Found during:** Task 2 (updating backend-api.ts download functions)
- **Issue:** The reports page `downloadPdfReport` and `viewAwsReport` handlers used `window.open(url, '_blank')` with the old URL-returning functions. Since the backend now requires a Bearer token, direct navigation to the download URL would return 401.
- **Fix:** Updated `downloadPdfReport` and `viewAwsReport` in `app/reports/[sessionId]/page.tsx` to call the new async `backend.downloadReport()` and `backend.downloadAwsReport()` functions, which use fetch with authHeaders() and trigger a blob download.
- **Files modified:** aws-frontend/app/reports/[sessionId]/page.tsx
- **Verification:** TypeScript compiles without error; download handlers are now async functions
- **Committed in:** 968ecfd (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 2 - missing critical auth on download requests)
**Impact on plan:** Auto-fix necessary for correct operation — without it, report downloads would silently fail with 401 after auth was wired in. No scope creep.

## Issues Encountered

None — plan executed cleanly. TypeScript compilation passed with zero errors after both tasks.

## User Setup Required

None — no external service configuration required beyond what was established in Phase 1 (Cognito User Pool and App Client IDs already in secrets). The CI `docker build` command must pass:
```
--build-arg NEXT_PUBLIC_COGNITO_USER_POOL_ID=us-east-1_U4ugKPUrh
--build-arg NEXT_PUBLIC_COGNITO_CLIENT_ID=65fis729feu3lr317rm6oaue5s
```

## Next Phase Readiness

- Frontend auth gate is complete — ready for Phase 5 deployment configuration
- Backend JWT middleware (Phase 3) accepts Cognito tokens and will return 200 for authenticated requests
- All review workflow actions now carry the real user identity for audit trail
- Remaining concern from STATE.md: Amplify v6 docs show Next.js support up to 15.x; project uses 16.1.6. Package installed without errors and TypeScript passes — compatibility appears satisfied in practice.

---
*Phase: 04-frontend-auth-integration*
*Completed: 2026-02-28*

## Self-Check: PASSED

- aws-frontend/lib/auth.ts: FOUND
- aws-frontend/components/amplify-provider.tsx: FOUND
- .planning/phases/04-frontend-auth-integration/04-01-SUMMARY.md: FOUND
- commit a1fddc9 (Task 1): FOUND in aws-frontend git log
- commit 968ecfd (Task 2): FOUND in aws-frontend git log
- TypeScript compilation: PASS (0 errors)
