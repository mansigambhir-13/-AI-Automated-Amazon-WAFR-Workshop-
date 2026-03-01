# WAFR Assessment Platform

## What This Is

A multi-agent AWS Well-Architected Framework Review (WAFR) platform that processes workshop transcripts through an AI pipeline (understanding, mapping, scoring, report generation) and creates AWS WA Tool workloads. The platform has a Next.js frontend and Python/FastAPI backend on App Runner, with Cognito authentication, DynamoDB storage, and full API security hardening.

## Core Value

Every WAFR assessment session is durably stored, only accessible to authorized users, and the backend API is protected from unauthorized access and abuse.

## Current State (v1.0 shipped 2026-03-01)

### Architecture
- **Frontend**: Next.js 16 + Tailwind + Radix UI + Amplify v6, deployed on App Runner (`3fhp6mfj7u.us-east-1.awsapprunner.com`)
- **Backend**: Python FastAPI with Strands agents, deployed on App Runner (`i5kj2nnkxd.us-east-1.awsapprunner.com`)
- **Storage**: DynamoDB (4 tables: wafr-sessions, wafr-review-sessions, wafr-users, wafr-audit-log) + S3 overflow
- **Auth**: AWS Cognito User Pool (us-east-1_U4ugKPUrh) with SRP-only auth, WafrTeam/WafrClients RBAC
- **AI**: AWS Bedrock (Claude 3.7 Sonnet, Claude 3.5 Haiku) via inference profiles
- **Security**: JWT middleware on 23 endpoints, CORS lockdown, slowapi rate limiting, ASGI audit trail
- **AWS Account**: 842387632939, region us-east-1
- **IAM Role**: `WafrAppRunnerInstanceRole` — DynamoDB, Cognito, SecretsManager, S3

### Codebase
- Backend: 33K Python LOC (`wafr-agents/`)
- Frontend: 8K TypeScript LOC (`aws-frontend/`)
- Key backend files: `wafr/ag_ui/server.py`, `wafr/storage/review_storage.py`, `wafr/auth/jwt_middleware.py`, `wafr/auth/audit.py`
- Key frontend files: `lib/auth.ts`, `lib/api.ts`, `components/amplify-provider.tsx`, `components/header.tsx`

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
- ✓ STOR-01: DynamoDB sessions survive container restarts — v1.0
- ✓ STOR-02: Pipeline results with S3 offload for >400KB items — v1.0
- ✓ STOR-03: Human review decisions persisted in DynamoDB — v1.0
- ✓ STOR-04: User profiles with roles in DynamoDB — v1.0
- ✓ AUTH-01: Cognito User Pool with WafrTeam/WafrClients groups — v1.0
- ✓ AUTH-02: Backend JWT validation on all endpoints — v1.0
- ✓ AUTH-03: Frontend login/password-reset via Amplify Authenticator — v1.0
- ✓ AUTH-04: Team=full access, Client=read-only on own assessments — v1.0
- ✓ SECR-01: CORS locked to frontend domain — v1.0
- ✓ SECR-02: Tiered slowapi rate limiting — v1.0
- ✓ SECR-03: Pydantic validation with 500K char transcript limit — v1.0
- ✓ SECR-04: Audit trail in DynamoDB for all authenticated requests — v1.0
- ✓ OPER-01: File-to-DynamoDB migration (idempotent) — v1.0
- ✓ OPER-02: AUTH_REQUIRED env flag for gradual rollout — v1.0
- ✓ OPER-03: IAM policy with DynamoDB + Cognito + SecretsManager — v1.0

### Active

(No active requirements — v1.0 complete, next milestone not started)

### Out of Scope

- OAuth providers (Google, GitHub) — Cognito native auth is sufficient for v1
- MFA enforcement — deferred to v2
- HttpOnly cookie token storage — sessionStorage meets current needs
- Distributed rate limiting (Redis) — single-instance slowapi is sufficient
- WAF integration — App Runner provides basic protection
- API versioning — single version deployed
- Mobile app — web-first approach

## Constraints

- **Tech stack**: AWS services (DynamoDB, Cognito, S3, App Runner, Bedrock)
- **Deployment**: App Runner on both services — no Lambda/API Gateway
- **Backend**: FastAPI (Python) with JWT middleware
- **Frontend**: Next.js (React) with Amplify v6
- **Region**: us-east-1 — all services same region
- **IAM**: Single role `WafrAppRunnerInstanceRole`

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| AWS Cognito over custom auth | Managed service, native AWS, handles tokens/MFA | ✓ Good — SRP auth works, Amplify v6 compatible |
| DynamoDB over RDS | Serverless, pay-per-request, schema-flexible | ✓ Good — PAY_PER_REQUEST matches scale-to-zero |
| JWT middleware over API Gateway | Keeps App Runner deployment, no architecture change | ✓ Good — PyJWT 2.11.0 with JWKS caching |
| File-to-DynamoDB migration | Data continuity, no lost assessments | ✓ Good — idempotent, 14 items migrated |
| Role-based access (team/client) | Team=full CRUD, clients=read-only | ✓ Good — 403 on write endpoints for clients |
| SRP-only auth (no password auth) | Prevents plaintext password transmission | ✓ Good — security best practice |
| sessionStorage (not localStorage) | Tab close = logout, session-only persistence | ✓ Good — matches security requirements |
| Pure-ASGI audit middleware | Avoids BaseHTTPMiddleware context issues | ⚠️ Revisit — empty string GSI key bug found, fixed |
| Pattern B migration (local docker run) | Prevents customer data leakage to ECR | ✓ Good — security-first approach |
| dos2unix guard in Dockerfile | Prevents Windows CRLF deployment failures | ✓ Good — caught real issue |

---
*Last updated: 2026-03-01 after v1.0 milestone*
