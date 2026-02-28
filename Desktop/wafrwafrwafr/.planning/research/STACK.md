# Technology Stack

**Project:** WAFR Assessment Platform — DynamoDB + Cognito + API Security Milestone
**Researched:** 2026-02-27
**Research Mode:** Stack dimension (ecosystem)

---

## Context

Existing stack being extended — not a greenfield project. The platform already runs:
- **Backend:** Python FastAPI (Strands agents, boto3, pydantic v2, uvicorn) on AWS App Runner
- **Frontend:** Next.js 16.1.6 + React 19 + Tailwind CSS 4 + Radix UI on AWS App Runner
- **Current auth:** None — all endpoints are open
- **Current storage:** File-based (`/review_sessions/`, `/tmp/reports/`) — lost on redeploy

This milestone adds DynamoDB persistence, Cognito auth, and API security hardening without changing the deployment architecture.

---

## Recommended Stack

### Backend — DynamoDB (Python)

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| `boto3` | `>=1.34.0` (latest: 1.42.58) | Sync DynamoDB operations — already in requirements.txt | HIGH |
| `aioboto3` | `15.5.0` | Async DynamoDB access for FastAPI async endpoints | HIGH |

**Use `boto3` Resource API for DynamoDB CRUD.** The Resource API (via `boto3.resource('dynamodb')`) handles Python-native type marshalling and batch writing automatically. AWS has stated they won't add new features to the Resource layer, but it remains fully supported and is the right choice for standard CRUD — not deprecated, just feature-frozen. Use the Client API only when you need newer DynamoDB features (TTL, Streams, PartiQL) not available via Resource.

**Use `aioboto3` for async endpoints.** The existing SSE streaming endpoints are async (`async def`). For those, use `aioboto3` as an async context manager. For background tasks and synchronous utility functions, use plain `boto3`.

**Do NOT use PynamoDB.** It lacks async support — critical for this FastAPI app. It also imposes an ORM abstraction that fights DynamoDB's access-pattern-first design.

### Backend — JWT / Auth (Python)

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| `PyJWT` | `2.11.0` | Decode and verify Cognito JWT tokens (RS256) | HIGH |
| `cryptography` | `>=42.0.0` | PyJWT dependency for RSA/RS256 support | HIGH |
| `httpx` | `>=0.27.0` | Async JWKS endpoint fetching (JWKS caching) | MEDIUM |

**Use PyJWT directly — do NOT use `fastapi-cognito` or `python-jose`.**

- `fastapi-cognito` depends on `cognitojwt`, which depends on `python-jose`, which depends on `ecdsa`. The `cognitojwt` repository was archived and is no longer maintained. This creates an unmaintained dependency in a security-critical code path.
- `python-jose` (v3.5.0) is still released but its dependency on the unmaintained `ecdsa` package is a liability for production auth code.
- `fastapi-cloudauth` is also an option but adds unnecessary abstraction since we only need Cognito.

**The correct pattern with PyJWT:**

```python
import jwt
from jwt import PyJWKClient

COGNITO_JWKS_URI = (
    f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
)
jwks_client = PyJWKClient(COGNITO_JWKS_URI, cache_keys=True)

def verify_token(token: str) -> dict:
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=CLIENT_ID,
        options={"verify_exp": True},
    )
```

`PyJWKClient` caches keys automatically — no manual JWKS caching needed. This is HIGH confidence: PyJWT 2.11.0 was verified on PyPI; AWS official docs confirm any reputable JWT library works; PyJWKClient is documented for this exact pattern.

### Backend — Rate Limiting

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| `slowapi` | `0.1.9` | Per-endpoint rate limiting (Starlette/FastAPI adapter of limits) | HIGH |
| `limits` | (slowapi dependency) | Rate limit storage backend | HIGH |

**Use `slowapi` with in-memory storage initially.** App Runner runs a single instance per service by default. In-memory storage (default) works correctly for single-instance deployments. If/when App Runner scales to multiple instances, add a Redis backend — but that's not needed for v1.

**Do NOT use API Gateway for rate limiting** — the PROJECT.md explicitly rules out migrating away from App Runner to API Gateway. Slowapi is the right layer to add rate limiting directly to the existing FastAPI app.

### Backend — Config Management

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| `pydantic-settings` | `2.13.1` | Type-safe environment variable config — Cognito pool IDs, table names, region | HIGH |

Already using `pydantic>=2.0.0`. `pydantic-settings` is the official companion package, directly supported by the FastAPI team. Use it to centralize all new config: Cognito User Pool ID, Client ID, AWS region, DynamoDB table names.

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    aws_region: str = "us-east-1"
    cognito_user_pool_id: str
    cognito_client_id: str
    dynamodb_sessions_table: str = "wafr-sessions"
    dynamodb_users_table: str = "wafr-users"
    dynamodb_audit_table: str = "wafr-audit"
    cors_allowed_origins: list[str] = []

    class Config:
        env_file = ".env"

settings = Settings()
```

### Backend — Security Middleware

| Middleware | Source | Purpose | Confidence |
|------------|--------|---------|------------|
| `CORSMiddleware` | `fastapi` (built-in via `starlette`) | Lock CORS to frontend domain only | HIGH |
| `TrustedHostMiddleware` | `starlette` (built-in) | Reject requests with unexpected Host headers | MEDIUM |
| FastAPI `Security` dependencies | `fastapi` (built-in) | Route-level auth via dependency injection | HIGH |

**No additional security libraries needed.** FastAPI's dependency injection system is the correct pattern for Cognito JWT validation — inject a `get_current_user` dependency that validates the Bearer token. This slots directly into the existing route structure without rewriting endpoints.

---

### Frontend — Cognito Authentication (Next.js)

| Library | Version | Purpose | Confidence |
|---------|---------|---------|------------|
| `aws-amplify` | `6.16.2` | Core Amplify JS v6 — Cognito auth operations (signIn, signOut, fetchAuthSession) | HIGH |
| `@aws-amplify/ui-react` | `6.x` | Pre-built Authenticator UI component (login/signup forms) | HIGH |
| `@aws-amplify/adapter-nextjs` | `1.x` | Server-side Amplify config for App Router — cookie-based token storage | HIGH |

**Use Amplify JS v6 configured against an existing Cognito User Pool — NOT Amplify Gen2 backend.** The project's Cognito resources are created via the AWS Console / IAM; Amplify Gen2 wants to own and deploy the Cognito backend itself. This is explicitly the wrong approach for this project. Instead:

```typescript
// lib/amplify-config.ts
import { Amplify } from 'aws-amplify';

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
      userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID!,
      loginWith: { email: true },
    },
  },
}, { ssr: true });
```

**Why Amplify v6 and not NextAuth/Auth.js?**
- NextAuth with Cognito requires the Cognito Hosted UI or a complex custom provider setup
- Amplify v6 ships `@aws-amplify/adapter-nextjs` with `runWithAmplifyServerContext` for App Router server components — this is the only library with first-class Next.js App Router + Cognito cookie-token support
- `@aws-amplify/ui-react` provides a production-ready `<Authenticator>` component that handles sign-in, sign-up, MFA, password reset out of the box

**Token storage:** Amplify v6 with `ssr: true` stores tokens in HTTP-only cookies (not localStorage). This is the correct pattern for Next.js App Router because Server Components cannot access localStorage. Tokens flow client → cookie → server components automatically.

**The existing `next: 16.1.6` is within Amplify v6's supported range** (`>=13.5.0 <16.0.0` — confirm: Next.js 16 was released after training data cutoff, verify Amplify compatibility before implementation).

**LOW confidence note:** Amplify v6's exact Next.js 16 compatibility should be verified at implementation time. The documented supported range mentions up to Next.js 15 in most sources found. If Amplify v6 doesn't support Next 16, the alternative is a custom Cognito integration using the Cognito Identity JS SDK (`amazon-cognito-identity-js`) directly.

---

## DynamoDB Table Design Decision

**Use multi-table design** for this project. Single-table design is optimal when access patterns are fully known and stable. At this milestone, the data model is new (sessions, users, audit trails, review decisions) and will evolve. Multi-table gives:

- Clearer IAM permission scoping per table
- Easier debugging (no composite key decoding)
- Simpler migration from file-based storage
- No risk of hot partition from mixed access patterns

**Recommended tables:**

| Table | Partition Key | Sort Key | Purpose |
|-------|--------------|----------|---------|
| `wafr-sessions` | `session_id` (S) | `created_at` (S) | Assessment sessions and pipeline results |
| `wafr-users` | `user_id` (S) | — | User profiles, roles (team/client) |
| `wafr-audit` | `user_id` (S) | `timestamp#session_id` (S) | Audit trail — who ran what, when |
| `wafr-review-decisions` | `session_id` (S) | `item_id` (S) | HRI review decisions per session |

**Capacity mode: Pay-per-request (on-demand).** App Runner scales to zero when idle; on-demand DynamoDB matches that cost profile exactly. Provisioned capacity makes sense at predictable high throughput — this platform is not there yet.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| JWT library | `PyJWT 2.11.0` | `python-jose 3.5.0` | Depends on archived `cognitojwt` + unmaintained `ecdsa` — unsafe for auth code |
| JWT library | `PyJWT 2.11.0` | `fastapi-cognito 2.9.0` | Thin wrapper over python-jose with the same bad dependency chain; `cognitojwt` is archived |
| Async DynamoDB | `aioboto3 15.5.0` | `aiodynamo` | Less adoption, more risk for primary DB access |
| DynamoDB ORM | `boto3` direct | `PynamoDB` | No async support — FastAPI endpoints are async |
| Rate limiting | `slowapi 0.1.9` | AWS WAF | WAF requires moving to CloudFront/API Gateway; violates App Runner constraint |
| Rate limiting | `slowapi 0.1.9` | Redis + custom | Over-engineering for single-instance App Runner v1 |
| Frontend auth | `aws-amplify v6` | `NextAuth/Auth.js` | No first-class App Router + Cognito cookie-token flow; requires Hosted UI |
| Frontend auth | `aws-amplify v6` | `amazon-cognito-identity-js` | More boilerplate; Amplify v6 is a thin wrapper over it anyway |
| DB design | Multi-table | Single-table | Access patterns not yet stable; single-table optimization is premature |

---

## Installation

### Backend (Python)

```bash
# Add to wafr-agents/requirements.txt

# DynamoDB async access
aioboto3==15.5.0

# Cognito JWT verification
PyJWT[crypto]==2.11.0   # [crypto] installs cryptography package for RS256

# Rate limiting
slowapi==0.1.9

# Config management
pydantic-settings==2.13.1
```

**Note:** `boto3>=1.34.0` is already in requirements.txt. `pydantic>=2.0.0` is already there. No version conflicts expected.

### Frontend (Node.js)

```bash
# Install Amplify v6 with Next.js adapter and UI components
npm install aws-amplify @aws-amplify/adapter-nextjs @aws-amplify/ui-react

# Expected versions:
# aws-amplify: ^6.16.2
# @aws-amplify/ui-react: ^6.x
# @aws-amplify/adapter-nextjs: ^1.x
```

---

## Environment Variables Required

### Backend (App Runner environment / `.env`)

```bash
# AWS region (already set via IAM role, but explicit config useful)
AWS_REGION=us-east-1

# Cognito
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx

# DynamoDB table names
DYNAMODB_SESSIONS_TABLE=wafr-sessions
DYNAMODB_USERS_TABLE=wafr-users
DYNAMODB_AUDIT_TABLE=wafr-audit
DYNAMODB_REVIEW_TABLE=wafr-review-decisions

# CORS
CORS_ALLOWED_ORIGINS=https://3fhp6mfj7u.us-east-1.awsapprunner.com
```

### Frontend (App Runner environment / `.env.local`)

```bash
NEXT_PUBLIC_COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
NEXT_PUBLIC_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
NEXT_PUBLIC_BACKEND_URL=https://i5kj2nnkxd.us-east-1.awsapprunner.com  # already exists
```

---

## IAM Permissions Required

The existing `WafrAppRunnerInstanceRole` needs these additional policies:

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "dynamodb:BatchWriteItem",
    "dynamodb:BatchGetItem",
    "dynamodb:DescribeTable"
  ],
  "Resource": [
    "arn:aws:dynamodb:us-east-1:842387632939:table/wafr-*"
  ]
}
```

No Cognito permissions needed on the backend role — JWT verification fetches JWKS from a public endpoint (`cognito-idp.us-east-1.amazonaws.com`) using HTTP, not AWS API calls.

---

## Sources

| Source | Confidence | Used For |
|--------|------------|---------|
| [boto3 official docs — DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/programming-with-python.html) | HIGH | boto3 Resource vs Client guidance |
| [boto3 PyPI — v1.42.58](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/dynamodb.html) | HIGH | Version confirmation |
| [aioboto3 GitHub — v15.5.0](https://github.com/terricain/aioboto3) | HIGH | Async DynamoDB wrapper, version |
| [PyJWT docs — v2.11.0 PyJWKClient](https://pyjwt.readthedocs.io/en/latest/usage.html) | HIGH | JWKS-based token verification pattern |
| [AWS Cognito JWT verification docs](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) | HIGH | Cognito JWT validation requirements (RS256, JWKS endpoint) |
| [fastapi-cognito GitHub — archived dep chain](https://github.com/markomirosavljev/fastapi-cognito/issues/19) | HIGH | Why NOT to use fastapi-cognito |
| [slowapi GitHub + PyPI — v0.1.9](https://github.com/laurentS/slowapi) | HIGH | Rate limiting library, version |
| [pydantic-settings PyPI — v2.13.1](https://pypi.org/project/pydantic-settings/) | HIGH | Config management version |
| [aws-amplify npm — v6.16.2](https://www.npmjs.com/package/aws-amplify) | HIGH | Frontend auth library version |
| [Amplify adapter-nextjs docs](https://docs.amplify.aws/javascript/build-a-backend/server-side-rendering/nextjs-app-router-server-components/) | HIGH | App Router + cookie token storage pattern |
| [Amplify "use existing Cognito" docs](https://docs.amplify.aws/nextjs/build-a-backend/auth/use-existing-cognito-resources/) | HIGH | How to configure Amplify without Amplify backend |
| [AWS blog — Single-table vs multi-table DynamoDB](https://aws.amazon.com/blogs/database/single-table-vs-multi-table-design-in-amazon-dynamodb/) | HIGH | DynamoDB design decision rationale |
| [DynamoDB on-demand pricing](https://aws.amazon.com/blogs/aws/amazon-dynamodb-on-demand-no-capacity-planning-and-pay-per-request-pricing/) | HIGH | Capacity mode recommendation |

---

## Open Validation Items

These must be verified at implementation time before writing code:

1. **Amplify v6 + Next.js 16 compatibility** — Amplify docs cite Next.js `>=13.5.0 <16.0.0`. The project uses Next.js 16.1.6. Confirm on [Amplify releases](https://github.com/aws-amplify/amplify-js/releases) whether v6 supports Next 16. If not, use `amazon-cognito-identity-js` directly.

2. **App Runner environment variable injection** — Confirm that `NEXT_PUBLIC_*` env vars are available at build time vs runtime in App Runner. App Runner injects env vars at runtime; Next.js `NEXT_PUBLIC_*` vars are baked in at build time. May need to use a config endpoint pattern instead.

3. **aioboto3 + boto3 version pinning** — `aioboto3==15.5.0` requires a specific `aiobotocore` version which in turn requires a specific `botocore` version. Ensure these don't conflict with the existing `boto3>=1.34.0` pin. Run `pip install aioboto3==15.5.0` in isolation to check resolution.

4. **JWKS caching in App Runner** — PyJWKClient caches keys in memory by default. If App Runner restarts the container, the cache is cold and the first request fetches from Cognito's endpoint. This is fine functionally but adds ~200ms latency on the first post-restart request. Acceptable for v1.
