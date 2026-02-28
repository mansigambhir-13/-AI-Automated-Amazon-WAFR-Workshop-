# Phase 1: Infrastructure Foundation - Research

**Researched:** 2026-02-28
**Domain:** AWS Infrastructure provisioning — DynamoDB, Cognito User Pool, IAM policy extension, App Runner environment variables
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Phase boundary**: Zero application code changes. All work is AWS resource provisioning only.
- **Region and account**: All resources in us-east-1, AWS account 842387632939.
- **DynamoDB TTL**: 365-day TTL on `wafr-sessions` and `wafr-review-sessions`. No TTL on `wafr-audit-log` or `wafr-users`.
- **PITR**: Enabled on all four tables.
- **Key schemas and GSIs**: As defined in roadmap success criteria.
- **Cognito admin-only signup**: No self-service user creation.
- **Cognito access token duration**: 1 hour.
- **Cognito MFA**: Not required for v1.
- **Cognito App Client**: Public client — no client secret (required for frontend Amplify integration).
- **Cognito user groups**: `WafrTeam` and `WafrClients`.
- **Existing IAM role**: Extend `WafrAppRunnerInstanceRole` — do NOT replace it. Must not break existing Bedrock and S3 permissions.
- **Environment variable naming**: `WAFR_` prefix (e.g., `WAFR_COGNITO_USER_POOL_ID`, `WAFR_DYNAMO_SESSIONS_TABLE`).
- **AUTH_REQUIRED**: Set to `true` immediately — do not set to `false`.
- **Scope of env var updates**: Both frontend (`3fhp6mfj7u.us-east-1.awsapprunner.com`) and backend (`i5kj2nnkxd.us-east-1.awsapprunner.com`) App Runner services get Cognito env vars in this phase.
- **Cognito values (Pool ID, Client ID)**: Store in AWS Secrets Manager, reference via ARN in App Runner.

### Claude's Discretion

- DynamoDB capacity mode selection (on-demand vs provisioned).
- Password policy strength.
- IAM policy structure (inline vs managed, action granularity).
- Cognito IAM permissions scope (read-only vs read+admin).
- Environment variable deployment method (AWS CLI vs apprunner.yaml).
- Whether DynamoDB table names go in Secrets Manager or plain text env vars.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| OPER-03 | WafrAppRunnerInstanceRole IAM policy includes DynamoDB and Cognito permissions | IAM inline policy extension pattern verified; DynamoDB CRUD action list confirmed; Cognito read-only scope clarified |
</phase_requirements>

---

## Summary

Phase 1 is a pure AWS infrastructure provisioning phase — no application code is written or modified. The work divides into three sequential dependency chains: (1) DynamoDB table creation with correct schemas, TTL, and PITR; (2) Cognito User Pool creation with admin-only signup, App Client, and groups; (3) IAM role extension and App Runner environment variable injection.

All resources are created via AWS CLI targeting us-east-1, account 842387632939. The existing `WafrAppRunnerInstanceRole` already carries Bedrock, S3, WA Tool, and CloudWatch permissions in an inline policy structure (see `wafr-agents/wafr-iam-policy.json`). New DynamoDB and Cognito permissions are added as additional statements in that same inline policy — extending, not replacing.

Environment variables for Cognito (sensitive: Pool ID, Client ID) are stored as Secrets Manager secrets and referenced by ARN in App Runner `RuntimeEnvironmentSecrets`. DynamoDB table names (non-sensitive) are set as plain `RuntimeEnvironmentVariables`. **Critical**: App Runner's `update-service` call for ECR-based image services uses `SourceConfiguration.ImageRepository.ImageConfiguration.RuntimeEnvironmentVariables` / `RuntimeEnvironmentSecrets` — the full block must include all existing variables alongside new ones, because the API replaces rather than merges.

**Primary recommendation:** Create all resources via AWS CLI scripts in dependency order (tables → Cognito → IAM → env vars), verifying each step with describe/list commands before proceeding. Store all resulting ARNs/IDs as the inputs to the next step.

---

## Standard Stack

### Core

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| AWS CLI v2 | `>=2.13` | All resource provisioning commands | Only reliable way to script AWS resource creation without CDK/Terraform |
| DynamoDB | managed service | Session, user, audit, review storage | Already selected in roadmap |
| Cognito User Pools | managed service | Identity management, JWT issuance | Already selected in roadmap |
| IAM inline policy | existing pattern | Extend `WafrAppRunnerInstanceRole` | Project already uses inline policy; consistent extension |
| AWS Secrets Manager | managed service | Secure storage of Cognito Pool ID and Client ID | Locked decision in CONTEXT.md |
| App Runner `update-service` | AWS CLI | Inject env vars into running services | Project uses App Runner for both services |

### Supporting

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `aws dynamodb update-continuous-backups` | Enable PITR after table creation | After each `create-table` succeeds |
| `aws dynamodb update-time-to-live` | Enable TTL attribute on session tables | After each session table `create-table` succeeds |
| `aws cognito-idp create-user-pool-client` | Create the public App Client | After user pool creation |
| `aws cognito-idp create-group` | Create `WafrTeam` and `WafrClients` groups | After user pool creation |
| `aws apprunner list-services` | Discover service ARNs by URL | Before `update-service` — ARN required |
| `aws secretsmanager create-secret` | Store Cognito values | Before updating App Runner env vars |

---

## Architecture Patterns

### DynamoDB Table Design

**Capacity mode: On-demand (PAY_PER_REQUEST).** The platform's App Runner services scale to zero when idle. On-demand DynamoDB matches this cost profile — no idle charges, instant scaling, no capacity planning. Provisioned capacity requires predicting throughput and charges for provisioned but unused capacity. At this workload size (small internal team, occasional assessments), on-demand is correct. Source: [AWS DynamoDB on-demand docs](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html)

**Table schemas (derived from roadmap success criteria and prior architecture research):**

| Table | Partition Key | Sort Key | GSIs Needed | TTL | PITR |
|-------|--------------|----------|-------------|-----|------|
| `wafr-sessions` | `session_id` (S) | `created_at` (S) | `user_id-created_at-index` (PK: user_id, SK: created_at) | `expires_at` (365-day) | Yes |
| `wafr-review-sessions` | `session_id` (S) | `item_id` (S) | `status-created_at-index` (PK: status, SK: created_at) | `expires_at` (365-day) | Yes |
| `wafr-users` | `user_id` (S) | — | `email-index` (PK: email) | None | Yes |
| `wafr-audit-log` | `user_id` (S) | `timestamp#session_id` (S) | `session_id-timestamp-index` (PK: session_id, SK: timestamp) | None | Yes |

**Note on table names**: The roadmap specifies `wafr-audit-log` (not `wafr-audit`). The prior research doc shows `wafr-audit` — the roadmap success criterion is authoritative, so `wafr-audit-log` is correct.

### DynamoDB CLI Pattern

```bash
# Create table with GSI and on-demand billing
aws dynamodb create-table \
  --table-name wafr-sessions \
  --attribute-definitions \
    AttributeName=session_id,AttributeType=S \
    AttributeName=created_at,AttributeType=S \
    AttributeName=user_id,AttributeType=S \
  --key-schema \
    AttributeName=session_id,KeyType=HASH \
    AttributeName=created_at,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[
    {
      "IndexName": "user_id-created_at-index",
      "KeySchema": [
        {"AttributeName": "user_id", "KeyType": "HASH"},
        {"AttributeName": "created_at", "KeyType": "RANGE"}
      ],
      "Projection": {"ProjectionType": "ALL"}
    }
  ]' \
  --region us-east-1

# Enable TTL (separate command after table is ACTIVE)
aws dynamodb update-time-to-live \
  --table-name wafr-sessions \
  --time-to-live-specification AttributeName=expires_at,Enabled=true \
  --region us-east-1

# Enable PITR (separate command after table is ACTIVE)
aws dynamodb update-continuous-backups \
  --table-name wafr-sessions \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region us-east-1
```

Source: [DynamoDB create-table CLI docs](https://docs.aws.amazon.com/cli/latest/reference/dynamodb/create-table.html); [PITR CLI docs](https://docs.aws.amazon.com/cli/latest/reference/dynamodb/update-continuous-backups.html)

**Wait for ACTIVE status** before enabling TTL or PITR:
```bash
aws dynamodb wait table-exists --table-name wafr-sessions --region us-east-1
```

### Cognito User Pool Pattern

**Admin-only signup** uses `--admin-create-user-config AllowAdminCreateUserOnly=true`. Access token validity is set on the App Client, not the pool.

```bash
# Create User Pool
aws cognito-idp create-user-pool \
  --pool-name wafr-user-pool \
  --admin-create-user-config AllowAdminCreateUserOnly=true \
  --policies 'PasswordPolicy={MinimumLength=12,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=true,TemporaryPasswordValidityDays=7}' \
  --region us-east-1
# Returns: UserPool.Id (e.g., us-east-1_XXXXXXXXX)

# Create public App Client (no secret)
aws cognito-idp create-user-pool-client \
  --user-pool-id us-east-1_XXXXXXXXX \
  --client-name wafr-app-client \
  --no-generate-secret \
  --access-token-validity 1 \
  --token-validity-units AccessToken=hours \
  --explicit-auth-flows ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH \
  --region us-east-1
# Returns: UserPoolClient.ClientId

# Create groups
aws cognito-idp create-group \
  --user-pool-id us-east-1_XXXXXXXXX \
  --group-name WafrTeam \
  --description "Internal WAFR team members" \
  --region us-east-1

aws cognito-idp create-group \
  --user-pool-id us-east-1_XXXXXXXXX \
  --group-name WafrClients \
  --description "External WAFR clients" \
  --region us-east-1
```

Source: [Cognito create-user-pool CLI docs](https://docs.aws.amazon.com/cli/latest/reference/cognito-idp/create-user-pool.html); [create-user-pool-client CLI docs](https://docs.aws.amazon.com/cli/latest/reference/cognito-idp/create-user-pool-client.html)

**Password policy recommendation (Claude's discretion):** MinimumLength=12, require uppercase + lowercase + numbers + symbols. This is reasonably strong for an internal + client-facing business app without being onerous.

**Auth flows for Amplify:** `ALLOW_USER_SRP_AUTH` (Secure Remote Password — Amplify's default and most secure) + `ALLOW_REFRESH_TOKEN_AUTH`. Do NOT include `ALLOW_USER_PASSWORD_AUTH` (sends plaintext password over the wire).

### IAM Policy Extension Pattern

The existing inline policy is at role `WafrAppRunnerInstanceRole`. Extending it requires reading the current policy, merging new statements, and re-applying with `put-role-policy`.

```bash
# Get current inline policy (to merge, not replace)
aws iam get-role-policy \
  --role-name WafrAppRunnerInstanceRole \
  --policy-name <existing-policy-name> \
  --region us-east-1

# Apply extended policy (all statements — old + new)
aws iam put-role-policy \
  --role-name WafrAppRunnerInstanceRole \
  --policy-name WafrAppRunnerPolicy \
  --policy-document file://extended-policy.json \
  --region us-east-1
```

**DynamoDB permissions to add:**
```json
{
  "Sid": "DynamoDBCRUD",
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "dynamodb:BatchGetItem",
    "dynamodb:BatchWriteItem",
    "dynamodb:DescribeTable"
  ],
  "Resource": [
    "arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*",
    "arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*/index/*"
  ]
}
```

**Cognito permissions to add (Claude's discretion resolved: read-only for backend JWT validation context):**

JWT validation itself uses the public JWKS HTTP endpoint — no IAM permissions needed for that. The backend may need `AdminGetUser` if it looks up user metadata. Recommend adding read-only Cognito permissions scoped to the specific pool to avoid future permission gaps:

```json
{
  "Sid": "CognitoReadOnly",
  "Effect": "Allow",
  "Action": [
    "cognito-idp:AdminGetUser",
    "cognito-idp:ListUsersInGroup",
    "cognito-idp:DescribeUserPool"
  ],
  "Resource": "arn:aws:cognito-idp:us-east-1:842387632939:userpool/*"
}
```

**Secrets Manager permission needed** for App Runner to read Cognito secrets at service startup:
```json
{
  "Sid": "SecretsManagerCognitoRead",
  "Effect": "Allow",
  "Action": [
    "secretsmanager:GetSecretValue"
  ],
  "Resource": "arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-*"
}
```

Source: [IAM DynamoDB CRUD policy examples](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/iam-policy-example-data-crud.html); [IAM managed vs inline policy guidance](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-vs-inline.html)

### Secrets Manager Pattern

```bash
# Store Cognito values as a single JSON secret
aws secretsmanager create-secret \
  --name wafr-cognito-config \
  --description "WAFR Cognito User Pool ID and App Client ID" \
  --secret-string '{"user_pool_id":"us-east-1_XXXXXXXXX","client_id":"XXXXXXXXXXXXXXXXXXXXXXXXXXX"}' \
  --region us-east-1
# Returns: ARN like arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-config-XXXXX
```

**Alternative (two separate secrets for individual env var mapping):**
```bash
aws secretsmanager create-secret \
  --name wafr-cognito-user-pool-id \
  --secret-string "us-east-1_XXXXXXXXX" \
  --region us-east-1

aws secretsmanager create-secret \
  --name wafr-cognito-client-id \
  --secret-string "XXXXXXXXXXXXXXXXXXXXXXXXXXX" \
  --region us-east-1
```

**Recommendation:** Two separate secrets — App Runner maps one secret to one env var via `RuntimeEnvironmentSecrets`. A single JSON secret cannot be split into two env vars without application-level parsing.

### App Runner Environment Variable Update Pattern

App Runner services are ECR-image-based. The `update-service` JSON for an ECR image service:

```json
{
  "ServiceArn": "arn:aws:apprunner:us-east-1:842387632939:service/...",
  "SourceConfiguration": {
    "ImageRepository": {
      "ImageIdentifier": "842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-backend:latest",
      "ImageRepositoryType": "ECR",
      "ImageConfiguration": {
        "RuntimeEnvironmentVariables": {
          "AUTH_REQUIRED": "true",
          "WAFR_DYNAMO_SESSIONS_TABLE": "wafr-sessions",
          "WAFR_DYNAMO_REVIEW_SESSIONS_TABLE": "wafr-review-sessions",
          "WAFR_DYNAMO_USERS_TABLE": "wafr-users",
          "WAFR_DYNAMO_AUDIT_TABLE": "wafr-audit-log"
        },
        "RuntimeEnvironmentSecrets": {
          "WAFR_COGNITO_USER_POOL_ID": "arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-user-pool-id-XXXXX",
          "WAFR_COGNITO_CLIENT_ID": "arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-client-id-XXXXX"
        }
      }
    }
  }
}
```

**Deployment method (Claude's discretion resolved: AWS CLI with `--cli-input-json`).** The backend service is ECR-based (not apprunner.yaml code-based). The `apprunner.yaml` file method applies only to code-repository-based services. AWS CLI `update-service` is the correct method for ECR image services.

```bash
# Get service ARN first
BACKEND_ARN=$(aws apprunner list-services --region us-east-1 \
  --query "ServiceSummaryList[?ServiceUrl=='i5kj2nnkxd.us-east-1.awsapprunner.com'].ServiceArn" \
  --output text)

FRONTEND_ARN=$(aws apprunner list-services --region us-east-1 \
  --query "ServiceSummaryList[?ServiceUrl=='3fhp6mfj7u.us-east-1.awsapprunner.com'].ServiceArn" \
  --output text)

# Apply update
aws apprunner update-service \
  --cli-input-json file://backend-update.json \
  --region us-east-1
```

Source: [App Runner env var management docs](https://docs.aws.amazon.com/apprunner/latest/dg/env-variable-manage.html); [App Runner env var reference](https://docs.aws.amazon.com/apprunner/latest/dg/env-variable.html)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DynamoDB table creation | Custom CloudFormation / CDK | AWS CLI `create-table` | Simplest for imperative one-time provisioning; no state file to manage |
| Secret storage | Env var in App Runner console plain text | AWS Secrets Manager | Console plain text is visible to anyone with console access; Secrets Manager encrypts and audits |
| PITR | Manual backup scripts | `update-continuous-backups` | AWS managed, automatic, restores to any second in the retention window |
| TTL expiry | Background cleanup Lambda | DynamoDB native TTL | DynamoDB handles expiry automatically at no extra cost |

---

## Common Pitfalls

### Pitfall 1: `update-service` Replaces, Not Merges, Environment Variables

**What goes wrong:** Calling `update-service` with only the new env vars drops all existing ones. If the service already has `BEDROCK_MODEL_ID`, `S3_BUCKET`, etc., and you only pass Cognito vars, those existing vars disappear.

**Why it happens:** App Runner's `update-service` API replaces the entire `RuntimeEnvironmentVariables` and `RuntimeEnvironmentSecrets` blocks — it does not merge. Source: confirmed via documentation omission + community reports.

**How to avoid:** Before calling `update-service`, call `describe-service` to retrieve the current environment variable configuration, merge in new values, then call `update-service` with the full merged set.

**Warning signs:** App crashes after env var update with "missing required environment variable" errors.

### Pitfall 2: TTL and PITR Cannot Be Set During `create-table`

**What goes wrong:** Both TTL (`update-time-to-live`) and PITR (`update-continuous-backups`) require the table to be in `ACTIVE` status. They are separate API calls, not parameters on `create-table`. Attempting to enable them immediately after `create-table` without waiting causes errors.

**Why it happens:** `create-table` returns before the table is fully active. The `TableStatus` is `CREATING` for a few seconds.

**How to avoid:** Use `aws dynamodb wait table-exists --table-name <name>` before calling `update-time-to-live` or `update-continuous-backups`.

**Warning signs:** `ResourceInUseException: Table is being created` on the secondary commands.

### Pitfall 3: GSI Attribute Definitions Must Cover All GSI Key Attributes

**What goes wrong:** DynamoDB requires every attribute used in ANY key schema (base table or GSI) to appear in `--attribute-definitions`. Omitting a GSI partition key from `attribute-definitions` causes `ValidationException`.

**Why it happens:** Developers include only the base table's partition/sort key in `attribute-definitions` by mistake.

**How to avoid:** List all unique attributes used as PK or SK in any GSI alongside base table keys in `--attribute-definitions`. No other attributes are defined there — DynamoDB is schemaless for non-key attributes.

### Pitfall 4: IAM Inline Policy Must Include /index/* for GSI Query Permissions

**What goes wrong:** The IAM policy resource `arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*` covers table-level operations but NOT GSI queries. Querying a GSI requires `arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*/index/*` as an additional resource.

**Why it happens:** The index path is a separate ARN sub-resource in DynamoDB's IAM model.

**How to avoid:** Always include both `table/wafr-*` and `table/wafr-*/index/*` in the Resource list for DynamoDB permissions.

**Warning signs:** `AccessDeniedException` on Query operations against GSI paths only; GetItem works fine.

### Pitfall 5: Cognito App Client Auth Flows Must Include SRP for Amplify

**What goes wrong:** If `ALLOW_USER_SRP_AUTH` is omitted from `explicit-auth-flows`, Amplify's default `signIn` call fails because Amplify uses SRP by default.

**Why it happens:** Developers add only `ALLOW_USER_PASSWORD_AUTH` or only `ALLOW_REFRESH_TOKEN_AUTH`.

**How to avoid:** Always include `ALLOW_USER_SRP_AUTH` and `ALLOW_REFRESH_TOKEN_AUTH` for Amplify-based clients. Do NOT include `ALLOW_USER_PASSWORD_AUTH` (sends plaintext password).

### Pitfall 6: Secrets Manager Secret ARN Has a Random Suffix — Use Partial ARN or Name Carefully

**What goes wrong:** Secrets Manager appends a 6-character random suffix to secret ARNs (e.g., `wafr-cognito-user-pool-id-AbCdEf`). IAM policy `Resource` patterns must account for this, or the App Runner instance role will not have `GetSecretValue` permission on the created secret.

**Why it happens:** The ARN is only known after secret creation.

**How to avoid:** Use a wildcard suffix in the IAM resource ARN: `arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-*`. This matches all WAFR Cognito secrets regardless of suffix. Alternatively, tighten after creation by using the exact ARN returned by `create-secret`.

---

## Code Examples

### Complete wafr-sessions Table Creation

```bash
# Source: AWS CLI DynamoDB create-table documentation
aws dynamodb create-table \
  --table-name wafr-sessions \
  --attribute-definitions \
    AttributeName=session_id,AttributeType=S \
    AttributeName=created_at,AttributeType=S \
    AttributeName=user_id,AttributeType=S \
  --key-schema \
    AttributeName=session_id,KeyType=HASH \
    AttributeName=created_at,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[{
    "IndexName": "user_id-created_at-index",
    "KeySchema": [
      {"AttributeName": "user_id", "KeyType": "HASH"},
      {"AttributeName": "created_at", "KeyType": "RANGE"}
    ],
    "Projection": {"ProjectionType": "ALL"}
  }]' \
  --region us-east-1

aws dynamodb wait table-exists --table-name wafr-sessions --region us-east-1

aws dynamodb update-time-to-live \
  --table-name wafr-sessions \
  --time-to-live-specification AttributeName=expires_at,Enabled=true \
  --region us-east-1

aws dynamodb update-continuous-backups \
  --table-name wafr-sessions \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region us-east-1
```

### wafr-audit-log Table (no TTL, composite sort key for temporal queries)

```bash
# Source: AWS CLI DynamoDB create-table documentation
aws dynamodb create-table \
  --table-name wafr-audit-log \
  --attribute-definitions \
    AttributeName=user_id,AttributeType=S \
    AttributeName=timestamp_session_id,AttributeType=S \
    AttributeName=session_id,AttributeType=S \
    AttributeName=timestamp,AttributeType=S \
  --key-schema \
    AttributeName=user_id,KeyType=HASH \
    AttributeName=timestamp_session_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --global-secondary-indexes '[{
    "IndexName": "session_id-timestamp-index",
    "KeySchema": [
      {"AttributeName": "session_id", "KeyType": "HASH"},
      {"AttributeName": "timestamp", "KeyType": "RANGE"}
    ],
    "Projection": {"ProjectionType": "ALL"}
  }]' \
  --region us-east-1

aws dynamodb wait table-exists --table-name wafr-audit-log --region us-east-1

# No TTL on audit log (per locked decision)
aws dynamodb update-continuous-backups \
  --table-name wafr-audit-log \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region us-east-1
```

### Complete IAM Policy Document (extended, with existing permissions preserved)

The executor must first read the current inline policy via `aws iam get-role-policy`, then produce a merged document. The new statements to add are:

```json
{
  "Sid": "DynamoDBCRUD",
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "dynamodb:BatchGetItem",
    "dynamodb:BatchWriteItem",
    "dynamodb:DescribeTable"
  ],
  "Resource": [
    "arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*",
    "arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*/index/*"
  ]
},
{
  "Sid": "CognitoReadOnly",
  "Effect": "Allow",
  "Action": [
    "cognito-idp:AdminGetUser",
    "cognito-idp:ListUsersInGroup",
    "cognito-idp:DescribeUserPool"
  ],
  "Resource": "arn:aws:cognito-idp:us-east-1:842387632939:userpool/*"
},
{
  "Sid": "SecretsManagerCognitoRead",
  "Effect": "Allow",
  "Action": [
    "secretsmanager:GetSecretValue"
  ],
  "Resource": "arn:aws:secretsmanager:us-east-1:842387632939:secret:wafr-cognito-*"
}
```

### Retrieve Current Env Vars Before Updating (prevent wipe)

```bash
# Source: AWS App Runner describe-service CLI docs
aws apprunner describe-service \
  --service-arn $BACKEND_ARN \
  --region us-east-1 \
  --query "Service.SourceConfiguration.ImageRepository.ImageConfiguration"
```

### Verify Table Creation

```bash
aws dynamodb describe-table --table-name wafr-sessions --region us-east-1 \
  --query "Table.{Status:TableStatus, BillingMode:BillingModeSummary.BillingMode, GSIs:GlobalSecondaryIndexes[*].IndexName}"
```

### Verify PITR Status

```bash
aws dynamodb describe-continuous-backups --table-name wafr-sessions --region us-east-1 \
  --query "ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus"
```

### Verify Cognito User Pool

```bash
aws cognito-idp describe-user-pool \
  --user-pool-id us-east-1_XXXXXXXXX \
  --region us-east-1 \
  --query "UserPool.{AdminOnly:AdminCreateUserConfig.AllowAdminCreateUserOnly, PoolName:Name}"
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|-----------------|--------|
| `PROVISIONED` capacity with Auto Scaling | `PAY_PER_REQUEST` on-demand | No capacity planning, correct for low-traffic / idle apps |
| Manual JSON secret copy-paste in App Runner console | Secrets Manager ARN reference via `RuntimeEnvironmentSecrets` | Secrets not visible in console; auditable access |
| Single `wafr-*` IAM resource wildcard without index path | `wafr-*` + `wafr-*/index/*` | GSI queries work correctly |
| `python-jose` for JWT validation | `PyJWT 2.11.0` with `PyJWKClient` | Avoids archived dependency in security-critical path |

---

## Open Questions

1. **Exact current inline policy name on `WafrAppRunnerInstanceRole`**
   - What we know: The file `wafr-agents/wafr-iam-policy.json` contains the policy JSON, but the actual name of the inline policy attached to the role in AWS is unknown.
   - What's unclear: Whether the role has one or multiple inline policies, and what they are named.
   - Recommendation: Executor must run `aws iam list-role-policies --role-name WafrAppRunnerInstanceRole` as the first step of Plan 01-03 to discover the policy name(s) before calling `put-role-policy`.

2. **Current App Runner service configuration (image ID, existing env vars)**
   - What we know: Backend URL is `i5kj2nnkxd.us-east-1.awsapprunner.com`, frontend URL is `3fhp6mfj7u.us-east-1.awsapprunner.com`.
   - What's unclear: Current `ImageIdentifier` tag in use, any existing `RuntimeEnvironmentVariables` or `RuntimeEnvironmentSecrets`.
   - Recommendation: Executor must run `aws apprunner describe-service` on both services before generating the `update-service` JSON to ensure no existing variables are dropped.

3. **Exact GSI attribute name for `wafr-audit-log` sort key**
   - What we know: The roadmap says sort key is `timestamp#session_id` (S) — a composite string.
   - What's unclear: Whether Phase 2 application code will write this as a single composite attribute (e.g., `"2026-02-28T12:00:00Z#sess-123"`) or as separate attributes.
   - Recommendation: The DynamoDB attribute in Phase 1 should be named `timestamp_session_id` (underscore, valid DynamoDB attribute name — `#` is reserved in DynamoDB expression syntax). Phase 2 writes the composite value as a formatted string. Document this naming convention in the table creation plan.

---

## Sources

### Primary (HIGH confidence)

- [AWS DynamoDB on-demand capacity mode](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html) — on-demand billing mode facts, limits, CLI flag
- [AWS DynamoDB create-table CLI reference](https://docs.aws.amazon.com/cli/latest/reference/dynamodb/create-table.html) — create-table parameter structure
- [AWS DynamoDB GSI CLI example](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GCICli.html) — working GSI create-table example
- [AWS DynamoDB PITR update-continuous-backups](https://docs.aws.amazon.com/cli/latest/reference/dynamodb/update-continuous-backups.html) — PITR enable CLI
- [AWS Cognito create-user-pool CLI](https://docs.aws.amazon.com/cli/latest/reference/cognito-idp/create-user-pool.html) — admin-only, password policy parameters
- [AWS Cognito create-user-pool-client CLI](https://docs.aws.amazon.com/cli/latest/reference/cognito-idp/create-user-pool-client.html) — public client, access token validity, auth flows
- [AWS App Runner env var reference](https://docs.aws.amazon.com/apprunner/latest/dg/env-variable.html) — Secrets Manager ARN format, IAM requirements
- [AWS App Runner env var management](https://docs.aws.amazon.com/apprunner/latest/dg/env-variable-manage.html) — RuntimeEnvironmentSecrets JSON structure, IAM policy template
- [AWS DynamoDB IAM CRUD policy example](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/iam-policy-example-data-crud.html) — complete action list, resource ARN formats
- [AWS IAM managed vs inline policy guidance](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-vs-inline.html) — decision rationale
- `.planning/research/STACK.md` — prior project-level technology stack research (Feb 2026)
- `.planning/research/PITFALLS.md` — prior domain pitfall research (Feb 2026)
- `wafr-agents/wafr-iam-policy.json` — existing inline policy, confirmed Bedrock/S3/WA Tool permissions to preserve

### Secondary (MEDIUM confidence)

- [AWS App Runner Secrets Manager integration announcement](https://aws.amazon.com/blogs/containers/aws-app-runner-now-integrates-with-aws-secrets-manager-and-aws-systems-manager-parameter-store/) — Secrets Manager integration confirmation (secrets pulled at deploy time, not runtime)
- [DynamoDB on-demand vs provisioned TechTarget](https://www.techtarget.com/searchcloudcomputing/answer/DynamoDB-on-demand-vs-provisioned-capacity-Which-is-better) — capacity mode selection guidance

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all tools are AWS native services with official CLI documentation verified
- Architecture patterns: HIGH — CLI commands verified against official AWS docs; table schema derived from roadmap success criteria
- Pitfalls: HIGH — IAM/index/* pitfall and TTL sequencing verified via official docs; env var merge pitfall is documented behavior
- Open questions: Known unknowns requiring discovery steps at execution time (not blockers)

**Research date:** 2026-02-28
**Valid until:** 2026-08-28 (AWS CLI syntax for DynamoDB/Cognito/App Runner is stable; re-verify if major AWS service updates occur)
