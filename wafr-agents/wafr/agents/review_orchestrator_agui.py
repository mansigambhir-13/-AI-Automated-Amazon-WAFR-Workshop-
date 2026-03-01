"""
Simplified AG-UI Review Orchestrator

Minimal wrapper around ReviewOrchestrator with optional AG-UI message emission.
Removes complex message emission - keeps it simple and optional.
"""

import logging
from typing import List, Optional

from wafr.ag_ui.emitter import WAFREventEmitter
from wafr.agents.review_orchestrator import ReviewOrchestrator, ReviewSession
from wafr.agents.session_learning import SessionLearningManager, get_learning_manager
from wafr.models.review_item import ReviewDecision, ReviewItem
from wafr.models.synthesized_answer import SynthesizedAnswer

logger = logging.getLogger(__name__)


class AGUIReviewOrchestrator:
    """
    Simplified AG-UI review orchestrator wrapper.
    
    Delegates to base ReviewOrchestrator with optional learning integration.
    No complex message emission - keep it simple.
    """
    
    def __init__(
        self,
        orchestrator: ReviewOrchestrator,
        emitter: Optional[WAFREventEmitter] = None,
        learning_manager: Optional[SessionLearningManager] = None,
    ):
        """
        Initialize AG-UI review orchestrator.
        
        Args:
            orchestrator: Base ReviewOrchestrator instance
            emitter: Optional AG-UI event emitter (for future use)
            learning_manager: Optional session learning manager
        """
        self.orchestrator = orchestrator
        self.emitter = emitter
        self.learning_manager = learning_manager or get_learning_manager()
    
    def create_review_session(
        self,
        synthesized_answers: List[SynthesizedAnswer],
        session_id: Optional[str] = None,
        transcript_answers_count: int = 0,
    ) -> ReviewSession:
        """
        Create review session (delegates to base orchestrator).
        
        Args:
            synthesized_answers: List of synthesized answers
            session_id: Optional session ID
            transcript_answers_count: Count of transcript-based answers
            
        Returns:
            ReviewSession instance
        """
        return self.orchestrator.create_review_session(
            synthesized_answers=synthesized_answers,
            session_id=session_id,
            transcript_answers_count=transcript_answers_count,
        )
    
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
        Submit review decision (delegates to base orchestrator).
        
        Optionally updates session learning if learning manager is available.
        
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
        # Submit review using base orchestrator
        item = self.orchestrator.submit_review(
            session_id=session_id,
            review_id=review_id,
            decision=decision,
            reviewer_id=reviewer_id,
            modified_answer=modified_answer,
            feedback=feedback,
        )
        
        # Update session learning from review decision (optional, non-critical)
        if self.learning_manager:
            try:
                self.learning_manager.update_from_review(
                    session_id=session_id,
                    review_item=item,
                    decision=decision,
                    feedback=feedback,
                )
            except Exception as e:
                logger.debug(f"Learning update failed (non-critical): {e}")
        
        return item
    
    # Delegate other methods to base orchestrator
    def __getattr__(self, name):
        """Delegate attribute access to base orchestrator."""
        return getattr(self.orchestrator, name)


def create_agui_review_orchestrator(
    orchestrator: Optional[ReviewOrchestrator] = None,
    emitter: Optional[WAFREventEmitter] = None,
    learning_manager: Optional[SessionLearningManager] = None,
) -> AGUIReviewOrchestrator:
    """
    Factory function to create AG-UI review orchestrator.
    
    Args:
        orchestrator: Base ReviewOrchestrator (created if not provided)
        emitter: Optional AG-UI event emitter
        learning_manager: Optional session learning manager
        
    Returns:
        AGUIReviewOrchestrator instance
    """
    if orchestrator is None:
        from wafr.agents.review_orchestrator import create_review_orchestrator
        orchestrator = create_review_orchestrator()
    
    return AGUIReviewOrchestrator(
        orchestrator=orchestrator,
        emitter=emitter,
        learning_manager=learning_manager,
    )
