# Task 06: App Runner Services - Environment Variables Update

## Date
2026-02-28

## Plan
01-03, Task 2

## Summary
Updated both backend and frontend App Runner services with DynamoDB table names, Cognito secret references, and AUTH_REQUIRED flag. All pre-existing environment variables preserved.

## Backend Service (wafr-backend)

**Service ARN:** arn:aws:apprunner:us-east-1:842387632939:service/wafr-backend/aa3b1b32d7944f65b5aa1eb76c89357f
**Service URL:** https://i5kj2nnkxd.us-east-1.awsapprunner.com
**Final Status:** RUNNING

### RuntimeEnvironmentVariables (plain text)

| Key | Value | Source |
|-----|-------|--------|
| AWS_DEFAULT_REGION | us-east-1 | Pre-existing |
| PYTHONUNBUFFERED | 1 | Pre-existing |
| S3_BUCKET | wafr-agent-production-artifacts-842387632939 | Pre-existing |
| AUTH_REQUIRED | true | NEW (this plan) |
| WAFR_DYNAMO_SESSIONS_TABLE | wafr-sessions | NEW (this plan) |
| WAFR_DYNAMO_REVIEW_SESSIONS_TABLE | wafr-review-sessions | NEW (this plan) |
| WAFR_DYNAMO_USERS_TABLE | wafr-users | NEW (this plan) |
| WAFR_DYNAMO_AUDIT_TABLE | wafr-audit-log | NEW (this plan) |

### RuntimeEnvironmentSecrets (from Secrets Manager)

| Key | Secret ARN | Source |
|-----|-----------|--------|
| WAFR_COGNITO_USER_POOL_ID | arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-user-pool-id-jPl3bS | NEW (this plan) |
| WAFR_COGNITO_CLIENT_ID | arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-client-id-fZZtaL | NEW (this plan) |

## Frontend Service (wafr-frontend-app)

**Service ARN:** arn:aws:apprunner:us-east-1:842387632939:service/wafr-frontend-app/0810ab0676de401e9a3ed4de81e6c03c
**Service URL:** https://3fhp6mfj7u.us-east-1.awsapprunner.com
**Final Status:** RUNNING

### RuntimeEnvironmentVariables (plain text)

| Key | Value | Source |
|-----|-------|--------|
| AUTH_REQUIRED | true | NEW (this plan) |

### RuntimeEnvironmentSecrets (from Secrets Manager)

| Key | Secret ARN | Source |
|-----|-----------|--------|
| WAFR_COGNITO_USER_POOL_ID | arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-user-pool-id-jPl3bS | NEW (this plan) |
| WAFR_COGNITO_CLIENT_ID | arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-client-id-fZZtaL | NEW (this plan) |

**Instance Role Added:** arn:aws:iam::842387632939:role/WafrAppRunnerInstanceRole
(Required for Secrets Manager access — frontend had no instance role previously)

## Deviation

**[Rule 1 - Bug] Frontend service required InstanceRoleArn for RuntimeEnvironmentSecrets**
- App Runner API returned InvalidRequestException: "Instance Role have to be provided if passing in RuntimeEnvironmentSecrets"
- Frontend did not have an instance role configured previously
- Added WafrAppRunnerInstanceRole (same as backend) to frontend InstanceConfiguration
- This role already has SecretsManagerCognitoRead permission (added in Task 1 of this plan)

## Verification Status
PASSED - Both services RUNNING with correct env vars and secrets after update
