---
phase: 01-infrastructure-foundation
plan: 01
subsystem: database
tags: [dynamodb, aws-cli, pitr, ttl, gsi, on-demand]

# Dependency graph
requires: []
provides:
  - "wafr-sessions DynamoDB table (PK: session_id, SK: created_at) with user_id-created_at-index GSI, TTL on expires_at, PITR"
  - "wafr-review-sessions DynamoDB table (PK: session_id, SK: item_id) with status-created_at-index GSI, TTL on expires_at, PITR"
  - "wafr-users DynamoDB table (PK: user_id) with email-index GSI, PITR, no TTL"
  - "wafr-audit-log DynamoDB table (PK: user_id, SK: timestamp_session_id) with session_id-timestamp-index GSI, PITR, no TTL"
affects: [02-storage-migration, 03-auth-backend, 04-auth-frontend, 05-security-hardening]

# Tech tracking
tech-stack:
  added: [dynamodb, aws-cli]
  patterns:
    - "All DynamoDB tables use PAY_PER_REQUEST (on-demand) billing — no capacity planning required"
    - "TTL on session tables via expires_at attribute — application sets Unix timestamp at write time"
    - "PITR enabled on all tables — 35-day point-in-time restore window"
    - "Composite sort key for audit log: timestamp_session_id (underscore, not hash) — hash reserved in DynamoDB expression syntax"
    - "GSI attribute definitions must include ALL key attributes (base table + GSI) to avoid ValidationException"

key-files:
  created:
    - ".planning/phases/01-infrastructure-foundation/infra-records/task-01-session-tables.md"
    - ".planning/phases/01-infrastructure-foundation/infra-records/task-02-user-audit-tables.md"
  modified: []

key-decisions:
  - "PAY_PER_REQUEST billing on all four tables — matches App Runner scale-to-zero profile, no idle charges"
  - "timestamp_session_id (underscore) used as sort key for wafr-audit-log — hash character # is reserved in DynamoDB expression syntax"
  - "TTL attribute is expires_at on session tables — application code in Phase 2 computes Unix epoch value at write time"
  - "wafr-users and wafr-audit-log have no TTL — user records and audit trails retained indefinitely per locked decision"

patterns-established:
  - "wait table-exists before update-time-to-live or update-continuous-backups — tables must be ACTIVE first"
  - "All GSI key attributes must appear in --attribute-definitions on create-table"

requirements-completed: [OPER-03]

# Metrics
duration: 7min
completed: 2026-02-28
---

# Phase 1 Plan 01: DynamoDB Table Provisioning Summary

**Four PAY_PER_REQUEST DynamoDB tables in us-east-1 with correct key schemas, GSIs, TTL on session tables, and PITR on all tables**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-28T05:44:30Z
- **Completed:** 2026-02-28T05:52:01Z
- **Tasks:** 2 of 2
- **Files modified:** 2 (infra tracking records)

## Accomplishments

- Created wafr-sessions (PK: session_id/SK: created_at) with user_id-created_at-index GSI, TTL on expires_at, PITR ENABLED
- Created wafr-review-sessions (PK: session_id/SK: item_id) with status-created_at-index GSI, TTL on expires_at, PITR ENABLED
- Created wafr-users (PK: user_id) with email-index GSI, PITR ENABLED, no TTL
- Created wafr-audit-log (PK: user_id/SK: timestamp_session_id) with session_id-timestamp-index GSI, PITR ENABLED, no TTL
- All tables verified ACTIVE with PAY_PER_REQUEST billing in us-east-1

## Task Commits

Each task was committed atomically:

1. **Task 1: Create wafr-sessions and wafr-review-sessions DynamoDB tables** - `ccde629` (feat)
2. **Task 2: Create wafr-users and wafr-audit-log DynamoDB tables** - `c138ea4` (feat)

**Plan metadata:** `[pending]` (docs: complete plan — committed with STATE.md, ROADMAP.md)

## Files Created/Modified

- `.planning/phases/01-infrastructure-foundation/infra-records/task-01-session-tables.md` - Provisioning record for session tables with ARNs, schemas, and verification status
- `.planning/phases/01-infrastructure-foundation/infra-records/task-02-user-audit-tables.md` - Provisioning record for user and audit tables with ARNs, schemas, and design notes

## Decisions Made

- **PAY_PER_REQUEST billing** — App Runner scale-to-zero profile means traffic is bursty/idle; on-demand billing avoids idle charges
- **timestamp_session_id (underscore)** — The `#` character is reserved in DynamoDB expression syntax; underscore used as composite separator. Application code in Phase 2 will write values like `2026-02-28T12:00:00Z_sess-abc123`
- **TTL attribute naming: expires_at** — Application sets Unix epoch timestamp at write time. 365-day TTL per locked decision

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all AWS CLI commands succeeded on first attempt. The research pitfalls (TTL/PITR require ACTIVE status, GSI attributes must be in --attribute-definitions) were followed proactively.

## User Setup Required

None - no external service configuration required. Tables are immediately accessible from the AWS account with appropriate IAM permissions.

## Next Phase Readiness

- All four DynamoDB tables are ACTIVE and ready for Plan 01-02 (Cognito User Pool creation)
- Tables are ready for Phase 2 (Storage Migration) — application code can target these tables
- IAM role (WafrAppRunnerInstanceRole) still needs DynamoDB permissions — covered in Plan 01-03
- Note for Phase 2: wafr-audit-log sort key is `timestamp_session_id` (underscore separator), not `timestamp#session_id`

---
*Phase: 01-infrastructure-foundation*
*Completed: 2026-02-28*
