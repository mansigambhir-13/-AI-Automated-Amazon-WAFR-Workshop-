"""
AG-UI Event Definitions for WAFR HITL Pipeline.

Defines custom event types specific to the WAFR workflow, including:
- HITL review events
- Synthesis progress events
- Pipeline step events
- Validation status events

These events extend the standard AG-UI event types to support
the WAFR-specific Human-in-the-Loop workflow.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json


# =============================================================================
# WAFR Pipeline Steps
# =============================================================================

class WAFRPipelineStep(str, Enum):
    """Pipeline steps in WAFR assessment."""
    
    # Input processing
    PDF_PROCESSING = "pdf_processing"
    TRANSCRIPT_LOADING = "transcript_loading"
    
    # Agent processing
    UNDERSTANDING = "understanding"
    MAPPING = "mapping"
    CONFIDENCE = "confidence"
    GAP_DETECTION = "gap_detection"
    PROMPT_GENERATION = "prompt_generation"
    
    # HITL workflow
    ANSWER_SYNTHESIS = "answer_synthesis"
    HITL_REVIEW = "hitl_review"
    
    # Finalization
    SCORING = "scoring"
    REPORT_GENERATION = "report_generation"
    WA_TOOL_INTEGRATION = "wa_tool_integration"
    
    # Completion
    FINALIZATION = "finalization"


# =============================================================================
# HITL Event Types
# =============================================================================

class HITLEventType(str, Enum):
    """Custom event types for HITL workflow."""
    
    # Review lifecycle
    REVIEW_REQUIRED = "hitl.review_required"
    REVIEW_SESSION_CREATED = "hitl.session_created"
    REVIEW_QUEUE_UPDATE = "hitl.queue_update"
    
    # Individual review actions
    REVIEW_STARTED = "hitl.review_started"
    REVIEW_DECISION = "hitl.decision"
    REVIEW_MODIFIED = "hitl.modified"
    REVIEW_REJECTED = "hitl.rejected"
    
    # Batch operations
    BATCH_APPROVE_STARTED = "hitl.batch_approve_started"
    BATCH_APPROVE_COMPLETED = "hitl.batch_approve_completed"
    
    # Synthesis
    SYNTHESIS_STARTED = "hitl.synthesis_started"
    SYNTHESIS_PROGRESS = "hitl.synthesis_progress"
    SYNTHESIS_COMPLETED = "hitl.synthesis_completed"
    SYNTHESIS_ERROR = "hitl.synthesis_error"
    
    # Re-synthesis (after rejection)
    RESYNTHESIS_STARTED = "hitl.resynthesis_started"
    RESYNTHESIS_COMPLETED = "hitl.resynthesis_completed"
    
    # Validation
    VALIDATION_CHECK = "hitl.validation_check"
    VALIDATION_PASSED = "hitl.validation_passed"
    VALIDATION_FAILED = "hitl.validation_failed"
    
    # Finalization
    SESSION_FINALIZING = "hitl.session_finalizing"
    SESSION_FINALIZED = "hitl.session_finalized"
    
    # Scores
    AUTHENTICITY_SCORE_UPDATE = "hitl.authenticity_score_update"
    PILLAR_COVERAGE_UPDATE = "hitl.pillar_coverage_update"


# =============================================================================
# HITL Event Data Classes
# =============================================================================

@dataclass
class ReviewQueueSummary:
    """Summary of review queue for events."""
    
    total_items: int = 0
    pending_count: int = 0
    approved_count: int = 0
    modified_count: int = 0
    rejected_count: int = 0
    
    # Grouped by confidence
    high_confidence_count: int = 0
    medium_confidence_count: int = 0
    low_confidence_count: int = 0
    
    # Grouped by pillar
    by_pillar: Dict[str, int] = field(default_factory=dict)
    
    # Grouped by criticality
    by_criticality: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for event payload."""
        return {
            "total_items": self.total_items,
            "pending_count": self.pending_count,
            "approved_count": self.approved_count,
            "modified_count": self.modified_count,
            "rejected_count": self.rejected_count,
            "by_confidence": {
                "high": self.high_confidence_count,
                "medium": self.medium_confidence_count,
                "low": self.low_confidence_count,
            },
            "by_pillar": self.by_pillar,
            "by_criticality": self.by_criticality,
        }


@dataclass
class SynthesisProgress:
    """Progress of answer synthesis."""
    
    current: int = 0
    total: int = 0
    question_id: str = ""
    pillar: str = ""
    confidence: float = 0.0
    
    @property
    def percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total == 0:
            return 0.0
        return round((self.current / self.total) * 100, 1)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for event payload."""
        return {
            "current": self.current,
            "total": self.total,
            "percentage": self.percentage,
            "question_id": self.question_id,
            "pillar": self.pillar,
            "confidence": self.confidence,
        }


@dataclass
class ReviewDecisionData:
    """Data for review decision event."""
    
    review_id: str
    question_id: str
    decision: str  # APPROVE, MODIFY, REJECT
    reviewer_id: str
    pillar: str = ""
    criticality: str = ""
    original_confidence: float = 0.0
    modified_answer: Optional[str] = None
    feedback: Optional[str] = None
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for event payload."""
        return {
            "review_id": self.review_id,
            "question_id": self.question_id,
            "decision": self.decision,
            "reviewer_id": self.reviewer_id,
            "pillar": self.pillar,
            "criticality": self.criticality,
            "original_confidence": self.original_confidence,
            "modified_answer": self.modified_answer,
            "feedback": self.feedback,
            "timestamp": self.timestamp,
        }


@dataclass
class ValidationStatus:
    """Validation status for finalization."""
    
    can_finalize: bool = False
    issues: List[str] = field(default_factory=list)
    authenticity_score: float = 0.0
    required_score: float = 70.0
    pending_count: int = 0
    pillar_coverage: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for event payload."""
        return {
            "can_finalize": self.can_finalize,
            "issues": self.issues,
            "authenticity_score": self.authenticity_score,
            "required_score": self.required_score,
            "pending_count": self.pending_count,
            "pillar_coverage": self.pillar_coverage,
        }


# =============================================================================
# HITL Events Factory
# =============================================================================

class HITLEvents:
    """Factory for creating HITL event payloads."""
    
    @staticmethod
    def review_required(
        session_id: str,
        queue_summary: ReviewQueueSummary,
    ) -> Dict[str, Any]:
        """Create REVIEW_REQUIRED event payload."""
        return {
            "event_type": HITLEventType.REVIEW_REQUIRED.value,
            "session_id": session_id,
            "queue_summary": queue_summary.to_dict(),
            "message": f"Human review required for {queue_summary.pending_count} items",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def synthesis_progress(progress: SynthesisProgress) -> Dict[str, Any]:
        """Create SYNTHESIS_PROGRESS event payload."""
        return {
            "event_type": HITLEventType.SYNTHESIS_PROGRESS.value,
            "progress": progress.to_dict(),
            "message": f"Synthesizing {progress.current}/{progress.total}: {progress.question_id}",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def review_decision(decision_data: ReviewDecisionData) -> Dict[str, Any]:
        """Create REVIEW_DECISION event payload."""
        return {
            "event_type": HITLEventType.REVIEW_DECISION.value,
            "decision": decision_data.to_dict(),
            "message": f"Review {decision_data.decision} for {decision_data.question_id}",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def batch_approve_completed(
        session_id: str,
        approved_count: int,
        remaining_count: int,
    ) -> Dict[str, Any]:
        """Create BATCH_APPROVE_COMPLETED event payload."""
        return {
            "event_type": HITLEventType.BATCH_APPROVE_COMPLETED.value,
            "session_id": session_id,
            "approved_count": approved_count,
            "remaining_count": remaining_count,
            "message": f"Batch approved {approved_count} items",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def validation_status(status: ValidationStatus) -> Dict[str, Any]:
        """Create VALIDATION_CHECK event payload."""
        event_type = (
            HITLEventType.VALIDATION_PASSED.value 
            if status.can_finalize 
            else HITLEventType.VALIDATION_FAILED.value
        )
        return {
            "event_type": event_type,
            "status": status.to_dict(),
            "message": (
                "Ready for finalization" 
                if status.can_finalize 
                else f"Cannot finalize: {len(status.issues)} issues"
            ),
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def session_finalized(
        session_id: str,
        authenticity_score: float,
        total_items: int,
        approved: int,
        modified: int,
    ) -> Dict[str, Any]:
        """Create SESSION_FINALIZED event payload."""
        return {
            "event_type": HITLEventType.SESSION_FINALIZED.value,
            "session_id": session_id,
            "authenticity_score": authenticity_score,
            "summary": {
                "total_items": total_items,
                "approved": approved,
                "modified": modified,
            },
            "message": f"Session finalized with {authenticity_score:.1f}% authenticity",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def authenticity_score_update(
        session_id: str,
        score: float,
        breakdown: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create AUTHENTICITY_SCORE_UPDATE event payload."""
        return {
            "event_type": HITLEventType.AUTHENTICITY_SCORE_UPDATE.value,
            "session_id": session_id,
            "authenticity_score": score,
            "breakdown": breakdown,
            "message": f"Authenticity score updated: {score:.1f}%",
            "timestamp": datetime.utcnow().isoformat(),
        }


# =============================================================================
# Utility Functions
# =============================================================================

def create_hitl_event(
    event_type: HITLEventType,
    data: Dict[str, Any],
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a generic HITL event payload.
    
    Args:
        event_type: Type of HITL event
        data: Event-specific data
        message: Optional human-readable message
    
    Returns:
        Event payload dictionary
    """
    return {
        "event_type": event_type.value,
        "data": data,
        "message": message or f"HITL event: {event_type.value}",
        "timestamp": datetime.utcnow().isoformat(),
    }


def parse_hitl_event(event_json: str) -> Dict[str, Any]:
    """
    Parse HITL event from JSON string.
    
    Args:
        event_json: JSON string of event
    
    Returns:
        Parsed event dictionary
    """
    return json.loads(event_json)

