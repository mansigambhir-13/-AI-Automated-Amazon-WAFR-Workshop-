---
phase: 03-backend-auth-and-api-security
plan: 01
subsystem: auth
tags: [jwt, cognito, pyjwt, fastapi, pydantic, auth, security]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation
    provides: Cognito User Pool (us-east-1_U4ugKPUrh), App Client (65fis729feu3lr317rm6oaue5s), WafrTeam/WafrClients groups, AUTH_REQUIRED=true on App Runner

provides:
  - wafr/auth/__init__.py — auth subpackage entry point
  - wafr/auth/jwt_middleware.py — verify_token and require_team_role FastAPI dependencies
  - All 23 API endpoints protected by Depends(verify_token) or Depends(require_team_role)
  - Pydantic input validation with max_length on all request models
  - AUTH_REQUIRED=false bypass returns synthetic WafrTeam claims for local dev

affects:
  - 03-02 (CORS lockdown — needs to know CORS must be added LAST in add_middleware after auth)
  - 03-03 (rate limiting — endpoints already have req: Request parameter added)
  - 03-04 (audit logging — request.state.claims is set by verify_token for audit middleware)

# Tech tracking
tech-stack:
  added:
    - PyJWT[crypto]>=2.11.0 (RS256 JWT decode with JWKS caching via PyJWKClient)
    - slowapi>=0.1.9 (added to requirements now; wired in Plan 03-02)
  patterns:
    - Dependency injection over BaseHTTPMiddleware for JWT auth (FastAPI idiomatic)
    - Lazy-initialized PyJWKClient singleton to avoid import-time KeyError on missing env vars
    - HTTPBearer(auto_error=False) + manual 401 raise for correct HTTP semantics
    - AUTH_REQUIRED env gate for local dev bypass (secure by default: "true")
    - request.state.claims set by verify_token for downstream middleware consumption

key-files:
  created:
    - wafr-agents/wafr/auth/__init__.py
    - wafr-agents/wafr/auth/jwt_middleware.py
  modified:
    - wafr-agents/wafr/ag_ui/server.py
    - wafr-agents/requirements.txt

key-decisions:
  - "HTTPBearer(auto_error=False) used — prevents default 403 on missing header; manual 401 raised instead per spec"
  - "Lazy PyJWKClient init via _get_jwks_client() helper — prevents KeyError at import time when env vars absent"
  - "Cognito access token validation: check client_id claim (not aud) because AWS uses non-standard claim name for access tokens"
  - "req: Request parameter added to all protected endpoints now — slowapi readiness for Plan 03-03"
  - "require_team_role used for write/destructive endpoints (POST /run, POST /process-file, DELETE /session, POST /cancel, POST /start)"
  - "verify_token used for all read endpoints — any authenticated user can read their session data"

patterns-established:
  - "Pattern: JWT dependency injection — use Depends(verify_token) not BaseHTTPMiddleware for all route protection"
  - "Pattern: Team-only guard — wrap verify_token with require_team_role sub-dependency for write endpoints"
  - "Pattern: Claims in request.state — verify_token sets request.state.claims for audit middleware access"

requirements-completed: [AUTH-01, AUTH-02, SECR-03]

# Metrics
duration: 6min
completed: 2026-02-28
---

# Phase 3 Plan 01: JWT Auth Middleware and Pydantic Input Validation Summary

**PyJWT RS256 Cognito JWT middleware wired onto all 23 FastAPI endpoints via dependency injection; Pydantic models enforce 500K char transcript size limits and typed Literal decision enum.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-28T19:05:25Z
- **Completed:** 2026-02-28T19:11:25Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `wafr/auth/` subpackage with `jwt_middleware.py` implementing PyJWT RS256 validation against Cognito JWKS endpoint, lazy-initialized singleton client, AUTH_REQUIRED dev bypass, and role-based `require_team_role` sub-dependency
- Wired `Depends(verify_token)` or `Depends(require_team_role)` onto all 23 API endpoints — only `GET /` and `GET /health` remain public
- Added `max_length` constraints to all Pydantic request models: transcript 500K chars, review IDs 128 chars, decision `Literal["APPROVE","MODIFY","REJECT"]`, feedback 10K chars

## Task Commits

Each task was committed atomically:

1. **Task 1: Create wafr/auth subpackage with JWT middleware and update requirements.txt** - `14342ee` (feat)
2. **Task 2: Wire JWT auth onto all server.py endpoints and add Pydantic input validation** - `0fa2d9a` (feat)

**Plan metadata:** (docs commit follows — see state updates)

## Files Created/Modified

- `wafr-agents/wafr/auth/__init__.py` — Auth subpackage init; exports verify_token and require_team_role
- `wafr-agents/wafr/auth/jwt_middleware.py` — PyJWKClient singleton, verify_token dep, require_team_role sub-dep
- `wafr-agents/wafr/ag_ui/server.py` — All 23 endpoints wired; all Pydantic models updated with max_length; Literal import added; req: Request added to all endpoints for slowapi readiness
- `wafr-agents/requirements.txt` — Added PyJWT[crypto]>=2.11.0 and slowapi>=0.1.9

## Decisions Made

- **HTTPBearer(auto_error=False):** FastAPI's default raises 403 on missing header; the spec requires 401. Using `auto_error=False` returns `None` when header is absent, then the dependency manually raises `HTTPException(401)`.
- **Lazy PyJWKClient initialization:** Module-level singletons evaluated at import time would raise `KeyError` if env vars not set during development. Implemented `_get_jwks_client()` with a `None` guard that creates the client on first call.
- **Cognito access token client_id claim:** AWS Cognito uses `client_id` (not `aud`) for access tokens — a deliberate AWS deviation from RFC 7519. Plan explicitly called this out and we validate accordingly.
- **req: Request added proactively:** Plan 02 (rate limiting) requires `request: Request` on all rate-limited endpoints for slowapi. Added `req: Request` to all protected endpoints now to avoid a second server.py edit.
- **Body param name preserved as `request`:** To avoid breaking 400+ lines of handler body code that uses `request.field`, the Starlette Request was added as `req` (not renamed). Body models retained `request` name.

## Deviations from Plan

None — plan executed exactly as written. All decisions were pre-specified in the plan or research doc.

## Issues Encountered

- `wafr-agents` is a git submodule within the parent repo. Git operations require running inside the submodule directory (`cd wafr-agents && git add ... && git commit ...`) rather than from the project root.

## User Setup Required

None — AUTH_REQUIRED=true is already set on App Runner from Phase 1. For local dev, engineers set `AUTH_REQUIRED=false` in their shell environment.

## Next Phase Readiness

- JWT auth foundation is complete — Plan 02 (CORS) and Plan 03 (rate limiting) can wire in their middleware knowing auth dep injection is stable
- `request.state.claims` is populated by `verify_token` — Plan 04 (audit logging) can read it from any middleware without per-endpoint changes
- `req: Request` is already present on all protected endpoints — Plan 03 (slowapi) can add `@limiter.limit()` decorators without touching signatures

---
*Phase: 03-backend-auth-and-api-security*
*Completed: 2026-02-28*
