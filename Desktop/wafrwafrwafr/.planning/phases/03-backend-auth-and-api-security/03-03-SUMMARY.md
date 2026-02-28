---
phase: 03-backend-auth-and-api-security
plan: 03
subsystem: auth
tags: [audit, dynamodb, boto3, fastapi, asgi, middleware, security, compliance]

# Dependency graph
requires:
  - phase: 03-01
    provides: verify_token dependency that sets request.state.claims; all 23 endpoints wired
  - phase: 03-02
    provides: SlowAPIMiddleware + CORSMiddleware registered; middleware stack ordering finalized
  - phase: 01-infrastructure-foundation
    provides: wafr-audit-log DynamoDB table (PK user_id, SK timestamp_session_id), boto3 in requirements

provides:
  - wafr/auth/audit.py — write_audit_entry() fire-and-forget DynamoDB writer and AuditMiddleware pure-ASGI class
  - All authenticated API calls produce audit entries in wafr-audit-log DynamoDB table (via AuditMiddleware)
  - 7 write endpoints additionally log full request body (via BackgroundTasks per-endpoint)
  - Failed auth attempts (401 responses) are logged with IP and timestamp
  - Transcript content excluded from audit body; transcript_length field captured instead

affects:
  - Phase 4 (frontend auth) — no direct code link, but audit logging is now active for all Phase 4 API calls
  - Future compliance/forensics — wafr-audit-log table will grow with every API call

# Tech tracking
tech-stack:
  added:
    - No new dependencies (boto3 already in requirements.txt from Phase 1)
  patterns:
    - Pure-ASGI middleware class for cross-cutting concerns (not BaseHTTPMiddleware)
    - asyncio.get_running_loop().run_in_executor() for non-blocking sync boto3 calls in ASGI middleware
    - Lazy singleton pattern for boto3 resource/Table (prevents import-time errors when env vars absent)
    - Fire-and-forget audit writes: all exceptions caught and logged as warnings, never raised
    - Per-endpoint BackgroundTasks for request body logging on write endpoints
    - Transcript content excluded from audit, length captured (avoids 500KB+ DynamoDB item limit risk)

key-files:
  created:
    - wafr-agents/wafr/auth/audit.py
  modified:
    - wafr-agents/wafr/ag_ui/server.py
    - wafr-agents/wafr/auth/__init__.py

key-decisions:
  - "asyncio.get_running_loop() used (not get_event_loop()) — get_event_loop() is deprecated and emits DeprecationWarning in Python 3.10+; get_running_loop() raises RuntimeError in non-async contexts which is explicitly handled"
  - "AuditMiddleware is pure-ASGI class (not BaseHTTPMiddleware) — avoids ContextVar propagation bugs and 20-30% latency overhead; compatible with add_middleware()"
  - "Lazy boto3 singleton via _get_audit_table() — prevents import-time failures when WAFR_DYNAMO_AUDIT_TABLE or AWS credentials absent in local dev"
  - "Transcript excluded from per-endpoint audit body (length captured instead) — avoids DynamoDB 400KB item size limit for /run and /start endpoints"
  - "AuditMiddleware registered before SlowAPIMiddleware (innermost) — captures response status AFTER all middleware processing; stack: AuditMiddleware -> SlowAPIMiddleware -> CORSMiddleware"
  - "Failed auth (401 with no claims) logged with user_id=anonymous — enables IP-based forensics for brute-force detection"

patterns-established:
  - "Pattern: Pure-ASGI audit middleware — __init__(app) + async __call__(scope, receive, send) wraps send() to capture status code, then fires background DynamoDB write"
  - "Pattern: Dual audit layering — middleware handles metadata for ALL 23+ endpoints; BackgroundTasks adds request body for 7 write endpoints only"
  - "Pattern: run_in_executor for sync AWS SDK in async middleware — loop.run_in_executor(None, sync_fn, *args) is the correct pattern for boto3 inside ASGI context"

requirements-completed: [SECR-04]

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 3 Plan 03: Audit Trail Logging Summary

**Pure-ASGI AuditMiddleware + BackgroundTasks fire-and-forget DynamoDB writes cover all 23 authenticated endpoints; 7 write endpoints additionally log request body; failed auth (401) logged with IP; transcript content excluded from audit items.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-28T13:52:33Z
- **Completed:** 2026-02-28T13:55:28Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `wafr/auth/audit.py` with `write_audit_entry()` synchronous DynamoDB writer using lazy-init boto3 singleton and `AuditMiddleware` pure-ASGI class; DynamoDB key schema matches Phase 1 spec (PK=user_id, SK=timestamp_session_id with underscore separator)
- Registered AuditMiddleware as innermost middleware in server.py (before SlowAPIMiddleware, inside CORS); all authenticated API calls now produce audit entries via response status code capture
- Added per-endpoint BackgroundTasks audit writes on 7 write endpoints with full request body; transcript content excluded from body on `/run`, `/start` (transcript_length field added instead)
- Updated `wafr/auth/__init__.py` to export `write_audit_entry` and `AuditMiddleware`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create audit logging module with DynamoDB writer and ASGI middleware** - `882464c` (feat)
2. **Task 2: Wire audit middleware and per-endpoint body logging into server.py** - `1ba2d94` (feat)

**Plan metadata:** (docs commit follows — see state updates)

## Files Created/Modified

- `wafr-agents/wafr/auth/audit.py` — `write_audit_entry()` sync DynamoDB writer with fire-and-forget; `AuditMiddleware` pure-ASGI class with run_in_executor for non-blocking writes; failed_auth logging for 401 responses
- `wafr-agents/wafr/ag_ui/server.py` — AuditMiddleware registered first (innermost); BackgroundTasks audit writes on 7 write endpoints; transcript excluded from audit body
- `wafr-agents/wafr/auth/__init__.py` — Added exports for write_audit_entry and AuditMiddleware

## Decisions Made

- **asyncio.get_running_loop() over get_event_loop():** Plan objective note specifically flagged this. `get_event_loop()` is deprecated in Python 3.10+ (emits DeprecationWarning) and will be removed. `get_running_loop()` raises `RuntimeError` when no loop is running (test context), which is explicitly caught and handled with a synchronous fallback call.
- **Pure-ASGI class over BaseHTTPMiddleware:** BaseHTTPMiddleware creates ~7 intermediate objects per request and has known `ContextVar` propagation bugs with asyncio. Pure-ASGI class with `__call__(scope, receive, send)` is the Starlette/FastAPI recommended approach for audit middleware.
- **Lazy boto3 singleton:** `_get_audit_table()` helper creates the DynamoDB resource + Table on first call. Prevents `KeyError` or `NoRegionError` at import time when `WAFR_DYNAMO_AUDIT_TABLE` or AWS credentials are absent during local dev or test imports.
- **Transcript excluded from audit body:** `/api/wafr/run` and `/start` accept up to 500K char transcripts. DynamoDB items have a 400KB limit; storing the transcript in the audit entry would cause write failures. `transcript_length` field provides forensic value without the size risk.
- **Dual audit layering (middleware + BackgroundTasks):** The middleware captures metadata (user_id, path, method, IP, status) for ALL 25+ endpoints — no per-endpoint changes required. BackgroundTasks on 7 write endpoints add the request body. This avoids body buffering in the middleware (which would break SSE streaming for `/run`).

## Deviations from Plan

None — plan executed exactly as written. The `asyncio.get_running_loop()` requirement was noted in the task objective and implemented correctly. All design decisions were pre-specified in the plan and research doc.

## Issues Encountered

None.

## User Setup Required

None — `wafr-audit-log` DynamoDB table was provisioned in Phase 1 with the correct key schema. `WAFR_DYNAMO_AUDIT_TABLE` env var defaults to `"wafr-audit-log"`. No new AWS infrastructure required.

## Next Phase Readiness

- Audit trail is complete — Phase 3 (backend auth and API security) is fully implemented: JWT auth (Plan 01), CORS + rate limiting (Plan 02), audit logging (Plan 03)
- Phase 4 (frontend Cognito auth) can proceed; all API calls it makes will automatically produce audit entries
- `write_audit_entry` and `AuditMiddleware` are exported from `wafr.auth` for reuse in any future endpoint or middleware

---
*Phase: 03-backend-auth-and-api-security*
*Completed: 2026-02-28*
