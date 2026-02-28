# Feature Landscape: DynamoDB + Cognito + API Security

**Domain:** Production authentication, persistent storage, and API security for a FastAPI + Next.js WAFR assessment platform
**Researched:** 2026-02-27
**Milestone context:** Adding storage, auth, and security to an existing publicly accessible WAFR assessment platform

---

## Table Stakes

Features that MUST exist — without them the system is insecure, unreliable, or unusable. Missing = unacceptable for production.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| JWT verification middleware on every FastAPI route | Anyone with the backend URL has full access today — this is the primary security gap | Medium | Use `python-jose` or `PyJWT` with JWKS caching; inject as FastAPI `Depends()` callable; verify `exp`, `iss`, `aud`/`client_id`, `token_use` claims per AWS official docs |
| Cognito User Pool with two groups: `team` and `client` | Role-based access is a hard requirement; `cognito:groups` claim appears in both ID and access tokens automatically | Low | Create pool + app client + two groups; group membership flows into JWT automatically, no Lambda triggers needed |
| Frontend login/logout flow using AWS Amplify v6 | Users cannot reach the app without authenticating | Medium | Amplify v6 supports Next.js 13.5–15.x; use `@aws-amplify/ui-react` Authenticator component OR Cognito Managed Login (hosted UI); Managed Login ships HttpOnly cookie support (March 2025) |
| DynamoDB persistence for assessment sessions | File-based storage loses all data on container restart/redeploy; this is a confirmed bug in production today | High | Replace `/review_sessions/` file writes with DynamoDB `put_item`/`update_item`; 5 entity types across 2–3 tables |
| CORS lockdown to frontend App Runner domain only | Currently `allow_origins=["*"]` — permits any origin, breaks `allow_credentials` support | Low | Set `allow_origins=["https://3fhp6mfj7u.us-east-1.awsapprunner.com"]`, `allow_credentials=True`, explicit `allow_methods` and `allow_headers`; cannot use wildcards once credentials are enabled (FastAPI official docs) |
| Role enforcement in route handlers | JWT verification alone does not enforce RBAC — group claim must be inspected per endpoint | Medium | Extract `cognito:groups` from decoded access token; `team` group can create/run assessments; `client` group can only read their own; raise 403 on violation |
| Rate limiting on all endpoints | No rate limiting today; brute-force and DoS attack surface | Medium | `slowapi` (Starlette-native, decorator-based) with in-memory storage is sufficient for single App Runner instance; use per-user-ID key function post-auth, per-IP for unauthenticated endpoints |
| Input validation — transcript size cap | WAFR transcripts can be arbitrarily large; no current limit risks memory exhaustion and cost blowout on Bedrock | Low | Pydantic field validator: `max_length` on transcript string; ASGI body-size middleware as defense-in-depth; recommended cap is 500KB–2MB depending on Bedrock limits |
| Audit trail — who ran what assessment and when | WAFR is a compliance tool; audit records are expected for enterprise clients | Medium | Dedicated `AuditTrail` DynamoDB table or GSI; write one record per significant action (session created, assessment started, review submitted, report generated); include `userId`, `action`, `sessionId`, `timestamp` |
| Session ownership — data isolation per user/client | Clients must only see their own assessments; team sees all | Medium | Add `userId` (from JWT `sub` claim) to every DynamoDB session item; filter queries by `userId` for client role; team role bypasses filter; enforce in service layer not just frontend |
| Token expiry handling in frontend | Expired tokens silently fail and users see blank/broken UI | Low | Amplify v6 handles token refresh automatically via refresh token rotation; configure `tokenRefresh` in Amplify config; ensure access token is forwarded to backend (not ID token) |
| DynamoDB migration of existing file sessions | There are live session files at `/review_sessions/` — losing them on migration is user-visible | Medium | Write one-time migration script: read existing JSON files, map to DynamoDB schema, `put_item` with `ConditionExpression='attribute_not_exists(PK)'` to prevent duplicates |
| IAM permissions on `WafrAppRunnerInstanceRole` | DynamoDB and Cognito calls will fail silently if the role lacks permissions | Low | Add `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `Query`, `DeleteItem` on specific table ARNs; add `cognito-idp:AdminGetUser` for user lookups if needed |
| HTTPS enforcement | App Runner provides HTTPS termination by default; backend must not accept plain HTTP from trusted paths | Low | App Runner handles this at the load balancer; add `ProxyHeadersMiddleware` so FastAPI reads `X-Forwarded-Proto` correctly for URL generation; do NOT add `HTTPSRedirectMiddleware` (double-redirect behind App Runner) |

---

## Differentiators

Features that provide real value beyond baseline security and persistence — not universally expected but meaningfully improve the product.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| HttpOnly cookie token storage on frontend | Tokens in localStorage are XSS-vulnerable; HttpOnly cookies prevent client-side script access | Medium | AWS Amplify v6 + Cognito Managed Login enables this as of March 2025; requires server-side sign-in flow; adds protection layer above token-in-header approach |
| DynamoDB TTL on temporary/in-progress sessions | Automatic cleanup of abandoned assessments without cron jobs or maintenance | Low | Set `expires_at` epoch attribute on `IN_PROGRESS` sessions; expire after 7 days; DynamoDB deletes within ~48h of expiry; note: items past TTL still appear in reads until deleted |
| Optimistic locking on session updates | Prevents race conditions if two processes write to the same session (e.g., streaming agent + human review simultaneously) | Medium | Add `version` attribute; use `ConditionExpression='#ver = :current_version'` on updates; increment on each write; catch `ConditionalCheckFailedException` and retry; AWS official pattern |
| Structured audit log with pre/post state | Beyond "who did what", capture before/after values for compliance reporting | High | DynamoDB Streams → Lambda (or direct in Python): on MODIFY events, store old and new image in audit table; significant operational complexity; defer unless compliance explicitly requires it |
| Per-assessment access tokens for clients | Instead of Cognito user account per client, generate time-limited presigned access to specific assessment reports | High | Requires custom token generation logic, separate auth path; major scope; defer to v2 |
| Session search across all assessments (team view) | Team members need to find past assessments by date, transcript content, or score | Medium | DynamoDB GSI on `userId` + `created_at` for team list-all; full-text search requires OpenSearch (out of scope); basic filtering by date range is achievable with GSI |
| Self-service user invitation flow | Team admin invites client directly from the UI without AWS Console access | High | Cognito Admin API (`adminCreateUser`) + SES email; non-trivial UI; medium-term feature |
| CloudWatch structured logging integration | Correlate API requests, auth events, and assessment runs in one log stream | Low | Python `logging` + JSON formatter + structured fields (`userId`, `sessionId`, `requestId`); App Runner ships logs to CloudWatch automatically; add correlation IDs to SSE stream events |

---

## Anti-Features

Features to deliberately NOT build in this milestone — either out of scope, harmful, or premature.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Custom JWT signing / home-rolled auth | Security-critical code that routinely introduces vulnerabilities (timing attacks, algorithm confusion, key mismanagement) | Use Cognito as the issuer; verify tokens against Cognito JWKS endpoint; never generate your own JWTs |
| OAuth social login (Google, GitHub) | The PROJECT.md explicitly defers this to v2; adds app client config, callback URL management, and user merge complexity | Cognito user pool with email/password is sufficient; add social later via Cognito identity provider config |
| Multi-tenancy with billing and isolation | Current user base doesn't need it; adds data partitioning complexity across every query | Use `userId` ownership model; full multi-tenancy (separate pools, tables per org) is a v3 concern |
| Real-time collaboration on assessments | Assessments are single-user workflows; collaborative editing requires WebSocket state management and conflict resolution | Keep assessments single-owner; share read-only links via presigned URLs in v2 |
| DynamoDB Streams for audit trail (v1) | Streams + Lambda adds operational complexity, cold start latency, and a new failure mode; overkill for v1 audit needs | Write audit records directly in the Python service layer at the point of each action; simpler and reliable |
| Frontend SSR authentication middleware (Next.js middleware.ts) | API-level JWT auth already protects all data; middleware-level auth adds a second auth path to maintain and can cause redirect loops with Amplify | Protect routes client-side via Amplify auth state; the backend is the real security boundary |
| Storing raw JWT tokens in DynamoDB | Tokens are not data; storing them creates a secondary credential store that must be revoked separately | Store only `sub` (Cognito user ID) as the user identifier in DynamoDB records; never store tokens |
| Per-endpoint Cognito Authorizer via API Gateway | PROJECT.md explicitly rules out API Gateway migration; App Runner → API Gateway migration is weeks of work | Implement JWT middleware in FastAPI directly; keeps the App Runner deployment intact |
| DynamoDB provisioned capacity with auto-scaling | WAFR assessments are highly variable (batch runs, then quiet); auto-scaling still has warm-up lag | Use on-demand capacity mode; AWS reduced pricing in Nov 2024 making it cost-competitive; eliminates capacity planning entirely |
| Admin UI inside this application | Building user management UI (list users, deactivate accounts) in this milestone creates scope creep | Use AWS Console or Cognito AdminCreateUser API for direct admin operations; defer UI to v2 |

---

## Feature Dependencies

```
Cognito User Pool created
  → App client created (enables token issuance)
    → Frontend Amplify configured (enables login flow)
    → Backend JWKS endpoint resolvable (enables JWT verification)
      → JWT verification middleware implemented
        → Role enforcement in route handlers
          → Session ownership filtering in DynamoDB queries

DynamoDB tables created with correct schema + GSIs
  → IAM role updated with DynamoDB permissions
    → File-based session writes replaced with DynamoDB writes
      → Migration script run (existing file sessions imported)
        → File-based storage can be disabled

Rate limiting implemented (requires: FastAPI app initialized)
CORS lockdown implemented (requires: frontend domain known — it is: App Runner URL)
Input validation implemented (requires: Pydantic models on endpoints — already exist in FastAPI codebase)
Audit trail writes (requires: JWT middleware, so userId is available)
```

---

## DynamoDB Schema Feature Details

The following entities drive the table design decisions:

| Entity | Access Patterns | Key Structure | TTL Needed |
|--------|----------------|---------------|-----------|
| Session | Get by sessionId; List by userId; List all (team) | PK=`SESSION#<sessionId>` SK=`METADATA` | Yes — 7 days for IN_PROGRESS |
| PipelineResults | Get by sessionId | PK=`SESSION#<sessionId>` SK=`RESULTS` | No |
| ReviewDecision | Get by sessionId + questionId | PK=`SESSION#<sessionId>` SK=`REVIEW#<questionId>` | No |
| User | Get by userId (sub) | PK=`USER#<sub>` SK=`PROFILE` | No |
| AuditEvent | List by userId+time; List by sessionId+time | PK=`AUDIT#<userId>` SK=`<timestamp>#<eventId>` | Optional — 90 days |

GSI needed: `userId-createdAt-index` on Session table (PK=`userId`, SK=`created_at`) for team "list all sessions" and client "list my sessions" queries.

**Recommendation:** Use two tables (Sessions + Audit) rather than pure single-table design. Audit table has distinct access patterns and could grow very large — keeping it separate prevents hot partition issues on the Sessions table and allows independent TTL policies. Session-related entities (Session, PipelineResults, ReviewDecision) colocate well in one table via composite SK.

---

## MVP Recommendation

Build in this order within the milestone:

**Must have (system is broken without these):**
1. DynamoDB tables created + IAM permissions added — nothing else can be done without storage
2. File-based session writes replaced with DynamoDB writes — stops data loss
3. Cognito User Pool + two groups (`team`, `client`) created
4. JWT verification middleware on all FastAPI routes — closes the open API security gap
5. Role enforcement in route handlers — separates team and client access
6. CORS lockdown to frontend domain
7. Rate limiting via slowapi
8. Input validation (transcript size cap)
9. Frontend Amplify v6 login/logout flow
10. Migration script for existing file sessions

**Build in this milestone if capacity allows:**
- Audit trail table + write events at action points
- TTL on IN_PROGRESS sessions
- Optimistic locking on session updates

**Defer to next milestone:**
- HttpOnly cookie token storage (requires Managed Login flow change, separate effort)
- Self-service user invitation UI
- DynamoDB Streams-based audit trail
- Per-assessment presigned access for clients

---

## Sources

- **FastAPI CORS official docs:** https://fastapi.tiangolo.com/tutorial/cors/ (HIGH confidence — official, fetched directly)
- **Cognito JWT verification:** https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html (HIGH confidence — official AWS docs)
- **Cognito user pool groups:** https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-user-groups.html (HIGH confidence — official AWS docs)
- **boto3 DynamoDB programming guide:** https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/programming-with-python.html (HIGH confidence — official AWS docs)
- **DynamoDB on-demand vs provisioned (Nov 2024 price cut):** https://aws.amazon.com/blogs/database/demystifying-amazon-dynamodb-on-demand-capacity-mode/ (MEDIUM confidence — AWS blog)
- **FastAPI + Cognito JWT pattern:** https://www.angelospanag.me/blog/verifying-a-json-web-token-from-cognito-in-python-and-fastapi (MEDIUM confidence — verified against official docs)
- **Amplify HttpOnly cookies for Next.js (March 2025):** https://aws.amazon.com/about-aws/whats-new/2025/03/aws-amplify-httponly-cookies-server-rendered-next-js-applications/ (HIGH confidence — official AWS announcement)
- **DynamoDB optimistic locking best practices:** https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BestPractices_ImplementingVersionControl.html (HIGH confidence — official AWS docs)
- **slowapi rate limiter for FastAPI/Starlette:** https://github.com/laurentS/slowapi (MEDIUM confidence — official repo, widely used)
- **FastAPI behind proxy (App Runner):** https://fastapi.tiangolo.com/advanced/behind-a-proxy/ (HIGH confidence — official FastAPI docs)
- **DynamoDB TTL conditional update example:** https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/example_dynamodb_UpdateItemConditionalTTL_section.html (HIGH confidence — official AWS docs)
- **Amplify v6 Next.js server-side rendering:** https://docs.amplify.aws/react/build-a-backend/server-side-rendering/ (HIGH confidence — official Amplify docs)
