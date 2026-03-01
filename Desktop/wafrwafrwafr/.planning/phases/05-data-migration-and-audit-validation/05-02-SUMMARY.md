---
phase: 05-data-migration-and-audit-validation
plan: "02"
subsystem: testing
tags: [smoke-test, cognito, dynamodb, audit, e2e]

requires:
  - phase: 05-01
    provides: "Deployed services, migrated data, test users"

provides:
  - "End-to-end validation of complete WAFR platform"
  - "Smoke test checklist with all sections PASS"
  - "Audit log bug fix (empty string GSI key)"

affects: []

tech-stack:
  added: [pycognito]
  patterns: ["SRP auth from CLI via pycognito for API smoke testing"]

key-files:
  created: [".planning/phases/05-data-migration-and-audit-validation/05-SMOKE-TEST-CHECKLIST.md"]
  modified: ["wafr-agents/wafr/auth/audit.py"]

key-decisions:
  - "Used pycognito for SRP auth (Cognito only allows USER_SRP_AUTH, not password auth)"
  - "Fixed audit log empty string GSI key — changed session_id from '' to 'no-session'"

patterns-established:
  - "SRP auth testing: pycognito.Cognito.authenticate() for CLI-based Cognito token acquisition"

requirements-completed: [OPER-01]

duration: 20min
completed: 2026-03-01
---

# Phase 5 Plan 02: Smoke test execution and audit validation

**All 7 smoke test sections pass — auth enforcement, migration idempotency, team lifecycle, client role isolation, audit logging, and data integrity all verified end-to-end.**

## What was done

### Task 1: Smoke test checklist creation
- Created comprehensive checklist at `05-SMOKE-TEST-CHECKLIST.md` with 7 sections
- Covers pre-flight, idempotency, team user, client user, audit log, spot-check, pass/fail summary

### Task 2: Full smoke test execution

**Section 1 — Pre-Flight:** Both services RUNNING, 401 on unauthenticated, health=200, data intact

**Section 2 — Migration Idempotency:** Re-ran migration → all 14 items SKIPPED (already in DynamoDB), counts unchanged (4 sessions, 25 review items)

**Section 3 — WafrTeam User:**
- Authenticated via SRP (pycognito) — token contains `cognito:groups: ['WafrTeam']`
- Listed 10 sessions (all migrated data visible), session detail/review/pillars all HTTP 200
- Delete endpoint accessible (team role = permitted)

**Section 4 — WafrClients User:**
- Authenticated via SRP — token contains `cognito:groups: ['WafrClients']`
- DELETE → 403 "Requires WafrTeam role"
- POST /run → 403 "Requires WafrTeam role"
- GET review items/summary → 200 (read access works)

**Section 5 — Audit Log:**
- 12 entries logged with correct user_id, path, method, status_code
- Both test users' requests appear
- 403 responses logged for denied client actions

**Section 6 — Spot-Check:** Session data readable with expected fields

### Bug found and fixed
- **Audit log empty string GSI key:** `session_id: ""` violates DynamoDB GSI constraint. Fixed to `"no-session"`. All audit writes were silently failing before this fix.
- Rebuilt, pushed, and redeployed backend
- Verified 12 audit entries after fix

## Commits

- `67e7d60` (wafr-agents) — Fix audit log empty string GSI key causing all writes to fail
- `2d85bc7` (parent) — Update wafr-agents: fix audit log empty string GSI key
