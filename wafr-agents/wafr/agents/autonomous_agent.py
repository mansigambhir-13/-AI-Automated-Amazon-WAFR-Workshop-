"""
Autonomous Agent Wrapper - Adds AG-UI event emission to agents.

This module provides an autonomous agent wrapper that automatically emits
AG-UI events for all agent operations, making agents observable and autonomous.
Integrates with the routing system to emit routing decisions as events.
"""

import logging
import uuid
from typing import Any, Dict, Optional, Callable
from datetime import datetime

from wafr.ag_ui.emitter import WAFREventEmitter
from wafr.agents.router import RouteResult, AgentRouter
from wafr.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class AutonomousAgentWrapper:
    """
    Wrapper that makes any agent autonomous by emitting AG-UI events.
    
    Automatically emits:
    - Tool call events for agent operations
    - Step events for processing stages
    - Text messages for progress updates
    - Activity events for ongoing operations
    - State updates for results
    """
    
    def __init__(
        self,
        agent: BaseAgent,
        agent_name: str,
        emitter: Optional[WAFREventEmitter] = None,
        router: Optional[AgentRouter] = None,
    ):
        """
        Initialize autonomous agent wrapper.
        
        Args:
            agent: Base agent instance to wrap
            agent_name: Name identifier for this agent
            emitter: Optional AG-UI event emitter
            router: Optional router for routing decisions
        """
        self.agent = agent
        self.agent_name = agent_name
        self.emitter = emitter
        self.router = router
        
        # Activity tracking
        self._current_activity_id: Optional[str] = None
        self._activity_type: str = "AGENT_OPERATION"
    
    async def process(
        self,
        input_data: Any,
        session_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Process input with full AG-UI event emission.
        
        Args:
            input_data: Input to process
            session_id: Optional session identifier
            **kwargs: Additional arguments
            
        Returns:
            Processing result
        """
        if not self.emitter:
            # No emitter, just call agent directly
            return self.agent.process(input_data, session_id, **kwargs)
        
        # Generate tool call ID
        tool_call_id = f"tool-{self.agent_name}-{uuid.uuid4().hex[:8]}"
        
        # Start activity
        activity_id = f"activity-{self.agent_name}-{uuid.uuid4().hex[:8]}"
        self._current_activity_id = activity_id
        
        # Build context for middleware
        context = {
            "session_id": session_id or "",
            "agent_name": self.agent_name,
            "agent_type": getattr(self.agent, 'agent_type', self.agent_name),
            "model_id": getattr(self.agent, 'model_id', None),
        }
        
        try:
            # Emit tool call start (with context for middleware)
            await self.emitter.tool_call_start(
                tool_call_id=tool_call_id,
                tool_name=self.agent_name,
                context=context,
            )
            
            # Emit step started
            await self.emitter.step_started(
                step_name=f"{self.agent_name}_processing",
                metadata={
                    "agent": self.agent_name,
                    "input_type": type(input_data).__name__,
                },
                context=context,
            )
            
            # Emit activity snapshot
            await self.emitter.activity_snapshot(
                message_id=activity_id,
                activity_type=self._activity_type,
                content={
                    "agent": self.agent_name,
                    "status": "processing",
                    "started_at": datetime.utcnow().isoformat(),
                },
                context=context,
            )
            
            # Emit text message start
            msg_id = f"msg-{self.agent_name}-{uuid.uuid4().hex[:8]}"
            await self.emitter.text_message_start(msg_id, role="assistant", context=context)
            await self.emitter.text_message_content(
                msg_id,
                f"Starting {self.agent_name} processing...",
                context=context,
            )
            
            # Emit tool call args
            args_summary = self._summarize_args(input_data, kwargs)
            await self.emitter.tool_call_args(tool_call_id, args_summary, context=context)
            
            # Execute agent (original logic preserved)
            result = self.agent.process(input_data, session_id, **kwargs)
            
            # Emit progress updates
            await self.emitter.text_message_content(
                msg_id,
                f"Completed {self.agent_name} processing.",
                context=context,
            )
            await self.emitter.text_message_end(msg_id, context=context)
            
            # Emit activity delta (completion)
            await self.emitter.activity_delta(
                message_id=activity_id,
                activity_type=self._activity_type,
                patch=[
                    {
                        "op": "replace",
                        "path": "/status",
                        "value": "completed",
                    },
                    {
                        "op": "replace",
                        "path": "/completed_at",
                        "value": datetime.utcnow().isoformat(),
                    },
                ],
                context=context,
            )
            
            # Emit tool call result
            result_summary = self._summarize_result(result)
            await self.emitter.tool_call_result(tool_call_id, result_summary, context=context)
            
            # Emit tool call end
            await self.emitter.tool_call_end(tool_call_id, str(result_summary), context=context)
            
            # Emit step finished
            await self.emitter.step_finished(
                step_name=f"{self.agent_name}_processing",
                result={
                    "status": "success",
                    "has_result": result is not None,
                },
                context=context,
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Agent {self.agent_name} error: {e}", exc_info=True)
            
            # Emit error events
            await self.emitter.tool_call_end(
                tool_call_id,
                f"Error: {str(e)}"
            )
            await self.emitter.step_finished(
                step_name=f"{self.agent_name}_processing",
                result={
                    "status": "error",
                    "error": str(e),
                }
            )
            
            # Emit activity delta (error)
            if self._current_activity_id:
                await self.emitter.activity_delta(
                    message_id=self._current_activity_id,
                    activity_type=self._activity_type,
                    patch=[
                        {
                            "op": "replace",
                            "path": "/status",
                            "value": "error",
                        },
                        {
                            "op": "replace",
                            "path": "/error",
                            "value": str(e),
                        },
                    ],
                )
            
            raise
    
    def _summarize_args(self, input_data: Any, kwargs: Dict[str, Any]) -> str:
        """Summarize arguments for event emission."""
        summary_parts = []
        
        if isinstance(input_data, str):
            summary_parts.append(f"input_length={len(input_data)}")
        elif isinstance(input_data, (list, dict)):
            summary_parts.append(f"input_type={type(input_data).__name__}")
            if isinstance(input_data, list):
                summary_parts.append(f"items={len(input_data)}")
            elif isinstance(input_data, dict):
                summary_parts.append(f"keys={len(input_data)}")
        
        if kwargs:
            summary_parts.append(f"kwargs={list(kwargs.keys())}")
        
        return ", ".join(summary_parts) if summary_parts else "no_args"
    
    def _summarize_result(self, result: Any) -> Dict[str, Any]:
        """Summarize result for event emission."""
        if isinstance(result, dict):
            return {
                "type": "dict",
                "keys": list(result.keys())[:10],  # Limit keys
                "has_data": True,
            }
        elif isinstance(result, list):
            return {
                "type": "list",
                "count": len(result),
                "has_data": len(result) > 0,
            }
        else:
            return {
                "type": type(result).__name__,
                "has_data": result is not None,
            }
    
    def set_activity_type(self, activity_type: str) -> None:
        """Set activity type for this agent."""
        self._activity_type = activity_type
    
    # Delegate other methods to wrapped agent
    def __getattr__(self, name):
        """Delegate attribute access to wrapped agent."""
        return getattr(self.agent, name)


class RoutedAutonomousAgent(AutonomousAgentWrapper):
    """
    Autonomous agent that uses routing for decision-making.
    
    Emits routing decisions as AG-UI events and uses router
    to determine processing strategy.
    """
    
    async def process_with_routing(
        self,
        request_type: str,
        context: Dict[str, Any],
        available_agents: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Process request using routing system.
        
        Args:
            request_type: Type of request
            context: Request context
            available_agents: Available agents dictionary
            **kwargs: Additional arguments
            
        Returns:
            Processing result
        """
        if not self.router:
            # No router, use direct processing
            return await self.process(
                context.get("input_data"),
                context.get("session_id"),
                **kwargs
            )
        
        if not self.emitter:
            # No emitter, just route and process
            route_result = self.router.route(request_type, context, available_agents)
            agent = available_agents[route_result.agent_name]
            return agent.process(context.get("input_data"), **kwargs)
        
        # Emit routing decision as activity
        routing_activity_id = f"routing-{uuid.uuid4().hex[:8]}"
        
        await self.emitter.activity_snapshot(
            message_id=routing_activity_id,
            activity_type="ROUTING",
            content={
                "request_type": request_type,
                "context_keys": list(context.keys()),
                "status": "evaluating",
            },
        )
        
        # Route request
        route_result = self.router.route(request_type, context, available_agents)
        
        # Emit routing decision
        await self.emitter.activity_delta(
            message_id=routing_activity_id,
            activity_type="ROUTING",
            patch=[
                {
                    "op": "replace",
                    "path": "/status",
                    "value": "routed",
                },
                {
                    "op": "replace",
                    "path": "/routed_to",
                    "value": route_result.agent_name,
                },
                {
                    "op": "replace",
                    "path": "/strategy",
                    "value": route_result.strategy.value,
                },
                {
                    "op": "replace",
                    "path": "/confidence",
                    "value": route_result.confidence,
                },
            ],
        )
        
        # Emit custom event for routing decision
        await self.emitter.custom_event(
            name="routing_decision",
            value={
                "request_type": request_type,
                "routed_to": route_result.agent_name,
                "strategy": route_result.strategy.value,
                "matched_rules": route_result.matched_rules,
                "confidence": route_result.confidence,
            }
        )
        
        # Process with routed agent
        routed_agent = available_agents[route_result.agent_name]
        
        # If routed agent is also autonomous, use it directly
        if isinstance(routed_agent, AutonomousAgentWrapper):
            return await routed_agent.process(
                context.get("input_data"),
                context.get("session_id"),
                **kwargs
            )
        
        # Otherwise wrap it temporarily
        wrapper = AutonomousAgentWrapper(
            agent=routed_agent,
            agent_name=route_result.agent_name,
            emitter=self.emitter,
        )
        return await wrapper.process(
            context.get("input_data"),
            context.get("session_id"),
            **kwargs
        )


def create_autonomous_agent(
    agent: BaseAgent,
    agent_name: str,
    emitter: Optional[WAFREventEmitter] = None,
    router: Optional[AgentRouter] = None,
    use_routing: bool = False,
) -> AutonomousAgentWrapper:
    """
    Create an autonomous agent wrapper.
    
    Args:
        agent: Base agent to wrap
        agent_name: Agent name identifier
        emitter: Optional event emitter
        router: Optional router for routing
        use_routing: Whether to use routing (creates RoutedAutonomousAgent)
        
    Returns:
        AutonomousAgentWrapper or RoutedAutonomousAgent instance
    """
    if use_routing and router:
        return RoutedAutonomousAgent(
            agent=agent,
            agent_name=agent_name,
            emitter=emitter,
            router=router,
        )
    else:
        return AutonomousAgentWrapper(
            agent=agent,
            agent_name=agent_name,
            emitter=emitter,
            router=router,
        )
