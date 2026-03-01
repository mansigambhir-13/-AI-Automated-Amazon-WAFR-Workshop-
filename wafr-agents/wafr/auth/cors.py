"""
CORS origin configuration for the WAFR AG-UI server.

Reads allowed origins from the WAFR_CORS_ORIGINS environment variable
(comma-separated list). Defaults to the production App Runner frontend
domain plus localhost for local development.

SSE endpoints use a slightly more permissive CORS configuration:
- Same origins as the standard list
- Plus any from WAFR_SSE_CORS_ORIGINS (empty by default)
- Plus allow_origin_regex for *.us-east-1.awsapprunner.com to support
  future embedding from other App Runner services in the same region.
"""

import os

# Default origins: production App Runner frontend + local dev
_DEFAULT_ORIGINS = (
    "https://3fhp6mfj7u.us-east-1.awsapprunner.com,"
    "http://localhost:3000"
)

# 1-hour preflight cache — balances security (renegotiation on config change)
# with performance (fewer OPTIONS roundtrips). Claude's discretion per research.
CORS_MAX_AGE = 3600

# Regex that matches any App Runner service in us-east-1 — used for SSE
# endpoints where embedding in other services is allowed.
SSE_ORIGIN_REGEX = r"https://.*\.us-east-1\.awsapprunner\.com"


def get_cors_origins() -> list[str]:
    """
    Return the list of allowed CORS origins for standard API endpoints.

    Reads WAFR_CORS_ORIGINS env var (comma-separated). Strips whitespace
    and filters empty strings. Defaults to production frontend + localhost.

    Examples:
        Default: ["https://3fhp6mfj7u.us-east-1.awsapprunner.com", "http://localhost:3000"]
        Override: WAFR_CORS_ORIGINS="https://myapp.com,http://localhost:8080"
    """
    raw = os.getenv("WAFR_CORS_ORIGINS", _DEFAULT_ORIGINS)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins


def get_sse_cors_origins() -> list[str]:
    """
    Return the list of allowed CORS origins for SSE streaming endpoints.

    Combines standard origins with any additional SSE-specific origins from
    WAFR_SSE_CORS_ORIGINS env var. The regex SSE_ORIGIN_REGEX covers the
    *.us-east-1.awsapprunner.com pattern and should be passed as
    allow_origin_regex in CORSMiddleware.
    """
    origins = get_cors_origins()
    sse_extra_raw = os.getenv("WAFR_SSE_CORS_ORIGINS", "")
    if sse_extra_raw.strip():
        extra = [o.strip() for o in sse_extra_raw.split(",") if o.strip()]
        # Deduplicate while preserving order
        seen = set(origins)
        for o in extra:
            if o not in seen:
                origins.append(o)
                seen.add(o)
    return origins
