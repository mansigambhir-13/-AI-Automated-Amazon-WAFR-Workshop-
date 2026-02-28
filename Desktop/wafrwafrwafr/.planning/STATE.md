# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-27)

**Core value:** Every WAFR assessment session is durably stored, only accessible to authorized users, and the backend API is protected from unauthorized access and abuse.
**Current focus:** Phase 2 — Storage Migration

## Current Position

Phase: 2 of 5 (Storage Migration)
Plan: 3 of 3 in current phase
**Current Plan:** 02-03
**Total Plans in Phase:** 3
Status: Ready to execute
Last activity: 2026-02-28 — Completed 02-02 (dead deployment.entrypoint blocks removed from server.py, REVIEW_STORAGE_TYPE env var confirmed, pipeline results and transcripts routed to DynamoDB storage)

Progress: [███░░░░░░░] 21%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: 6 min
- Total execution time: 0.3 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure-foundation | 1 | 7 min | 7 min |
| 02-storage-migration | 2 | 13 min | 6.5 min |

**Recent Trend:**
- Last 5 plans: 01-01 (7 min), 02-01 (5 min), 02-02 (8 min)
- Trend: stable

*Updated after each plan completion*
| Phase 01-infrastructure-foundation P02 | 2 | 2 tasks | 2 files |
| Phase 01-infrastructure-foundation P01-03 | 10 | 2 tasks | 5 files |
| Phase 02-storage-migration P01 | 5 | 1 task | 1 file |
| Phase 02-storage-migration P02 | 8 | 2 tasks | 2 files |

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

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 4]: Amplify v6 documents Next.js support up to 15.x; project uses 16.1.6 — must verify compatibility before writing any frontend auth code. Fallback: amazon-cognito-identity-js directly.
- [Phase 4]: NEXT_PUBLIC_* variables are baked at build time in Next.js but App Runner injects at runtime — must verify env vars are available during App Runner build step.
- [02-01 resolved]: Session JSON file sizes confirmed in research — 77-147KB after stripping report_base64; S3 offload for transcripts is locked decision but not size-driven for current data.

## Session Continuity

Last session: 2026-02-28
Stopped at: Completed 02-02-PLAN.md (dead deployment.entrypoint blocks removed from server.py, factory **kwargs added, pipeline results and transcripts routed to DynamoDB storage via hasattr guards)
Resume file: None
