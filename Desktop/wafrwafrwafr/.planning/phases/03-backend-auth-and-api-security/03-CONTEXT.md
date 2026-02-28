# Phase 3: Backend Auth and API Security - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Add JWT authentication middleware, CORS lockdown, rate limiting, input validation, and audit trail to the FastAPI backend. Every endpoint is protected by Cognito JWT tokens. No frontend changes — Phase 4 handles the login UI.

</domain>

<decisions>
## Implementation Decisions

### JWT Auth Behavior
- Exempt endpoints: Health check (/health, /api/health) AND /docs (OpenAPI Swagger UI) are public — everything else requires valid Cognito token
- Error response: Standard 401 with JSON body `{"detail": "Missing or invalid authentication token"}` — no token details leaked
- Auth control: AUTH_REQUIRED env var only — no separate DEV_AUTH_BYPASS flag. Set to false for local dev.
- Role extraction: Middleware extracts Cognito group (WafrTeam/WafrClients) into request state. Individual endpoints check role where needed.

### CORS Policy
- Allowed origins: Frontend App Runner domain (https://3fhp6mfj7u.us-east-1.awsapprunner.com) AND http://localhost:3000
- SSE endpoints: More permissive CORS than standard endpoints (allow additional origins for potential embedding)
- Configuration: WAFR_CORS_ORIGINS env var with comma-separated origins — configurable without redeployment
- Preflight cache: Claude's discretion (pick a reasonable Access-Control-Max-Age)

### Rate Limiting Rules
- Rate limit scope: Claude's discretion (per-IP vs per-user vs hybrid)
- Endpoint tiers: Claude's discretion (design tiers based on endpoint cost — 10/min for POST /run per roadmap spec)
- Rate limit response: 429 Too Many Requests with Retry-After header
- SSE endpoints: No rate limiting on SSE streaming connections (long-lived, initial POST /run already limited)

### Audit Trail Scope
- Scope: Log ALL authenticated API calls, not just key actions
- Failed auth: Log failed authentication attempts with IP and timestamp
- Data per entry: Standard fields (user_id, session_id, action_type, timestamp, IP, HTTP method+path) PLUS full request body
- Write mode: Async fire-and-forget — don't block API response. If log write fails, request still succeeds.
- Storage: wafr-audit-log DynamoDB table (created in Phase 1, no TTL — keep forever)

### Claude's Discretion
- CORS preflight cache duration
- Rate limit scope (per-IP vs per-user)
- Rate limit tier design per endpoint
- Input validation rules beyond transcript size (500K char limit per roadmap)

</decisions>

<specifics>
## Specific Ideas

- Cognito User Pool ID: us-east-1_U4ugKPUrh (in Secrets Manager as wafr-cognito-user-pool-id)
- Cognito App Client ID: 65fis729feu3lr317rm6oaue5s (in Secrets Manager as wafr-cognito-client-id)
- JWKS URL: https://cognito-idp.us-east-1.amazonaws.com/us-east-1_U4ugKPUrh/.well-known/jwks.json
- Backend server: wafr-agents/wafr/ag_ui/server.py (~2400 lines)
- AUTH_REQUIRED=true already set on App Runner (from Phase 1)
- Frontend App Runner: https://3fhp6mfj7u.us-east-1.awsapprunner.com
- Backend App Runner: https://i5kj2nnkxd.us-east-1.awsapprunner.com
- Research recommended PyJWT over python-jose for JWT validation
- Research recommended slowapi for rate limiting

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-backend-auth-and-api-security*
*Context gathered: 2026-02-28*
