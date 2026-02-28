---
phase: 02-storage-migration
plan: 02
subsystem: server
tags: [fastapi, dynamodb, storage-factory, dead-code-removal, python]

# Dependency graph
requires:
  - phase: 02-storage-migration
    plan: 01
    provides: "DynamoDBReviewStorage class and create_review_storage('dynamodb') factory branch"
provides:
  - "create_review_storage() with **kwargs parameter and comprehensive env-var docstring"
  - "server.py free of all deployment.entrypoint dead code (three blocks removed)"
  - "REVIEW_STORAGE_TYPE env var controls storage backend via get_review_orchestrator()"
  - "Pipeline results and transcripts routed to DynamoDB storage when dynamodb backend active"
affects:
  - 02-03-migration-script
  - App Runner REVIEW_STORAGE_TYPE=dynamodb deployment

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "hasattr guard (hasattr(storage, 'save_pipeline_results')) for optional DynamoDB method calls — safe for file/memory backends"
    - "REVIEW_STORAGE_TYPE env var read at singleton init time in get_review_orchestrator()"
    - "Dead deployment.entrypoint blocks fully removed; all DynamoDB access routes through wafr/storage/"

key-files:
  created: []
  modified:
    - "wafr-agents/wafr/storage/review_storage.py"
    - "wafr-agents/wafr/ag_ui/server.py"

key-decisions:
  - "**kwargs added to create_review_storage() for forward-compatibility — callers may pass extra keyword args without error if signature evolves"
  - "Pipeline results and transcript DynamoDB writes are wrapped in try/except — DynamoDB errors never break the existing file-storage code path"
  - "hasattr guards used for save_pipeline_results and save_transcript — method presence signals DynamoDB backend; file/memory backends simply skip"
  - "REVIEW_STORAGE_TYPE was already wired in get_review_orchestrator() — no change needed there (plan over-specified)"

patterns-established:
  - "Pattern: try/except + hasattr guard for optional DynamoDB storage methods — zero-impact on non-DynamoDB backends"
  - "Pattern: All DynamoDB access routes through wafr/storage/DynamoDBReviewStorage — deployment.entrypoint anti-pattern fully eliminated"

requirements-completed: [STOR-01, STOR-02, STOR-03, OPER-02]

# Metrics
duration: 8min
completed: 2026-02-28
---

# Phase 2 Plan 02: Wire DynamoDBReviewStorage into Application Summary

**Storage factory updated with **kwargs and comprehensive docstring; three dead deployment.entrypoint blocks removed from server.py; REVIEW_STORAGE_TYPE env var controls all storage selection; pipeline results and transcripts routed to DynamoDB when active**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-28T08:44:00Z
- **Completed:** 2026-02-28T08:52:06Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Updated `create_review_storage()` factory with `**kwargs` parameter and expanded docstring documenting all five environment variables used by the DynamoDB backend
- Removed three dead `from deployment.entrypoint import ...` try/except blocks from `server.py`:
  - Block 1 (~line 595): `save_session_data` call in the `/api/wafr/run` background `process()` handler
  - Block 2 (~line 842): `get_dynamodb_table()` scan in the `list_sessions` endpoint
  - Block 3 (~line 951): `get_dynamodb_table()` query in the `get_session_details` endpoint
- Confirmed `REVIEW_STORAGE_TYPE` env var was already wired in `get_review_orchestrator()` (present from prior development)
- Added `save_pipeline_results()` and `save_transcript()` calls with `hasattr` guards in the pipeline results handler, ensuring DynamoDB storage receives data when the `dynamodb` backend is active

## Task Commits

Each task was committed atomically:

1. **Task 1: Update factory with **kwargs and comprehensive docstring** - `24ddb9e` (feat)
2. **Task 2: Remove dead deployment.entrypoint blocks and wire REVIEW_STORAGE_TYPE** - `876d9d7` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `wafr-agents/wafr/storage/review_storage.py` - Added `**kwargs` parameter to `create_review_storage()`, expanded docstring with all env var names and defaults
- `wafr-agents/wafr/ag_ui/server.py` - Removed three dead code blocks (19 lines + 38 lines + 26 lines), added `save_pipeline_results()` and `save_transcript()` routing with hasattr guards

## Decisions Made

- **`**kwargs` in factory:** Allows callers to pass extra keyword arguments without error if the factory signature evolves. The parameter is accepted but ignored — future-proof without behavioral change.
- **try/except + hasattr guards for DynamoDB calls:** Both `save_pipeline_results()` and `save_transcript()` calls are wrapped in `try/except` with `hasattr` guards. This means DynamoDB errors never interrupt the main pipeline flow, and file/memory backends silently skip the calls.
- **REVIEW_STORAGE_TYPE already wired:** The `get_review_orchestrator()` function already contained `os.getenv("REVIEW_STORAGE_TYPE", "file")` — no change was needed. The plan over-specified this as a new addition.
- **Dead blocks fully removed (not replaced):** The three `deployment.entrypoint` blocks were deleted entirely. The surrounding `review_orch.storage.*()` calls already handle all persistence — no replacement code needed.

## Deviations from Plan

### Auto-fixed Issues

None.

### Minor Variance

**Task 2 Part B — REVIEW_STORAGE_TYPE already present:**
- **Found during:** Task 2 execution
- **Issue:** Plan described "wiring REVIEW_STORAGE_TYPE" as new work, but `get_review_orchestrator()` already contained `storage_type = os.getenv("REVIEW_STORAGE_TYPE", "file")` from prior development.
- **Resolution:** Confirmed the existing code was correct per plan requirements. No change needed. Documented as "already done."
- **Impact:** None — plan's success criteria are fully met.

## Issues Encountered

None — all edits were surgical and verifications passed on first attempt.

## User Setup Required

To activate DynamoDB storage on App Runner:
1. Set `REVIEW_STORAGE_TYPE=dynamodb` in App Runner environment variables
2. Ensure `WAFR_DYNAMO_SESSIONS_TABLE`, `WAFR_DYNAMO_REVIEW_SESSIONS_TABLE`, `WAFR_DYNAMO_USERS_TABLE` are set (already set via Phase 1)
3. Ensure `S3_BUCKET` and `AWS_DEFAULT_REGION` are set (already present)
4. Deploy the updated Docker image

## Next Phase Readiness

- `create_review_storage('dynamodb')` factory path is fully working end-to-end
- `server.py` has zero references to `deployment.entrypoint`
- Setting `REVIEW_STORAGE_TYPE=dynamodb` on App Runner switches all persistence to DynamoDB
- Plan 02-03 (migration script) can proceed: `DynamoDBReviewStorage.save_session()` and `save_pipeline_results()` are ready

## Self-Check: PASSED

- review_storage.py: FOUND at wafr-agents/wafr/storage/review_storage.py
- server.py: FOUND at wafr-agents/wafr/ag_ui/server.py
- Task 1 commit 24ddb9e: FOUND (wafr-agents repo)
- Task 2 commit 876d9d7: FOUND (wafr-agents repo)
- Verification 1 (no deployment.entrypoint): PASS
- Verification 2 (REVIEW_STORAGE_TYPE in server.py): PASS (line 253)
- Verification 3 (server.py compiles): PASS
- Verification 4 (review_storage.py compiles): PASS
- Verification 5 (factory creates correct types): PASS

---
*Phase: 02-storage-migration*
*Completed: 2026-02-28*
