"""
Rate limiting configuration for the WAFR AG-UI server using slowapi.

Tier Design:
- expensive: 10/minute  — POST /api/wafr/run (AI pipeline trigger)
                        — POST /api/wafr/process-file (file pipeline trigger)
                        — POST /start (async job trigger)
- standard:  60/minute  — All other POST/DELETE endpoints
- read:     200/minute  — All GET endpoints (covered by default_limits)
- excluded:  no limit   — SSE streaming connections (long-lived; initial POST
                          already limited), WebSocket connections

Rate limit scope:
Hybrid per-user/per-IP — uses JWT sub claim when a Bearer token is present
(falls back to request IP for unauthenticated surface). This handles the
common enterprise case where many users share a NAT gateway: each user gets
their own bucket instead of competing for a shared IP bucket.

Implementation note:
The JWT is decoded WITHOUT signature verification solely to extract the sub
claim for the rate limit key. The actual security validation is handled by
the verify_token FastAPI dependency. Any decode failure (expired, malformed,
missing) silently falls back to IP-based keying.

Re-exported for server.py convenience:
- limiter          — Limiter singleton; attach to app.state and decorators
- RateLimitExceeded — exception class for the exception handler
- _rate_limit_exceeded_handler — built-in 429 handler with Retry-After header
- SlowAPIMiddleware — ASGI middleware; registers before CORSMiddleware
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from fastapi import Request


def _get_rate_limit_key(request: Request) -> str:
    """
    Hybrid rate limit key function.

    Returns "user:{sub}" when the request carries a valid-looking Bearer
    token with a sub claim. Falls back to "ip:{remote_address}" on any
    failure — missing header, malformed token, missing sub claim, etc.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            import jwt as pyjwt
            token = auth.split(" ", 1)[1]
            # Decode without signature verification — we only need the sub claim
            # for rate limit bucketing. Full validation is done by verify_token.
            unverified = pyjwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["RS256"],
            )
            sub = unverified.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            # Any failure (expired, malformed, missing library) → IP fallback
            pass
    return f"ip:{get_remote_address(request)}"


# Singleton limiter — attach to app.state.limiter in server.py.
# default_limits covers all GET endpoints (read tier: 200/minute).
# POST/DELETE endpoints add explicit @limiter.limit() decorators per tier.
limiter = Limiter(
    key_func=_get_rate_limit_key,
    default_limits=["200/minute"],
)

__all__ = [
    "limiter",
    "RateLimitExceeded",
    "_rate_limit_exceeded_handler",
    "SlowAPIMiddleware",
]
