---
phase: 03-backend-auth-and-api-security
plan: 02
subsystem: auth
tags: [cors, rate-limiting, slowapi, fastapi, security, middleware]

# Dependency graph
requires:
  - phase: 03-01
    provides: wafr/auth/__init__.py, jwt_middleware.py, all 23 endpoints with req:Request param

provides:
  - wafr/auth/cors.py — get_cors_origins() from WAFR_CORS_ORIGINS env var; CORS_MAX_AGE; SSE_ORIGIN_REGEX
  - wafr/auth/rate_limit.py — slowapi Limiter singleton with hybrid per-user/per-IP key_func
  - wafr/ag_ui/server.py — explicit CORS origins, SlowAPIMiddleware, 8 rate-limit decorators

affects:
  - 03-03 (audit logging — CORS + rate limiting middleware stack finalized; no further add_middleware ordering changes expected)
  - 03-04+ (CORS headers on all responses including future 401/429 confirmed working)

# Tech tracking
tech-stack:
  added:
    - slowapi>=0.1.9 wired (was in requirements.txt from 03-01; now active in server.py)
  patterns:
    - CORSMiddleware registered last (outermost) so all error responses carry CORS headers
    - SlowAPIMiddleware registered before CORS (inside CORS in execution order)
    - Hybrid per-user/per-IP rate limit key: JWT sub when available, IP fallback
    - Limiter.limit() decorator BELOW route decorator (required by slowapi)
    - Body model param renamed to 'body', Starlette Request named 'request' (slowapi requirement)

key-files:
  created:
    - wafr-agents/wafr/auth/cors.py
    - wafr-agents/wafr/auth/rate_limit.py
  modified:
    - wafr-agents/wafr/ag_ui/server.py
    - wafr-agents/wafr/auth/__init__.py

key-decisions:
  - "SlowAPIMiddleware registered before CORSMiddleware in source order — CORS executes first on requests (outermost), ensuring 429 responses carry Access-Control-Allow-Origin"
  - "Body Pydantic models renamed to 'body' param; Starlette Request must be named 'request' — slowapi parameter detection uses inspect.signature and checks name == 'request'"
  - "3 expensive-tier (10/min) + 5 standard-tier (60/min) rate-limited endpoints; GET endpoints use default_limits=200/min; SSE/WebSocket excluded"
  - "SSE_ORIGIN_REGEX = r'https://.*\\.us-east-1\\.awsapprunner\\.com' exported for future SSE-specific CORS config"

requirements-completed: [SECR-01, SECR-02]

# Metrics
duration: 5min
completed: 2026-02-28
---

# Phase 3 Plan 02: CORS Lockdown and Rate Limiting Summary

**Explicit CORS origins from env var replacing wildcard, slowapi tiered rate limiting on all write endpoints, SlowAPIMiddleware + CORSMiddleware registered in correct stack order so 401/429 responses carry CORS headers.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-28T13:42:36Z
- **Completed:** 2026-02-28T13:48:32Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `wafr/auth/cors.py` with `get_cors_origins()` reading `WAFR_CORS_ORIGINS` env var (defaults to App Runner frontend + localhost:3000), `CORS_MAX_AGE=3600`, `SSE_ORIGIN_REGEX` for future SSE permissiveness, and `get_sse_cors_origins()` combining standard + `WAFR_SSE_CORS_ORIGINS`
- Created `wafr/auth/rate_limit.py` with hybrid per-user/per-IP `_get_rate_limit_key()` (JWT sub when present, IP fallback), `Limiter` singleton with `default_limits=["200/minute"]`, and re-exports of slowapi helpers
- Replaced `allow_origins=["*"]` + `allow_credentials=True` (browser-rejected combination per Pitfall 6) with explicit `get_cors_origins()` list; added `expose_headers`, `max_age`
- Registered `SlowAPIMiddleware` before `CORSMiddleware` so CORS is outermost (executes first on requests, last on responses — 429/401 errors carry CORS headers)
- Added 8 rate-limit decorators: 3 expensive-tier (`10/minute`) on `/run`, `/process-file`, `/start`; 5 standard-tier (`60/minute`) on `/decision`, `/batch-approve`, `/finalize`, `/cancel`, `/session DELETE`
- Updated `wafr/auth/__init__.py` to export `get_cors_origins`, `CORS_MAX_AGE`, `limiter`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CORS and rate limiting modules** - `c665ec4` (feat)
2. **Task 2: Replace CORS wildcard and wire rate limiting into server.py** - `ac05ea9` (feat)

## Files Created/Modified

- `wafr-agents/wafr/auth/cors.py` — CORS origin parser; CORS_MAX_AGE=3600; SSE regex; get_sse_cors_origins()
- `wafr-agents/wafr/auth/rate_limit.py` — slowapi Limiter singleton; hybrid key_func; re-exports
- `wafr-agents/wafr/ag_ui/server.py` — CORS wildcard replaced; SlowAPIMiddleware + CORSMiddleware registered in correct order; 8 @limiter.limit() decorators; body model params renamed
- `wafr-agents/wafr/auth/__init__.py` — Added cors and rate_limit exports

## Decisions Made

- **SlowAPIMiddleware before CORSMiddleware in source order:** Starlette/FastAPI builds middleware as a LIFO stack — the last `add_middleware()` call wraps all previous middleware. CORS registered last becomes outermost (first to execute on inbound, last on outbound). This ensures Access-Control-Allow-Origin headers appear on ALL responses including 401 from JWT auth and 429 from rate limiter.
- **Slowapi requires parameter named `request`:** At decoration time, slowapi inspects the function signature and raises `Exception('No "request" or "websocket" argument')` if no parameter named `request` is found. Plan 03-01 named the Starlette Request `req` to avoid collision with Pydantic body model named `request`. Fix: rename Pydantic body params to `body`, rename Starlette Request to `request` on all rate-limited endpoints.
- **8 rate-limited endpoints confirmed:** 3 expensive (10/min): `/run`, `/process-file`, `/start`; 5 standard (60/min): `/decision`, `/batch-approve`, `/finalize`, `/cancel`, DELETE `/session`. GET endpoints use `default_limits=["200/minute"]` — no decorator needed. SSE and WebSocket excluded per spec.
- **SSE_ORIGIN_REGEX documented but not wired yet:** The regex `r"https://.*\.us-east-1\.awsapprunner\.com"` is exported from `cors.py` for future use when SSE endpoints need `allow_origin_regex`. Not wired into `CORSMiddleware` on the main app — SSE routes currently use the same origins as all others.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed slowapi parameter detection failure on rate-limited endpoints**
- **Found during:** Task 2 verification (`python3 -c "from wafr.ag_ui.server import app"`)
- **Issue:** slowapi's `@limiter.limit()` decorator inspects the function signature at decoration time and raises `Exception('No "request" or "websocket" argument on function')` if no parameter named exactly `request` is found. Plan 03-01 had added `req: Request` (named `req`) to all endpoints to avoid collision with the existing `request: RunWAFRRequest` body model parameter.
- **Fix:** Renamed Pydantic body model parameters from `request` to `body` on all 6 rate-limited endpoints with body models. Renamed Starlette Request parameter from `req` to `request` on all 8 rate-limited endpoints. Updated all internal references from `request.field` to `body.field` inside those functions.
- **Files modified:** `wafr-agents/wafr/ag_ui/server.py`
- **Commit:** `ac05ea9` (included in Task 2 commit)

## Next Phase Readiness

- CORS is fully locked down — Plan 03-03 (audit logging) can add its middleware (pure-ASGI class) registering before `SlowAPIMiddleware` (innermost) without any CORS ordering concerns
- `request.state.claims` is available to any future middleware from `verify_token` dependency
- All 8 rate-limited endpoints confirmed compiling with correct slowapi signature detection

---
*Phase: 03-backend-auth-and-api-security*
*Completed: 2026-02-28*
