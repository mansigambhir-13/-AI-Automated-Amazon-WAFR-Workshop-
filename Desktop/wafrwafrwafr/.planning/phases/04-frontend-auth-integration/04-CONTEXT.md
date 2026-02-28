# Phase 4: Frontend Auth Integration - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Add Cognito authentication to the Next.js frontend: login/logout UI via Amplify Authenticator, automatic access token attachment on all API requests, role-based UI visibility (WafrTeam vs WafrClients), and auth guard that prevents unauthenticated access. No backend changes — Phase 3 already deployed JWT middleware.

</domain>

<decisions>
## Implementation Decisions

### Login/Logout Experience
- Use Amplify Authenticator component (not a custom form)
- Specific error messages from Cognito (e.g., "User not found" vs "Wrong password") — not generic
- Session-only storage (sessionStorage) — closing the browser tab logs the user out
- Login only — hide the signup/create-account tab (admin-only signup per Phase 1)
- Forgot password flow enabled via Authenticator's built-in reset
- No "Remember me" checkbox — consistent with session-only persistence
- After successful login, redirect to the dashboard/sessions list page
- Style the Authenticator to match the app's existing theme (CSS variable overrides)
- Display WAFR app name + logo above the login form
- Claude's discretion: logout button placement (header vs user menu)
- Claude's discretion: loading spinner vs immediate form during auth state check
- Claude's discretion: lockout UX (use Cognito's built-in messages)

### Token Management
- SSE streaming connections use fetch-based SSE (ReadableStream) instead of EventSource — supports Authorization header natively
- Claude's discretion: centralized API client vs per-component token fetch (recommend centralized based on existing patterns)
- Claude's discretion: silent token refresh vs re-login prompt on expiry (recommend Amplify's default silent refresh)
- Claude's discretion: 401 response handling strategy (recommend try-refresh-then-redirect)

### Role-Based UI Access
- Display logged-in user's name and role badge (WafrTeam/WafrClients) in the app header
- Claude's discretion: WafrClients see own sessions only vs read-only view of all (recommend own sessions only)
- Claude's discretion: restricted actions hidden completely vs visible-but-disabled (recommend hidden)
- Claude's discretion: client-side + server-side enforcement vs backend-only (recommend both)

### Auth Guard Behavior
- Claude's discretion: redirect to login page vs login modal overlay (recommend redirect)
- Claude's discretion: deep link preservation vs always-dashboard (recommend always-dashboard, consistent with post-login decision)
- Claude's discretion: guard entire app vs specific routes (recommend entire app)
- Claude's discretion: block-until-resolved vs skeleton during auth loading (recommend block with spinner)

### Claude's Discretion
- Logout button placement (header button vs dropdown menu)
- Auth loading state UX (spinner vs form flash)
- Lockout messaging (Cognito's built-in vs custom)
- API client pattern (centralized recommended)
- Token refresh strategy (silent refresh recommended)
- 401 handling (try-refresh-then-redirect recommended)
- Client data visibility (own sessions only recommended)
- Restricted action UI (hidden recommended)
- Role enforcement layer (both client + server recommended)
- Auth guard redirect style (redirect recommended)
- Deep link handling (always-dashboard recommended)
- Guard scope (entire app recommended)
- Auth loading gate (block with spinner recommended)

</decisions>

<specifics>
## Specific Ideas

- Cognito User Pool ID: us-east-1_U4ugKPUrh (in Secrets Manager as wafr-cognito-user-pool-id, already in App Runner env)
- Cognito App Client ID: 65fis729feu3lr317rm6oaue5s (in Secrets Manager as wafr-cognito-client-id, already in App Runner env)
- Frontend App Runner: https://3fhp6mfj7u.us-east-1.awsapprunner.com
- Backend App Runner: https://i5kj2nnkxd.us-east-1.awsapprunner.com
- Phase 1 blocker noted: Amplify v6 documents Next.js support up to 15.x; project uses 16.1.6 — must verify compatibility before writing any auth code. Fallback: amazon-cognito-identity-js directly.
- Phase 1 blocker noted: NEXT_PUBLIC_* variables are baked at build time in Next.js but App Runner injects at runtime — must verify env vars are available during App Runner build step.
- Backend auth already enforces: AUTH_REQUIRED env var, Cognito JWT validation, require_team_role dependency on write endpoints

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-frontend-auth-integration*
*Context gathered: 2026-02-28*
