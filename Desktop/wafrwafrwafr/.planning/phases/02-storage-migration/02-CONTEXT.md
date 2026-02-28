# Phase 2: Storage Migration - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace file-based session storage with DynamoDB so that assessment sessions, pipeline results, review decisions, and user profiles survive container restarts. Includes a migration script for existing file data. No authentication changes — Phase 1 already set AUTH_REQUIRED=true.

</domain>

<decisions>
## Implementation Decisions

### Storage Switchover
- Switchover strategy: Claude's discretion (feature flag cut-over vs dual-write)
- File-based storage path: Keep permanently as fallback for local dev and testing — do not remove
- Auth during testing: Claude's discretion (create test Cognito user or temporarily disable auth)
- Default for REVIEW_STORAGE_TYPE when unset: Claude's discretion (pick safest default)

### Large Item Handling
- Offload strategy: S3 offload with DynamoDB pointer for items exceeding size limit
- S3 bucket: Use existing wafr S3 bucket with a new prefix (e.g., `dynamo-overflow/`)
- Size threshold: Claude's discretion (pick a safe threshold below 400KB)
- Transcripts: Always store in S3 regardless of size — only keep a reference in DynamoDB

### Data Model Mapping
- Nested pipeline results: Claude's discretion (single item with nested maps vs separate items per pillar/question)
- Review decisions: Claude's discretion (use wafr-review-sessions table or embed in session — match Phase 1 table design)
- Queryable metadata: Claude's discretion (match GSIs created in Phase 1)
- Float-to-Decimal conversion: Claude's discretion (transparent vs explicit — minimize codebase changes)

### Migration Approach
- Migration method: Claude's discretion (one-shot script vs lazy migration)
- Idempotency: Required — script must be safe to re-run without creating duplicates
- Reporting: Summary report with counts of migrated, skipped, and failed items plus log file
- Original files: Keep intact after migration — do not delete, serve as backup

### Claude's Discretion
- Switchover strategy (feature flag vs dual-write)
- Auth bypass approach during Phase 2 testing
- REVIEW_STORAGE_TYPE default value
- S3 offload size threshold
- Data model shape (nested vs flat, table assignment)
- Float-to-Decimal conversion approach
- Migration method (one-shot vs lazy)

</decisions>

<specifics>
## Specific Ideas

- Phase 1 created 4 DynamoDB tables: wafr-sessions, wafr-review-sessions, wafr-users, wafr-audit-log
- Phase 1 set AUTH_REQUIRED=true — testing approach must account for this
- Cognito User Pool ID: us-east-1_U4ugKPUrh, App Client ID: 65fis729feu3lr317rm6oaue5s
- Existing file storage paths: `/review_sessions/pipeline_results/`, `/review_sessions/sessions/`, `/tmp/reports/`
- Existing storage code: `wafr-agents/wafr/storage/review_storage.py`
- Known issue: DynamoDB save already attempted in server.py but fails (`No module named 'deployment'`)
- Backend server: `wafr-agents/wafr/ag_ui/server.py` (~2400 lines)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-storage-migration*
*Context gathered: 2026-02-28*
