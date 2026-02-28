# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-27)

**Core value:** Every WAFR assessment session is durably stored, only accessible to authorized users, and the backend API is protected from unauthorized access and abuse.
**Current focus:** Phase 3 complete — ready for Phase 4

## Current Position

Phase: 3 of 5 (Backend Auth and API Security) — COMPLETE
Plan: 3 of 3 complete
**Total Plans in Phase:** 3
Status: Phase 3 verified (5/5 must-haves). JWT auth, CORS lockdown, rate limiting, input validation, audit trail all wired.
Last activity: 2026-02-28 — Phase 3 verification passed, marked complete

Progress: [██████░░░░] 60%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: 6 min
- Total execution time: 0.3 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure-foundation | 1 | 7 min | 7 min |
| 02-storage-migration | 3 | 17 min | 5.7 min |

**Recent Trend:**
- Last 5 plans: 01-01 (7 min), 02-01 (5 min), 02-02 (8 min), 02-03 (4 min)
- Trend: stable

*Updated after each plan completion*
| Phase 01-infrastructure-foundation P02 | 2 | 2 tasks | 2 files |
| Phase 01-infrastructure-foundation P01-03 | 10 | 2 tasks | 5 files |
| Phase 02-storage-migration P01 | 5 | 1 task | 1 file |
| Phase 02-storage-migration P02 | 8 | 2 tasks | 2 files |
| Phase 02-storage-migration P03 | 4 | 1 task | 1 file |
| Phase 03-backend-auth-and-api-security P01 | 6 | 2 tasks | 4 files |
| Phase 03-backend-auth-and-api-security P02 | 5 | 2 tasks | 4 files |
| Phase 03-backend-auth-and-api-security P03 | 3 | 2 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: All new storage code goes in `wafr/storage/` to avoid the existing `No module named 'deployment'` PYTHONPATH failure
- [Roadmap]: CORS middleware registered last in FastAPI code (executes first on requests) to prevent auth 401 responses arriving at browser without CORS headers
- [Roadmap]: PyJWT 2.11.0 chosen over python-jose/fastapi-cognito — python-jose depends on archived cognitojwt package
- [Roadmap]: AUTH_REQUIRED environment flag enables deploying backend auth before frontend is ready (no atomic deployment needed)
- [01-01]: PAY_PER_REQUEST billing on all four DynamoDB tables — matches App Runner scale-to-zero profile, no idle charges
- [01-01]: timestamp_session_id (underscore) used as sort key for wafr-audit-log — hash character # is reserved in DynamoDB expression syntax
- [01-01]: expires_at TTL attribute on wafr-sessions and wafr-review-sessions — application code sets Unix epoch at write time; 365-day TTL per locked decision
- [01-01]: wafr-users and wafr-audit-log have no TTL — user records and audit trails retained indefinitely per locked decision
- [Phase 01-02]: No client secret on App Client — public client required for Amplify frontend (browser cannot store secrets securely)
- [Phase 01-02]: ALLOW_USER_SRP_AUTH only — excludes ALLOW_USER_PASSWORD_AUTH to prevent plaintext password transmission (Pitfall 5 from research)
- [Phase 01-02]: 1-hour access token validity — short-lived tokens reduce blast radius if compromised
- [Phase 01-03]: Separate secrets per Cognito value — App Runner RuntimeEnvironmentSecrets maps one secret ARN to one env var; combined JSON would require application-side parsing
- [Phase 01-03]: WafrAppRunnerInstanceRole attached to frontend App Runner — required when using RuntimeEnvironmentSecrets; uses same role as backend for consistency
- [Phase 01-03]: wafr-cognito-* wildcard in IAM SecretsManagerCognitoRead — Secrets Manager appends random 6-char suffix; wildcard covers current and future rotated secrets
- [Phase 01-03]: AUTH_REQUIRED=true set immediately on both services — per locked roadmap decision to enable auth enforcement before Phase 3 backend middleware lands
- [02-01]: 300KB S3 overflow threshold — safe headroom below 400KB DynamoDB limit; current stripped pipeline results top at 147KB so threshold is a safety valve only
- [02-01]: Pipeline results stored as JSON string attribute (not DynamoDB map) — avoids Decimal conversion on deeply nested 11-step pipeline dicts; string up to 400KB satisfies the constraint
- [02-01]: Per-item rows pattern for wafr-review-sessions — each review item as separate DynamoDB row (item_id=<review_id>), enables individual updates without rewriting whole session
- [02-01]: create_review_storage() extended with 'dynamodb' branch reading WAFR_DYNAMO_* env vars; existing 'memory' and 'file' branches untouched
- [02-02]: **kwargs added to create_review_storage() for forward-compatibility — callers may pass extra keyword args without error if signature evolves
- [02-02]: Dead deployment.entrypoint blocks fully removed from server.py (three blocks); all DynamoDB access now routes through wafr/storage/DynamoDBReviewStorage
- [02-02]: hasattr guards used for save_pipeline_results and save_transcript in server.py — method presence signals DynamoDB backend; file/memory backends silently skip
- [02-03]: sys.path manipulation prepends wafr-agents/ project root in migration script so 'from wafr.storage.review_storage import ...' works from any working directory
- [02-03]: isinstance(storage, DynamoDBReviewStorage) check after factory call confirms backend type before using non-ABC methods save_pipeline_results/load_pipeline_results
- [02-03]: Log file auto-named migration_<UTC-timestamp>.log when --log-file is not specified — preserves logs from previous runs rather than overwriting them
- [02-03]: exit(1) on any individual migration failures — allows CI to detect partial failures; exit(0) only when all items processed successfully or skipped
- [Phase 03-backend-auth-and-api-security]: HTTPBearer(auto_error=False) used — prevents default 403 on missing header; manual 401 raised per spec
- [Phase 03-backend-auth-and-api-security]: Lazy PyJWKClient init via _get_jwks_client() helper — prevents KeyError at import time when Cognito env vars not set
- [Phase 03-backend-auth-and-api-security]: req: Request added proactively to all protected endpoints — slowapi (Plan 03-03) readiness without a second server.py edit
- [Phase 03-backend-auth-and-api-security]: SlowAPIMiddleware registered before CORSMiddleware (CORS outermost) so 401/429 errors carry CORS headers
- [Phase 03-backend-auth-and-api-security]: Pydantic body params renamed to 'body'; Starlette Request named 'request' — slowapi requires parameter named exactly 'request'
- [Phase 03-backend-auth-and-api-security]: WAFR_CORS_ORIGINS env var with comma-separated origins — explicit list required when allow_credentials=True (no wildcard)
- [Phase 03-backend-auth-and-api-security]: asyncio.get_running_loop() used in AuditMiddleware (not get_event_loop()) — get_event_loop() is deprecated in Python 3.10+; RuntimeError fallback handles non-async test contexts
- [Phase 03-backend-auth-and-api-security]: AuditMiddleware is pure-ASGI class (not BaseHTTPMiddleware) — registered as innermost middleware; stack is now: AuditMiddleware -> SlowAPIMiddleware -> CORSMiddleware
- [Phase 03-backend-auth-and-api-security]: Transcript excluded from audit body on /run and /start (transcript_length field instead) — avoids DynamoDB 400KB item limit for 500K char transcripts

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 4]: Amplify v6 documents Next.js support up to 15.x; project uses 16.1.6 — must verify compatibility before writing any frontend auth code. Fallback: amazon-cognito-identity-js directly.
- [Phase 4]: NEXT_PUBLIC_* variables are baked at build time in Next.js but App Runner injects at runtime — must verify env vars are available during App Runner build step.
- [02-01 resolved]: Session JSON file sizes confirmed in research — 77-147KB after stripping report_base64; S3 offload for transcripts is locked decision but not size-driven for current data.

## Session Continuity

Last session: 2026-02-28
Stopped at: Phase 3 complete (all 3 plans executed + verified 5/5). Next: Phase 4 — Frontend Auth Integration.
Resume file: None
