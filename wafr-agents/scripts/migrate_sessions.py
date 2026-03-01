#!/usr/bin/env python3
"""
Migrate file-based review sessions and pipeline results to DynamoDB.

Idempotent: safe to re-run — skips already-migrated sessions.
Original files are never deleted or modified.

Usage:
    python scripts/migrate_sessions.py                          # Full migration
    python scripts/migrate_sessions.py --dry-run                # Preview only
    python scripts/migrate_sessions.py --sessions-dir /path     # Custom path
    python scripts/migrate_sessions.py --log-file migration.log # Custom log
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# sys.path: ensure 'wafr' package is importable when running from wafr-agents/
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent  # wafr-agents/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from wafr.storage.review_storage import create_review_storage, DynamoDBReviewStorage


# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(log_file: Optional[str] = None) -> logging.Logger:
    """
    Configure root logger to write to both console (INFO) and a log file (DEBUG).

    Args:
        log_file: Path for the log file. Defaults to migration_<timestamp>.log in cwd.

    Returns:
        Configured logger for this module.
    """
    if log_file is None:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        log_file = f"migration_{timestamp}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler — INFO and above
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )

    # File handler — DEBUG and above (per-session detail)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    log = logging.getLogger(__name__)
    log.info("Logging initialised — writing DEBUG detail to: %s", log_file)
    return log


# =============================================================================
# Migration Functions
# =============================================================================

def migrate_sessions(
    sessions_dir: Path,
    storage: DynamoDBReviewStorage,
    dry_run: bool,
    logger: logging.Logger,
) -> Dict[str, Any]:
    """
    Migrate session JSON files from sessions_dir to DynamoDB.

    Each .json file in sessions_dir is treated as one review session. The
    session_id is derived from the filename stem (e.g. ``abc123.json`` →
    ``session_id='abc123'``).

    Idempotency: ``storage.load_session(session_id)`` is called before every
    write. If a record already exists it is skipped without overwriting.

    Args:
        sessions_dir: Path to ``review_sessions/sessions/`` directory.
        storage: Initialised DynamoDB storage backend.
        dry_run: When True, no writes are made to DynamoDB.
        logger: Logger instance for progress and error output.

    Returns:
        Dict with keys ``migrated``, ``skipped``, ``failed``, ``errors``.
    """
    migrated = 0
    skipped = 0
    failed = 0
    errors: List[str] = []

    json_files = sorted(sessions_dir.glob("*.json"))
    if not json_files:
        logger.info("No session files found in %s", sessions_dir)
        return {"migrated": migrated, "skipped": skipped, "failed": failed, "errors": errors}

    logger.info("Found %d session file(s) to process in %s", len(json_files), sessions_dir)

    for file_path in json_files:
        session_id = file_path.stem
        logger.debug("Processing session file: %s (session_id=%s)", file_path.name, session_id)

        try:
            # Idempotency check — does this session already exist in DynamoDB?
            existing = storage.load_session(session_id)
            if existing is not None:
                logger.info("SKIP  %s — already in DynamoDB", session_id)
                skipped += 1
                continue

            if dry_run:
                logger.info("WOULD MIGRATE  %s (dry-run)", session_id)
                migrated += 1
            else:
                with open(file_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)

                # Ensure session_id is present in the data (use filename as fallback)
                if "session_id" not in data:
                    data["session_id"] = session_id

                storage.save_session(data)
                logger.info("MIGRATED  %s", session_id)
                migrated += 1

        except Exception as exc:  # noqa: BLE001
            msg = f"{session_id}: {type(exc).__name__}: {exc}"
            logger.error("FAILED  %s", msg)
            errors.append(msg)
            failed += 1
            # Continue to next file — do not abort entire migration on one failure
            continue

    return {"migrated": migrated, "skipped": skipped, "failed": failed, "errors": errors}


def migrate_pipeline_results(
    pipeline_dir: Path,
    storage: DynamoDBReviewStorage,
    dry_run: bool,
    logger: logging.Logger,
) -> Dict[str, Any]:
    """
    Migrate pipeline result JSON files from pipeline_dir to DynamoDB.

    Each .json file in pipeline_dir is treated as one pipeline result record.
    The session_id is derived from the filename stem.

    Idempotency: ``storage.load_pipeline_results(session_id)`` is called
    before every write.

    Args:
        pipeline_dir: Path to ``review_sessions/pipeline_results/`` directory.
        storage: Initialised DynamoDB storage backend.
        dry_run: When True, no writes are made to DynamoDB.
        logger: Logger instance for progress and error output.

    Returns:
        Dict with keys ``migrated``, ``skipped``, ``failed``, ``errors``.
    """
    migrated = 0
    skipped = 0
    failed = 0
    errors: List[str] = []

    json_files = sorted(pipeline_dir.glob("*.json"))
    if not json_files:
        logger.info("No pipeline result files found in %s", pipeline_dir)
        return {"migrated": migrated, "skipped": skipped, "failed": failed, "errors": errors}

    logger.info(
        "Found %d pipeline result file(s) to process in %s", len(json_files), pipeline_dir
    )

    for file_path in json_files:
        session_id = file_path.stem
        logger.debug(
            "Processing pipeline result file: %s (session_id=%s)", file_path.name, session_id
        )

        try:
            # Idempotency check — does a pipeline result already exist in DynamoDB?
            existing = storage.load_pipeline_results(session_id)
            if existing is not None:
                logger.info("SKIP  %s — pipeline results already in DynamoDB", session_id)
                skipped += 1
                continue

            if dry_run:
                logger.info("WOULD MIGRATE  %s pipeline results (dry-run)", session_id)
                migrated += 1
            else:
                with open(file_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)

                storage.save_pipeline_results(session_id, data)
                logger.info("MIGRATED  %s pipeline results", session_id)
                migrated += 1

        except Exception as exc:  # noqa: BLE001
            msg = f"{session_id}: {type(exc).__name__}: {exc}"
            logger.error("FAILED pipeline result  %s", msg)
            errors.append(msg)
            failed += 1
            continue

    return {"migrated": migrated, "skipped": skipped, "failed": failed, "errors": errors}


# =============================================================================
# Summary Report
# =============================================================================

def print_summary(
    session_report: Dict[str, Any],
    pipeline_report: Dict[str, Any],
    elapsed_seconds: float,
) -> None:
    """
    Print a formatted migration summary to stdout.

    Args:
        session_report: Result dict from migrate_sessions().
        pipeline_report: Result dict from migrate_pipeline_results().
        elapsed_seconds: Total wall-clock time for the migration.
    """
    border = "=" * 44

    print()
    print(border)
    print("MIGRATION SUMMARY")
    print(border)
    print("Sessions:")
    print(f"  Migrated: {session_report['migrated']}")
    print(f"  Skipped:  {session_report['skipped']} (already in DynamoDB)")
    print(f"  Failed:   {session_report['failed']}")
    print()
    print("Pipeline Results:")
    print(f"  Migrated: {pipeline_report['migrated']}")
    print(f"  Skipped:  {pipeline_report['skipped']} (already in DynamoDB)")
    print(f"  Failed:   {pipeline_report['failed']}")
    print()
    print(f"Total time: {elapsed_seconds:.1f}s")
    print(border)

    all_errors = session_report["errors"] + pipeline_report["errors"]
    if all_errors:
        print()
        print("Errors encountered:")
        for error in all_errors:
            print(f"  - {error}")
        print()


# =============================================================================
# CLI Entry Point
# =============================================================================

def main() -> None:
    """Parse arguments, run migration, print summary, and exit with appropriate code."""
    parser = argparse.ArgumentParser(
        prog="migrate_sessions",
        description=(
            "Migrate file-based review sessions and pipeline results to DynamoDB. "
            "Idempotent — safe to re-run; original files are never deleted."
        ),
    )
    parser.add_argument(
        "--sessions-dir",
        default="review_sessions/sessions",
        help="Path to directory containing session JSON files (default: review_sessions/sessions)",
    )
    parser.add_argument(
        "--pipeline-dir",
        default="review_sessions/pipeline_results",
        help=(
            "Path to directory containing pipeline result JSON files "
            "(default: review_sessions/pipeline_results)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be migrated without writing anything to DynamoDB",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path for the log file (default: migration_<timestamp>.log in current directory)",
    )

    args = parser.parse_args()

    logger = setup_logging(args.log_file)

    if args.dry_run:
        logger.info("DRY-RUN mode — no writes will be made to DynamoDB")

    sessions_dir = Path(args.sessions_dir)
    pipeline_dir = Path(args.pipeline_dir)

    # Validate that both directories exist before touching AWS
    missing = []
    if not sessions_dir.exists():
        missing.append(f"Sessions directory not found: {sessions_dir.resolve()}")
    if not pipeline_dir.exists():
        missing.append(f"Pipeline results directory not found: {pipeline_dir.resolve()}")

    if missing:
        for msg in missing:
            logger.error(msg)
        sys.exit(1)

    logger.info("Initialising DynamoDB storage backend...")
    storage = create_review_storage("dynamodb")
    # Narrow type for methods not in the ABC (save_pipeline_results, load_pipeline_results)
    if not isinstance(storage, DynamoDBReviewStorage):
        logger.error(
            "create_review_storage('dynamodb') returned unexpected type: %s", type(storage)
        )
        sys.exit(1)

    start_epoch = time.monotonic()

    logger.info("--- Migrating review sessions ---")
    session_report = migrate_sessions(sessions_dir, storage, args.dry_run, logger)

    logger.info("--- Migrating pipeline results ---")
    pipeline_report = migrate_pipeline_results(pipeline_dir, storage, args.dry_run, logger)

    elapsed = time.monotonic() - start_epoch

    print_summary(session_report, pipeline_report, elapsed)

    # Exit with code 1 if any individual items failed
    total_failed = session_report["failed"] + pipeline_report["failed"]
    if total_failed > 0:
        logger.warning("%d item(s) failed to migrate — review errors above", total_failed)
        sys.exit(1)

    logger.info("Migration complete — all items processed successfully")
    sys.exit(0)


if __name__ == "__main__":
    main()
