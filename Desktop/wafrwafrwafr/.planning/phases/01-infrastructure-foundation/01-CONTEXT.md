# Phase 1: Infrastructure Foundation - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Provision all AWS resources (DynamoDB tables, Cognito User Pool, IAM permissions, environment variables) required by subsequent phases. Zero application code changes. All resources in us-east-1, AWS account 842387632939.

</domain>

<decisions>
## Implementation Decisions

### DynamoDB Table Design
- Capacity mode: Claude's discretion (evaluate on-demand vs provisioned based on workload)
- TTL on session tables (wafr-sessions, wafr-review-sessions): 365 days auto-expiry
- TTL on audit-log table: No TTL — keep audit trails indefinitely
- TTL on users table: No TTL
- Point-in-Time Recovery (PITR): Enabled on all four tables
- Key schemas and GSIs as defined in roadmap success criteria

### Cognito Configuration
- Account creation: Admin-only — no self-service signup
- Password policy: Claude's discretion (pick a reasonable policy)
- Access token duration: 1 hour
- MFA: Not required for v1 (deferred to AUTH-06 in v2)
- App Client: Public client (no client secret) — required for frontend Amplify integration
- User groups: WafrTeam and WafrClients

### IAM Permission Scoping
- DynamoDB permission scope: Claude's discretion (table-level pattern vs per-table+per-action)
- Policy type: Claude's discretion (inline vs managed, consider current inline pattern for Bedrock)
- Cognito permissions: Claude's discretion (read-only vs read+admin, based on what the app needs)
- Must not break existing Bedrock and S3 permissions on WafrAppRunnerInstanceRole

### Environment Variables
- Naming convention: WAFR_ prefix (e.g., WAFR_COGNITO_USER_POOL_ID, WAFR_DYNAMO_SESSIONS_TABLE)
- Deployment method: Claude's discretion (AWS CLI vs apprunner.yaml, based on current setup)
- AUTH_REQUIRED: Set to true immediately — do not start with false
- Scope: Set Cognito env vars on both frontend and backend App Runner services in this phase
- Cognito values (Pool ID, Client ID): Store in AWS Secrets Manager
- DynamoDB table names: Claude's discretion on whether to use Secrets Manager or plain env vars

### Claude's Discretion
- DynamoDB capacity mode selection
- Password policy strength
- IAM policy structure (inline vs managed, granularity)
- Cognito IAM permissions scope (read-only vs admin)
- Environment variable deployment method
- Whether DynamoDB table names go in Secrets Manager or plain env vars

</decisions>

<specifics>
## Specific Ideas

- Existing IAM role is `WafrAppRunnerInstanceRole` — already has Bedrock inference-profile and S3 permissions. Extend, don't replace.
- Backend App Runner service: `i5kj2nnkxd.us-east-1.awsapprunner.com`
- Frontend App Runner service: `3fhp6mfj7u.us-east-1.awsapprunner.com`
- Four DynamoDB tables: `wafr-sessions`, `wafr-review-sessions`, `wafr-users`, `wafr-audit-log`
- AUTH_REQUIRED=true from the start means Phases 2-4 testing will need auth tokens or a bypass mechanism during development

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-infrastructure-foundation*
*Context gathered: 2026-02-28*
