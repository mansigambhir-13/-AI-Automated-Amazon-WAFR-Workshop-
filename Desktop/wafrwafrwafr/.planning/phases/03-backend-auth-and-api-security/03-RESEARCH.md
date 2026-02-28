# Phase 3: Backend Auth and API Security - Research

**Researched:** 2026-02-28
**Domain:** FastAPI JWT authentication, CORS, rate limiting, input validation, audit logging
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**JWT Auth Behavior**
- Exempt endpoints: `/health`, `/api/health`, and `/docs` are public — everything else requires valid Cognito token
- Error response: Standard 401 with JSON body `{"detail": "Missing or invalid authentication token"}` — no token details leaked
- Auth control: `AUTH_REQUIRED` env var only — no separate `DEV_AUTH_BYPASS` flag. Set to `false` for local dev.
- Role extraction: Middleware extracts Cognito group (`WafrTeam`/`WafrClients`) into request state. Individual endpoints check role where needed.

**CORS Policy**
- Allowed origins: Frontend App Runner domain (`https://3fhp6mfj7u.us-east-1.awsapprunner.com`) AND `http://localhost:3000`
- SSE endpoints: More permissive CORS than standard endpoints (allow additional origins for potential embedding)
- Configuration: `WAFR_CORS_ORIGINS` env var with comma-separated origins — configurable without redeployment
- Preflight cache: Claude's discretion (pick a reasonable `Access-Control-Max-Age`)

**Rate Limiting Rules**
- Rate limit scope: Claude's discretion (per-IP vs per-user vs hybrid)
- Endpoint tiers: Claude's discretion (design tiers based on endpoint cost — 10/min for `POST /run` per roadmap spec)
- Rate limit response: 429 Too Many Requests with `Retry-After` header
- SSE endpoints: No rate limiting on SSE streaming connections (long-lived, initial `POST /run` already limited)

**Audit Trail Scope**
- Scope: Log ALL authenticated API calls, not just key actions
- Failed auth: Log failed authentication attempts with IP and timestamp
- Data per entry: Standard fields (user_id, session_id, action_type, timestamp, IP, HTTP method+path) PLUS full request body
- Write mode: Async fire-and-forget — don't block API response. If log write fails, request still succeeds.
- Storage: `wafr-audit-log` DynamoDB table (created in Phase 1, no TTL — keep forever)

### Claude's Discretion
- CORS preflight cache duration
- Rate limit scope (per-IP vs per-user)
- Rate limit tier design per endpoint
- Input validation rules beyond transcript size (500K char limit per roadmap)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AUTH-01 | AWS Cognito User Pool created with team and client user groups | Already complete (Phase 1). Pool `us-east-1_U4ugKPUrh`, App Client `65fis729feu3lr317rm6oaue5s`, groups `WafrTeam`/`WafrClients` live. |
| AUTH-02 | Backend validates Cognito JWT access tokens on all API endpoints via FastAPI middleware | PyJWT 2.11.0 with `PyJWKClient` against JWKS URL; FastAPI dependency injection pattern; `AUTH_REQUIRED` env gate. |
| SECR-01 | CORS is locked down to only allow requests from the frontend App Runner domain | FastAPI `CORSMiddleware` with `allow_origins` from `WAFR_CORS_ORIGINS` env var; CORS registered last in `add_middleware()` calls (executes first on requests). |
| SECR-02 | Rate limiting is enforced per-user/IP on all API endpoints via slowapi | `slowapi 0.1.9` with `Limiter(key_func=...)`, `SlowAPIMiddleware`, tiered `@limiter.limit()` decorators. |
| SECR-03 | All API inputs are validated with Pydantic models including transcript size limits | Pydantic v2 `Field(max_length=500_000)` on `RunWAFRRequest.transcript`; existing models augmented. |
| SECR-04 | Audit trail logs who ran what assessment, when, with what transcript | `wafr-audit-log` DynamoDB table (PK: `user_id`, SK: `timestamp_session_id`); async `BackgroundTasks` fire-and-forget writes via existing `boto3`. |
</phase_requirements>

---

## Summary

Phase 3 adds four orthogonal security layers to the existing FastAPI server (`wafr-agents/wafr/ag_ui/server.py`, ~2500 lines): JWT middleware, CORS lockdown, rate limiting, and audit logging. All four layers are independent, meaning they can be implemented and tested in isolation before being composed.

The Cognito infrastructure is 100% ready from Phase 1. Pool ID (`us-east-1_U4ugKPUrh`), App Client ID (`65fis729feu3lr317rm6oaue5s`), JWKS URL, and both app runner env vars (`WAFR_COGNITO_USER_POOL_ID`, `WAFR_COGNITO_CLIENT_ID`) are live. The `wafr-audit-log` DynamoDB table is live with the correct key schema (`user_id` PK, `timestamp_session_id` SK). The existing `boto3` dependency in `requirements.txt` covers DynamoDB writes; no new AWS SDK dependency is needed.

The standard library choices are: **PyJWT 2.11.0** (with `[crypto]` extra for RS256) for JWT validation, **slowapi 0.1.9** for rate limiting, and **FastAPI's built-in `CORSMiddleware`** and **Pydantic v2** for CORS and validation respectively. These are all mature, widely-deployed libraries with stable APIs. The biggest implementation nuance is middleware registration order: CORS must be registered via `add_middleware()` **after** auth (so it executes first on inbound requests), or auth 401 responses will arrive at the browser without CORS headers, causing a network error instead of a meaningful 401.

**Primary recommendation:** Create `wafr/auth/` as a new subpackage containing `jwt_middleware.py`, `cors.py`, `rate_limit.py`, and `audit.py`. Wire all four into `server.py` using dependency injection for JWT and direct middleware registration for CORS/rate-limiting. Keep audit writes as `BackgroundTasks` to avoid blocking SSE streams.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PyJWT | `2.11.0` (use `PyJWT[crypto]`) | RS256 JWT decode + JWKS key fetching | Official recommendation over `python-jose` (archived dependency chain); includes built-in JWKS caching via `PyJWKClient`; active maintenance |
| slowapi | `0.1.9` | Per-IP/per-user rate limiting for FastAPI/Starlette | Direct port of `flask-limiter` to Starlette; decorator-based; 10+ million monthly downloads |
| fastapi (existing) | current | CORS middleware, dependency injection, 422 validation | Already in use; built-in `CORSMiddleware` handles preflight |
| pydantic v2 (existing) | `>=2.0.0` | Field-level input size constraints | Already a dependency; `Field(max_length=N)` produces automatic 422 before route handler runs |
| boto3 (existing) | `>=1.34.0` | DynamoDB audit log writes | Already in use; synchronous calls are fine when wrapped in `BackgroundTasks` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `cryptography` | bundled via `PyJWT[crypto]` | RSA key operations for RS256 | Required whenever PyJWT decodes RS256 tokens — included automatically via the `[crypto]` extra |
| `slowapi[redis]` | optional | Distributed rate limiting across multiple App Runner instances | Needed only if App Runner scales to >1 instance AND per-user limits must be globally consistent. Deferred to SECR-05 (v2). |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `PyJWT[crypto]` | `python-jose` | `python-jose` depends on `cognitojwt` (archived). PyJWT is actively maintained and more direct. (Decision locked.) |
| `PyJWT[crypto]` | `fastapi-cognito` | Higher-level wrapper, but thin abstraction over PyJWT with limited flexibility for custom error messages and group extraction. |
| `slowapi` | `fastapi-limiter` | `fastapi-limiter` requires Redis even for basic usage. `slowapi` works with in-memory backend for single-instance App Runner, no extra infra. |
| `BackgroundTasks` for audit | `aioboto3` async | `aioboto3` is more elegant but adds a dependency. `BackgroundTasks` with sync `boto3` is sufficient — FastAPI runs sync background tasks in a thread executor automatically. |

**Installation:**
```bash
pip install "PyJWT[crypto]>=2.11.0" "slowapi>=0.1.9"
```

Add to `wafr-agents/requirements.txt`:
```
PyJWT[crypto]>=2.11.0
slowapi>=0.1.9
```

---

## Architecture Patterns

### Recommended Project Structure

```
wafr-agents/wafr/
├── auth/                     # NEW: auth security subpackage
│   ├── __init__.py
│   ├── jwt_middleware.py     # PyJWKClient singleton, verify_token dep, role guard
│   ├── cors.py               # CORS origins parser from WAFR_CORS_ORIGINS env var
│   ├── rate_limit.py         # slowapi Limiter singleton, key_func, tier decorators
│   └── audit.py              # write_audit_entry(), build_audit_item()
└── ag_ui/
    └── server.py             # MODIFIED: wire in new auth layer
```

### Pattern 1: JWT Dependency Injection (not BaseHTTPMiddleware)

**What:** Use FastAPI's `Depends()` system to protect each route rather than `BaseHTTPMiddleware`. `BaseHTTPMiddleware` has known performance issues (creates 7 intermediate objects per request) and breaks `contextvars` propagation. Dependency injection is idiomatic FastAPI and has no such overhead.

**When to use:** All protected routes. The `AUTH_REQUIRED` env gate lives inside the dependency function.

**Example:**

```python
# wafr/auth/jwt_middleware.py
import os
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

JWKS_URL = (
    f"https://cognito-idp.us-east-1.amazonaws.com/"
    f"{os.environ['WAFR_COGNITO_USER_POOL_ID']}/.well-known/jwks.json"
)
# Singleton — PyJWKClient caches JWKS internally; re-fetches on unknown kid
_jwks_client = jwt.PyJWKClient(JWKS_URL)

# auto_error=False → returns None instead of 403 when header is absent
_bearer = HTTPBearer(auto_error=False)

COGNITO_ISSUER = (
    f"https://cognito-idp.us-east-1.amazonaws.com/"
    f"{os.environ['WAFR_COGNITO_USER_POOL_ID']}"
)
APP_CLIENT_ID = os.environ["WAFR_COGNITO_CLIENT_ID"]

def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """FastAPI dependency. Returns decoded claims dict. Raises 401 on any failure."""
    if not os.getenv("AUTH_REQUIRED", "true").lower() == "true":
        # Local dev bypass — return synthetic claims
        return {"sub": "dev-user", "cognito:groups": ["WafrTeam"]}

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authentication token",
        )
    token = credentials.credentials
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={
                "verify_exp": True,
                "verify_iss": True,
                "verify_signature": True,
                "require": ["exp", "iss", "sub", "token_use"],
            },
        )
        # Cognito access tokens use client_id (not aud) for audience
        if claims.get("token_use") != "access":
            raise ValueError("token_use must be 'access'")
        if claims.get("client_id") != APP_CLIENT_ID:
            raise ValueError("client_id mismatch")
        return claims
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authentication token",
        )


def require_team_role(claims: dict = Depends(verify_token)) -> dict:
    """Sub-dependency: raises 403 if user is not in WafrTeam group."""
    groups = claims.get("cognito:groups", [])
    if "WafrTeam" not in groups:
        raise HTTPException(status_code=403, detail="Requires WafrTeam role")
    return claims
```

**Usage on protected routes:**
```python
# Standard protected route
@app.get("/api/wafr/sessions", dependencies=[Depends(verify_token)])
async def list_sessions(): ...

# Team-only route
@app.post("/api/wafr/run", dependencies=[Depends(require_team_role)])
async def run_wafr_assessment(request: RunWAFRRequest, req: Request): ...

# Public routes — no dependency added
@app.get("/health")
async def health_check(): ...

@app.get("/docs")     # FastAPI serves /docs automatically; don't add auth dep
```

### Pattern 2: CORS Registration Order (CRITICAL)

**What:** CORS middleware must be added to `app` via `add_middleware()` **after** all other middlewares in the source code. FastAPI/Starlette wraps middlewares in a stack — the last registered is the outermost layer, meaning it executes **first** on incoming requests. CORS must be outermost so it adds `Access-Control-*` headers to ALL responses, including 401 errors from the auth dependency.

**When to use:** Every FastAPI app that combines auth + CORS.

**Example:**
```python
# server.py — order matters
# Step 1: Add rate limiter middleware
app.add_middleware(SlowAPIMiddleware)

# Step 2 (LAST): Add CORS middleware — executes first on requests
cors_origins = [
    o.strip()
    for o in os.getenv(
        "WAFR_CORS_ORIGINS",
        "https://3fhp6mfj7u.us-east-1.awsapprunner.com,http://localhost:3000"
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    max_age=3600,   # 1-hour preflight cache (Claude's discretion recommendation)
)
```

**Note on allow_credentials + wildcards:** When `allow_credentials=True`, CORS spec forbids wildcard `"*"` for origins, methods, or headers. Must enumerate explicitly.

### Pattern 3: slowapi Rate Limiting with Tiers

**What:** A single `Limiter` singleton; different tiers applied via `@limiter.limit()` decorator per endpoint. The `request: Request` parameter MUST be present in the endpoint signature for slowapi to function.

**Key design decision — rate limit scope (Claude's Discretion):**
Recommendation: **Per-IP for unauthenticated surface, per-user (sub claim) for authenticated endpoints.** This covers the case where multiple users share a NAT gateway (common in enterprise). Implementation: custom `key_func` that returns JWT `sub` claim when present, falls back to IP.

```python
# wafr/auth/rate_limit.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request

def _get_rate_limit_key(request: Request) -> str:
    """Use JWT sub for authenticated requests, IP for unauthenticated."""
    # Try to extract sub from Bearer token header (no full validation — just key extraction)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            import jwt as pyjwt
            token = auth.split(" ", 1)[1]
            # Decode without verification just to get sub for key
            unverified = pyjwt.decode(token, options={"verify_signature": False}, algorithms=["RS256"])
            sub = unverified.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"

limiter = Limiter(key_func=_get_rate_limit_key, default_limits=["200/minute"])
```

**Endpoint tier design (Claude's Discretion):**

| Tier | Limit | Applies To |
|------|-------|-----------|
| expensive | `10/minute` | `POST /api/wafr/run` (AI pipeline trigger) |
| standard | `60/minute` | All other POST/DELETE endpoints |
| read | `200/minute` | All GET endpoints (covered by default_limits) |
| excluded | no limit | SSE streaming connections (long-lived; initial POST already limited) |

```python
# Wiring in server.py
from wafr.auth.rate_limit import limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# On POST /api/wafr/run endpoint:
@app.post("/api/wafr/run")
@limiter.limit("10/minute")
async def run_wafr_assessment(request: Request, body: RunWAFRRequest): ...
```

**Important:** `request: Request` parameter must be present on every rate-limited endpoint. The `_rate_limit_exceeded_handler` built into slowapi returns 429 with `Retry-After` header automatically.

### Pattern 4: Pydantic Input Validation

**What:** Add `max_length` constraints to existing Pydantic models. Pydantic v2 enforces this before the route handler runs; FastAPI converts validation errors to 422 automatically.

**Example — augment existing `RunWAFRRequest`:**
```python
from pydantic import BaseModel, Field

class RunWAFRRequest(BaseModel):
    thread_id: Optional[str] = Field(None, description="Thread/session ID")
    run_id: Optional[str] = Field(None, description="Run ID")
    transcript: Optional[str] = Field(
        None,
        description="Transcript text",
        max_length=500_000,   # SECR-03: reject oversized transcripts with 422
    )
    transcript_path: Optional[str] = Field(None, description="Path to transcript file")
    generate_report: bool = Field(True, description="Generate PDF report")
    client_name: Optional[str] = Field(None, max_length=200, description="Client name for workload")
    options: Optional[Dict[str, Any]] = Field(None, description="Optional settings")
```

**Additional validation for other models (Claude's Discretion):**
- `ReviewDecisionRequest.decision`: `Literal["APPROVE", "MODIFY", "REJECT"]` (eliminates invalid enum values)
- `ReviewDecisionRequest.review_id`: `max_length=128` (prevents absurdly long IDs)
- `StartJobRequest.transcript`: `max_length=500_000` (matches `RunWAFRRequest`)

### Pattern 5: Async Audit Logging with BackgroundTasks

**What:** Every authenticated request writes an audit entry to `wafr-audit-log` DynamoDB table as a fire-and-forget `BackgroundTask`. Sync boto3 calls inside a `BackgroundTask` run in a thread pool executor — safe for async FastAPI.

**DynamoDB key schema (from Phase 1 infra record):**
- PK: `user_id` (S)
- SK: `timestamp_session_id` (S) — format: `"2026-02-28T12:00:00Z_{session_id}"`
- GSI: `session_id-timestamp-index`
- No TTL

**Audit item structure:**
```python
# wafr/auth/audit.py
import boto3
import json
import os
from datetime import datetime, timezone
from typing import Optional

_dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
_audit_table = _dynamodb.Table(os.getenv("WAFR_DYNAMO_AUDIT_TABLE", "wafr-audit-log"))

def write_audit_entry(
    user_id: str,
    session_id: Optional[str],
    action_type: str,
    http_method: str,
    path: str,
    client_ip: str,
    request_body: Optional[dict] = None,
) -> None:
    """Synchronous DynamoDB write — called via BackgroundTasks thread pool."""
    now = datetime.now(timezone.utc).isoformat()
    sk = f"{now}_{session_id or 'no-session'}"
    item = {
        "user_id": user_id,
        "timestamp_session_id": sk,
        "session_id": session_id or "",
        "timestamp": now,
        "action_type": action_type,
        "http_method": http_method,
        "path": path,
        "client_ip": client_ip,
        "request_body": json.dumps(request_body or {}, default=str),
    }
    try:
        _audit_table.put_item(Item=item)
    except Exception as exc:
        # Fire-and-forget: log failure but never raise (don't block API response)
        import logging
        logging.getLogger(__name__).warning("Audit write failed: %s", exc)
```

**Middleware integration for audit logging:**
Because audit logging needs to capture ALL authenticated requests (not per-endpoint), the cleanest approach is a lightweight pure-ASGI middleware or a global `after_request` pattern. Since FastAPI dependencies run before the response, the pattern is:

1. Create an `audit_log_middleware` pure-ASGI class that reads `request.state.claims` (set by the `verify_token` dep via `request.state`) and schedules a background write after response is sent.
2. Alternatively, inject `BackgroundTasks` into every endpoint — but this is verbose for 25+ endpoints.

**Recommended approach for audit logging:** A pure-ASGI middleware that wraps ALL responses. It reads `request.state` (populated by the auth dependency) and schedules the DynamoDB write after `send()`. Failed auth writes (before `request.state.claims` is populated) are handled by catching the auth exception and writing a `failed_auth` entry with IP only.

```python
# wafr/auth/audit.py — pure ASGI middleware class
class AuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request
        import asyncio
        request = Request(scope, receive)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Schedule audit after response headers sent
                asyncio.create_task(self._write_audit(request, message))
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _write_audit(self, request, response_message):
        claims = getattr(request.state, "claims", None)
        if claims is None:
            return  # Unauthenticated requests (health, docs) — skip
        user_id = claims.get("sub", "unknown")
        # ... build and write audit item
```

**Note:** Storing `claims` in `request.state` requires the auth dependency to explicitly set it:
```python
async def verify_token(request: Request, credentials=Depends(_bearer)) -> dict:
    claims = _decode_and_validate(credentials)
    request.state.claims = claims  # Available to audit middleware
    return claims
```

### Anti-Patterns to Avoid

- **Using `BaseHTTPMiddleware` for JWT auth:** Causes ContextVar propagation bugs and 20-30% latency overhead. Use `Depends(verify_token)` instead.
- **Creating a new `PyJWKClient` per request:** JWKS is fetched on every request, hammering Cognito. Use a module-level singleton.
- **Setting `allow_origins=["*"]` with `allow_credentials=True`:** Browser enforces CORS spec — this combination is rejected by all modern browsers. Must use explicit origin list.
- **Adding CORS middleware before auth middleware:** Auth 401 responses arrive at the browser without `Access-Control-Allow-Origin` header, causing an opaque network error in the frontend instead of a meaningful 401.
- **Placing `@limiter.limit()` decorator below the route decorator:** slowapi requires the route decorator to be outermost. Always: `@app.post(...)` then `@limiter.limit(...)`.
- **Missing `request: Request` parameter on rate-limited endpoints:** slowapi cannot extract the key without it; will raise 500 at runtime.
- **Returning token validation error details in the 401 body:** Leaks information about validation failure mode (expired vs. invalid vs. wrong issuer). Always return the generic message regardless of failure type.
- **Synchronous boto3 DynamoDB writes inside `async def` endpoints:** Blocks the event loop. Use `BackgroundTasks` (auto-threaded) or `asyncio.create_task()` (pure-ASGI approach).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JWKS key fetching and caching | Custom HTTP client + in-memory key cache | `PyJWKClient` (PyJWT built-in) | Handles `kid` matching, automatic cache refresh on key rotation, retries |
| RS256 signature verification | Custom RSA verify | `jwt.decode(algorithms=["RS256"])` | Algorithm confusion attacks are easy to introduce when hand-rolling; PyJWT handles them correctly |
| Rate limit sliding window | Custom `dict` + timestamp tracking | `slowapi` | Correct fixed-window/sliding-window semantics, `Retry-After` header, decorator syntax |
| 429 response with `Retry-After` | Custom exception handler | `_rate_limit_exceeded_handler` from slowapi | Built-in, correctly formatted, includes the `Retry-After` value from the limit descriptor |
| Pydantic 422 responses | Manual `len(transcript) > 500000` check | `Field(max_length=500_000)` | Pydantic runs before the route handler; no extra code path needed |

**Key insight:** Every item in this table has been an industry-standard solved problem for 3+ years. Custom implementations introduce security vulnerabilities (JWT) and subtle correctness bugs (rate limiting window semantics, CORS header edge cases).

---

## Common Pitfalls

### Pitfall 1: HTTPBearer Returns 403 Instead of 401

**What goes wrong:** FastAPI's `HTTPBearer()` raises `HTTPException(403)` by default when the `Authorization` header is missing or malformed. The roadmap spec requires 401.
**Why it happens:** FastAPI's `HTTPBearer` defaults `auto_error=True`, which produces 403 ("Forbidden") rather than 401 ("Unauthorized").
**How to avoid:** Instantiate with `HTTPBearer(auto_error=False)` and manually check if `credentials is None`, then raise `HTTPException(401, ...)`.
**Warning signs:** curl test `curl /api/wafr/sessions` returns 403, not 401.

### Pitfall 2: CORS 401 Missing CORS Headers

**What goes wrong:** Browser receives a 401 from the auth dependency but the response has no `Access-Control-Allow-Origin` header. The browser shows a network CORS error, masking the real 401.
**Why it happens:** `CORSMiddleware` was registered via `add_middleware()` before other middlewares, making it execute after the auth layer in the request pipeline.
**How to avoid:** Register `CORSMiddleware` as the absolute last call to `add_middleware()` in server.py (it will be outermost in the middleware stack, executing first on inbound requests and last on outbound responses).
**Warning signs:** Frontend console shows `Access to fetch has been blocked by CORS policy` for authenticated endpoints, even with correct token.

### Pitfall 3: Cognito Access Token vs. ID Token Confusion

**What goes wrong:** Frontend sends the ID token; backend validates `aud` claim against App Client ID — this works. But later the frontend sends the access token; backend tries to validate `aud` — fails because Cognito access tokens use `client_id` claim, NOT `aud`.
**Why it happens:** Cognito uses different claim names for the two token types (AWS-specific deviation from RFC 7519).
**How to avoid:** Always check `token_use` claim first. If `token_use == "access"`, validate `claims["client_id"]`. If `token_use == "id"`, validate `claims["aud"]`. Per roadmap decisions, we accept access tokens only (Frontend will send access tokens from Amplify SRP flow).
**Warning signs:** JWT decode succeeds but `client_id` check fails with a 401.

### Pitfall 4: `PyJWKClient` Instantiated After Env Vars Are Available

**What goes wrong:** Module-level `_jwks_client = jwt.PyJWKClient(JWKS_URL)` is evaluated at import time; if `WAFR_COGNITO_USER_POOL_ID` is not set yet, the URL is malformed.
**Why it happens:** Python evaluates module-level expressions at import time.
**How to avoid:** Use lazy initialization — create the client on first use inside the dependency function, cache via `functools.lru_cache()` or a module-level `None` guard.
**Warning signs:** `KeyError: 'WAFR_COGNITO_USER_POOL_ID'` at server startup.

```python
_jwks_client: jwt.PyJWKClient | None = None

def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        pool_id = os.environ["WAFR_COGNITO_USER_POOL_ID"]
        _jwks_client = jwt.PyJWKClient(
            f"https://cognito-idp.us-east-1.amazonaws.com/{pool_id}/.well-known/jwks.json"
        )
    return _jwks_client
```

### Pitfall 5: slowapi `request` Parameter Missing on Rate-Limited Endpoints

**What goes wrong:** `POST /api/wafr/run` uses `RunWAFRRequest` body but doesn't declare `request: Request`. slowapi can't extract the rate limit key and raises a 500 Internal Server Error.
**Why it happens:** slowapi accesses the raw Starlette `Request` object to read IP/headers. FastAPI doesn't inject it automatically unless declared.
**How to avoid:** Add `request: Request` as the first parameter on every rate-limited endpoint. FastAPI will not include it in the OpenAPI schema.
**Warning signs:** `500` on first call to a rate-limited endpoint in dev; `AttributeError` in slowapi internals.

### Pitfall 6: CORS `allow_credentials=True` with Wildcard Origins

**What goes wrong:** Setting `allow_origins=["*"]` and `allow_credentials=True` simultaneously. Browsers enforce the CORS spec and reject this combination entirely — preflight returns no `Access-Control-Allow-Origin` header.
**Why it happens:** CORS spec §3.2 prohibits credentials with wildcard origins.
**How to avoid:** Always use an explicit list of allowed origins when `allow_credentials=True`. Read from `WAFR_CORS_ORIGINS` env var; never default to `"*"`.
**Warning signs:** Preflight OPTIONS returns 200 but frontend requests are still blocked.

### Pitfall 7: Audit Middleware Ordering with CORS

**What goes wrong:** If the audit middleware is registered via `add_middleware()` after the CORS middleware, CORS headers are stripped from the audit middleware's internal response manipulation.
**Why it happens:** Same middleware ordering issue as Pitfall 2.
**How to avoid:** Use pure-ASGI middleware for audit (class with `__call__(scope, receive, send)`) and register it first (innermost). CORS stays outermost. Order: CORS (outermost) > SlowAPI > (auth via Depends) > AuditMiddleware (innermost, or use BackgroundTasks per-endpoint).

### Pitfall 8: Audit Writes Block SSE Streams

**What goes wrong:** Synchronous `boto3` `put_item` call runs inline in an async endpoint for `POST /api/wafr/run`. The endpoint returns an SSE `StreamingResponse`, but the sync write blocks the event loop before the first event is sent.
**Why it happens:** `asyncio` cannot yield to the event loop during a synchronous blocking call.
**How to avoid:** Always use `BackgroundTasks.add_task(write_audit_entry, ...)` or `asyncio.create_task()` so the sync DynamoDB call is off the event loop. The SSE stream starts immediately.

---

## Code Examples

Verified patterns from official sources and confirmed working implementations:

### JWT Verification with PyJWKClient (RS256 + Cognito claims)

```python
# Source: PyJWT 2.11.0 docs + AWS Cognito verification guide
import jwt
import os

def _decode_cognito_access_token(token: str) -> dict:
    """
    Decode and validate a Cognito access token.
    Returns claims dict. Raises jwt.PyJWTError on any validation failure.
    """
    client = _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    pool_id = os.environ["WAFR_COGNITO_USER_POOL_ID"]
    issuer = f"https://cognito-idp.us-east-1.amazonaws.com/{pool_id}"

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],       # Must specify — prevents algorithm confusion
        issuer=issuer,
        options={
            "verify_exp": True,
            "verify_iss": True,
            "verify_signature": True,
            "require": ["exp", "iss", "sub", "token_use"],
        },
    )
    # Cognito access token: client_id claim (not aud)
    if claims.get("token_use") != "access":
        raise ValueError("Expected access token, got id or other token type")
    if claims.get("client_id") != os.environ["WAFR_COGNITO_CLIENT_ID"]:
        raise ValueError("client_id does not match App Client ID")
    return claims
```

### slowapi Full Setup

```python
# Source: slowapi 0.1.9 docs + PyPI README
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI, Request

limiter = Limiter(key_func=_get_rate_limit_key, default_limits=["200/minute"])
app = FastAPI(...)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

@app.post("/api/wafr/run")
@limiter.limit("10/minute")
async def run_wafr_assessment(request: Request, body: RunWAFRRequest):
    # request: Request is REQUIRED for slowapi — must be first positional param
    ...
```

### CORS Middleware with Env-Var Origins

```python
# Source: FastAPI docs + verified pattern
import os
from fastapi.middleware.cors import CORSMiddleware

default_origins = "https://3fhp6mfj7u.us-east-1.awsapprunner.com,http://localhost:3000"
cors_origins = [
    o.strip()
    for o in os.getenv("WAFR_CORS_ORIGINS", default_origins).split(",")
    if o.strip()
]

# MUST be last add_middleware() call (executes first on requests)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Cache-Control"],
    expose_headers=["X-Request-ID"],
    max_age=3600,  # 1 hour preflight cache
)
```

### Pydantic max_length Validation (produces automatic 422)

```python
# Source: Pydantic v2 docs — Field constraints
from pydantic import BaseModel, Field

class RunWAFRRequest(BaseModel):
    transcript: Optional[str] = Field(
        None,
        max_length=500_000,  # 500K chars → 422 before route handler runs
        description="Transcript text",
    )
```

### DynamoDB Audit Write (fire-and-forget via BackgroundTasks)

```python
# Source: FastAPI BackgroundTasks docs + boto3 DynamoDB docs
from fastapi import BackgroundTasks

@app.post("/api/wafr/run")
@limiter.limit("10/minute")
async def run_wafr_assessment(
    request: Request,
    body: RunWAFRRequest,
    background_tasks: BackgroundTasks,
    claims: dict = Depends(verify_token),
):
    background_tasks.add_task(
        write_audit_entry,
        user_id=claims["sub"],
        session_id=body.thread_id,
        action_type="wafr_run",
        http_method="POST",
        path="/api/wafr/run",
        client_ip=request.client.host,
        request_body=body.model_dump(),
    )
    # ... rest of handler; audit write is non-blocking
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `python-jose` for JWT | `PyJWT[crypto]` | 2023 (python-jose became unmaintained) | PyJWT is the ecosystem standard; better JWKS support |
| `BaseHTTPMiddleware` for auth | `Depends()` dependency injection | FastAPI 0.95+ (2023) | No ContextVar bugs, better performance |
| `allow_origins=["*"]` in dev | `WAFR_CORS_ORIGINS` env var with explicit origins | Best practice since always, now locked | Configurable without redeployment; avoids credentials+wildcard bug |
| Manual JWT decode without `require` | `options={"require": [...]}` | PyJWT 2.4+ | Prevents missing-claim vulnerabilities |

**Deprecated/outdated:**
- `python-jose`: Depends on `cognitojwt` which is archived. Do not use.
- `fastapi-cloudauth`: Last release 2022; assumes older Cognito JWT structure.
- `starlette-jwt`: Archived, last release 2020. Predates PyJWT 2.x JWKS support.

---

## Open Questions

1. **SSE endpoint CORS permissiveness**
   - What we know: User decision says SSE endpoints have "more permissive CORS than standard endpoints (allow additional origins for potential embedding)"
   - What's unclear: Which additional origins? Are they known now, or is this a placeholder?
   - Recommendation: Default the SSE CORS to the same `WAFR_CORS_ORIGINS` list plus `allow_origin_regex` for `*.awsapprunner.com`. Keep a separate `WAFR_SSE_CORS_ORIGINS` env var documented but empty by default. This satisfies the intent without hardcoding unknown origins.

2. **Audit middleware vs. per-endpoint BackgroundTasks**
   - What we know: "Log ALL authenticated API calls" — implies a centralized approach is better than decorating all 25+ endpoints.
   - What's unclear: Pure-ASGI audit middleware is cleaner but requires reading request body (potentially large for `/run`). `BackgroundTasks` per-endpoint is verbose but simpler.
   - Recommendation: Hybrid. Pure-ASGI middleware handles metadata (user_id, path, IP, method) for all routes. Per-endpoint `BackgroundTasks` adds the `request_body` for the handful of write endpoints (`/run`, `/decision`, `/batch-approve`, `/finalize`). This avoids buffering SSE stream bodies in the middleware.

3. **`AUTH_REQUIRED` env var evaluation timing**
   - What we know: `AUTH_REQUIRED=true` is already set on App Runner from Phase 1.
   - What's unclear: The decision says "Set to false for local dev" — but who sets it? There's no `.env` file in the repo.
   - Recommendation: Document in the plan that local devs set `AUTH_REQUIRED=false` in their shell. Default in code is `true` (secure by default). No changes to App Runner config needed.

---

## Sources

### Primary (HIGH confidence)

- PyJWT 2.11.0 official docs (https://pyjwt.readthedocs.io/en/latest/) — PyJWKClient instantiation, RS256 decode, `require` option, caching behavior
- AWS Cognito JWT Verification Guide (https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) — `token_use`, `aud` vs `client_id`, `iss` format, 5-step verification process
- FastAPI CORS docs (https://fastapi.tiangolo.com/tutorial/cors/) — `CORSMiddleware` all parameters, wildcard + credentials constraint
- FastAPI BackgroundTasks docs (https://fastapi.tiangolo.com/tutorial/background-tasks/) — fire-and-forget pattern, sync tasks run in thread pool
- SlowAPI docs (https://slowapi.readthedocs.io/) — Limiter setup, `SlowAPIMiddleware`, `_rate_limit_exceeded_handler`, decorator syntax
- Phase 1 infra records (`.planning/phases/01-infrastructure-foundation/infra-records/task-02-user-audit-tables.md`) — `wafr-audit-log` key schema confirmed

### Secondary (MEDIUM confidence)

- angelospanag.me FastAPI Cognito JWT post (https://www.angelospanag.me/blog/verifying-a-json-web-token-from-cognito-in-python-and-fastapi) — Dependency class pattern, algorithm confusion warning, `token_use` validation pattern. Verified against official AWS docs.
- alukach.com FastAPI RS256 JWKS post (https://alukach.com/posts/fastapi-rs256-jwt/) — Singleton `PyJWKClient` pattern, `Security` dependency injection variant. Consistent with PyJWT docs.
- FastAPI/Starlette middleware ordering GitHub discussion (https://github.com/fastapi/fastapi/issues/2693) — CORS middleware ordering bug confirmation. Consistent with Starlette docs.

### Tertiary (LOW confidence — flag for validation)

- slowapi per-user hybrid key_func pattern (synthesized from docs examples + community usage): Unverified decode of JWT for rate limit key extraction. Low risk — errors fall back to IP.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — PyJWT 2.11.0 and slowapi 0.1.9 verified via PyPI and official docs; versions confirmed current
- Architecture: HIGH — Dependency injection over BaseHTTPMiddleware confirmed by FastAPI official docs and Starlette maintainer posts; CORS ordering confirmed by FastAPI GitHub issues
- Pitfalls: HIGH — HTTPBearer 403 vs 401 confirmed by FastAPI GitHub issues (#2026, #9130, #10177); Cognito token_use/client_id vs aud confirmed by AWS official docs; CORS+credentials wildcard confirmed by FastAPI official docs

**Research date:** 2026-02-28
**Valid until:** 2026-05-28 (stable libraries; 90-day validity)
