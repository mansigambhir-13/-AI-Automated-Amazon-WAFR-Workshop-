# WAFR Assessment Platform — DynamoDB, Auth & Security Milestone

## What This Is

A multi-agent AWS Well-Architected Framework Review (WAFR) platform that processes workshop transcripts through an AI pipeline (understanding → mapping → scoring → report generation) and creates AWS WA Tool workloads. The platform has a Next.js frontend deployed on App Runner and a Python/FastAPI backend on App Runner, both publicly accessible with no authentication.

This milestone adds persistent DynamoDB storage, AWS Cognito authentication (internal team + external clients), and full API security hardening.

## Core Value

Every WAFR assessment session is durably stored, only accessible to authorized users, and the backend API is protected from unauthorized access and abuse.

## Requirements

### Validated

- ✓ Multi-agent WAFR pipeline (understanding, mapping, confidence, gap detection, answer synthesis, scoring, report) — existing
- ✓ SSE streaming for real-time progress — existing
- ✓ AWS WA Tool integration (create workloads, populate answers) — existing
- ✓ Next.js frontend with assessment dashboard, progress, results, review pages — existing
- ✓ FastAPI backend with AG-UI protocol — existing
- ✓ App Runner deployment (frontend + backend) — existing
- ✓ Human Review Interface (HRI) for approving/rejecting AI answers — existing
- ✓ PDF report generation with S3 storage — existing

### Active

- [ ] DynamoDB tables for sessions, results, users, audit trail, review decisions
- [ ] AWS Cognito user pools with internal team and client roles
- [ ] Frontend login/signup flow with Cognito
- [ ] Backend API authentication via Cognito JWT tokens
- [ ] Rate limiting on all API endpoints
- [ ] CORS lockdown to frontend domain only
- [ ] Input validation on all API inputs (transcript size, parameters)
- [ ] HTTPS enforcement
- [ ] Migration of existing file-based sessions to DynamoDB
- [ ] Audit trail logging (who ran what assessment, when)
- [ ] Role-based access (team creates assessments, clients view their own)

### Out of Scope

- OAuth providers (Google, GitHub) — Cognito handles auth natively, defer third-party OAuth to v2
- Multi-tenancy with billing — not needed for current user base
- Custom domain / SSL certificates — App Runner provides HTTPS by default
- Real-time collaboration — assessments are single-user workflows
- Frontend SSR auth (middleware-level) — API-level auth is sufficient for v1

## Context

### Current Architecture
- **Frontend**: Next.js 16 + Tailwind + Radix UI, deployed on App Runner (`3fhp6mfj7u.us-east-1.awsapprunner.com`)
- **Backend**: Python FastAPI with Strands agents, deployed on App Runner (`i5kj2nnkxd.us-east-1.awsapprunner.com`)
- **Storage**: File-based (`/review_sessions/pipeline_results/`, `/review_sessions/sessions/`, `/tmp/reports/`)
- **AI**: AWS Bedrock (Claude 3.7 Sonnet, Claude 3.5 Haiku) via inference profiles
- **AWS Account**: 842387632939, region us-east-1
- **IAM Role**: `WafrAppRunnerInstanceRole` — needs DynamoDB and Cognito permissions added

### Known Issues
- Backend currently has NO authentication — anyone with the URL has full access
- Session data is stored in local files — lost on container restart/redeploy
- DynamoDB save already attempted in code but fails (`No module named 'deployment'`)
- No rate limiting or input validation
- CORS is permissive (allows all origins)
- Scoring agent had hardcoded default scores (fixed in latest deployment)

### Existing Codebase Key Files
- Backend server: `wafr-agents/wafr/ag_ui/server.py` (~2400 lines)
- Orchestrator: `wafr-agents/wafr/agents/orchestrator.py`
- Review storage: `wafr-agents/wafr/storage/review_storage.py`
- Frontend API layer: `aws-frontend/lib/backend-api.ts`
- Frontend SSE client: `aws-frontend/lib/sse-client.ts`
- Frontend env: `aws-frontend/.env.local` (NEXT_PUBLIC_BACKEND_URL)

## Constraints

- **Tech stack**: Must use AWS services (DynamoDB, Cognito) — already on AWS, no external dependencies
- **Deployment**: App Runner on both services — no Lambda/API Gateway migration
- **Backend framework**: FastAPI (Python) — Cognito JWT validation middleware
- **Frontend framework**: Next.js (React) — Amplify UI or custom Cognito integration
- **Region**: us-east-1 — all services must be in same region
- **IAM**: Single role `WafrAppRunnerInstanceRole` — add permissions incrementally
- **Backwards compatibility**: Existing API endpoints must not break — add auth as middleware layer

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| AWS Cognito over custom auth | Managed service, native AWS integration, handles user pools, tokens, MFA | — Pending |
| DynamoDB over RDS | Serverless, pay-per-request, schema-flexible for varying assessment data shapes | — Pending |
| JWT middleware over API Gateway | Keeps current App Runner deployment, no architecture change needed | — Pending |
| Migrate existing data | Ensures data continuity, no lost assessments post-migration | — Pending |
| Role-based access (team/client) | Internal team needs full CRUD, clients need read-only on their assessments | — Pending |

---
*Last updated: 2026-02-27 after initialization*
