# AI-Automated Amazon WAFR Workshop

An AI-powered platform that automates AWS Well-Architected Framework Reviews (WAFR) using multi-agent orchestration. Upload a workshop transcript, and the system extracts insights, maps them to WAFR pillars, scores your architecture, generates a PDF report, and populates a real AWS WA Tool workload — all in under 10 minutes.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Key Features](#key-features)
- [Multi-Agent Pipeline](#multi-agent-pipeline)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup & Installation](#setup--installation)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
- [Deployment](#deployment)
  - [Docker Build](#docker-build)
  - [AWS App Runner Deployment](#aws-app-runner-deployment)
- [AWS Infrastructure](#aws-infrastructure)
  - [DynamoDB Tables](#dynamodb-tables)
  - [Cognito Authentication](#cognito-authentication)
  - [IAM Configuration](#iam-configuration)
  - [S3 Storage](#s3-storage)
- [API Reference](#api-reference)
  - [Authentication](#authentication)
  - [Assessment Endpoints](#assessment-endpoints)
  - [Session Endpoints](#session-endpoints)
  - [Review Endpoints](#review-endpoints)
  - [Report Endpoints](#report-endpoints)
- [Frontend Pages](#frontend-pages)
- [Security](#security)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Architecture Overview

```
                          +---------------------------+
                          |    Next.js Frontend        |
                          |    (App Runner)            |
                          |  Cognito Authenticator     |
                          +------------+---------------+
                                       |
                                  HTTPS + JWT
                                       |
                          +------------v---------------+
                          |    FastAPI Backend          |
                          |    (App Runner)             |
                          |  JWT Middleware + CORS      |
                          |  Rate Limiting + Audit      |
                          +--+------+------+------+----+
                             |      |      |      |
              +--------------+   +--+--+  ++-+  +-+----------+
              |                  |     |  |   | |            |
        +-----v-----+    +------v-+ +-v---v+ +v---------+   |
        | DynamoDB   |    |Bedrock | | S3   | | AWS WA   |   |
        | 4 Tables   |    |Claude  | |Reports| | Tool API |   |
        +------------+    +--------+ +------+ +----------+   |
                                                              |
                                                    +---------v---+
                                                    | Cognito      |
                                                    | User Pool    |
                                                    +--------------+
```

**Two-service deployment:**
- **Frontend** — Next.js 16 with Amplify v6 Authenticator, deployed on AWS App Runner
- **Backend** — Python FastAPI with Strands multi-agent framework, deployed on AWS App Runner

---

## Key Features

### AI-Powered Assessment
- **Automated transcript analysis** — Upload a WAFR workshop transcript and get a complete assessment
- **Multi-lens support** — Well-Architected, Serverless, SaaS, and Migration lenses
- **Intelligent gap detection** — Identifies unanswered areas and synthesizes responses
- **Confidence scoring** — Evidence-based confidence levels for every answer
- **HRI validation** — Claude validates High-Risk Issues, filtering false positives (typically 40-60% reduction)

### AWS WA Tool Integration
- **Automatic workload creation** — Creates a real workload in AWS Well-Architected Tool
- **Batch question answering** — Populates answers across all pillars in parallel
- **Milestone creation** — Snapshots the assessment in AWS WA Tool
- **Official WAFR PDF report** — Generated and uploaded to S3 with presigned download URL

### Human Review Interface (HRI)
- **Review AI answers** — Approve, modify, or reject each AI-generated answer
- **Confidence-based sorting** — Low-confidence answers surfaced first for human attention
- **Per-pillar review** — Organized by WAFR pillars for structured review workflow
- **Persistent decisions** — All review actions saved to DynamoDB

### Real-Time Streaming
- **SSE (Server-Sent Events)** — Live progress updates as the pipeline runs
- **AG-UI Protocol** — Structured events: `STEP_STARTED`, `STATE_DELTA`, `TEXT_MESSAGE_CONTENT`, `RUN_FINISHED`
- **State snapshots** — Full state sync on connection with incremental deltas

### Enterprise Security
- **Cognito authentication** — SRP-only auth (no plaintext passwords over the wire)
- **JWT validation** — Every API endpoint protected with PyJWT + JWKS caching
- **RBAC** — WafrTeam (full access) and WafrClients (read-only) groups
- **Rate limiting** — Tiered slowapi limits per endpoint category
- **CORS lockdown** — Only the frontend domain is allowed
- **Audit trail** — Every authenticated request logged to DynamoDB with user, action, and timestamp

---

## Multi-Agent Pipeline

The backend orchestrates **11 specialized agents** in sequence:

```
Transcript Input
      |
      v
[1. Understanding Agent]     -- Extracts key insights from transcript
      |
      v
[2. Mapping Agent]           -- Maps insights to specific WAFR questions
      |
      v
[3. Confidence Agent]        -- Scores evidence quality per answer
      |
      v
[4. Gap Detection Agent]     -- Identifies unanswered WAFR questions
      |
      v
[5. Answer Synthesis Agent]  -- Generates answers for gaps using evidence
      |
      v
[6. Auto-Populate]           -- Fills remaining questions automatically
      |
      v
[7. Gap Prompts]             -- Creates targeted follow-up questions
      |
      v
[8. Scoring Agent]           -- Calculates pillar and overall scores
      |
      v
[9. Report Agent]            -- Generates PDF report (uploaded to S3)
      |
      v
[10. WA Tool Agent]          -- Creates AWS workload, fills answers, creates milestone
      |
      v
[11. HRI Validation]         -- Claude validates High-Risk Issues
      |
      v
   Complete (session saved to DynamoDB)
```

**AI Models Used:**
- **Claude 3.7 Sonnet** (`us.anthropic.claude-3-7-sonnet-20250219-v1:0`) — Primary reasoning, answer synthesis, HRI validation
- **Claude 3.5 Haiku** (`us.anthropic.claude-3-5-haiku-20241022-v1:0`) — Fast extraction, classification, scoring

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS, Radix UI, Recharts |
| **Auth (Frontend)** | AWS Amplify v6, `@aws-amplify/ui-react` Authenticator |
| **Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic |
| **AI Framework** | AWS Strands Agents SDK |
| **AI Models** | AWS Bedrock (Claude 3.7 Sonnet, Claude 3.5 Haiku) |
| **Database** | Amazon DynamoDB (4 tables, PAY_PER_REQUEST) |
| **Object Storage** | Amazon S3 (reports, overflow data, transcripts) |
| **Authentication** | Amazon Cognito User Pool (SRP auth) |
| **Deployment** | AWS App Runner (2 services) + Amazon ECR |
| **Security** | PyJWT, slowapi, CORS middleware, ASGI audit middleware |

---

## Project Structure

```
.
├── wafr-agents/                    # Backend (Python/FastAPI)
│   ├── Dockerfile                  # Production container image
│   ├── requirements.txt            # Python dependencies
│   ├── __init__.py
│   ├── scripts/
│   │   ├── entrypoint.sh           # Uvicorn startup script
│   │   └── migrate_sessions.py     # File-to-DynamoDB migration tool
│   ├── knowledge_base/
│   │   └── lenses/                 # WAFR lens definitions (JSON)
│   │       ├── wellarchitected.json
│   │       ├── serverless.json
│   │       └── softwareasaservice.json
│   ├── wafr/
│   │   ├── ag_ui/                  # AG-UI Protocol layer
│   │   │   ├── server.py           # FastAPI app — all 23+ endpoints
│   │   │   ├── emitter.py          # SSE event emitter
│   │   │   ├── events.py           # AG-UI event types
│   │   │   ├── state.py            # Pipeline state management
│   │   │   ├── middleware.py       # Logging middleware
│   │   │   ├── orchestrator_integration.py
│   │   │   └── review_messages_integration.py
│   │   ├── agents/                 # Multi-agent pipeline (32 files)
│   │   │   ├── orchestrator.py     # Main pipeline orchestrator
│   │   │   ├── understanding_agent.py
│   │   │   ├── mapping_agent.py
│   │   │   ├── confidence_agent.py
│   │   │   ├── gap_detection_agent.py
│   │   │   ├── answer_synthesis_agent.py
│   │   │   ├── scoring_agent.py
│   │   │   ├── report_agent.py
│   │   │   ├── wa_tool_agent.py    # AWS WA Tool integration
│   │   │   ├── wa_tool_client.py   # WA Tool API client
│   │   │   ├── review_orchestrator.py
│   │   │   ├── lens_manager.py     # Multi-lens support
│   │   │   ├── batch_optimizer.py  # Parallel batch processing
│   │   │   ├── cost_optimizer.py   # Token cost management
│   │   │   ├── model_config.py     # Bedrock model configuration
│   │   │   └── ...
│   │   ├── auth/                   # Security layer
│   │   │   ├── jwt_middleware.py   # JWT validation + RBAC
│   │   │   ├── audit.py           # DynamoDB audit trail
│   │   │   ├── cors.py            # CORS configuration
│   │   │   └── rate_limit.py      # Tiered rate limiting
│   │   ├── models/                 # Pydantic data models
│   │   │   ├── review_item.py
│   │   │   ├── synthesized_answer.py
│   │   │   └── validation_record.py
│   │   ├── storage/                # Persistence layer
│   │   │   └── review_storage.py   # DynamoDB + S3 storage
│   │   └── utils/                  # Utilities
│   │       ├── s3_storage.py       # S3 upload/download
│   │       ├── concurrency.py      # Async helpers
│   │       ├── error_handling.py
│   │       └── logging_config.py
│   ├── wafr-iam-policy.json        # IAM policy template
│   ├── apprunner-ecr-trust-policy.json
│   └── apprunner-instance-trust-policy.json
│
├── aws-frontend/                   # Frontend (Next.js/React)
│   ├── Dockerfile                  # Production container image
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── app/
│   │   ├── layout.tsx              # Root layout with AmplifyProvider
│   │   ├── page.tsx                # Dashboard — session list
│   │   ├── new-assessment/
│   │   │   └── page.tsx            # Transcript upload form
│   │   ├── progress/
│   │   │   └── [sessionId]/page.tsx  # Real-time pipeline progress
│   │   ├── results/
│   │   │   └── [sessionId]/page.tsx  # Assessment results + scores
│   │   ├── review/
│   │   │   └── [sessionId]/page.tsx  # Human review interface
│   │   └── reports/
│   │       └── [sessionId]/page.tsx  # PDF report download
│   ├── components/
│   │   ├── amplify-provider.tsx    # Cognito auth wrapper
│   │   ├── header.tsx              # Navigation header with sign-out
│   │   ├── pillar-card.tsx         # WAFR pillar score card
│   │   ├── insight-card.tsx        # Extracted insight display
│   │   ├── gap-card.tsx            # Gap analysis card
│   │   ├── review-item.tsx         # Review approve/reject UI
│   │   ├── stat-card.tsx           # Statistics display
│   │   ├── charts/                 # Recharts visualizations
│   │   │   ├── results-bar-chart.tsx
│   │   │   ├── results-radar-chart.tsx
│   │   │   ├── reports-benchmark-chart.tsx
│   │   │   └── reports-line-chart.tsx
│   │   └── ui/                     # Radix UI primitives (shadcn/ui)
│   └── lib/
│       ├── api.ts                  # API client with auth headers
│       ├── auth.ts                 # Cognito token management
│       ├── backend-api.ts          # Backend URL configuration
│       ├── sse-client.ts           # SSE stream consumer
│       ├── session-db.ts           # Session state management
│       ├── types.ts                # TypeScript type definitions
│       └── utils.ts                # Utility functions
│
├── .gitignore
└── README.md
```

---

## Prerequisites

- **AWS Account** with the following services enabled:
  - Amazon Bedrock (Claude models — request access in us-east-1)
  - Amazon DynamoDB
  - Amazon S3
  - Amazon Cognito
  - Amazon ECR
  - AWS App Runner
  - AWS Well-Architected Tool
- **AWS CLI v2** configured with appropriate credentials
- **Docker** for building container images
- **Node.js 20+** for frontend development
- **Python 3.11+** for backend development

---

## Setup & Installation

### Backend Setup

```bash
cd wafr-agents

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
pip install "uvicorn[standard]" "fastapi>=0.109.0"

# Run locally (without auth — for development)
AUTH_REQUIRED=false uvicorn wafr.ag_ui.server:app \
  --host 0.0.0.0 --port 8000 --reload
```

### Frontend Setup

```bash
cd aws-frontend

# Install dependencies
npm install

# Set environment variables
export NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
export NEXT_PUBLIC_COGNITO_USER_POOL_ID=your-pool-id
export NEXT_PUBLIC_COGNITO_CLIENT_ID=your-client-id

# Run locally
npm run dev
```

---

## Deployment

### Docker Build

**Backend:**
```bash
cd wafr-agents
docker build -t wafr-backend:latest .
```

**Frontend:**
```bash
cd aws-frontend
docker build \
  --build-arg NEXT_PUBLIC_BACKEND_URL=https://your-backend.awsapprunner.com \
  --build-arg NEXT_PUBLIC_COGNITO_USER_POOL_ID=us-east-1_XXXXXXX \
  --build-arg NEXT_PUBLIC_COGNITO_CLIENT_ID=your-client-id \
  -t wafr-frontend:latest .
```

> **Note:** `NEXT_PUBLIC_*` variables are baked at build time in Next.js. They must be passed as `--build-arg` during `docker build`, not as runtime environment variables.

### AWS App Runner Deployment

**1. Create ECR repositories:**
```bash
aws ecr create-repository --repository-name wafr-backend
aws ecr create-repository --repository-name wafr-frontend
```

**2. Push images to ECR:**
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1

aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Backend
docker tag wafr-backend:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/wafr-backend:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/wafr-backend:latest

# Frontend
docker tag wafr-frontend:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/wafr-frontend:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/wafr-frontend:latest
```

**3. Create App Runner services** via AWS Console or CLI with:
- Backend: Port 8000, 2 vCPU, 4GB RAM, instance role with DynamoDB/Cognito/S3/Bedrock/WATool permissions
- Frontend: Port 3000, 1 vCPU, 2GB RAM

**4. Backend environment variables** (set in App Runner):
```
AUTH_REQUIRED=true
REVIEW_STORAGE_TYPE=dynamodb
COGNITO_USER_POOL_ID=us-east-1_XXXXXXX
COGNITO_CLIENT_ID=your-client-id
CORS_ALLOWED_ORIGINS=https://your-frontend.awsapprunner.com
```

---

## AWS Infrastructure

### DynamoDB Tables

| Table | Partition Key | Sort Key | GSIs | Purpose |
|-------|--------------|----------|------|---------|
| `wafr-sessions` | `session_id` (S) | — | `status-updated_at-index` | Assessment session metadata |
| `wafr-review-sessions` | `session_id` (S) | `item_id` (S) | `status-index` | Review items (AI answers, human decisions) |
| `wafr-users` | `user_id` (S) | — | `username-index`, `email-index` | User profiles and preferences |
| `wafr-audit-log` | `audit_id` (S) | — | `user_id-timestamp-index`, `session_id-timestamp-index` | Security audit trail |

All tables use **PAY_PER_REQUEST** billing (scale to zero, no provisioned capacity).

### Cognito Authentication

- **User Pool:** SRP-only authentication (no `USER_PASSWORD_AUTH`)
- **App Client:** No client secret (public client for frontend)
- **Groups:**
  - `WafrTeam` — Full CRUD access to all assessments
  - `WafrClients` — Read-only access to their own assessments
- **Password Policy:** 12+ characters, uppercase, lowercase, numbers, symbols

### IAM Configuration

The App Runner instance role (`WafrAppRunnerInstanceRole`) requires:

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query",
    "dynamodb:Scan", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem"
  ],
  "Resource": "arn:aws:dynamodb:us-east-1:*:table/wafr-*"
}
```

Plus: `cognito-idp:*`, `s3:PutObject/GetObject`, `bedrock:InvokeModel`, `wellarchitected:*`, `secretsmanager:GetSecretValue`.

See `wafr-agents/wafr-iam-policy.json` for the full policy.

### S3 Storage

- **Bucket:** `wafr-agent-production-artifacts-{account-id}`
- **Reports:** `reports/{session-id}/wa_tool_official_report_{timestamp}.pdf`
- **Overflow:** `dynamo-overflow/pipeline_results/{session-id}.json` (items >400KB)
- **Transcripts:** `dynamo-overflow/transcripts/{session-id}.txt`

---

## API Reference

Base URL: `https://your-backend.awsapprunner.com`

### Authentication

All endpoints (except `/health`) require a Bearer token:
```
Authorization: Bearer <cognito-access-token>
```

### Assessment Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/wafr/run` | Start a new WAFR assessment (SSE stream) | WafrTeam |
| `POST` | `/api/wafr/upload-transcript` | Upload transcript file | WafrTeam |
| `GET` | `/health` | Health check | None |

**POST /api/wafr/run** — Start Assessment
```json
{
  "transcript": "Workshop transcript text...",
  "assessment_name": "My Assessment",
  "industry": "E-Commerce",
  "domain": "Retail",
  "user_context": {
    "compliance_requirements": ["SOC2", "PCI-DSS"],
    "business_priorities": ["reliability", "cost-optimization"]
  }
}
```

Returns an SSE stream with AG-UI events:
```
data: {"type": "RUN_STARTED", "runId": "..."}
data: {"type": "STEP_STARTED", "stepName": "understanding", ...}
data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "[understanding] Extracting insights..."}
data: {"type": "STATE_DELTA", "delta": [{"op": "replace", "path": "/pipeline/progress_percentage", "value": 25.0}]}
...
data: {"type": "RUN_FINISHED", ...}
```

### Session Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/wafr/sessions` | List all sessions | WafrTeam/WafrClients |
| `GET` | `/api/wafr/session/{id}/details` | Get session details | WafrTeam/WafrClients |
| `GET` | `/api/wafr/session/{id}/results` | Get pipeline results | WafrTeam/WafrClients |
| `DELETE` | `/api/wafr/session/{id}` | Delete session | WafrTeam only |

### Review Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/wafr/review/{id}/items` | Get review items | WafrTeam/WafrClients |
| `GET` | `/api/wafr/review/{id}/pillars` | Get items grouped by pillar | WafrTeam/WafrClients |
| `PUT` | `/api/wafr/review/{id}/item/{itemId}` | Update review decision | WafrTeam only |
| `POST` | `/api/wafr/review/{id}/bulk-approve` | Bulk approve items | WafrTeam only |

### Report Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/wafr/report/{id}` | Get report metadata | WafrTeam/WafrClients |
| `GET` | `/api/wafr/report/{id}/download` | Download PDF report | WafrTeam/WafrClients |

---

## Frontend Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Lists all assessment sessions with status, scores, dates |
| `/new-assessment` | New Assessment | Transcript upload form with industry/domain fields |
| `/progress/[sessionId]` | Progress | Real-time pipeline progress with step-by-step updates |
| `/results/[sessionId]` | Results | Pillar scores, radar chart, bar chart, insights, gaps |
| `/review/[sessionId]` | Review | Human review interface — approve/modify/reject per answer |
| `/reports/[sessionId]` | Reports | PDF report download, benchmark charts, trend analysis |

All pages are wrapped in the Amplify Authenticator — users must log in via Cognito before accessing any page.

---

## Security

### Authentication Flow
1. User enters credentials in Amplify Authenticator
2. Cognito SRP handshake (password never sent in plaintext)
3. Cognito returns `AccessToken`, `IdToken`, `RefreshToken`
4. Tokens stored in `sessionStorage` (cleared on tab close)
5. Every API request includes `Authorization: Bearer <AccessToken>`
6. Backend validates JWT signature using Cognito JWKS (cached)
7. Backend extracts user groups for RBAC decisions

### Security Layers
- **CORS:** Only the frontend domain is allowed (`Access-Control-Allow-Origin`)
- **Rate Limiting:** Tiered per endpoint — assessment runs: 5/min, reads: 30/min, auth: 10/min
- **Input Validation:** Pydantic models with 500K character transcript limit
- **Audit Trail:** Every authenticated request logged to `wafr-audit-log` DynamoDB table
- **RBAC:** `WafrTeam` = full CRUD, `WafrClients` = read-only (403 on write endpoints)

---

## Environment Variables

### Backend

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AUTH_REQUIRED` | No | `true` | Enable/disable JWT authentication |
| `REVIEW_STORAGE_TYPE` | No | `dynamodb` | Storage backend (`dynamodb` or `file`) |
| `COGNITO_USER_POOL_ID` | Yes* | — | Cognito User Pool ID |
| `COGNITO_CLIENT_ID` | Yes* | — | Cognito App Client ID |
| `CORS_ALLOWED_ORIGINS` | No | `*` | Comma-separated allowed origins |
| `AWS_REGION` | No | `us-east-1` | AWS region |

*Required when `AUTH_REQUIRED=true`

### Frontend (Build-time)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_BACKEND_URL` | Yes | Backend API base URL |
| `NEXT_PUBLIC_COGNITO_USER_POOL_ID` | Yes | Cognito User Pool ID |
| `NEXT_PUBLIC_COGNITO_CLIENT_ID` | Yes | Cognito App Client ID |

---

## Troubleshooting

### Common Issues

**"Incorrect username or password" on frontend login**
- Cognito requires 12+ character passwords with uppercase, lowercase, numbers, and symbols
- Usernames are case-sensitive
- Verify user status is `CONFIRMED` (not `FORCE_CHANGE_PASSWORD`)

**Backend returns 401 Unauthorized**
- Token may be expired (Cognito access tokens expire in 1 hour)
- Verify `COGNITO_USER_POOL_ID` and `COGNITO_CLIENT_ID` match between frontend and backend
- Check `AUTH_REQUIRED` is set correctly

**CRLF line ending errors in Docker**
- The Dockerfile includes a `dos2unix` guard: `RUN sed -i 's/\r$//' scripts/entrypoint.sh`
- If you edit shell scripts on Windows, ensure they use LF line endings

**DynamoDB audit writes failing silently**
- The audit middleware catches all exceptions and logs them as warnings
- Check CloudWatch logs for `Audit write failed` messages
- Common cause: empty string GSI key values (use `"no-session"` as placeholder)

**Pipeline timeout on large transcripts**
- Default App Runner request timeout is 120s, but SSE streams are long-lived
- Set `timeout-keep-alive=300` in Uvicorn config
- Transcripts are limited to 500K characters by Pydantic validation

---

## License

This project is proprietary. All rights reserved.
