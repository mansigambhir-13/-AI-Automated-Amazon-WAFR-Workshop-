"""
ValidationRecord data model for final approval records.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional


@dataclass
class ValidationRecord:
    """
    Final validation record for a completed review session.
    
    This represents the approval record after all items have been
    reviewed and the session is ready for report generation.
    """
    # Session Info
    session_id: str
    finalized_at: datetime
    approver_id: str
    
    # Summary
    total_items: int
    approved_count: int
    modified_count: int
    rejected_count: int
    
    # Scores
    authenticity_score: float  # 0.0 - 100.0
    pillar_coverage: Dict[str, float] = field(default_factory=dict)  # Pillar -> coverage %
    
    # Audit
    review_duration_seconds: Optional[int] = None
    revision_attempts: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "finalized_at": self.finalized_at.isoformat(),
            "approver_id": self.approver_id,
            "total_items": self.total_items,
            "approved_count": self.approved_count,
            "modified_count": self.modified_count,
            "rejected_count": self.rejected_count,
            "authenticity_score": self.authenticity_score,
            "pillar_coverage": self.pillar_coverage,
            "review_duration_seconds": self.review_duration_seconds,
            "revision_attempts": self.revision_attempts,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationRecord":
        """Create from dictionary."""
        finalized_at = datetime.fromisoformat(data["finalized_at"])
        
        return cls(
            session_id=data["session_id"],
            finalized_at=finalized_at,
            approver_id=data["approver_id"],
            total_items=data["total_items"],
            approved_count=data["approved_count"],
            modified_count=data["modified_count"],
            rejected_count=data["rejected_count"],
            authenticity_score=data["authenticity_score"],
            pillar_coverage=data.get("pillar_coverage", {}),
            review_duration_seconds=data.get("review_duration_seconds"),
            revision_attempts=data.get("revision_attempts", 0),
        )

