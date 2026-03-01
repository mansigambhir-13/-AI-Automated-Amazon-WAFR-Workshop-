"""
Error classes for WAFR Agent System.

Provides structured exception handling for:
- Synthesis errors (AI answer generation failures)
- Review errors (HITL workflow failures)
- Validation errors (finalization checks)
- Agent processing errors (general agent failures)
"""

from typing import Any, Dict, List, Optional


class WAFRAgentError(Exception):
    """
    Base exception for all WAFR agent errors.
    
    All custom exceptions in the WAFR system should inherit from this class
    to enable consistent error handling and logging.
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize WAFR agent error.
        
        Args:
            message: Human-readable error message
            details: Optional additional context
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


# =============================================================================
# Synthesis Errors
# =============================================================================

class SynthesisError(WAFRAgentError):
    """
    Error during AI answer synthesis.
    
    Raised when the Answer Synthesis Agent fails to generate an answer
    for a gap question.
    """
    
    def __init__(
        self,
        question_id: str,
        reason: str,
        pillar: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        """
        Initialize synthesis error.
        
        Args:
            question_id: ID of the question that failed synthesis
            reason: Explanation of why synthesis failed
            pillar: WAFR pillar (SEC, REL, etc.)
            original_error: Original exception if wrapping
        """
        self.question_id = question_id
        self.reason = reason
        self.pillar = pillar
        self.original_error = original_error
        
        message = f"Synthesis failed for {question_id}: {reason}"
        details = {
            "question_id": question_id,
            "pillar": pillar,
            "reason": reason,
        }
        if original_error:
            details["original_error"] = str(original_error)
        
        super().__init__(message, details)


class BatchSynthesisError(WAFRAgentError):
    """
    Error during batch synthesis of multiple questions.
    
    Contains information about which questions succeeded and which failed.
    """
    
    def __init__(
        self,
        total_questions: int,
        failed_questions: List[str],
        errors: List[Dict[str, Any]],
    ):
        """
        Initialize batch synthesis error.
        
        Args:
            total_questions: Total questions attempted
            failed_questions: List of question IDs that failed
            errors: List of error details for each failure
        """
        self.total_questions = total_questions
        self.failed_questions = failed_questions
        self.errors = errors
        
        message = f"Batch synthesis partially failed: {len(failed_questions)}/{total_questions} questions failed"
        details = {
            "total_questions": total_questions,
            "failed_count": len(failed_questions),
            "failed_questions": failed_questions,
            "errors": errors,
        }
        
        super().__init__(message, details)


class ResynthesisError(WAFRAgentError):
    """
    Error during re-synthesis after rejection.
    
    Raised when attempting to re-synthesize an answer based on feedback
    fails after maximum attempts.
    """
    
    def __init__(
        self,
        question_id: str,
        attempt_count: int,
        max_attempts: int,
        last_error: Optional[str] = None,
    ):
        """
        Initialize re-synthesis error.
        
        Args:
            question_id: ID of the question
            attempt_count: Number of attempts made
            max_attempts: Maximum allowed attempts
            last_error: Last error message before giving up
        """
        self.question_id = question_id
        self.attempt_count = attempt_count
        self.max_attempts = max_attempts
        
        message = f"Re-synthesis exhausted for {question_id} after {attempt_count}/{max_attempts} attempts"
        details = {
            "question_id": question_id,
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "last_error": last_error,
        }
        
        super().__init__(message, details)


# =============================================================================
# Review Errors
# =============================================================================

class ReviewError(WAFRAgentError):
    """
    Error during review process.
    
    Base class for all review-related errors.
    """
    pass


class SessionNotFoundError(ReviewError):
    """Review session not found."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        message = f"Review session not found: {session_id}"
        super().__init__(message, {"session_id": session_id})


class ReviewItemNotFoundError(ReviewError):
    """Review item not found in session."""
    
    def __init__(self, session_id: str, review_id: str):
        self.session_id = session_id
        self.review_id = review_id
        message = f"Review item {review_id} not found in session {session_id}"
        super().__init__(message, {"session_id": session_id, "review_id": review_id})


class InvalidReviewDecisionError(ReviewError):
    """Invalid review decision provided."""
    
    def __init__(self, decision: str, valid_decisions: List[str]):
        self.decision = decision
        self.valid_decisions = valid_decisions
        message = f"Invalid review decision '{decision}'. Valid options: {valid_decisions}"
        super().__init__(message, {"decision": decision, "valid_decisions": valid_decisions})


class ReviewAlreadySubmittedError(ReviewError):
    """Review already submitted for this item."""
    
    def __init__(self, review_id: str, current_status: str):
        self.review_id = review_id
        self.current_status = current_status
        message = f"Review already submitted for {review_id} (status: {current_status})"
        super().__init__(message, {"review_id": review_id, "current_status": current_status})


class SessionExpiredError(ReviewError):
    """Review session has expired."""
    
    def __init__(self, session_id: str, expired_at: str):
        self.session_id = session_id
        self.expired_at = expired_at
        message = f"Review session {session_id} expired at {expired_at}"
        super().__init__(message, {"session_id": session_id, "expired_at": expired_at})


# =============================================================================
# Validation Errors
# =============================================================================

class ValidationError(WAFRAgentError):
    """
    Error during validation checks.
    
    Raised when validation requirements are not met.
    """
    pass


class FinalizationError(ValidationError):
    """
    Error when attempting to finalize a session.
    
    Contains details about which validation checks failed.
    """
    
    def __init__(self, session_id: str, issues: List[str]):
        self.session_id = session_id
        self.issues = issues
        
        message = f"Cannot finalize session {session_id}: {'; '.join(issues)}"
        details = {
            "session_id": session_id,
            "issues": issues,
            "issue_count": len(issues),
        }
        
        super().__init__(message, details)


class AuthenticityThresholdError(ValidationError):
    """Authenticity score below required threshold."""
    
    def __init__(self, current_score: float, required_score: float, session_id: str):
        self.current_score = current_score
        self.required_score = required_score
        self.session_id = session_id
        
        message = f"Authenticity score {current_score:.1f}% below required {required_score:.1f}%"
        details = {
            "session_id": session_id,
            "current_score": current_score,
            "required_score": required_score,
            "deficit": required_score - current_score,
        }
        
        super().__init__(message, details)


class PillarApprovalError(ValidationError):
    """Pillar approval rate below required threshold."""
    
    def __init__(self, pillar: str, current_rate: float, required_rate: float, session_id: str):
        self.pillar = pillar
        self.current_rate = current_rate
        self.required_rate = required_rate
        self.session_id = session_id
        
        message = f"{pillar} pillar approval rate {current_rate*100:.1f}% below required {required_rate*100:.1f}%"
        details = {
            "session_id": session_id,
            "pillar": pillar,
            "current_rate": current_rate,
            "required_rate": required_rate,
        }
        
        super().__init__(message, details)


# =============================================================================
# Agent Processing Errors
# =============================================================================

class AgentProcessingError(WAFRAgentError):
    """
    Error during agent processing.
    
    General error for agent pipeline failures.
    """
    
    def __init__(
        self,
        agent_name: str,
        step_name: str,
        reason: str,
        session_id: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        self.agent_name = agent_name
        self.step_name = step_name
        self.reason = reason
        self.session_id = session_id
        self.original_error = original_error
        
        message = f"{agent_name} failed at {step_name}: {reason}"
        details = {
            "agent_name": agent_name,
            "step_name": step_name,
            "reason": reason,
            "session_id": session_id,
        }
        if original_error:
            details["original_error"] = str(original_error)
        
        super().__init__(message, details)


class ModelInvocationError(WAFRAgentError):
    """Error invoking Bedrock model."""
    
    def __init__(
        self,
        model_id: str,
        reason: str,
        retry_count: int = 0,
        original_error: Optional[Exception] = None,
    ):
        self.model_id = model_id
        self.reason = reason
        self.retry_count = retry_count
        self.original_error = original_error
        
        message = f"Model invocation failed for {model_id}: {reason}"
        details = {
            "model_id": model_id,
            "reason": reason,
            "retry_count": retry_count,
        }
        if original_error:
            details["original_error"] = str(original_error)
        
        super().__init__(message, details)


class TimeoutError(WAFRAgentError):
    """Operation timed out."""
    
    def __init__(self, operation: str, timeout_seconds: int):
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        
        message = f"Operation '{operation}' timed out after {timeout_seconds}s"
        details = {
            "operation": operation,
            "timeout_seconds": timeout_seconds,
        }
        
        super().__init__(message, details)


# =============================================================================
# Storage Errors
# =============================================================================

class StorageError(WAFRAgentError):
    """Error during storage operations."""
    
    def __init__(self, operation: str, resource: str, reason: str):
        self.operation = operation
        self.resource = resource
        self.reason = reason
        
        message = f"Storage {operation} failed for {resource}: {reason}"
        details = {
            "operation": operation,
            "resource": resource,
            "reason": reason,
        }
        
        super().__init__(message, details)

