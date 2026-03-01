# Milestones

## v1.0 DynamoDB, Auth & Security (Shipped: 2026-03-01)

**Phases completed:** 5 phases, 13 plans, 4 tasks

**Delivered:** Every WAFR assessment session is durably stored in DynamoDB, only accessible to authenticated Cognito users with role-based access, and the backend API is protected by JWT validation, CORS lockdown, rate limiting, and audit trail logging.

**Key accomplishments:**
1. Four DynamoDB tables (PAY_PER_REQUEST, GSIs, TTL, PITR) replacing ephemeral file storage
2. DynamoDBReviewStorage with S3 overflow for large items and idempotent migration script
3. Cognito User Pool with SRP-only auth, WafrTeam/WafrClients RBAC groups
4. PyJWT RS256 JWT middleware on all 23 FastAPI endpoints with Pydantic input validation
5. CORS lockdown, tiered slowapi rate limiting, and pure-ASGI audit trail middleware
6. Amplify v6 login gate with sessionStorage, Bearer token on all API/SSE requests, role-based UI
7. Full E2E smoke test: 10 sessions migrated, both roles verified, 12 audit entries, zero duplicates

**Stats:** 51 commits, 129 files changed, 33K Python LOC + 8K TypeScript LOC, 47 days

**Archives:** `milestones/v1.0-ROADMAP.md`, `milestones/v1.0-REQUIREMENTS.md`

---

