---
phase: 05-data-migration-and-audit-validation
plan: "01"
subsystem: infra
tags: [docker, ecr, apprunner, cognito, dynamodb, migration]

requires:
  - phase: 02-storage-migration
    provides: "migrate_sessions.py script and DynamoDBReviewStorage"
  - phase: 03-backend-auth-and-api-security
    provides: "JWT middleware with AUTH_REQUIRED enforcement"
  - phase: 04-frontend-auth-integration
    provides: "Amplify Authenticator with Cognito config build args"

provides:
  - "Backend Docker image with uvicorn-only entrypoint (no embedded data)"
  - "Frontend Docker image with Cognito User Pool/Client IDs baked in"
  - "Both App Runner services deployed with Phase 1-4 code"
  - "10 sessions + 4 pipeline results migrated to DynamoDB"
  - "Two Cognito test users (wafr-team-test, wafr-client-test) in correct groups"
  - "Auth enforcement verified (401 on unauthenticated requests)"

affects: [05-02-smoke-test]

tech-stack:
  added: []
  patterns: ["dos2unix guard in Dockerfile (sed -i 's/\\r$//' for Windows CRLF)"]

key-files:
  created: ["wafr-agents/scripts/entrypoint.sh"]
  modified: ["wafr-agents/Dockerfile"]

key-decisions:
  - "Pattern B migration: local docker run with volume mount, not embedded in ECR image"
  - "dos2unix sed guard added to Dockerfile to prevent CRLF deployment failures"
  - "Password generation with guaranteed character classes (upper+lower+digit+special)"

patterns-established:
  - "CRLF guard: Dockerfile runs sed -i 's/\\r$//' on shell scripts copied from Windows"
  - "Cognito user creation: 3-step (admin-create-user + admin-set-user-password --permanent + admin-add-user-to-group)"

requirements-completed: [OPER-01]

duration: 15min
completed: 2026-02-28
---

# Phase 5 Plan 01: Deploy services, migrate data, create test users

**Both App Runner services deployed with all Phase 1-4 code, 14 items migrated to DynamoDB, two Cognito test users created, and auth enforcement confirmed (401 on unauthenticated requests).**

## What was done

### Task 1: Entrypoint wrapper and Dockerfile
- Created `wafr-agents/scripts/entrypoint.sh` — uvicorn-only startup (no migration embedded)
- Updated `wafr-agents/Dockerfile` — added `COPY scripts/`, `sed` CRLF guard, `CMD ["bash", "scripts/entrypoint.sh"]`
- Intentionally omits `COPY review_sessions/` to prevent customer data leakage to ECR

### Task 2: Deployment and migration (operator-executed)
1. **ECR authentication** — Docker logged into 842387632939.dkr.ecr.us-east-1.amazonaws.com
2. **Migration** — Ran locally via `docker run` with volume mount (Pattern B):
   - Dry run: 10 sessions + 4 pipeline results found
   - Real run: all 14 items migrated successfully
   - DynamoDB counts: wafr-sessions=4, wafr-review-sessions=25
3. **Backend image** — Built, tagged, pushed to ECR. First deploy failed (CRLF line endings in entrypoint.sh). Fixed with `sed -i 's/\r$//'` and added dos2unix guard to Dockerfile. Second deploy succeeded.
4. **Frontend image** — Built with `--build-arg NEXT_PUBLIC_COGNITO_USER_POOL_ID=us-east-1_U4ugKPUrh --build-arg NEXT_PUBLIC_COGNITO_CLIENT_ID=65fis729feu3lr317rm6oaue5s`, tagged, pushed to ECR. Deploy succeeded.
5. **Cognito test users** — Created with generated passwords:
   - `wafr-team-test` in WafrTeam group (CONFIRMED status)
   - `wafr-client-test` in WafrClients group (CONFIRMED status)

### Verification results
- Auth enforcement: `curl` to `/api/wafr/sessions` returns **401** (unauthenticated blocked)
- Health endpoint: returns 200 with healthy status (no auth on health)
- Frontend: returns 200 (accessible)
- DynamoDB counts intact after deploy (wafr-sessions=4, wafr-review-sessions=25)
- Both test users CONFIRMED with correct group memberships

## Commits

- `c8f2fef` (wafr-agents) — Create entrypoint.sh and update Dockerfile with scripts/
- `166c71f` (wafr-agents) — Fix CRLF line endings in entrypoint.sh and add dos2unix guard
- `60057c8` (parent) — Update wafr-agents submodule: entrypoint and Dockerfile for App Runner
- `48d250f` (parent) — Update wafr-agents submodule: fix CRLF in entrypoint.sh

## Test credentials (not stored in code)

Passwords were generated at runtime and output to the operator. They are not committed anywhere in the repository.
- WafrTeam: `wafr-team-test`
- WafrClients: `wafr-client-test`
