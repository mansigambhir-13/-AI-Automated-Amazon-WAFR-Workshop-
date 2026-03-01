"""
Review Storage - Persistence layer for HITL review sessions.

Provides:
- ReviewStorage: Abstract base class defining the storage interface
- InMemoryReviewStorage: In-memory implementation for development/testing
- FileReviewStorage: File-based implementation with JSON persistence
- DynamoDBReviewStorage: DynamoDB-backed implementation for production
"""

import copy
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


# =============================================================================
# Abstract Base Class
# =============================================================================

class ReviewStorage(ABC):
    """
    Abstract interface for review session storage.
    
    All storage implementations must implement these methods to ensure
    consistent behavior across different backends (memory, file, DynamoDB, etc.)
    """
    
    @abstractmethod
    def save_session(self, session_data: Dict[str, Any]) -> None:
        """
        Save or update a review session.
        
        Args:
            session_data: Session data dictionary (serialized ReviewSession)
        """
        pass
    
    @abstractmethod
    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a review session by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session data dictionary or None if not found
        """
        pass
    
    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a review session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deleted, False if not found
        """
        pass
    
    @abstractmethod
    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List review sessions with optional filtering.
        
        Args:
            status: Optional status filter ("ACTIVE", "FINALIZED", etc.)
            limit: Maximum number of sessions to return
            
        Returns:
            List of session data dictionaries
        """
        pass
    
    @abstractmethod
    def update_item(
        self,
        session_id: str,
        review_id: str,
        item_data: Dict[str, Any],
    ) -> bool:
        """
        Update a specific review item within a session.
        
        Args:
            session_id: Session identifier
            review_id: Review item identifier
            item_data: Updated item data
            
        Returns:
            True if updated, False if not found
        """
        pass
    
    @abstractmethod
    def save_validation_record(self, record: Dict[str, Any]) -> None:
        """
        Save a validation record for finalized sessions.
        
        Args:
            record: Validation record data
        """
        pass
    
    @abstractmethod
    def load_validation_record(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load validation record for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Validation record or None if not found
        """
        pass


# =============================================================================
# In-Memory Implementation
# =============================================================================

class InMemoryReviewStorage(ReviewStorage):
    """
    In-memory storage implementation for development and testing.
    
    Data is lost when the application stops. Useful for:
    - Unit testing
    - Development environments
    - Prototyping
    """
    
    def __init__(self):
        """Initialize empty storage."""
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._validation_records: Dict[str, Dict[str, Any]] = {}
        logger.info("InMemoryReviewStorage initialized")
    
    def save_session(self, session_data: Dict[str, Any]) -> None:
        """Save session to memory."""
        session_id = session_data.get("session_id")
        if not session_id:
            raise ValueError("Session data must include 'session_id'")
        
        self._sessions[session_id] = session_data.copy()
        logger.debug(f"Saved session {session_id} to memory")
    
    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session from memory."""
        session = self._sessions.get(session_id)
        return session.copy() if session else None
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session from memory."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.debug(f"Deleted session {session_id} from memory")
            return True
        return False
    
    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List sessions from memory."""
        sessions = list(self._sessions.values())
        
        if status:
            sessions = [s for s in sessions if s.get("status") == status]
        
        # Sort by created_at descending
        sessions.sort(
            key=lambda s: s.get("created_at", ""),
            reverse=True,
        )
        
        return [s.copy() for s in sessions[:limit]]
    
    def update_item(
        self,
        session_id: str,
        review_id: str,
        item_data: Dict[str, Any],
    ) -> bool:
        """Update item in memory."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        items = session.get("items", [])
        for i, item in enumerate(items):
            if item.get("review_id") == review_id:
                items[i] = item_data
                logger.debug(f"Updated item {review_id} in session {session_id}")
                return True
        
        return False
    
    def save_validation_record(self, record: Dict[str, Any]) -> None:
        """Save validation record to memory."""
        session_id = record.get("session_id")
        if not session_id:
            raise ValueError("Validation record must include 'session_id'")
        
        self._validation_records[session_id] = record.copy()
        logger.debug(f"Saved validation record for session {session_id}")
    
    def load_validation_record(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load validation record from memory."""
        record = self._validation_records.get(session_id)
        return record.copy() if record else None
    
    def clear(self) -> None:
        """Clear all data (useful for testing)."""
        self._sessions.clear()
        self._validation_records.clear()
        logger.debug("Cleared all in-memory storage")


# =============================================================================
# File-Based Implementation
# =============================================================================

class FileReviewStorage(ReviewStorage):
    """
    File-based storage implementation with JSON persistence.
    
    Stores each session as a separate JSON file. Suitable for:
    - Single-server deployments
    - Development with persistence needs
    - Simple production setups
    """
    
    def __init__(self, storage_dir: str = "review_sessions"):
        """
        Initialize file storage.
        
        Args:
            storage_dir: Directory for storing session files
        """
        self.storage_dir = Path(storage_dir)
        self.sessions_dir = self.storage_dir / "sessions"
        self.records_dir = self.storage_dir / "validation_records"
        
        # Create directories if they don't exist
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.records_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"FileReviewStorage initialized at {self.storage_dir}")
    
    def _session_path(self, session_id: str) -> Path:
        """Get file path for a session."""
        return self.sessions_dir / f"{session_id}.json"
    
    def _record_path(self, session_id: str) -> Path:
        """Get file path for a validation record."""
        return self.records_dir / f"{session_id}.json"
    
    def save_session(self, session_data: Dict[str, Any]) -> None:
        """Save session to file."""
        session_id = session_data.get("session_id")
        if not session_id:
            raise ValueError("Session data must include 'session_id'")
        
        file_path = self._session_path(session_id)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2, default=str)
        
        logger.debug(f"Saved session {session_id} to {file_path}")
    
    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session from file."""
        file_path = self._session_path(session_id)
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading session {session_id}: {e}")
            return None
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session file."""
        file_path = self._session_path(session_id)
        
        if file_path.exists():
            file_path.unlink()
            logger.debug(f"Deleted session file {file_path}")
            return True
        return False
    
    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List sessions from files."""
        sessions = []
        
        for file_path in self.sessions_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    session = json.load(f)
                    
                    if status is None or session.get("status") == status:
                        sessions.append(session)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error reading {file_path}: {e}")
                continue
        
        # Sort by created_at descending
        sessions.sort(
            key=lambda s: s.get("created_at", ""),
            reverse=True,
        )
        
        return sessions[:limit]
    
    def update_item(
        self,
        session_id: str,
        review_id: str,
        item_data: Dict[str, Any],
    ) -> bool:
        """Update item in session file."""
        session = self.load_session(session_id)
        if not session:
            return False
        
        items = session.get("items", [])
        updated = False
        
        for i, item in enumerate(items):
            if item.get("review_id") == review_id:
                items[i] = item_data
                updated = True
                break
        
        if updated:
            session["items"] = items
            self.save_session(session)
            logger.debug(f"Updated item {review_id} in session {session_id}")
        
        return updated
    
    def save_validation_record(self, record: Dict[str, Any]) -> None:
        """Save validation record to file."""
        session_id = record.get("session_id")
        if not session_id:
            raise ValueError("Validation record must include 'session_id'")
        
        file_path = self._record_path(session_id)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str)
        
        logger.debug(f"Saved validation record for {session_id}")
    
    def load_validation_record(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load validation record from file."""
        file_path = self._record_path(session_id)
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading validation record {session_id}: {e}")
            return None


# =============================================================================
# DynamoDB Helpers
# =============================================================================

def _python_to_dynamodb(obj: Any) -> Any:
    """Recursively convert Python types to DynamoDB-compatible types.

    DynamoDB does not accept Python ``float`` — it requires ``Decimal``.
    This function walks any dict/list structure and converts every ``float``
    to ``Decimal(str(float_val))``, using the string representation to
    avoid floating-point precision artifacts.

    All other types (str, int, bool, None, Decimal) pass through unchanged.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: _python_to_dynamodb(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_python_to_dynamodb(i) for i in obj]
    return obj


def _dynamodb_to_python(obj: Any) -> Any:
    """Recursively convert DynamoDB types back to native Python types.

    After a DynamoDB query/get_item the boto3 resource API returns all
    numbers as ``Decimal``.  This function converts them back:
    - ``Decimal('3')``  → ``int(3)``   (no fractional part)
    - ``Decimal('3.5')`` → ``float(3.5)`` (has fractional part)

    Walks nested dicts and lists.
    """
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    elif isinstance(obj, dict):
        return {k: _dynamodb_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_dynamodb_to_python(i) for i in obj]
    return obj


def _compute_ttl_365d() -> int:
    """Return a Unix-epoch TTL 365 days from now (integer)."""
    return int(time.time()) + (365 * 24 * 60 * 60)


# =============================================================================
# DynamoDB Implementation
# =============================================================================

class DynamoDBReviewStorage(ReviewStorage):
    """
    DynamoDB-backed storage implementation for production deployments.

    Table layout
    ------------
    - ``wafr-sessions``         — pipeline result blobs (PK: session_id, SK: created_at)
    - ``wafr-review-sessions``  — review session metadata (item_id='SESSION') and
                                   per-item decisions (item_id=<review_id>)
                                   (PK: session_id, SK: item_id)
    - ``wafr-users``            — user profiles (PK: user_id)

    Large-item strategy
    -------------------
    - Pipeline results with ``report_base64`` stripped are stored inline as a
      JSON string attribute.  If the stripped result still exceeds
      ``S3_OVERFLOW_THRESHOLD`` (300 KB), it is offloaded to S3 at
      ``dynamo-overflow/pipeline_results/<session_id>.json`` and a pointer key
      is stored in DynamoDB.
    - Transcripts are *always* stored in S3 at
      ``dynamo-overflow/transcripts/<session_id>.txt`` regardless of size.
    """

    S3_OVERFLOW_THRESHOLD = 300 * 1024  # 300 KB in bytes

    def __init__(
        self,
        sessions_table: str = "wafr-sessions",
        review_sessions_table: str = "wafr-review-sessions",
        users_table: str = "wafr-users",
        s3_bucket: str = "wafr-agent-production-artifacts-842387632939",
        region: str = "us-east-1",
    ) -> None:
        """
        Initialise DynamoDB and S3 clients.

        Args:
            sessions_table: Name of the wafr-sessions DynamoDB table.
            review_sessions_table: Name of the wafr-review-sessions table.
            users_table: Name of the wafr-users table.
            s3_bucket: S3 bucket for large-item overflow and transcript storage.
            region: AWS region for both DynamoDB and S3.
        """
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._sessions_table = self._dynamodb.Table(sessions_table)
        self._review_table = self._dynamodb.Table(review_sessions_table)
        self._users_table = self._dynamodb.Table(users_table)
        self._s3 = boto3.client("s3", region_name=region)
        self._s3_bucket = s3_bucket
        logger.info(
            "DynamoDBReviewStorage initialized: sessions=%s, review_sessions=%s, users=%s, bucket=%s",
            sessions_table,
            review_sessions_table,
            users_table,
            s3_bucket,
        )

    # ------------------------------------------------------------------
    # ABC method implementations
    # ------------------------------------------------------------------

    def save_session(self, session_data: Dict[str, Any]) -> None:
        """
        Save a review session to ``wafr-review-sessions``.

        The session metadata is stored at ``item_id='SESSION'``.
        Each review item in ``session_data["items"]`` is stored as a
        separate row with ``item_id=<review_id>``.

        Args:
            session_data: Session data dictionary (must contain ``session_id``).

        Raises:
            ValueError: If ``session_id`` is missing from ``session_data``.
            ClientError: On unrecoverable DynamoDB errors (after logging).
        """
        session_id = session_data.get("session_id")
        if not session_id:
            raise ValueError("session_data must include 'session_id'")

        expires_at = _compute_ttl_365d()
        now_iso = datetime.utcnow().isoformat()

        # --- session metadata row (item_id = 'SESSION') ---
        metadata_item = _python_to_dynamodb({
            "session_id": session_id,
            "item_id": "SESSION",
            "status": session_data.get("status", "ACTIVE"),
            "created_at": session_data.get("created_at", now_iso),
            "updated_at": now_iso,
            "transcript_answers_count": session_data.get("transcript_answers_count", 0),
            "summary": session_data.get("summary", {}),
            "assessment_summary": session_data.get("assessment_summary", {}),
            "expires_at": expires_at,
        })

        try:
            self._review_table.put_item(Item=metadata_item)
        except ClientError as exc:
            logger.error(
                "DynamoDB put_item failed for session metadata %s: %s",
                session_id,
                exc,
            )
            raise

        # --- individual review item rows ---
        for review_item in session_data.get("items", []):
            review_id = review_item.get("review_id")
            if not review_id:
                logger.warning(
                    "Skipping review item without review_id in session %s", session_id
                )
                continue
            row = _python_to_dynamodb(
                {**review_item, "session_id": session_id, "item_id": review_id, "expires_at": expires_at}
            )
            try:
                self._review_table.put_item(Item=row)
            except ClientError as exc:
                logger.error(
                    "DynamoDB put_item failed for review item %s/%s: %s",
                    session_id,
                    review_id,
                    exc,
                )
                raise

        logger.debug("Saved session %s to DynamoDB (%d items)", session_id, len(session_data.get("items", [])))

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a review session from ``wafr-review-sessions``.

        Queries all rows for ``session_id``, separates the metadata row
        (``item_id='SESSION'``) from the per-item rows, and returns the
        reconstructed session dict.

        Args:
            session_id: Session identifier.

        Returns:
            Session dict with ``items`` list, or ``None`` if not found.
        """
        try:
            response = self._review_table.query(
                KeyConditionExpression=Key("session_id").eq(session_id)
            )
        except ClientError as exc:
            logger.error("DynamoDB query failed for session %s: %s", session_id, exc)
            raise

        items = response.get("Items", [])
        if not items:
            return None

        session_meta: Optional[Dict[str, Any]] = None
        review_items: List[Dict[str, Any]] = []

        for raw_item in items:
            item = _dynamodb_to_python(raw_item)
            if item.get("item_id") == "SESSION":
                session_meta = item
            elif item.get("item_id") != "VALIDATION":
                review_items.append(item)

        if session_meta is None:
            return None

        session_meta["items"] = review_items
        return session_meta

    def delete_session(self, session_id: str) -> bool:
        """
        Delete all DynamoDB rows for a session from ``wafr-review-sessions``.

        Queries all items for the session, then batch-deletes them.

        Args:
            session_id: Session identifier.

        Returns:
            ``True`` if rows were deleted, ``False`` if no rows found.
        """
        try:
            response = self._review_table.query(
                KeyConditionExpression=Key("session_id").eq(session_id)
            )
        except ClientError as exc:
            logger.error(
                "DynamoDB query failed during delete for session %s: %s", session_id, exc
            )
            raise

        items = response.get("Items", [])
        if not items:
            return False

        try:
            with self._review_table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(
                        Key={
                            "session_id": item["session_id"],
                            "item_id": item["item_id"],
                        }
                    )
        except ClientError as exc:
            logger.error(
                "DynamoDB batch_writer failed during delete for session %s: %s",
                session_id,
                exc,
            )
            raise

        logger.debug("Deleted session %s from DynamoDB (%d rows)", session_id, len(items))
        return True

    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List review session metadata rows from ``wafr-review-sessions``.

        If ``status`` is provided, queries the ``status-created_at-index`` GSI
        and filters for ``item_id='SESSION'`` rows.  Otherwise, scans the
        table with a filter on ``item_id='SESSION'``.

        Returns summary-only dicts (no nested review items).

        Args:
            status: Optional status filter (e.g. ``"ACTIVE"``).
            limit: Maximum number of session metadata rows to return.

        Returns:
            List of session metadata dicts (without ``items`` lists).
        """
        try:
            if status:
                response = self._review_table.query(
                    IndexName="status-created_at-index",
                    KeyConditionExpression=Key("status").eq(status),
                    FilterExpression=Attr("item_id").eq("SESSION"),
                    ScanIndexForward=False,
                    Limit=limit * 2,  # over-fetch; filter reduces results
                )
            else:
                response = self._review_table.scan(
                    FilterExpression=Attr("item_id").eq("SESSION"),
                    Limit=limit,
                )
        except ClientError as exc:
            logger.error("DynamoDB list_sessions failed (status=%s): %s", status, exc)
            raise

        return [_dynamodb_to_python(item) for item in response.get("Items", [])]

    def update_item(
        self,
        session_id: str,
        review_id: str,
        item_data: Dict[str, Any],
    ) -> bool:
        """
        Overwrite a specific review item row in ``wafr-review-sessions``.

        Uses ``put_item`` for upsert semantics on the composite key
        ``(session_id, item_id=review_id)``.

        Args:
            session_id: Session identifier.
            review_id: Review item identifier (used as ``item_id``).
            item_data: Full item data to store.

        Returns:
            ``True`` on success, ``False`` on ``ClientError``.
        """
        item = _python_to_dynamodb(
            {
                **item_data,
                "session_id": session_id,
                "item_id": review_id,
                "expires_at": _compute_ttl_365d(),
            }
        )
        try:
            self._review_table.put_item(Item=item)
            logger.debug("Updated item %s/%s in DynamoDB", session_id, review_id)
            return True
        except ClientError as exc:
            logger.error(
                "DynamoDB put_item failed for update_item %s/%s: %s",
                session_id,
                review_id,
                exc,
            )
            return False

    def save_validation_record(self, record: Dict[str, Any]) -> None:
        """
        Save a validation record to ``wafr-review-sessions`` at ``item_id='VALIDATION'``.

        Args:
            record: Validation record dict (must contain ``session_id``).

        Raises:
            ValueError: If ``session_id`` is missing.
            ClientError: On unrecoverable DynamoDB errors (after logging).
        """
        session_id = record.get("session_id")
        if not session_id:
            raise ValueError("Validation record must include 'session_id'")

        item = _python_to_dynamodb(
            {**record, "session_id": session_id, "item_id": "VALIDATION", "expires_at": _compute_ttl_365d()}
        )
        try:
            self._review_table.put_item(Item=item)
            logger.debug("Saved validation record for session %s", session_id)
        except ClientError as exc:
            logger.error(
                "DynamoDB put_item failed for validation record %s: %s", session_id, exc
            )
            raise

    def load_validation_record(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a validation record from ``wafr-review-sessions``.

        Args:
            session_id: Session identifier.

        Returns:
            Validation record dict, or ``None`` if not found.
        """
        try:
            response = self._review_table.get_item(
                Key={"session_id": session_id, "item_id": "VALIDATION"}
            )
        except ClientError as exc:
            logger.error(
                "DynamoDB get_item failed for validation record %s: %s", session_id, exc
            )
            raise

        item = response.get("Item")
        return _dynamodb_to_python(item) if item else None

    # ------------------------------------------------------------------
    # Additional methods (not in ABC; required for Phase 2)
    # ------------------------------------------------------------------

    def save_pipeline_results(self, session_id: str, results: Dict[str, Any]) -> None:
        """
        Save pipeline results to ``wafr-sessions``.

        Strips ``report_base64`` from ``steps.wa_workload.review`` before
        writing (the field is already in S3; stripping reduces payload from
        ~1.1 MB to ~77–147 KB).

        If the resulting JSON string still exceeds ``S3_OVERFLOW_THRESHOLD``
        (300 KB), the payload is uploaded to S3 at
        ``dynamo-overflow/pipeline_results/<session_id>.json`` and a pointer
        key is stored in DynamoDB.  Otherwise the JSON string is stored
        directly in the ``pipeline_results_json`` attribute.

        Args:
            session_id: Session identifier.
            results: Raw pipeline results dict (may contain ``report_base64``).

        Raises:
            ClientError: On unrecoverable DynamoDB / S3 errors (after logging).
        """
        # Deep-copy so the caller's object is not mutated
        results_clean = copy.deepcopy(results)

        # Strip report_base64 (already in S3; keeps DynamoDB item small)
        wa = results_clean.get("steps", {}).get("wa_workload", {})
        review = wa.get("review", {})
        if isinstance(review, dict) and "report_base64" in review:
            del review["report_base64"]
            review["report_base64_stripped"] = True

        results_json = json.dumps(results_clean, default=str)
        now_iso = datetime.utcnow().isoformat()
        expires_at = _compute_ttl_365d()

        if len(results_json) > self.S3_OVERFLOW_THRESHOLD:
            # Offload to S3 and store pointer in DynamoDB
            s3_key = f"dynamo-overflow/pipeline_results/{session_id}.json"
            try:
                self._s3.put_object(
                    Bucket=self._s3_bucket,
                    Key=s3_key,
                    Body=results_json.encode("utf-8"),
                    ContentType="application/json",
                )
                logger.info(
                    "Pipeline results for %s offloaded to S3 at %s", session_id, s3_key
                )
            except ClientError as exc:
                logger.error(
                    "S3 put_object failed for pipeline results %s: %s", session_id, exc
                )
                raise

            item = {
                "session_id": session_id,
                "created_at": now_iso,
                "pipeline_results_s3_key": s3_key,
                "pipeline_results_json": None,
                "expires_at": expires_at,
            }
        else:
            item = {
                "session_id": session_id,
                "created_at": now_iso,
                "pipeline_results_json": results_json,
                "expires_at": expires_at,
            }

        try:
            self._sessions_table.put_item(Item=item)
            logger.debug("Saved pipeline results for session %s to DynamoDB", session_id)
        except ClientError as exc:
            logger.error(
                "DynamoDB put_item failed for pipeline results %s: %s", session_id, exc
            )
            raise

    def load_pipeline_results(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load pipeline results from ``wafr-sessions``.

        Retrieves the most-recent item for ``session_id`` (sorted by
        ``created_at`` descending) and returns the parsed pipeline-results
        dict.  Handles both inline JSON and S3-offloaded payloads.

        Args:
            session_id: Session identifier.

        Returns:
            Parsed pipeline results dict, or ``None`` if not found.
        """
        try:
            response = self._sessions_table.query(
                KeyConditionExpression=Key("session_id").eq(session_id),
                ScanIndexForward=False,
                Limit=1,
            )
        except ClientError as exc:
            logger.error(
                "DynamoDB query failed for pipeline results %s: %s", session_id, exc
            )
            raise

        items = response.get("Items", [])
        if not items:
            return None

        item = items[0]

        s3_key = item.get("pipeline_results_s3_key")
        if s3_key:
            try:
                obj = self._s3.get_object(Bucket=self._s3_bucket, Key=s3_key)
                return json.loads(obj["Body"].read().decode("utf-8"))
            except ClientError as exc:
                logger.error(
                    "S3 get_object failed for pipeline results %s (key=%s): %s",
                    session_id,
                    s3_key,
                    exc,
                )
                raise

        results_json = item.get("pipeline_results_json")
        if results_json:
            return json.loads(results_json)

        return None

    def save_transcript(self, session_id: str, transcript_text: str) -> None:
        """
        Save a transcript to S3 and store a reference pointer in ``wafr-sessions``.

        Transcripts are *always* stored in S3 regardless of size, at:
        ``dynamo-overflow/transcripts/<session_id>.txt``

        The DynamoDB row in ``wafr-sessions`` is updated (or created) with
        the ``transcript_s3_key`` attribute pointing to the S3 location.

        Args:
            session_id: Session identifier.
            transcript_text: Raw transcript string.

        Raises:
            ClientError: On unrecoverable S3 / DynamoDB errors (after logging).
        """
        s3_key = f"dynamo-overflow/transcripts/{session_id}.txt"

        # Upload transcript to S3
        try:
            self._s3.put_object(
                Bucket=self._s3_bucket,
                Key=s3_key,
                Body=transcript_text.encode("utf-8"),
                ContentType="text/plain",
            )
            logger.info("Transcript for session %s stored in S3 at %s", session_id, s3_key)
        except ClientError as exc:
            logger.error(
                "S3 put_object failed for transcript %s: %s", session_id, exc
            )
            raise

        # Store S3 pointer in wafr-sessions via UpdateItem
        now_iso = datetime.utcnow().isoformat()
        try:
            self._sessions_table.update_item(
                Key={"session_id": session_id, "created_at": now_iso},
                UpdateExpression="SET transcript_s3_key = :sk",
                ExpressionAttributeValues={":sk": s3_key},
            )
            logger.debug(
                "Updated transcript_s3_key for session %s in DynamoDB", session_id
            )
        except ClientError as exc:
            logger.error(
                "DynamoDB update_item failed for transcript pointer %s: %s",
                session_id,
                exc,
            )
            raise

    def sync_user_profile(
        self,
        user_id: str,
        email: str,
        groups: Optional[List[str]] = None,
        display_name: Optional[str] = None,
    ) -> None:
        """
        Write (upsert) a user profile to the ``wafr-users`` table.

        Uses ``put_item`` for upsert semantics.  Existing records are
        overwritten with the latest values from the identity provider.

        Args:
            user_id: Cognito sub / unique user identifier (primary key).
            email: User's email address.
            groups: List of Cognito group names the user belongs to.
            display_name: Optional human-readable display name.

        Raises:
            ClientError: On unrecoverable DynamoDB errors (after logging).
        """
        now_iso = datetime.utcnow().isoformat()
        item = _python_to_dynamodb({
            "user_id": user_id,
            "email": email,
            "groups": groups or [],
            "display_name": display_name or "",
            "created_at": now_iso,
            "updated_at": now_iso,
        })

        try:
            self._users_table.put_item(Item=item)
            logger.info("Synced user profile for user_id=%s (email=%s)", user_id, email)
        except ClientError as exc:
            logger.error(
                "DynamoDB put_item failed for user profile %s: %s", user_id, exc
            )
            raise


# =============================================================================
# Factory Function
# =============================================================================

def create_review_storage(
    storage_type: str = "memory",
    storage_dir: Optional[str] = None,
    **kwargs: Any,
) -> ReviewStorage:
    """
    Factory function to create appropriate storage instance.

    Args:
        storage_type: One of ``"memory"``, ``"file"``, or ``"dynamodb"``.
        storage_dir: Directory for file storage (only used when
            ``storage_type="file"``; defaults to ``"review_sessions"``).
        **kwargs: Accepted but ignored — allows callers to pass extra keyword
            arguments without breaking if the factory signature evolves.

    Returns:
        ReviewStorage implementation matching the requested backend.

    Raises:
        ValueError: If ``storage_type`` is not one of the supported values.

    Environment variables (used when ``storage_type="dynamodb"``):
        WAFR_DYNAMO_SESSIONS_TABLE:        DynamoDB table for pipeline results
                                           (default: ``"wafr-sessions"``).
        WAFR_DYNAMO_REVIEW_SESSIONS_TABLE: DynamoDB table for review sessions
                                           (default: ``"wafr-review-sessions"``).
        WAFR_DYNAMO_USERS_TABLE:           DynamoDB table for user profiles
                                           (default: ``"wafr-users"``).
        S3_BUCKET:                         S3 bucket for large-item overflow and
                                           transcript storage
                                           (default: ``"wafr-agent-production-artifacts-842387632939"``).
        AWS_DEFAULT_REGION:                AWS region for DynamoDB and S3
                                           (default: ``"us-east-1"``).
    """
    if storage_type == "memory":
        return InMemoryReviewStorage()
    elif storage_type == "file":
        return FileReviewStorage(storage_dir or "review_sessions")
    elif storage_type == "dynamodb":
        return DynamoDBReviewStorage(
            sessions_table=os.getenv("WAFR_DYNAMO_SESSIONS_TABLE", "wafr-sessions"),
            review_sessions_table=os.getenv("WAFR_DYNAMO_REVIEW_SESSIONS_TABLE", "wafr-review-sessions"),
            users_table=os.getenv("WAFR_DYNAMO_USERS_TABLE", "wafr-users"),
            s3_bucket=os.getenv("S3_BUCKET", "wafr-agent-production-artifacts-842387632939"),
            region=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
    else:
        raise ValueError(f"Unknown storage type: {storage_type}. Use 'memory', 'file', or 'dynamodb'.")

