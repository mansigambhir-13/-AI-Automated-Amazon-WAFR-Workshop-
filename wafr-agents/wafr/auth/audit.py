"""
Audit logging module for WAFR API security.

Provides:
  - write_audit_entry(): synchronous DynamoDB writer (fire-and-forget via BackgroundTasks / run_in_executor)
  - AuditMiddleware: pure-ASGI class that captures metadata for ALL authenticated requests,
    and logs failed authentication attempts (401 responses) with IP and timestamp.

Design decisions:
  - AuditMiddleware is a pure-ASGI class (not BaseHTTPMiddleware) to avoid ContextVar
    propagation issues and middleware ordering conflicts.
  - write_audit_entry() is synchronous so it can be called via FastAPI BackgroundTasks
    (which run sync functions in a thread executor automatically) or via
    asyncio.get_running_loop().run_in_executor() from async middleware.
  - All failures are logged as warnings; exceptions are NEVER re-raised so that
    audit failures never block or fail API responses (fire-and-forget contract).
  - DynamoDB key schema: PK user_id (S), SK timestamp_session_id (S) with underscore
    separator to match Phase 1 infra spec (# is reserved in DynamoDB expression syntax).
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-initialised DynamoDB table singleton
# ---------------------------------------------------------------------------

_dynamodb = None
_audit_table = None


def _get_audit_table():
    """Return lazy-initialised DynamoDB Table resource (singleton)."""
    global _dynamodb, _audit_table
    if _audit_table is None:
        _dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table_name = os.getenv("WAFR_DYNAMO_AUDIT_TABLE", "wafr-audit-log")
        _audit_table = _dynamodb.Table(table_name)
    return _audit_table


# ---------------------------------------------------------------------------
# write_audit_entry — synchronous, designed for thread-pool execution
# ---------------------------------------------------------------------------

def write_audit_entry(
    user_id: str,
    session_id: Optional[str],
    action_type: str,
    http_method: str,
    path: str,
    client_ip: str,
    request_body: Optional[dict] = None,
    status_code: Optional[int] = None,
) -> None:
    """
    Write a single audit log entry to the wafr-audit-log DynamoDB table.

    This function is synchronous and must NOT be called directly from an
    async event loop.  Use FastAPI BackgroundTasks or
    asyncio.get_running_loop().run_in_executor(None, write_audit_entry, ...)
    so it runs in a thread pool.

    DynamoDB key schema (Phase 1 spec):
      PK  user_id              (S)
      SK  timestamp_session_id (S)  — format: "<ISO_UTC>_<session_id_or_no-session>"

    All exceptions are caught and logged as warnings; the function never raises.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        sk = f"{now}_{session_id or 'no-session'}"

        item: dict = {
            "user_id": user_id,
            "timestamp_session_id": sk,
            "session_id": session_id or "no-session",
            "timestamp": now,
            "action_type": action_type,
            "http_method": http_method,
            "path": path,
            "client_ip": client_ip,
            "request_body": json.dumps(request_body or {}, default=str),
        }

        if status_code is not None:
            item["status_code"] = status_code

        _get_audit_table().put_item(Item=item)

    except Exception as exc:  # noqa: BLE001 — fire-and-forget; never raise
        logger.warning("Audit write failed for user=%s path=%s: %s", user_id, path, exc)


# ---------------------------------------------------------------------------
# AuditMiddleware — pure-ASGI class
# ---------------------------------------------------------------------------

class AuditMiddleware:
    """
    Pure-ASGI middleware that writes an audit entry for every HTTP request.

    Behaviour:
      - Non-HTTP scopes (WebSocket, lifespan) are passed through unchanged.
      - Wraps the inner send() to capture the HTTP response status code from
        the ``http.response.start`` message.
      - After the response is fully sent:
          • Authenticated request  (request.state.claims is set by verify_token):
            schedules write_audit_entry() via run_in_executor (non-blocking).
          • Unauthenticated + 401:  logs a "failed_auth" entry with user_id="anonymous".
          • Unauthenticated + other status (public endpoints like /health): skipped.
      - Does NOT read the request body to avoid buffering large payloads.
        Per-endpoint BackgroundTasks handle body logging for write endpoints.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import asyncio
        from starlette.requests import Request

        request = Request(scope, receive)
        status_code_holder: list[int] = []  # mutable container for closure capture

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_code_holder.append(message.get("status", 0))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Schedule audit write AFTER the response is sent (fire-and-forget)
            status_code = status_code_holder[0] if status_code_holder else None

            claims = getattr(request.state, "claims", None)
            path = scope.get("path", "")
            method = scope.get("method", "")
            client = scope.get("client")
            client_ip = client[0] if client else "unknown"

            if claims is not None:
                # Authenticated request — write standard audit entry
                user_id = claims.get("sub", "unknown")
                session_id = None  # Middleware has no per-endpoint session context

                try:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(
                        None,
                        write_audit_entry,
                        user_id,
                        session_id,
                        "api_call",
                        method,
                        path,
                        client_ip,
                        None,          # request_body — not captured in middleware
                        status_code,
                    )
                except RuntimeError:
                    # No running event loop (e.g. test context) — call synchronously
                    write_audit_entry(
                        user_id=user_id,
                        session_id=session_id,
                        action_type="api_call",
                        http_method=method,
                        path=path,
                        client_ip=client_ip,
                        status_code=status_code,
                    )

            elif status_code == 401:
                # Failed authentication attempt — log with anonymous user_id
                try:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(
                        None,
                        write_audit_entry,
                        "anonymous",
                        None,
                        "failed_auth",
                        method,
                        path,
                        client_ip,
                        None,
                        status_code,
                    )
                except RuntimeError:
                    write_audit_entry(
                        user_id="anonymous",
                        session_id=None,
                        action_type="failed_auth",
                        http_method=method,
                        path=path,
                        client_ip=client_ip,
                        status_code=status_code,
                    )
            # else: public endpoint (e.g. /health) — skip logging
