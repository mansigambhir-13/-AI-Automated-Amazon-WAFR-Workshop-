# Project Research Summary

**Project:** WAFR Assessment Platform — DynamoDB + Cognito + API Security Milestone
**Domain:** Production authentication, persistent storage, and API hardening for a FastAPI + Next.js SaaS assessment tool on AWS App Runner
**Researched:** 2026-02-27
**Confidence:** HIGH

## Executive Summary

The WAFR Assessment Platform is an existing FastAPI + Next.js application deployed on AWS App Runner that currently has three production-critical defects: all data is stored in files that are wiped on every container restart/redeploy, all API endpoints are completely unauthenticated and open to the internet, and CORS is set to wildcard allowing any origin. This milestone is purely additive — it layers DynamoDB persistence, Cognito JWT authentication, and API security hardening onto the existing App Runner deployment without any infrastructure migration. The project is an extension, not a rewrite; every architectural decision is constrained by the requirement to keep App Runner as-is.

The recommended approach is a five-phase implementation ordered by dependencies: infrastructure first (DynamoDB tables + Cognito User Pool), then storage migration (replace file I/O with DynamoDB), then backend auth middleware (JWT verification, CORS lockdown, rate limiting), then frontend auth integration (Amplify v6), then data migration and audit trail activation. This order allows each phase to be deployed and validated independently without breaking the existing unauthenticated flow — specifically via a backend `AUTH_REQUIRED` feature flag that lets the storage migration go live before the frontend sends tokens. PyJWT 2.11.0 (not python-jose, which has an archived dependency chain) and slowapi 0.1.9 are the library choices; aws-amplify v6 handles the frontend Cognito integration with the existing Next.js App Router.

The top risks are: (1) the existing broken DynamoDB import (`No module named 'deployment'`) indicates a Python path problem that will recur if new storage code follows the same pattern — all new code must go inside the existing `wafr/storage/` package; (2) WAFR pipeline results and transcripts will exceed DynamoDB's 400KB item limit — transcripts must be stored in S3, results split across multiple items; (3) FastAPI middleware ordering is counterintuitive — CORS must be registered last in code so it executes first on requests, or auth 401 responses will arrive at the browser without CORS headers, creating misleading CORS errors on SSE endpoints. These risks are all preventable if addressed at the design stage rather than discovered during implementation.

---

## Key Findings

### Recommended Stack

See full details: `.planning/research/STACK.md`

The stack is almost entirely determined by what already exists — this is an additive milestone, not a greenfield project. The backend already runs Python FastAPI with boto3, pydantic v2, and uvicorn; the frontend already runs Next.js + React + Tailwind + Radix UI. New dependencies are minimal and chosen specifically to avoid common traps in this ecosystem.

**Core technologies:**
- `boto3` (already present, 1.34.0+): Synchronous DynamoDB CRUD via Resource API — preferred over aioboto3 for simplicity since DynamoDB calls are not the bottleneck (AI pipeline dominates latency)
- `PyJWT 2.11.0` with `[crypto]` extra: Cognito RS256 JWT verification using built-in `PyJWKClient` with automatic JWKS caching — chosen explicitly over `python-jose` / `fastapi-cognito` because those libraries depend on the archived `cognitojwt` package, which is a security liability in an auth code path
- `slowapi 0.1.9`: Per-endpoint rate limiting via Starlette middleware decorator — the only correct approach given the App Runner constraint (API Gateway and WAF are ruled out by PROJECT.md)
- `pydantic-settings 2.13.1`: Type-safe config management for all new environment variables (Cognito pool IDs, table names, region) — native to the pydantic v2 already in use
- `aws-amplify 6.16.2` + `@aws-amplify/adapter-nextjs` + `@aws-amplify/ui-react`: Frontend Cognito integration — the only library with first-class Next.js App Router + Cognito cookie-token support and a ready-made Authenticator UI component

**DynamoDB design:** Multi-table (not single-table) with on-demand (pay-per-request) capacity. Four tables: `wafr-sessions`, `wafr-review-sessions`, `wafr-users`, `wafr-audit-log`. Access patterns are not yet stable enough to justify single-table optimization.

**Critical open item:** Amplify v6 documents Next.js support up to 15.x; the project uses 16.1.6. This must be verified before writing any frontend auth code. Fallback: `amazon-cognito-identity-js` directly.

### Expected Features

See full details: `.planning/research/FEATURES.md`

**Must have (table stakes — system is broken or insecure without these):**
- JWT verification middleware on every FastAPI route — closes the wide-open API (zero auth today)
- Cognito User Pool with `WafrTeam` and `WafrClients` groups — RBAC is a hard requirement
- DynamoDB persistence for assessment sessions — data loss on every redeploy is a confirmed production bug
- CORS lockdown from wildcard to the frontend App Runner URL only
- Role enforcement in route handlers — JWT validation alone does not enforce RBAC
- Rate limiting on all endpoints (especially POST /api/wafr/run which invokes Bedrock)
- Input validation (transcript size cap, ~500KB) — unbounded input risks memory exhaustion and Bedrock cost blowout
- Audit trail — who ran which assessment and when (compliance requirement for enterprise clients)
- Session ownership filtering — clients must only see their own sessions; team sees all
- Frontend login/logout flow via Amplify v6
- Migration script for existing file-based sessions

**Should have (capacity allows in this milestone):**
- DynamoDB TTL on IN_PROGRESS sessions (automatic cleanup, zero-effort maintenance)
- Optimistic locking on session updates (prevents race conditions on concurrent writes)
- CloudWatch structured logging with correlation IDs per session

**Defer to next milestone:**
- HttpOnly cookie token storage (requires Managed Login flow change — separate effort)
- Self-service user invitation UI (AdminCreateUser + SES, non-trivial)
- DynamoDB Streams-based audit trail (operational complexity not justified for v1)
- Per-assessment presigned access for clients (major scope, custom token logic)
- OAuth social login (explicitly deferred to v2 in PROJECT.md)

**Anti-features (deliberately excluded):**
- Custom JWT signing or home-rolled auth (security incident waiting to happen)
- API Gateway in front of App Runner (explicitly ruled out; also breaks SSE streaming at 29-second timeout)
- Storing JWTs in DynamoDB (wrong abstraction — tokens are not data)
- DynamoDB provisioned capacity with auto-scaling (on-demand is correct for variable WAFR workloads)

### Architecture Approach

See full details: `.planning/research/ARCHITECTURE.md`

The architecture is a layered middleware addition to the existing FastAPI app with no deployment topology changes. Requests flow: Browser → Cognito (auth) → Next.js Frontend → FastAPI Backend (CORS → Rate Limit → JWT Auth → Route Handler) → DynamoDB / S3 / Bedrock / AWS WA Tool. Auth is implemented as FastAPI dependency injection (`get_current_user`) applied per-route, not as a global middleware, which allows the `/health` endpoint to stay unauthenticated for App Runner health checks. The existing `ReviewStorage` abstract class provides a clean seam for adding `DynamoDBReviewStorage` as a drop-in for `FileReviewStorage`, controlled by the `REVIEW_STORAGE_TYPE` environment variable.

**Major components:**
1. Cognito User Pool — user identity, JWT issuance, group membership (`WafrTeam` / `WafrClients`); source of truth for auth
2. FastAPI Middleware Stack — CORS (executes first), SlowAPI rate limiting (executes second), JWT auth dependency (per-route); enforces all security policy
3. DynamoDB Storage Layer — `DynamoDBReviewStorage` implementing existing `ReviewStorage` interface; four tables with GSI on `UserSessionsIndex` for efficient user-scoped session listing
4. Next.js Frontend Auth — Amplify v6 `<Authenticator>` component wrapping the app; `fetchAuthSession()` in `api.ts` attaches access token as Bearer header on every request
5. Backward-Compatible Rollout Toggle — `AUTH_REQUIRED=false/true` environment variable allows backend auth to be deployed before frontend is ready, eliminating the need for atomic backend+frontend deployment

**Key patterns:**
- JWKS caching in-memory at startup via `PyJWKClient`; refresh only on `kid` miss — prevents ~100ms latency on every request
- User-scoped session reads: client role always filtered by `owner_user_id`; team bypasses filter; enforced in service layer not just frontend
- Middleware registration order in FastAPI is reverse of execution order — CORS added last in code executes first on requests

### Critical Pitfalls

See full details: `.planning/research/PITFALLS.md`

1. **SSE breaks with CORS/auth middleware ordering** — Auth 401 responses returned before CORS middleware adds headers cause the browser to report a CORS error instead of an auth error, masking the real problem on SSE endpoints. Prevention: register `CORSMiddleware` last in code (it executes first on requests); auth dependency runs per-route, never as global middleware that intercepts SSE.

2. **DynamoDB 400KB item size limit on pipeline results** — WAFR pipeline results (100+ questions across 5 pillars with confidence scores) will exceed the hard DynamoDB 400KB limit. Prevention: measure existing session JSON files before writing migration code; store raw transcripts in S3 (key in DynamoDB); split pipeline results into multiple items by agent/pillar using composite sort keys.

3. **Algorithm confusion attack on JWT validation** — JWT libraries that accept "any algorithm" or default to HS256 will accept tokens forged using the publicly available Cognito JWKS public key as an HS256 symmetric secret. Prevention: always explicitly specify `algorithms=["RS256"]` in every `jwt.decode()` call; never omit.

4. **ID token vs access token confusion** — Using Cognito's ID token for API authorization (instead of access token) breaks `aud` claim validation and doesn't carry OAuth scopes. Prevention: validate `token_use == "access"` in every backend token verification; frontend must use `session.tokens.accessToken.toString()` not `idToken`.

5. **Float type rejection by boto3 DynamoDB** — WAFR scoring agents produce Python `float` values; boto3 raises `TypeError` for any `float` in DynamoDB writes (only `Decimal` and `int` are accepted). Prevention: implement a recursive `floats_to_decimal()` converter applied to all data before every `put_item` / `update_item`; add a reverse converter for reads (FastAPI JSON encoder also doesn't handle `Decimal` by default).

6. **Existing broken `No module named 'deployment'` import** — New DynamoDB code following the same broken import pattern will fail identically in App Runner. Prevention: all new storage code goes in `wafr/storage/` alongside the existing working code; fix PYTHONPATH before any new module introduction.

---

## Implications for Roadmap

Based on combined research, the dependency chain is strict and non-negotiable: AWS infrastructure must exist before any application code can be tested, storage must work before auth is layered on top, backend auth must be deployed before the frontend can send real tokens. The five-phase structure below directly maps to that dependency graph.

### Phase 1: Infrastructure Foundation

**Rationale:** Everything else depends on this. DynamoDB tables and Cognito User Pool must exist before a single line of application code can be validated. This phase has zero code changes to the application — pure AWS resource provisioning. Doing it first allows developers to test each subsequent phase against real AWS services immediately.

**Delivers:** DynamoDB tables (`wafr-sessions`, `wafr-review-sessions`, `wafr-users`, `wafr-audit-log`) with correct schema and GSIs; Cognito User Pool with App Client (no client secret — public client); `WafrTeam` and `WafrClients` groups; updated `WafrAppRunnerInstanceRole` IAM policy scoped to `arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*`; backend environment variables set in App Runner (Cognito pool IDs, table names, `AUTH_REQUIRED=false`).

**Addresses:** IAM permission completeness (Pitfall 12), Cognito config staleness after rotation (Pitfall 8).

**Avoids:** Touching application code while AWS resources don't exist yet — prevents false-positive test failures.

**Research flag:** Well-documented, standard patterns — no additional research needed. AWS Console or CloudFormation/CDK both work; IaC is preferred for reproducibility.

### Phase 2: Storage Migration

**Rationale:** Data loss on redeploy is the most impactful production bug. Fixing it is independent of auth — DynamoDB storage can go live with `AUTH_REQUIRED=false` and the existing unauthenticated flow continues working. Validating storage in isolation before adding auth complexity reduces debugging surface area.

**Delivers:** `DynamoDBReviewStorage` class implementing existing `ReviewStorage` interface; updated `create_review_storage()` factory controlled by `REVIEW_STORAGE_TYPE=dynamodb`; float-to-Decimal converter at the storage boundary; migration script for existing file sessions; backend deployed with DynamoDB active and auth still bypassed.

**Uses:** `boto3` Resource API (already present); synchronous implementation (not aioboto3 — AI pipeline dominates latency, DynamoDB calls are not the bottleneck).

**Avoids:** DynamoDB 400KB item limit (Pitfall 3) — measure existing session files first, S3 offload for transcripts if needed; float type rejection (Pitfall 6) — converter required; broken import pattern (Pitfall 13) — new code in `wafr/storage/` only.

**Research flag:** Standard boto3 patterns — well-documented. The item-size measurement step is required before writing code; this is a one-off verification, not ongoing research.

### Phase 3: Backend Auth and API Security

**Rationale:** Once storage is validated, add the security layer. Backend auth is deployed with `AUTH_REQUIRED=false` initially, then flipped to `true` once the frontend (Phase 4) is verified sending tokens. This eliminates the need for atomic backend+frontend deployment. All security hardening goes in one phase — CORS, rate limiting, input validation, and JWT middleware are all middleware-layer concerns that share the same testing surface.

**Delivers:** `get_current_user` FastAPI dependency using PyJWT 2.11.0 with JWKS caching; `require_team` role guard applied to write endpoints; CORS locked to frontend App Runner URL (exact string, no trailing slash); slowapi rate limiting (10/min on AI endpoints, 60/min on review decisions); transcript max_length=500,000 Pydantic validation; audit trail writes at key action points; `AUTH_REQUIRED` toggle set to `true` after Phase 4 validation.

**Uses:** `PyJWT[crypto] 2.11.0`, `slowapi 0.1.9`, `pydantic-settings 2.13.1`, FastAPI `CORSMiddleware` (built-in).

**Avoids:** CORS/auth middleware ordering bug (Pitfall 1) — CORS registered last in code; algorithm confusion attack (Pitfall 5) — `algorithms=["RS256"]` explicit; ID vs access token (Pitfall 4) — `token_use == "access"` validated; cognito:groups vs cognito:roles confusion (Pitfall 7) — use `cognito:groups`; rate limit bypass under multi-instance (Pitfall 9) — document App Runner min instances = 1.

**Research flag:** JWT validation, CORS, and rate limiting are all well-documented patterns. No additional research needed — STACK.md and PITFALLS.md provide complete implementation detail including code examples.

### Phase 4: Frontend Auth Integration

**Rationale:** Frontend must come after Phase 1 (Cognito pool exists) and Phase 3 (backend accepts and validates tokens). This is the only phase with frontend code changes. Amplify v6 compatibility with Next.js 16 must be verified before writing any code — this is the single highest-risk open item in the entire milestone.

**Delivers:** Amplify v6 configured against existing Cognito User Pool (`ssr: true` for cookie-based token storage); `<Authenticator>` component wrapping `layout.tsx`; `api.ts` updated to call `fetchAuthSession()` and attach `Authorization: Bearer <access_token>` header on all requests; 401 interceptor that triggers token refresh and redirects to login on persistent failure; Cognito access token TTL set to 8 hours (mitigates Amplify silent refresh bug); visibility-change refresh trigger.

**Uses:** `aws-amplify 6.16.2`, `@aws-amplify/adapter-nextjs`, `@aws-amplify/ui-react`; `NEXT_PUBLIC_*` environment variables in App Runner frontend service.

**Avoids:** Sending ID token instead of access token (Pitfall 11) — explicit `session.tokens.accessToken.toString()` usage; Amplify silent refresh bug (Pitfall 14) — 8-hour TTL + visibility-change trigger + 401 retry interceptor; NEXT_PUBLIC variable injection issue (Stack open item 2) — verify build-time vs runtime availability in App Runner.

**Research flag:** Amplify v6 + Next.js 16 compatibility is a REQUIRED validation step before implementation. If Amplify v6 does not support Next.js 16, fallback is `amazon-cognito-identity-js` directly — more boilerplate but fully supported. This is the only phase that may need ad-hoc research.

### Phase 5: Data Migration and Audit Validation

**Rationale:** Final phase runs the one-time migration of existing file-based sessions into DynamoDB, activates `AUTH_REQUIRED=true` to enforce authentication end-to-end, and validates the audit trail is capturing all required events. Short but critical — skipping it leaves production data in files and leaves the auth bypass open.

**Delivers:** All existing `/review_sessions/*.json` files imported to DynamoDB with `ConditionExpression='attribute_not_exists(session_id)'` to prevent duplicates; `AUTH_REQUIRED=true` set in App Runner backend environment; audit log entries verified for session create, assessment run, review decision, and report generation events; end-to-end smoke test: login as team user → run assessment → view results → login as client user → verify session isolation.

**Avoids:** Data loss on migration (idempotent migration script with condition expression); client accessing another client's sessions (session ownership filter verified in smoke test).

**Research flag:** No research needed — this is operational execution of patterns established in Phases 2-4.

### Phase Ordering Rationale

- **Infrastructure first** because DynamoDB tables and Cognito must exist before any application code can be tested against real AWS services; there are no meaningful unit tests for this milestone's core value.
- **Storage before auth** because the data-loss bug is the highest-severity production issue and can be fixed independently; it also simplifies debugging (one variable at a time).
- **Backend auth before frontend** because the backend can be tested with real Cognito tokens using curl/Postman without any frontend changes; the `AUTH_REQUIRED` flag allows safe, incremental exposure.
- **Frontend last** because it depends on both Cognito (Phase 1) and the backend accepting tokens (Phase 3); it's also the highest-risk phase due to the Amplify/Next.js 16 compatibility question.
- **Migration and validation last** because it requires all prior phases to be working correctly; running the migration script on a broken system would corrupt the data transition.

### Research Flags

Phases needing verification during implementation:
- **Phase 4 (Frontend Auth):** Amplify v6 compatibility with Next.js 16.1.6 must be verified before writing code. Check [Amplify JS releases](https://github.com/aws-amplify/amplify-js/releases) and the `@aws-amplify/adapter-nextjs` changelog. If incompatible, evaluate `amazon-cognito-identity-js` as fallback.
- **Phase 4 (Frontend Auth):** Verify that `NEXT_PUBLIC_*` environment variables are available at build time in App Runner. App Runner injects env vars at runtime; Next.js bakes `NEXT_PUBLIC_*` at build time. May need a config API endpoint pattern or build-time environment injection via App Runner build configuration.
- **Phase 2 (Storage Migration):** Measure 3-5 existing session JSON files for size before writing migration code. If any approach 300KB, the S3 offload strategy for transcripts is mandatory, not optional.

Phases with well-documented patterns (no additional research needed):
- **Phase 1 (Infrastructure):** DynamoDB table creation, Cognito User Pool setup, and IAM policies are all standard AWS Console/IaC operations with thorough official documentation.
- **Phase 3 (Backend Auth):** PyJWT, slowapi, CORS middleware, and pydantic-settings are all well-documented. STACK.md and PITFALLS.md provide complete implementation code.
- **Phase 5 (Migration):** One-time operational script; patterns established in Phase 2.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library choices verified against official PyPI / npm / AWS docs; versions confirmed; alternatives explicitly evaluated and rejected with documented reasoning |
| Features | HIGH | Table-stakes features derived directly from official AWS Cognito and FastAPI docs; DynamoDB access patterns verified against official AWS documentation; feature triage is opinionated but grounded in PROJECT.md constraints |
| Architecture | HIGH | All component boundaries and data flows verified against official FastAPI, boto3, and Amplify documentation; middleware ordering behavior confirmed via official FastAPI docs |
| Pitfalls | HIGH (critical), MEDIUM (minor) | Critical pitfalls (SSE/CORS ordering, 400KB limit, algorithm confusion, float types) are all verified against official documentation or long-standing confirmed bugs; minor pitfalls (Amplify silent refresh, App Runner secrets rotation) have MEDIUM confidence based on confirmed GitHub issues and official AWS documentation |

**Overall confidence:** HIGH

### Gaps to Address

- **Amplify v6 + Next.js 16 compatibility:** The documented Amplify v6 support range is Next.js 13.5–15.x. The project uses 16.1.6. This is the single largest open question in the milestone. Resolution: check Amplify JS GitHub releases at implementation time. Fallback path (`amazon-cognito-identity-js`) is well-understood and ready to use.

- **NEXT_PUBLIC_* variable injection in App Runner:** Next.js bakes `NEXT_PUBLIC_*` variables at build time, but App Runner injects environment variables at runtime. If the App Runner build step doesn't have access to these variables, the Cognito config will be blank in production. Resolution: test with a deploy to App Runner before writing the full auth integration; consider a `GET /api/config` endpoint that returns non-secret config to the frontend at runtime as a fallback.

- **Existing session file sizes:** The 400KB DynamoDB limit analysis assumes typical WAFR session sizes, but actual sizes in production `/review_sessions/` are unknown. Resolution: measure before migrating; this is a one-step pre-migration check, not ongoing research.

- **App Runner min instances configuration:** Slowapi in-memory rate limiting requires min instances = 1 to function correctly. If the current App Runner service is configured with min instances = 0 (scale to zero), rate limiting is per-instance and ineffective at scale. Resolution: confirm current App Runner configuration; document the constraint in deployment notes.

---

## Sources

### Primary (HIGH confidence)
- [AWS Cognito JWT verification official docs](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) — JWT validation requirements, token types, claims
- [boto3 DynamoDB programming guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/programming-with-python.html) — Resource vs Client API, DynamoDB operations
- [DynamoDB large item best practices](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-use-s3-too.html) — 400KB limit and S3 offload pattern
- [Cognito RBAC with Groups](https://docs.aws.amazon.com/cognito/latest/developerguide/role-based-access-control.html) — cognito:groups claim behavior
- [Amplify JS — Use Existing Cognito Resources](https://docs.amplify.aws/nextjs/build-a-backend/auth/use-existing-cognito-resources/) — non-Amplify-backend configuration pattern
- [Amplify adapter-nextjs — App Router server components](https://docs.amplify.aws/javascript/build-a-backend/server-side-rendering/nextjs-app-router-server-components/) — cookie-based token storage
- [PyJWT docs v2.11.0 — PyJWKClient](https://pyjwt.readthedocs.io/en/latest/usage.html) — JWKS-based token verification
- [FastAPI CORS documentation](https://fastapi.tiangolo.com/tutorial/cors/) — CORSMiddleware, middleware ordering
- [FastAPI behind a proxy](https://fastapi.tiangolo.com/advanced/behind-a-proxy/) — App Runner proxy header handling
- [boto3 GitHub Issue #369 — Float types not supported](https://github.com/boto/boto3/issues/369) — DynamoDB float/Decimal constraint

### Secondary (MEDIUM confidence)
- [Angelos Panagiotopoulos — FastAPI + Cognito JWT guide](https://www.angelospanag.me/blog/verifying-a-json-web-token-from-cognito-in-python-and-fastapi) — JWT validation pitfall enumeration; consistent with official docs
- [slowapi GitHub](https://github.com/laurentS/slowapi) — Rate limiting for FastAPI/Starlette
- [DynamoDB Single-Table vs Multi-Table — AWS Blog](https://aws.amazon.com/blogs/database/single-table-vs-multi-table-design-in-amazon-dynamodb/) — Table design decision rationale
- [FastAPI middleware ordering — Medium](https://medium.com/@saurabhbatham17/navigating-middleware-ordering-in-fastapi-a-cors-dilemma-8be88ab2ee7b) — CORS + auth middleware ordering behavior
- [AWS App Runner + Secrets Manager integration](https://aws.amazon.com/blogs/containers/aws-app-runner-now-integrates-with-aws-secrets-manager-and-aws-systems-manager-parameter-store/) — Secrets not auto-rotated on container restart
- [Amplify silent refresh bug — GitHub Issue #14406](https://github.com/aws-amplify/amplify-js/issues/14406) — Confirmed open bug in Amplify v6 token refresh

### Tertiary (LOW confidence)
- None — all findings have at least MEDIUM confidence grounding.

---
*Research completed: 2026-02-27*
*Ready for roadmap: yes*
