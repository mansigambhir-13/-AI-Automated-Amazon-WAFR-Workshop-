# Requirements: WAFR Platform — DynamoDB, Auth & Security

**Defined:** 2026-02-28
**Core Value:** Every WAFR assessment session is durably stored, only accessible to authorized users, and the backend API is protected from unauthorized access and abuse.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Storage

- [x] **STOR-01**: Assessment sessions are stored durably in DynamoDB and survive container restarts
- [x] **STOR-02**: Pipeline results (orchestrator output) are stored in DynamoDB with S3 offload for items >400KB
- [x] **STOR-03**: Human review decisions (approve/reject/modify per question) are persisted in DynamoDB
- [x] **STOR-04**: User profiles with roles and preferences are stored in DynamoDB

### Authentication

- [x] **AUTH-01**: AWS Cognito User Pool created with team and client user groups
- [x] **AUTH-02**: Backend validates Cognito JWT access tokens on all API endpoints via FastAPI middleware
- [ ] **AUTH-03**: Frontend provides login, signup, and password reset UI via Amplify
- [ ] **AUTH-04**: Team users can create/view/manage all assessments; client users can only view their own

### Security

- [x] **SECR-01**: CORS is locked down to only allow requests from the frontend App Runner domain
- [x] **SECR-02**: Rate limiting is enforced per-user/IP on all API endpoints via slowapi
- [x] **SECR-03**: All API inputs are validated with Pydantic models including transcript size limits
- [ ] **SECR-04**: Audit trail logs who ran what assessment, when, with what transcript

### Operations

- [ ] **OPER-01**: Existing file-based sessions are migrated to DynamoDB via migration script
- [ ] **OPER-02**: AUTH_REQUIRED environment flag enables gradual auth rollout
- [x] **OPER-03**: WafrAppRunnerInstanceRole IAM policy includes DynamoDB and Cognito permissions

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Auth

- **AUTH-05**: OAuth providers (Google, GitHub) via Cognito identity providers
- **AUTH-06**: MFA enforcement for team users
- **AUTH-07**: HttpOnly cookie token storage via Cognito Managed Login

### Enhanced Security

- **SECR-05**: Redis-backed distributed rate limiting for multi-instance scaling
- **SECR-06**: WAF integration for DDoS protection
- **SECR-07**: API versioning with deprecation policy

### Enhanced Storage

- **STOR-05**: DynamoDB streams for real-time change notifications
- **STOR-06**: Point-in-time recovery (PITR) for DynamoDB tables
- **STOR-07**: Cross-region replication for disaster recovery

## Out of Scope

| Feature | Reason |
|---------|--------|
| API Gateway migration | Would break SSE streaming (29s timeout) and require full architecture change |
| Multi-tenancy with billing | Not needed for current user base size |
| Custom domain / SSL certificates | App Runner provides HTTPS by default |
| Real-time collaboration | Assessments are single-user workflows |
| Lambda@Edge auth | Adds complexity without benefit on App Runner |
| Mobile app authentication | Web-first, mobile deferred |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| STOR-01 | Phase 2 | Complete (02-01) |
| STOR-02 | Phase 2 | Complete (02-01) |
| STOR-03 | Phase 2 | Complete (02-01) |
| STOR-04 | Phase 2 | Complete (02-01) |
| AUTH-01 | Phase 3 | Complete |
| AUTH-02 | Phase 3 | Complete |
| AUTH-03 | Phase 4 | Pending |
| AUTH-04 | Phase 4 | Pending |
| SECR-01 | Phase 3 | Complete |
| SECR-02 | Phase 3 | Complete |
| SECR-03 | Phase 3 | Complete |
| SECR-04 | Phase 3 | Pending |
| OPER-01 | Phase 5 | Pending |
| OPER-02 | Phase 2 | Pending |
| OPER-03 | Phase 1 (Plan 01-03) | Complete |

**Coverage:**
- v1 requirements: 15 total
- Mapped to phases: 15
- Unmapped: 0

---
*Requirements defined: 2026-02-28*
*Last updated: 2026-02-28 after 01-01 plan execution (DynamoDB tables provisioned)*
