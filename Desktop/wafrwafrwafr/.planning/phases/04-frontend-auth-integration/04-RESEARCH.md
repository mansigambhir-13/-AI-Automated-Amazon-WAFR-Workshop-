# Phase 4: Frontend Auth Integration - Research

**Researched:** 2026-02-28
**Domain:** AWS Amplify v6 + Next.js 16 App Router authentication, Cognito token management, role-based UI
**Confidence:** HIGH (critical blockers resolved via official sources; API patterns verified)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- Use Amplify Authenticator component (not a custom form)
- Specific error messages from Cognito (e.g., "User not found" vs "Wrong password") — not generic
- Session-only storage (sessionStorage) — closing the browser tab logs the user out
- Login only — hide the signup/create-account tab (admin-only signup per Phase 1)
- Forgot password flow enabled via Authenticator's built-in reset
- No "Remember me" checkbox — consistent with session-only persistence
- After successful login, redirect to the dashboard/sessions list page
- Style the Authenticator to match the app's existing theme (CSS variable overrides)
- Display WAFR app name + logo above the login form
- SSE streaming connections use fetch-based SSE (ReadableStream) instead of EventSource — supports Authorization header natively
- Display logged-in user's name and role badge (WafrTeam/WafrClients) in the app header

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

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AUTH-03 | Frontend provides login, signup, and password reset UI via Amplify | Amplify Authenticator with `hideSignUp` prop; `initialState="signIn"`; forgot password built-in; `sessionStorage` token storage via `cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage)` |
| AUTH-04 | Team users can create/view/manage all assessments; client users can only view their own | `fetchAuthSession()` returns `accessToken` JWT; decode payload for `cognito:groups`; WafrTeam vs WafrClients group check; filter `listSessions()` for client role |
</phase_requirements>

---

## Summary

Phase 4 adds Cognito authentication to the existing Next.js 16.1.6 frontend. The two critical blockers identified in STATE.md are both resolved: `@aws-amplify/adapter-nextjs` v1.7.0 (released late 2025) updated its peer dependency range to `next: ">=13.5.0 <17.0.0"`, meaning Next.js 16 is officially supported when using aws-amplify 6.13.1+. The Turbopack-specific issue with `@aws-amplify/ui-react-liveness` does not affect this project (that package is for facial liveness detection, not auth UI). The Authenticator and core auth libraries work correctly with Next.js 16 and Turbopack.

The NEXT_PUBLIC_* env var blocker is real but manageable. The frontend Dockerfile already uses build-time `ARG NEXT_PUBLIC_BACKEND_URL` and the App Runner deployment passes Cognito IDs as `WAFR_COGNITO_USER_POOL_ID` and `WAFR_COGNITO_CLIENT_ID` via Secrets Manager (not `NEXT_PUBLIC_*`). This means Cognito config values are NOT currently `NEXT_PUBLIC_*` variables — they are server-side env vars available at `process.env.WAFR_COGNITO_USER_POOL_ID`. Since `Amplify.configure()` must run on the client side (in a `"use client"` component), the Cognito IDs must be exposed to the browser. The correct pattern for this project is to inject them from a server component into the client-side config, or add them as `NEXT_PUBLIC_*` build-time ARGs in the Dockerfile.

The architecture follows a standard pattern: an `AmplifyProvider` client component wraps the app in `layout.tsx`, calling `Amplify.configure()` and `cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage)`. The `Authenticator` component gates all children. The existing `lib/api.ts` is extended to fetch the access token from `fetchAuthSession()` before each request. The existing `lib/backend-api.ts` is unchanged except that `reviewer_id: 'frontend-user'` hardcodes get replaced with the real user's sub/username from `getCurrentUser()`.

**Primary recommendation:** Install `aws-amplify@^6.13.1` and `@aws-amplify/ui-react@^6.15.0`, add Cognito IDs as Docker build ARGs (`NEXT_PUBLIC_COGNITO_USER_POOL_ID`, `NEXT_PUBLIC_COGNITO_CLIENT_ID`), wrap the layout with an `AmplifyProvider` client component that configures Amplify with `sessionStorage`, and extend `lib/api.ts` to attach `Authorization: Bearer <token>` on all requests.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `aws-amplify` | ^6.16.2 (latest) | Core Cognito auth APIs: `fetchAuthSession`, `getCurrentUser`, `signOut` | Official AWS client; v6 is modular (tree-shakeable), v5 is deprecated |
| `@aws-amplify/ui-react` | ^6.15.0 (latest) | Authenticator component with pre-built login/forgot-password UI | Official AWS UI library; `hideSignUp` prop, CSS variable theming |
| `@aws-amplify/adapter-nextjs` | ^1.7.0+ | Next.js-specific adapter for SSR contexts | Required for `createServerRunner` / server-side auth; v1.7.0 added Next.js 16 support |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aws-amplify/utils` (sub-export) | included in aws-amplify | `sessionStorage` storage option import | Required for tab-close-equals-logout behavior |
| `aws-amplify/auth/cognito` (sub-export) | included in aws-amplify | `cognitoUserPoolsTokenProvider` for custom storage config | Required to call `setKeyValueStorage(sessionStorage)` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Amplify Authenticator | Custom form with `amazon-cognito-identity-js` directly | More control; much more boilerplate; no forgot-password UI; user decided Amplify Authenticator |
| NEXT_PUBLIC_* env vars for Cognito IDs | Server-side injection via window.__ENV | Either approach works; NEXT_PUBLIC_* is simpler for App Runner since IDs are baked at build time (not secret) |
| sessionStorage | CookieStorage (Amplify default for Next.js SSR) | sessionStorage is correct for this project's "tab close = logout" requirement; cookies persist across tabs |

**Installation:**
```bash
npm install aws-amplify@^6.16.2 @aws-amplify/ui-react@^6.15.0 @aws-amplify/adapter-nextjs@^1.7.0
```

---

## Architecture Patterns

### Recommended Project Structure

New files and modifications for this phase:

```
aws-frontend/
├── lib/
│   ├── auth.ts              # NEW: auth helpers (getAccessToken, getCurrentUserInfo, signOutUser)
│   ├── api.ts               # MODIFY: add Authorization header to all fetch calls
│   └── backend-api.ts       # MODIFY: replace hardcoded 'frontend-user' with real user ID
├── components/
│   ├── amplify-provider.tsx # NEW: "use client" wrapper — Amplify.configure + sessionStorage
│   └── header.tsx           # MODIFY: add user name + role badge + logout button
└── app/
    └── layout.tsx           # MODIFY: wrap children with <AmplifyProvider>
```

### Pattern 1: AmplifyProvider Client Component

**What:** A `"use client"` component placed at the layout level. It calls `Amplify.configure()` once on mount and wraps all children with `<Authenticator>`. This is the required pattern for Next.js App Router because `Amplify.configure()` uses browser APIs and must run in a client component.

**When to use:** Always — this is the entry point for all auth functionality.

**Example:**
```typescript
// components/amplify-provider.tsx
"use client";

import { Amplify } from "aws-amplify";
import { sessionStorage } from "aws-amplify/utils";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { Authenticator } from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";

// Amplify.configure must be called before any auth API is used.
// These are NEXT_PUBLIC_* so they are baked at build time — acceptable
// because User Pool ID and Client ID are not secret (they appear in public JS bundles).
Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
      userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID!,
    },
  },
});

// Override default localStorage with sessionStorage — tab close clears session.
cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage);

export default function AmplifyProvider({ children }: { children: React.ReactNode }) {
  return (
    <Authenticator
      hideSignUp
      components={{
        Header() {
          return (
            <div className="...">
              {/* WAFR logo + app name above the form */}
            </div>
          );
        },
      }}
    >
      {children}
    </Authenticator>
  );
}
```

**layout.tsx integration:**
```typescript
// app/layout.tsx
import AmplifyProvider from "@/components/amplify-provider";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
          <AmplifyProvider>
            <main className="min-h-screen bg-background bg-dot-pattern">
              {children}
            </main>
          </AmplifyProvider>
          <Toaster position="bottom-right" richColors />
        </ThemeProvider>
      </body>
    </html>
  );
}
```

### Pattern 2: Centralized Auth-Aware API Client

**What:** Extend the existing `lib/api.ts` to fetch the access token from `fetchAuthSession()` before every request and attach it as `Authorization: Bearer <token>`. Amplify's `fetchAuthSession()` automatically refreshes the token when expired (if a valid refresh token exists), so no manual retry logic is needed for the normal case.

**When to use:** All outgoing API calls — replaces the current unauthenticated `fetch` calls in `api.ts`.

**Example:**
```typescript
// lib/auth.ts  — auth helpers
import { fetchAuthSession, getCurrentUser, signOut } from "aws-amplify/auth";

export async function getAccessToken(): Promise<string> {
  const session = await fetchAuthSession();
  const token = session.tokens?.accessToken?.toString();
  if (!token) throw new Error("No access token — user not authenticated");
  return token;
}

export async function getCurrentUserInfo(): Promise<{
  userId: string;
  username: string;
  groups: string[];
}> {
  const user = await getCurrentUser();
  const session = await fetchAuthSession();
  // Groups are in the access token payload as cognito:groups
  const payload = session.tokens?.accessToken?.payload;
  const groups = (payload?.["cognito:groups"] as string[]) ?? [];
  return { userId: user.userId, username: user.username, groups };
}

export function isTeamUser(groups: string[]): boolean {
  return groups.includes("WafrTeam");
}

export async function signOutUser(): Promise<void> {
  await signOut();
}
```

```typescript
// lib/api.ts  — modified to add auth header
import { getAccessToken } from "./auth";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

async function authHeaders(): Promise<Record<string, string>> {
  try {
    const token = await getAccessToken();
    return { Authorization: `Bearer ${token}` };
  } catch {
    // If token fetch fails (e.g., not logged in), return empty — Authenticator will redirect
    return {};
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const url = path.startsWith("http") ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, { headers: await authHeaders() });
  if (res.status === 401) {
    // Token may be expired and refresh failed — force re-login
    window.location.href = "/";
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const errorText = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const url = path.startsWith("http") ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    window.location.href = "/";
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const errorText = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const url = path.startsWith("http") ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (res.status === 401) {
    window.location.href = "/";
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const errorText = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export { BACKEND_URL };
```

### Pattern 3: SSE with Auth Header (fetch-based — already implemented)

**What:** The existing `lib/sse-client.ts` already uses `fetch` (not `EventSource`), so it already supports custom headers. Only the header attachment needs to be added.

**Example diff:**
```typescript
// lib/sse-client.ts — only change: add Authorization header to fetch call
const response = await fetch(url, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    ...(await authHeaders()),   // add this line
  },
  body,
  signal: controller.signal,
});
```

Because `authHeaders()` is in `lib/auth.ts`, import it and call it the same way as in `api.ts`. The SSE streaming logic itself is unchanged.

### Pattern 4: Role-Based Header (user name + role badge)

**What:** The header component uses `getCurrentUserInfo()` to display the logged-in user's name and a role badge (WafrTeam or WafrClients). The user's Cognito `username` attribute is the display name. Role comes from the `cognito:groups` claim in the access token.

**Example:**
```typescript
// components/header.tsx — add to existing component
"use client";
import { useEffect, useState } from "react";
import { getCurrentUserInfo, signOutUser } from "@/lib/auth";

// Inside Header component:
const [userInfo, setUserInfo] = useState<{ username: string; groups: string[] } | null>(null);

useEffect(() => {
  getCurrentUserInfo().then(setUserInfo).catch(() => setUserInfo(null));
}, []);

// In JSX — right side of header, before the theme toggle:
{userInfo && (
  <div className="flex items-center gap-2">
    <span className="text-sm text-foreground font-medium">{userInfo.username}</span>
    <Badge className={userInfo.groups.includes("WafrTeam")
      ? "bg-primary/10 text-primary border-primary/20"
      : "bg-secondary/10 text-secondary border-secondary/20"
    }>
      {userInfo.groups.includes("WafrTeam") ? "WafrTeam" : "WafrClients"}
    </Badge>
    <Button variant="ghost" size="sm" onClick={signOutUser}>
      Sign out
    </Button>
  </div>
)}
```

### Pattern 5: Role-Based Session Filtering (AUTH-04)

**What:** Client users should only see their own sessions. The backend `listSessions()` endpoint already returns sessions filtered by user on the server side (via JWT middleware in Phase 3). The frontend also enforces this by checking the user's role:

- WafrTeam: call `apiGet('/api/wafr/sessions')` as-is
- WafrClients: the backend already returns only their sessions, but the UI hides the "New Assessment" button and any write actions

The role check happens in each page component that uses `getCurrentUserInfo()`. Because this is client-side enforcement layered on top of server-side enforcement (backend already validates JWT and user group), this is defense in depth per the locked decision.

### Pattern 6: Authenticator CSS Variable Theming

**What:** Override Amplify's built-in CSS variables to match the existing app theme. The app uses `oklch()` color values from `globals.css`. Target the `[data-amplify-authenticator]` CSS selector.

**Example (add to globals.css):**
```css
[data-amplify-authenticator] {
  --amplify-components-authenticator-router-box-shadow: none;
  --amplify-components-authenticator-router-border-width: 1px;
  --amplify-components-button-primary-background-color: oklch(0.750 0.160 55);
  --amplify-components-button-primary-color: oklch(0.985 0 0);
  --amplify-components-button-primary-hover-background-color: oklch(0.700 0.160 55);
  --amplify-components-fieldcontrol-focus-box-shadow: 0 0 0 2px oklch(0.750 0.160 55 / 30%);
  --amplify-components-tabs-item-active-border-color: oklch(0.750 0.160 55);
  --amplify-components-tabs-item-active-color: oklch(0.750 0.160 55);
  --amplify-fonts-default-variable: var(--font-figtree);
  --amplify-fonts-default-static: var(--font-figtree);
}
```

### Anti-Patterns to Avoid

- **Calling `Amplify.configure()` in a server component:** Server components run on the server and cannot access `sessionStorage` or `window`. Always call `Amplify.configure()` in a `"use client"` component.
- **Calling `fetchAuthSession()` without catching errors:** If the user has no session, it throws. Always wrap in try/catch or check the Authenticator context.
- **Using `EventSource` for SSE:** The existing code already uses `fetch`-based SSE — do not switch to `EventSource` which does not support custom headers.
- **Storing tokens in `localStorage`:** The decision is `sessionStorage` for tab-close-equals-logout. Amplify defaults to `localStorage`; the `cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage)` call is mandatory.
- **Using `CookieStorage` in the Next.js SSR adapter:** This project uses App Runner with a client-side-only auth flow. The `createServerRunner` / cookie-based SSR pattern is for Next.js Middleware auth guards on server components — not required here since the Authenticator component handles the guard client-side.
- **Placing `Amplify.configure()` at module scope in a file that might be imported by server code:** This can cause build errors. Keep it inside the `"use client"` component or in a file that is only ever imported by client components.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Login form with forgot password | Custom form + Cognito API calls | `@aws-amplify/ui-react` `<Authenticator>` | Password reset flow, SRP auth challenge, error message mapping — all handled; user decided Amplify Authenticator |
| Token refresh on expiry | Retry interceptor + manual refresh call | `fetchAuthSession()` automatic refresh | Amplify calls Cognito's refresh endpoint automatically when the access token is expired and a valid refresh token exists |
| SRP authentication challenge | Custom HMAC-SHA256 implementation | `aws-amplify` core | SRP is cryptographically complex; `ALLOW_USER_SRP_AUTH` (already configured in Phase 1) requires SRP — Amplify handles this |
| JWT decode for group claims | `atob()` + manual JSON parse | `session.tokens?.accessToken?.payload` | Amplify parses the JWT payload automatically and exposes it as an object |
| Auth state listener | `setInterval` polling | `Hub.listen('auth', handler)` from `aws-amplify/utils` | Amplify dispatches auth events (signedIn, signedOut, tokenRefresh) via Hub; use for sign-out cleanup if needed |

**Key insight:** Amplify v6's modular imports mean you pay only for what you use. Import from `"aws-amplify/auth"` (not `"aws-amplify"`) to keep the bundle small. The Authenticator UI component handles the entire login/forgot-password flow including Cognito error message passthrough.

---

## Common Pitfalls

### Pitfall 1: Cognito IDs exposed as NEXT_PUBLIC_* (expected, not a bug)

**What goes wrong:** Teams treat User Pool ID and App Client ID as secrets. They are NOT secrets — they appear in the compiled JavaScript bundle and are visible to any user. Secrets Manager is correct for server-side code (Python backend). For the Next.js frontend, `NEXT_PUBLIC_COGNITO_USER_POOL_ID` and `NEXT_PUBLIC_COGNITO_CLIENT_ID` as Docker build ARGs is the correct pattern.

**Why it happens:** Confusion between Cognito App Client ID (public) and App Client Secret (secret — and we have NO client secret per Phase 1 decision). Public clients have no secret by design.

**How to avoid:** Add two ARG lines to the Dockerfile. Pass them in the CI/CD `docker build` command. The values are already available in Secrets Manager if needed for the build step (but since they are public IDs, hardcoding them in the Dockerfile or CI env is also fine).

**Warning signs:** If `process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID` is `undefined` in the browser console, the ARG was not passed to `docker build`.

### Pitfall 2: `Amplify.configure()` called before Next.js hydration

**What goes wrong:** `Amplify.configure()` called at module scope in a file that gets server-side rendered. Error: "sessionStorage is not defined" or "window is not defined".

**Why it happens:** Next.js App Router server components run on Node.js where `sessionStorage` does not exist.

**How to avoid:** Always mark the file containing `Amplify.configure()` with `"use client"`. The `AmplifyProvider` component pattern (Pattern 1) is the correct isolation.

**Warning signs:** Build error mentioning `sessionStorage`, `window`, or `localStorage` during `next build`.

### Pitfall 3: `sessionStorage` not set before Authenticator renders

**What goes wrong:** `Amplify.configure()` is called but `cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage)` is called after the Authenticator has already rendered. Tokens get stored in `localStorage` (the default).

**Why it happens:** The `setKeyValueStorage` call must happen immediately after `Amplify.configure()` at module scope (inside the `"use client"` file), not inside a `useEffect`.

**How to avoid:** Call both at module scope in `amplify-provider.tsx`:
```typescript
Amplify.configure({ ... });
cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage);
```
Not inside `useEffect`.

**Warning signs:** Tokens persist after tab close; opening a new tab keeps the user logged in.

### Pitfall 4: `@aws-amplify/ui-react/styles.css` not imported

**What goes wrong:** Authenticator renders with no styling — broken layout, invisible buttons.

**Why it happens:** The Authenticator CSS must be explicitly imported. It is not injected automatically.

**How to avoid:** Add `import "@aws-amplify/ui-react/styles.css";` to `amplify-provider.tsx` (or `globals.css` via `@import`).

**Warning signs:** Login form appears as unstyled HTML.

### Pitfall 5: `fetchAuthSession()` throws when called during SSR

**What goes wrong:** Any component that calls `fetchAuthSession()` on the server side (e.g., in a server component's render path) throws because there is no session context on the server.

**Why it happens:** `fetchAuthSession()` from `"aws-amplify/auth"` is client-only. The server-side version requires `createServerRunner` from `@aws-amplify/adapter-nextjs`.

**How to avoid:** This project does not use server-side auth checks (all pages are guarded by the client-side Authenticator). Only call `fetchAuthSession()` in `"use client"` components or in `lib/api.ts` functions that are only invoked from client components.

**Warning signs:** Error: "You are not signed in" or "No current user" thrown during server-side rendering.

### Pitfall 6: NEXT_PUBLIC_* variable is `undefined` at runtime in App Runner

**What goes wrong:** `process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID` is `undefined` in the browser even though it is set in App Runner's runtime environment.

**Why it happens:** `NEXT_PUBLIC_*` variables are inlined at `next build` time. App Runner's runtime environment is injected after the build — the values exist in `process.env` on the server at runtime, but they were NOT present during `next build` inside the Docker container, so the inline replacement never happened.

**How to avoid:** The Cognito User Pool ID and Client ID must be available as Docker `ARG` values passed at `docker build` time:
```dockerfile
ARG NEXT_PUBLIC_COGNITO_USER_POOL_ID
ENV NEXT_PUBLIC_COGNITO_USER_POOL_ID=$NEXT_PUBLIC_COGNITO_USER_POOL_ID
ARG NEXT_PUBLIC_COGNITO_CLIENT_ID
ENV NEXT_PUBLIC_COGNITO_CLIENT_ID=$NEXT_PUBLIC_COGNITO_CLIENT_ID
```
And the CI pipeline must pass `--build-arg NEXT_PUBLIC_COGNITO_USER_POOL_ID=us-east-1_U4ugKPUrh --build-arg NEXT_PUBLIC_COGNITO_CLIENT_ID=65fis729feu3lr317rm6oaue5s` to `docker build`.

**Warning signs:** `Amplify.configure()` is called with `userPoolId: undefined` and Authenticator silently fails or throws `AuthError`.

### Pitfall 7: The Amplify CSS conflicts with Tailwind v4

**What goes wrong:** Importing `@aws-amplify/ui-react/styles.css` introduces CSS that conflicts with the app's Tailwind v4 / shadcn setup.

**Why it happens:** Amplify's CSS sets global styles and uses CSS custom properties that may collide with Tailwind reset.

**How to avoid:** Import Amplify CSS before Tailwind in `globals.css` or scope the import. Override conflicting CSS variables in the `[data-amplify-authenticator]` block. If conflicts are severe, consider importing only the Authenticator's CSS via a scoped import.

**Warning signs:** App-wide button styles change after adding Amplify CSS import; Tailwind utilities stop working in Authenticator area.

---

## Code Examples

Verified patterns from official sources:

### Configure sessionStorage (Source: docs.amplify.aws gen1/javascript manage-user-session)

```typescript
import { Amplify } from "aws-amplify";
import { sessionStorage } from "aws-amplify/utils";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
      userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID!,
    },
  },
});

cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage);
```

### Hide Sign-Up Tab (Source: ui.docs.amplify.aws authenticator configuration)

```tsx
<Authenticator hideSignUp>
  {({ user }) => <>{children}</>}
</Authenticator>
```

### Get Access Token for API Requests (Source: docs.amplify.aws manage-user-session)

```typescript
import { fetchAuthSession } from "aws-amplify/auth";

const session = await fetchAuthSession();
const token = session.tokens?.accessToken?.toString();
// token is the raw JWT string — use as Bearer token
```

### Get User Groups from Access Token (Source: Amplify v6 token payload)

```typescript
import { fetchAuthSession } from "aws-amplify/auth";

const session = await fetchAuthSession();
const payload = session.tokens?.accessToken?.payload;
const groups = (payload?.["cognito:groups"] as string[]) ?? [];
const isTeam = groups.includes("WafrTeam");
```

### Force Token Refresh (for 401 retry pattern)

```typescript
import { fetchAuthSession } from "aws-amplify/auth";

// Amplify auto-refreshes on expiry; force refresh if backend returns 401
const session = await fetchAuthSession({ forceRefresh: true });
const token = session.tokens?.accessToken?.toString();
```

### Sign Out

```typescript
import { signOut } from "aws-amplify/auth";

await signOut(); // clears sessionStorage tokens; Authenticator redirects to login
```

### Authenticator Custom Header (logo above form)

```tsx
import { Authenticator, useAuthenticator } from "@aws-amplify/ui-react";
import { Settings } from "lucide-react";

<Authenticator
  hideSignUp
  components={{
    Header() {
      return (
        <div className="flex flex-col items-center gap-2 pt-6 pb-2">
          <Settings className="h-10 w-10 text-primary" />
          <h1 className="text-xl font-bold font-heading text-foreground">
            AWS Well-Architected Tool
          </h1>
          <p className="text-sm text-muted-foreground">
            Framework Review &amp; Assessment
          </p>
        </div>
      );
    },
  }}
>
  {({ signOut, user }) => <>{children}</>}
</Authenticator>
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Amplify v5 `withSSRContext` | `createServerRunner` from `@aws-amplify/adapter-nextjs` | Amplify v6 (2023) | Not needed for this project (client-only auth); do not use withSSRContext |
| `Auth.currentSession()` | `fetchAuthSession()` | Amplify v6 | New tree-shakeable import from `"aws-amplify/auth"` |
| `Auth.currentAuthenticatedUser()` | `getCurrentUser()` | Amplify v6 | Returns `{ userId, username }` |
| `Hub.dispatch` / event string | `Hub.listen("auth", callback)` | Amplify v6 | Same pattern, cleaner event names |
| `next.config.js` (CommonJS) | `next.config.ts` (TypeScript) | Next.js 15+ | This project already uses TS config |
| `publicRuntimeConfig` | Server Component + `window.__ENV` injection | Next.js 13+ | `publicRuntimeConfig` removed; NEXT_PUBLIC_* baked at build time — use ARG in Dockerfile |

**Deprecated/outdated:**
- `withSSRContext`: Removed in Amplify v6; do not use.
- `Auth.configure({})`: v5 API; use `Amplify.configure({ Auth: { Cognito: {} } })` in v6.
- `Amplify.configure(awsExports)`: Still works but `awsExports` was generated by `amplify pull`; this project uses manual config instead.

---

## Env Var Architecture for This Project

This section is critical because of the blocker about `NEXT_PUBLIC_*` vs runtime App Runner env vars.

### Current State (before Phase 4)

The Dockerfile has:
```dockerfile
ARG NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
```

App Runner `frontend-update.json` has:
```json
"RuntimeEnvironmentVariables": { "AUTH_REQUIRED": "true" },
"RuntimeEnvironmentSecrets": {
  "WAFR_COGNITO_USER_POOL_ID": "arn:...",
  "WAFR_COGNITO_CLIENT_ID": "arn:..."
}
```

### Problem

`WAFR_COGNITO_USER_POOL_ID` and `WAFR_COGNITO_CLIENT_ID` are runtime secrets, injected by App Runner at container start. They are NOT `NEXT_PUBLIC_*` variables and NOT available at `docker build` time. `Amplify.configure()` needs them on the client side, but `NEXT_PUBLIC_*` variables must be baked at build time.

### Resolution

Two valid approaches:

**Approach A (Recommended — simpler):** Add Cognito IDs as Docker build ARGs. These IDs are public (they are not secret — there is no client secret). Update the Dockerfile to accept them and the CI pipeline to pass them. Remove `WAFR_COGNITO_USER_POOL_ID` from RuntimeEnvironmentSecrets (it's only needed by the frontend; the backend uses `WAFR_COGNITO_USER_POOL_ID` from its own Secrets Manager config).

```dockerfile
# In aws-frontend/Dockerfile — add after existing ARG NEXT_PUBLIC_BACKEND_URL:
ARG NEXT_PUBLIC_COGNITO_USER_POOL_ID
ENV NEXT_PUBLIC_COGNITO_USER_POOL_ID=$NEXT_PUBLIC_COGNITO_USER_POOL_ID
ARG NEXT_PUBLIC_COGNITO_CLIENT_ID
ENV NEXT_PUBLIC_COGNITO_CLIENT_ID=$NEXT_PUBLIC_COGNITO_CLIENT_ID
```

CI build command:
```bash
docker build \
  --build-arg NEXT_PUBLIC_BACKEND_URL=https://i5kj2nnkxd.us-east-1.awsapprunner.com \
  --build-arg NEXT_PUBLIC_COGNITO_USER_POOL_ID=us-east-1_U4ugKPUrh \
  --build-arg NEXT_PUBLIC_COGNITO_CLIENT_ID=65fis729feu3lr317rm6oaue5s \
  -t 842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-frontend:latest \
  ./aws-frontend
```

**Approach B (No Dockerfile change — slightly more complex):** Keep Cognito IDs as runtime secrets. Use a server component in `layout.tsx` to read `process.env.WAFR_COGNITO_USER_POOL_ID` (available at runtime on the server) and inject them into a `<script>` tag as `window.__COGNITO_CONFIG`. Then in `amplify-provider.tsx`, read from `window.__COGNITO_CONFIG` instead of `process.env.NEXT_PUBLIC_*`.

**Recommendation: Approach A.** The values are public identifiers, not secrets. The Dockerfile already uses the same pattern for `NEXT_PUBLIC_BACKEND_URL`. This is simpler and aligns with existing project conventions.

---

## Open Questions

1. **Does the App Runner CI pipeline have access to the Cognito IDs to pass as build args?**
   - What we know: The values are in Secrets Manager (`wafr-cognito-user-pool-id`, `wafr-cognito-client-id`). The current CI for the backend reads them.
   - What's unclear: Whether the frontend CI script (which builds the Docker image) has credentials to read Secrets Manager.
   - Recommendation: Hardcode the known values (`us-east-1_U4ugKPUrh`, `65fis729feu3lr317rm6oaue5s`) as build args in the CI pipeline or Makefile, since they are public IDs. No need to read from Secrets Manager.

2. **Does `@aws-amplify/ui-react` CSS conflict with Tailwind v4?**
   - What we know: Tailwind v4 uses `@import "tailwindcss"` in globals.css; Amplify uses standard CSS custom properties. Potential conflict is at the base reset layer.
   - What's unclear: Whether importing both in the same CSS file causes visible UI regressions in the existing app.
   - Recommendation: Import Amplify CSS first in globals.css and add scoped overrides in `[data-amplify-authenticator]`. Test for regressions on the existing pages. If conflicts arise, use the `className` prop on Authenticator slots to replace Amplify's CSS entirely.

3. **Do `cognito:groups` claims appear in the access token or only the ID token?**
   - What we know: Cognito access tokens include `cognito:groups` by default in the payload. `fetchAuthSession()` exposes both `idToken` and `accessToken` payloads as parsed objects.
   - What's unclear: Whether the Phase 1 User Pool configuration explicitly added groups to the access token (some configurations only include groups in the ID token).
   - Recommendation: Verify by decoding a real access token after first login. If groups are missing from `accessToken.payload`, fall back to `idToken.payload["cognito:groups"]`.

---

## Sources

### Primary (HIGH confidence)

- `docs.amplify.aws/gen1/javascript/build-a-backend/auth/manage-user-session/` — sessionStorage configuration, `cognitoUserPoolsTokenProvider.setKeyValueStorage()` API (fetched directly)
- `ui.docs.amplify.aws/react/connected-components/authenticator/configuration` — `hideSignUp` prop, `components.Header` slot (fetched directly)
- `ui.docs.amplify.aws/react/connected-components/authenticator/customization` — CSS variable names for theming (fetched directly)
- `github.com/aws-amplify/amplify-js/issues/14600` — Next.js 16 support status; webpack works; Turbopack issue is liveness-only (fetched directly)
- `dev.classmethod.jp/articles/aws-amplify-adapter-nextjs-v1-7-0-next-js-16/` — `@aws-amplify/adapter-nextjs` v1.7.0 peer deps `next: ">=13.5.0 <17.0.0"` (fetched directly)

### Secondary (MEDIUM confidence)

- WebSearch: aws-amplify v6.16.2 is the latest version; `@aws-amplify/ui-react` v6.15.0 is the latest (multiple sources agree; npm registry)
- WebSearch + verified: NEXT_PUBLIC_* baked at build time in Next.js standalone Docker; runtime env vars not available at build time (Next.js documentation + multiple engineering blogs agree)
- `nemanjamitic.com/blog/2025-12-13-nextjs-runtime-environment-variables/` — recommended pattern for runtime env vars; Approach A (ARG at build time) is established practice

### Tertiary (LOW confidence)

- WebSearch only: `cognito:groups` in access token payload — common community assumption; should be verified with a real token after login
- WebSearch: Tailwind v4 + Amplify CSS compatibility — no authoritative source found; flagged as open question

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — package versions verified via npm, Next.js 16 support confirmed via GitHub issue and classmethod article
- Architecture: HIGH — all patterns from official Amplify docs (fetched directly); consistent with existing project structure
- Env var blocker: HIGH — resolved; Approach A is well-established and matches existing project Dockerfile pattern
- Pitfalls: MEDIUM — most verified by official docs; Tailwind/Amplify CSS conflict is speculative

**Research date:** 2026-02-28
**Valid until:** 2026-03-30 (aws-amplify v6 is active; Next.js 16 support just landed; check for patch releases before execution)
