"""
AG-UI Shared State Management

Implements bidirectional state synchronization between agents and frontends,
enabling collaborative human-in-the-loop workflows.

Based on AG-UI State Management specification:
https://docs.ag-ui.com/concepts/state
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
import json
import copy

from wafr.ag_ui.state import WAFRState, JSONPatch, PatchOp
from wafr.agents.user_context import UserContext
from wafr.agents.session_learning import SessionLearningContext

logger = logging.getLogger(__name__)


# =============================================================================
# Shared State Components
# =============================================================================

@dataclass
class UserContextState:
    """User context state for shared state."""
    
    industry: Optional[str] = None
    domain: Optional[str] = None
    use_case: Optional[str] = None
    thinking_style: Optional[str] = None
    communication_style: Optional[str] = None
    perspective: Optional[str] = None
    compliance_requirements: List[str] = field(default_factory=list)
    business_priorities: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "industry": self.industry,
            "domain": self.domain,
            "use_case": self.use_case,
            "thinking_style": self.thinking_style,
            "communication_style": self.communication_style,
            "perspective": self.perspective,
            "compliance_requirements": self.compliance_requirements,
            "business_priorities": self.business_priorities,
        }
    
    @classmethod
    def from_user_context(cls, user_context: UserContext) -> "UserContextState":
        """Create from UserContext."""
        return cls(
            industry=user_context.industry,
            domain=user_context.domain,
            use_case=user_context.use_case,
            thinking_style=user_context.thinking_style,
            communication_style=user_context.communication_style,
            perspective=user_context.perspective,
            compliance_requirements=user_context.compliance_requirements.copy(),
            business_priorities=user_context.business_priorities.copy(),
        )


@dataclass
class LearningState:
    """Session learning state for shared state."""
    
    total_reviews: int = 0
    learned_patterns: Dict[str, Any] = field(default_factory=dict)
    preferred_style: Optional[str] = None
    preferred_format: Optional[str] = None
    detail_level: str = "medium"
    common_feedback: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_reviews": self.total_reviews,
            "learned_patterns": self.learned_patterns,
            "preferred_style": self.preferred_style,
            "preferred_format": self.preferred_format,
            "detail_level": self.detail_level,
            "common_feedback": self.common_feedback,
        }
    
    @classmethod
    def from_learning_context(cls, learning_context: SessionLearningContext) -> "LearningState":
        """Create from SessionLearningContext."""
        return cls(
            total_reviews=len(learning_context.review_history),
            learned_patterns=learning_context.learned_patterns.copy(),
            preferred_style=learning_context.guidance.preferred_style,
            preferred_format=learning_context.guidance.preferred_format,
            detail_level=learning_context.guidance.detail_level,
            common_feedback=learning_context.guidance.common_feedback.copy(),
        )


@dataclass
class ProposalState:
    """
    Proposal state for human-in-the-loop collaboration.
    
    Represents agent proposals that require human approval/modification.
    """
    
    proposal_id: str
    proposal_type: str  # e.g., "answer_synthesis", "report_generation", "review_decision"
    status: str = "pending"  # "pending", "approved", "rejected", "modified"
    proposed_value: Any = None
    modified_value: Optional[Any] = None
    created_at: str = ""
    reviewed_at: Optional[str] = None
    reviewer_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "status": self.status,
            "proposed_value": self.proposed_value,
            "modified_value": self.modified_value,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
            "reviewer_id": self.reviewer_id,
        }


# =============================================================================
# Enhanced Shared State
# =============================================================================

@dataclass
class SharedWAFRState:
    """
    Enhanced shared state with user context, learning, and proposals.
    
    Extends WAFRState with additional state for bidirectional collaboration.
    """
    
    # Core WAFR state
    wafr_state: WAFRState
    
    # User context state
    user_context: UserContextState = field(default_factory=UserContextState)
    
    # Learning state
    learning: LearningState = field(default_factory=LearningState)
    
    # Frontend state (user preferences, UI state)
    frontend_state: Dict[str, Any] = field(default_factory=dict)
    
    def __init__(self, session_id: str = ""):
        """Initialize shared state."""
        self.wafr_state = WAFRState(session_id=session_id)
        self.user_context = UserContextState()
        self.learning = LearningState()
        self.frontend_state = {}
    
    def to_snapshot(self) -> Dict[str, Any]:
        """
        Convert to complete STATE_SNAPSHOT format.
        
        Returns:
            Complete state dictionary for AG-UI STATE_SNAPSHOT event.
        """
        snapshot = self.wafr_state.to_snapshot()
        
        # Add extended state
        snapshot["user_context"] = self.user_context.to_dict()
        snapshot["learning"] = self.learning.to_dict()
        snapshot["frontend_state"] = self.frontend_state.copy()
        
        return snapshot
    
    # Proposal system removed - unnecessary complexity
    # Use direct approval/rejection in review orchestrator instead
    
    def update_user_context(self, user_context: UserContext) -> List[Dict[str, Any]]:
        """
        Update user context state.
        
        Args:
            user_context: UserContext instance
            
        Returns:
            List of JSON Patch deltas
        """
        old_context = self.user_context.to_dict()
        self.user_context = UserContextState.from_user_context(user_context)
        new_context = self.user_context.to_dict()
        
        # Create deltas for changed fields
        deltas = []
        for key, new_value in new_context.items():
            old_value = old_context.get(key)
            if old_value != new_value:
                deltas.append(
                    JSONPatch(
                        op=PatchOp.REPLACE.value,
                        path=f"/user_context/{key}",
                        value=new_value,
                    ).to_dict()
                )
        
        return deltas
    
    def update_learning(self, learning_context: SessionLearningContext) -> List[Dict[str, Any]]:
        """
        Update learning state.
        
        Args:
            learning_context: SessionLearningContext instance
            
        Returns:
            List of JSON Patch deltas
        """
        old_learning = self.learning.to_dict()
        self.learning = LearningState.from_learning_context(learning_context)
        new_learning = self.learning.to_dict()
        
        # Create deltas for changed fields
        deltas = []
        for key, new_value in new_learning.items():
            old_value = old_learning.get(key)
            if old_value != new_value:
                deltas.append(
                    JSONPatch(
                        op=PatchOp.REPLACE.value,
                        path=f"/learning/{key}",
                        value=new_value,
                    ).to_dict()
                )
        
        return deltas
    
    def update_frontend_state(
        self,
        path: str,
        value: Any,
        op: str = PatchOp.REPLACE.value,
    ) -> Dict[str, Any]:
        """
        Update frontend state (from frontend).
        
        Args:
            path: JSON Pointer path (e.g., "/ui/theme")
            value: New value
            op: Operation type
            
        Returns:
            JSON Patch delta
        """
        # Apply to local state
        if op == PatchOp.REPLACE.value:
            # Simple path update
            parts = path.strip("/").split("/")
            current = self.frontend_state
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        
        return JSONPatch(op=op, path=f"/frontend_state{path}", value=value).to_dict()
    
    def apply_frontend_delta(self, delta: Dict[str, Any]) -> None:
        """
        Apply frontend state delta (from frontend).
        
        Args:
            delta: JSON Patch operation
        """
        op = delta.get("op")
        path = delta.get("path", "").replace("/frontend_state", "")
        
        if op == PatchOp.REPLACE.value:
            parts = path.strip("/").split("/")
            current = self.frontend_state
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = delta.get("value")
        elif op == PatchOp.ADD.value:
            parts = path.strip("/").split("/")
            current = self.frontend_state
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = delta.get("value")
        elif op == PatchOp.REMOVE.value:
            parts = path.strip("/").split("/")
            current = self.frontend_state
            for part in parts[:-1]:
                current = current[part]
            del current[parts[-1]]
    
    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> "SharedWAFRState":
        """Create shared state from snapshot."""
        session_id = snapshot.get("session", {}).get("id", "")
        shared_state = cls(session_id=session_id)
        
        # Restore WAFR state
        shared_state.wafr_state = WAFRState.from_snapshot(snapshot)
        
        # Restore user context
        if "user_context" in snapshot:
            uc_data = snapshot["user_context"]
            shared_state.user_context = UserContextState(**uc_data)
        
        # Restore learning
        if "learning" in snapshot:
            learning_data = snapshot["learning"]
            shared_state.learning = LearningState(**learning_data)
        
        # Restore frontend state
        if "frontend_state" in snapshot:
            shared_state.frontend_state = snapshot["frontend_state"].copy()
        
        return shared_state


# =============================================================================
# State Manager
# =============================================================================

class SharedStateManager:
    """
    Manages shared state synchronization between agents and frontends.
    
    Handles:
    - State snapshots and deltas
    - Bidirectional state updates
    - Conflict resolution
    - State persistence
    """
    
    def __init__(self):
        """Initialize state manager."""
        self.states: Dict[str, SharedWAFRState] = {}
        self.state_listeners: Dict[str, List[Callable]] = {}
        logger.info("SharedStateManager initialized")
    
    def get_state(self, session_id: str) -> SharedWAFRState:
        """
        Get or create shared state for session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            SharedWAFRState instance
        """
        if session_id not in self.states:
            self.states[session_id] = SharedWAFRState(session_id=session_id)
            logger.debug(f"Created shared state for session {session_id}")
        
        return self.states[session_id]
    
    def get_snapshot(self, session_id: str) -> Dict[str, Any]:
        """
        Get complete state snapshot.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Complete state snapshot
        """
        state = self.get_state(session_id)
        return state.to_snapshot()
    
    def apply_delta(
        self,
        session_id: str,
        delta: List[Dict[str, Any]],
        source: str = "agent",
    ) -> bool:
        """
        Apply state delta from agent or frontend.
        
        Args:
            session_id: Session identifier
            delta: List of JSON Patch operations
            source: Source of update ("agent" or "frontend")
            
        Returns:
            True if applied successfully
        """
        try:
            state = self.get_state(session_id)
            
            # Apply each patch operation
            for patch in delta:
                op = patch.get("op")
                path = patch.get("path", "")
                
                if source == "frontend" and path.startswith("/frontend_state"):
                    # Frontend state update
                    state.apply_frontend_delta(patch)
                else:
                    # Agent state update - apply to WAFR state
                    # This would need JSON Patch library for proper application
                    # For now, we'll handle common cases
                    logger.debug(f"Applying delta: {op} {path} from {source}")
            
            # Notify listeners
            self._notify_listeners(session_id, delta, source)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply delta: {e}", exc_info=True)
            return False
    
    def add_listener(
        self,
        session_id: str,
        callback: Callable[[str, List[Dict[str, Any]], str], None],
    ) -> None:
        """
        Add state change listener.
        
        Args:
            session_id: Session identifier
            callback: Callback function (session_id, delta, source)
        """
        if session_id not in self.state_listeners:
            self.state_listeners[session_id] = []
        self.state_listeners[session_id].append(callback)
    
    def _notify_listeners(
        self,
        session_id: str,
        delta: List[Dict[str, Any]],
        source: str,
    ) -> None:
        """Notify state change listeners."""
        if session_id in self.state_listeners:
            for callback in self.state_listeners[session_id]:
                try:
                    callback(session_id, delta, source)
                except Exception as e:
                    logger.error(f"Listener error: {e}", exc_info=True)
    
    def clear_session(self, session_id: str) -> None:
        """Clear state for session."""
        if session_id in self.states:
            del self.states[session_id]
        if session_id in self.state_listeners:
            del self.state_listeners[session_id]
        logger.info(f"Cleared shared state for session {session_id}")


# Global state manager instance
_shared_state_manager = SharedStateManager()


def get_shared_state_manager() -> SharedStateManager:
    """Get global shared state manager instance."""
    return _shared_state_manager
