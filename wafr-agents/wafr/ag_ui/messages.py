"""
AG-UI Messages for HITL Review Workflow

Implements AG-UI message concepts for human review of synthesized answers.
Uses Activity Messages for review status, Assistant Messages for synthesized answers,
User Messages for comments/feedback, and Tool Messages for synthesis results.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from wafr.models.review_item import ReviewDecision, ReviewItem, ReviewStatus
from wafr.models.synthesized_answer import SynthesizedAnswer


# =============================================================================
# AG-UI Message Types
# =============================================================================

@dataclass
class BaseMessage:
    """Base message structure following AG-UI spec."""
    
    id: str
    role: str  # "user", "assistant", "system", "tool", "activity", "developer"
    content: Optional[str] = None
    name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "id": self.id,
            "role": self.role,
        }
        if self.content:
            result["content"] = self.content
        if self.name:
            result["name"] = self.name
        return result


@dataclass
class UserMessage(BaseMessage):
    """User message - for comments and feedback."""
    
    role: str = "user"
    content: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "content": self.content,
        }


@dataclass
class AssistantMessage(BaseMessage):
    """Assistant message - for synthesized answers."""
    
    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.content:
            result["content"] = self.content
        if self.tool_calls:
            result["toolCalls"] = self.tool_calls
        return result


@dataclass
class ToolMessage(BaseMessage):
    """Tool message - for synthesis results."""
    
    role: str = "tool"
    content: str = ""
    tool_call_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "content": self.content,
            "toolCallId": self.tool_call_id,
        }


@dataclass
class ActivityMessage(BaseMessage):
    """Activity message - for review status and progress (frontend-only)."""
    
    role: str = "activity"
    activity_type: str = ""
    content: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "activityType": self.activity_type,
            "content": self.content,
        }


# =============================================================================
# Review Message Builders
# =============================================================================

class ReviewMessageBuilder:
    """Builder for creating AG-UI messages from review items."""
    
    @staticmethod
    def create_synthesized_answer_message(
        synthesized_answer: SynthesizedAnswer,
        tool_call_id: Optional[str] = None,
    ) -> AssistantMessage:
        """
        Create assistant message for synthesized answer.
        
        Args:
            synthesized_answer: Synthesized answer to convert
            tool_call_id: Optional tool call ID that generated this
            
        Returns:
            AssistantMessage with synthesized answer
        """
        message_id = f"msg-synth-{synthesized_answer.question_id}-{uuid.uuid4().hex[:8]}"
        
        # Build content with answer and metadata
        content_parts = [
            f"**Synthesized Answer for Question {synthesized_answer.question_id}**",
            f"",
            f"**Answer:**",
            synthesized_answer.synthesized_answer,
            f"",
            f"**Confidence:** {synthesized_answer.confidence:.0%}",
            f"**Confidence Justification:** {synthesized_answer.confidence_justification}",
        ]
        
        if synthesized_answer.reasoning_chain:
            content_parts.extend([
                f"",
                f"**Reasoning Chain:**",
            ])
            for i, step in enumerate(synthesized_answer.reasoning_chain, 1):
                content_parts.append(f"{i}. {step}")
        
        if synthesized_answer.assumptions:
            content_parts.extend([
                f"",
                f"**Assumptions:**",
            ])
            for assumption in synthesized_answer.assumptions:
                content_parts.append(f"- {assumption}")
        
        content = "\n".join(content_parts)
        
        # Build tool calls if synthesis was via tool
        tool_calls = None
        if tool_call_id:
            tool_calls = [{
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": "synthesize_answer",
                    "arguments": f'{{"question_id": "{synthesized_answer.question_id}", "pillar": "{synthesized_answer.pillar}"}}',
                }
            }]
        
        return AssistantMessage(
            id=message_id,
            content=content,
            tool_calls=tool_calls,
            name="answer_synthesis_agent",
        )
    
    @staticmethod
    def create_tool_result_message(
        synthesized_answer: SynthesizedAnswer,
        tool_call_id: str,
    ) -> ToolMessage:
        """
        Create tool message for synthesis result.
        
        Args:
            synthesized_answer: Synthesized answer result
            tool_call_id: Tool call ID that generated this
            
        Returns:
            ToolMessage with synthesis result
        """
        message_id = f"msg-tool-{synthesized_answer.question_id}-{uuid.uuid4().hex[:8]}"
        
        # Format result as JSON
        result_content = {
            "question_id": synthesized_answer.question_id,
            "answer": synthesized_answer.synthesized_answer,
            "confidence": synthesized_answer.confidence,
            "reasoning_chain": synthesized_answer.reasoning_chain,
            "assumptions": synthesized_answer.assumptions,
            "synthesis_method": synthesized_answer.synthesis_method,
        }
        
        import json
        content = json.dumps(result_content, indent=2)
        
        return ToolMessage(
            id=message_id,
            content=content,
            tool_call_id=tool_call_id,
        )
    
    @staticmethod
    def create_user_comment_message(
        review_item: ReviewItem,
        comment: str,
        reviewer_id: Optional[str] = None,
    ) -> UserMessage:
        """
        Create user message for review comment/feedback.
        
        Args:
            review_item: Review item being commented on
            comment: User's comment/feedback
            reviewer_id: Optional reviewer identifier
            
        Returns:
            UserMessage with comment
        """
        message_id = f"msg-comment-{review_item.review_id}-{uuid.uuid4().hex[:8]}"
        
        content_parts = [
            f"**Review Comment for Question {review_item.question_id}**",
            f"",
            comment,
        ]
        
        if review_item.decision:
            content_parts.append(f"")
            content_parts.append(f"**Decision:** {review_item.decision.value}")
        
        if review_item.modified_answer:
            content_parts.extend([
                f"",
                f"**Modified Answer:**",
                review_item.modified_answer,
            ])
        
        content = "\n".join(content_parts)
        
        return UserMessage(
            id=message_id,
            content=content,
            name=reviewer_id or "reviewer",
        )
    
    @staticmethod
    def create_review_activity_message(
        review_item: ReviewItem,
        session_id: str,
    ) -> ActivityMessage:
        """
        Create activity message for review item status.
        
        Args:
            review_item: Review item to represent
            session_id: Review session ID
            
        Returns:
            ActivityMessage with review status
        """
        message_id = f"activity-review-{review_item.review_id}"
        
        # Build activity content
        content = {
            "review_id": review_item.review_id,
            "question_id": review_item.question_id,
            "pillar": review_item.pillar,
            "criticality": review_item.criticality,
            "status": review_item.status.value,
            "confidence": review_item.confidence,
            "synthesized_answer": review_item.synthesized_answer.synthesized_answer,
            "decision": review_item.decision.value if review_item.decision else None,
            "reviewed_at": review_item.reviewed_at.isoformat() if review_item.reviewed_at else None,
            "revision_count": review_item.revision_count,
        }
        
        if review_item.modified_answer:
            content["modified_answer"] = review_item.modified_answer
        
        if review_item.rejection_feedback:
            content["rejection_feedback"] = review_item.rejection_feedback
        
        return ActivityMessage(
            id=message_id,
            activity_type="REVIEW_ITEM",
            content=content,
        )
    
    @staticmethod
    def create_review_queue_activity_message(
        session_id: str,
        total_items: int,
        pending_count: int,
        approved_count: int,
        rejected_count: int,
        modified_count: int = 0,
    ) -> ActivityMessage:
        """
        Create activity message for review queue status.
        
        Args:
            session_id: Review session ID
            total_items: Total items in queue
            pending_count: Pending items count
            approved_count: Approved items count
            rejected_count: Rejected items count
            modified_count: Modified items count
            
        Returns:
            ActivityMessage with queue status
        """
        message_id = f"activity-queue-{session_id}"
        
        progress = (approved_count / total_items * 100) if total_items > 0 else 0
        
        content = {
            "session_id": session_id,
            "status": "ACTIVE",
            "total_items": total_items,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "modified_count": modified_count,
            "progress_percentage": round(progress, 1),
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        return ActivityMessage(
            id=message_id,
            activity_type="REVIEW_QUEUE",
            content=content,
        )


# =============================================================================
# Message Conversion Utilities
# =============================================================================

def review_session_to_messages(
    review_session: Any,  # ReviewSession
    include_activities: bool = True,
) -> List[Dict[str, Any]]:
    """
    Convert review session to AG-UI message list.
    
    Args:
        review_session: ReviewSession instance
        include_activities: Include activity messages
        
    Returns:
        List of message dictionaries
    """
    messages: List[Dict[str, Any]] = []
    builder = ReviewMessageBuilder()
    
    # Add queue activity message
    if include_activities:
        queue_activity = builder.create_review_queue_activity_message(
            session_id=review_session.session_id,
            total_items=len(review_session.items),
            pending_count=review_session.pending_count,
            approved_count=review_session.approved_count,
            rejected_count=review_session.rejected_count,
            modified_count=len([i for i in review_session.items if i.status == ReviewStatus.MODIFIED]),
        )
        messages.append(queue_activity.to_dict())
    
    # Add messages for each review item
    for item in review_session.items:
        # Add synthesized answer as assistant message
        synth_msg = builder.create_synthesized_answer_message(item.synthesized_answer)
        messages.append(synth_msg.to_dict())
        
        # Add review activity
        if include_activities:
            activity_msg = builder.create_review_activity_message(item, review_session.session_id)
            messages.append(activity_msg.to_dict())
        
        # Add user comments/feedback if present
        if item.rejection_feedback:
            comment_msg = builder.create_user_comment_message(
                item,
                item.rejection_feedback,
            )
            messages.append(comment_msg.to_dict())
        
        # Add modified answer as user message if present
        if item.modified_answer and item.status == ReviewStatus.MODIFIED:
            modified_msg = UserMessage(
                id=f"msg-modified-{item.review_id}",
                content=f"**Modified Answer:**\n\n{item.modified_answer}",
                name="reviewer",
            )
            messages.append(modified_msg.to_dict())
    
    return messages


def review_item_to_messages(
    review_item: ReviewItem,
    include_activity: bool = True,
) -> List[Dict[str, Any]]:
    """
    Convert single review item to AG-UI messages.
    
    Args:
        review_item: ReviewItem instance
        include_activity: Include activity message
        
    Returns:
        List of message dictionaries
    """
    messages: List[Dict[str, Any]] = []
    builder = ReviewMessageBuilder()
    
    # Add synthesized answer
    synth_msg = builder.create_synthesized_answer_message(review_item.synthesized_answer)
    messages.append(synth_msg.to_dict())
    
    # Add activity if requested
    if include_activity:
        activity_msg = builder.create_review_activity_message(review_item, "")
        messages.append(activity_msg.to_dict())
    
    # Add user feedback if present
    if review_item.rejection_feedback:
        comment_msg = builder.create_user_comment_message(
            review_item,
            review_item.rejection_feedback,
        )
        messages.append(comment_msg.to_dict())
    
    return messages
