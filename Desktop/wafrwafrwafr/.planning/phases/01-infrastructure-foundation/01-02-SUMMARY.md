---
phase: 01-infrastructure-foundation
plan: 02
subsystem: auth
tags: [cognito, aws, user-pool, srp, rbac, amplify]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation
    provides: "DynamoDB tables provisioned (01-01)"
provides:
  - "Cognito User Pool us-east-1_U4ugKPUrh with admin-only signup and 12-char password policy"
  - "Public App Client 65fis729feu3lr317rm6oaue5s with SRP auth (no client secret)"
  - "WafrTeam group for internal team with full access"
  - "WafrClients group for external clients with limited access"
affects:
  - "01-03 (Secrets Manager — needs Pool ID and Client ID)"
  - "03-backend-auth (JWT validation middleware uses Pool ID for JWKS endpoint)"
  - "04-frontend-auth (Amplify uses App Client ID)"

# Tech tracking
tech-stack:
  added: [AWS Cognito User Pools, AWS Cognito App Clients, Cognito User Groups]
  patterns:
    - "Admin-only user creation — no self-service signup, all users created by WafrTeam admins"
    - "SRP auth flow only — no plaintext password transmission (ALLOW_USER_PASSWORD_AUTH excluded)"
    - "Role-based groups — WafrTeam (full access) vs WafrClients (limited access) for RBAC"

key-files:
  created:
    - ".planning/phases/01-infrastructure-foundation/infra-records/task-03-cognito-user-pool.md"
    - ".planning/phases/01-infrastructure-foundation/infra-records/task-04-cognito-app-client-groups.md"
  modified: []

key-decisions:
  - "No client secret on App Client — public client required for Amplify frontend (browser cannot store secrets securely)"
  - "ALLOW_USER_SRP_AUTH only — excludes ALLOW_USER_PASSWORD_AUTH to prevent plaintext password transmission (Pitfall 5 from research)"
  - "MFA deferred to AUTH-06 (v2) — not required for v1 per locked decision"
  - "1-hour access token validity — short-lived tokens reduce blast radius if compromised"

patterns-established:
  - "Cognito RBAC: group membership drives access level — WafrTeam=full, WafrClients=limited"
  - "SRP-only auth: Amplify frontend uses SRP; backend API validates JWTs via Cognito JWKS endpoint"

requirements-completed: [OPER-03]

# Metrics
duration: 2min
completed: 2026-02-28
---

# Phase 1 Plan 02: Cognito User Pool and App Client Setup Summary

**Cognito User Pool us-east-1_U4ugKPUrh with admin-only signup, SRP-only App Client 65fis729feu3lr317rm6oaue5s, and WafrTeam/WafrClients RBAC groups**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-28T05:56:22Z
- **Completed:** 2026-02-28T05:58:23Z
- **Tasks:** 2
- **Files modified:** 2 (infra record files created)

## Accomplishments
- Cognito User Pool `wafr-user-pool` (ID: `us-east-1_U4ugKPUrh`) created in us-east-1 with admin-only account creation and 12-character minimum password policy enforcing all character types
- Public App Client `wafr-app-client` (ID: `65fis729feu3lr317rm6oaue5s`) created with SRP auth and 1-hour access token validity — no client secret (required for Amplify frontend)
- Two RBAC user groups provisioned: WafrTeam (internal team, full access) and WafrClients (external clients, limited access)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Cognito User Pool with admin-only signup and password policy** - `f941cea` (feat)
2. **Task 2: Create public App Client with SRP auth and user groups** - `dbd47b2` (feat)

**Plan metadata:** *(docs commit follows this file)*

## Critical Output Values for Plan 01-03

These Cognito identifiers must be stored in Secrets Manager (Plan 01-03) and injected as App Runner environment variables:

| Key | Value |
|-----|-------|
| COGNITO_USER_POOL_ID | `us-east-1_U4ugKPUrh` |
| COGNITO_APP_CLIENT_ID | `65fis729feu3lr317rm6oaue5s` |
| COGNITO_REGION | `us-east-1` |
| JWKS_URL | `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_U4ugKPUrh/.well-known/jwks.json` |

## Files Created/Modified
- `.planning/phases/01-infrastructure-foundation/infra-records/task-03-cognito-user-pool.md` - User Pool provisioning record with Pool ID and configuration
- `.planning/phases/01-infrastructure-foundation/infra-records/task-04-cognito-app-client-groups.md` - App Client and group provisioning record with Client ID

## Decisions Made
- No client secret on App Client: public client required for Amplify frontend (browser cannot store secrets securely)
- ALLOW_USER_SRP_AUTH only, no ALLOW_USER_PASSWORD_AUTH: SRP prevents plaintext password transmission (per research Pitfall 5)
- MFA deferred to v2 (AUTH-06): not required for v1 per locked decision
- 1-hour access token validity: short-lived tokens reduce blast radius if compromised

## Deviations from Plan

None — plan executed exactly as written. All locked decisions implemented verbatim.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. All Cognito infrastructure provisioned via AWS CLI with existing IAM credentials.

## Next Phase Readiness

- Pool ID `us-east-1_U4ugKPUrh` and Client ID `65fis729feu3lr317rm6oaue5s` are ready for Plan 01-03 (Secrets Manager storage)
- JWKS endpoint is live: `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_U4ugKPUrh/.well-known/jwks.json`
- Phase 3 backend auth middleware can use Pool ID to construct JWKS URL for JWT validation
- Phase 4 frontend Amplify configuration needs Client ID and Pool ID
- No blockers — all dependencies for Plan 01-03 are now satisfied

---
*Phase: 01-infrastructure-foundation*
*Completed: 2026-02-28*

## Self-Check: PASSED

- FOUND: task-03-cognito-user-pool.md
- FOUND: task-04-cognito-app-client-groups.md
- FOUND: 01-02-SUMMARY.md
- FOUND: f941cea (Task 1 commit — User Pool)
- FOUND: dbd47b2 (Task 2 commit — App Client + Groups)
- FOUND: Cognito Pool us-east-1_U4ugKPUrh ACTIVE in AWS
- FOUND: App Client 65fis729feu3lr317rm6oaue5s in AWS
- FOUND: WafrTeam group in pool
- FOUND: WafrClients group in pool
