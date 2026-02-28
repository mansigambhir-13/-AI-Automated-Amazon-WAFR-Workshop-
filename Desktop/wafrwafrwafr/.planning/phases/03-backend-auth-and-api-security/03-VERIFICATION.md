---
phase: 03-backend-auth-and-api-security
verified: 2026-02-28T21:15:00Z
status: passed
score: 5/5 must-haves verified (ROADMAP Success Criteria)
re_verification: false
---

# Phase 3: Backend Auth and API Security Verification Report

**Phase Goal:** Every FastAPI endpoint is protected by Cognito JWT authentication, the API accepts requests only from the frontend domain, and all inputs are validated and rate-limited.
**Verified:** 2026-02-28T21:15:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A curl request to any API endpoint without a valid Cognito access token receives 401 Unauthorized (not 403, not 200) | VERIFIED | `verify_token` in `jwt_middleware.py` raises `HTTPException(status_code=401, detail="Missing or invalid authentication token")` when credentials are None or decode fails. `HTTPBearer(auto_error=False)` prevents FastAPI's default 403. All 23 non-public endpoints use `Depends(verify_token)` or `Depends(require_team_role)` (which chains through `verify_token`). Only `GET /` and `GET /health` are public. |
| 2 | A request from a non-frontend origin receives a CORS rejection; a request from the frontend App Runner domain succeeds | VERIFIED | `cors.py` `get_cors_origins()` returns `["https://3fhp6mfj7u.us-east-1.awsapprunner.com", "http://localhost:3000"]` by default (configurable via `WAFR_CORS_ORIGINS` env var). `server.py` line 83-91 registers `CORSMiddleware` with `allow_origins=get_cors_origins()`. No `allow_origins=["*"]` found in server.py (grep returned 0 matches). CORSMiddleware is the last `add_middleware()` call (outermost -- executes first), ensuring 401/429 responses carry CORS headers. |
| 3 | Sending more than 10 requests per minute to `POST /api/wafr/run` from a single IP returns 429 Too Many Requests on the excess requests | VERIFIED | `rate_limit.py` creates `Limiter(key_func=_get_rate_limit_key, default_limits=["200/minute"])` with hybrid per-user/per-IP key. `server.py` line 433: `@limiter.limit("10/minute")` on `POST /api/wafr/run`. 8 total `@limiter.limit()` decorators: 3 expensive-tier (10/min on `/run`, `/process-file`, `/start`) + 5 standard-tier (60/min on `/decision`, `/batch-approve`, `/finalize`, `/cancel`, DELETE `/session`). `SlowAPIMiddleware` registered at line 76. slowapi's built-in handler includes `Retry-After` header on 429 responses. |
| 4 | A transcript body exceeding 500,000 characters is rejected with a 422 Validation Error before reaching the AI pipeline | VERIFIED | `RunWAFRRequest.transcript` has `max_length=500_000` (line 324). `StartJobRequest.transcript` has `max_length=500_000` (line 2451). Additional `max_length` constraints on: `client_name` (200), `file_path` (1024), `review_id` (128), `reviewer_id` (128), `modified_answer` (500K), `feedback` (10K), `approver_id` (128). `ReviewDecisionRequest.decision` uses `Literal["APPROVE", "MODIFY", "REJECT"]` type-safe enum. Pydantic v2 returns 422 automatically when constraints are violated. |
| 5 | After a team user runs an assessment, an audit log entry exists in `wafr-audit-log` with user ID, session ID, action type, and timestamp | VERIFIED | `AuditMiddleware` (pure-ASGI class, line 67 in server.py) captures metadata for ALL authenticated requests via `run_in_executor`. Per-endpoint `BackgroundTasks` on 7 write endpoints add request body. `POST /api/wafr/run` specifically calls `write_audit_entry` (line 448-457) with `user_id=claims.get("sub")`, `session_id=body.thread_id`, `action_type="wafr_run"`, and timestamp derived in `write_audit_entry()` via `datetime.now(timezone.utc).isoformat()`. DynamoDB key schema uses PK=`user_id`, SK=`timestamp_session_id` (underscore separator matching Phase 1 spec). Transcript excluded from audit body; `transcript_length` captured instead (lines 446-447). |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `wafr-agents/wafr/auth/__init__.py` | Auth subpackage exports | VERIFIED | 15 lines. Exports `verify_token`, `require_team_role`, `get_cors_origins`, `CORS_MAX_AGE`, `limiter`, `write_audit_entry`, `AuditMiddleware` with `__all__` list. |
| `wafr-agents/wafr/auth/jwt_middleware.py` | verify_token and require_team_role FastAPI dependencies | VERIFIED | 169 lines. Lazy `PyJWKClient` singleton via `_get_jwks_client()`, `HTTPBearer(auto_error=False)`, RS256 decode with issuer/exp/sub/token_use validation, `client_id` check (Cognito access token quirk), `request.state.claims` assignment, `AUTH_REQUIRED` env var bypass with synthetic dev claims, generic 401 on all failures. |
| `wafr-agents/wafr/auth/cors.py` | CORS origin parsing from WAFR_CORS_ORIGINS env var | VERIFIED | 67 lines. `get_cors_origins()` reads env var with defaults, strips whitespace, filters empties. `CORS_MAX_AGE=3600`. `SSE_ORIGIN_REGEX` exported. `get_sse_cors_origins()` combines standard + SSE-specific origins. |
| `wafr-agents/wafr/auth/rate_limit.py` | slowapi Limiter singleton with hybrid key function | VERIFIED | 81 lines. Hybrid `_get_rate_limit_key` extracts JWT sub without verification for per-user bucketing, falls back to IP. `Limiter(default_limits=["200/minute"])`. Re-exports `SlowAPIMiddleware`, `RateLimitExceeded`, `_rate_limit_exceeded_handler`. |
| `wafr-agents/wafr/auth/audit.py` | write_audit_entry() and AuditMiddleware ASGI class | VERIFIED | 211 lines. Lazy boto3 singleton via `_get_audit_table()`. `write_audit_entry()` is synchronous with fire-and-forget try/except (never raises). `AuditMiddleware` is pure-ASGI class (not BaseHTTPMiddleware), wraps `send()` to capture status, uses `run_in_executor` for non-blocking DynamoDB writes, logs `failed_auth` for 401 responses with user_id="anonymous", skips public endpoints. |
| `wafr-agents/wafr/ag_ui/server.py` | All middleware wired, all endpoints protected | VERIFIED | Imports all auth modules (lines 46-49). Middleware stack correct: AuditMiddleware (innermost, line 67), SlowAPIMiddleware (line 76), CORSMiddleware (outermost, lines 83-91). 23 endpoints protected (18 verify_token + 5 require_team_role). 2 public (root, health). 8 rate limit decorators. 7 per-endpoint audit writes. |
| `wafr-agents/requirements.txt` | PyJWT[crypto] and slowapi added | VERIFIED | `PyJWT[crypto]>=2.11.0` at line 33. `slowapi>=0.1.9` at line 34. Both under "Security -- JWT Authentication and Rate Limiting (Phase 3)" section header. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `server.py` | `jwt_middleware.py` | `from wafr.auth.jwt_middleware import verify_token, require_team_role` | WIRED | Line 46. 23 usages across endpoints. |
| `server.py` | `cors.py` | `from wafr.auth.cors import get_cors_origins, CORS_MAX_AGE` | WIRED | Line 47. Used in CORSMiddleware config (line 85, 90). |
| `server.py` | `rate_limit.py` | `from wafr.auth.rate_limit import limiter, SlowAPIMiddleware, RateLimitExceeded, _rate_limit_exceeded_handler` | WIRED | Line 48. limiter assigned to app.state (line 74), exception handler registered (line 75), SlowAPIMiddleware added (line 76), 8 `@limiter.limit()` decorators. |
| `server.py` | `audit.py` | `from wafr.auth.audit import AuditMiddleware, write_audit_entry` | WIRED | Line 49. AuditMiddleware registered (line 67). write_audit_entry called in 7 BackgroundTasks. |
| `jwt_middleware.py` | Cognito JWKS endpoint | `PyJWKClient` singleton with lazy init | WIRED | `_get_jwks_client()` creates `jwt.PyJWKClient(jwks_url)` on first call. JWKS URL built from `WAFR_COGNITO_USER_POOL_ID` env var. |
| `audit.py` | `wafr-audit-log` DynamoDB table | `boto3 Table.put_item()` | WIRED | `_get_audit_table()` creates `boto3.resource("dynamodb").Table(table_name)`. `put_item(Item=item)` at line 96. |
| `audit.py` | `request.state.claims` | Reads claims set by verify_token | WIRED | `AuditMiddleware.__call__` reads `getattr(request.state, "claims", None)` at line 148. verify_token sets `request.state.claims` at lines 95 and 134 of jwt_middleware.py. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| AUTH-01 | 03-01 | AWS Cognito User Pool created with team and client user groups | SATISFIED | Phase 1 created the pool. Phase 3 validates tokens against it via `jwt_middleware.py` with correct pool ID and client ID. |
| AUTH-02 | 03-01 | Backend validates Cognito JWT access tokens on all API endpoints via FastAPI middleware | SATISFIED | `verify_token` dependency on all 23 non-public endpoints. RS256 validation with issuer, expiry, token_use, and client_id checks. `require_team_role` sub-dependency for WafrTeam-only write endpoints. |
| SECR-01 | 03-02 | CORS is locked down to only allow requests from the frontend App Runner domain | SATISFIED | `CORSMiddleware` with `allow_origins=get_cors_origins()` (explicit list, no wildcard). Configurable via `WAFR_CORS_ORIGINS` env var. Defaults include App Runner frontend and localhost:3000. |
| SECR-02 | 03-02 | Rate limiting is enforced per-user/IP on all API endpoints via slowapi | SATISFIED | `SlowAPIMiddleware` registered. 3 expensive-tier (10/min), 5 standard-tier (60/min), all GET endpoints covered by default 200/min. Hybrid per-user/per-IP key function. |
| SECR-03 | 03-01 | All API inputs are validated with Pydantic models including transcript size limits | SATISFIED | `max_length=500_000` on transcript fields. Additional constraints on review_id (128), client_name (200), file_path (1024), feedback (10K). Literal enum for decision field. |
| SECR-04 | 03-03 | Audit trail logs who ran what assessment, when, with what transcript | SATISFIED | `AuditMiddleware` covers all authenticated requests. 7 write endpoints log request body via BackgroundTasks. Failed auth logged with IP. DynamoDB `put_item` with correct key schema. Fire-and-forget design. |

**Note on user-supplied requirement IDs:** The user's prompt listed "AUTH-03: Role-based access (WafrTeam vs WafrClients)" and "AUTH-04: Failed auth returns 401, no token details leaked" as Phase 3 requirements. Per REQUIREMENTS.md, AUTH-03 is "Frontend provides login, signup, and password reset UI via Amplify" (Phase 4) and AUTH-04 is "Team users can create/view/manage all assessments; client users can only view their own" (Phase 4). The described behaviors (role extraction and generic 401) are implemented as part of AUTH-02's `verify_token`/`require_team_role` and are verified under that requirement. AUTH-03 and AUTH-04 are not in scope for Phase 3.

**Note on SECR-03 mapping:** The user listed "SECR-03: Auth bypass disabled in production (AUTH_REQUIRED=true)". Per REQUIREMENTS.md, SECR-03 is "All API inputs are validated with Pydantic models including transcript size limits". The AUTH_REQUIRED=true behavior is verified as part of AUTH-02 (`verify_token` checks `AUTH_REQUIRED` env var, defaults to "true" -- secure by default).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | - | - | - | No TODOs, FIXMEs, placeholders, or stub implementations found in any auth module or server.py auth-related code |

### Human Verification Required

### 1. JWT Token Validation End-to-End

**Test:** Send a curl request to `POST /api/wafr/run` on the live App Runner backend without an Authorization header. Then send one with a valid Cognito access token.
**Expected:** First request returns `{"detail": "Missing or invalid authentication token"}` with HTTP 401. Second request proceeds to the assessment pipeline.
**Why human:** Requires a live Cognito token and network access to the deployed backend.

### 2. CORS Rejection from Unauthorized Origin

**Test:** From a browser console on a non-allowed domain, issue a `fetch()` to the backend API. Then from the frontend App Runner URL, issue the same request.
**Expected:** First request is blocked by browser CORS policy (no `Access-Control-Allow-Origin` header matching the requesting origin). Second succeeds with CORS headers.
**Why human:** CORS enforcement is browser-side; cannot verify programmatically without a browser context.

### 3. Rate Limiting 429 Response

**Test:** Send 11 rapid `POST /api/wafr/run` requests within 60 seconds from the same IP/user.
**Expected:** First 10 succeed (or return expected auth/processing responses). 11th returns HTTP 429 with `Retry-After` header.
**Why human:** Requires real HTTP traffic with timing control against the live endpoint.

### 4. Audit Trail DynamoDB Entries

**Test:** After running an authenticated assessment, query the `wafr-audit-log` DynamoDB table for the user's `user_id` partition key.
**Expected:** At least two entries: one from AuditMiddleware (action_type="api_call", no request_body) and one from BackgroundTasks (action_type="wafr_run", with request_body including transcript_length field but no transcript content).
**Why human:** Requires DynamoDB access to verify actual written items. The write path uses boto3 against a real AWS table.

### 5. AUTH_REQUIRED=false Dev Bypass

**Test:** Set `AUTH_REQUIRED=false` and send a request without an Authorization header to a protected endpoint.
**Expected:** Request succeeds with synthetic claims `{"sub": "dev-user", "cognito:groups": ["WafrTeam"]}`.
**Why human:** Requires running the server locally with specific env var configuration.

### Gaps Summary

No gaps found. All 5 ROADMAP Success Criteria are verified through code inspection. All 6 requirements (AUTH-01, AUTH-02, SECR-01 through SECR-04) have implementation evidence. All 7 artifacts exist, are substantive (not stubs), and are wired into the application. All 7 key links are connected and functional. No anti-patterns detected.

The middleware stack ordering is correct (AuditMiddleware innermost, SlowAPIMiddleware middle, CORSMiddleware outermost), ensuring CORS headers appear on all error responses and audit captures final response status codes.

The 6 commits (14342ee, 0fa2d9a, c665ec4, ac05ea9, 882464c, 1ba2d94) all exist in the wafr-agents submodule git history and match the claimed summaries.

---

_Verified: 2026-02-28T21:15:00Z_
_Verifier: Claude (gsd-verifier)_
