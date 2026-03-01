---
phase: 02-storage-migration
plan: 01
subsystem: database
tags: [dynamodb, boto3, s3, python, decimal, storage, persistence]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation
    provides: "DynamoDB tables (wafr-sessions, wafr-review-sessions, wafr-users), S3 bucket, IAM role with CRUD permissions"
provides:
  - "DynamoDBReviewStorage class implementing all 7 ReviewStorage ABC methods"
  - "Float-to-Decimal bidirectional converters (_python_to_dynamodb, _dynamodb_to_python)"
  - "Pipeline results storage with report_base64 stripping and 300KB S3 offload"
  - "Transcript storage always routed to S3 at dynamo-overflow/transcripts/"
  - "User profile sync method (sync_user_profile) writing to wafr-users table"
  - "Updated create_review_storage() factory accepting storage_type='dynamodb'"
affects:
  - 02-02-deploy-validate
  - 02-03-migration-script
  - 03-auth-middleware

# Tech tracking
tech-stack:
  added:
    - "boto3 DynamoDB resource API (already in requirements.txt)"
    - "botocore.exceptions.ClientError for DynamoDB/S3 error handling"
    - "boto3.dynamodb.conditions.Key, Attr for query/filter expressions"
    - "decimal.Decimal for float-to-DynamoDB conversion"
  patterns:
    - "Float-to-Decimal converter applied recursively before every put_item call"
    - "Decimal-to-Python converter applied recursively after every get_item/query call"
    - "Session metadata stored at item_id='SESSION', review items at item_id=<review_id> in wafr-review-sessions"
    - "report_base64 stripped before DynamoDB write; S3 key pointer preserved in result dict"
    - "Transcripts always stored in S3 regardless of size (per locked decision)"
    - "300KB S3 overflow threshold as safety valve for future large items"

key-files:
  created: []
  modified:
    - "wafr-agents/wafr/storage/review_storage.py"

key-decisions:
  - "300KB S3 overflow threshold chosen (safe headroom below 400KB DynamoDB limit; current stripped results are 77-147KB)"
  - "Pipeline results stored as JSON string attribute (not native DynamoDB map) to avoid Decimal conversion on deeply nested 11-step pipeline dicts"
  - "Per-item rows in wafr-review-sessions match table schema (PK: session_id, SK: item_id), enable individual item updates without rewriting whole session"
  - "create_review_storage() factory extended with 'dynamodb' branch reading env vars; existing 'memory' and 'file' branches untouched"
  - "wafr-agents/ is its own embedded git repository; committed review_storage.py there, not in outer repo"

patterns-established:
  - "Pattern: _python_to_dynamodb() applied to ALL data before any put_item() call — prevents TypeError: Float types not supported"
  - "Pattern: _dynamodb_to_python() applied to ALL data after any get_item()/query() call — prevents Decimal serialization errors"
  - "Pattern: S3 offload key prefix dynamo-overflow/ for all large items and transcripts"
  - "Pattern: Session metadata stored at item_id='SESSION', validation at item_id='VALIDATION', review items at item_id=<review_id>"

requirements-completed: [STOR-01, STOR-02, STOR-03, STOR-04]

# Metrics
duration: 5min
completed: 2026-02-28
---

# Phase 2 Plan 01: DynamoDB Review Storage Summary

**DynamoDBReviewStorage class with all 7 ABC methods, transparent float-to-Decimal conversion, S3 overflow for items >300KB, and always-S3 transcript storage**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-28T08:37:44Z
- **Completed:** 2026-02-28T08:43:36Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Implemented `DynamoDBReviewStorage` class in `wafr-agents/wafr/storage/review_storage.py` with all 7 abstract methods from the `ReviewStorage` ABC
- Added `_python_to_dynamodb()` / `_dynamodb_to_python()` bidirectional converters and `_compute_ttl_365d()` TTL helper as module-level functions
- Implemented `save_pipeline_results()` with `report_base64` stripping (reduces 1.1MB to 77-147KB) and 300KB S3 overflow safety valve
- Implemented `save_transcript()` always routing to S3 at `dynamo-overflow/transcripts/<session_id>.txt`
- Implemented `sync_user_profile()` for upsert writes to `wafr-users` table
- Extended `create_review_storage()` factory to accept `storage_type='dynamodb'` reading WAFR_DYNAMO_* env vars

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement float-to-Decimal bidirectional converters and DynamoDBReviewStorage class with all ABC methods** - `48265ce` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `wafr-agents/wafr/storage/review_storage.py` - Added DynamoDBReviewStorage class (651 lines added), updated factory function; all existing classes untouched

## Decisions Made

- **300KB S3 overflow threshold:** Chosen as safe headroom below the 400KB DynamoDB item limit. Current stripped pipeline results top at 147KB — threshold will not be triggered in practice but is a correctness safety valve.
- **Pipeline results as JSON string attribute:** Avoids need to apply Decimal conversion to deeply nested 11-step pipeline dicts. The string attribute stores up to 400KB (same limit, but as a single string attribute). This is the `pipeline_results_json` attribute on `wafr-sessions`.
- **Per-item rows pattern:** Each review item stored as a separate DynamoDB row with `item_id=<review_id>`. Matches the composite key schema of `wafr-review-sessions` and enables individual item updates without rewriting the whole session.
- **wafr-agents is an embedded git repo:** The project has `wafr-agents/.git` making it a separate git repository. Committed `review_storage.py` within the `wafr-agents` repo (commit `48265ce`) rather than the outer repo.

## Deviations from Plan

None — plan executed exactly as written. The `save_transcript()` and `load_pipeline_results()` methods were both included in the plan spec and are fully implemented.

## Issues Encountered

- **Embedded git repo discovery:** `wafr-agents/` has its own `.git` directory, making it a separate git repository from the outer project repo. This was discovered during commit staging. Resolution: committed the file within the `wafr-agents` repo as intended. The outer repo tracks `wafr-agents/` as an untracked directory (not a submodule).

## User Setup Required

None — no external service configuration required for this code change. The `DynamoDBReviewStorage` class will connect to AWS when instantiated via `create_review_storage('dynamodb')`, which requires `REVIEW_STORAGE_TYPE=dynamodb` env var on App Runner (set in Plan 02-02).

## Next Phase Readiness

- `DynamoDBReviewStorage` is ready to use — import and instantiate with correct table/bucket names
- `create_review_storage('dynamodb')` factory works end-to-end once AWS credentials are available
- Plan 02-02 (deploy validation) can proceed: deploy to App Runner, set `REVIEW_STORAGE_TYPE=dynamodb`, run smoke tests
- Plan 02-03 (migration script) can proceed: `storage.save_session()` and `storage.save_pipeline_results()` are implemented and ready to receive migrated data
- STOR-04 (user profile sync) is implemented as `sync_user_profile()` — Phase 3 will wire it into JWT middleware

## Self-Check: PASSED

- review_storage.py: FOUND
- 02-01-SUMMARY.md: FOUND
- Task commit 48265ce: FOUND (wafr-agents repo)
- Metadata commit 555da44: FOUND (outer repo)
- All import/method/converter assertions: PASSED

---
*Phase: 02-storage-migration*
*Completed: 2026-02-28*
