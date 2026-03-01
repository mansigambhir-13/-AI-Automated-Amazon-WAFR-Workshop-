"""
AG-UI Messages Integration for Review Orchestrator

Integrates AG-UI message concepts with the HITL review workflow,
enabling structured message-based communication for review sessions.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from wafr.ag_ui.emitter import WAFREventEmitter
from wafr.ag_ui.messages import (
    ReviewMessageBuilder,
    review_session_to_messages,
    review_item_to_messages,
)
from wafr.models.review_item import ReviewDecision, ReviewItem, ReviewStatus
from wafr.models.synthesized_answer import SynthesizedAnswer

logger = logging.getLogger(__name__)


class ReviewMessagesIntegration:
    """
    Integration layer for AG-UI messages in review workflow.
    
    Emits AG-UI messages for:
    - Synthesized answers (Assistant Messages)
    - User comments/feedback (User Messages)
    - Review status (Activity Messages)
    - Review queue progress (Activity Messages)
    """
    
    def __init__(self, emitter: WAFREventEmitter):
        """
        Initialize review messages integration.
        
        Args:
            emitter: AG-UI event emitter
        """
        self.emitter = emitter
        self.builder = ReviewMessageBuilder()
    
    async def emit_review_session_messages(
        self,
        review_session: Any,  # ReviewSession
    ) -> None:
        """
        Emit complete message snapshot for review session.
        
        Args:
            review_session: ReviewSession instance
        """
        # Convert session to messages
        messages = review_session_to_messages(review_session, include_activities=True)
        
        # Emit messages snapshot
        await self.emitter.messages_snapshot(messages)
        
        logger.info(
            f"Emitted {len(messages)} messages for review session {review_session.session_id}"
        )
    
    async def emit_synthesized_answer_message(
        self,
        synthesized_answer: SynthesizedAnswer,
        tool_call_id: Optional[str] = None,
    ) -> str:
        """
        Emit assistant message for synthesized answer.
        
        Args:
            synthesized_answer: Synthesized answer to emit
            tool_call_id: Optional tool call ID
            
        Returns:
            Message ID
        """
        # Create assistant message
        assistant_msg = self.builder.create_synthesized_answer_message(
            synthesized_answer,
            tool_call_id,
        )
        
        # Emit as text message stream
        await self.emitter.text_message_start(
            assistant_msg.id,
            role="assistant",
            context={"agent_name": "answer_synthesis_agent"},
        )
        
        # Stream content in chunks
        content = assistant_msg.content or ""
        chunk_size = 500
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            await self.emitter.text_message_content(
                assistant_msg.id,
                chunk,
                context={"agent_name": "answer_synthesis_agent"},
            )
        
        await self.emitter.text_message_end(
            assistant_msg.id,
            context={"agent_name": "answer_synthesis_agent"},
        )
        
        # If tool call ID provided, emit tool result message
        if tool_call_id:
            tool_msg = self.builder.create_tool_result_message(
                synthesized_answer,
                tool_call_id,
            )
            # Emit tool message as text message
            await self.emitter.text_message_start(
                tool_msg.id,
                role="tool",
                context={"tool_call_id": tool_call_id},
            )
            await self.emitter.text_message_content(
                tool_msg.id,
                tool_msg.content,
                context={"tool_call_id": tool_call_id},
            )
            await self.emitter.text_message_end(
                tool_msg.id,
                context={"tool_call_id": tool_call_id},
            )
        
        return assistant_msg.id
    
    async def emit_user_comment_message(
        self,
        review_item: ReviewItem,
        comment: str,
        reviewer_id: Optional[str] = None,
    ) -> str:
        """
        Emit user message for review comment/feedback.
        
        Args:
            review_item: Review item being commented on
            comment: User's comment/feedback
            reviewer_id: Optional reviewer identifier
            
        Returns:
            Message ID
        """
        # Create user message
        user_msg = self.builder.create_user_comment_message(
            review_item,
            comment,
            reviewer_id,
        )
        
        # Emit as text message
        await self.emitter.text_message_start(
            user_msg.id,
            role="user",
            context={"reviewer_id": reviewer_id},
        )
        await self.emitter.text_message_content(
            user_msg.id,
            user_msg.content,
            context={"reviewer_id": reviewer_id},
        )
        await self.emitter.text_message_end(
            user_msg.id,
            context={"reviewer_id": reviewer_id},
        )
        
        return user_msg.id
    
    async def emit_review_item_activity(
        self,
        review_item: ReviewItem,
        session_id: str,
    ) -> None:
        """
        Emit activity message for review item status.
        
        Args:
            review_item: Review item to represent
            session_id: Review session ID
        """
        # Create activity message
        activity_msg = self.builder.create_review_activity_message(
            review_item,
            session_id,
        )
        
        # Emit as activity snapshot
        await self.emitter.activity_snapshot(
            message_id=activity_msg.id,
            activity_type=activity_msg.activity_type,
            content=activity_msg.content,
            replace=True,
            context={"session_id": session_id},
        )
    
    async def emit_review_queue_activity(
        self,
        session_id: str,
        total_items: int,
        pending_count: int,
        approved_count: int,
        rejected_count: int,
        modified_count: int = 0,
    ) -> None:
        """
        Emit activity message for review queue status.
        
        Args:
            session_id: Review session ID
            total_items: Total items in queue
            pending_count: Pending items count
            approved_count: Approved items count
            rejected_count: Rejected items count
            modified_count: Modified items count
        """
        # Create activity message
        activity_msg = self.builder.create_review_queue_activity_message(
            session_id,
            total_items,
            pending_count,
            approved_count,
            rejected_count,
            modified_count,
        )
        
        # Emit as activity snapshot
        await self.emitter.activity_snapshot(
            message_id=activity_msg.id,
            activity_type=activity_msg.activity_type,
            content=activity_msg.content,
            replace=True,
            context={"session_id": session_id},
        )
    
    async def update_review_item_activity(
        self,
        review_item: ReviewItem,
        session_id: str,
    ) -> None:
        """
        Update review item activity with status changes.
        
        Args:
            review_item: Updated review item
            session_id: Review session ID
        """
        # Create activity message
        activity_msg = self.builder.create_review_activity_message(
            review_item,
            session_id,
        )
        
        # Emit as activity delta (update)
        await self.emitter.activity_delta(
            message_id=activity_msg.id,
            activity_type=activity_msg.activity_type,
            patch=[
                {
                    "op": "replace",
                    "path": "/status",
                    "value": review_item.status.value,
                },
                {
                    "op": "replace",
                    "path": "/decision",
                    "value": review_item.decision.value if review_item.decision else None,
                },
                {
                    "op": "replace",
                    "path": "/reviewed_at",
                    "value": review_item.reviewed_at.isoformat() if review_item.reviewed_at else None,
                },
            ],
            context={"session_id": session_id},
        )
    
    async def update_review_queue_activity(
        self,
        session_id: str,
        pending_count: int,
        approved_count: int,
        rejected_count: int,
        modified_count: int = 0,
    ) -> None:
        """
        Update review queue activity with progress changes.
        
        Args:
            session_id: Review session ID
            pending_count: Updated pending count
            approved_count: Updated approved count
            rejected_count: Updated rejected count
            modified_count: Updated modified count
        """
        activity_id = f"activity-queue-{session_id}"
        total_items = pending_count + approved_count + rejected_count + modified_count
        progress = (approved_count / total_items * 100) if total_items > 0 else 0
        
        # Emit activity delta
        await self.emitter.activity_delta(
            message_id=activity_id,
            activity_type="REVIEW_QUEUE",
            patch=[
                {
                    "op": "replace",
                    "path": "/pending_count",
                    "value": pending_count,
                },
                {
                    "op": "replace",
                    "path": "/approved_count",
                    "value": approved_count,
                },
                {
                    "op": "replace",
                    "path": "/rejected_count",
                    "value": rejected_count,
                },
                {
                    "op": "replace",
                    "path": "/modified_count",
                    "value": modified_count,
                },
                {
                    "op": "replace",
                    "path": "/progress_percentage",
                    "value": round(progress, 1),
                },
                {
                    "op": "replace",
                    "path": "/updated_at",
                    "value": datetime.utcnow().isoformat(),
                },
            ],
            context={"session_id": session_id},
        )


def create_review_messages_integration(
    emitter: WAFREventEmitter,
) -> ReviewMessagesIntegration:
    """
    Factory function to create review messages integration.
    
    Args:
        emitter: AG-UI event emitter
        
    Returns:
        ReviewMessagesIntegration instance
    """
    return ReviewMessagesIntegration(emitter)
