"""
ReviewItem data model for HITL review workflow.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from wafr.models.synthesized_answer import SynthesizedAnswer


class ReviewStatus(str, Enum):
    """Status of a review item."""
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    MODIFIED = "MODIFIED"
    REJECTED = "REJECTED"


class ReviewDecision(str, Enum):
    """Decision made by reviewer."""
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"


@dataclass
class ReviewItem:
    """
    An item in the review queue for human validation.
    
    Represents a synthesized answer that needs human review,
    approval, modification, or rejection.
    """
    # Identity
    review_id: str
    question_id: str
    pillar: str
    criticality: str
    
    # Content
    synthesized_answer: SynthesizedAnswer
    
    # Review State
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    decision: Optional[ReviewDecision] = None
    
    # Modifications
    modified_answer: Optional[str] = None
    rejection_feedback: Optional[str] = None
    revision_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "review_id": self.review_id,
            "question_id": self.question_id,
            "pillar": self.pillar,
            "criticality": self.criticality,
            "synthesized_answer": self.synthesized_answer.to_dict(),
            "status": self.status.value,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "decision": self.decision.value if self.decision else None,
            "modified_answer": self.modified_answer,
            "rejection_feedback": self.rejection_feedback,
            "revision_count": self.revision_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewItem":
        """Create from dictionary."""
        reviewed_at = None
        if data.get("reviewed_at"):
            reviewed_at = datetime.fromisoformat(data["reviewed_at"])
        
        decision = None
        if data.get("decision"):
            decision = ReviewDecision(data["decision"])
        
        status = ReviewStatus(data.get("status", "PENDING"))
        
        synthesized_answer = SynthesizedAnswer.from_dict(
            data["synthesized_answer"]
        )
        
        return cls(
            review_id=data["review_id"],
            question_id=data["question_id"],
            pillar=data.get("pillar", ""),
            criticality=data.get("criticality", "MEDIUM"),
            synthesized_answer=synthesized_answer,
            status=status,
            reviewer_id=data.get("reviewer_id"),
            reviewed_at=reviewed_at,
            decision=decision,
            modified_answer=data.get("modified_answer"),
            rejection_feedback=data.get("rejection_feedback"),
            revision_count=data.get("revision_count", 0),
        )

