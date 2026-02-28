# Phase 5: Data Migration and Audit Validation - Research

**Researched:** 2026-02-28
**Domain:** AWS operational runbook — ECR/Docker deployment, App Runner service management, Cognito user provisioning, DynamoDB migration, end-to-end smoke testing
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Migration Execution**
- Existing file-based sessions need to be migrated to DynamoDB
- Migration script runs inside the App Runner container (not from local machine)
- Rollback plan: DynamoDB PITR (Point-in-Time Recovery) to restore pre-migration state if something goes wrong
- Claude's discretion on post-migration validation approach (count comparison, spot-check, or both)

**Auth Enforcement Cutover**
- AUTH_REQUIRED=true is already set on App Runner from Phase 1 — enforce immediately on deploy (no temporary false)
- Emergency rollback: flip AUTH_REQUIRED=false via App Runner env var update (~1 minute, no code redeploy)
- Create test users as part of this phase: one WafrTeam user, one WafrClients user
- Claude generates secure passwords for test users — passwords output to operator, stored nowhere in code

**End-to-End Smoke Test**
- Full assessment lifecycle: Login → create assessment → run analysis → review decisions → download report → logout
- Test both WafrTeam and WafrClients user roles
- Manual checklist format (not scripted/automated) — step-by-step document to walk through in the browser
- Verify audit log entries exist in wafr-audit-log DynamoDB table after smoke test
- Pass/fail criteria: any auth or data issue blocks the milestone (login failure, 401 on authenticated requests, missing sessions, absent audit entries)

**Deployment Sequencing**
- Deploy frontend and backend simultaneously (both App Runner services updated at the same time)
- Docker images built and pushed via CLI commands (Claude provides exact commands, operator executes)
- ECR container registry already exists — push images there
- Migration runs after deploy — new code has DynamoDB support, migration writes to DynamoDB from within the running container

### Claude's Discretion
- Post-migration validation depth (count comparison vs spot-check vs both)
- Exact deployment CLI commands (docker build, push, update-service)
- Smoke test checklist structure and ordering
- Audit log query commands for verification

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| OPER-01 | Existing file-based sessions are migrated to DynamoDB via migration script | Migration script at `wafr-agents/scripts/migrate_sessions.py` is idempotent, supports `--dry-run`, logs per-session. 10 sessions + 4 pipeline results confirmed in local `review_sessions/`. Script runs inside App Runner via entrypoint wrapper pattern. |
| OPER-02 | AUTH_REQUIRED environment flag enables gradual auth rollout | Already set to `true` on both App Runner services per backend-update.json and frontend-update.json. Enforced on deploy. Emergency rollback via `aws apprunner update-service`. |
</phase_requirements>

---

## Summary

Phase 5 is a pure operational runbook phase — no new code is written. All infrastructure, storage, authentication, and frontend code was completed in Phases 1-4. This phase runs the one-time file-to-DynamoDB migration, deploys updated Docker images to both App Runner services simultaneously, creates two Cognito test users, and validates the entire system with a manual browser smoke test.

The single critical constraint that shapes all planning is that **App Runner does not support shell exec into running containers**. The migration script cannot be triggered interactively. The only viable approach without a code redeploy is to incorporate the migration as a startup command in the Dockerfile entrypoint or to build a dedicated migration container image. Research confirms the recommended pattern for App Runner one-off tasks is an entrypoint wrapper script that runs migrations before the main server process starts.

The ECR/Docker workflow, Cognito user provisioning via admin CLI, DynamoDB audit log querying, and App Runner `start-deployment` for simultaneous deployment are all well-documented standard AWS CLI operations with HIGH confidence. The migration script itself is already built: 369 lines, idempotent (skips already-migrated sessions via existence check), `--dry-run` supported, exits 1 on any individual failure.

**Primary recommendation:** Run migration by building a migration-only Docker image variant (or an entrypoint wrapper) that runs `python scripts/migrate_sessions.py` and exits, deployed as a temporary App Runner service update or as a one-off container run outside App Runner using `docker run` locally with the same AWS credentials and env vars the App Runner service uses.

---

## Standard Stack

### Core (all already installed in this project)

| Tool | Version/Source | Purpose | Why Standard |
|------|---------------|---------|--------------|
| AWS CLI v2 | System (operator machine) | ECR auth, App Runner deployment, Cognito user creation, DynamoDB queries | Only CLI for AWS control-plane operations |
| Docker | System (operator machine) | Build + push images to ECR | Required for ECR image pushes |
| `wafr-agents/scripts/migrate_sessions.py` | Project (369 lines) | File-to-DynamoDB migration | Already built, idempotent, tested |
| boto3 | In `requirements.txt` | Migration script DynamoDB client | Used by existing storage layer |

### Supporting

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `aws apprunner start-deployment` | Trigger deployment after image push | After both ECR images pushed |
| `aws apprunner describe-service` | Poll deployment status | After start-deployment to monitor RUNNING state |
| `aws apprunner update-service` | Emergency rollback (flip AUTH_REQUIRED=false) | Only if smoke test reveals auth is broken |
| `aws cognito-idp admin-create-user` | Provision test users | Before smoke test |
| `aws cognito-idp admin-set-user-password --permanent` | Set permanent password (bypass FORCE_CHANGE_PASSWORD) | Immediately after admin-create-user |
| `aws cognito-idp admin-add-user-to-group` | Assign users to WafrTeam / WafrClients | After each user is created |
| `aws dynamodb scan` | Count items in tables post-migration | Post-migration validation |
| `aws dynamodb query` | Verify audit log entries by user_id | After smoke test |

---

## Architecture Patterns

### Critical Constraint: App Runner Has No Shell Exec

**Finding (MEDIUM confidence — verified from multiple community sources + GitHub roadmap issue #251):**
App Runner does NOT support `docker exec`-style access to running containers. There is no `aws apprunner exec` command. The AWS App Runner GitHub roadmap issue #251 ("Ability to run a shell command") has been open since at least 2023 and was not resolved as of the search date.

**Consequence for migration:** The locked decision says "migration runs inside the App Runner container." This means the migration must be triggered via one of these patterns:

**Pattern A — Entrypoint Wrapper Script (recommended for this phase)**
Build the backend Docker image with a startup.sh entrypoint that:
1. Runs `python scripts/migrate_sessions.py` first
2. Then `exec uvicorn ...` (the normal server start)

The migration is idempotent — re-running it skips already-migrated items. On subsequent container restarts, the script runs again, finds everything already in DynamoDB, and proceeds in <1 second. This matches the Django migrations pattern documented in AWS's own App Runner blog posts.

**Pattern B — Local Docker Run (simpler, no Dockerfile change)**
Since the migration script needs only: (1) DynamoDB access via IAM, and (2) the file-based sessions directory, the operator can run the migration locally using Docker with the same env vars:
```bash
docker run --rm \
  -e AWS_ACCESS_KEY_ID=... \
  -e AWS_SECRET_ACCESS_KEY=... \
  -e AWS_DEFAULT_REGION=us-east-1 \
  -e REVIEW_STORAGE_TYPE=dynamodb \
  -e WAFR_DYNAMO_SESSIONS_TABLE=wafr-sessions \
  -e WAFR_DYNAMO_REVIEW_SESSIONS_TABLE=wafr-review-sessions \
  -e WAFR_DYNAMO_USERS_TABLE=wafr-users \
  -e WAFR_DYNAMO_AUDIT_TABLE=wafr-audit-log \
  -v /path/to/wafr-agents:/app \
  -w /app \
  python:3.11-slim \
  python scripts/migrate_sessions.py --dry-run
```

**Recommendation:** Pattern A (entrypoint wrapper) aligns with the locked decision ("runs inside container"). It keeps migration co-located with the deploy. The planner should choose Pattern A — modify `Dockerfile` to use an `entrypoint.sh` wrapper, then deploy.

### Migration Data Volume (Confirmed)

From filesystem inspection:
- `review_sessions/sessions/`: **10 JSON files** (10 sessions to migrate)
- `review_sessions/pipeline_results/`: **4 JSON files** (4 pipeline results to migrate)
- Total: 14 DynamoDB writes on first run; all subsequent runs skip (idempotent)

Session file schema confirmed: `['session_id', 'created_at', 'status', 'items', 'transcript_answers_count', 'summary']`

### Deployment: ECR Push + App Runner start-deployment

**Pattern (HIGH confidence — official AWS docs):**

```bash
# Step 1: Authenticate Docker to ECR (token valid 12 hours)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  842387632939.dkr.ecr.us-east-1.amazonaws.com

# Step 2: Build backend image (with scripts/ directory added)
docker build -t wafr-backend:latest ./wafr-agents/

# Step 3: Tag and push backend
docker tag wafr-backend:latest \
  842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-backend:latest
docker push 842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-backend:latest

# Step 4: Build frontend image (bake in Cognito values at build time)
docker build \
  --build-arg NEXT_PUBLIC_BACKEND_URL=https://i5kj2nnkxd.us-east-1.awsapprunner.com \
  --build-arg NEXT_PUBLIC_COGNITO_USER_POOL_ID=us-east-1_U4ugKPUrh \
  --build-arg NEXT_PUBLIC_COGNITO_CLIENT_ID=65fis729feu3lr317rm6oaue5s \
  -t wafr-frontend:latest ./aws-frontend/

# Step 5: Tag and push frontend
docker tag wafr-frontend:latest \
  842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-frontend:latest
docker push 842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-frontend:latest

# Step 6: Trigger both App Runner deployments simultaneously
aws apprunner start-deployment \
  --service-arn arn:aws:apprunner:us-east-1:842387632939:service/wafr-backend/aa3b1b32d7944f65b5aa1eb76c89357f \
  --region us-east-1

aws apprunner start-deployment \
  --service-arn arn:aws:apprunner:us-east-1:842387632939:service/wafr-frontend-app/0810ab0676de401e9a3ed4de81e6c03c \
  --region us-east-1
```

**Key insight:** `start-deployment` uses the existing image already pushed to ECR and triggers App Runner to pull and deploy it. It requires only the service ARN. `update-service` is for configuration changes; `start-deployment` is for deploying new image versions.

**Monitoring deployment completion:**
```bash
aws apprunner describe-service \
  --service-arn arn:aws:apprunner:us-east-1:842387632939:service/wafr-backend/aa3b1b32d7944f65b5aa1eb76c89357f \
  --query 'Service.Status' --output text
# Expected output: RUNNING (vs OPERATION_IN_PROGRESS during update)
```

### Cognito Test User Provisioning

**Pattern (HIGH confidence — official AWS CLI docs verified):**

The user creation flow is a 3-step sequence per user: create → set permanent password → add to group.

```bash
# --- WafrTeam test user ---
aws cognito-idp admin-create-user \
  --user-pool-id us-east-1_U4ugKPUrh \
  --username wafr-team-test \
  --user-attributes Name=email,Value=wafr-team-test@example.com \
                    Name=email_verified,Value=true \
  --message-action SUPPRESS \
  --region us-east-1

# Set permanent password (bypasses FORCE_CHANGE_PASSWORD status)
aws cognito-idp admin-set-user-password \
  --user-pool-id us-east-1_U4ugKPUrh \
  --username wafr-team-test \
  --password "<GENERATED_PASSWORD>" \
  --permanent \
  --region us-east-1

# Add to WafrTeam group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id us-east-1_U4ugKPUrh \
  --username wafr-team-test \
  --group-name WafrTeam \
  --region us-east-1

# --- WafrClients test user (same 3 steps) ---
aws cognito-idp admin-create-user \
  --user-pool-id us-east-1_U4ugKPUrh \
  --username wafr-client-test \
  --user-attributes Name=email,Value=wafr-client-test@example.com \
                    Name=email_verified,Value=true \
  --message-action SUPPRESS \
  --region us-east-1

aws cognito-idp admin-set-user-password \
  --user-pool-id us-east-1_U4ugKPUrh \
  --username wafr-client-test \
  --password "<GENERATED_PASSWORD>" \
  --permanent \
  --region us-east-1

aws cognito-idp admin-add-user-to-group \
  --user-pool-id us-east-1_U4ugKPUrh \
  --username wafr-client-test \
  --group-name WafrClients \
  --region us-east-1
```

**Critical: `--permanent` flag on admin-set-user-password**
Without `--permanent`, the user status stays `FORCE_CHANGE_PASSWORD` and the user cannot log in via the Amplify UI (which uses SRP auth, not admin auth). The `--permanent` flag sets status to `CONFIRMED` immediately.

**Password requirements:** Cognito User Pool must have a password policy; the generated password must satisfy it. The pool was created in Phase 1 — standard policy typically requires 8+ chars, uppercase, lowercase, number, symbol.

### Audit Log Verification Queries

The `wafr-audit-log` table schema (from `audit.py`):
- **PK**: `user_id` (String) — Cognito `sub` claim UUID
- **SK**: `timestamp_session_id` (String) — format: `<ISO_UTC>_<session_id_or_no-session>`

**Verification approach — scan after smoke test:**
```bash
# Count all audit entries (smoke test generates at least 1 per authenticated request)
aws dynamodb scan \
  --table-name wafr-audit-log \
  --select COUNT \
  --region us-east-1

# Scan recent entries to verify content (returns all attributes)
aws dynamodb scan \
  --table-name wafr-audit-log \
  --region us-east-1 \
  --output table

# Query by user_id (need Cognito sub — get it after login from JWT decode)
aws dynamodb query \
  --table-name wafr-audit-log \
  --key-condition-expression "user_id = :uid" \
  --expression-attribute-values '{":uid":{"S":"<cognito-sub-uuid>"}}' \
  --region us-east-1
```

**Simpler verification:** Because `user_id` is the PK and we know the usernames (not subs) before login, the easiest post-smoke-test check is a full scan with COUNT > 0, then inspect one row to confirm `action_type`, `path`, and `status_code` fields are populated.

### Post-Migration Validation (Claude's Discretion: use both count + spot-check)

```bash
# Count sessions in DynamoDB after migration
aws dynamodb scan \
  --table-name wafr-sessions \
  --select COUNT \
  --region us-east-1
# Expected: >= 10 (the 10 local session files)

# Count review sessions
aws dynamodb scan \
  --table-name wafr-review-sessions \
  --select COUNT \
  --region us-east-1
# Expected: > 0 (at minimum the 4 pipeline result sessions have review data)

# Spot-check: verify a known session_id from the file system exists in DynamoDB
aws dynamodb get-item \
  --table-name wafr-sessions \
  --key '{"session_id":{"S":"1225d11d-c2ce-4236-b7fc-41d54b31a5e5"}}' \
  --region us-east-1
```

### Emergency Rollback Pattern

**AUTH_REQUIRED rollback (no redeploy needed, ~1 min):**
```bash
aws apprunner update-service \
  --service-arn arn:aws:apprunner:us-east-1:842387632939:service/wafr-backend/aa3b1b32d7944f65b5aa1eb76c89357f \
  --source-configuration file://backend-update.json \
  --region us-east-1
```
Where `backend-update.json` has `AUTH_REQUIRED: false` in `RuntimeEnvironmentVariables`. This does NOT require a new Docker image push — App Runner restarts the existing container with the new env var.

**PITR rollback (DynamoDB, only for catastrophic migration failure):**
Use AWS Console → DynamoDB → Table → Backups → Restore to point in time (before migration ran). This creates a new table — the application's env var table names would need to be updated, making this a last resort.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Migration idempotency | Custom "already-migrated" flag file | Built into `migrate_sessions.py` via `load_session()` existence check | Script already written; skips existing DynamoDB records |
| ECR authentication | Manual credential passing | `aws ecr get-login-password \| docker login` | Standard AWS pattern; token valid 12h |
| Cognito password status | Custom user state reset endpoint | `admin-set-user-password --permanent` | One CLI call sets CONFIRMED status |
| DynamoDB count verification | Full table download and count locally | `aws dynamodb scan --select COUNT` | Returns count without transferring items |
| App Runner deployment waiting | Sleep loops in scripts | `aws apprunner describe-service --query Service.Status` | Poll until RUNNING |

---

## Common Pitfalls

### Pitfall 1: Migration Script Cannot Be Invoked via SSH/Exec on App Runner
**What goes wrong:** Operator tries `aws apprunner exec` or expects a shell — this command does not exist.
**Why it happens:** App Runner is a fully managed service; it does not expose container shell access (unlike ECS with ECS Exec enabled).
**How to avoid:** Use the entrypoint wrapper pattern — add a `scripts/entrypoint.sh` to the backend Dockerfile that runs migration then starts uvicorn. The migration is idempotent so running on every startup is safe.
**Warning signs:** Any plan task that says "ssh into" or "exec into" the App Runner container is wrong.

### Pitfall 2: Migration Script Default Paths Are Relative to CWD
**What goes wrong:** Script defaults to `review_sessions/sessions` and `review_sessions/pipeline_results` relative to CWD. Inside the App Runner container, `WORKDIR` is `/app`. The files are at `/app/review_sessions/sessions/`.
**Why it happens:** The Dockerfile copies `review_sessions/` into the image (implied by `RUN mkdir -p review_sessions/pipeline_results review_sessions/sessions`), but session data from local dev is NOT copied into the Docker image — only the directory structure is created.
**Critical implication:** The local file-based sessions (`review_sessions/sessions/*.json`) are on the developer's machine, NOT in the ECR image. The migration must be run from the local machine (Pattern B) OR the local session files must be included in the Docker image (not recommended — secrets risk).
**Recommendation:** Run migration via Pattern B (local `docker run` with AWS credentials), not from inside the App Runner container. The session files live locally and can access DynamoDB directly if the operator has valid AWS credentials.

### Pitfall 3: Frontend NEXT_PUBLIC_* Variables Must Be Baked at Build Time
**What goes wrong:** NEXT_PUBLIC_ environment variables are inlined at build time by Next.js. Setting them in App Runner's `RuntimeEnvironmentVariables` does NOT make them available to the browser bundle — they are server-only runtime vars.
**Why it happens:** Next.js compiles NEXT_PUBLIC_ vars into the client-side JavaScript during `npm run build`. The Dockerfile uses ARG/ENV correctly for this.
**How to avoid:** Always pass `--build-arg NEXT_PUBLIC_COGNITO_USER_POOL_ID=...` during `docker build`. Already done in the Dockerfile — operator must not forget the `--build-arg` flags.
**Warning signs:** Frontend shows blank/undefined Cognito config; login page errors with "UserPool not configured".

### Pitfall 4: admin-create-user Without --permanent Leaves User Unable to Login
**What goes wrong:** User is created but stuck in `FORCE_CHANGE_PASSWORD` status. Amplify's SRP auth flow rejects this user — it expects `CONFIRMED` status for normal login.
**Why it happens:** Cognito admin-created users must change password on first login by default. The `--temporary-password` flag creates a temporary credential that requires the Cognito challenge flow.
**How to avoid:** Always follow `admin-create-user` immediately with `admin-set-user-password --permanent`.

### Pitfall 5: DynamoDB wafr-sessions Table Key Schema
**What goes wrong:** Using `get-item` or `query` with wrong key attribute name.
**Why it happens:** The `wafr-sessions` table PK is `session_id` (not `id` or `pk`). The `wafr-audit-log` table has PK `user_id` and SK `timestamp_session_id` (underscore, not hash — hash is reserved in DynamoDB expression syntax per Phase 1 decision).
**How to avoid:** Use the exact key attribute names from the table schema.

### Pitfall 6: App Runner Deployment Takes 2-5 Minutes
**What goes wrong:** Operator checks the URL immediately after `start-deployment` and sees old behavior.
**Why it happens:** App Runner pulls the new image, starts new instances, health-checks them, then shifts traffic. This takes 2-5 minutes typically.
**How to avoid:** Poll `describe-service --query Service.Status` until it returns `RUNNING`. Only begin smoke test after both services show RUNNING.

### Pitfall 7: Migration Script Needs REVIEW_STORAGE_TYPE=dynamodb + WAFR_DYNAMO_* env vars
**What goes wrong:** `create_review_storage('dynamodb')` fails to connect or uses wrong table names.
**Why it happens:** The storage factory reads env vars `WAFR_DYNAMO_SESSIONS_TABLE`, `WAFR_DYNAMO_REVIEW_SESSIONS_TABLE`, `WAFR_DYNAMO_USERS_TABLE`, `WAFR_DYNAMO_AUDIT_TABLE`.
**How to avoid:** Set all four WAFR_DYNAMO_* env vars when running migration locally. Values confirmed in `backend-update.json`.

---

## Code Examples

### Entrypoint Wrapper Script (Pattern A — in container)

```bash
#!/bin/bash
# scripts/entrypoint.sh
set -e

echo "Running migration (idempotent, safe to re-run)..."
cd /app
python scripts/migrate_sessions.py \
  --sessions-dir review_sessions/sessions \
  --pipeline-dir review_sessions/pipeline_results

echo "Migration complete. Starting server..."
exec uvicorn wafr.ag_ui.server:app \
  --host 0.0.0.0 \
  --port 8000 \
  --timeout-keep-alive 300 \
  --workers 1 \
  --log-level info
```

Dockerfile change:
```dockerfile
COPY scripts/ ./scripts/
RUN chmod +x scripts/entrypoint.sh
CMD ["scripts/entrypoint.sh"]
```

### Local Docker Run Migration (Pattern B — from operator machine)

```bash
docker run --rm \
  -e AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}" \
  -e AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}" \
  -e AWS_SESSION_TOKEN="${AWS_SESSION_TOKEN}" \
  -e AWS_DEFAULT_REGION=us-east-1 \
  -e REVIEW_STORAGE_TYPE=dynamodb \
  -e WAFR_DYNAMO_SESSIONS_TABLE=wafr-sessions \
  -e WAFR_DYNAMO_REVIEW_SESSIONS_TABLE=wafr-review-sessions \
  -e WAFR_DYNAMO_USERS_TABLE=wafr-users \
  -e WAFR_DYNAMO_AUDIT_TABLE=wafr-audit-log \
  -v "$(pwd)/wafr-agents:/app" \
  -w /app \
  842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-backend:latest \
  python scripts/migrate_sessions.py --dry-run
# Remove --dry-run for real run
```

### Describe Service Status Poll

```bash
while true; do
  STATUS=$(aws apprunner describe-service \
    --service-arn arn:aws:apprunner:us-east-1:842387632939:service/wafr-backend/aa3b1b32d7944f65b5aa1eb76c89357f \
    --query 'Service.Status' --output text --region us-east-1)
  echo "Backend: $STATUS"
  [ "$STATUS" = "RUNNING" ] && break
  sleep 15
done
```

### Verify Auth is Enforced (unauthenticated curl gets 401)

```bash
# Must return HTTP 401 — confirms AUTH_REQUIRED=true is active
curl -s -o /dev/null -w "%{http_code}" \
  https://i5kj2nnkxd.us-east-1.awsapprunner.com/sessions
# Expected: 401
```

---

## Key Infrastructure Facts (from codebase inspection)

| Item | Value | Source |
|------|-------|--------|
| AWS Account ID | 842387632939 | backend-update.json / frontend-update.json |
| ECR backend repo | `842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-backend:latest` | backend-update.json |
| ECR frontend repo | `842387632939.dkr.ecr.us-east-1.amazonaws.com/wafr-frontend:latest` | frontend-update.json |
| Backend App Runner ARN | `arn:aws:apprunner:us-east-1:842387632939:service/wafr-backend/aa3b1b32d7944f65b5aa1eb76c89357f` | backend-update.json |
| Frontend App Runner ARN | `arn:aws:apprunner:us-east-1:842387632939:service/wafr-frontend-app/0810ab0676de401e9a3ed4de81e6c03c` | frontend-update.json |
| Backend URL | `https://i5kj2nnkxd.us-east-1.awsapprunner.com` | CONTEXT.md |
| Frontend URL | `https://3fhp6mfj7u.us-east-1.awsapprunner.com` | CONTEXT.md |
| Cognito User Pool | `us-east-1_U4ugKPUrh` | CONTEXT.md |
| Cognito App Client | `65fis729feu3lr317rm6oaue5s` | CONTEXT.md |
| DynamoDB tables | `wafr-sessions`, `wafr-review-sessions`, `wafr-users`, `wafr-audit-log` | backend-update.json |
| Audit log PK | `user_id` (String) | audit.py line 17 |
| Audit log SK | `timestamp_session_id` (String, format: `<ISO_UTC>_<session_id>`) | audit.py line 73 |
| Sessions to migrate | 10 session files, 4 pipeline result files | filesystem inspection |
| backend WORKDIR | `/app` | wafr-agents/Dockerfile |
| Backend server module | `wafr.ag_ui.server:app` | wafr-agents/Dockerfile CMD |
| Auth enforcement | `AUTH_REQUIRED=true` already set on both services | backend-update.json, frontend-update.json |

---

## Open Questions

1. **Which migration pattern does the plan use — entrypoint wrapper (A) or local docker run (B)?**
   - What we know: Pattern A matches locked decision ("runs inside container"); Pattern B is simpler and avoids session files needing to be in the Docker image
   - What's unclear: Are the local session files intended to be included in the Docker build context? The current Dockerfile does NOT copy `review_sessions/sessions/*.json` files — it only creates the empty directory structure.
   - Recommendation: Use **Pattern B** (local docker run). The session files are local. Pattern A would require either (a) including session files in the Docker image (bad — they would be public in ECR) or (b) the sessions already being in the container from a prior deployment (they were — old containers had them). Since `AutoDeploymentsEnabled=false` and old containers had file sessions, those containers are no longer running after the new image deploys. The safest approach is to run migration locally before or in parallel with deploy.

2. **Does the backend Dockerfile need `scripts/` directory copied?**
   - What we know: Current Dockerfile does NOT `COPY scripts/ ./scripts/` — it only copies `wafr/`, `knowledge_base/`, `__init__.py`
   - What's unclear: If Pattern A is chosen, the scripts directory must be added to the Dockerfile COPY instructions
   - Recommendation: If Plan uses Pattern A, add `COPY scripts/ ./scripts/` to the Dockerfile before the migration entrypoint step

3. **Smoke test: how to get Cognito user's `sub` UUID for audit log query?**
   - What we know: Audit log PK is the `sub` claim from the JWT, not the username
   - What's unclear: Smoke test is manual/browser-based — the operator won't easily see the JWT sub
   - Recommendation: Use `aws dynamodb scan --table-name wafr-audit-log --select COUNT` to confirm entries exist without needing the sub. For deeper verification, use scan (no filter) to see all entries by timestamp.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `aws ecr get-login` (deprecated) | `aws ecr get-login-password \| docker login` | AWS CLI v2 | `get-login` removed in CLI v2 |
| `FORCE_CHANGE_PASSWORD` workaround via challenge flow | `admin-set-user-password --permanent` | Cognito API always had this; CLI v2 surfaced it clearly | Enables clean test user setup without browser interaction |
| App Runner auto-deploy | `start-deployment` for manual control | App Runner service creation option | `AutoDeploymentsEnabled=false` is already set — must trigger manually |

---

## Sources

### Primary (HIGH confidence)
- AWS official CLI docs — `aws apprunner start-deployment`, `update-service`, `describe-service` — verified via WebFetch to `docs.aws.amazon.com/apprunner/latest/dg/manage-deploy.html`
- AWS official CLI docs — `aws cognito-idp admin-create-user`, `admin-set-user-password`, `admin-add-user-to-group` — verified via WebFetch to `docs.aws.amazon.com/cli/latest/reference/cognito-idp/`
- AWS official ECR docs — `aws ecr get-login-password` flow — `docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html`
- Project source: `wafr-agents/scripts/migrate_sessions.py` — read directly, 369 lines, idempotent confirmed
- Project source: `wafr-agents/wafr/auth/audit.py` — read directly, DynamoDB key schema confirmed
- Project source: `wafr-agents/Dockerfile` — read directly, WORKDIR, CMD, COPY instructions confirmed
- Project source: `aws-frontend/Dockerfile` — read directly, build-arg pattern for NEXT_PUBLIC_* confirmed
- Project source: `backend-update.json`, `frontend-update.json` — read directly, ARNs, account ID, env vars confirmed

### Secondary (MEDIUM confidence)
- App Runner exec limitation — confirmed by multiple re:Post community posts + GitHub roadmap issue #251 (open, unresolved)
- Django + App Runner migration pattern — AWS blog "Deploy and scale Django applications on AWS App Runner" — entrypoint wrapper approach endorsed by AWS

### Tertiary (LOW confidence)
- App Runner deployment duration "2-5 minutes" — community estimate, no official SLA documented

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all tools are standard AWS CLI, Docker, already in use in project
- Architecture patterns: HIGH for ECR/Cognito/DynamoDB CLI patterns (official docs); MEDIUM for App Runner exec limitation (community-verified but not officially documented as permanent gap)
- Pitfalls: HIGH — most derived directly from code inspection of Dockerfile, audit.py, migrate_sessions.py

**Research date:** 2026-02-28
**Valid until:** 2026-03-28 (stable AWS CLI and Docker commands; App Runner exec limitation may be resolved if AWS ships the feature)
