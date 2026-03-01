"""
Simplified Review Orchestrator - Confidence-based auto-approval with optional review.

Removes unnecessary complexity while maintaining reliability:
- Auto-approves high confidence answers (>= 0.75)
- Flags low confidence for optional review
- Simple re-synthesis on rejection
- No mandatory review workflow
- No complex validation requirements
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from wafr.agents.config import HITL_AUTO_APPROVE_THRESHOLD, HITL_MAX_RESYNTHESIS_ATTEMPTS
from wafr.models.review_item import ReviewDecision, ReviewItem, ReviewStatus
from wafr.models.synthesized_answer import SynthesizedAnswer

logger = logging.getLogger(__name__)


# =============================================================================
# Simplified Review Session
# =============================================================================

@dataclass
class ReviewSession:
    """Simplified review session - tracks items for optional review."""
    
    session_id: str
    created_at: datetime
    items: List[ReviewItem] = field(default_factory=list)
    status: str = "ACTIVE"  # ACTIVE, COMPLETED
    transcript_answers_count: int = 0
    
    @property
    def auto_approved_count(self) -> int:
        """Count of auto-approved items."""
        return len([i for i in self.items if i.status == ReviewStatus.APPROVED and not i.reviewer_id])
    
    @property
    def reviewed_count(self) -> int:
        """Count of human-reviewed items."""
        return len([i for i in self.items if i.reviewer_id])
    
    @property
    def pending_review_count(self) -> int:
        """Count of items pending optional review."""
        return len([i for i in self.items if i.status == ReviewStatus.PENDING])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
            "transcript_answers_count": self.transcript_answers_count,
            "summary": {
                "total": len(self.items),
                "auto_approved": self.auto_approved_count,
                "reviewed": self.reviewed_count,
                "pending_review": self.pending_review_count,
            },
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewSession":
        """Reconstruct session from dictionary."""
        items = [ReviewItem.from_dict(item) for item in data.get("items", [])]
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        return cls(
            session_id=data["session_id"],
            created_at=created_at,
            items=items,
            status=data.get("status", "ACTIVE"),
            transcript_answers_count=data.get("transcript_answers_count", 0),
        )


# =============================================================================
# Simplified Review Orchestrator
# =============================================================================

class ReviewOrchestrator:
    """
    Simplified review orchestrator with confidence-based auto-approval.
    
    Features:
    - Auto-approves high confidence answers (>= 0.75)
    - Flags low confidence for optional review
    - Simple re-synthesis on rejection
    - No mandatory review requirements
    """
    
    def __init__(self, synthesis_agent=None, storage=None):
        """
        Initialize Review Orchestrator.
        
        Args:
            synthesis_agent: Optional AnswerSynthesisAgent for re-synthesis
            storage: Optional ReviewStorage for persistence
        """
        self.synthesis_agent = synthesis_agent
        self.storage = storage
        self.sessions: Dict[str, ReviewSession] = {}
        logger.info("ReviewOrchestrator initialized (simplified)")
    
    def create_review_session(
        self,
        synthesized_answers: List[SynthesizedAnswer],
        session_id: Optional[str] = None,
        transcript_answers_count: int = 0,
    ) -> ReviewSession:
        """
        Create review session with confidence-based auto-approval.
        
        High confidence answers (>= 0.75) are auto-approved.
        Low confidence answers are flagged for optional review.
        
        Args:
            synthesized_answers: List of AI-synthesized answers
            session_id: Optional custom session ID
            transcript_answers_count: Count of transcript-based answers
            
        Returns:
            Created ReviewSession with auto-approved items
        """
        session_id = session_id or str(uuid.uuid4())
        
        items = []
        auto_approved = 0
        
        for answer in synthesized_answers:
            if isinstance(answer, dict):
                answer = SynthesizedAnswer.from_dict(answer)
            
            item = ReviewItem(
                review_id=str(uuid.uuid4()),
                question_id=answer.question_id,
                pillar=answer.pillar,
                criticality=answer.criticality,
                synthesized_answer=answer,
            )
            
            # Auto-approve high confidence
            if answer.confidence >= HITL_AUTO_APPROVE_THRESHOLD:
                item.status = ReviewStatus.APPROVED
                auto_approved += 1
                logger.debug(f"Auto-approved {answer.question_id} (confidence: {answer.confidence:.2f})")
            else:
                # Flag for optional review
                item.status = ReviewStatus.PENDING
                logger.debug(f"Flagged {answer.question_id} for optional review (confidence: {answer.confidence:.2f})")
            
            items.append(item)
        
        # Sort by criticality (HIGH first) then by confidence (low first)
        items.sort(key=lambda x: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(x.criticality.upper(), 2),
            x.synthesized_answer.confidence,
        ))
        
        session = ReviewSession(
            session_id=session_id,
            created_at=datetime.utcnow(),
            items=items,
            transcript_answers_count=transcript_answers_count,
        )
        
        self.sessions[session_id] = session
        
        # Persist if storage available
        if self.storage:
            try:
                self.storage.save_session(session.to_dict())
                logger.info(f"Session {session_id} saved to storage successfully")
            except Exception as e:
                logger.error(f"Failed to save session {session_id} to storage: {e}", exc_info=True)
                # Don't fail the session creation if storage fails
        else:
            logger.warning(f"Session {session_id} created but NOT saved to storage (storage not configured)")
        
        logger.info(
            f"Created review session {session_id}: "
            f"{auto_approved} auto-approved, {len(items) - auto_approved} flagged for optional review"
        )
        return session
    
    def get_session(self, session_id: str) -> Optional[ReviewSession]:
        """Get session by ID, loading from storage if needed."""
        if session_id in self.sessions:
            return self.sessions[session_id]
        
        # Try loading from storage
        if self.storage:
            data = self.storage.load_session(session_id)
            if data:
                session = ReviewSession.from_dict(data)
                self.sessions[session_id] = session
                return session
        
        return None
    
    def get_review_summary(self, session_id: str) -> Dict[str, Any]:
        """Get simple review summary."""
        session = self.get_session(session_id)
        if not session:
            return {}
        
        return session.to_dict()["summary"]
    
    def get_pending_review_items(self, session_id: str) -> List[ReviewItem]:
        """Get items flagged for optional review."""
        session = self.get_session(session_id)
        if not session:
            return []
        
        return [item for item in session.items if item.status == ReviewStatus.PENDING]
    
    def submit_review(
        self,
        session_id: str,
        review_id: str,
        decision: ReviewDecision,
        reviewer_id: str,
        modified_answer: Optional[str] = None,
        feedback: Optional[str] = None,
    ) -> ReviewItem:
        """
        Submit a review decision for an item.
        
        Args:
            session_id: Session identifier
            review_id: Review item ID
            decision: APPROVE, MODIFY, or REJECT
            reviewer_id: ID of the reviewer
            modified_answer: Modified text (for MODIFY)
            feedback: Rejection reason (for REJECT)
            
        Returns:
            Updated ReviewItem
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        item = next((i for i in session.items if i.review_id == review_id), None)
        if not item:
            raise ValueError(f"Review item {review_id} not found")
        
        # Update item
        item.reviewer_id = reviewer_id
        item.reviewed_at = datetime.utcnow()
        item.decision = decision
        
        if decision == ReviewDecision.APPROVE:
            item.status = ReviewStatus.APPROVED
            logger.info(f"Answer approved for {item.question_id}")
            
        elif decision == ReviewDecision.MODIFY:
            item.status = ReviewStatus.MODIFIED
            item.modified_answer = modified_answer
            logger.info(f"Answer modified for {item.question_id}")
            
        elif decision == ReviewDecision.REJECT:
            item.rejection_feedback = feedback
            item.revision_count += 1
            
            # Simple re-synthesis if agent available and under limit
            if (self.synthesis_agent and 
                item.revision_count <= HITL_MAX_RESYNTHESIS_ATTEMPTS and
                hasattr(self.synthesis_agent, 're_synthesize_with_feedback')):
                logger.info(f"Re-synthesizing answer for {item.question_id}")
                try:
                    new_answer = self.synthesis_agent.re_synthesize_with_feedback(
                        original=item.synthesized_answer,
                        feedback=feedback or "Please provide a more accurate answer.",
                        context={},
                        session_id=session_id,
                    )
                    item.synthesized_answer = new_answer
                    item.status = ReviewStatus.PENDING  # Back to pending for review
                    logger.info(f"Re-synthesis complete for {item.question_id}")
                except Exception as e:
                    logger.error(f"Re-synthesis failed: {e}")
                    item.status = ReviewStatus.REJECTED
            else:
                item.status = ReviewStatus.REJECTED
                logger.warning(f"Max revisions reached or no synthesis agent for {item.question_id}")
        
        # Persist changes
        if self.storage:
            self.storage.update_item(session_id, review_id, item.to_dict())
        
        return item
    
    def get_validated_answers(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get validated answers for report generation.
        
        Returns all approved/modified answers (including auto-approved).
        """
        session = self.get_session(session_id)
        if not session:
            return []
        
        validated = []
        for item in session.items:
            # Include auto-approved and human-reviewed items
            if item.status in [ReviewStatus.APPROVED, ReviewStatus.MODIFIED]:
                answer = item.synthesized_answer
                answer_text = item.modified_answer if item.modified_answer else answer.synthesized_answer
                
                validated.append({
                    "question_id": item.question_id,
                    "question_text": answer.question_text,
                    "pillar": item.pillar,
                    "answer_content": answer_text,
                    "source": "AI_MODIFIED" if item.status == ReviewStatus.MODIFIED else (
                        "AI_VALIDATED" if item.reviewer_id else "AI_AUTO_APPROVED"
                    ),
                    "confidence": answer.confidence,
                    "synthesis_method": answer.synthesis_method.value,
                    "reasoning_chain": answer.reasoning_chain,
                    "assumptions": answer.assumptions,
                    "evidence_quotes": [
                        {"text": eq.text, "location": eq.location, "relevance": eq.relevance}
                        for eq in answer.evidence_quotes
                    ],
                    "requires_attention": answer.requires_attention,
                    "review_metadata": {
                        "reviewer_id": item.reviewer_id,
                        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
                        "decision": item.decision.value if item.decision else None,
                        "revision_count": item.revision_count,
                        "auto_approved": item.reviewer_id is None,
                    },
                })
        
        return validated
    
    def complete_session(self, session_id: str) -> None:
        """Mark session as completed (no validation required)."""
        session = self.get_session(session_id)
        if session:
            session.status = "COMPLETED"
            if self.storage:
                try:
                    self.storage.save_session(session.to_dict())
                    logger.info(f"Session {session_id} marked as completed and saved to storage")
                except Exception as e:
                    logger.error(f"Failed to save completed session {session_id} to storage: {e}", exc_info=True)
            else:
                logger.warning(f"Session {session_id} marked as completed but NOT saved to storage (storage not configured)")
        else:
            logger.warning(f"Attempted to complete session {session_id} but session not found")


# =============================================================================
# Factory Function
# =============================================================================

def create_review_orchestrator(
    synthesis_agent=None,
    storage=None,
) -> ReviewOrchestrator:
    """
    Factory function to create Review Orchestrator.
    
    Args:
        synthesis_agent: Optional AnswerSynthesisAgent for re-synthesis
        storage: Optional ReviewStorage for persistence
        
    Returns:
        Configured ReviewOrchestrator instance
    """
    return ReviewOrchestrator(synthesis_agent=synthesis_agent, storage=storage)
