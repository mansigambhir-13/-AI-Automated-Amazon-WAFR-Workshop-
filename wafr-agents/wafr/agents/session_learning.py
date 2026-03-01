"""
Session-Specific Learning System

Stores and applies reviewer feedback and preferences per session,
enabling agents to adapt to user requirements without affecting other sessions.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from wafr.agents.user_context import UserContextManager, get_user_context_manager
from wafr.models.review_item import ReviewDecision, ReviewItem
from wafr.models.synthesized_answer import SynthesizedAnswer

logger = logging.getLogger(__name__)


# =============================================================================
# Session Learning Data Structures
# =============================================================================

@dataclass
class ReviewerGuidance:
    """
    Guidance from reviewer for a specific session.
    
    Captures preferences, patterns, and feedback that should be applied
    only to this session's answers.
    """
    
    session_id: str
    reviewer_id: Optional[str] = None
    
    # Feedback patterns
    preferred_style: Optional[str] = None  # e.g., "detailed", "concise", "technical"
    preferred_format: Optional[str] = None  # e.g., "bullet_points", "paragraphs"
    
    # Domain-specific guidance
    domain_context: Dict[str, Any] = field(default_factory=dict)  # Industry, workload type, etc.
    terminology_preferences: Dict[str, str] = field(default_factory=dict)  # Preferred terms
    
    # Answer quality preferences
    detail_level: str = "medium"  # "high", "medium", "low"
    require_evidence: bool = True
    require_examples: bool = False
    
    # Pillar-specific preferences
    pillar_preferences: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Common feedback patterns
    common_feedback: List[str] = field(default_factory=list)  # Recurring feedback themes
    rejected_patterns: List[str] = field(default_factory=list)  # What to avoid
    
    # Approved patterns (what reviewer likes)
    approved_patterns: List[str] = field(default_factory=list)  # What to replicate
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "reviewer_id": self.reviewer_id,
            "preferred_style": self.preferred_style,
            "preferred_format": self.preferred_format,
            "domain_context": self.domain_context,
            "terminology_preferences": self.terminology_preferences,
            "detail_level": self.detail_level,
            "require_evidence": self.require_evidence,
            "require_examples": self.require_examples,
            "pillar_preferences": self.pillar_preferences,
            "common_feedback": self.common_feedback,
            "rejected_patterns": self.rejected_patterns,
            "approved_patterns": self.approved_patterns,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewerGuidance":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            reviewer_id=data.get("reviewer_id"),
            preferred_style=data.get("preferred_style"),
            preferred_format=data.get("preferred_format"),
            domain_context=data.get("domain_context", {}),
            terminology_preferences=data.get("terminology_preferences", {}),
            detail_level=data.get("detail_level", "medium"),
            require_evidence=data.get("require_evidence", True),
            require_examples=data.get("require_examples", False),
            pillar_preferences=data.get("pillar_preferences", {}),
            common_feedback=data.get("common_feedback", []),
            rejected_patterns=data.get("rejected_patterns", []),
            approved_patterns=data.get("approved_patterns", []),
        )


@dataclass
class SessionLearningContext:
    """
    Learning context for a session.
    
    Tracks what the reviewer prefers and applies it to future answers.
    """
    
    session_id: str
    guidance: ReviewerGuidance = field(default_factory=lambda: ReviewerGuidance(session_id=""))
    
    # Learning from reviews
    review_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Patterns learned
    learned_patterns: Dict[str, Any] = field(default_factory=dict)
    
    def update_from_review(
        self,
        review_item: ReviewItem,
        decision: ReviewDecision,
        feedback: Optional[str] = None,
    ) -> None:
        """
        Update learning context from review decision.
        
        Args:
            review_item: Review item
            decision: Review decision
            feedback: Optional feedback text
        """
        # Record review in history
        self.review_history.append({
            "review_id": review_item.review_id,
            "question_id": review_item.question_id,
            "pillar": review_item.pillar,
            "decision": decision.value,
            "feedback": feedback,
            "confidence": review_item.confidence,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # Learn from decision
        if decision == ReviewDecision.APPROVE:
            # Extract patterns from approved answer
            if review_item.synthesized_answer:
                self._learn_approved_patterns(review_item.synthesized_answer)
        
        elif decision == ReviewDecision.REJECT:
            # Learn what to avoid
            if feedback:
                self.guidance.rejected_patterns.append(feedback)
                self._extract_feedback_patterns(feedback)
        
        elif decision == ReviewDecision.MODIFY:
            # Learn from modifications
            if review_item.modified_answer:
                self._learn_from_modification(review_item)
    
    def _learn_approved_patterns(self, answer: SynthesizedAnswer) -> None:
        """Extract patterns from approved answer."""
        # Learn style preferences
        if answer.synthesized_answer:
            # Check if detailed or concise
            word_count = len(answer.synthesized_answer.split())
            if word_count > 200:
                self.guidance.preferred_style = "detailed"
            elif word_count < 50:
                self.guidance.preferred_style = "concise"
        
        # Learn format preferences
        if "\n- " in answer.synthesized_answer or "\n* " in answer.synthesized_answer:
            self.guidance.preferred_format = "bullet_points"
        elif "\n\n" in answer.synthesized_answer:
            self.guidance.preferred_format = "paragraphs"
        
        # Learn pillar preferences
        if answer.pillar not in self.guidance.pillar_preferences:
            self.guidance.pillar_preferences[answer.pillar] = {}
        
        # Store approved answer characteristics
        self.guidance.approved_patterns.append({
            "pillar": answer.pillar,
            "synthesis_method": answer.synthesis_method.value,
            "confidence": answer.confidence,
            "has_reasoning": len(answer.reasoning_chain) > 0,
            "has_evidence": len(answer.evidence_quotes) > 0,
        })
    
    def _extract_feedback_patterns(self, feedback: str) -> None:
        """Extract patterns from feedback."""
        feedback_lower = feedback.lower()
        
        # Extract common themes
        if "more detail" in feedback_lower or "more specific" in feedback_lower:
            self.guidance.detail_level = "high"
            self.guidance.common_feedback.append("needs_more_detail")
        
        if "too detailed" in feedback_lower or "too long" in feedback_lower:
            self.guidance.detail_level = "low"
            self.guidance.common_feedback.append("too_detailed")
        
        if "example" in feedback_lower or "instance" in feedback_lower:
            self.guidance.require_examples = True
            self.guidance.common_feedback.append("needs_examples")
        
        if "evidence" in feedback_lower or "proof" in feedback_lower:
            self.guidance.require_evidence = True
            self.guidance.common_feedback.append("needs_evidence")
        
        # Extract terminology preferences
        # (Could be enhanced with NLP to extract preferred terms)
    
    def _learn_from_modification(self, review_item: ReviewItem) -> None:
        """Learn from modified answer."""
        if not review_item.modified_answer:
            return
        
        # Compare original vs modified to learn preferences
        original = review_item.synthesized_answer.synthesized_answer
        modified = review_item.modified_answer
        
        # Learn style differences
        original_words = len(original.split())
        modified_words = len(modified.split())
        
        if modified_words > original_words * 1.5:
            self.guidance.detail_level = "high"
        elif modified_words < original_words * 0.7:
            self.guidance.detail_level = "low"
        
        # Store modification pattern
        self.guidance.approved_patterns.append({
            "pillar": review_item.pillar,
            "modification_type": "user_modified",
            "original_length": original_words,
            "modified_length": modified_words,
        })
    
    def get_synthesis_guidance(self, pillar: Optional[str] = None) -> Dict[str, Any]:
        """
        Get guidance for synthesizing answers in this session.
        
        Args:
            pillar: Optional pillar to get pillar-specific guidance
            
        Returns:
            Guidance dictionary for synthesis agent
        """
        guidance = {
            "preferred_style": self.guidance.preferred_style,
            "preferred_format": self.guidance.preferred_format,
            "detail_level": self.guidance.detail_level,
            "require_evidence": self.guidance.require_evidence,
            "require_examples": self.guidance.require_examples,
            "domain_context": self.guidance.domain_context,
            "terminology_preferences": self.guidance.terminology_preferences,
            "common_feedback": self.guidance.common_feedback,
            "rejected_patterns": self.guidance.rejected_patterns,
            "approved_patterns": [
                p for p in self.guidance.approved_patterns
                if not pillar or p.get("pillar") == pillar
            ],
        }
        
        # Add pillar-specific guidance
        if pillar and pillar in self.guidance.pillar_preferences:
            guidance["pillar_specific"] = self.guidance.pillar_preferences[pillar]
        
        return guidance
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "guidance": self.guidance.to_dict(),
            "review_history": self.review_history,
            "learned_patterns": self.learned_patterns,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionLearningContext":
        """Create from dictionary."""
        context = cls(
            session_id=data["session_id"],
            guidance=ReviewerGuidance.from_dict(data.get("guidance", {"session_id": data["session_id"]})),
            review_history=data.get("review_history", []),
            learned_patterns=data.get("learned_patterns", {}),
        )
        return context


# =============================================================================
# Session Learning Manager
# =============================================================================

class SessionLearningManager:
    """
    Manages session-specific learning across the system.
    
    Stores reviewer preferences per session and provides guidance
    for agents to adapt their behavior.
    """
    
    def __init__(self, user_context_manager: Optional[UserContextManager] = None):
        """
        Initialize learning manager.
        
        Args:
            user_context_manager: Optional user context manager for integration
        """
        self.contexts: Dict[str, SessionLearningContext] = {}
        self.user_context_manager = user_context_manager or get_user_context_manager()
        logger.info("SessionLearningManager initialized")
    
    def get_context(self, session_id: str) -> SessionLearningContext:
        """
        Get or create learning context for session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            SessionLearningContext instance
        """
        if session_id not in self.contexts:
            self.contexts[session_id] = SessionLearningContext(session_id=session_id)
            logger.debug(f"Created learning context for session {session_id}")
        
        return self.contexts[session_id]
    
    def update_from_review(
        self,
        session_id: str,
        review_item: ReviewItem,
        decision: ReviewDecision,
        feedback: Optional[str] = None,
    ) -> None:
        """
        Update learning from review decision.
        
        Args:
            session_id: Session identifier
            review_item: Review item
            decision: Review decision
            feedback: Optional feedback text
        """
        context = self.get_context(session_id)
        context.update_from_review(review_item, decision, feedback)
        
        logger.info(
            f"Updated learning for session {session_id} "
            f"from {decision.value} decision on {review_item.question_id}"
        )
    
    def get_synthesis_guidance(
        self,
        session_id: str,
        pillar: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get synthesis guidance for session.
        
        Args:
            session_id: Session identifier
            pillar: Optional pillar for pillar-specific guidance
            
        Returns:
            Guidance dictionary for synthesis agent
        """
        context = self.get_context(session_id)
        guidance = context.get_synthesis_guidance(pillar)
        
        # Merge with user context adaptation guidance
        user_guidance = self.user_context_manager.get_adaptation_guidance(session_id)
        guidance["user_adaptation"] = user_guidance
        
        return guidance
    
    def set_domain_context(
        self,
        session_id: str,
        domain_context: Dict[str, Any],
    ) -> None:
        """
        Set domain context for session.
        
        Args:
            session_id: Session identifier
            domain_context: Domain-specific context (industry, workload type, etc.)
        """
        context = self.get_context(session_id)
        context.guidance.domain_context.update(domain_context)
        logger.info(f"Updated domain context for session {session_id}")
    
    def set_terminology_preferences(
        self,
        session_id: str,
        preferences: Dict[str, str],
    ) -> None:
        """
        Set terminology preferences for session.
        
        Args:
            session_id: Session identifier
            preferences: Map of terms to preferred alternatives
        """
        context = self.get_context(session_id)
        context.guidance.terminology_preferences.update(preferences)
        logger.info(f"Updated terminology preferences for session {session_id}")
    
    def clear_session(self, session_id: str) -> None:
        """Clear learning context for session."""
        if session_id in self.contexts:
            del self.contexts[session_id]
            logger.info(f"Cleared learning context for session {session_id}")
    
    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """
        Get learning summary for session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Summary dictionary
        """
        context = self.get_context(session_id)
        return {
            "session_id": session_id,
            "total_reviews": len(context.review_history),
            "guidance": context.guidance.to_dict(),
            "learned_patterns": context.learned_patterns,
        }


# Global learning manager instance
_learning_manager = SessionLearningManager()


def get_learning_manager() -> SessionLearningManager:
    """Get global learning manager instance."""
    return _learning_manager
