"""
JWT authentication middleware for WAFR FastAPI backend.

Provides FastAPI dependency-injection based JWT validation against AWS Cognito.
Uses PyJWT with PyJWKClient for RS256 token verification and JWKS caching.

Usage:
    # Protect a route (any authenticated user):
    @app.get("/api/wafr/sessions", dependencies=[Depends(verify_token)])
    async def list_sessions(): ...

    # Protect a route (WafrTeam members only):
    @app.post("/api/wafr/run")
    async def run_assessment(claims: dict = Depends(require_team_role)): ...

Environment Variables:
    WAFR_COGNITO_USER_POOL_ID  - Cognito User Pool ID (e.g. us-east-1_U4ugKPUrh)
    WAFR_COGNITO_CLIENT_ID     - App Client ID for audience validation
    AUTH_REQUIRED              - Set to "false" to bypass JWT validation for local dev
                                 Defaults to "true" (secure by default)
"""

import os
import logging
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# =============================================================================
# Bearer scheme — auto_error=False so absent header returns None (not 403)
# See: Research Pitfall 1 — HTTPBearer returns 403 instead of 401 by default
# =============================================================================

_bearer = HTTPBearer(auto_error=False)

# =============================================================================
# Lazy-initialized JWKS client singleton
# See: Research Pitfall 4 — PyJWKClient instantiated before env vars available
# =============================================================================

_jwks_client: "jwt.PyJWKClient | None" = None


def _get_jwks_client() -> "jwt.PyJWKClient":
    """
    Return the module-level PyJWKClient singleton, creating it on first call.

    Lazy initialization prevents KeyError at import time when
    WAFR_COGNITO_USER_POOL_ID is not yet in the environment.
    PyJWKClient caches JWKS internally and re-fetches on unknown kid.
    """
    global _jwks_client
    if _jwks_client is None:
        pool_id = os.environ["WAFR_COGNITO_USER_POOL_ID"]
        jwks_url = (
            f"https://cognito-idp.us-east-1.amazonaws.com"
            f"/{pool_id}/.well-known/jwks.json"
        )
        _jwks_client = jwt.PyJWKClient(jwks_url)
        logger.info("PyJWKClient initialized for pool: %s", pool_id)
    return _jwks_client


# =============================================================================
# verify_token — primary FastAPI dependency
# =============================================================================

async def verify_token(
    request: Request,
    credentials: "HTTPAuthorizationCredentials | None" = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency that validates a Cognito JWT access token.

    - If AUTH_REQUIRED env var is not "true" (case-insensitive), returns
      synthetic dev claims without hitting Cognito — safe for local dev.
    - If credentials is None (no Authorization header), raises HTTP 401.
    - On any decode / validation failure, raises HTTP 401 with a generic
      message — never leaks validation details (expired vs wrong issuer etc.)
    - Stores decoded claims in request.state.claims for audit middleware.

    Returns:
        dict: Decoded JWT claims dict (sub, cognito:groups, token_use, etc.)

    Raises:
        HTTPException(401): Missing, malformed, or invalid token.
    """
    auth_required = os.getenv("AUTH_REQUIRED", "true").strip().lower() == "true"

    if not auth_required:
        # Local dev bypass — return synthetic claims
        synthetic = {"sub": "dev-user", "cognito:groups": ["WafrTeam"]}
        request.state.claims = synthetic
        return synthetic

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authentication token",
        )

    token = credentials.credentials
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)

        pool_id = os.environ["WAFR_COGNITO_USER_POOL_ID"]
        app_client_id = os.environ["WAFR_COGNITO_CLIENT_ID"]
        issuer = f"https://cognito-idp.us-east-1.amazonaws.com/{pool_id}"

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={
                "verify_exp": True,
                "verify_iss": True,
                "verify_signature": True,
                "require": ["exp", "iss", "sub", "token_use"],
            },
        )

        # Cognito access tokens use client_id claim, NOT aud
        # See: Research Pitfall 3 — access token vs id token audience claim
        if claims.get("token_use") != "access":
            raise ValueError("token_use must be 'access'")
        if claims.get("client_id") != app_client_id:
            raise ValueError("client_id mismatch")

        # Store claims for audit middleware (Plan 03)
        request.state.claims = claims
        return claims

    except Exception:
        # Never leak validation failure details — always return generic message
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authentication token",
        )


# =============================================================================
# require_team_role — sub-dependency for write/admin endpoints
# =============================================================================

def require_team_role(claims: dict = Depends(verify_token)) -> dict:
    """
    FastAPI sub-dependency that enforces WafrTeam group membership.

    Called after verify_token; claims dict is already validated.
    Raises HTTP 403 if the user is not in the WafrTeam Cognito group.

    Returns:
        dict: Same claims dict passed through from verify_token.

    Raises:
        HTTPException(403): User authenticated but lacks WafrTeam role.
    """
    groups: list = claims.get("cognito:groups", [])
    if "WafrTeam" not in groups:
        raise HTTPException(
            status_code=403,
            detail="Requires WafrTeam role",
        )
    return claims
