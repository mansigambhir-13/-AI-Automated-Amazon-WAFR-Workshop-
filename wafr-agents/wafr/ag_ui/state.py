"""
AG-UI State Management for WAFR Pipeline.

Provides WAFRState class that tracks the complete state of a WAFR assessment
session, enabling efficient state synchronization with frontend clients via
STATE_SNAPSHOT and STATE_DELTA events.

The state follows AG-UI conventions for state management, supporting:
- Complete snapshots for initial sync
- JSON Patch deltas for incremental updates
- Nested state structure for organized data

Usage:
    state = WAFRState(session_id="session-123")
    
    # Update state
    state.update_step("understanding")
    state.set_insights_count(15)
    
    # Get snapshot for sync
    snapshot = state.to_snapshot()
    
    # Get delta for incremental update
    delta = state.create_delta("/content/insights_count", 15)
"""

from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import json
import copy


# =============================================================================
# State Status Enums
# =============================================================================

class SessionStatus(str, Enum):
    """Status of WAFR session."""
    
    INITIALIZED = "initialized"
    PROCESSING = "processing"
    REVIEW = "review"
    SCORING = "scoring"
    REPORT = "report"
    FINALIZED = "finalized"
    ERROR = "error"


class ReviewQueueStatus(str, Enum):
    """Status of review queue."""
    
    EMPTY = "empty"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# =============================================================================
# JSON Patch Operations
# =============================================================================

class PatchOp(str, Enum):
    """JSON Patch operation types."""
    
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"
    MOVE = "move"
    COPY = "copy"
    TEST = "test"


@dataclass
class JSONPatch:
    """JSON Patch operation for STATE_DELTA."""
    
    op: str
    path: str
    value: Any = None
    from_path: Optional[str] = None  # For move/copy
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {"op": self.op, "path": self.path}
        if self.value is not None:
            result["value"] = self.value
        if self.from_path is not None:
            result["from"] = self.from_path
        return result


# =============================================================================
# Nested State Components
# =============================================================================

@dataclass
class SessionInfo:
    """Session metadata."""
    
    id: str = ""
    status: str = SessionStatus.INITIALIZED.value
    started_at: str = ""
    updated_at: str = ""
    error: Optional[str] = None
    
    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }


@dataclass
class PipelineProgress:
    """Pipeline execution progress."""
    
    current_step: str = ""
    completed_steps: List[str] = field(default_factory=list)
    total_steps: int = 10  # Default WAFR pipeline steps
    
    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage, capped at 100%."""
        if self.total_steps == 0:
            return 0.0
        # Cap at 100% to handle cases where more steps are completed than expected
        progress = round((len(self.completed_steps) / self.total_steps) * 100, 1)
        return min(100.0, progress)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_step": self.current_step,
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "progress_percentage": self.progress_percentage,
        }


@dataclass
class ContentState:
    """Content extraction state."""
    
    transcript_loaded: bool = False
    transcript_length: int = 0
    insights_count: int = 0
    questions_answered: int = 0
    questions_total: int = 0
    gaps_count: int = 0
    synthesized_count: int = 0
    
    @property
    def coverage_percentage(self) -> float:
        """Calculate coverage percentage."""
        if self.questions_total == 0:
            return 0.0
        return round((self.questions_answered / self.questions_total) * 100, 1)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "transcript_loaded": self.transcript_loaded,
            "transcript_length": self.transcript_length,
            "insights_count": self.insights_count,
            "questions_answered": self.questions_answered,
            "questions_total": self.questions_total,
            "gaps_count": self.gaps_count,
            "synthesized_count": self.synthesized_count,
            "coverage_percentage": self.coverage_percentage,
        }


@dataclass
class ReviewState:
    """HITL review state."""
    
    session_id: Optional[str] = None
    status: str = ReviewQueueStatus.EMPTY.value
    pending_count: int = 0
    approved_count: int = 0
    modified_count: int = 0
    rejected_count: int = 0
    
    # Grouped counts
    high_confidence_pending: int = 0
    medium_confidence_pending: int = 0
    low_confidence_pending: int = 0
    
    # By pillar
    by_pillar: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    @property
    def total_reviewed(self) -> int:
        """Total items reviewed."""
        return self.approved_count + self.modified_count + self.rejected_count
    
    @property
    def total_items(self) -> int:
        """Total items in queue."""
        return self.pending_count + self.total_reviewed
    
    @property
    def review_progress(self) -> float:
        """Review progress percentage."""
        if self.total_items == 0:
            return 100.0
        return round((self.total_reviewed / self.total_items) * 100, 1)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "pending_count": self.pending_count,
            "approved_count": self.approved_count,
            "modified_count": self.modified_count,
            "rejected_count": self.rejected_count,
            "total_reviewed": self.total_reviewed,
            "total_items": self.total_items,
            "review_progress": self.review_progress,
            "by_confidence": {
                "high": self.high_confidence_pending,
                "medium": self.medium_confidence_pending,
                "low": self.low_confidence_pending,
            },
            "by_pillar": self.by_pillar,
        }


@dataclass
class ScoreState:
    """Scoring state."""
    
    authenticity_score: float = 0.0
    overall_score: float = 0.0
    pillar_scores: Dict[str, float] = field(default_factory=dict)
    pillar_coverage: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "authenticity_score": self.authenticity_score,
            "overall_score": self.overall_score,
            "pillar_scores": self.pillar_scores,
            "pillar_coverage": self.pillar_coverage,
        }


@dataclass
class ReportState:
    """Report generation state."""
    
    generated: bool = False
    file_path: Optional[str] = None
    format: str = "pdf"
    generated_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated": self.generated,
            "file_path": self.file_path,
            "format": self.format,
            "generated_at": self.generated_at,
        }


# =============================================================================
# Main WAFRState Class
# =============================================================================

@dataclass
class WAFRState:
    """
    Complete state for WAFR assessment session.
    
    Tracks all aspects of a WAFR assessment for AG-UI state synchronization.
    Supports both full snapshots and incremental deltas.
    
    State Structure:
    {
        "session": {...},
        "pipeline": {...},
        "content": {...},
        "review": {...},
        "scores": {...},
        "report": {...}
    }
    """
    
    # Nested state components
    session: SessionInfo = field(default_factory=SessionInfo)
    pipeline: PipelineProgress = field(default_factory=PipelineProgress)
    content: ContentState = field(default_factory=ContentState)
    review: ReviewState = field(default_factory=ReviewState)
    scores: ScoreState = field(default_factory=ScoreState)
    report: ReportState = field(default_factory=ReportState)
    
    # For delta tracking
    _previous_snapshot: Dict[str, Any] = field(default_factory=dict, repr=False)
    
    def __init__(self, session_id: str = ""):
        """Initialize state with session ID."""
        self.session = SessionInfo(id=session_id)
        self.pipeline = PipelineProgress()
        self.content = ContentState()
        self.review = ReviewState()
        self.scores = ScoreState()
        self.report = ReportState()
        self._previous_snapshot = {}
    
    # =========================================================================
    # Snapshot Methods
    # =========================================================================
    
    def to_snapshot(self) -> Dict[str, Any]:
        """
        Convert to complete STATE_SNAPSHOT format.
        
        Returns:
            Complete state dictionary for AG-UI STATE_SNAPSHOT event.
        """
        # Update timestamp
        self.session.updated_at = datetime.utcnow().isoformat()
        
        snapshot = {
            "session": self.session.to_dict(),
            "pipeline": self.pipeline.to_dict(),
            "content": self.content.to_dict(),
            "review": self.review.to_dict(),
            "scores": self.scores.to_dict(),
            "report": self.report.to_dict(),
        }
        
        # Store for delta comparison
        self._previous_snapshot = copy.deepcopy(snapshot)
        
        return snapshot
    
    # =========================================================================
    # Delta Methods
    # =========================================================================
    
    def create_delta(
        self,
        path: str,
        value: Any,
        op: str = PatchOp.REPLACE.value,
    ) -> Dict[str, Any]:
        """
        Create JSON Patch delta for STATE_DELTA event.
        
        Args:
            path: JSON Pointer path (e.g., "/content/insights_count")
            value: New value
            op: Operation type (default: "replace")
        
        Returns:
            JSON Patch operation dictionary.
        """
        return JSONPatch(op=op, path=path, value=value).to_dict()
    
    def create_deltas(self, patches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Create multiple JSON Patch deltas.
        
        Args:
            patches: List of (path, value) or (path, value, op) tuples
        
        Returns:
            List of JSON Patch operations.
        """
        deltas = []
        for patch in patches:
            if len(patch) == 2:
                deltas.append(self.create_delta(patch["path"], patch["value"]))
            else:
                deltas.append(self.create_delta(
                    patch["path"], 
                    patch["value"], 
                    patch.get("op", PatchOp.REPLACE.value)
                ))
        return deltas
    
    # =========================================================================
    # Update Methods
    # =========================================================================
    
    def update_status(self, status: SessionStatus) -> Dict[str, Any]:
        """Update session status and return delta."""
        self.session.status = status.value
        self.session.updated_at = datetime.utcnow().isoformat()
        return self.create_delta("/session/status", status.value)
    
    def update_step(self, step: str) -> List[Dict[str, Any]]:
        """Update current step and return deltas."""
        # Add previous step to completed if not already there
        if self.pipeline.current_step and self.pipeline.current_step not in self.pipeline.completed_steps:
            self.pipeline.completed_steps.append(self.pipeline.current_step)
        
        self.pipeline.current_step = step
        
        return [
            self.create_delta("/pipeline/current_step", step),
            self.create_delta("/pipeline/completed_steps", self.pipeline.completed_steps),
            self.create_delta("/pipeline/progress_percentage", self.pipeline.progress_percentage),
        ]
    
    def complete_step(self, step: str) -> Dict[str, Any]:
        """Mark step as completed and return delta."""
        if step not in self.pipeline.completed_steps:
            self.pipeline.completed_steps.append(step)
        return self.create_delta("/pipeline/completed_steps", self.pipeline.completed_steps)
    
    def set_transcript_loaded(self, length: int) -> List[Dict[str, Any]]:
        """Set transcript loaded and return deltas."""
        self.content.transcript_loaded = True
        self.content.transcript_length = length
        return [
            self.create_delta("/content/transcript_loaded", True),
            self.create_delta("/content/transcript_length", length),
        ]
    
    def set_insights_count(self, count: int) -> Dict[str, Any]:
        """Set insights count and return delta."""
        self.content.insights_count = count
        return self.create_delta("/content/insights_count", count)
    
    def set_questions_stats(
        self,
        answered: int,
        total: int,
        gaps: int,
    ) -> List[Dict[str, Any]]:
        """Set question statistics and return deltas."""
        self.content.questions_answered = answered
        self.content.questions_total = total
        self.content.gaps_count = gaps
        return [
            self.create_delta("/content/questions_answered", answered),
            self.create_delta("/content/questions_total", total),
            self.create_delta("/content/gaps_count", gaps),
            self.create_delta("/content/coverage_percentage", self.content.coverage_percentage),
        ]
    
    def set_synthesized_count(self, count: int) -> Dict[str, Any]:
        """Set synthesized answers count and return delta."""
        self.content.synthesized_count = count
        return self.create_delta("/content/synthesized_count", count)
    
    def update_review_state(
        self,
        session_id: str,
        pending: int,
        approved: int = 0,
        modified: int = 0,
        rejected: int = 0,
    ) -> List[Dict[str, Any]]:
        """Update review state and return deltas."""
        self.review.session_id = session_id
        self.review.pending_count = pending
        self.review.approved_count = approved
        self.review.modified_count = modified
        self.review.rejected_count = rejected
        
        if pending > 0:
            self.review.status = ReviewQueueStatus.PENDING.value
        elif self.review.total_reviewed > 0:
            self.review.status = ReviewQueueStatus.COMPLETED.value
        
        return [
            self.create_delta("/review/session_id", session_id),
            self.create_delta("/review/pending_count", pending),
            self.create_delta("/review/approved_count", approved),
            self.create_delta("/review/modified_count", modified),
            self.create_delta("/review/rejected_count", rejected),
            self.create_delta("/review/status", self.review.status),
            self.create_delta("/review/review_progress", self.review.review_progress),
        ]
    
    def update_review_confidence_counts(
        self,
        high: int,
        medium: int,
        low: int,
    ) -> Dict[str, Any]:
        """Update review confidence counts and return delta."""
        self.review.high_confidence_pending = high
        self.review.medium_confidence_pending = medium
        self.review.low_confidence_pending = low
        return self.create_delta("/review/by_confidence", {
            "high": high,
            "medium": medium,
            "low": low,
        })
    
    def set_authenticity_score(self, score: float) -> Dict[str, Any]:
        """Set authenticity score and return delta."""
        self.scores.authenticity_score = score
        return self.create_delta("/scores/authenticity_score", score)
    
    def set_pillar_scores(self, pillar_scores: Dict[str, float]) -> Dict[str, Any]:
        """Set pillar scores and return delta."""
        self.scores.pillar_scores = pillar_scores
        return self.create_delta("/scores/pillar_scores", pillar_scores)
    
    def set_pillar_coverage(self, coverage: Dict[str, float]) -> Dict[str, Any]:
        """Set pillar coverage and return delta."""
        self.scores.pillar_coverage = coverage
        return self.create_delta("/scores/pillar_coverage", coverage)
    
    def set_report_generated(
        self,
        file_path: str,
        format: str = "pdf",
    ) -> List[Dict[str, Any]]:
        """Set report as generated and return deltas."""
        self.report.generated = True
        self.report.file_path = file_path
        self.report.format = format
        self.report.generated_at = datetime.utcnow().isoformat()
        return [
            self.create_delta("/report/generated", True),
            self.create_delta("/report/file_path", file_path),
            self.create_delta("/report/format", format),
            self.create_delta("/report/generated_at", self.report.generated_at),
        ]
    
    def set_error(self, error: str) -> List[Dict[str, Any]]:
        """Set error state and return deltas."""
        self.session.status = SessionStatus.ERROR.value
        self.session.error = error
        return [
            self.create_delta("/session/status", SessionStatus.ERROR.value),
            self.create_delta("/session/error", error),
        ]
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize state to JSON string."""
        return json.dumps(self.to_snapshot(), indent=indent)
    
    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> 'WAFRState':
        """Create state from snapshot dictionary."""
        state = cls(session_id=snapshot.get("session", {}).get("id", ""))
        
        # Restore session
        if "session" in snapshot:
            state.session = SessionInfo(**snapshot["session"])
        
        # Restore pipeline
        if "pipeline" in snapshot:
            pipeline_data = snapshot["pipeline"].copy()
            pipeline_data.pop("progress_percentage", None)  # Computed property
            state.pipeline = PipelineProgress(**pipeline_data)
        
        # Restore content
        if "content" in snapshot:
            content_data = snapshot["content"].copy()
            content_data.pop("coverage_percentage", None)  # Computed property
            state.content = ContentState(**content_data)
        
        # Restore review
        if "review" in snapshot:
            review_data = snapshot["review"].copy()
            # Remove computed properties
            for key in ["total_reviewed", "total_items", "review_progress"]:
                review_data.pop(key, None)
            # Handle nested by_confidence
            if "by_confidence" in review_data:
                conf = review_data.pop("by_confidence")
                review_data["high_confidence_pending"] = conf.get("high", 0)
                review_data["medium_confidence_pending"] = conf.get("medium", 0)
                review_data["low_confidence_pending"] = conf.get("low", 0)
            state.review = ReviewState(**review_data)
        
        # Restore scores
        if "scores" in snapshot:
            state.scores = ScoreState(**snapshot["scores"])
        
        # Restore report
        if "report" in snapshot:
            state.report = ReportState(**snapshot["report"])
        
        return state

