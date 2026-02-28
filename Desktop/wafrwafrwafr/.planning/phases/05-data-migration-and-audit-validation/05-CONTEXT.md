# Phase 5: Data Migration and Audit Validation - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Run the one-time file-to-DynamoDB migration, create Cognito test users, deploy both services to App Runner (with auth enforcement), and smoke-test the full end-to-end workflow for both WafrTeam and WafrClients roles. Verify audit log entries exist in DynamoDB. No new feature code — this phase validates everything built in Phases 1-4.

</domain>

<decisions>
## Implementation Decisions

### Migration Execution
- Existing file-based sessions need to be migrated to DynamoDB
- Migration runs locally via `docker run` with operator's AWS credentials (Pattern B) — session files are on the local machine, not in the Docker image, and embedding them in ECR would be a security risk
- Rollback plan: DynamoDB PITR (Point-in-Time Recovery) to restore pre-migration state if something goes wrong
- Claude's discretion on post-migration validation approach (count comparison, spot-check, or both)

### Auth Enforcement Cutover
- AUTH_REQUIRED=true is already set on App Runner from Phase 1 — enforce immediately on deploy (no temporary false)
- Emergency rollback: flip AUTH_REQUIRED=false via App Runner env var update (~1 minute, no code redeploy)
- Create test users as part of this phase: one WafrTeam user, one WafrClients user
- Claude generates secure passwords for test users — passwords output to operator, stored nowhere in code

### End-to-End Smoke Test
- Full assessment lifecycle: Login → create assessment → run analysis → review decisions → download report → logout
- Test both WafrTeam and WafrClients user roles
- Manual checklist format (not scripted/automated) — step-by-step document to walk through in the browser
- Verify audit log entries exist in wafr-audit-log DynamoDB table after smoke test
- Pass/fail criteria: any auth or data issue blocks the milestone (login failure, 401 on authenticated requests, missing sessions, absent audit entries)

### Deployment Sequencing
- Deploy frontend and backend simultaneously (both App Runner services updated at the same time)
- Docker images built and pushed via CLI commands (Claude provides exact commands, operator executes)
- ECR container registry already exists — push images there
- Migration runs locally before or in parallel with deploy — Pattern B runs independently of App Runner deployment timing

### Claude's Discretion
- Post-migration validation depth (count comparison vs spot-check vs both)
- Exact deployment CLI commands (docker build, push, update-service)
- Smoke test checklist structure and ordering
- Audit log query commands for verification

</decisions>

<specifics>
## Specific Ideas

- Backend App Runner: https://i5kj2nnkxd.us-east-1.awsapprunner.com
- Frontend App Runner: https://3fhp6mfj7u.us-east-1.awsapprunner.com
- Cognito User Pool ID: us-east-1_U4ugKPUrh
- Cognito App Client ID: 65fis729feu3lr317rm6oaue5s
- Migration script: wafr-agents/scripts/migrate_sessions.py (369 lines, idempotent, --dry-run support)
- DynamoDB tables: wafr-sessions, wafr-review-sessions, wafr-users, wafr-audit-log
- All four tables have PITR enabled from Phase 1
- AUTH_REQUIRED=true already set on both App Runner services
- Cognito groups: WafrTeam, WafrClients
- Backend Dockerfile already sets ENV REVIEW_STORAGE_TYPE=dynamodb
- Frontend Dockerfile needs NEXT_PUBLIC_COGNITO_USER_POOL_ID and NEXT_PUBLIC_COGNITO_CLIENT_ID as build args

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-data-migration-and-audit-validation*
*Context gathered: 2026-02-28*
