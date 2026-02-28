# Architecture Patterns: DynamoDB + Cognito + API Security on FastAPI + Next.js

**Domain:** WAFR Assessment Platform — Auth, Persistence, API Security milestone
**Researched:** 2026-02-27
**Context:** Subsequent milestone — existing App Runner deployment, no architecture change

---

## System Overview

This milestone adds three orthogonal concerns to the existing system:

1. **Persistence** — swap file-based session storage for DynamoDB
2. **Authentication** — add Cognito user pools, JWT verification middleware
3. **API security** — CORS lockdown, rate limiting, input validation

The key constraint is: existing App Runner deployment stays intact. No migration to Lambda or API Gateway. Auth is added as a FastAPI middleware layer, not as an infrastructure-level gateway.

---

## Component Map

```
[Browser]
    |
    | (1) Login: SRP auth challenge
    v
[Cognito User Pool]  <-- manages users, groups (team/client), issues JWTs
    |
    | (2) Returns: id_token, access_token, refresh_token
    v
[Next.js Frontend — App Runner]
    |
    | (3) HTTP requests with Authorization: Bearer <access_token>
    v
[FastAPI Backend — App Runner]
    |   |
    |   | (4) CognitoJWTMiddleware: fetches JWKS, verifies token, extracts claims
    |   |     - cognito:groups -> role (team / client)
    |   |     - sub -> user_id
    |   |
    |   | (5) Route handler runs (user context injected as FastAPI dependency)
    |   |
    |   +-- (6) DynamoDB: session read/write
    |   +-- (7) S3: PDF report storage (existing)
    |   +-- (8) Bedrock: AI pipeline (existing)
    |   +-- (9) AWS WA Tool: workload management (existing)
    v
[DynamoDB Tables]
    - wafr-sessions
    - wafr-review-sessions
    - wafr-users
    - wafr-audit-log
```

---

## Component Boundaries

| Component | Responsibility | Communicates With | Auth Involvement |
|-----------|---------------|-------------------|------------------|
| Cognito User Pool | User identity, password management, JWT issuance | Frontend (auth flows), Backend (JWKS endpoint) | Source of truth |
| Next.js Frontend | Amplify auth UI, token storage, attach Bearer header | Cognito (directly), FastAPI (API calls) | Consumes JWTs |
| FastAPI Middleware | JWT verification, user context extraction, rate limiting, CORS | Cognito JWKS endpoint (cached), DynamoDB | Enforces auth |
| DynamoDB | Durable session, user, audit storage | FastAPI backend only | Stores auth context in audit trail |
| S3 | PDF report blobs | FastAPI backend only | No auth change |
| Bedrock | AI inference | FastAPI backend only | No auth change |

---

## Recommended Architecture

### Authentication Flow

**Pattern: JWT Bearer, verified at middleware layer.**

Do NOT use API Gateway. App Runner stays as-is. FastAPI adds a `CognitoJWTMiddleware` (or FastAPI dependency) that:
1. Reads `Authorization: Bearer <token>` header
2. Fetches JWKS from `https://cognito-idp.us-east-1.amazonaws.com/<user_pool_id>/.well-known/jwks.json` (cache this — key rotates rarely)
3. Verifies signature with `python-jose` or `PyJWT`
4. Checks: `exp` (not expired), `iss` (matches user pool), `token_use` = `access`
5. Extracts `sub` (user_id) and `cognito:groups` (role list) from claims
6. Injects `CurrentUser` Pydantic model into request state

**Implementation recommendation:** Write a thin custom middleware using `python-jose[cryptography]`. Do NOT use `fastapi-cloudauth` — it has slow maintenance. Do NOT use `fastapi-cognito` — small community, adds indirection.

```python
# Pattern: FastAPI dependency for auth
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import httpx

security = HTTPBearer()

class CurrentUser:
    def __init__(self, user_id: str, email: str, role: str):
        self.user_id = user_id
        self.email = email
        self.role = role  # "team" or "client"

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CurrentUser:
    token = credentials.credentials
    # 1. Decode header to get kid
    # 2. Fetch JWKS (cached), find matching key
    # 3. Verify token with jose
    # 4. Extract claims
    claims = _verify_cognito_token(token)
    groups = claims.get("cognito:groups", [])
    role = "team" if "WafrTeam" in groups else "client"
    return CurrentUser(
        user_id=claims["sub"],
        email=claims.get("email", ""),
        role=role
    )
```

Apply to endpoints:
```python
@app.post("/api/wafr/run")
async def run_wafr(
    request: RunWAFRRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    # current_user.role, current_user.user_id available
```

Existing `/health` endpoint stays unauthenticated (needed for App Runner health checks).

---

### Role-Based Access (Cognito Groups)

**Two groups in Cognito User Pool:**

| Group | Members | Access |
|-------|---------|--------|
| `WafrTeam` | Internal assessors | Full CRUD — create assessments, view all sessions, approve HRI decisions |
| `WafrClients` | External clients | Read-only — view only their own session results and reports |

**Enforcement in FastAPI:**

```python
def require_team(current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role != "team":
        raise HTTPException(status_code=403, detail="Team access required")
    return current_user
```

Applied to: `POST /api/wafr/run`, `POST /api/wafr/review/*/decision`, `POST /api/wafr/review/*/batch-approve`, `POST /api/wafr/review/*/finalize`.

Client-accessible read endpoints: `GET /api/wafr/session/{id}/state`, `GET /api/wafr/session/{id}/pillars`, `GET /api/wafr/session/{id}/results` — filtered by `session.owner_user_id == current_user.user_id`.

---

### Frontend Auth Integration

**Pattern: AWS Amplify v6 configured against existing Cognito pool (no Amplify backend).**

Rationale: Amplify UI provides a ready-made `<Authenticator>` component (login/signup/forgot-password) without building custom forms. It handles token refresh automatically. Direct configuration against an existing user pool is documented and supported.

```typescript
// aws-frontend/lib/amplify-config.ts
import { Amplify } from 'aws-amplify';

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
      userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID!,
      loginWith: { email: true },
    }
  }
});
```

```typescript
// aws-frontend/lib/api.ts — updated to attach token
import { fetchAuthSession } from 'aws-amplify/auth';

export async function apiGet<T>(path: string): Promise<T> {
  const session = await fetchAuthSession();
  const token = session.tokens?.accessToken?.toString();
  const res = await fetch(`${BACKEND_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {}
  });
  // ... error handling unchanged
}
```

Token lifecycle: Amplify handles refresh automatically. Access tokens expire in 1 hour by default (configurable in Cognito app client settings up to 24 hours). `fetchAuthSession()` returns a fresh token if the current one is near expiry.

The `session-db.ts` IndexedDB cache remains valid — it serves as offline-capable session list cache, independent of auth.

---

### DynamoDB Table Design

**Use separate tables, not single-table design.**

Single-table design optimizes for read performance across heterogeneous entities accessed together. For WAFR, the entities (sessions, review-sessions, users, audit) are accessed independently, not in joins. Separate tables are simpler to reason about and maintain.

#### Table 1: `wafr-sessions`

| Attribute | Type | Role |
|-----------|------|------|
| `session_id` (PK) | String | Unique session UUID |
| `owner_user_id` | String | Cognito sub of creator |
| `status` | String | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `ERROR` |
| `assessment_name` | String | Human-readable name |
| `created_at` | String (ISO8601) | Creation timestamp |
| `updated_at` | String (ISO8601) | Last update timestamp |
| `pipeline_results` | Map | Full orchestrator output JSON |
| `workload_id` | String | AWS WA Tool workload ID |
| `report_s3_key` | String | S3 path to PDF report |

GSI: `UserSessionsIndex` — PK: `owner_user_id`, SK: `created_at` — enables "list all sessions for user X, sorted by date."

#### Table 2: `wafr-review-sessions`

Replaces `FileReviewStorage`. The existing `ReviewStorage` abstract class already defines the interface — `DynamoDBReviewStorage` becomes a new implementation.

| Attribute | Type | Role |
|-----------|------|------|
| `session_id` (PK) | String | Links to `wafr-sessions` |
| `status` | String | `ACTIVE`, `FINALIZED` |
| `items` | List | Review item objects |
| `created_at` | String | Timestamp |
| `updated_at` | String | Timestamp |

#### Table 3: `wafr-users`

| Attribute | Type | Role |
|-----------|------|------|
| `user_id` (PK) | String | Cognito `sub` |
| `email` | String | User email |
| `role` | String | Mirrors Cognito group: `team` or `client` |
| `created_at` | String | First login timestamp |
| `last_seen_at` | String | Updated on each authenticated request |

This table is optional for phase 1 — Cognito is the source of truth. Use it if you need persistent user preferences or cross-session user data that Cognito doesn't store.

#### Table 4: `wafr-audit-log`

Write-only audit trail. Append-only pattern.

| Attribute | Type | Role |
|-----------|------|------|
| `log_id` (PK) | String | UUID |
| `user_id` (SK) | String | Actor |
| `action` | String | `RUN_ASSESSMENT`, `REVIEW_DECISION`, `FINALIZE`, `VIEW_RESULTS` |
| `session_id` | String | Target session |
| `timestamp` | String | ISO8601 |
| `metadata` | Map | Extra context (decision type, etc.) |

GSI: `UserAuditIndex` — PK: `user_id`, SK: `timestamp`.

#### DynamoDB Access from App Runner

App Runner uses the `WafrAppRunnerInstanceRole` IAM role. Add these permissions:

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
    "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"
  ],
  "Resource": [
    "arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*",
    "arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*/index/*"
  ]
}
```

boto3 will auto-discover credentials from the instance metadata service — no keys needed in code.

---

### Storage Layer: Adding DynamoDB Implementation

The existing `ReviewStorage` abstract class in `wafr/storage/review_storage.py` is perfectly positioned for a DynamoDB implementation. Add a `DynamoDBReviewStorage` class that implements the same interface.

```python
# wafr/storage/dynamodb_review_storage.py
import boto3
from wafr.storage.review_storage import ReviewStorage

class DynamoDBReviewStorage(ReviewStorage):
    def __init__(self, table_name: str = "wafr-review-sessions", region: str = "us-east-1"):
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(table_name)

    def save_session(self, session_data: dict) -> None:
        self._table.put_item(Item=session_data)

    def load_session(self, session_id: str) -> dict | None:
        resp = self._table.get_item(Key={"session_id": session_id})
        return resp.get("Item")
    # ... etc
```

Update the factory `create_review_storage()` to accept `storage_type="dynamodb"`. Use environment variable `REVIEW_STORAGE_TYPE=dynamodb` in App Runner.

For pipeline results (currently in `_save_pipeline_results` / `_load_pipeline_results`), store these directly in `wafr-sessions` table as the `pipeline_results` Map attribute.

**Use synchronous boto3, not aioboto3.** The FastAPI endpoints that touch storage are not the hot path for concurrency — the AI pipeline dominates latency. Adding async DynamoDB adds complexity with minimal benefit. FastAPI handles sync functions in a thread pool automatically.

---

### API Security Layer

Three independent middleware components added to the FastAPI app, applied in this order:

```
Request → CORS Check → Rate Limit Check → JWT Auth Check → Route Handler
```

#### CORS Lockdown

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://3fhp6mfj7u.us-east-1.awsapprunner.com",  # existing frontend
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

CORS middleware must be added last in FastAPI (executes first in request chain) to ensure preflight responses get CORS headers even when auth fails.

#### Rate Limiting

Use `slowapi` — it is the standard for FastAPI and wraps `limits` library. It integrates natively with Starlette middleware.

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/api/wafr/run")
@limiter.limit("10/minute")
async def run_wafr(request: Request, ...):
    ...
```

Limits by endpoint:
- `POST /api/wafr/run` — `10/minute` (AI pipeline is expensive)
- `POST /api/wafr/process-file` — `10/minute`
- `POST /api/wafr/review/*/decision` — `60/minute`
- `GET /api/wafr/sessions` — `30/minute`

For App Runner with multiple instances, in-memory rate limiting means limits apply per instance, not globally. This is acceptable for v1 — the user base is small (internal team + clients). Redis-backed global rate limiting can be added later.

#### Input Validation

Pydantic models already enforce types. Add explicit validation for the critical attack surface — transcript size:

```python
class RunWAFRRequest(BaseModel):
    transcript: Optional[str] = Field(
        None,
        max_length=500_000,  # ~500KB max, Bedrock context limit
        description="Transcript text"
    )
    # ... existing fields
```

Add HTTPS enforcement: App Runner provides HTTPS by default (TLS termination at the load balancer). No additional configuration needed.

---

## Data Flow: End-to-End Assessment

```
1. User visits frontend → Amplify checks token (refresh if needed)
2. Login page → Cognito SRP auth → returns access_token (1hr TTL)
3. Amplify stores tokens in localStorage (managed by Amplify)
4. User submits transcript → frontend calls POST /api/wafr/run
   - Header: Authorization: Bearer <access_token>
5. FastAPI CORSMiddleware → allows request from frontend origin
6. SlowAPI limiter → checks IP rate (10/min)
7. get_current_user dependency → verifies JWT against Cognito JWKS
   - Extracts: user_id = claims["sub"], role = "team"
8. Route handler starts SSE stream
9. AI pipeline runs (Bedrock calls, existing logic)
10. On completion: save to wafr-sessions DynamoDB table
    - session_id, owner_user_id, status=COMPLETED, pipeline_results
11. SSE stream ends, frontend navigates to /results
12. GET /api/wafr/session/{id}/state → auth check → DynamoDB read
    - If role=client: verify session.owner_user_id == current_user.user_id
    - If role=team: no ownership filter
13. Audit log entry written: {action: "VIEW_RESULTS", user_id, session_id}
```

---

## Data Flow: Frontend Auth State

```
App startup
  └─ layout.tsx wraps app in <Amplify.configure> call
  └─ AuthProvider component:
       - Calls Auth.currentAuthenticatedUser()
       - If logged in → render app
       - If not logged in → render <Authenticator> (Amplify UI)

API calls (api.ts)
  └─ fetchAuthSession() → returns cached tokens (refreshes if < 5min to expiry)
  └─ Attach Authorization header to all fetch calls

Token expiry
  └─ Amplify automatically refreshes using refresh_token (valid 30 days)
  └─ If refresh fails → redirect to login
```

---

## Suggested Build Order

This is the critical dependency chain for this milestone:

### Phase 1: Infrastructure Foundation (no frontend changes)
Build this first because everything depends on it.
1. Create DynamoDB tables (IaC or AWS console, us-east-1)
2. Add DynamoDB permissions to `WafrAppRunnerInstanceRole`
3. Create Cognito User Pool + App Client + Groups (WafrTeam, WafrClients)
4. Add Cognito permissions to `WafrAppRunnerInstanceRole` (admin APIs if needed)

### Phase 2: Storage Migration (backend only)
Build before auth — validates DynamoDB works independently of auth.
1. Implement `DynamoDBReviewStorage` (drop-in for `FileReviewStorage`)
2. Update `_save_pipeline_results` / `_load_pipeline_results` to use `wafr-sessions` table
3. Update `create_review_storage()` factory to support `storage_type=dynamodb`
4. Write migration script: read existing JSON files, write to DynamoDB
5. Deploy backend with `REVIEW_STORAGE_TYPE=dynamodb`, test with existing no-auth flow

### Phase 3: Backend Auth Middleware (backend only)
Build auth after storage — independently testable, no frontend dep.
1. Add `python-jose[cryptography]` to requirements
2. Implement `CognitoJWTMiddleware` / `get_current_user` dependency
3. Add JWKS caching (in-memory dict, refresh on `kid` miss)
4. Apply auth to all non-health endpoints
5. Add role enforcement (team vs client) to write endpoints
6. Tighten CORS: replace `allow_origins=["*"]` with frontend App Runner URL
7. Add `slowapi` rate limiting
8. Add transcript `max_length` validation
9. Deploy and test with Postman / curl using real Cognito tokens

### Phase 4: Frontend Auth Integration (frontend only)
Build last — needs working Cognito pool from Phase 1.
1. Install `aws-amplify` v6
2. Configure Amplify with Cognito user pool IDs (env vars)
3. Wrap layout with `<AuthWrapper>` using Amplify `<Authenticator>`
4. Update `api.ts` to attach `Authorization: Bearer` header
5. Handle 401 responses (redirect to login)
6. Test full flow: login → submit assessment → view results

### Phase 5: Data Migration and Audit
1. Run migration script for existing sessions
2. Verify audit log entries are being created
3. Validate client role can only see own sessions

---

## Patterns to Follow

### Pattern 1: JWKS Caching

**What:** Cache Cognito public keys in-memory at startup. Refresh only on `kid` miss (Cognito rotates keys rarely, months apart).

**Why:** JWKS endpoint is an HTTP call. Hitting it on every request adds ~100ms latency and is fragile.

```python
_jwks_cache: dict[str, Any] = {}  # kid -> public key
_jwks_fetched_at: float = 0

async def get_public_key(kid: str) -> Any:
    if kid not in _jwks_cache or (time.time() - _jwks_fetched_at) > 3600:
        await _refresh_jwks()
    return _jwks_cache.get(kid)
```

### Pattern 2: User-Scoped Session Reads

**What:** When a client role requests session data, always filter by `owner_user_id`.

**Why:** Prevents horizontal privilege escalation — client A cannot access client B's sessions.

```python
async def get_session_with_authz(
    session_id: str, current_user: CurrentUser
) -> dict:
    session = await dynamodb_get_session(session_id)
    if not session:
        raise HTTPException(404)
    if current_user.role == "client" and session["owner_user_id"] != current_user.user_id:
        raise HTTPException(403)  # Do NOT reveal session exists (404 is fine too)
    return session
```

### Pattern 3: Middleware Order in FastAPI

**What:** Add middleware in reverse of desired execution order. FastAPI wraps each added middleware around the previous.

```python
# Execution order: CORS → RateLimit → Auth → Handler
# But add_middleware order (last added = first executed):
app.add_middleware(SlowAPIMiddleware)  # 2nd in execution
app.add_middleware(CORSMiddleware, ...)  # 1st in execution (handles preflight)
```

CORS must execute before auth so that preflight OPTIONS requests (which have no auth header) get proper CORS response headers. Auth middleware rejecting a preflight with 401 breaks CORS.

### Pattern 4: Backward-Compatible Auth Rollout

**What:** Deploy auth middleware with a bypass flag first, then enable once frontend is ready.

**Why:** Backend and frontend cannot deploy atomically. Without bypass, deploying backend auth before frontend sends tokens breaks the existing (unauthenticated) flow.

```python
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").lower() == "true"

async def get_current_user_or_anonymous(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security)
) -> CurrentUser:
    if not AUTH_REQUIRED:
        return CurrentUser(user_id="anonymous", email="", role="team")
    # ... full JWT verification
```

Deploy backend with `AUTH_REQUIRED=false`, deploy frontend with Amplify auth, then flip `AUTH_REQUIRED=true`.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Storing JWTs in DynamoDB
**What:** Saving Cognito tokens in DynamoDB as a session-token pattern.
**Why bad:** JWTs are stateless. Cognito handles token state. Storing them duplicates trust anchors and creates stale token problems.
**Instead:** Verify JWTs on every request against Cognito's JWKS. Trust the signature, not a DB record.

### Anti-Pattern 2: API Gateway in Front of App Runner
**What:** Adding API Gateway between frontend and App Runner for auth/rate-limiting.
**Why bad:** Adds latency (~20-50ms), SSE streaming compatibility issues with API Gateway's 29-second timeout, breaks existing App Runner URL, requires environment migration.
**Instead:** Auth and rate limiting as FastAPI middleware. App Runner handles both directly.

### Anti-Pattern 3: Storing Cognito Passwords or Secrets in Code
**What:** Embedding User Pool Client Secret in frontend JavaScript.
**Why bad:** Client secret exposed in browser = security incident.
**Instead:** Use a Cognito App Client configured WITHOUT a client secret (public client). Amplify's SRP auth protocol does not require the client secret.

### Anti-Pattern 4: Single DynamoDB Table for All Entities
**What:** Packing sessions, users, review-sessions, and audit-log into one table with composite keys.
**Why bad:** WAFR entities are accessed independently. Single-table design benefit (co-located joins) does not apply. Adds key design complexity for no performance gain at this scale.
**Instead:** Separate tables per entity type. Simpler access patterns, easier to debug.

### Anti-Pattern 5: Async DynamoDB (aioboto3) for v1
**What:** Using aioboto3 for truly non-blocking DynamoDB calls.
**Why bad:** aioboto3 adds complexity (async context managers, lifecycle management). The WAFR pipeline is CPU+AI-bound. DynamoDB calls (<5ms) are not the bottleneck.
**Instead:** Synchronous boto3 in sync def functions. FastAPI runs these in a thread pool, preserving concurrency. Revisit if DynamoDB call volume becomes a bottleneck.

### Anti-Pattern 6: Putting Large Pipeline Results in URL Parameters or Headers
**What:** Attempting to pass full pipeline results through query params or headers.
**Why bad:** HTTP headers have 8KB limits. Full assessment results are 10-100KB JSON.
**Instead:** Store in DynamoDB `pipeline_results` attribute (max 400KB item size). Return by session_id reference.

---

## Scalability Considerations

| Concern | Current (10 users) | Future (100 users) | Future (1000 users) |
|---------|-------------------|-------------------|-------------------|
| Auth token verification | JWKS in-memory cache — negligible | Same, still negligible | Same |
| DynamoDB reads | `GetItem` by session_id — 1ms | Same | Add DAX if needed |
| Rate limiting | SlowAPI in-memory per instance | Multiple App Runner instances = per-instance limits | Add Redis backend |
| Session list queries | `Query` on UserSessionsIndex GSI | Same, add pagination | Add status GSI for filtering |
| Audit log writes | Async fire-and-forget | Same | DynamoDB Streams → Lambda |
| CORS | Single origin allowed | Add origins as needed | Same |

---

## Environment Variables Required

### Backend (App Runner environment)
| Variable | Value | Purpose |
|----------|-------|---------|
| `COGNITO_USER_POOL_ID` | `us-east-1_XXXXXXXX` | JWT issuer verification |
| `COGNITO_CLIENT_ID` | `xxxxxxxxxxxxxx` | Token audience verification |
| `COGNITO_REGION` | `us-east-1` | JWKS endpoint region |
| `DYNAMODB_SESSIONS_TABLE` | `wafr-sessions` | Main session storage |
| `DYNAMODB_REVIEW_TABLE` | `wafr-review-sessions` | Review session storage |
| `DYNAMODB_AUDIT_TABLE` | `wafr-audit-log` | Audit trail |
| `REVIEW_STORAGE_TYPE` | `dynamodb` | Storage backend selector |
| `AUTH_REQUIRED` | `true` (after frontend ready) | Auth bypass toggle |
| `FRONTEND_URL` | `https://3fhp6mfj7u.us-east-1.awsapprunner.com` | CORS allowed origin |

### Frontend (App Runner environment / .env.local)
| Variable | Value | Purpose |
|----------|-------|---------|
| `NEXT_PUBLIC_COGNITO_USER_POOL_ID` | `us-east-1_XXXXXXXX` | Amplify config |
| `NEXT_PUBLIC_COGNITO_CLIENT_ID` | `xxxxxxxxxxxxxx` | Amplify config |
| `NEXT_PUBLIC_BACKEND_URL` | existing backend URL | Already set |

---

## Sources

- [FastAPI CORS Documentation](https://fastapi.tiangolo.com/tutorial/cors/) — HIGH confidence (official)
- [Verifying Cognito JWTs — AWS Official Docs](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) — HIGH confidence (official)
- [Cognito RBAC with Groups — AWS Official Docs](https://docs.aws.amazon.com/cognito/latest/developerguide/role-based-access-control.html) — HIGH confidence (official)
- [Amplify Gen 2 — Use Existing Cognito Resources](https://docs.amplify.aws/nextjs/build-a-backend/auth/use-existing-cognito-resources/) — HIGH confidence (official)
- [SlowAPI — Rate Limiter for FastAPI/Starlette](https://github.com/laurentS/slowapi) — MEDIUM confidence (widely used, maintained)
- [aioboto3 PyPI](https://pypi.org/project/aioboto3/) — MEDIUM confidence (verified library exists, async pattern confirmed)
- [boto3 Credentials Guide — IAM Roles](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html) — HIGH confidence (official)
- [DynamoDB Single-Table Design Tradeoffs — DeBrie Advisory](https://www.alexdebrie.com/posts/dynamodb-single-table/) — MEDIUM confidence (expert source, widely cited)
- [python-jose for JWT verification — FastAPI pattern](https://www.angelospanag.me/blog/verifying-a-json-web-token-from-cognito-in-python-and-fastapi) — MEDIUM confidence (consistent with official docs)
- [DynamoDB GSI query patterns — boto3 docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/client/query.html) — HIGH confidence (official)
