"""
Routing + AG-UI Integration

This module integrates the routing system with AG-UI events, enabling
autonomous agent operations with full observability.
"""

import logging
from typing import Any, Dict, Optional

from wafr.ag_ui.emitter import WAFREventEmitter
from wafr.agents.router import (
    AgentRouter,
    RouteResult,
    RoutingStrategy,
    create_router,
    create_default_wafr_rules,
)
from wafr.agents.autonomous_agent import (
    AutonomousAgentWrapper,
    RoutedAutonomousAgent,
    create_autonomous_agent,
)

logger = logging.getLogger(__name__)


class RoutingAGUIIntegration:
    """
    Integration layer for routing + AG-UI events.
    
    Provides unified interface for:
    - Routing decisions with event emission
    - Autonomous agent execution
    - Activity tracking
    - State synchronization
    """
    
    def __init__(
        self,
        emitter: WAFREventEmitter,
        router: Optional[AgentRouter] = None,
    ):
        """
        Initialize routing + AG-UI integration.
        
        Args:
            emitter: AG-UI event emitter
            router: Optional router (creates default if not provided)
        """
        self.emitter = emitter
        self.router = router or create_router(
            RoutingStrategy.RULE_BASED,
            rules=create_default_wafr_rules()
        )
        
        # Track routing decisions
        self._routing_history: list[RouteResult] = []
    
    async def route_and_execute(
        self,
        request_type: str,
        context: Dict[str, Any],
        available_agents: Dict[str, Any],
        **kwargs
    ) -> Any:
        """
        Route request and execute with full AG-UI event emission.
        
        Args:
            request_type: Type of request
            context: Request context
            available_agents: Available agents dictionary
            **kwargs: Additional arguments
            
        Returns:
            Execution result
        """
        # Emit routing activity start
        routing_activity_id = f"routing-{request_type}-{id(context)}"
        
        await self.emitter.activity_snapshot(
            message_id=routing_activity_id,
            activity_type="ROUTING",
            content={
                "request_type": request_type,
                "status": "evaluating",
                "context_keys": list(context.keys()),
            },
        )
        
        # Perform routing
        route_result = self.router.route(request_type, context, available_agents)
        self._routing_history.append(route_result)
        
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
                    "op": "add",
                    "path": "/routing_decision",
                    "value": {
                        "agent_name": route_result.agent_name,
                        "strategy": route_result.strategy.value,
                        "confidence": route_result.confidence,
                        "matched_rules": route_result.matched_rules,
                    },
                },
            ],
        )
        
        # Emit custom event for routing
        await self.emitter.custom_event(
            name="routing_decision",
            value={
                "request_type": request_type,
                "routed_to": route_result.agent_name,
                "strategy": route_result.strategy.value,
                "confidence": route_result.confidence,
                "metadata": route_result.metadata,
            }
        )
        
        # Get routed agent
        routed_agent = available_agents[route_result.agent_name]
        
        # Wrap agent if not already autonomous
        if not isinstance(routed_agent, AutonomousAgentWrapper):
            routed_agent = create_autonomous_agent(
                agent=routed_agent,
                agent_name=route_result.agent_name,
                emitter=self.emitter,
            )
        
        # Execute with autonomous wrapper
        result = await routed_agent.process(
            context.get("input_data"),
            context.get("session_id"),
            **kwargs
        )
        
        # Emit routing completion
        await self.emitter.activity_delta(
            message_id=routing_activity_id,
            activity_type="ROUTING",
            patch=[
                {
                    "op": "replace",
                    "path": "/status",
                    "value": "completed",
                },
                {
                    "op": "add",
                    "path": "/result",
                    "value": {
                        "has_result": result is not None,
                        "result_type": type(result).__name__,
                    },
                },
            ],
        )
        
        return result
    
    async def emit_routing_meta(
        self,
        request_type: str,
        route_result: RouteResult,
    ) -> None:
        """Emit routing decision as custom event."""
        await self.emitter.custom_event(
            name="routing_decision",
            value={
                "request_type": request_type,
                "routed_to": route_result.agent_name,
                "strategy": route_result.strategy.value,
                "confidence": route_result.confidence,
                "matched_rules": route_result.matched_rules,
            }
        )
    
    def get_routing_history(self) -> list[RouteResult]:
        """Get history of routing decisions."""
        return self._routing_history.copy()
    
    def clear_routing_history(self) -> None:
        """Clear routing history."""
        self._routing_history.clear()


def create_routing_agui_integration(
    emitter: WAFREventEmitter,
    router: Optional[AgentRouter] = None,
) -> RoutingAGUIIntegration:
    """
    Factory function to create routing + AG-UI integration.
    
    Args:
        emitter: AG-UI event emitter
        router: Optional router
        
    Returns:
        RoutingAGUIIntegration instance
    """
    return RoutingAGUIIntegration(emitter=emitter, router=router)
