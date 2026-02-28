# Phase 2: Storage Migration - Research

**Researched:** 2026-02-28
**Domain:** DynamoDB persistence layer, S3 overflow, Python boto3 Decimal handling, storage factory pattern
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **File-based storage path:** Keep permanently as fallback for local dev and testing — do not remove
- **Large item offload strategy:** S3 offload with DynamoDB pointer for items exceeding size limit
- **S3 bucket for overflow:** Use existing `wafr-agent-production-artifacts-842387632939` bucket with prefix `dynamo-overflow/`
- **Transcript storage:** Always store in S3 regardless of size — only keep a reference in DynamoDB
- **Migration idempotency:** Script must be safe to re-run without creating duplicates
- **Migration reporting:** Summary with counts of migrated, skipped, and failed items plus log file
- **Original files after migration:** Keep intact — do not delete, serve as backup

### Claude's Discretion

- Switchover strategy (feature flag vs dual-write)
- Auth bypass approach during Phase 2 testing
- REVIEW_STORAGE_TYPE default value
- S3 offload size threshold (pick safe threshold below 400KB)
- Data model shape (nested vs flat, table assignment)
- Float-to-Decimal conversion approach
- Migration method (one-shot vs lazy)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| STOR-01 | Assessment sessions stored durably in DynamoDB and survive container restarts | DynamoDB put_item to `wafr-sessions` table; session metadata (~12KB) fits easily under 400KB limit |
| STOR-02 | Pipeline results stored in DynamoDB with S3 offload for items >400KB | Pipeline results are 1.0–1.3MB total but only 77–147KB after stripping `report_base64` (already in S3); stripped result fits DynamoDB directly |
| STOR-03 | Human review decisions persisted in DynamoDB | Review items are ~1KB each; store in `wafr-review-sessions` with session_id (PK) + item_id (SK) pattern |
| STOR-04 | User profiles with roles and preferences stored in DynamoDB | Write to `wafr-users` (PK: user_id); synced on first Cognito login in Phase 3 — Phase 2 must write a stub user record |
| OPER-02 | AUTH_REQUIRED env flag enables gradual auth rollout | AUTH_REQUIRED=true already set; test with Cognito test user or temporarily set AUTH_REQUIRED=false on App Runner during Phase 2 testing |
</phase_requirements>

---

## Summary

Phase 2 replaces ephemeral file-based session storage with DynamoDB persistence. The four DynamoDB tables are already provisioned and the IAM role has CRUD permissions — the work is entirely in application code: one new `DynamoDBReviewStorage` class, one updated storage factory, one fixed PYTHONPATH issue in the server, and one migration script.

The critical sizing discovery: pipeline result files are 1.0–1.3MB, but this is almost entirely a `report_base64` field (the PDF as a base64 string) that is already uploaded to S3 and has an `s3_key` pointer in the same file. Stripping this field before writing to DynamoDB reduces pipeline results to 77–147KB — well within the 400KB item limit. No general S3 overflow needed for current data. The `dynamo-overflow/` prefix should still be implemented as a safety valve for future large items (300KB threshold is safe), but the standard path will not require it.

The broken DynamoDB save in `server.py` (lines 597, 844, 953) imports `from deployment.entrypoint import ...` where the `deployment/` directory does not exist. The fix is to eliminate these dead code paths entirely and route all persistence through the new `DynamoDBReviewStorage` class under `wafr/storage/` (the path that works per the roadmap decision). Review sessions (the `wafr-review-sessions` table) have a composite key `session_id` (PK) + `item_id` (SK), which enables the elegant pattern of storing session metadata as `item_id='SESSION'` and individual review decisions as `item_id=<review_id>` — one DynamoDB item per review decision, naturally queryable.

**Primary recommendation:** Implement `DynamoDBReviewStorage` in `wafr/storage/review_storage.py` using boto3 resource API with a transparent float-to-Decimal converter; update `create_review_storage()` to accept `storage_type='dynamodb'`; remove the three dead `deployment.entrypoint` import blocks from server.py; write a one-shot idempotent migration script that reads file sessions and writes to DynamoDB. Default `REVIEW_STORAGE_TYPE` to `file` until deployment is validated, then flip to `dynamodb` via App Runner env var.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| boto3 | >=1.34.0 (already in requirements.txt) | DynamoDB resource API for put/get/delete/query | AWS SDK — only way to talk to DynamoDB from Python |
| decimal | stdlib | Float-to-Decimal conversion required by DynamoDB | DynamoDB does not accept Python float; Decimal required for all numeric attributes |
| boto3.dynamodb.conditions | bundled with boto3 | Key(), Attr() for query/filter expressions | Type-safe condition expression builder |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| botocore.exceptions.ClientError | bundled | DynamoDB error handling (ConditionalCheckFailed, ProvisionedThroughputExceeded) | Wrap all DynamoDB calls |
| json | stdlib | Serialize/deserialize pipeline results and session blobs | Round-trip through Decimal conversion on load |
| time | stdlib | Compute TTL Unix timestamps (expires_at) | Phase 1 established 365-day TTL via `expires_at` attribute |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| boto3 resource API | boto3 client API (lower level) | Resource API auto-deserializes Decimal; client returns raw DynamoDB types requiring manual deserialization |
| Storing pipeline results as DynamoDB map | Storing as JSON string attribute | JSON string avoids Decimal issues entirely and supports larger payloads up to 400KB string limit; tradeoff is loss of native DynamoDB query on fields. Recommendation: store as JSON string attribute for pipeline_results blob |
| Per-item row in wafr-review-sessions | Single session row with items as nested list | Per-item rows match the table schema (PK: session_id, SK: item_id), enable individual item updates without rewriting whole session, and avoid Decimal conversion on nested lists |

---

## Architecture Patterns

### Recommended File Structure

```
wafr-agents/wafr/storage/
├── __init__.py
└── review_storage.py          # Add DynamoDBReviewStorage class here
                               # Keep FileReviewStorage and InMemoryReviewStorage unchanged
                               # Update create_review_storage() factory to accept 'dynamodb'

wafr-agents/scripts/
└── migrate_sessions.py        # One-shot idempotent migration script (new file)
```

### Pattern 1: DynamoDBReviewStorage Class

**What:** Implement `DynamoDBReviewStorage(ReviewStorage)` that maps the existing `ReviewStorage` ABC interface to DynamoDB operations.

**Table assignment:**
- `wafr-sessions` — assessment session metadata + pipeline results (one item per session, `item_id` not needed as this table has PK: session_id, SK: created_at)
- `wafr-review-sessions` — review sessions and per-item decisions (session metadata at item_id='SESSION', each review item at item_id=<review_id>)
- `wafr-users` — user profiles (one item per user_id)

**Key insight on `wafr-sessions` sort key:** The table has `created_at` as sort key (string). The `save_session` write must include `created_at`. On `load_session(session_id)`, use a `query()` with `Key('session_id').eq(session_id)` and take the most recent item (sorted by created_at DESC). This is preferable to a `get_item` since we may not know `created_at` at retrieval time.

**Example — Float-to-Decimal converter:**
```python
# Source: AWS boto3 DynamoDB documentation + verified locally
from decimal import Decimal

def _python_to_dynamodb(obj):
    """Recursively convert Python dicts/lists for DynamoDB storage."""
    if isinstance(obj, float):
        return Decimal(str(obj))  # str() avoids floating-point precision artifacts
    elif isinstance(obj, dict):
        return {k: _python_to_dynamodb(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_python_to_dynamodb(i) for i in obj]
    return obj

def _dynamodb_to_python(obj):
    """Recursively convert DynamoDB types back to Python types."""
    if isinstance(obj, Decimal):
        # Preserve int vs float semantics
        return int(obj) if obj == int(obj) else float(obj)
    elif isinstance(obj, dict):
        return {k: _dynamodb_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_dynamodb_to_python(i) for i in obj]
    return obj
```

**Example — save_session to wafr-review-sessions:**
```python
import time

def save_session(self, session_data: Dict[str, Any]) -> None:
    session_id = session_data["session_id"]
    expires_at = int(time.time()) + (365 * 24 * 60 * 60)

    # Store session metadata row (item_id = 'SESSION')
    item = _python_to_dynamodb({
        "session_id": session_id,
        "item_id": "SESSION",
        "status": session_data.get("status", "ACTIVE"),
        "created_at": session_data.get("created_at", datetime.utcnow().isoformat()),
        "updated_at": datetime.utcnow().isoformat(),
        "transcript_answers_count": session_data.get("transcript_answers_count", 0),
        "summary": session_data.get("summary", {}),
        "assessment_summary": session_data.get("assessment_summary", {}),
        "expires_at": expires_at,
    })
    self._review_table.put_item(Item=item)

    # Store each review item individually
    for review_item in session_data.get("items", []):
        row = _python_to_dynamodb({**review_item,
            "session_id": session_id,
            "item_id": review_item["review_id"],
            "expires_at": expires_at,
        })
        self._review_table.put_item(Item=row)
```

**Example — load_session from wafr-review-sessions:**
```python
from boto3.dynamodb.conditions import Key

def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
    # Get all items for this session (metadata + review items)
    response = self._review_table.query(
        KeyConditionExpression=Key("session_id").eq(session_id)
    )
    items = response.get("Items", [])
    if not items:
        return None

    session_meta = None
    review_items = []
    for item in items:
        item = _dynamodb_to_python(item)
        if item["item_id"] == "SESSION":
            session_meta = item
        else:
            review_items.append(item)

    if not session_meta:
        return None

    session_meta["items"] = review_items
    return session_meta
```

### Pattern 2: Pipeline Results Storage in wafr-sessions

**What:** Store pipeline results as a JSON string blob in `wafr-sessions`, stripping the `report_base64` field before writing (it is already in S3).

**Rationale:** The `report_base64` is a PDF already uploaded to `wafr-agent-production-artifacts-842387632939` — its `s3_key` is stored in the same dict. Stripping it reduces the payload from 1.0–1.3MB to 77–147KB, well under the 400KB DynamoDB item limit. Store as a JSON string attribute rather than a native DynamoDB map to avoid Decimal conversion on deeply nested structures with 11 pipeline steps.

```python
def save_pipeline_results(self, session_id: str, results: dict) -> None:
    # Strip report_base64 before storing (already in S3)
    import copy, json
    results_clean = copy.deepcopy(results)
    wa = results_clean.get("steps", {}).get("wa_workload", {})
    review = wa.get("review", {})
    if isinstance(review, dict) and "report_base64" in review:
        del review["report_base64"]
        review["report_base64_stripped"] = True  # flag for debugging

    results_json = json.dumps(results_clean, default=str)

    # S3 offload if still over 300KB threshold
    if len(results_json) > 300 * 1024:
        s3_key = f"dynamo-overflow/pipeline_results/{session_id}.json"
        self._s3.put_object(Bucket=self._bucket, Key=s3_key, Body=results_json)
        self._sessions_table.update_item(...)  # store pointer
    else:
        # Store inline as JSON string attribute
        self._sessions_table.put_item(Item={
            "session_id": session_id,
            "created_at": datetime.utcnow().isoformat(),
            "pipeline_results_json": results_json,
            "expires_at": int(time.time()) + 365*24*60*60,
        })
```

### Pattern 3: Storage Factory Update

**What:** Extend `create_review_storage()` to accept `storage_type='dynamodb'`.

```python
def create_review_storage(storage_type="file", storage_dir=None, **kwargs):
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
```

### Pattern 4: Dead Code Removal in server.py

**What:** Remove the three `from deployment.entrypoint import ...` blocks (lines 597, 844, 953). The `deployment/` directory does not exist — these cause `ModuleNotFoundError` at runtime and are caught by bare `except Exception`. Replace them with no-ops or route through the proper `DynamoDBReviewStorage`.

**Lines to fix:**
- Line 597–613: `save_session_data` call → Remove. The `review_orch.storage.save_session()` call at line 539/581 already handles this.
- Lines 844–879: `get_dynamodb_table()` in `list_sessions` → Remove entire try block. The `review_orch.storage.list_sessions()` at line 809 already handles DynamoDB-backed listing.
- Lines 953–976: `get_dynamodb_table()` in `get_session_details` → Remove. The `review_orch.storage.load_session()` at line 940 already handles this.

### Pattern 5: REVIEW_STORAGE_TYPE Default Strategy

**Recommendation:** Default to `file` (current behavior). Set `dynamodb` only when explicitly configured via env var on App Runner. This satisfies the requirement that `REVIEW_STORAGE_TYPE=file` with `AUTH_REQUIRED=false` keeps a fully working local dev path.

```python
# In get_review_orchestrator():
storage_type = os.getenv("REVIEW_STORAGE_TYPE", "file")  # keep default='file'
```

Flip to `dynamodb` by updating the App Runner env var — no code change required.

### Pattern 6: One-Shot Migration Script

**What:** A standalone script that reads all JSON files from `review_sessions/sessions/` and `review_sessions/pipeline_results/` and writes them to DynamoDB. Idempotency via `ConditionExpression='attribute_not_exists(session_id)'` or by detecting existing items before writing.

**Recommended: check-then-write idempotency** (simpler than ConditionalExpression for multi-table writes):
```python
for session_file in sessions_dir.glob("*.json"):
    session_id = session_file.stem
    # Check if already in DynamoDB
    existing = storage.load_session(session_id)
    if existing:
        report["skipped"] += 1
        continue
    # Write
    storage.save_session(json.loads(session_file.read_text()))
    report["migrated"] += 1
```

### Anti-Patterns to Avoid

- **Using boto3 client API instead of resource API:** Client returns raw DynamoDB JSON `{'S': 'value'}` — resource API handles type mapping automatically (including Decimal round-trip).
- **Storing floats directly in DynamoDB:** boto3 raises `TypeError: Float types are not supported. Use Decimal types instead`. Must convert with `Decimal(str(float_val))`.
- **Storing report_base64 in DynamoDB:** 1.1MB base64 string — will exceed 400KB item limit with error. Strip it; the S3 key pointer is already present.
- **Using scan() for session lookup by session_id:** The `wafr-sessions` table has `session_id` as partition key — always use `query()` with `Key('session_id').eq(...)`. scan() is expensive and slow.
- **Importing `deployment.entrypoint` anywhere:** The `deployment/` directory does not exist in the Docker image. All DynamoDB access must go through `wafr/storage/`.
- **Re-creating `_review_orchestrator` singleton when storage type changes:** The singleton is initialized once. If `REVIEW_STORAGE_TYPE` changes between restarts, the App Runner service restart picks it up on next init.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Float-to-Decimal conversion | Custom type registry | `Decimal(str(float_val))` recursively applied | Simple, reliable, handles edge cases like `Decimal('0.1')` vs `Decimal(0.1)` |
| DynamoDB type mapping | Manual type annotation (`{'S': ...}`) | boto3 **resource** API (`dynamodb.Table`) | Resource API auto-maps Python types; client API returns raw type descriptors |
| Conditional put for idempotency | Complex custom locking | `ConditionExpression='attribute_not_exists(session_id)'` or check-before-write | DynamoDB has built-in conditional writes |
| TTL calculation | Date arithmetic library | `int(time.time()) + 365*24*60*60` | Simple Unix epoch math; DynamoDB TTL expects epoch integer |
| S3 JSON upload | Custom S3 wrapper | `s3.put_object(Bucket=..., Key=..., Body=json_bytes)` | Existing `S3ReportStorage` in `wafr/utils/s3_storage.py` can be reused or the pattern copied |

**Key insight:** The boto3 DynamoDB **resource** API (not client) is the right level of abstraction. It handles all type serialization except the float→Decimal conversion, which must be done explicitly before calling `put_item`.

---

## Common Pitfalls

### Pitfall 1: Float in DynamoDB Causes TypeError at Runtime

**What goes wrong:** Any pipeline result or session containing a Python `float` (e.g., `overall_score: 0.75`) passed to `table.put_item()` raises `TypeError: Float types are not supported. Use Decimal types instead`. This error is silent if caught by the bare `except Exception` handlers currently in server.py.

**Why it happens:** boto3's DynamoDB serializer does not accept Python `float` — AWS DynamoDB uses a fixed-precision decimal type. Python `float` has ambiguous precision.

**How to avoid:** Apply `_python_to_dynamodb()` recursively to all data before `put_item()`. The conversion `Decimal(str(float_val))` uses the string representation to preserve the original precision.

**Warning signs:** DynamoDB writes silently fail, caught by except block; session data exists in memory but is never persisted to DynamoDB.

### Pitfall 2: wafr-sessions Sort Key Required on put_item

**What goes wrong:** `wafr-sessions` has composite key `session_id` (PK) + `created_at` (SK). Calling `put_item` without `created_at` raises `ValidationException: One or more parameter values were invalid: Missing the key created_at in the item`.

**Why it happens:** DynamoDB requires all key attributes in `put_item`. The table was designed with created_at as sort key.

**How to avoid:** Always include both `session_id` and `created_at` in every `put_item` call to `wafr-sessions`. For `load_session(session_id)`, use `query()` with only the partition key — no sort key needed for queries.

**Warning signs:** ValidationException on save; item not found on load (if created_at mismatches).

### Pitfall 3: report_base64 Exceeds Item Size Limit

**What goes wrong:** Pipeline results include a `steps.wa_workload.review.report_base64` field that is 1.1–1.2MB. Storing the full result dict in DynamoDB raises `ItemSizeTooLarge` error.

**Why it happens:** DynamoDB has a hard 400KB per-item limit. The report_base64 is the PDF rendered as base64 — it is already stored in S3 and has an `s3_key` pointer in the same dict.

**How to avoid:** Always strip `report_base64` before writing pipeline results. Set a flag `report_base64_stripped: True` for debuggability. The S3 key is preserved at `steps.wa_workload.s3_key`.

**Warning signs:** `ItemSizeTooLarge` exception on pipeline result save.

### Pitfall 4: deployment.entrypoint Import Causes ModuleNotFoundError

**What goes wrong:** `from deployment.entrypoint import save_session_data` raises `ModuleNotFoundError: No module named 'deployment'` — caught silently by the bare except handler. DynamoDB operations in the session list and detail endpoints fall back to no data returned.

**Why it happens:** The `deployment/` directory was referenced in server.py but never exists in the Docker image (only `wafr/` is copied by the Dockerfile). This was the original broken DynamoDB save mentioned in the CONTEXT.md.

**How to avoid:** Remove all three `from deployment.entrypoint import ...` try blocks from server.py. All DynamoDB access routes through `wafr/storage/DynamoDBReviewStorage`.

**Warning signs:** "Failed to save session to DynamoDB" warning in logs; "Failed to load sessions from DynamoDB (may not be configured)" debug log.

### Pitfall 5: list_sessions with wafr-review-sessions Requires GSI

**What goes wrong:** `list_sessions(status='ACTIVE')` needs to find all sessions with a given status. `wafr-review-sessions` has `status` as a GSI partition key (`status-created_at-index`). A scan() or query on the base table won't work efficiently.

**Why it happens:** The table's primary key is `session_id` + `item_id`, not `status`. Without GSI query, listing by status requires a full table scan.

**How to avoid:** Use the `status-created_at-index` GSI for status-filtered queries:
```python
response = self._review_table.query(
    IndexName="status-created_at-index",
    KeyConditionExpression=Key("status").eq(status),
    ScanIndexForward=False,  # newest first
    Limit=limit,
)
```
For `list_sessions()` with no status filter, use scan with a filter on `item_id = 'SESSION'` to get session metadata rows only.

### Pitfall 6: Auth During Testing

**What goes wrong:** `AUTH_REQUIRED=true` is already set on the App Runner backend. Phase 2 tests that call the API without a Cognito token get 401 responses — no way to test whether DynamoDB save is working.

**How to avoid (two options):**
1. **Recommended:** Create a test Cognito user via AWS CLI (`aws cognito-idp admin-create-user`) and use the `admin-initiate-auth` flow to get a token for curl tests. User Pool ID: `us-east-1_U4ugKPUrh`, App Client ID: `65fis729feu3lr317rm6oaue5s`.
2. **Fallback:** Temporarily set `AUTH_REQUIRED=false` on App Runner backend for the duration of Phase 2 deploy validation, then re-enable before Phase 3.

Option 1 is preferred because it validates the full stack including auth.

### Pitfall 7: Decimal Deserialization Requires Manual Conversion on Read

**What goes wrong:** After a `query()` or `get_item()`, all numbers come back as `Decimal` objects. Passing these to `json.dumps()` raises `TypeError: Object of type Decimal is not JSON serializable`. Passing to the frontend raises similar serialization errors.

**Why it happens:** boto3 resource API deserializes DynamoDB N type to Python `Decimal`, not `float`.

**How to avoid:** Apply `_dynamodb_to_python()` recursively after every `get_item()` or `query()` response. This converts `Decimal` back to `int` or `float` depending on whether it has a fractional part.

### Pitfall 8: REVIEW_STORAGE_TYPE Singleton Initialized at First Request

**What goes wrong:** `_review_orchestrator` is a module-level singleton initialized on first call to `get_review_orchestrator()`. If `REVIEW_STORAGE_TYPE` env var is changed but the process is still running (e.g., in a test), the old storage type is used.

**How to avoid:** In production (App Runner), service restart picks up env var changes — not a real concern. In tests, reset the singleton between test cases: `import wafr.ag_ui.server as srv; srv._review_orchestrator = None`.

---

## Code Examples

### Float-to-Decimal Bidirectional Converter

```python
# Source: Verified locally — boto3 resource API behavior
from decimal import Decimal
from typing import Any

def _python_to_dynamodb(obj: Any) -> Any:
    """Convert Python types to DynamoDB-compatible types (float → Decimal)."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: _python_to_dynamodb(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_python_to_dynamodb(i) for i in obj]
    return obj


def _dynamodb_to_python(obj: Any) -> Any:
    """Convert DynamoDB types back to Python types (Decimal → int or float)."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    elif isinstance(obj, dict):
        return {k: _dynamodb_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_dynamodb_to_python(i) for i in obj]
    return obj
```

### DynamoDBReviewStorage Constructor

```python
import boto3
import os

class DynamoDBReviewStorage(ReviewStorage):
    def __init__(
        self,
        sessions_table: str = "wafr-sessions",
        review_sessions_table: str = "wafr-review-sessions",
        users_table: str = "wafr-users",
        s3_bucket: str = "wafr-agent-production-artifacts-842387632939",
        region: str = "us-east-1",
    ):
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._sessions_table = self._dynamodb.Table(sessions_table)
        self._review_table = self._dynamodb.Table(review_sessions_table)
        self._users_table = self._dynamodb.Table(users_table)
        self._s3 = boto3.client("s3", region_name=region)
        self._s3_bucket = s3_bucket
        logger.info(f"DynamoDBReviewStorage initialized: tables={sessions_table}, {review_sessions_table}")
```

### Session List via GSI

```python
# Source: Verified against wafr-review-sessions table schema (status-created_at-index GSI)
from boto3.dynamodb.conditions import Key, Attr

def list_sessions(self, status=None, limit=100):
    if status:
        # Use GSI for status-filtered queries
        response = self._review_table.query(
            IndexName="status-created_at-index",
            KeyConditionExpression=Key("status").eq(status),
            FilterExpression=Attr("item_id").eq("SESSION"),
            ScanIndexForward=False,
            Limit=limit * 2,  # over-fetch because filter reduces results
        )
    else:
        # Scan for all SESSION metadata rows
        response = self._review_table.scan(
            FilterExpression=Attr("item_id").eq("SESSION"),
            Limit=limit,
        )
    return [_dynamodb_to_python(item) for item in response.get("Items", [])]
```

### TTL Calculation

```python
# Source: Phase 1 decision — 365-day TTL, Unix epoch integer
import time
def _compute_ttl_365d() -> int:
    return int(time.time()) + (365 * 24 * 60 * 60)
```

### Idempotent Migration Script Structure

```python
# wafr-agents/scripts/migrate_sessions.py
import json, logging
from pathlib import Path
from wafr.storage.review_storage import create_review_storage

def migrate(sessions_dir, pipeline_dir, dry_run=False):
    storage = create_review_storage("dynamodb")
    report = {"migrated": 0, "skipped": 0, "failed": 0, "errors": []}

    for session_file in Path(sessions_dir).glob("*.json"):
        session_id = session_file.stem
        # Idempotency: skip if already in DynamoDB
        existing = storage.load_session(session_id)
        if existing:
            report["skipped"] += 1
            continue
        try:
            data = json.loads(session_file.read_text())
            if not dry_run:
                storage.save_session(data)
            report["migrated"] += 1
        except Exception as e:
            report["failed"] += 1
            report["errors"].append({"session_id": session_id, "error": str(e)})

    # Migrate pipeline results separately
    for pr_file in Path(pipeline_dir).glob("*.json"):
        session_id = pr_file.stem
        try:
            results = json.loads(pr_file.read_text())
            if not dry_run:
                storage.save_pipeline_results(session_id, results)
            report["migrated"] += 1
        except Exception as e:
            report["failed"] += 1
            report["errors"].append({"session_id": f"pipeline_{session_id}", "error": str(e)})

    return report
```

---

## Key Infrastructure Facts (from Phase 1)

### DynamoDB Tables

| Table | PK | SK | GSI | TTL | Notes |
|-------|----|----|-----|-----|-------|
| wafr-sessions | session_id (S) | created_at (S) | user_id-created_at-index | expires_at | Pipeline results + session metadata |
| wafr-review-sessions | session_id (S) | item_id (S) | status-created_at-index | expires_at | Review sessions (item_id='SESSION') + per-item decisions (item_id=review_id) |
| wafr-users | user_id (S) | none | email-index | none | User profiles |
| wafr-audit-log | user_id (S) | timestamp_session_id (S) | session_id-timestamp-index | none | Audit records |

### App Runner Environment Variables (already set via Phase 1)

| Variable | Value |
|----------|-------|
| WAFR_DYNAMO_SESSIONS_TABLE | wafr-sessions |
| WAFR_DYNAMO_REVIEW_SESSIONS_TABLE | wafr-review-sessions |
| WAFR_DYNAMO_USERS_TABLE | wafr-users |
| WAFR_DYNAMO_AUDIT_TABLE | wafr-audit-log |
| AUTH_REQUIRED | true |
| REVIEW_STORAGE_TYPE | not set (defaults to 'file') |

### S3 Bucket

- **Name:** `wafr-agent-production-artifacts-842387632939` (confirmed accessible)
- **Existing prefix for reports:** `reports/<session_id>/`
- **New prefix for dynamo overflow:** `dynamo-overflow/pipeline_results/<session_id>.json`
- **Transcripts:** Store at `dynamo-overflow/transcripts/<session_id>.txt` — but note transcripts are NOT currently persisted in pipeline results (no `transcript` key found in existing files). Transcript storage in S3 is a forward-looking requirement; Phase 2 should add it when the transcript is first received in the `/api/wafr/run` handler.

### Existing File Storage Paths

- Pipeline results: `<project_root>/review_sessions/pipeline_results/<session_id>.json` (1.0–1.3MB each, 4 existing files)
- Review sessions: `<project_root>/review_sessions/sessions/<session_id>.json` (4–12KB each, 9 existing files)
- Validation records: `<project_root>/review_sessions/validation_records/`

---

## Decisions to Make During Planning

### 1. REVIEW_STORAGE_TYPE Default

**Recommendation:** Default to `file`. Flip to `dynamodb` on App Runner after Plan 02-01 (code written) and Plan 02-02 (deploy + validate) succeed. This keeps local dev working without AWS credentials.

### 2. Pipeline Results: Inline JSON string vs Separate DynamoDB Attribute Map

**Recommendation:** Store as JSON string in `pipeline_results_json` attribute on the `wafr-sessions` item. Avoids needing to convert deeply nested 11-step pipeline dicts to Decimal throughout. The string is at most 147KB (after stripping report_base64), easily fits in one item.

### 3. S3 Overflow Threshold

**Recommendation:** 300KB. This provides 100KB headroom below the 400KB limit. Current data (after stripping report_base64) tops out at 147KB — the 300KB threshold will not be triggered in practice but is a necessary safety valve.

### 4. Auth During Phase 2 Testing

**Recommendation:** Create a Cognito test user (`wafr-phase2-tester`) via CLI for manual API testing. This validates the full stack without disabling auth. Use `AUTH_REQUIRED=false` only as a last resort if Cognito test user auth fails.

### 5. User Profile (STOR-04) Implementation

**Concern:** Phase 2 has no auth middleware yet (that comes in Phase 3). User profiles require a `user_id` — which only comes from JWT tokens in Phase 3.

**Recommendation:** For Phase 2, write user profile sync as a `sync_user_profile(user_id, email, groups)` method on `DynamoDBReviewStorage` that can be called from Phase 3's auth middleware. In Phase 2, just verify the method writes correctly by calling it with a test user_id directly — satisfies STOR-04's "user profile records exist in DynamoDB" success criterion.

---

## Open Questions

1. **STOR-04 trigger point — when does a user profile get written?**
   - What we know: Phase 2 has no JWT middleware. Phase 3 will validate tokens and know user_id.
   - What's unclear: Whether the planner will stub a user profile write in Phase 2 or defer to Phase 3.
   - Recommendation: Phase 2 implements `sync_user_profile()` method and verifies it manually. Phase 3 wires it into middleware. Mark STOR-04 as "implemented but not wired" after Phase 2.

2. **wafr-sessions created_at query — can we always reconstruct it?**
   - What we know: Table has session_id (PK) + created_at (SK). load_session() needs to query by session_id only.
   - What's unclear: Whether to query and take first result vs get_item requiring exact created_at.
   - Recommendation: Use query(KeyConditionExpression=Key('session_id').eq(session_id)) and take the most recent item. Confirmed working via AWS SDK behavior — no created_at needed for query, only for get_item.

3. **Existing file sessions count and migration time**
   - What we know: 4 pipeline results, 9 session files. Migration is fast (<1 second total).
   - What's unclear: Whether any new sessions will be created during migration window.
   - Recommendation: One-shot script is safe; file storage remains active during migration; script skips already-migrated items.

---

## Sources

### Primary (HIGH confidence)

- Verified locally: boto3 1.34+ resource API behavior with DynamoDB — Decimal type handling confirmed with working code
- Verified locally: DynamoDB table schemas by querying table.key_schema via boto3 resource API
- Verified locally: Pipeline result file sizes (1.0–1.3MB total; 77–147KB after stripping report_base64)
- Verified locally: S3 bucket `wafr-agent-production-artifacts-842387632939` accessible via head_bucket
- Verified locally: DynamoDB put_item + get_item + delete_item round-trip works with Decimal types
- Phase 1 SUMMARY files: Table schemas, GSI names, TTL attribute names, IAM role permissions confirmed

### Secondary (MEDIUM confidence)

- wafr-agents/wafr/ag_ui/server.py code inspection: three broken `from deployment.entrypoint import ...` blocks identified at lines 597, 844, 953
- wafr-agents/wafr/storage/review_storage.py code inspection: existing ABC interface documented; factory function identified
- wafr-agents/wafr/utils/s3_storage.py code inspection: `S3_BUCKET` env var and production bucket name confirmed

### Tertiary (LOW confidence)

None — all findings verified from source code or live AWS environment.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — boto3 already in requirements.txt; verified working against live tables
- Architecture: HIGH — verified against actual table schemas, file sizes, and existing code structure
- Pitfalls: HIGH — float-to-Decimal verified locally; dead deployment module confirmed missing; report_base64 size measured directly

**Research date:** 2026-02-28
**Valid until:** 2026-03-28 (stable AWS SDK APIs; table schemas immutable once provisioned)
