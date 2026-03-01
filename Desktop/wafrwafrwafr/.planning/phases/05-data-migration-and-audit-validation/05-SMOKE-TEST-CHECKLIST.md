# WAFR Platform End-to-End Smoke Test Checklist

**Date:** 2026-03-01
**Phase:** 05 — Data Migration and Audit Validation
**Purpose:** Validate that all five phases work together as a complete system
**Result:** ALL PASS

---

## Section 1: Pre-Flight Checks

- [x] Backend App Runner service is RUNNING (`https://i5kj2nnkxd.us-east-1.awsapprunner.com`)
- [x] Frontend App Runner service is RUNNING (`https://3fhp6mfj7u.us-east-1.awsapprunner.com`)
- [x] Unauthenticated request returns **401**: `curl -s -o /dev/null -w "%{http_code}" https://i5kj2nnkxd.us-east-1.awsapprunner.com/api/wafr/sessions`
- [x] Health endpoint returns **200**: `{"status":"healthy","service":"wafr-ag-ui-server","version":"1.0.0"}`
- [x] DynamoDB wafr-sessions count: **4 items**
- [x] DynamoDB wafr-review-sessions count: **25 items** (pre-test)

## Section 2: Migration Idempotency Verification

**Pre-run counts:** wafr-sessions=4, wafr-review-sessions=25

- [x] Re-ran migration script: all 10 sessions SKIPPED ("already in DynamoDB")
- [x] Re-ran migration script: all 4 pipeline results SKIPPED ("already in DynamoDB")
- [x] wafr-sessions count after re-run: **4** (identical — no duplicates)
- [x] wafr-review-sessions count after re-run: **25** (identical — no duplicates)
- [x] Migration summary: `Migrated: 0, Skipped: 10, Failed: 0` (sessions), `Migrated: 0, Skipped: 4, Failed: 0` (pipeline results)

## Section 3: WafrTeam User Smoke Test

**Login:** wafr-team-test (SRP auth via pycognito, Cognito groups: `['WafrTeam']`)

1. [x] Team user authenticates successfully — access token obtained (1085 chars)
2. [x] Token contains `cognito:groups: ['WafrTeam']` and `username: wafr-team-test`
3. [x] List sessions: **HTTP 200** — 10 sessions returned (all migrated sessions visible)
4. [x] Session detail: **HTTP 200** — returns session_id, found, results, source, session, assessment_summary
5. [x] Review items: **HTTP 200** — 10 review items returned with review_id, question_id, pillar, etc.
6. [x] Review summary: **HTTP 200** — status=in_progress, total=10, pending=5
7. [x] Pillars: **HTTP 200**
8. [x] Delete endpoint (team access): **HTTP 404** (non-existent ID) — confirms team user has access (not 403)
9. [x] Sign out: pycognito session invalidated

## Section 4: WafrClients User Smoke Test

**Login:** wafr-client-test (SRP auth via pycognito, Cognito groups: `['WafrClients']`)

1. [x] Client user authenticates successfully — access token obtained (1092 chars)
2. [x] Token contains `cognito:groups: ['WafrClients']` and `username: wafr-client-test`
3. [x] List sessions: **HTTP 200** — sessions returned
4. [x] DELETE session: **HTTP 403** — `{"detail":"Requires WafrTeam role"}`
5. [x] POST /run (create assessment): **HTTP 403** — `{"detail":"Requires WafrTeam role"}`
6. [x] GET review items (read-only): **HTTP 200** — client can read
7. [x] GET review summary (read-only): **HTTP 200** — client can read

## Section 5: Audit Log Verification

- [x] Audit log count after smoke tests: **12 entries**
- [x] Entries contain paths with `/api/wafr/` prefix
- [x] Both user IDs appear: `94089478...` (client), `b4c824f8...` (team)
- [x] All entries have fields: `user_id`, `path`, `http_method`, `status_code`, `action_type`, `session_id`
- [x] 403 responses logged for client's delete/run attempts
- [x] 200 responses logged for successful read operations

**Sample entries:**
| user_id | method | path | status |
|---------|--------|------|--------|
| client-test (9408...) | GET | /api/wafr/sessions | 200 |
| client-test (9408...) | DELETE | /api/wafr/session/3f4c... | 403 |
| client-test (9408...) | POST | /api/wafr/run | 403 |
| team-test (b4c8...) | GET | /api/wafr/sessions | 200 |
| team-test (b4c8...) | GET | /api/wafr/session/.../details | 200 |
| team-test (b4c8...) | GET | /api/wafr/review/.../items | 200 |

## Section 6: Spot-Check Migrated Data

- [x] Session `3f4c0122-914d-4236-9881-ae4cfa936d9c` exists with `session_id`, `created_at`, `status` fields
- [x] Data is readable and not corrupted (created_at=2026-03-01T00:13:35.497314)

## Section 7: Pass/Fail Summary

| Check | Result |
|-------|--------|
| Auth enforced (401 on unauthenticated) | **PASS** |
| Migration data present in DynamoDB | **PASS** |
| Migration idempotency (no duplicates) | **PASS** |
| WafrTeam full API lifecycle | **PASS** |
| WafrClients role isolation (403 on write, 200 on read) | **PASS** |
| Audit log entries present (12 entries) | **PASS** |
| Spot-check migrated data | **PASS** |
| **Overall** | **PASS** |

Pass criteria per CONTEXT.md: "any auth or data issue blocks the milestone" — No blockers found.

### Bug Found and Fixed During Testing

**Audit log empty string GSI key:** The audit middleware was writing `session_id: ""` for middleware-level entries (where no specific session context exists). DynamoDB rejects empty strings as GSI key values on `session_id-timestamp-index`, causing all audit writes to silently fail. Fixed by using `"no-session"` placeholder. Commit: `67e7d60` (wafr-agents), `2d85bc7` (parent).

---

*Smoke test completed: 2026-03-01*
*Phase: 05-data-migration-and-audit-validation*
