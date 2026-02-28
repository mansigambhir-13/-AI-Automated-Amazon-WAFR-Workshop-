---
phase: 02-storage-migration
plan: "03"
subsystem: database
tags: [dynamodb, s3, python, cli, migration, boto3]

# Dependency graph
requires:
  - phase: 02-02-storage-migration
    provides: create_review_storage('dynamodb') factory and DynamoDBReviewStorage class with save_pipeline_results/load_pipeline_results methods
provides:
  - Standalone idempotent CLI migration script that reads file-based sessions and pipeline results and writes them to DynamoDB
affects: [05-data-migration-audit-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Check-before-write idempotency: load_session() / load_pipeline_results() called before every put to prevent duplicates on re-runs"
    - "Dual-handler logging: INFO to console, DEBUG to timestamped log file for per-session audit trail"
    - "Continue-on-failure: individual file errors are caught, logged, and counted; migration continues to next file"

key-files:
  created:
    - wafr-agents/scripts/migrate_sessions.py
  modified: []

key-decisions:
  - "sys.path manipulation prepends wafr-agents/ project root so 'from wafr.storage.review_storage import ...' works when script is run from any directory"
  - "isinstance(storage, DynamoDBReviewStorage) check after factory call confirms backend type before using non-ABC methods save_pipeline_results/load_pipeline_results"
  - "exit(1) on any individual migration failures — allows CI to detect partial failures; exit(0) only when all items processed successfully or skipped"
  - "Log file auto-named migration_<UTC-timestamp>.log when --log-file is not specified — avoids overwriting previous runs"

patterns-established:
  - "Migration script pattern: check-before-write idempotency via existing read, never delete source files, formatted summary + per-item log file"

requirements-completed: [STOR-01, STOR-02, STOR-03, OPER-02]

# Metrics
duration: 4min
completed: "2026-02-28"
---

# Phase 2 Plan 03: Storage Migration — Migration Script Summary

**Idempotent CLI script that migrates file-based review sessions and pipeline results to DynamoDB using check-before-write idempotency, --dry-run preview, and formatted summary reporting**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-28T08:56:45Z
- **Completed:** 2026-02-28T09:00:45Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `wafr-agents/scripts/migrate_sessions.py` — 369-line standalone CLI script
- Idempotent via `load_session()` / `load_pipeline_results()` check before every write — safe to re-run multiple times without duplicates
- `--dry-run` flag previews all migration actions without touching DynamoDB
- Formatted summary table (MIGRATION SUMMARY) with migrated/skipped/failed counts for both sessions and pipeline results
- Dual-handler logging: INFO-level to stdout, DEBUG-level to timestamped log file for per-session audit trail
- Individual file failures are caught and counted, migration continues — no single failure aborts the whole run
- Original source files are never deleted or modified (no `unlink`, `os.remove`, or `shutil.rmtree`)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create idempotent migration script with dry-run mode and summary reporting** - `b198e1d` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `wafr-agents/scripts/migrate_sessions.py` — Standalone CLI migration script with argparse, check-before-write idempotency, dual-handler logging, formatted summary, and graceful per-file error handling

## Decisions Made

- `sys.path` manipulation prepends the `wafr-agents/` project root so `from wafr.storage.review_storage import create_review_storage, DynamoDBReviewStorage` works when the script is run from any working directory
- `isinstance(storage, DynamoDBReviewStorage)` guard after factory call ensures the script fails fast with a clear message if the factory ever returns a non-DynamoDB backend (which would lack `save_pipeline_results`/`load_pipeline_results`)
- Log file is auto-named `migration_<UTC-timestamp>.log` when `--log-file` is not specified — preserves logs from previous runs rather than overwriting them
- `sys.exit(1)` is returned whenever any individual item fails — enables CI/CD pipelines to detect partial migration failures; `sys.exit(0)` only on full success

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- `python` command not found in the shell environment; used `python3` for verification. The script shebang uses `#!/usr/bin/env python3` which resolves correctly in production environments.

## User Setup Required

None — the script uses `create_review_storage("dynamodb")` which reads existing WAFR_DYNAMO_* environment variables established in Plan 02-01. No new environment variables required.

## Next Phase Readiness

- Phase 2 complete: DynamoDB storage class, factory wiring, and migration script all in place
- Phase 5 (Data Migration and Audit Validation) can now run `python scripts/migrate_sessions.py` to migrate existing file-based sessions before the storage switchover
- `--dry-run` allows operators to preview the migration scope before committing to it
- Phase 3 (Backend Auth and API Security) can proceed: storage layer is fully independent of auth

## Self-Check: PASSED

- `wafr-agents/scripts/migrate_sessions.py` — FOUND
- Commit `b198e1d` — FOUND (feat(02-03): add idempotent file-to-DynamoDB migration script)

---
*Phase: 02-storage-migration*
*Completed: 2026-02-28*
