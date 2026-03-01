"""
Router Integration Example - Shows how to integrate routing into orchestrator.

This module demonstrates how to integrate the AgentRouter into the WafrOrchestrator
for intelligent agent routing.
"""

import logging
from typing import Any, Dict, Optional

from wafr.agents.router import (
    AgentRouter,
    RouteCondition,
    RouteResult,
    RouteRule,
    RoutingStrategy,
    create_default_wafr_rules,
    create_router,
)

logger = logging.getLogger(__name__)


class RoutedOrchestratorMixin:
    """
    Mixin class that adds routing capabilities to orchestrator.
    
    This can be mixed into WafrOrchestrator to add routing functionality.
    """
    
    def __init__(self, *args, router: Optional[AgentRouter] = None, **kwargs):
        """Initialize with optional router."""
        super().__init__(*args, **kwargs)
        self.router = router or self._create_default_router()
    
    def _create_default_router(self) -> AgentRouter:
        """Create default router with WAFR rules."""
        router = create_router(
            RoutingStrategy.RULE_BASED,
            rules=create_default_wafr_rules()
        )
        # Set default agent (fallback)
        router.set_default_agent("understanding_agent")
        return router
    
    def _get_available_agents(self) -> Dict[str, Any]:
        """Get dictionary of available agents."""
        return {
            "understanding_agent": self.understanding_agent,
            "mapping_agent": self.mapping_agent,
            "confidence_agent": self.confidence_agent,
            "gap_detection_agent": self.gap_detection_agent,
            "answer_synthesis_agent": self.answer_synthesis_agent,
            "scoring_agent": self.scoring_agent,
            "report_agent": self.report_agent,
            "wa_tool_agent": self.wa_tool_agent,
            "pdf_processor": self.pdf_processor,
        }
    
    def route_to_agent(
        self,
        request_type: str,
        context: Dict[str, Any],
    ) -> RouteResult:
        """
        Route a request to an appropriate agent.
        
        Args:
            request_type: Type of request (e.g., "process_transcript", "validate_answer")
            context: Context dictionary with request data
            
        Returns:
            RouteResult with routing decision
        """
        available_agents = self._get_available_agents()
        return self.router.route(request_type, context, available_agents)
    
    def execute_routed_request(
        self,
        request_type: str,
        context: Dict[str, Any],
        **kwargs
    ) -> Any:
        """
        Route and execute a request.
        
        Args:
            request_type: Type of request
            context: Request context
            **kwargs: Additional arguments to pass to agent
            
        Returns:
            Result from routed agent
        """
        route_result = self.route_to_agent(request_type, context)
        agent = self._get_available_agents()[route_result.agent_name]
        
        logger.info(
            f"Executing {request_type} via {route_result.agent_name} "
            f"(strategy: {route_result.strategy.value})"
        )
        
        # Execute agent based on request type
        if hasattr(agent, "process"):
            return agent.process(context.get("input_data"), **kwargs)
        elif hasattr(agent, request_type):
            method = getattr(agent, request_type)
            return method(context.get("input_data"), **kwargs)
        else:
            raise ValueError(
                f"Agent {route_result.agent_name} does not support "
                f"request type {request_type}"
            )


# =============================================================================
# Example: Custom Routing Logic
# =============================================================================

def create_custom_wafr_router() -> AgentRouter:
    """
    Example of creating a custom router with specific routing logic.
    
    Returns:
        Configured AgentRouter instance
    """
    # Create custom rules
    custom_rules = [
        # Route high-confidence results directly to scoring
        RouteRule(
            condition=lambda ctx: ctx.get("confidence", 0) >= 0.9,
            agent_name="scoring_agent",
            priority=15,
            context_required=["confidence"],
        ),
        # Route low-confidence to re-understanding
        RouteRule(
            condition=lambda ctx: ctx.get("confidence", 0) < 0.5,
            agent_name="understanding_agent",
            priority=12,
            context_required=["confidence"],
        ),
        # Route gap questions to answer synthesis
        RouteRule(
            condition=RouteCondition.HAS_GAPS,
            agent_name="answer_synthesis_agent",
            priority=10,
        ),
        # Route mapping results to confidence validation
        RouteRule(
            condition=lambda ctx: ctx.get("request_type") == "validate_mapping",
            agent_name="confidence_agent",
            priority=8,
        ),
    ]
    
    router = create_router(RoutingStrategy.RULE_BASED, rules=custom_rules)
    router.set_default_agent("understanding_agent")
    return router


# =============================================================================
# Example: Priority-Based Routing
# =============================================================================

def create_priority_based_router() -> AgentRouter:
    """
    Example of creating a priority-based router.
    
    Returns:
        Configured PriorityBasedRouter instance
    """
    def understanding_priority(context: Dict[str, Any]) -> float:
        """Calculate priority for understanding agent."""
        confidence = context.get("confidence", 0.5)
        input_length = len(str(context.get("input_data", "")))
        
        # Higher priority for low confidence or long inputs
        if confidence < 0.5:
            return 0.9
        if input_length > 10000:
            return 0.8
        return 0.5
    
    def confidence_priority(context: Dict[str, Any]) -> float:
        """Calculate priority for confidence agent."""
        has_mapping = "mapping_result" in context
        has_insights = "insights" in context
        
        # Higher priority when we have mapping or insights to validate
        if has_mapping and has_insights:
            return 0.9
        if has_mapping or has_insights:
            return 0.7
        return 0.3
    
    def gap_detection_priority(context: Dict[str, Any]) -> float:
        """Calculate priority for gap detection agent."""
        has_insights = "insights" in context
        has_mapping = "mapping_result" in context
        
        # High priority when we have both insights and mapping
        if has_insights and has_mapping:
            return 0.95
        return 0.4
    
    priority_functions = {
        "understanding_agent": understanding_priority,
        "confidence_agent": confidence_priority,
        "gap_detection_agent": gap_detection_priority,
    }
    
    return create_router(
        RoutingStrategy.PRIORITY_BASED,
        priority_functions=priority_functions
    )

