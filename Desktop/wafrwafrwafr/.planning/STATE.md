# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-27)

**Core value:** Every WAFR assessment session is durably stored, only accessible to authorized users, and the backend API is protected from unauthorized access and abuse.
**Current focus:** Phase 1 — Infrastructure Foundation

## Current Position

Phase: 1 of 5 (Infrastructure Foundation)
Plan: 1 of 3 in current phase
**Current Plan:** 2
**Total Plans in Phase:** 3
Status: Ready to execute
Last activity: 2026-02-28 — Completed 01-02 (Cognito User Pool, App Client, and RBAC groups)

Progress: [█░░░░░░░░░] 7%

## Performance Metrics

**Velocity:**
- Total plans completed: 1
- Average duration: 7 min
- Total execution time: 0.1 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure-foundation | 1 | 7 min | 7 min |

**Recent Trend:**
- Last 5 plans: 01-01 (7 min)
- Trend: —

*Updated after each plan completion*
| Phase 01-infrastructure-foundation P02 | 2 | 2 tasks | 2 files |

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

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 4]: Amplify v6 documents Next.js support up to 15.x; project uses 16.1.6 — must verify compatibility before writing any frontend auth code. Fallback: amazon-cognito-identity-js directly.
- [Phase 4]: NEXT_PUBLIC_* variables are baked at build time in Next.js but App Runner injects at runtime — must verify env vars are available during App Runner build step.
- [Phase 2]: Existing session JSON file sizes in /review_sessions/ are unknown — must measure 3-5 files before writing migration code to confirm whether S3 offload for transcripts is mandatory.

## Session Continuity

Last session: 2026-02-28
Stopped at: Completed 01-02-PLAN.md (Cognito User Pool wafr-user-pool — us-east-1_U4ugKPUrh, App Client wafr-app-client — 65fis729feu3lr317rm6oaue5s, Groups WafrTeam + WafrClients)
Resume file: None
