"""
AG-UI SSE Server for WAFR Pipeline.

Provides FastAPI endpoints for AG-UI compatible event streaming,
enabling real-time frontend updates during WAFR assessment.

Endpoints:
- POST /api/wafr/run - Start WAFR assessment with SSE streaming
- POST /api/wafr/process-file - Process file with SSE streaming
- GET /api/wafr/session/{session_id}/state - Get session state
- POST /api/wafr/review/{session_id}/decision - Submit review decision
- POST /api/wafr/review/{session_id}/batch-approve - Batch approve items
- POST /api/wafr/review/{session_id}/finalize - Finalize review session

Usage:
    # Run server
    uvicorn ag_ui.server:app --reload --port 8000
    
    # Or use in existing FastAPI app
    from ag_ui.server import router
    app.include_router(router)
"""

from typing import Any, Dict, List, Literal, Optional
from datetime import datetime
from pathlib import Path
import asyncio
import uuid
import logging
import json
import os

from fastapi import Depends, FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from wafr.ag_ui.emitter import WAFREventEmitter
from wafr.ag_ui.events import (
    ReviewQueueSummary,
    SynthesisProgress,
    ReviewDecisionData,
    ValidationStatus,
)
from wafr.ag_ui.state import WAFRState, SessionStatus
from wafr.auth.jwt_middleware import verify_token, require_team_role
from wafr.auth.cors import get_cors_origins, CORS_MAX_AGE
from wafr.auth.rate_limit import limiter, SlowAPIMiddleware, RateLimitExceeded, _rate_limit_exceeded_handler
from wafr.auth.audit import AuditMiddleware, write_audit_entry

logger = logging.getLogger(__name__)


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="WAFR AG-UI Server",
    description="AG-UI compatible event streaming for WAFR pipeline",
    version="1.0.0",
)

# 1. Audit middleware (innermost — must be registered first so it captures
#    response status codes AFTER all other middleware have processed the
#    request/response).  Pure-ASGI class, compatible with add_middleware().
app.add_middleware(AuditMiddleware)

# 2. Rate limiter state — must be set before SlowAPIMiddleware is added.
#    SlowAPIMiddleware registered BEFORE CORSMiddleware in source order.
#    Starlette builds middleware as a stack: last add_middleware() call becomes
#    the outermost layer (first to run on requests). SlowAPIMiddleware runs
#    INSIDE CORS so that CORS headers are present on 429 responses too.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS middleware — MUST be the last add_middleware() call (outermost layer,
# executes first on inbound requests). This guarantees that auth 401 and
# rate-limit 429 responses carry Access-Control-Allow-Origin headers so the
# browser can display meaningful errors instead of an opaque CORS failure.
# (Research Pitfall 2 + Pitfall 6: no wildcard with allow_credentials=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Cache-Control"],
    expose_headers=["X-Request-ID"],
    max_age=CORS_MAX_AGE,
)

# Store active sessions
active_sessions: Dict[str, WAFREventEmitter] = {}
session_states: Dict[str, WAFRState] = {}
session_results: Dict[str, Dict[str, Any]] = {}  # Store full orchestrator results per session

# Pipeline results persistence
PIPELINE_RESULTS_DIR = Path(__file__).parent.parent.parent / "review_sessions" / "pipeline_results"
SESSIONS_DIR = Path(__file__).parent.parent.parent / "review_sessions" / "sessions"
REPORTS_DIR = Path("/tmp/reports")


def _save_pipeline_results(session_id: str, results: dict) -> None:
    """Persist pipeline results to disk for survival across restarts."""
    PIPELINE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = PIPELINE_RESULTS_DIR / f"{session_id}.json"
    with open(file_path, "w") as f:
        json.dump(results, f, default=str)


def _load_pipeline_results(session_id: str) -> Optional[dict]:
    """Load pipeline results from disk."""
    file_path = PIPELINE_RESULTS_DIR / f"{session_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, "r") as f:
        return json.load(f)


def _reconstruct_from_report(session_id: str) -> Optional[dict]:
    """
    Reconstruct a session_results-compatible dict from the report JSON and session file.
    Used for sessions that completed before persistence was added.
    """
    # Find the report JSON file
    report_path = REPORTS_DIR / f"wafr_report_{session_id}.json"
    if not report_path.exists():
        return None

    try:
        with open(report_path, "r") as f:
            report_data = json.load(f)
    except Exception:
        return None

    report = report_data.get("report", {})
    pillar_analysis = report.get("pillar_analysis", [])
    exec_summary = report.get("executive_summary", {})
    pillar_coverage_raw = exec_summary.get("pillar_coverage", {})

    # Load session file for overall_score and metadata
    session_path = SESSIONS_DIR / f"{session_id}.json"
    session_meta = {}
    if session_path.exists():
        try:
            with open(session_path, "r") as f:
                session_meta = json.load(f)
        except Exception:
            pass

    assessment = session_meta.get("assessment_summary", {})
    overall_score = assessment.get("overall_score", 0.0)

    # Reconstruct all_answers from pillar_analysis questions
    all_answers = []
    for pillar in pillar_analysis:
        pillar_id = pillar.get("pillar_id", "")
        pillar_name = pillar.get("pillar_name", "")
        for q in pillar.get("questions", []):
            answer_text = q.get("answer", "")
            all_answers.append({
                "question_id": q.get("question_id", ""),
                "question_text": q.get("question_text", ""),
                "pillar": pillar_name,
                "pillar_id": pillar_id,
                "answer": answer_text,
                "risk_level": q.get("risk_level", "LOW"),
                "confidence": 0.8 if answer_text else 0.0,
                "source": "reconstructed_from_report",
            })

    # Reconstruct pillar scores from coverage data
    pillar_scores = {}
    pillar_coverage = {}
    for pid, cov in pillar_coverage_raw.items():
        coverage_pct = cov.get("coverage_pct", 0) if isinstance(cov, dict) else 0
        pillar_coverage[pid] = coverage_pct
        pillar_scores[pid] = round(coverage_pct / 100.0, 2)

    # Reconstruct gaps from unanswered questions
    gaps = []
    for answer in all_answers:
        if not answer.get("answer"):
            gaps.append({
                "question_id": answer["question_id"],
                "question_text": answer["question_text"],
                "pillar": answer["pillar"],
                "pillar_id": answer.get("pillar_id", ""),
                "gap_type": "unanswered",
                "criticality": "medium",
                "question_data": {"best_practices": []},
            })

    # Build the session_results-compatible structure
    reconstructed = {
        "session_id": session_id,
        "status": "completed",
        "reconstructed": True,
        "steps": {
            "understanding": {"insights": []},
            "mapping": {
                "mappings": [],
                "pillar_coverage": pillar_coverage_raw,
            },
            "confidence": {
                "validated_answers": [a for a in all_answers if a.get("answer")],
                "all_validations": [],
                "summary": {},
            },
            "gap_detection": {"gaps": gaps},
            "answer_synthesis": {
                "synthesized_answers": [],
                "total_synthesized": 0,
            },
            "auto_populate": {
                "all_answers": all_answers,
                "validated_count": len([a for a in all_answers if a.get("answer")]),
                "synthesized_count": 0,
            },
            "scoring": {
                "scores": {
                    "overall_score": overall_score,
                    "pillar_scores": pillar_scores,
                    "pillar_coverage": pillar_coverage,
                },
            },
            "report": report_data.get("report", {}),
            "wa_workload": {
                "workload_id": assessment.get("workload_id"),
                "report_file": assessment.get("report_file"),
                "status": "completed",
            },
        },
        "processing_time": {},
        "errors": [],
    }

    logger.info(f"Reconstructed session_results for {session_id} from report JSON ({len(all_answers)} answers, {len(gaps)} gaps)")

    # Persist the reconstruction so we don't repeat this
    _save_pipeline_results(session_id, reconstructed)

    return reconstructed


def _ensure_session_results(session_id: str) -> bool:
    """Load pipeline results from disk or DynamoDB into session_results if not in memory."""
    if session_id in session_results:
        return True
    # Try loading persisted pipeline results from disk
    loaded = _load_pipeline_results(session_id)
    if loaded:
        session_results[session_id] = loaded
        return True
    # Try loading from DynamoDB storage (recovery after container restart)
    try:
        review_orch = get_review_orchestrator()
        if review_orch and hasattr(review_orch.storage, 'load_pipeline_results'):
            ddb_results = review_orch.storage.load_pipeline_results(session_id)
            if ddb_results:
                session_results[session_id] = ddb_results
                # Cache to local disk for subsequent reads
                _save_pipeline_results(session_id, ddb_results)
                logger.info("Recovered pipeline results for session %s from DynamoDB", session_id)
                return True
    except Exception as e:
        logger.warning("Failed to load pipeline results from DynamoDB for session %s: %s", session_id, e)
    # Fallback: reconstruct from report JSON for old sessions
    reconstructed = _reconstruct_from_report(session_id)
    if reconstructed:
        session_results[session_id] = reconstructed
        return True
    return False


# ---------------------------------------------------------------------------
# Validated-answers helpers (wire HITL review into data & report)
# ---------------------------------------------------------------------------

def _merge_validated_answers_into_results(session_id: str, validated_answers: List[Dict]) -> bool:
    """
    Overlay human-reviewed answers onto session_results so every data endpoint
    (get_questions, get_pillars, download_results) returns post-review content.

    Returns True if the merge changed anything.
    """
    if not validated_answers:
        return False

    _ensure_session_results(session_id)
    if session_id not in session_results:
        logger.warning(f"Cannot merge validated answers: no session_results for {session_id}")
        return False

    results = session_results[session_id]
    steps = results.setdefault("steps", {})

    # Build lookup: question_id → validated answer
    validated_map = {va["question_id"]: va for va in validated_answers}

    changed = False

    # Patch auto_populate.all_answers (primary source for get_questions)
    all_answers = steps.get("auto_populate", {}).get("all_answers", [])
    for ans in all_answers:
        qid = ans.get("question_id", "")
        if qid in validated_map:
            va = validated_map[qid]
            ans["answer_content"] = va["answer_content"]
            ans["synthesized_answer"] = va["answer_content"]
            ans["source"] = va["source"]
            ans["confidence"] = va["confidence"]
            ans["review_status"] = va["source"]  # AI_VALIDATED / AI_MODIFIED
            changed = True

    # Patch answer_synthesis.synthesized_answers (fallback source)
    synth_answers = steps.get("answer_synthesis", {}).get("synthesized_answers", [])
    for ans in synth_answers:
        qid = ans.get("question_id", "")
        if qid in validated_map:
            va = validated_map[qid]
            ans["synthesized_answer"] = va["answer_content"]
            ans["answer_content"] = va["answer_content"]
            ans["source"] = va["source"]
            ans["confidence"] = va["confidence"]
            changed = True

    # Patch confidence.validated_answers
    conf_answers = steps.get("confidence", {}).get("validated_answers", [])
    for ans in conf_answers:
        qid = ans.get("question_id", "")
        if qid in validated_map:
            va = validated_map[qid]
            ans["answer_content"] = va["answer_content"]
            ans["source"] = va["source"]
            ans["confidence"] = va["confidence"]
            changed = True

    # Mark results as validated
    if changed:
        results["review_applied"] = True
        results["review_applied_at"] = datetime.utcnow().isoformat()
        results["review_stats"] = {
            "total_validated": len(validated_answers),
            "modified": sum(1 for v in validated_answers if v["source"] == "AI_MODIFIED"),
        }
        # Persist updated results
        _save_pipeline_results(session_id, results)
        try:
            review_orch = get_review_orchestrator()
            if review_orch and hasattr(review_orch.storage, 'save_pipeline_results'):
                review_orch.storage.save_pipeline_results(session_id, results)
        except Exception as e:
            logger.warning(f"Failed to persist reviewed results to DynamoDB: {e}")
        logger.info(f"Merged {len(validated_answers)} validated answers into session_results for {session_id}")

    return changed


async def _regenerate_wa_report(session_id: str, validated_answers: List[Dict]) -> None:
    """
    Background task: push reviewed answer notes into the AWS WA Tool workload
    and regenerate the official PDF report so it reflects human review.
    """
    import asyncio

    _ensure_session_results(session_id)
    results = session_results.get(session_id)
    if not results:
        logger.warning(f"[WA-regen] No results for {session_id}, skipping report regen")
        return

    wa_step = results.get("steps", {}).get("wa_workload", {})
    workload_id = wa_step.get("workload_id") if isinstance(wa_step, dict) else None
    if not workload_id:
        logger.info(f"[WA-regen] No workload_id for {session_id}, skipping WA report regen")
        return

    try:
        from wafr.agents.wa_tool_agent import WAToolAgent

        wa_agent = WAToolAgent()

        # Update notes for each validated answer in WA Tool
        modified_answers = [va for va in validated_answers if va["source"] == "AI_MODIFIED"]
        if modified_answers:
            logger.info(f"[WA-regen] Updating {len(modified_answers)} modified answers in WA Tool workload {workload_id}")
            for va in modified_answers:
                qid = va["question_id"]
                try:
                    # Get current answer to preserve selected_choices
                    current = wa_agent.wa_client.get_answer(
                        workload_id=workload_id,
                        lens_alias="wellarchitected",
                        question_id=qid,
                    )
                    current_answer = current.get("Answer", {})
                    selected = current_answer.get("SelectedChoices", [])
                    if not selected:
                        # Keep existing choices; cannot update without them
                        logger.debug(f"[WA-regen] No selected choices for {qid}, updating notes only via existing choices")
                        selected = current_answer.get("ChoiceAnswers", [])
                        selected = [ca.get("ChoiceId") for ca in selected if ca.get("Status") == "SELECTED"]

                    if selected:
                        wa_agent.wa_client.update_answer(
                            workload_id=workload_id,
                            lens_alias="wellarchitected",
                            question_id=qid,
                            selected_choices=selected,
                            notes=f"[Human-Reviewed] {va['answer_content'][:2048]}",
                        )
                        logger.info(f"[WA-regen] Updated WA Tool answer for {qid}")
                    else:
                        logger.warning(f"[WA-regen] Skipping {qid}: no selected choices found")
                except Exception as e:
                    logger.warning(f"[WA-regen] Failed to update WA answer for {qid}: {e}")

        # Regenerate report (create new milestone + download PDF)
        logger.info(f"[WA-regen] Regenerating report for workload {workload_id}")
        save_path = f"/tmp/reports/wafr_aws_report_{session_id}_reviewed.pdf"
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        review_result = wa_agent.create_milestone_and_review(
            workload_id=workload_id,
            milestone_name=f"Post_Review_{session_id[:8]}",
            save_report_path=save_path,
        )

        if os.path.exists(save_path):
            # Update session_results with new report path
            if isinstance(wa_step, dict):
                wa_step["report_file"] = save_path
                wa_step["report_reviewed"] = True
            _save_pipeline_results(session_id, results)
            # Update in-memory state
            if session_id in session_states:
                session_states[session_id].report.file_path = save_path
                session_states[session_id].report.generated = True
            logger.info(f"[WA-regen] Regenerated reviewed report at {save_path}")
        else:
            logger.warning(f"[WA-regen] Report file not created at {save_path}")

    except Exception as e:
        logger.error(f"[WA-regen] Failed to regenerate WA report for {session_id}: {e}", exc_info=True)


# Initialize ReviewOrchestrator with storage (singleton)
_review_orchestrator = None

def get_review_orchestrator():
    """Get or create ReviewOrchestrator instance with storage."""
    global _review_orchestrator
    if _review_orchestrator is None:
        from wafr.agents.review_orchestrator import ReviewOrchestrator
        from wafr.storage.review_storage import create_review_storage
        import os
        from pathlib import Path
        
        # Initialize storage (default to dynamodb in container deployments)
        if not os.getenv("REVIEW_STORAGE_TYPE"):
            logger.warning(
                "REVIEW_STORAGE_TYPE not set; defaulting to 'dynamodb'. "
                "Set to 'file' for local development."
            )
        storage_type = os.getenv("REVIEW_STORAGE_TYPE", "dynamodb")
        storage_dir = os.getenv("REVIEW_STORAGE_DIR", "review_sessions")

        # Convert to absolute path if relative
        if not os.path.isabs(storage_dir):
            # Get project root (parent of src directory)
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # Go up from src/wafr/ag_ui/server.py
            storage_dir = str(project_root / storage_dir)

        storage = create_review_storage(storage_type=storage_type, storage_dir=storage_dir)
        
        _review_orchestrator = ReviewOrchestrator(storage=storage)
        logger.info(f"ReviewOrchestrator initialized with {storage_type} storage at {storage_dir}")
    
    return _review_orchestrator


# =============================================================================
# Request/Response Models
# =============================================================================

class RunWAFRRequest(BaseModel):
    """Request to run WAFR assessment."""

    thread_id: Optional[str] = Field(None, description="Thread/session ID")
    run_id: Optional[str] = Field(None, description="Run ID")
    transcript: Optional[str] = Field(
        None,
        max_length=500_000,
        description="Transcript text (max 500,000 characters)",
    )
    transcript_path: Optional[str] = Field(None, description="Path to transcript file")
    generate_report: bool = Field(True, description="Generate PDF report")
    client_name: Optional[str] = Field(
        None,
        max_length=200,
        description="Client name for workload",
    )
    options: Optional[Dict[str, Any]] = Field(None, description="Optional settings (generate_report, client_name)")


class ProcessFileRequest(BaseModel):
    """Request to process file."""

    thread_id: Optional[str] = Field(None, description="Thread/session ID")
    file_path: str = Field(..., max_length=1024, description="Path to file")
    generate_report: bool = Field(True, description="Generate PDF report")


class ReviewDecisionRequest(BaseModel):
    """Request to submit review decision."""

    review_id: str = Field(..., max_length=128, description="Review item ID")
    decision: Literal["APPROVE", "MODIFY", "REJECT"] = Field(
        ..., description="Decision: APPROVE, MODIFY, or REJECT"
    )
    reviewer_id: str = Field(..., max_length=128, description="Reviewer ID")
    modified_answer: Optional[str] = Field(
        None, max_length=500_000, description="Modified answer text"
    )
    feedback: Optional[str] = Field(
        None, max_length=10_000, description="Feedback for rejection"
    )


class BatchApproveRequest(BaseModel):
    """Request to batch approve items."""

    review_ids: list[str] = Field(..., description="List of review item IDs")
    reviewer_id: str = Field(..., max_length=128, description="Reviewer ID")


class FinalizeRequest(BaseModel):
    """Request to finalize review session."""

    approver_id: str = Field(..., max_length=128, description="Approver ID")


class StateResponse(BaseModel):
    """Response containing session state."""
    
    session_id: str
    state: Dict[str, Any]
    timestamp: str


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str
    service: str
    version: str
    active_sessions: int


# =============================================================================
# Root & Health Check
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint — server info and available routes."""
    return {
        "service": "WAFR AG-UI Server",
        "version": "1.0.0",
        "status": "running",
        "active_sessions": len(active_sessions),
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "run_assessment": "POST /api/wafr/run",
            "process_file": "POST /api/wafr/process-file",
            "sessions": "GET /api/wafr/sessions",
            "session_state": "GET /api/wafr/session/{session_id}/state",
            "review_decision": "POST /api/wafr/review/{session_id}/decision",
            "batch_approve": "POST /api/wafr/review/{session_id}/batch-approve",
            "finalize": "POST /api/wafr/review/{session_id}/finalize",
        },
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        service="wafr-ag-ui-server",
        version="1.0.0",
        active_sessions=len(active_sessions),
    )


# =============================================================================
# WAFR Processing Endpoints
# =============================================================================

@app.post("/api/wafr/run")
@limiter.limit("10/minute")
async def run_wafr_assessment(
    request: Request,
    body: RunWAFRRequest,
    background_tasks: BackgroundTasks,
    claims: dict = Depends(require_team_role),
):
    """
    Run WAFR assessment with AG-UI event streaming.

    Returns SSE stream of events.
    """
    # Per-endpoint audit: log request body (transcript excluded — too large)
    audit_body = body.model_dump(exclude={"transcript"})
    audit_body["transcript_length"] = len(body.transcript) if body.transcript else 0
    background_tasks.add_task(
        write_audit_entry,
        user_id=claims.get("sub", "unknown"),
        session_id=body.thread_id,
        action_type="wafr_run",
        http_method="POST",
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
        request_body=audit_body,
    )

    thread_id = body.thread_id or str(uuid.uuid4())
    run_id = body.run_id or str(uuid.uuid4())
    
    # Create event emitter
    emitter = WAFREventEmitter(thread_id=thread_id, run_id=run_id)
    active_sessions[thread_id] = emitter
    session_states[thread_id] = emitter.state
    
    async def event_generator():
        """Generate SSE events."""
        try:
            # Import here to avoid circular imports
            from wafr.ag_ui.orchestrator_integration import create_agui_orchestrator
            
            # Determine input source
            if body.transcript:
                transcript = body.transcript
            elif body.transcript_path:
                with open(body.transcript_path, 'r', encoding='utf-8') as f:
                    transcript = f.read()
            else:
                await emitter.run_error("No transcript or transcript_path provided")
                async for event_data in emitter.stream_events():
                    yield event_data
                return

            # Create AG-UI enabled orchestrator with the emitter
            agui_orchestrator = create_agui_orchestrator(
                orchestrator=None,  # Will create production orchestrator
                emitter=emitter,
                thread_id=thread_id,
            )

            # Merge options (backward compatibility for "options" payload)
            opts = body.options or {}
            generate_report = opts.get("generate_report", body.generate_report)
            client_name = opts.get("client_name", body.client_name)
            
            # Ensure client_name has a default value if None
            if not client_name:
                client_name = "WAFR-Client"
                logger.warning(f"No client_name provided, using default: {client_name}")
            
            # AWS WA Tool integration is always enabled - every assessment creates a workload and generates official report
            create_wa_workload = True
            
            # Log for debugging
            logger.info(f"WA Tool integration always enabled - generate_report: {generate_report}, client_name: {client_name}")
            
            # Process in background task
            async def process():
                try:
                    # Use AG-UI orchestrator wrapper which handles event emission
                    result = await agui_orchestrator.process_transcript_with_agui(
                        transcript=transcript,
                        session_id=thread_id,
                        generate_report=generate_report,
                        client_name=client_name,
                    )
                    
                    # Store results for later retrieval via API endpoints
                    session_results[thread_id] = result
                    # Persist to disk for survival across restarts
                    _save_pipeline_results(thread_id, result)
                    # Persist to DynamoDB when dynamodb backend is active
                    try:
                        _orch = get_review_orchestrator()
                        if _orch and hasattr(_orch.storage, 'save_pipeline_results'):
                            _orch.storage.save_pipeline_results(thread_id, result)
                    except Exception as _ddb_err:
                        logger.warning(f"Failed to save pipeline results to DynamoDB storage: {_ddb_err}")
                    # Persist transcript to S3 when dynamodb backend is active
                    try:
                        _orch = get_review_orchestrator()
                        if _orch and hasattr(_orch.storage, 'save_transcript') and transcript:
                            _orch.storage.save_transcript(thread_id, transcript)
                    except Exception as _tx_err:
                        logger.warning(f"Failed to save transcript to DynamoDB storage: {_tx_err}")

                    # Update report state in session_states if report was generated
                    if result and isinstance(result, dict):
                        steps = result.get("steps", {})
                        
                        # Check for report file path
                        report_path = None
                        if "report" in steps:
                            report_step = steps["report"]
                            if isinstance(report_step, dict):
                                report_path = report_step.get("file_path") or report_step.get("report_path")
                        
                        # Check WA Tool report if no regular report
                        if not report_path and "wa_workload" in steps:
                            wa_step = steps["wa_workload"]
                            if isinstance(wa_step, dict):
                                report_path = wa_step.get("report_file")
                        
                        # Update state if report found
                        if report_path and thread_id in session_states:
                            state = session_states[thread_id]
                            state.report.generated = True
                            state.report.file_path = report_path
                            state.report.generated_at = datetime.utcnow().isoformat() + "Z"
                            logger.info(f"Updated session state with report path: {report_path}")
                    
                    # State updates are now handled in orchestrator_integration.py
                    # before the final state snapshot is emitted
                    # This ensures the state is updated before the snapshot is sent
                    logger.info(f"Processing completed with status: {result.get('status', 'unknown')}")
                    
                    # Save session to storage when assessment completes with summary data
                    try:
                        logger.info(f"Attempting to save session {thread_id} to storage with summary...")
                        review_orch = get_review_orchestrator()
                        logger.info(f"ReviewOrchestrator: {review_orch}, Storage: {review_orch.storage if review_orch else None}")
                        if review_orch and review_orch.storage:
                            # Extract assessment summary from results
                            steps = result.get("steps", {}) if result else {}
                            
                            # Get assessment name (from client_name or generate default)
                            assessment_name = client_name or f"Assessment {thread_id[:8]}"
                            
                            # Get scores
                            overall_score = 0.0
                            if "scoring" in steps:
                                scoring_result = steps["scoring"]
                                if isinstance(scoring_result, dict):
                                    scores = scoring_result.get("scores", {})
                                    if isinstance(scores, dict):
                                        overall_score = scores.get("overall_score", 0.0)
                            
                            # Get workload ID if available
                            workload_id = None
                            if "wa_workload" in steps:
                                wa_step = steps["wa_workload"]
                                if isinstance(wa_step, dict):
                                    workload_id = wa_step.get("workload_id")
                            
                            # Get report file path
                            report_file = None
                            if "wa_workload" in steps:
                                wa_step = steps["wa_workload"]
                                if isinstance(wa_step, dict):
                                    report_file = wa_step.get("report_file")
                            
                            # Check if session exists in ReviewOrchestrator
                            session = review_orch.get_session(thread_id)
                            logger.info(f"Session lookup result: {session is not None}")
                            if session:
                                # Update session status based on result
                                status = result.get('status', 'unknown') if result else 'unknown'
                                if status in ('completed', 'completed_with_errors'):
                                    session.status = "COMPLETED"
                                elif status == 'error':
                                    session.status = "ERROR"
                                else:
                                    session.status = "IN_PROGRESS"
                                
                                # Add assessment summary to session data
                                session_dict = session.to_dict()
                                session_dict["assessment_summary"] = {
                                    "assessment_name": assessment_name,
                                    "client_name": client_name,
                                    "overall_score": overall_score,
                                    "workload_id": workload_id,
                                    "report_file": report_file,
                                    "created_at": session_dict.get("created_at", datetime.utcnow().isoformat()),
                                    "updated_at": datetime.utcnow().isoformat(),
                                }
                                
                                # Save to storage
                                review_orch.storage.save_session(session_dict)
                                logger.info(f"Session {thread_id} saved to storage with summary: {assessment_name}, score: {overall_score}")
                                
                                # Also update session_states if it exists
                                if thread_id in session_states:
                                    # Map ReviewOrchestrator status to SessionStatus
                                    status_map = {
                                        "COMPLETED": SessionStatus.FINALIZED.value,
                                        "ERROR": SessionStatus.ERROR.value,
                                        "IN_PROGRESS": SessionStatus.PROCESSING.value,
                                    }
                                    session_states[thread_id].session.status = status_map.get(session.status, session.status.lower())
                                    session_states[thread_id].session.updated_at = datetime.utcnow().isoformat() + "Z"
                            else:
                                # Create a new session entry if it doesn't exist
                                # This happens when assessment completes without review workflow
                                from wafr.agents.review_orchestrator import ReviewSession
                                
                                status = result.get('status', 'unknown') if result else 'unknown'
                                session_status = "COMPLETED" if status in ('completed', 'completed_with_errors') else "ERROR" if status == 'error' else "IN_PROGRESS"
                                
                                new_session = ReviewSession(
                                    session_id=thread_id,
                                    created_at=datetime.utcnow(),
                                    items=[],
                                    transcript_answers_count=0,
                                )
                                new_session.status = session_status
                                
                                # Add assessment summary
                                session_dict = new_session.to_dict()
                                session_dict["assessment_summary"] = {
                                    "assessment_name": assessment_name,
                                    "client_name": client_name,
                                    "overall_score": overall_score,
                                    "workload_id": workload_id,
                                    "report_file": report_file,
                                    "created_at": session_dict.get("created_at", datetime.utcnow().isoformat()),
                                    "updated_at": datetime.utcnow().isoformat(),
                                }
                                
                                review_orch.sessions[thread_id] = new_session
                                review_orch.storage.save_session(session_dict)
                                logger.info(f"Created and saved new session {thread_id} to storage with summary: {assessment_name}, score: {overall_score}")
                                
                                # Also update session_states if it exists
                                if thread_id in session_states:
                                    # Map ReviewOrchestrator status to SessionStatus
                                    status_map = {
                                        "COMPLETED": SessionStatus.FINALIZED.value,
                                        "ERROR": SessionStatus.ERROR.value,
                                        "IN_PROGRESS": SessionStatus.PROCESSING.value,
                                    }
                                    session_states[thread_id].session.status = status_map.get(session_status, session_status.lower())
                                    session_states[thread_id].session.updated_at = datetime.utcnow().isoformat() + "Z"
                            
                    except Exception as save_error:
                        logger.error(f"Failed to save session {thread_id} to storage: {save_error}", exc_info=True)
                        import traceback
                        logger.error(f"Full traceback: {traceback.format_exc()}")
                        
                except Exception as e:
                    logger.error(f"Processing error: {e}", exc_info=True)
                    import traceback
                    error_trace = traceback.format_exc()
                    logger.error(f"Full traceback: {error_trace}")
                    
                    try:
                        await emitter.run_error(str(e), code="PROCESSING_ERROR")
                    except Exception as emit_error:
                        logger.error(f"Failed to emit error event: {emit_error}")
                    
                    # Store error in results for debugging
                    session_results[thread_id] = {
                        "status": "error",
                        "error": str(e),
                        "error_trace": error_trace,
                    }
            
            # Start processing task
            asyncio.create_task(process())

            # Stream events (emitter has built-in 30s heartbeat for keep-alive)
            async for event_data in emitter.stream_events():
                yield event_data

        except Exception as e:
            logger.error(f"Event generation error: {e}", exc_info=True)
            yield f"data: {{'type': 'ERROR', 'message': '{str(e)}'}}\n\n"
        finally:
            # Cleanup
            if thread_id in active_sessions:
                del active_sessions[thread_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/api/wafr/process-file")
@limiter.limit("10/minute")
async def process_file(
    request: Request,
    body: ProcessFileRequest,
    background_tasks: BackgroundTasks,
    claims: dict = Depends(require_team_role),
):
    """
    Process file with AG-UI event streaming.

    Returns SSE stream of events.
    """
    # Per-endpoint audit: log request body
    background_tasks.add_task(
        write_audit_entry,
        user_id=claims.get("sub", "unknown"),
        session_id=body.thread_id,
        action_type="process_file",
        http_method="POST",
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
        request_body=body.model_dump(),
    )

    thread_id = body.thread_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    # Create event emitter
    emitter = WAFREventEmitter(thread_id=thread_id, run_id=run_id)
    active_sessions[thread_id] = emitter
    session_states[thread_id] = emitter.state
    
    async def event_generator():
        """Generate SSE events."""
        try:
            from wafr.agents.orchestrator import create_orchestrator
            
            orchestrator = create_orchestrator()
            
            await emitter.run_started()
            await emitter.step_started("file_processing")

            # Read file and process as transcript
            try:
                import os
                file_path = body.file_path
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"File not found: {file_path}")

                with open(file_path, "r", encoding="utf-8") as f:
                    transcript_text = f.read()

                if not transcript_text.strip():
                    raise ValueError(f"File is empty: {file_path}")

                result = orchestrator.process_transcript(
                    transcript=transcript_text,
                    session_id=thread_id,
                    generate_report=body.generate_report,
                )
                
                await emitter.step_finished("file_processing", {
                    "status": result.get("status", "unknown")
                })
                
                if result.get("status") == "completed":
                    await emitter.state_snapshot()
                    await emitter.run_finished()
                else:
                    await emitter.run_error(
                        result.get("error", "Unknown error"),
                        code="PROCESSING_ERROR"
                    )
                    
            except Exception as e:
                await emitter.run_error(str(e), code="PROCESSING_ERROR")
            
            async for event_data in emitter.stream_events():
                yield event_data
                
        except Exception as e:
            logger.error(f"File processing error: {e}", exc_info=True)
            yield f"data: {{'type': 'ERROR', 'message': '{str(e)}'}}\n\n"
        finally:
            if thread_id in active_sessions:
                del active_sessions[thread_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# State Endpoints
# =============================================================================

@app.get("/api/wafr/session/{session_id}/state", response_model=StateResponse)
async def get_session_state(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """Get current state for a session."""
    if session_id not in session_states:
        raise HTTPException(status_code=404, detail="Session not found")
    
    state = session_states[session_id]
    
    return StateResponse(
        session_id=session_id,
        state=state.to_snapshot(),
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/api/wafr/sessions")
async def list_sessions(
    req: Request,
    claims: dict = Depends(verify_token),
):
    """
    List all sessions with assessment summaries for dashboard display.
    Returns data formatted for frontend dashboard showing recent assessments.
    """
    sessions_dict = {}
    
    # Load sessions from in-memory state
    for session_id, state in session_states.items():
        # Get assessment summary from session_results if available
        summary = {}
        _ensure_session_results(session_id)
        if session_id in session_results:
            result = session_results[session_id]
            steps = result.get("steps", {}) if result else {}
            
            # Extract summary data
            if "scoring" in steps:
                scoring_result = steps["scoring"]
                if isinstance(scoring_result, dict):
                    scores = scoring_result.get("scores", {})
                    if isinstance(scores, dict):
                        summary["overall_score"] = scores.get("overall_score", 0.0)
            
            if "wa_workload" in steps:
                wa_step = steps["wa_workload"]
                if isinstance(wa_step, dict):
                    summary["workload_id"] = wa_step.get("workload_id")
                    summary["report_file"] = wa_step.get("report_file")
        
        sessions_dict[session_id] = {
            "session_id": session_id,
            "assessment_name": summary.get("assessment_name", f"Assessment {session_id[:8]}"),
            "status": state.session.status.upper() if hasattr(state.session.status, 'upper') else str(state.session.status).upper(),
            "current_step": state.pipeline.current_step,
            "progress": state.pipeline.progress_percentage,
            "overall_score": summary.get("overall_score", 0.0),
            "created_at": state.session.started_at,
            "updated_at": state.session.updated_at,
        }
    
    # Load sessions from storage (includes assessment summaries)
    try:
        review_orch = get_review_orchestrator()
        if review_orch and review_orch.storage:
            stored_sessions = review_orch.storage.list_sessions(limit=100)
            for stored_session in stored_sessions:
                session_id = stored_session.get("session_id")
                if session_id:
                    # Get assessment summary from stored session
                    summary = stored_session.get("assessment_summary", {})
                    
                    session_data = {
                        "session_id": session_id,
                        "assessment_name": summary.get("assessment_name", f"Assessment {session_id[:8]}"),
                        "status": stored_session.get("status", "unknown").upper(),
                        "current_step": "",
                        "progress": 100.0 if stored_session.get("status") == "COMPLETED" else 0.0,
                        "overall_score": summary.get("overall_score", 0.0),
                        "client_name": summary.get("client_name"),
                        "workload_id": summary.get("workload_id"),
                        "report_file": summary.get("report_file"),
                        "created_at": stored_session.get("created_at") or summary.get("created_at"),
                        "updated_at": stored_session.get("updated_at") or stored_session.get("created_at") or summary.get("updated_at"),
                    }
                    
                    # Only add if not already in memory (memory takes precedence for active sessions)
                    if session_id not in sessions_dict:
                        sessions_dict[session_id] = session_data
                    else:
                        # Update with storage data if available and more recent
                        stored_updated = session_data.get("updated_at", "")
                        if stored_updated and stored_updated > sessions_dict[session_id].get("updated_at", ""):
                            sessions_dict[session_id].update(session_data)
    except Exception as e:
        logger.warning(f"Failed to load sessions from storage: {e}", exc_info=True)
    
    # Convert to list and sort by updated_at descending
    sessions_list = list(sessions_dict.values())
    sessions_list.sort(
        key=lambda s: s.get("updated_at") or s.get("created_at") or "",
        reverse=True
    )
    
    # Calculate dashboard metrics
    total_assessments = len(sessions_list)
    completed = len([s for s in sessions_list if s.get("status") == "COMPLETED"])
    in_progress = len([s for s in sessions_list if s.get("status") in ("IN_PROGRESS", "PROCESSING")])
    avg_score = sum([s.get("overall_score", 0.0) for s in sessions_list if s.get("status") == "COMPLETED"]) / completed if completed > 0 else 0.0
    
    return {
        "sessions": sessions_list,
        "count": total_assessments,
        "metrics": {
            "total_assessments": total_assessments,
            "completed": completed,
            "in_progress": in_progress,
            "avg_score": round(avg_score, 1),
        },
    }


@app.get("/api/wafr/session/{session_id}/details")
async def get_session_details(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """
    Get full session details for reopening a prior session.
    Returns complete session data including assessment summary, results, and state.
    """
    session_data = {
        "session_id": session_id,
        "found": False,
    }
    
    # Try to load from in-memory state first
    if session_id in session_states:
        state = session_states[session_id]
        session_data.update({
            "found": True,
            "state": state.to_snapshot(),
            "source": "memory",
        })
    
    # Try to load from session_results (with disk fallback)
    _ensure_session_results(session_id)
    if session_id in session_results:
        result = session_results[session_id]
        session_data.update({
            "found": True,
            "results": result,
            "source": "memory",
        })
    
    # Try to load from storage
    try:
        review_orch = get_review_orchestrator()
        if review_orch and review_orch.storage:
            stored_session = review_orch.storage.load_session(session_id)
            if stored_session:
                session_data.update({
                    "found": True,
                    "session": stored_session,
                    "assessment_summary": stored_session.get("assessment_summary", {}),
                    "source": "storage",
                })
    except Exception as e:
        logger.warning(f"Failed to load session from storage: {e}", exc_info=True)
    
    if not session_data.get("found"):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    return session_data


# =============================================================================
# Review Endpoints
# =============================================================================

@app.post("/api/wafr/review/{session_id}/decision")
@limiter.limit("60/minute")
async def submit_review_decision(
    session_id: str,
    body: ReviewDecisionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    claims: dict = Depends(verify_token),
):
    """
    Submit review decision for an item.

    Emits review decision event if session has active emitter.
    """
    # Per-endpoint audit: log request body
    background_tasks.add_task(
        write_audit_entry,
        user_id=claims.get("sub", "unknown"),
        session_id=session_id,
        action_type="review_decision",
        http_method="POST",
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
        request_body=body.model_dump(),
    )

    try:
        # Import here to avoid circular imports
        from wafr.models.review_item import ReviewDecision

        # Get review orchestrator with storage
        review_orch = get_review_orchestrator()

        # Map string decision to enum
        decision_map = {
            "APPROVE": ReviewDecision.APPROVE,
            "MODIFY": ReviewDecision.MODIFY,
            "REJECT": ReviewDecision.REJECT,
        }
        decision_enum = decision_map.get(body.decision.upper())
        if not decision_enum:
            raise HTTPException(status_code=400, detail=f"Invalid decision: {body.decision}")

        # Persist decision via review orchestrator (updates item + writes to DynamoDB)
        updated_item = review_orch.submit_review(
            session_id=session_id,
            review_id=body.review_id,
            decision=decision_enum,
            reviewer_id=body.reviewer_id,
            modified_answer=body.modified_answer,
            feedback=body.feedback,
        )

        # Update in-memory state if available
        if session_id in session_states:
            state = session_states[session_id]
            review_session = review_orch.get_session(session_id)
            if review_session:
                pending = sum(1 for i in review_session.items if i.status.value == "PENDING")
                approved = sum(1 for i in review_session.items if i.status.value == "APPROVED")
                modified = sum(1 for i in review_session.items if i.status.value == "MODIFIED")
                rejected = sum(1 for i in review_session.items if i.status.value == "REJECTED")
                state.review.pending_count = pending
                state.review.approved_count = approved
                state.review.modified_count = modified
                state.review.rejected_count = rejected

        # Create decision data for SSE event
        decision_data = ReviewDecisionData(
            review_id=body.review_id,
            question_id=updated_item.question_id,
            decision=body.decision,
            reviewer_id=body.reviewer_id,
            modified_answer=body.modified_answer,
            feedback=body.feedback,
        )

        # Emit event if session has emitter
        if session_id in active_sessions:
            emitter = active_sessions[session_id]
            await emitter.review_decision(decision_data)

        return {
            "status": "success",
            "review_id": body.review_id,
            "decision": body.decision,
            "new_status": updated_item.status.value,
            "session_id": session_id,
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Review decision error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/wafr/review/{session_id}/batch-approve")
@limiter.limit("60/minute")
async def batch_approve(
    session_id: str,
    body: BatchApproveRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    claims: dict = Depends(verify_token),
):
    """
    Batch approve multiple review items.

    Emits batch approval event if session has active emitter.
    """
    # Per-endpoint audit: log request body
    background_tasks.add_task(
        write_audit_entry,
        user_id=claims.get("sub", "unknown"),
        session_id=session_id,
        action_type="batch_approve",
        http_method="POST",
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
        request_body=body.model_dump(),
    )

    try:
        from wafr.models.review_item import ReviewDecision

        review_orch = get_review_orchestrator()
        approved_count = 0

        # Persist each approval via review orchestrator
        for review_id in body.review_ids:
            try:
                review_orch.submit_review(
                    session_id=session_id,
                    review_id=review_id,
                    decision=ReviewDecision.APPROVE,
                    reviewer_id=body.reviewer_id,
                )
                approved_count += 1
            except ValueError as e:
                logger.warning(f"Batch approve skip {review_id}: {e}")

        # Calculate remaining from actual session state
        review_session = review_orch.get_session(session_id)
        remaining_count = 0
        if review_session:
            remaining_count = sum(1 for i in review_session.items if i.status.value == "PENDING")

        # Update in-memory state
        if session_id in session_states and review_session:
            state = session_states[session_id]
            pending = sum(1 for i in review_session.items if i.status.value == "PENDING")
            approved_total = sum(1 for i in review_session.items if i.status.value == "APPROVED")
            modified = sum(1 for i in review_session.items if i.status.value == "MODIFIED")
            rejected = sum(1 for i in review_session.items if i.status.value == "REJECTED")
            state.review.pending_count = pending
            state.review.approved_count = approved_total
            state.review.modified_count = modified
            state.review.rejected_count = rejected

        # Emit event if session has emitter
        if session_id in active_sessions:
            emitter = active_sessions[session_id]
            await emitter.batch_approve_completed(
                session_id=session_id,
                approved_count=approved_count,
                remaining_count=remaining_count,
            )

        return {
            "status": "success",
            "approved_count": approved_count,
            "remaining_count": remaining_count,
            "session_id": session_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch approve error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/wafr/review/{session_id}/finalize")
@limiter.limit("60/minute")
async def finalize_review_session(
    session_id: str,
    body: FinalizeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    claims: dict = Depends(verify_token),
):
    """
    Finalize review session.

    Validates requirements and emits finalization event.
    """
    # Per-endpoint audit: log request body
    background_tasks.add_task(
        write_audit_entry,
        user_id=claims.get("sub", "unknown"),
        session_id=session_id,
        action_type="finalize_review",
        http_method="POST",
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
        request_body=body.model_dump(),
    )

    try:
        # Validate session exists in memory or storage
        review_orch = get_review_orchestrator()
        review_session = review_orch.get_session(session_id)

        if session_id not in session_states and not review_session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Get pending count from review orchestrator (source of truth)
        pending_count = 0
        if review_session:
            pending_count = sum(1 for i in review_session.items if i.status.value == "PENDING")

        state = session_states.get(session_id)

        # Check if can finalize
        if pending_count > 0:
            authenticity = state.scores.authenticity_score if state else 0.0
            validation_status = ValidationStatus(
                can_finalize=False,
                issues=[f"{pending_count} items still pending review"],
                authenticity_score=authenticity,
                pending_count=pending_count,
            )
            
            if session_id in active_sessions:
                await active_sessions[session_id].validation_status(validation_status)
            
            return {
                "status": "validation_failed",
                "can_finalize": False,
                "issues": validation_status.issues,
            }
        
        # Get counts from review orchestrator (source of truth)
        total_items = len(review_session.items) if review_session else 0
        approved = sum(1 for i in review_session.items if i.status.value == "APPROVED") if review_session else 0
        modified = sum(1 for i in review_session.items if i.status.value == "MODIFIED") if review_session else 0
        rejected = sum(1 for i in review_session.items if i.status.value == "REJECTED") if review_session else 0
        authenticity_score = state.scores.authenticity_score if state else 0.0

        # Save validation record to DynamoDB
        if review_orch.storage:
            try:
                validation_record = {
                    "session_id": session_id,
                    "authenticity_score": authenticity_score,
                    "total_items": total_items,
                    "approved": approved,
                    "modified": modified,
                    "rejected": rejected,
                }
                review_orch.storage.save_validation_record(validation_record)
                logger.info(f"Validation record saved for {session_id}")
            except Exception as e:
                logger.error(f"Failed to save validation record: {e}", exc_info=True)

        # Emit finalization event
        if session_id in active_sessions:
            await active_sessions[session_id].session_finalized(
                session_id=session_id,
                authenticity_score=authenticity_score,
                total_items=total_items,
                approved=approved,
                modified=modified,
            )

        # Update in-memory state
        if state:
            state.session.status = SessionStatus.FINALIZED.value
            state.review.pending_count = 0
            state.review.approved_count = approved
            state.review.modified_count = modified
            state.review.rejected_count = rejected

        # ------------------------------------------------------------------
        # CRITICAL: Merge validated answers into session_results so every
        # data endpoint (questions, pillars, report download) reflects
        # the human-reviewed content instead of raw pipeline output.
        # ------------------------------------------------------------------
        validated_answers = review_orch.get_validated_answers(session_id)
        answers_merged = False
        if validated_answers:
            answers_merged = _merge_validated_answers_into_results(session_id, validated_answers)
            logger.info(f"Validated answers merged: {answers_merged} ({len(validated_answers)} answers)")

            # Kick off background WA Tool report regeneration (best-effort)
            if modified > 0:
                background_tasks.add_task(_regenerate_wa_report, session_id, validated_answers)
                logger.info(f"Queued WA report regeneration for {session_id} ({modified} modified answers)")

        return {
            "status": "success",
            "session_id": session_id,
            "authenticity_score": authenticity_score,
            "summary": {
                "total_items": total_items,
                "approved": approved,
                "modified": modified,
                "rejected": rejected,
            },
            "review_applied": answers_merged,
            "report_regenerating": modified > 0,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Finalize error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Review Items Endpoints (CRITICAL - P0)
# =============================================================================

@app.get("/api/wafr/review/{session_id}/items")
async def get_review_items(
    session_id: str,
    req: Request,
    status: Optional[str] = None,
    pillar: Optional[str] = None,
    confidence: Optional[str] = None,
    claims: dict = Depends(verify_token),
):
    """
    Get review items for a session.
    
    Query Parameters:
    - status: Filter by status (pending, approved, modified, rejected)
    - pillar: Filter by pillar (e.g., Security, Reliability)
    - confidence: Filter by confidence (high, medium, low)
    """
    try:
        from wafr.models.synthesized_answer import SynthesizedAnswer
        
        # Get review orchestrator with storage
        review_orch = get_review_orchestrator()
        review_session = review_orch.get_session(session_id)

        # If review session doesn't exist or was saved with 0 items, try to (re)create from session_results
        if not review_session or len(review_session.items) == 0:
            if not _ensure_session_results(session_id):
                logger.warning(f"Session {session_id} not found in session_results or on disk")
                raise HTTPException(status_code=404, detail="Review session not found")
            
            results = session_results[session_id]
            steps = results.get("steps", {})
            
            logger.info(f"Attempting to create review session from session_results. Steps: {list(steps.keys()) if steps else 'None'}")
            
            # Try multiple sources for answers - handle None values
            answer_synthesis_step = steps.get("answer_synthesis")
            if answer_synthesis_step is None:
                logger.warning(f"answer_synthesis step is None")
                synthesized_answers = []
            elif isinstance(answer_synthesis_step, dict):
                synthesized_answers = answer_synthesis_step.get("synthesized_answers", [])
            else:
                logger.warning(f"answer_synthesis step is unexpected type: {type(answer_synthesis_step)}")
                synthesized_answers = []
            
            confidence_step = steps.get("confidence")
            if confidence_step is None:
                validated_answers = []
            elif isinstance(confidence_step, dict):
                validated_answers = confidence_step.get("validated_answers", [])
            else:
                validated_answers = []
            
            auto_populate_step = steps.get("auto_populate")
            if auto_populate_step is None:
                auto_populate_answers = []
            elif isinstance(auto_populate_step, dict):
                auto_populate_answers = auto_populate_step.get("all_answers", [])
            else:
                auto_populate_answers = []
            
            # Use auto_populate if available, otherwise use synthesized
            source_answers = auto_populate_answers if auto_populate_answers else synthesized_answers
            
            logger.info(f"Found {len(synthesized_answers)} synthesized, {len(validated_answers)} validated, {len(auto_populate_answers)} auto_populate answers")
            
            # Helper functions to handle different answer formats
            def get_answer_content(answer_dict: dict) -> str:
                """Extract answer content from different formats."""
                # Try all possible keys, checking for non-empty values
                # Order matters: check most specific first
                for key in ["synthesized_answer", "answer_content", "answer", "response", "generated_answer"]:
                    value = answer_dict.get(key)
                    if value:
                        # Handle both string and other types
                        if isinstance(value, str):
                            # Allow empty strings - they might still be valid for review
                            return value.strip() if value.strip() else ""
                        elif not isinstance(value, str):
                            # Convert non-string to string
                            return str(value).strip()
                # Return empty string - will be handled later
                return ""
            
            def get_confidence(answer_dict: dict) -> float:
                """Extract confidence from different formats."""
                return (
                    answer_dict.get("confidence") or 
                    answer_dict.get("confidence_score") or 
                    0.5
                )
            
            def get_evidence_quotes(answer_dict: dict) -> list:
                """Extract evidence quotes from different formats and normalize to dict format."""
                # Try evidence_quotes first
                evidence_quotes = answer_dict.get("evidence_quotes", [])
                if evidence_quotes:
                    # Normalize: convert strings to dicts, ensure all are dicts
                    normalized = []
                    for eq in evidence_quotes:
                        if isinstance(eq, str):
                            normalized.append({"text": eq, "location": "", "relevance": ""})
                        elif isinstance(eq, dict):
                            normalized.append(eq)
                        else:
                            logger.warning(f"Unexpected evidence_quote type: {type(eq)}, value: {eq}")
                    return normalized
                
                # Try evidence_quote (singular)
                evidence_quote = answer_dict.get("evidence_quote")
                if evidence_quote:
                    if isinstance(evidence_quote, str):
                        return [{"text": evidence_quote, "location": "", "relevance": ""}]
                    elif isinstance(evidence_quote, dict):
                        return [evidence_quote]
                
                # Try evidence (list)
                evidence = answer_dict.get("evidence", [])
                if evidence:
                    if isinstance(evidence, list):
                        normalized = []
                        for ev in evidence:
                            if isinstance(ev, str):
                                normalized.append({"text": ev, "location": "", "relevance": ""})
                            elif isinstance(ev, dict):
                                normalized.append(ev)
                        return normalized
                    elif isinstance(evidence, str):
                        return [{"text": evidence, "location": "", "relevance": ""}]
                
                return []
            
            # Convert to SynthesizedAnswer objects if needed
            all_synthesized = []
            logger.info(f"Processing {len(source_answers)} source answers for review session creation")
            
            for idx, answer in enumerate(source_answers):
                if isinstance(answer, dict):
                    # Handle both auto_populate and synthesized answer formats
                    try:
                        # Get answer content (handles both formats)
                        answer_content = get_answer_content(answer)
                        # Allow empty answers - they might still need review
                        # Only skip if we don't have a question_id
                        
                        # Ensure we have at least question_id
                        question_id = answer.get("question_id", "")
                        if not question_id:
                            logger.warning(f"Answer #{idx} missing question_id. Keys: {list(answer.keys())}")
                            continue
                        
                        # If answer is empty, use a placeholder or construct from other fields
                        if not answer_content:
                            # Try to get question text to create a meaningful placeholder
                            question_text = answer.get("question_text", answer.get("question", ""))
                            if question_text:
                                answer_content = f"[Answer pending for: {question_text[:50]}...]"
                            else:
                                answer_content = "[Answer pending]"
                        
                        # Convert to SynthesizedAnswer format
                        syn_dict = {
                            "question_id": question_id,
                            "pillar": answer.get("pillar", ""),
                            "question_text": answer.get("question_text", answer.get("question", "")),
                            "synthesized_answer": answer_content,
                            "criticality": answer.get("criticality", "MEDIUM"),
                            "confidence": get_confidence(answer),
                            "confidence_justification": answer.get("confidence_justification", ""),
                            "synthesis_method": answer.get("synthesis_method", answer.get("source", "INFERENCE")),
                            "evidence_quotes": get_evidence_quotes(answer),
                            "reasoning_chain": answer.get("reasoning_chain", []),
                            "assumptions": answer.get("assumptions", []),
                            "related_insights": answer.get("related_insights", []),
                            "requires_attention": answer.get("requires_attention", []),
                        }
                        
                        # Use from_dict to properly construct the object
                        syn_answer = SynthesizedAnswer.from_dict(syn_dict)
                        all_synthesized.append(syn_answer)
                        logger.debug(f"Successfully converted answer #{idx} (question_id: {question_id})")
                    except Exception as e:
                        logger.error(f"Could not convert answer to SynthesizedAnswer: {e}", exc_info=True)
                        logger.debug(f"Answer data keys: {list(answer.keys()) if isinstance(answer, dict) else 'not a dict'}")
                        logger.debug(f"Answer data: {answer}")
                        continue
                elif isinstance(answer, SynthesizedAnswer):
                    # Already a SynthesizedAnswer object
                    all_synthesized.append(answer)
                else:
                    logger.warning(f"Unexpected answer type: {type(answer)}")
                    continue
            
            # Get transcript answers count
            transcript_count = len(validated_answers)
            
            # Create review session if we have synthesized answers
            if all_synthesized:
                logger.info(f"Creating review session with {len(all_synthesized)} synthesized answers for {session_id}")
                try:
                    review_session = review_orch.create_review_session(
                        synthesized_answers=all_synthesized,
                        session_id=session_id,
                        transcript_answers_count=transcript_count,
                    )
                    logger.info(f"Successfully created review session for {session_id} with {len(review_session.items)} items")
                except Exception as e:
                    logger.error(f"Error creating review session: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail=f"Failed to create review session: {str(e)}")
            else:
                logger.warning(f"No synthesized answers found for session {session_id}")
                logger.warning(f"  - Source answers count: {len(source_answers)}")
                logger.warning(f"  - Synthesized answers: {len(synthesized_answers)}")
                logger.warning(f"  - Auto-populate answers: {len(auto_populate_answers)}")
                logger.warning(f"  - Available steps: {list(steps.keys())}")
                if source_answers:
                    logger.warning(f"  - First source answer keys: {list(source_answers[0].keys()) if source_answers else 'N/A'}")
                raise HTTPException(status_code=404, detail="No review items available. Assessment may not have completed synthesis step or answers are in unexpected format.")
        
        if not review_session:
            raise HTTPException(status_code=404, detail="Review session not found")
        
        # Filter items
        items = review_session.items
        
        if status:
            status_map = {
                "pending": "PENDING",
                "approved": "APPROVED",
                "modified": "MODIFIED",
                "rejected": "REJECTED",
            }
            items = [i for i in items if i.status.value == status_map.get(status.lower(), status.upper())]
        
        if pillar:
            items = [i for i in items if i.pillar.lower() == pillar.lower()]
        
        if confidence:
            items = [i for i in items if i.synthesized_answer.confidence_level == confidence.upper()]
        
        # Convert to API format
        items_data = []
        for item in items:
            # Extract evidence quotes as list of strings
            evidence_list = []
            if hasattr(item.synthesized_answer, 'evidence_quotes') and item.synthesized_answer.evidence_quotes:
                evidence_list = [
                    f"{eq.text} (from {eq.location})" 
                    for eq in item.synthesized_answer.evidence_quotes
                ]
            elif hasattr(item.synthesized_answer, 'evidence') and item.synthesized_answer.evidence:
                # Fallback for old format
                evidence_list = item.synthesized_answer.evidence if isinstance(item.synthesized_answer.evidence, list) else [item.synthesized_answer.evidence]
            
            # Get confidence level
            confidence_level = "medium"
            if hasattr(item.synthesized_answer, 'confidence_level'):
                confidence_level = item.synthesized_answer.confidence_level
            elif hasattr(item.synthesized_answer, 'confidence'):
                conf = item.synthesized_answer.confidence
                if conf >= 0.8:
                    confidence_level = "high"
                elif conf >= 0.5:
                    confidence_level = "medium"
                else:
                    confidence_level = "low"
            
            item_dict = {
                "review_id": item.review_id,
                "question_id": item.question_id,
                "question_text": item.synthesized_answer.question_text,
                "pillar": item.pillar,
                "criticality": item.criticality,
                "generated_answer": item.synthesized_answer.synthesized_answer,  # Fixed: use synthesized_answer, not answer
                "evidence": evidence_list,  # Fixed: convert evidence_quotes to list of strings
                "confidence_score": item.synthesized_answer.confidence,
                "confidence_level": confidence_level,
                "source": "synthesis" if hasattr(item.synthesized_answer, 'source') else "mapping",
                "status": item.status.value,
                "reviewer_id": item.reviewer_id,
                "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
                "decision": item.decision.value if item.decision else None,
                "modified_answer": item.modified_answer,
                "feedback": item.rejection_feedback,
            }
            items_data.append(item_dict)
        
        # Group by pillar for summary
        by_pillar = {}
        for item in review_session.items:
            pillar = item.pillar
            if pillar not in by_pillar:
                by_pillar[pillar] = {"total": 0, "pending": 0, "approved": 0}
            by_pillar[pillar]["total"] += 1
            if item.status.value == "PENDING":
                by_pillar[pillar]["pending"] += 1
            elif item.status.value == "APPROVED":
                by_pillar[pillar]["approved"] += 1
        
        return {
            "items": items_data,
            "total": len(items_data),
            "filters": {
                "status": status,
                "pillar": pillar,
                "confidence": confidence,
            },
            "by_pillar": by_pillar,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get review items error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/wafr/review/{session_id}/summary")
async def get_review_summary(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """
    Get review progress summary for a session.
    
    Returns summary of review status including counts by status, pillar, etc.
    """
    try:
        # Get review orchestrator with storage
        review_orch = get_review_orchestrator()
        review_session = review_orch.get_session(session_id)

        # If review session doesn't exist or was saved with 0 items, try to (re)create from session_results
        if not review_session or len(review_session.items) == 0:
            if not _ensure_session_results(session_id):
                raise HTTPException(status_code=404, detail="Review session not found")

            # Try to create review session from session_results
            # Use the same logic as get_review_items
            results = session_results[session_id]
            steps = results.get("steps", {})
            
            auto_populate_step = steps.get("auto_populate")
            if auto_populate_step and isinstance(auto_populate_step, dict):
                auto_populate_answers = auto_populate_step.get("all_answers", [])
            else:
                auto_populate_answers = []
            
            answer_synthesis_step = steps.get("answer_synthesis")
            if answer_synthesis_step and isinstance(answer_synthesis_step, dict):
                synthesized_answers = answer_synthesis_step.get("synthesized_answers", [])
            else:
                synthesized_answers = []
            
            source_answers = auto_populate_answers if auto_populate_answers else synthesized_answers
            
            if not source_answers:
                # Return empty summary if no answers available
                return {
                    "session_id": session_id,
                    "status": "empty",
                    "total_items": 0,
                    "pending": 0,
                    "approved": 0,
                    "modified": 0,
                    "rejected": 0,
                    "progress_percentage": 0.0,
                    "by_pillar": {},
                    "can_finalize": False,
                }
            
            # Create review session (simplified - just to get counts)
            # We'll create a minimal review session for summary purposes
            from wafr.models.synthesized_answer import SynthesizedAnswer
            
            # Get review orchestrator with storage
            review_orch = get_review_orchestrator()
            
            def get_answer_content(answer_dict: dict) -> str:
                for key in ["synthesized_answer", "answer_content", "answer", "response"]:
                    value = answer_dict.get(key)
                    if value and isinstance(value, str) and value.strip():
                        return value.strip()
                return "[Answer pending]"
            
            all_synthesized = []
            for answer in source_answers:
                if isinstance(answer, dict):
                    question_id = answer.get("question_id", "")
                    if question_id:
                        answer_content = get_answer_content(answer)
                        if not answer_content:
                            answer_content = "[Answer pending]"
                        
                        syn_dict = {
                            "question_id": question_id,
                            "pillar": answer.get("pillar", ""),
                            "question_text": answer.get("question_text", answer.get("question", "")),
                            "synthesized_answer": answer_content,
                            "confidence": answer.get("confidence", answer.get("confidence_score", 0.5)),
                            "evidence_quotes": answer.get("evidence_quotes", answer.get("evidence_quote", [])),
                        }
                        try:
                            syn_answer = SynthesizedAnswer.from_dict(syn_dict)
                            all_synthesized.append(syn_answer)
                        except:
                            continue
            
            if all_synthesized:
                try:
                    review_session = review_orch.create_review_session(
                        synthesized_answers=all_synthesized,
                        session_id=session_id,
                        transcript_answers_count=0,
                    )
                except:
                    # If creation fails, return empty summary
                    pass
        
        if not review_session:
            return {
                "session_id": session_id,
                "status": "empty",
                "total_items": 0,
                "pending": 0,
                "approved": 0,
                "modified": 0,
                "rejected": 0,
                "progress_percentage": 0.0,
                "by_pillar": {},
                "can_finalize": False,
            }
        
        # Calculate summary
        total_items = len(review_session.items)
        pending = sum(1 for item in review_session.items if item.status.value == "PENDING")
        approved = sum(1 for item in review_session.items if item.status.value == "APPROVED")
        modified = sum(1 for item in review_session.items if item.status.value == "MODIFIED")
        rejected = sum(1 for item in review_session.items if item.status.value == "REJECTED")
        
        progress_percentage = ((approved + modified + rejected) / total_items * 100.0) if total_items > 0 else 0.0
        
        # Group by pillar
        by_pillar = {}
        for item in review_session.items:
            pillar = item.pillar
            if pillar not in by_pillar:
                by_pillar[pillar] = {
                    "total": 0,
                    "pending": 0,
                    "approved": 0,
                    "modified": 0,
                    "rejected": 0,
                }
            by_pillar[pillar]["total"] += 1
            status = item.status.value
            if status == "PENDING":
                by_pillar[pillar]["pending"] += 1
            elif status == "APPROVED":
                by_pillar[pillar]["approved"] += 1
            elif status == "MODIFIED":
                by_pillar[pillar]["modified"] += 1
            elif status == "REJECTED":
                by_pillar[pillar]["rejected"] += 1
        
        # Determine status
        if total_items == 0:
            status = "empty"
        elif pending == 0:
            status = "completed"
        elif approved + modified + rejected > 0:
            status = "in_progress"
        else:
            status = "pending"
        
        return {
            "session_id": session_id,
            "status": status,
            "total_items": total_items,
            "pending": pending,
            "approved": approved,
            "modified": modified,
            "rejected": rejected,
            "progress_percentage": round(progress_percentage, 2),
            "by_pillar": by_pillar,
            "can_finalize": pending == 0 and total_items > 0,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get review summary error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Results Endpoints (P1)
# =============================================================================

# Pillar abbreviation → full name map (shared with report_agent)
PILLAR_ABBREV_TO_FULL = {
    'OPS': 'Operational Excellence',
    'SEC': 'Security',
    'REL': 'Reliability',
    'PERF': 'Performance Efficiency',
    'COST': 'Cost Optimization',
    'SUS': 'Sustainability',
}

# Insight type → severity mapping
_INSIGHT_TYPE_SEVERITY = {
    'risk': 'High',
    'constraint': 'Medium',
    'decision': 'Low',
    'service': 'Low',
    'lens_specific': 'Medium',
}


def _normalize_pillar_name(name: str) -> str:
    """Normalize pillar abbreviations to full names."""
    return PILLAR_ABBREV_TO_FULL.get(name, name)


@app.get("/api/wafr/session/{session_id}/insights")
async def get_insights(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """Get extracted insights for a session."""
    if not _ensure_session_results(session_id):
        raise HTTPException(status_code=404, detail="Session results not found")

    results = session_results[session_id]
    raw_insights = results.get("steps", {}).get("understanding", {}).get("insights", [])

    # Enrich insights with frontend-expected fields
    insights = []
    for raw in raw_insights:
        content = raw.get("content", "")
        insight_type = raw.get("insight_type", "")
        # Title: first sentence or truncated to ~80 chars
        first_sentence = content.split(". ")[0] if ". " in content else content
        title = first_sentence[:80] + ("..." if len(first_sentence) > 80 else "")

        enriched = {
            **raw,
            "title": title,
            "description": content,
            "severity": _INSIGHT_TYPE_SEVERITY.get(insight_type, "Medium"),
            "pillar": _normalize_pillar_name(raw.get("pillar", "General")),
            "recommendation": raw.get("transcript_quote", ""),
        }
        insights.append(enriched)

    return {
        "session_id": session_id,
        "insights": insights,
        "count": len(insights),
    }


@app.get("/api/wafr/session/{session_id}/questions")
async def get_questions(
    session_id: str,
    req: Request,
    pillar: Optional[str] = None,
    claims: dict = Depends(verify_token),
):
    """Get all questions with answers for a session."""
    if not _ensure_session_results(session_id):
        raise HTTPException(status_code=404, detail="Session results not found")
    
    results = session_results[session_id]
    steps = results.get("steps", {})
    
    # Get all answers (includes validated + synthesized)
    all_answers = steps.get("auto_populate", {}).get("all_answers", [])
    if not all_answers:
        # Fallback to validated + synthesized separately
        validated = steps.get("confidence", {}).get("validated_answers", [])
        synthesized = steps.get("answer_synthesis", {}).get("synthesized_answers", [])
        all_answers = validated + synthesized
    
    # Filter by pillar if specified
    if pillar:
        all_answers = [a for a in all_answers if a.get("pillar", "").lower() == pillar.lower()]
    
    # Format questions
    questions = []
    for answer in all_answers:
        question_dict = {
            "question_id": answer.get("question_id", ""),
            "question_text": answer.get("question_text", ""),
            "pillar": _normalize_pillar_name(answer.get("pillar", "")),
            "category": answer.get("category", ""),
            "answer": answer.get("answer_content") or answer.get("synthesized_answer") or answer.get("answer", ""),
            "evidence": answer.get("evidence", []),
            "confidence": answer.get("confidence", 0.0),
            "confidence_level": answer.get("confidence_level", "LOW"),
            "source": answer.get("source", "unknown"),  # "transcript", "mapping", "synthesis"
        }
        questions.append(question_dict)
    
    return {
        "session_id": session_id,
        "questions": questions,
        "count": len(questions),
        "by_pillar": _group_by_pillar(questions),
    }


@app.get("/api/wafr/session/{session_id}/pillars")
async def get_pillars(
    session_id: str,
    req: Request,
    pillar: Optional[str] = None,
    claims: dict = Depends(verify_token),
):
    """Get pillar-level breakdown for a session."""
    if not _ensure_session_results(session_id):
        raise HTTPException(status_code=404, detail="Session results not found")
    
    results = session_results[session_id]
    steps = results.get("steps", {})
    
    # Get scores
    scores = steps.get("scoring", {}).get("scores", {})
    pillar_scores = scores.get("pillar_scores", {})
    pillar_coverage = scores.get("pillar_coverage", {})
    
    # Get questions per pillar
    all_answers = steps.get("auto_populate", {}).get("all_answers", [])
    if not all_answers:
        validated = steps.get("confidence", {}).get("validated_answers", [])
        synthesized = steps.get("answer_synthesis", {}).get("synthesized_answers", [])
        all_answers = validated + synthesized
    
    # Group by pillar (normalize abbreviations to full names)
    by_pillar = {}
    for answer in all_answers:
        pillar_name = _normalize_pillar_name(answer.get("pillar", "Unknown"))
        if pillar_name not in by_pillar:
            by_pillar[pillar_name] = {
                "questions_answered": 0,
                "total_questions": 0,
                "average_confidence": 0.0,
            }
        by_pillar[pillar_name]["questions_answered"] += 1

    # Add scores and coverage (normalize pillar names from scores too)
    for raw_pillar_name, score in pillar_scores.items():
        pillar_name = _normalize_pillar_name(raw_pillar_name)
        if pillar_name not in by_pillar:
            by_pillar[pillar_name] = {
                "questions_answered": 0,
                "total_questions": 0,
                "average_confidence": 0.0,
            }
        # score may be a dict like {"score": 0.72, "num_answers": 10, "avg_composite": 72.0}
        if isinstance(score, dict):
            by_pillar[pillar_name]["score"] = score.get("score", 0.0)
        else:
            by_pillar[pillar_name]["score"] = score

        cov = pillar_coverage.get(raw_pillar_name, 0.0)
        # coverage may be a dict like {"answered": N, "coverage_percentage": N}
        if isinstance(cov, dict):
            by_pillar[pillar_name]["coverage"] = cov.get("coverage_percentage", 0.0) / 100.0
        else:
            by_pillar[pillar_name]["coverage"] = cov

    # Calculate average confidence per pillar
    for pillar_name in by_pillar:
        pillar_answers = [a for a in all_answers if _normalize_pillar_name(a.get("pillar", "")) == pillar_name]
        if pillar_answers:
            avg_conf = sum(a.get("confidence", 0.0) for a in pillar_answers) / len(pillar_answers)
            by_pillar[pillar_name]["average_confidence"] = round(avg_conf, 2)
    
    # Filter if specific pillar requested
    if pillar:
        if pillar.lower() not in [p.lower() for p in by_pillar.keys()]:
            raise HTTPException(status_code=404, detail=f"Pillar '{pillar}' not found")
        pillar_key = next(k for k in by_pillar.keys() if k.lower() == pillar.lower())
        return {
            "session_id": session_id,
            "pillar": pillar_key,
            "details": by_pillar[pillar_key],
        }
    
    return {
        "session_id": session_id,
        "pillars": by_pillar,
        "count": len(by_pillar),
    }


@app.get("/api/wafr/session/{session_id}/gaps")
async def get_gaps(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """Get detected gaps for a session."""
    if not _ensure_session_results(session_id):
        raise HTTPException(status_code=404, detail="Session results not found")

    results = session_results[session_id]
    raw_gaps = results.get("steps", {}).get("gap_detection", {}).get("gaps", [])

    # Enrich gaps with frontend-expected fields
    gaps = []
    for raw in raw_gaps:
        question_data = raw.get("question_data", {})
        best_practices = question_data.get("best_practices", [])
        criticality = raw.get("criticality", "medium")

        # Build description from best practices
        if best_practices:
            description = "Best practices: " + "; ".join(
                bp.get("title", str(bp)) if isinstance(bp, dict) else str(bp)
                for bp in best_practices[:5]
            )
        else:
            description = raw.get("context_hint", "") or ""

        # Build mitigation from best practice recommendations
        mitigation_parts = []
        for bp in best_practices[:5]:
            if isinstance(bp, dict):
                mitigation_parts.append(bp.get("title", bp.get("description", str(bp))))
            else:
                mitigation_parts.append(str(bp))
        mitigation = "; ".join(mitigation_parts) if mitigation_parts else ""

        enriched = {
            **raw,
            "title": raw.get("question_text", ""),
            "description": description,
            "risk_level": criticality.capitalize(),
            "category": question_data.get("pillar_id", ""),
            "mitigation": mitigation,
            "business_impact": f"Priority score: {raw.get('priority_score', 0)}",
            "pillar": _normalize_pillar_name(raw.get("pillar", "")),
        }
        gaps.append(enriched)

    return {
        "session_id": session_id,
        "gaps": gaps,
        "count": len(gaps),
    }


@app.get("/api/wafr/session/{session_id}/debug")
async def debug_session(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """Debug endpoint to inspect session_results structure."""
    if not _ensure_session_results(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    results = session_results[session_id]
    steps = results.get("steps", {})
    
    debug_info = {
        "session_id": session_id,
        "steps_available": list(steps.keys()),
        "answer_synthesis": {
            "exists": "answer_synthesis" in steps,
            "keys": list(steps.get("answer_synthesis", {}).keys()) if "answer_synthesis" in steps else [],
            "synthesized_count": len(steps.get("answer_synthesis", {}).get("synthesized_answers", [])),
            "first_answer_keys": list(steps.get("answer_synthesis", {}).get("synthesized_answers", [{}])[0].keys()) if steps.get("answer_synthesis", {}).get("synthesized_answers") else [],
        },
        "auto_populate": {
            "exists": "auto_populate" in steps,
            "keys": list(steps.get("auto_populate", {}).keys()) if "auto_populate" in steps else [],
            "answers_count": len(steps.get("auto_populate", {}).get("all_answers", [])),
            "first_answer_keys": list(steps.get("auto_populate", {}).get("all_answers", [{}])[0].keys()) if steps.get("auto_populate", {}).get("all_answers") else [],
        },
        "confidence": {
            "exists": "confidence" in steps,
            "validated_count": len(steps.get("confidence", {}).get("validated_answers", [])),
        },
    }
    
    return debug_info


# =============================================================================
# Report Endpoints (CRITICAL - P0)
# =============================================================================

from fastapi.responses import FileResponse

@app.get("/api/wafr/session/{session_id}/report/download")
async def download_report(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """Download PDF report for a session."""
    file_path = None
    logger.info(f"Download report requested for session: {session_id}")
    
    # Try to get report path from session_states first
    if session_id in session_states:
        state = session_states[session_id]
        logger.info(f"Session state found. Report generated: {state.report.generated}, file_path: {state.report.file_path}")
        if state.report.generated and state.report.file_path:
            file_path = state.report.file_path
            logger.info(f"Found report path from session_states: {file_path}")
    
    # Fallback: check session_results (with disk fallback)
    _ensure_session_results(session_id)
    if not file_path and session_id in session_results:
        results = session_results[session_id]
        steps = results.get("steps", {})
        logger.info(f"Checking session_results. Available steps: {list(steps.keys())}")
        
        # Check report step
        if "report" in steps:
            report_step = steps["report"]
            if report_step is None:
                logger.info(f"Report step exists but is None (report generation may have been skipped)")
            elif isinstance(report_step, dict):
                logger.info(f"Report step found: keys: {list(report_step.keys())}")
                file_path = report_step.get("file_path") or report_step.get("report_path") or report_step.get("report_filename")
                if file_path:
                    logger.info(f"Found report path from report step: {file_path}")
            else:
                logger.warning(f"Report step is unexpected type: {type(report_step)}")
        
        # Check WA Tool report
        if not file_path and "wa_workload" in steps:
            wa_step = steps["wa_workload"]
            if wa_step is None:
                logger.info(f"WA workload step exists but is None (WA Tool integration may have been skipped)")
            elif isinstance(wa_step, dict):
                logger.info(f"WA workload step found: keys: {list(wa_step.keys())}")
                file_path = wa_step.get("report_file") or wa_step.get("report_path") or wa_step.get("report_filename")
                if file_path:
                    logger.info(f"Found report path from WA workload step: {file_path}")
            else:
                logger.warning(f"WA workload step is unexpected type: {type(wa_step)}")
    
    if not file_path:
        logger.warning(f"Report not found for session {session_id}. Session in states: {session_id in session_states}, Session in results: {session_id in session_results}")
        raise HTTPException(status_code=404, detail="Report not generated yet. Please finalize the review session first.")
    
    # Check if file exists
    if not os.path.exists(file_path):
        logger.warning(f"Report file not found at path: {file_path}")
        # Try to find report in output/reports directory
        import glob
        report_pattern = f"output/reports/wafr_report_*{session_id}*.pdf"
        matching_reports = glob.glob(report_pattern)
        if matching_reports:
            file_path = matching_reports[0]
            logger.info(f"Found report using pattern search: {file_path}")
        else:
            # Try JSON fallback
            report_pattern_json = f"output/reports/wafr_report_*{session_id}*.json"
            matching_json = glob.glob(report_pattern_json)
            if matching_json:
                file_path = matching_json[0]
                logger.info(f"Found JSON report using pattern search: {file_path}")
            else:
                raise HTTPException(status_code=404, detail=f"Report file not found on disk at: {file_path}")
    
    try:
        logger.info(f"Serving report file: {file_path}")
        media_type = "application/pdf" if file_path.lower().endswith(".pdf") else "application/json"
        download_name = f"wafr_report_{session_id}" + (".pdf" if media_type == "application/pdf" else ".json")
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=download_name,
        )
    except Exception as e:
        logger.error(f"Error serving report file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error serving report: {str(e)}")


@app.get("/api/wafr/session/{session_id}/report/aws/download")
async def download_aws_report(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """
    Download the official AWS WA Tool report for a session.

    This serves the WA Tool generated PDF (if WA integration was enabled).
    """
    file_path = None
    logger.info(f"Download AWS WA Tool report requested for session: {session_id}")

    # Check session_results for WA Tool report path (with disk fallback)
    _ensure_session_results(session_id)
    if session_id in session_results:
        results = session_results[session_id]
        steps = results.get("steps", {})
        logger.info(f"Checking session_results for WA report. Steps: {list(steps.keys())}")

        wa_step = steps.get("wa_workload")
        if wa_step and isinstance(wa_step, dict):
            logger.info(f"WA workload step found: keys: {list(wa_step.keys())}")
            file_path = wa_step.get("report_file") or wa_step.get("report_path") or wa_step.get("report_filename")
            if file_path:
                logger.info(f"Found WA report path: {file_path}")
        else:
            logger.info("WA workload step not found or not a dict when attempting AWS report download.")
    else:
        logger.info(f"Session {session_id} not found in session_results when attempting AWS report download.")

    if not file_path:
        logger.warning(f"WA Tool report not generated or path missing for session {session_id}")
        raise HTTPException(
            status_code=404,
            detail="AWS WA Tool report not generated. AWS integration is always enabled - check logs for errors."
        )

    # Validate file exists
    if not os.path.exists(file_path):
        logger.warning(f"WA report file not found at path: {file_path}")
        raise HTTPException(status_code=404, detail=f"WA report file not found on disk at: {file_path}")

    try:
        logger.info(f"Serving WA report file: {file_path}")
        return FileResponse(
            path=file_path,
            media_type="application/pdf",
            filename=f"wafr_aws_report_{session_id}.pdf",
        )
    except Exception as e:
        logger.error(f"Error serving WA report file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error serving AWS report: {str(e)}")


@app.get("/api/wafr/session/{session_id}/results/download")
async def download_results(
    session_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """Download JSON results for a session."""
    if not _ensure_session_results(session_id):
        raise HTTPException(status_code=404, detail="Session results not found")
    
    results = session_results[session_id]
    
    # Sanitize results to ensure JSON serializable
    import json
    from datetime import datetime
    
    def sanitize_for_json(obj):
        """Recursively sanitize object for JSON serialization."""
        if obj is None:
            return None
        elif isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, dict):
            return {k: sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [sanitize_for_json(item) for item in obj]
        elif isinstance(obj, datetime):
            # Handle datetime objects - ensure ISO format
            if obj.tzinfo is None:
                return obj.isoformat() + "Z"
            return obj.isoformat()
        elif hasattr(obj, 'isoformat'):  # Handle date objects
            return obj.isoformat()
        elif hasattr(obj, '__dict__'):
            # Try to convert object to dict
            try:
                return sanitize_for_json(obj.__dict__)
            except:
                return str(obj)
        else:
            # Fallback to string representation
            try:
                return str(obj)
            except:
                return None
    
    try:
        sanitized_results = sanitize_for_json(results)
        
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=sanitized_results,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="wafr_results_{session_id}.json"'
            },
        )
    except Exception as e:
        logger.error(f"Error serializing results for download: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error serializing results: {str(e)}")


# =============================================================================
# Session Management Endpoints (P2)
# =============================================================================

@app.delete("/api/wafr/session/{session_id}")
@limiter.limit("60/minute")
async def delete_session(
    session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    claims: dict = Depends(require_team_role),
):
    """Delete a session and all its data."""
    # Per-endpoint audit: no body for DELETE, log action only
    background_tasks.add_task(
        write_audit_entry,
        user_id=claims.get("sub", "unknown"),
        session_id=session_id,
        action_type="delete_session",
        http_method="DELETE",
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
        request_body=None,
    )

    deleted = False
    
    if session_id in active_sessions:
        del active_sessions[session_id]
        deleted = True
    
    if session_id in session_states:
        del session_states[session_id]
        deleted = True
    
    if session_id in session_results:
        del session_results[session_id]
        deleted = True
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"status": "success", "session_id": session_id}


@app.post("/api/wafr/session/{session_id}/cancel")
@limiter.limit("60/minute")
async def cancel_session(
    session_id: str,
    request: Request,
    claims: dict = Depends(require_team_role),
):
    """Cancel a running session."""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Mark session as cancelled
    if session_id in session_states:
        session_states[session_id].session.status = "cancelled"
    
    # Note: Actual cancellation would require stopping the orchestrator
    # This is a simplified version that just updates state
    
    return {"status": "cancelled", "session_id": session_id}


# =============================================================================
# Utility Functions
# =============================================================================

def _group_by_pillar(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """Group items by pillar (normalized to full names)."""
    by_pillar = {}
    for item in items:
        pillar = _normalize_pillar_name(item.get("pillar", "Unknown"))
        by_pillar[pillar] = by_pillar.get(pillar, 0) + 1
    return by_pillar


# =============================================================================
# WebSocket Support (Optional)
# =============================================================================

@app.websocket("/ws/wafr/{session_id}")
async def websocket_endpoint(websocket, session_id: str):
    """
    WebSocket endpoint for bidirectional communication.
    
    Alternative to SSE for clients that prefer WebSocket.
    """
    from fastapi import WebSocket, WebSocketDisconnect
    
    await websocket.accept()
    
    # Get or create emitter
    if session_id not in active_sessions:
        emitter = WAFREventEmitter(thread_id=session_id)
        active_sessions[session_id] = emitter
        session_states[session_id] = emitter.state
    else:
        emitter = active_sessions[session_id]
    
    try:
        # Send initial state
        await websocket.send_json({
            "type": "STATE_SNAPSHOT",
            "snapshot": emitter.state.to_snapshot(),
        })
        
        # Listen for events and client messages
        while True:
            try:
                # Check for client messages (non-blocking)
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.1
                )
                
                # Handle client commands
                if data.get("type") == "GET_STATE":
                    await websocket.send_json({
                        "type": "STATE_SNAPSHOT",
                        "snapshot": emitter.state.to_snapshot(),
                    })
                    
            except asyncio.TimeoutError:
                # No client message, check for events
                if not emitter.event_queue.empty():
                    event = await emitter.event_queue.get()
                    await websocket.send_json(event.to_dict())
                elif emitter.is_finished:
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if session_id in active_sessions and active_sessions[session_id].is_finished:
            del active_sessions[session_id]


# =============================================================================
# Router for Integration
# =============================================================================

from fastapi import APIRouter

router = APIRouter(prefix="/api/wafr", tags=["WAFR AG-UI"])

# Copy endpoints to router for integration into existing apps
router.add_api_route("/run", run_wafr_assessment, methods=["POST"])
router.add_api_route("/process-file", process_file, methods=["POST"])
router.add_api_route("/session/{session_id}/state", get_session_state, methods=["GET"])
router.add_api_route("/sessions", list_sessions, methods=["GET"])
router.add_api_route("/review/{session_id}/decision", submit_review_decision, methods=["POST"])
router.add_api_route("/review/{session_id}/batch-approve", batch_approve, methods=["POST"])
router.add_api_route("/review/{session_id}/finalize", finalize_review_session, methods=["POST"])
# New endpoints
router.add_api_route("/review/{session_id}/items", get_review_items, methods=["GET"])
router.add_api_route("/review/{session_id}/summary", get_review_summary, methods=["GET"])
router.add_api_route("/session/{session_id}/insights", get_insights, methods=["GET"])
router.add_api_route("/session/{session_id}/questions", get_questions, methods=["GET"])
router.add_api_route("/session/{session_id}/pillars", get_pillars, methods=["GET"])
router.add_api_route("/session/{session_id}/gaps", get_gaps, methods=["GET"])
router.add_api_route("/session/{session_id}/report/download", download_report, methods=["GET"])
router.add_api_route("/session/{session_id}/report/aws/download", download_aws_report, methods=["GET"])
router.add_api_route("/session/{session_id}/results/download", download_results, methods=["GET"])
router.add_api_route("/session/{session_id}", delete_session, methods=["DELETE"])
router.add_api_route("/session/{session_id}/cancel", cancel_session, methods=["POST"])


# =============================================================================
# ASYNC POLLING ENDPOINTS - For frontends that can't hold long connections
# =============================================================================
# Job store for async polling (in-memory with DynamoDB fallback)
from threading import Lock
import time as _time

_job_store: Dict[str, Dict[str, Any]] = {}
_job_store_lock = Lock()

def _create_job(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new job entry."""
    job = {
        "job_id": job_id,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "payload": payload,
        "result": None,
        "error": None,
        "progress": 0,
        "message": "Job created, waiting to start",
    }
    with _job_store_lock:
        _job_store[job_id] = job
    return job

def _update_job(job_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Update job fields."""
    with _job_store_lock:
        if job_id not in _job_store:
            return None
        _job_store[job_id].update(kwargs)
        _job_store[job_id]["updated_at"] = datetime.utcnow().isoformat() + "Z"
        return _job_store[job_id].copy()

def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job by ID."""
    with _job_store_lock:
        return _job_store.get(job_id, {}).copy() if job_id in _job_store else None


class StartJobRequest(BaseModel):
    """Request to start async job."""

    transcript: str = Field(
        ...,
        max_length=500_000,
        description="Transcript text (max 500,000 characters)",
    )
    generate_report: bool = Field(True, description="Generate PDF report")
    client_name: Optional[str] = Field(
        None, max_length=200, description="Client name"
    )
    options: Optional[Dict[str, Any]] = Field(None, description="Additional options")


@app.post("/start")
@limiter.limit("10/minute")
async def start_async_job(
    request: Request,
    body: StartJobRequest,
    background_tasks: BackgroundTasks,
    claims: dict = Depends(require_team_role),
):
    """
    Start an async WAFR assessment job.
    Returns immediately with job_id for polling.

    Frontend should poll GET /status/{job_id} every 30 seconds.
    """
    # Per-endpoint audit: exclude transcript (large), capture length instead
    audit_body = body.model_dump(exclude={"transcript"})
    audit_body["transcript_length"] = len(body.transcript) if body.transcript else 0
    background_tasks.add_task(
        write_audit_entry,
        user_id=claims.get("sub", "unknown"),
        session_id=None,
        action_type="start_async_job",
        http_method="POST",
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
        request_body=audit_body,
    )

    job_id = f"wafr-job-{uuid.uuid4().hex}-{uuid.uuid4().hex[:8]}"

    payload = {
        "transcript": body.transcript,
        "options": {
            "generate_report": body.generate_report,
            "client_name": body.client_name or "AsyncClient",
            **(body.options or {})
        }
    }
    
    job = _create_job(job_id, payload)
    
    # Start background processing
    background_tasks.add_task(_process_job_async, job_id, payload)
    
    logger.info(f"Started async job: {job_id}")
    
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "pending",
            "message": "Job created, processing started",
            "poll_url": f"/status/{job_id}",
            "poll_interval_seconds": 30,
            "created_at": job["created_at"],
        }
    )


@app.get("/status/{job_id}")
async def get_job_status(
    job_id: str,
    req: Request,
    claims: dict = Depends(verify_token),
):
    """
    Get status of an async job.
    Poll this endpoint every 30 seconds until status is 'completed' or 'error'.
    """
    job = _get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail={
            "error": "Job not found",
            "job_id": job_id,
            "message": "Job may have expired or never existed"
        })
    
    response = {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }
    
    if job["status"] == "completed":
        response["result"] = job.get("result")
        response["processing_time"] = job.get("processing_time", 0)
    
    if job["status"] == "error":
        response["error"] = job.get("error")
        response["error_type"] = job.get("error_type")
    
    return JSONResponse(content=response)


@app.get("/jobs")
async def list_async_jobs(
    req: Request,
    claims: dict = Depends(verify_token),
):
    """List all jobs (for debugging)."""
    with _job_store_lock:
        jobs = [
            {
                "job_id": j["job_id"],
                "status": j["status"],
                "progress": j.get("progress", 0),
                "message": j.get("message", ""),
                "created_at": j.get("created_at"),
                "updated_at": j.get("updated_at"),
            }
            for j in _job_store.values()
        ]
    
    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return JSONResponse(content={"jobs": jobs[:20], "count": len(jobs)})


async def _process_job_async(job_id: str, payload: Dict[str, Any]):
    """Background task to process WAFR job."""
    start_time = _time.time()
    
    try:
        _update_job(job_id, status="processing", message="Starting WAFR analysis", progress=10)
        
        transcript = payload.get("transcript", "")
        if not transcript:
            _update_job(job_id, status="error", error="Missing transcript", progress=100)
            return
        
        _update_job(job_id, message="Initializing orchestrator", progress=20)
        
        # Import orchestrator
        from wafr.ag_ui.orchestrator_integration import create_agui_orchestrator
        
        options = payload.get("options", {})
        generate_report = options.get("generate_report", True)
        client_name = options.get("client_name", "AsyncClient")
        
        _update_job(job_id, message="Processing transcript - this may take 1-3 minutes", progress=30)
        
        # Create orchestrator and process
        agui_orchestrator = create_agui_orchestrator(
            orchestrator=None,
            emitter=None,
            thread_id=job_id,
        )
        
        # Run in executor to not block
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: agui_orchestrator.orchestrator.process_transcript(
                transcript=transcript,
                session_id=job_id,
                generate_report=generate_report,
                client_name=client_name,
            )
        )
        
        processing_time = _time.time() - start_time
        
        # Convert result to JSON-serializable format
        def json_safe(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: json_safe(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [json_safe(i) for i in obj]
            elif hasattr(obj, '__dict__'):
                return json_safe(obj.__dict__)
            else:
                try:
                    json.dumps(obj)
                    return obj
                except:
                    return str(obj)
        
        _update_job(
            job_id,
            status="completed",
            message="WAFR analysis completed successfully",
            progress=100,
            result=json_safe(result),
            processing_time=processing_time,
        )
        
        logger.info(f"Job {job_id} completed in {processing_time:.2f}s")
        
    except Exception as e:
        processing_time = _time.time() - start_time
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        
        _update_job(
            job_id,
            status="error",
            message=f"Processing failed: {str(e)}",
            progress=100,
            error=str(e),
            error_type=type(e).__name__,
        )


# WebSocket router (separate because APIRouter handles websockets differently)
ws_router = APIRouter(tags=["WAFR WebSocket"])

@ws_router.websocket("/ws/wafr/{session_id}")
async def ws_wafr_session(websocket, session_id: str):
    """
    WebSocket endpoint for bidirectional communication.
    Alternative to SSE for clients that prefer WebSocket.
    """
    from fastapi import WebSocket, WebSocketDisconnect
    
    await websocket.accept()
    
    # Get or create emitter
    if session_id not in active_sessions:
        emitter = WAFREventEmitter(thread_id=session_id)
        active_sessions[session_id] = emitter
        session_states[session_id] = emitter.state
    else:
        emitter = active_sessions[session_id]
    
    try:
        # Send initial state
        await websocket.send_json({
            "type": "STATE_SNAPSHOT",
            "snapshot": emitter.state.to_snapshot(),
        })
        
        # Listen for events and client messages
        while True:
            try:
                # Check for client messages (non-blocking)
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.1
                )
                
                # Handle client commands
                if data.get("type") == "GET_STATE":
                    await websocket.send_json({
                        "type": "STATE_SNAPSHOT",
                        "snapshot": emitter.state.to_snapshot(),
                    })
                    
            except asyncio.TimeoutError:
                # No client message, check for events
                if not emitter.event_queue.empty():
                    event = await emitter.event_queue.get()
                    await websocket.send_json(event.to_dict())
                elif emitter.is_finished:
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if session_id in active_sessions and active_sessions[session_id].is_finished:
            del active_sessions[session_id]


# =============================================================================
# Main Entry Point
# =============================================================================

def create_app() -> FastAPI:
    """Create FastAPI application with AG-UI endpoints."""
    return app


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "ag_ui.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

