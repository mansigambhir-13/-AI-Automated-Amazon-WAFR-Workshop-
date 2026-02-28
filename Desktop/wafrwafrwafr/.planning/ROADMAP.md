# Roadmap: WAFR Platform — DynamoDB, Auth & Security

## Overview

This milestone layers three missing production capabilities onto the existing WAFR Assessment Platform: durable DynamoDB storage (replacing file-based sessions that are wiped on every container restart), AWS Cognito authentication (closing the completely open API), and API security hardening (CORS lockdown, rate limiting, input validation). The five phases follow a strict dependency chain — AWS infrastructure must exist before application code can be tested, storage must be validated before auth is layered on top, backend auth must be deployed before the frontend can send real tokens, and migration runs last when all prior phases are confirmed working.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Infrastructure Foundation** - Provision DynamoDB tables, Cognito User Pool, and IAM permissions — zero application code changes (completed 2026-02-28)
- [x] **Phase 2: Storage Migration** - Replace file-based session storage with DynamoDB; deploy with auth bypassed to validate in isolation (completed 2026-02-28)
- [x] **Phase 3: Backend Auth and API Security** - JWT middleware, CORS lockdown, rate limiting, input validation, and audit trail on the FastAPI backend (completed 2026-02-28)
- [ ] **Phase 4: Frontend Auth Integration** - Amplify v6 login/logout UI, token attachment on all API requests, and role-based access enforcement (Plan 1 of 2 complete)
- [ ] **Phase 5: Data Migration and Audit Validation** - Run one-time file-to-DynamoDB migration, flip AUTH_REQUIRED=true, and smoke-test end-to-end

## Phase Details

### Phase 1: Infrastructure Foundation
**Goal**: All AWS resources required by subsequent phases exist and are correctly configured before any application code is written
**Depends on**: Nothing (first phase)
**Requirements**: OPER-03
**Success Criteria** (what must be TRUE):
  1. Four DynamoDB tables exist in us-east-1 (`wafr-sessions`, `wafr-review-sessions`, `wafr-users`, `wafr-audit-log`) with correct key schemas and GSIs
  2. Cognito User Pool exists with a public App Client (no client secret) and two groups: `WafrTeam` and `WafrClients`
  3. `WafrAppRunnerInstanceRole` IAM policy allows DynamoDB CRUD scoped to `arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*` and Cognito read operations
  4. Backend App Runner service environment variables include Cognito User Pool ID, App Client ID, table names, and `AUTH_REQUIRED=false`
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Provision four DynamoDB tables with key schemas, GSIs, TTL, and PITR (Wave 1)
- [ ] 01-02-PLAN.md — Create Cognito User Pool, public App Client, and WafrTeam/WafrClients groups (Wave 1)
- [ ] 01-03-PLAN.md — Extend IAM policy, store Cognito values in Secrets Manager, update App Runner env vars (Wave 2)

### Phase 2: Storage Migration
**Goal**: Assessment sessions, pipeline results, and review decisions survive container restarts by being stored in DynamoDB instead of local files
**Depends on**: Phase 1
**Requirements**: STOR-01, STOR-02, STOR-03, STOR-04, OPER-02
**Success Criteria** (what must be TRUE):
  1. A WAFR assessment run after deployment persists its session record in DynamoDB and is retrievable after a manual App Runner service restart
  2. Pipeline results (including large items) are stored correctly — transcripts in S3, structured results in DynamoDB — without truncation or error
  3. Human review decisions (approve/reject/modify per question) written via the HRI are retrievable from DynamoDB after a service restart
  4. User profile records exist in DynamoDB and are read correctly by the application
  5. Setting `REVIEW_STORAGE_TYPE=dynamodb` in the App Runner environment switches storage; the previous file-based path still works with `REVIEW_STORAGE_TYPE=file` and `AUTH_REQUIRED=false` keeps the API unauthenticated during this phase
**Plans**: 3 plans

Plans:
- [x] 02-01-PLAN.md — Implement DynamoDBReviewStorage class with float-to-Decimal converters, S3 offload, and all ABC methods (Wave 1) (completed 2026-02-28)
- [x] 02-02-PLAN.md — Wire storage factory for 'dynamodb', remove dead deployment.entrypoint code from server.py, connect REVIEW_STORAGE_TYPE env var (Wave 2) (completed 2026-02-28)
- [x] 02-03-PLAN.md — Build idempotent migration script for existing file-based sessions and pipeline results (Wave 3) (completed 2026-02-28)

### Phase 3: Backend Auth and API Security
**Goal**: Every FastAPI endpoint is protected by Cognito JWT authentication, the API accepts requests only from the frontend domain, and all inputs are validated and rate-limited
**Depends on**: Phase 2
**Requirements**: AUTH-01, AUTH-02, SECR-01, SECR-02, SECR-03, SECR-04
**Success Criteria** (what must be TRUE):
  1. A curl request to any API endpoint without a valid Cognito access token receives 401 Unauthorized (not 403, not 200)
  2. A request from a non-frontend origin receives a CORS rejection; a request from the frontend App Runner domain succeeds
  3. Sending more than 10 requests per minute to `POST /api/wafr/run` from a single IP returns 429 Too Many Requests on the excess requests
  4. A transcript body exceeding 500,000 characters is rejected with a 422 Validation Error before reaching the AI pipeline
  5. After a team user runs an assessment, an audit log entry exists in `wafr-audit-log` with user ID, session ID, action type, and timestamp
**Plans**: 3 plans

Plans:
- [ ] 03-01-PLAN.md — Create wafr/auth/ subpackage with JWT middleware, wire Depends(verify_token) on all endpoints, add Pydantic input validation (Wave 1)
- [ ] 03-02-PLAN.md — Replace CORS wildcard with env-var origins, add slowapi rate limiting with tiered limits (Wave 2)
- [ ] 03-03-PLAN.md — Implement audit trail ASGI middleware and per-endpoint body logging to wafr-audit-log DynamoDB table (Wave 3)

### Phase 4: Frontend Auth Integration
**Goal**: Users log in and log out through the Next.js frontend using Cognito credentials, and every API request automatically carries a valid access token
**Depends on**: Phase 3
**Requirements**: AUTH-03, AUTH-04
**Success Criteria** (what must be TRUE):
  1. A user who visits the app without a session is presented with a login form and cannot access any assessment page
  2. A team user who logs in can create and view all assessments; a client user who logs in can only see assessments associated with their account
  3. Every API request from the frontend includes an `Authorization: Bearer <access_token>` header with a valid Cognito access token
  4. When an access token expires, the frontend transparently refreshes it and retries the request without the user needing to log in again
**Plans**: 2 plans

Plans:
- [x] 04-01-PLAN.md — Install Amplify v6, create AmplifyProvider + Authenticator with sessionStorage, create auth helpers, wire Bearer token on all API/SSE requests, update Dockerfile with Cognito build ARGs (Wave 1) (completed 2026-02-28)
- [ ] 04-02-PLAN.md — Add user info + role badge + sign-out to header, enforce role-based UI visibility on dashboard and new-assessment, auth-aware report downloads, human verification checkpoint (Wave 2) — Task 1 complete, awaiting human-verify checkpoint

### Phase 5: Data Migration and Audit Validation
**Goal**: All existing file-based sessions are in DynamoDB, authentication is enforced on all endpoints, and the full end-to-end workflow is verified for both user roles
**Depends on**: Phase 4
**Requirements**: OPER-01
**Success Criteria** (what must be TRUE):
  1. All previously file-based assessment sessions are readable in the app after migration, with no duplicates created by re-running the migration script
  2. `AUTH_REQUIRED=true` is set in the backend App Runner environment and the existing unauthenticated path no longer works (curl without token gets 401)
  3. A team user can log in, start an assessment, approve review decisions, and download a report in a single end-to-end smoke test
  4. A client user can log in and see only their own assessments — attempting to access another session ID returns a 403 or empty result
**Plans**: TBD

Plans:
- [ ] 05-01: Run migration script, verify idempotency, and set AUTH_REQUIRED=true
- [ ] 05-02: End-to-end smoke test for team user and client user role isolation

## Progress

**Execution Order:**
Phases execute in strict dependency order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Foundation | 3/3 | Complete   | 2026-02-28 |
| 2. Storage Migration | 3/3 | Complete   | 2026-02-28 |
| 3. Backend Auth and API Security | 3/3 | Complete   | 2026-02-28 |
| 4. Frontend Auth Integration | 1.5/2 | In Progress (checkpoint) | - |
| 5. Data Migration and Audit Validation | 0/2 | Not started | - |
