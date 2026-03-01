"""WAFR Authentication and Security subpackage."""
from wafr.auth.jwt_middleware import verify_token, require_team_role
from wafr.auth.cors import get_cors_origins, CORS_MAX_AGE
from wafr.auth.rate_limit import limiter
from wafr.auth.audit import write_audit_entry, AuditMiddleware

__all__ = [
    "verify_token",
    "require_team_role",
    "get_cors_origins",
    "CORS_MAX_AGE",
    "limiter",
    "write_audit_entry",
    "AuditMiddleware",
]
