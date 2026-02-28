# Domain Pitfalls: DynamoDB + Cognito + API Security on FastAPI / App Runner

**Domain:** WAFR Assessment Platform — adding persistence, auth, and security to an existing FastAPI + Next.js app on App Runner
**Researched:** 2026-02-27
**Context:** Existing app has no auth, file-based storage (lost on container restart), permissive CORS, and a known broken DynamoDB import (`No module named 'deployment'`). This milestone adds DynamoDB, Cognito, and API hardening without breaking existing endpoints.

---

## Critical Pitfalls

Mistakes that cause rewrites, security incidents, or data loss.

---

### Pitfall 1: SSE Streaming Endpoints Break When Auth Middleware Runs Before CORS

**What goes wrong:** The existing SSE endpoints stream real-time pipeline progress to the Next.js frontend. When you add JWT authentication middleware, requests that fail token validation return error responses *before* CORSMiddleware processes them. The browser receives the error response without `Access-Control-Allow-Origin` headers and reports a CORS error — masking the actual auth error and making debugging extremely difficult.

**Why it happens:** FastAPI middleware executes in reverse registration order. If auth middleware is added *after* CORS middleware in code, auth runs *before* CORS on incoming requests. A 401 returned by auth middleware never reaches CORS middleware, so the response has no CORS headers.

**Consequences:** The frontend SSE client (`aws-frontend/lib/sse-client.ts`) fails silently or with a misleading CORS error. Developers spend hours debugging CORS when the real problem is token validation. Worse, disabling CORS middleware "to fix the bug" creates a security regression.

**Prevention:**
1. Register `CORSMiddleware` LAST in code (it executes FIRST on requests — FastAPI reverses middleware order).
2. Auth middleware must run *after* CORS preflight is handled.
3. Correct order in `server.py`:
   ```python
   app.add_middleware(AuthMiddleware)   # added first in code = runs second on requests
   app.add_middleware(CORSMiddleware, ...)  # added last in code = runs first on requests
   ```
4. Test: Issue an OPTIONS preflight to an auth-protected endpoint and verify the response has CORS headers even when no token is provided.

**Detection:** Browser console shows CORS error on SSE endpoint, but server logs show no request reached the route handler. Auth 401 responses lack `Access-Control-Allow-Origin` headers.

**Phase:** DynamoDB + Auth setup phase — address before wiring in any auth middleware.

**Confidence:** HIGH — verified via FastAPI official docs and multiple production case studies.

---

### Pitfall 2: SSE Connections Are Not HTTP Request/Response — JWT Validation Needs Special Handling

**What goes wrong:** Standard FastAPI `Depends()` JWT validation works for normal HTTP endpoints but behaves incorrectly for SSE. SSE opens one long-lived HTTP connection that lasts for the entire pipeline run (potentially 5-15 minutes for a WAFR assessment). The JWT is validated only at connection open. If the JWT expires mid-stream (Cognito access tokens expire in 1 hour), the server has no mechanism to re-validate — but the existing code never checked auth anyway, so adding naive middleware that validates on every request may not apply to SSE at all depending on implementation.

**Why it happens:** SSE is a persistent HTTP GET with `Content-Type: text/event-stream`. FastAPI's `StreamingResponse` returns a generator. Auth middleware typically validates headers at the start of the request lifecycle but cannot interrupt a streaming generator mid-flight.

**Consequences:**
- If token expires during a long assessment run, the connection stays open (token was valid when established) — this is acceptable behavior.
- If you validate the token on *every streamed chunk* (wrong approach), you'll get auth errors mid-stream.
- If you forget to exclude SSE paths from aggressive middleware, you'll break all streaming.

**Prevention:**
1. Validate JWT once at SSE connection establishment using a `Depends()` on the route, not in middleware.
2. Set a reasonable connection-level auth strategy: token valid at connection time = connection is trusted for its lifetime.
3. Cognito access token default TTL is 1 hour — ensure assessment runs complete within that window (they should; WAFR runs are <30 min).
4. Add SSE endpoint paths (`/run-assessment`, `/stream/*`) to any middleware exclusion list to avoid double-processing.

**Detection:** Pipeline hangs or drops mid-run after ~60 minutes. Auth errors appear in logs with stream-related context.

**Phase:** Auth middleware implementation.

**Confidence:** MEDIUM — SSE + JWT pattern verified via FastAPI community sources; specific Cognito expiry interaction is reasoning from verified facts.

---

### Pitfall 3: DynamoDB Item Size Limit — WAFR Transcripts and Pipeline Results Will Exceed 400KB

**What goes wrong:** DynamoDB has a hard 400KB limit per item. WAFR workshop transcripts can be large (multi-hour sessions produce lengthy text). Pipeline results include full question/answer pairs across all five WAFR pillars (100+ questions), confidence scores, gap analysis, and JSON structured data. Storing the entire session as a single DynamoDB item will hit the 400KB limit and cause `ValidationException: Item size has exceeded the maximum allowed size` — silently dropping saves in the worst case if error handling is absent.

**Why it happens:** The natural mapping from the existing file-based storage (one JSON file per session in `/review_sessions/`) to DynamoDB is "one item per session." This seems correct but ignores the size constraint. The existing `review_storage.py` stores full pipeline output in a single structure.

**Consequences:** DynamoDB writes fail for large assessments. The application silently uses stale file-based data (if fallback exists) or crashes. This is likely what caused the existing broken DynamoDB save attempt (`No module named 'deployment'`) — the module error masked a deeper design problem.

**Prevention:**
1. **Store transcript text in S3, not DynamoDB.** The transcript is already being processed — store the S3 key in DynamoDB, not the raw text.
2. **Split pipeline results across multiple items:** Use `PK = SESSION#{session_id}`, `SK = RESULT#understanding`, `SK = RESULT#mapping`, etc. Each agent's output is a separate item.
3. **Measure before you migrate:** Use the DynamoDB item size calculator on 3-5 real session files. If any exceed 300KB (leaving headroom), split immediately.
4. **PDF reports are already in S3** (`/tmp/reports/` → S3) — extend this pattern to transcripts.

**Detection:** `ValidationException: Item size has exceeded the maximum allowed size` in boto3 error logs. Sessions with longer transcripts fail to save while short ones succeed.

**Phase:** DynamoDB table design phase — must resolve before writing the storage migration code.

**Confidence:** HIGH — 400KB limit is documented AWS constraint; S3 offload pattern is the official AWS recommendation.

---

### Pitfall 4: Using Cognito ID Token Instead of Access Token for API Authorization

**What goes wrong:** Cognito issues two relevant tokens: the **ID token** (contains user identity: email, name, custom attributes) and the **access token** (contains scopes and `cognito:groups` claims for authorization). Teams default to using the ID token because it has more readable user information, but the ID token is intended for *authentication* (proving who the user is), not *authorization* (controlling what the user can do). Using the ID token for API authorization is a security anti-pattern.

**Why it happens:** The ID token's claims are more human-readable (`email`, `name`, custom attributes). Access tokens look sparse by comparison. FastAPI tutorials sometimes show ID token validation without explaining the distinction. The `cognito:groups` claim IS present on both token types, which blurs the distinction further.

**Consequences:**
- The `aud` claim validation differs: ID tokens use the `aud` claim (App Client ID); access tokens use `client_id`. Validating with the wrong claim field causes tokens from other applications to pass validation (security vulnerability).
- If you later add OAuth scopes for fine-grained API control, ID tokens don't carry scope information.
- AWS explicitly states: "Use the access token to authorize API calls based on the custom scopes of specified access-protected resources."

**Prevention:**
1. Use access tokens for all FastAPI endpoint authorization.
2. Use ID tokens only in the Next.js frontend for displaying user information (name, email).
3. In JWT validation, verify `token_use == "access"` claim explicitly.
4. Validate the `client_id` claim (not `aud`) for access tokens.
5. Required validation chain: `RS256 algorithm` → `issuer (iss)` → `expiry (exp)` → `token_use == "access"` → `client_id` → `cognito:groups` for RBAC.

**Detection:** Auth passes for tokens issued to different app clients (wrong `aud` but correct `iss`). Group-based RBAC silently fails when groups claim is missing (ID tokens may not always include `cognito:groups`).

**Phase:** JWT middleware implementation.

**Confidence:** HIGH — verified via official AWS Cognito documentation and authoritative FastAPI+Cognito implementation guide.

---

### Pitfall 5: Algorithm Confusion Attack — Not Enforcing RS256 in JWT Validation

**What goes wrong:** Cognito uses RS256 (RSA asymmetric signing). If the JWT validation library is configured to accept "any algorithm" or defaults to HS256 (HMAC symmetric), an attacker can forge tokens signed with the public key (which is publicly available from the JWKS endpoint) as an HS256 symmetric secret. The validator accepts the forged token.

**Why it happens:** JWT libraries default to being permissive. Python's `python-jose`, `PyJWT`, and others require explicit algorithm specification. Copy-pasted JWT validation code from generic tutorials often omits `algorithms=["RS256"]`.

**Consequences:** Complete authentication bypass — any attacker who knows your Cognito User Pool's public JWKS can forge valid tokens.

**Prevention:**
```python
import jwt
from jwt import PyJWKClient

jwks_client = PyJWKClient(
    f"https://cognito-idp.us-east-1.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
)
signing_key = jwks_client.get_signing_key_from_jwt(token)
payload = jwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],          # EXPLICIT — never omit
    options={"verify_exp": True},  # EXPLICIT — never omit
    audience=None,                 # Access tokens use client_id, not aud
)
```

**Detection:** Forged tokens with mismatched algorithm headers pass validation in testing. Security scanners flag algorithm confusion vulnerability.

**Phase:** JWT middleware implementation — the very first thing to get right before anything else.

**Confidence:** HIGH — documented vulnerability class, verified via official FastAPI+Cognito guide by Angelos Panagiotopoulos.

---

## Moderate Pitfalls

Mistakes that cause bugs, data inconsistency, or significant debugging time.

---

### Pitfall 6: boto3 DynamoDB Rejects Python Float Values — Assessment Scores Will Break Saves

**What goes wrong:** WAFR scoring agents produce numerical scores (confidence scores, weighted assessments) as Python `float` values. boto3's DynamoDB type serializer does NOT accept Python `float` — it raises `TypeError: Float types are not supported. Use Decimal types instead`. This is a well-known boto3 limitation that has existed since 2015 and remains unfixed.

**Why it happens:** The existing scoring agent stores results in-memory and to files. When migrating to DynamoDB, developers assume Python numbers map naturally to DynamoDB Number type. They do — but only for `int` and `Decimal`, not `float`.

**Consequences:** Every DynamoDB write that includes a floating-point score fails with a TypeError. Assessment results cannot be persisted. This is almost certainly a contributor to the existing broken DynamoDB save attempt.

**Prevention:**
1. Create a serialization helper that recursively converts all `float` to `Decimal` before any `put_item` or `update_item` call:
   ```python
   from decimal import Decimal
   import json

   def floats_to_decimal(obj):
       if isinstance(obj, float):
           return Decimal(str(obj))
       if isinstance(obj, dict):
           return {k: floats_to_decimal(v) for k, v in obj.items()}
       if isinstance(obj, list):
           return [floats_to_decimal(i) for i in obj]
       return obj
   ```
2. Apply this helper to ALL data before writing to DynamoDB.
3. When reading from DynamoDB, convert `Decimal` back to `float` for JSON serialization (FastAPI's JSON encoder doesn't handle `Decimal` by default either — use a custom encoder).

**Detection:** `TypeError: Float types are not supported. Use Decimal types instead` in DynamoDB write paths. Easy to reproduce in tests.

**Phase:** DynamoDB storage migration.

**Confidence:** HIGH — long-standing boto3 limitation, confirmed via multiple official boto3 GitHub issues.

---

### Pitfall 7: Cognito Groups Claim Is in the Access Token but RBAC Logic Reads from the Wrong Place

**What goes wrong:** The `cognito:groups` claim exists in both the ID token and access token. However, the FastAPI backend needs to implement role-based access control (team vs. client roles). Developers often write RBAC logic that reads `cognito:roles` or `cognito:preferred_role` (IAM-related claims) instead of `cognito:groups` (the application group membership claim). These are different claims with different semantics.

**Why it happens:** AWS documentation covers both User Pool groups AND Identity Pool role mapping in the same sections. `cognito:roles` contains IAM role ARNs (for AWS service access). `cognito:groups` contains the group names (like "team-admins" or "clients"). Mixing them up is easy.

**Consequences:** RBAC silently fails — all users appear to have no role, or roles resolve to AWS ARN strings that don't match any application-level check. Clients can access team-only endpoints if the role check always evaluates to false (fails open) rather than denying.

**Prevention:**
1. Use `cognito:groups` (not `cognito:roles`) for application-level RBAC in FastAPI.
2. Define group names clearly in Cognito: `wafr-team` and `wafr-clients`.
3. FastAPI dependency for role checking:
   ```python
   def require_role(required_group: str):
       def _check(payload: dict = Depends(get_current_user)):
           groups = payload.get("cognito:groups", [])
           if required_group not in groups:
               raise HTTPException(status_code=403, detail="Insufficient role")
           return payload
       return _check
   ```
4. Fail closed: if `cognito:groups` is absent from token, deny access (don't default to permissive).

**Detection:** All authenticated users receive 403 regardless of group membership. Or: all users can access admin endpoints regardless of group.

**Phase:** RBAC implementation.

**Confidence:** HIGH — verified via AWS Cognito documentation on User Pool groups and token claims.

---

### Pitfall 8: App Runner Secrets Rotation Is Not Automatic — Cognito Config Will Stale After Rotation

**What goes wrong:** App Runner supports referencing secrets from AWS Secrets Manager and SSM Parameter Store as environment variables. However, App Runner **only pulls secrets at service deployment time** — not at runtime. If Cognito User Pool IDs, App Client secrets, or other configuration values change (e.g., recreating a User Pool during development, rotating a client secret), the running App Runner service continues to use the old values until it is redeployed.

**Why it happens:** Developers assume that because App Runner reads from Secrets Manager, updates propagate automatically. They don't.

**Consequences:** After any Cognito reconfiguration, the backend silently rejects all tokens (wrong issuer or client_id in JWT validation). All users are logged out. The fix is a full redeploy.

**Prevention:**
1. Store Cognito config (User Pool ID, App Client ID, region) in SSM Parameter Store and reference from App Runner.
2. Document clearly: any Cognito User Pool configuration change requires a backend redeploy.
3. Never store Cognito config as plaintext environment variables in the App Runner console (visible in AWS console, not encrypted).
4. Add a `/health` endpoint that validates the Cognito JWKS endpoint is reachable and returns a 200 — use this to detect config staleness after rotation.

**Detection:** After Cognito config changes, all JWT validation returns 401 `invalid issuer`. Redeploying the App Runner service fixes it.

**Phase:** Infrastructure setup (IAM + Cognito provisioning).

**Confidence:** MEDIUM — App Runner secrets rotation behavior verified via official AWS documentation and re:Post discussions. Cognito-specific consequence is reasoning from verified base fact.

---

### Pitfall 9: Rate Limiting with In-Memory State Fails Under App Runner Auto-Scaling

**What goes wrong:** App Runner can run multiple container instances of the FastAPI backend (min 1, max N based on configuration). SlowAPI's default in-memory rate limiting (`limits/memory`) tracks request counts **per container instance** — not globally. Under load, a user who should be rate-limited at 10 req/min can hit 10 req/min on each instance, effectively getting N × 10 req/min where N is the number of running instances.

**Why it happens:** Developers test rate limiting locally on a single instance and it works correctly. Under production load, App Runner scales to multiple instances, each with its own counter store.

**Consequences:** Rate limiting is completely ineffective at preventing abuse of the expensive Bedrock/AI pipeline endpoints during scale-out events.

**Prevention:**
1. For this WAFR platform (internal + limited client users, not high-scale), in-memory rate limiting on a single App Runner instance (min instances = 1) is acceptable as a basic protection.
2. If scaling beyond 1 instance is needed, use ElastiCache Redis as the SlowAPI backend:
   ```python
   from slowapi import Limiter
   from slowapi.util import get_remote_address
   limiter = Limiter(key_func=get_remote_address, storage_uri="redis://your-redis-endpoint:6379")
   ```
3. OR use user-based rate limiting keyed on Cognito `sub` (user ID from JWT) rather than IP — more meaningful for an authenticated app.
4. Document App Runner min instances = 1 for rate limiting to function correctly without Redis.

**Detection:** Users report being able to submit many more assessments than the rate limit should allow. Rate limit 429 responses stop appearing under load.

**Phase:** API security hardening.

**Confidence:** MEDIUM — App Runner scaling behavior is HIGH confidence; rate limiting state-per-instance consequence is well-established in distributed systems literature.

---

### Pitfall 10: DynamoDB Scan Operations for Session Listing — Will Silently Degrade as Data Grows

**What goes wrong:** The most natural way to list "all sessions for a user" or "all recent sessions" is a DynamoDB `Scan` with a filter. Scans read every item in the table and apply filters afterwards. The 1MB read limit per Scan call means large tables require paginated scans. More critically, Scan operations consume Read Capacity Units for every item read — not just items returned.

**Why it happens:** The table design isn't thought through before coding. `Scan` is the first API developers reach for when learning DynamoDB. The dashboard listing existing assessments needs this pattern, and without GSIs, Scan is the only option.

**Consequences:** As the audit trail and session count grows (even to a few thousand sessions), listing sessions becomes progressively slower and more expensive. At 10,000 sessions, a full-table scan to list one user's assessments reads every other user's data unnecessarily.

**Prevention:**
1. Design access patterns first:
   - "List all sessions for user X" → `PK = USER#{cognito_sub}`, `SK = SESSION#{timestamp}` — Query, not Scan.
   - "Get session by ID" → `PK = SESSION#{session_id}` — GetItem.
   - "List recent sessions across all users (admin view)" → GSI with `PK = STATUS`, `SK = CREATED_AT`.
   - "Get audit trail for session X" → `PK = SESSION#{session_id}`, `SK = AUDIT#{timestamp}` — Query.
2. Never use Scan for application data queries. Reserve Scan for DynamoDB console exploration and migration scripts only.
3. Define all access patterns in table design doc before writing any boto3 code.

**Detection:** Dashboard listing takes >500ms. CloudWatch shows high `ConsumedReadCapacityUnits` on Scan operations. AWS DynamoDB Contributor Insights shows full-table reads.

**Phase:** DynamoDB table design — must be correct before writing any storage layer code.

**Confidence:** HIGH — DynamoDB Query vs Scan behavior is official documentation.

---

### Pitfall 11: Missing `token_use` Claim Validation Allows Cross-Purpose Token Usage

**What goes wrong:** Cognito issues multiple token types (access, id, refresh). If `token_use` claim validation is skipped, an attacker who obtains a refresh token could attempt to use it as an access token. More practically: developers accidentally send ID tokens to the backend API because the frontend Amplify session object makes the ID token more accessible than the access token.

**Why it happens:** Amplify's `fetchAuthSession()` returns a session object. The ID token is at `session.tokens.idToken.toString()`. The access token is at `session.tokens.accessToken.toString()`. Developers often grab the first one they see.

**Consequences:** Either the backend accepts the wrong token type (missing validation) or the frontend sends the wrong token and all API calls return 401 (broken app).

**Prevention:**
1. Backend validates `token_use == "access"` explicitly.
2. Frontend must send access token in the `Authorization: Bearer` header, not the ID token:
   ```typescript
   const session = await fetchAuthSession();
   const accessToken = session.tokens?.accessToken?.toString();
   // NOT: session.tokens?.idToken?.toString()
   ```
3. Add an integration test that: (a) obtains an ID token, (b) sends it to a protected endpoint, (c) verifies the endpoint returns 401.

**Detection:** API calls return 401 even though user is authenticated. Decoding the token in jwt.io reveals `token_use: "id"` instead of `token_use: "access"`.

**Phase:** Frontend + backend auth integration.

**Confidence:** HIGH — Cognito token_use claim is official documentation; Amplify API access pattern is verified.

---

## Minor Pitfalls

Issues that are annoying but don't cause data loss or security incidents.

---

### Pitfall 12: `WafrAppRunnerInstanceRole` Needs Both DynamoDB AND Cognito-IDP Permissions — Missing One Causes Silent Failures

**What goes wrong:** The backend uses the `WafrAppRunnerInstanceRole` IAM role for all AWS SDK calls (no explicit credentials — App Runner provides the role automatically). When adding DynamoDB, the team remembers to add `dynamodb:*` but forgets `cognito-idp:AdminGetUser` or `cognito-idp:ListUsers` for any admin user management operations. Or vice versa.

**Why it happens:** IAM policy updates happen incrementally. DynamoDB permissions get added when DynamoDB is set up. Cognito permissions get added when Cognito is set up. But if the backend needs to look up user metadata from Cognito (e.g., listing users for an admin view), those permissions are separate.

**Consequences:** `AccessDeniedException` from boto3 that appears only on specific code paths. The error message includes the missing permission and role ARN but is easy to miss in logs if error handling swallows the exception.

**Prevention:**
1. Define the full IAM policy for this milestone upfront, add all permissions at once:
   ```json
   {
     "Effect": "Allow",
     "Action": [
       "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
       "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:BatchWriteItem"
     ],
     "Resource": "arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*"
   }
   ```
   Note: scope to specific table ARNs, not `dynamodb:*` on `*` resource.
2. The backend does NOT need to call Cognito Admin APIs for JWT validation (validation uses the public JWKS endpoint over HTTPS — no AWS credentials needed). Cognito Admin API permissions are only needed if the backend creates/lists/deletes users.
3. Test IAM permissions by hitting each DynamoDB operation in isolation from App Runner (not from local dev with full admin credentials).

**Detection:** `AccessDeniedException: User: arn:aws:sts::842387632939:assumed-role/WafrAppRunnerInstanceRole/... is not authorized to perform: dynamodb:PutItem on resource: ...`

**Phase:** Infrastructure / IAM setup.

**Confidence:** HIGH — IAM permission behavior is official documentation.

---

### Pitfall 13: Fixing the Existing `No module named 'deployment'` Error Requires Understanding Import Path, Not Just Adding the Module

**What goes wrong:** The existing codebase has a broken DynamoDB save attempt that fails with `No module named 'deployment'`. The instinct is to find what `deployment` refers to and add it. But this error indicates a broken relative import or wrong `PYTHONPATH` configuration when the App Runner container starts — not simply a missing package.

**Why it happens:** App Runner Python services run from a specific working directory. If the code uses `from deployment.db import DynamoStorage` but `deployment/` is a directory relative to the repo root (not in `PYTHONPATH`), the import fails at runtime even though it works locally (where `PYTHONPATH` includes the repo root).

**Consequences:** Any new DynamoDB storage code that follows the same import pattern will fail identically. The fix applied locally won't reproduce the App Runner failure.

**Prevention:**
1. Investigate the actual import chain in `server.py` and related files before writing new storage code.
2. Fix the import pattern — use absolute imports from the package root or adjust the App Runner `apprunner.yaml` start command to set `PYTHONPATH`.
3. Write the new `DynamoStorage` class inside the existing package structure that already works (e.g., alongside `review_storage.py` in `wafr/storage/`).
4. Test the full Docker build locally with `docker build` and `docker run` before deploying to App Runner.

**Detection:** `No module named 'X'` in App Runner service logs. Works in local `uvicorn` start, fails in App Runner.

**Phase:** DynamoDB storage migration — first step.

**Confidence:** MEDIUM — the specific error is documented in PROJECT.md; root cause inference is from standard Python import behavior in containerized apps.

---

### Pitfall 14: Cognito Token Refresh in the Frontend — Amplify Silent Refresh Has Known Bugs

**What goes wrong:** Amplify's `fetchAuthSession()` is supposed to transparently refresh tokens when they expire. However, there is a confirmed bug where once both the `idToken` and `accessToken` expire simultaneously, Amplify does not initiate a refresh even when a valid refresh token is present — it silently returns `undefined` instead of throwing an error or refreshing.

**Why it happens:** The WAFR platform has long assessment runs. If a user opens the app, starts an assessment, the tokens expire (1-hour TTL) during the run, and then they try to start another assessment, the frontend will silently have no valid token to send.

**Consequences:** Silent API failures after 1 hour of inactivity. No error shown to user. Next assessment attempt gets 401 from the backend. User sees a confusing blank screen or spinner.

**Prevention:**
1. Set Cognito access token TTL to 8 hours (reasonable for a work session) rather than the default 1 hour.
2. Implement explicit token refresh on app focus/visibility change:
   ```typescript
   document.addEventListener('visibilitychange', async () => {
     if (!document.hidden) {
       await fetchAuthSession({ forceRefresh: true });
     }
   });
   ```
3. Add a 401 response interceptor in `backend-api.ts` that triggers a token refresh and retries the request once.
4. On persistent 401 after refresh, redirect to login page.

**Detection:** Users report being "logged out" after ~1 hour without page reload. Amplify `fetchAuthSession()` returns undefined in browser console.

**Phase:** Frontend Cognito integration.

**Confidence:** MEDIUM — Amplify silent refresh bug is confirmed via GitHub issue #14406; workaround pattern is from AWS re:Post community guidance.

---

### Pitfall 15: CORS Lockdown Must Allow the Exact App Runner Frontend URL — Trailing Slash Matters

**What goes wrong:** The frontend is at `https://3fhp6mfj7u.us-east-1.awsapprunner.com` (no trailing slash). If the FastAPI CORS configuration uses `https://3fhp6mfj7u.us-east-1.awsapprunner.com/` (trailing slash), CORS will reject all requests from the frontend. Similarly, if a custom domain is added later, the old App Runner URL CORS allowlist breaks.

**Why it happens:** Origin comparison in CORS is exact string matching. A trailing slash makes it a different origin.

**Prevention:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://3fhp6mfj7u.us-east-1.awsapprunner.com",  # No trailing slash
        # Add custom domain here when set up
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

**Detection:** Browser shows CORS error. Check exact `Origin` header value in the rejected preflight request against the allowlist.

**Phase:** API security hardening (CORS lockdown).

**Confidence:** HIGH — CORS origin matching is a browser standard; trailing slash behavior is well-documented.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|----------------|------------|
| DynamoDB table design | Scan instead of Query for user session listing | Design all access patterns with GSIs before writing code |
| DynamoDB table design | Transcript/result items exceed 400KB | Measure existing session files; store transcripts in S3 |
| DynamoDB storage migration | `float` values in scoring data | Add `floats_to_decimal()` converter at the storage layer boundary |
| DynamoDB storage migration | Existing broken import (`No module named 'deployment'`) | Fix import path first; write new storage inside `wafr/storage/` |
| Auth middleware setup | CORS breaks when auth middleware added | Register CORS middleware last in code (executes first on requests) |
| JWT validation implementation | Algorithm confusion (RS256 vs HS256) | Enforce `algorithms=["RS256"]` explicitly in every validation call |
| JWT validation implementation | ID token used instead of access token | Validate `token_use == "access"` claim; backend sends access token |
| JWT validation implementation | Missing issuer/expiry/audience validation | Use full validation chain; never trust unverified claims |
| RBAC implementation | `cognito:roles` (IAM ARN) confused with `cognito:groups` (app groups) | Use `cognito:groups`; define group names `wafr-team`/`wafr-clients` |
| Frontend Cognito integration | Token refresh silently fails after 1-hour expiry | Increase token TTL to 8h; add visibility-change refresh trigger |
| Frontend Cognito integration | ID token sent instead of access token to backend | Use `session.tokens.accessToken.toString()` explicitly |
| Rate limiting | In-memory limits bypass under App Runner multi-instance | Keep min instances = 1; document limitation; use Redis if scaling |
| Rate limiting | Rate limiting middleware blocks SSE keep-alive chunks | Exclude SSE paths from per-request rate limit counting |
| IAM permissions | Insufficient DynamoDB table permissions on App Runner role | Add permissions before testing; scope to `wafr-*` table ARNs |
| CORS lockdown | Trailing slash in allowed origin | Use exact URL without trailing slash |
| CORS lockdown | Future custom domain breaks lockdown | Keep App Runner URL + custom domain both in allowlist |

---

## Sources

- [Verifying a JSON Web Token from Amazon Cognito in Python and FastAPI — Angelos Panagiotopoulos](https://www.angelospanag.me/blog/verifying-a-json-web-token-from-cognito-in-python-and-fastapi) (HIGH confidence — direct JWT validation pitfall enumeration)
- [Understanding user pool JSON web tokens — AWS Cognito Official Docs](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-with-identity-providers.html) (HIGH confidence)
- [Best practices for storing large items in DynamoDB — AWS Official Docs](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-use-s3-too.html) (HIGH confidence — 400KB limit and S3 offload pattern)
- [Float types not supported in boto3 DynamoDB — boto3 GitHub Issue #369](https://github.com/boto/boto3/issues/369) (HIGH confidence — long-standing confirmed bug)
- [Using role-based access control — AWS Cognito Official Docs](https://docs.aws.amazon.com/cognito/latest/developerguide/role-based-access-control.html) (HIGH confidence — cognito:groups vs cognito:roles distinction)
- [Navigating Middleware Ordering in FastAPI — Medium](https://medium.com/@saurabhbatham17/navigating-middleware-ordering-in-fastapi-a-cors-dilemma-8be88ab2ee7b) (MEDIUM confidence — CORS + auth middleware ordering)
- [AWS App Runner integrates with Secrets Manager — AWS News](https://aws.amazon.com/blogs/containers/aws-app-runner-now-integrates-with-aws-secrets-manager-and-aws-systems-manager-parameter-store/) (HIGH confidence — secrets not auto-rotated)
- [Amplify silent refresh bug — GitHub Issue #14406](https://github.com/aws-amplify/amplify-js/issues/14406) (MEDIUM confidence — confirmed open GitHub issue)
- [DynamoDB throttling — AWS Official Docs](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TroubleshootingThrottling.html) (HIGH confidence)
- [Building fine-grained authorization with Cognito User Pool groups — AWS Security Blog](https://aws.amazon.com/blogs/mobile/building-fine-grained-authorization-using-amazon-cognito-user-pools-groups/) (HIGH confidence)
- [SlowAPI — FastAPI rate limiting library](https://github.com/laurentS/slowapi) (HIGH confidence)
- [DynamoDB 10 Limits You Need to Know — Dynobase](https://dynobase.dev/dynamodb-limits/) (MEDIUM confidence — comprehensive limits reference)
