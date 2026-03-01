"""
Agent Router - Intelligent routing system for multi-agent coordination.

Routes requests to appropriate agents based on conditions, context, and routing strategies.
Supports rule-based routing, priority-based routing, and dynamic agent selection.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Routing Enums and Types
# =============================================================================

class RoutingStrategy(Enum):
    """Available routing strategies."""
    RULE_BASED = "rule_based"  # Route based on predefined rules
    PRIORITY_BASED = "priority_based"  # Route based on priority scores
    CONDITIONAL = "conditional"  # Route based on dynamic conditions
    PARALLEL = "parallel"  # Route to multiple agents in parallel
    SEQUENTIAL = "sequential"  # Route through agents in sequence


class RouteCondition(Enum):
    """Common routing conditions."""
    ALWAYS = "always"
    CONFIDENCE_HIGH = "confidence_high"  # confidence >= threshold
    CONFIDENCE_LOW = "confidence_low"  # confidence < threshold
    HAS_GAPS = "has_gaps"  # gaps detected
    NO_GAPS = "no_gaps"  # no gaps detected
    INPUT_TYPE_TEXT = "input_type_text"
    INPUT_TYPE_PDF = "input_type_pdf"
    LENS_DETECTED = "lens_detected"
    ERROR_OCCURRED = "error_occurred"


# =============================================================================
# Routing Data Structures
# =============================================================================

@dataclass
class RouteRule:
    """
    A routing rule that determines when to route to an agent.
    
    Attributes:
        condition: Condition that must be met
        agent_name: Name of the agent to route to
        priority: Priority of this rule (higher = evaluated first)
        context_required: List of context keys that must be present
        custom_check: Optional custom function to check condition
    """
    condition: RouteCondition | str | Callable[[Dict[str, Any]], bool]
    agent_name: str
    priority: int = 0
    context_required: List[str] = None
    custom_check: Optional[Callable[[Dict[str, Any]], bool]] = None
    
    def __post_init__(self):
        if self.context_required is None:
            self.context_required = []
    
    def matches(self, context: Dict[str, Any]) -> bool:
        """Check if this rule matches the given context."""
        # Check required context keys
        for key in self.context_required:
            if key not in context:
                return False
        
        # Check condition
        if isinstance(self.condition, RouteCondition):
            return self._check_enum_condition(self.condition, context)
        elif isinstance(self.condition, str):
            return self._check_string_condition(self.condition, context)
        elif callable(self.condition):
            return self.condition(context)
        else:
            return False
    
    def _check_enum_condition(self, condition: RouteCondition, context: Dict[str, Any]) -> bool:
        """Check enum-based conditions."""
        if condition == RouteCondition.ALWAYS:
            return True
        elif condition == RouteCondition.CONFIDENCE_HIGH:
            confidence = context.get("confidence", 0.0)
            threshold = context.get("confidence_threshold", 0.7)
            return confidence >= threshold
        elif condition == RouteCondition.CONFIDENCE_LOW:
            confidence = context.get("confidence", 0.0)
            threshold = context.get("confidence_threshold", 0.7)
            return confidence < threshold
        elif condition == RouteCondition.HAS_GAPS:
            gaps = context.get("gaps", [])
            return len(gaps) > 0
        elif condition == RouteCondition.NO_GAPS:
            gaps = context.get("gaps", [])
            return len(gaps) == 0
        elif condition == RouteCondition.INPUT_TYPE_TEXT:
            input_type = context.get("input_type", "")
            return input_type == "text" or input_type == "transcript"
        elif condition == RouteCondition.INPUT_TYPE_PDF:
            input_type = context.get("input_type", "")
            return input_type == "pdf"
        elif condition == RouteCondition.LENS_DETECTED:
            lenses = context.get("detected_lenses", [])
            return len(lenses) > 0
        elif condition == RouteCondition.ERROR_OCCURRED:
            errors = context.get("errors", [])
            return len(errors) > 0
        
        return False
    
    def _check_string_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """Check string-based conditions (for custom conditions)."""
        # Support simple key=value conditions
        if "=" in condition:
            key, value = condition.split("=", 1)
            return context.get(key) == value
        
        # Support key existence checks
        return condition in context and bool(context[condition])


@dataclass
class RouteResult:
    """Result of a routing decision."""
    agent_name: str
    strategy: RoutingStrategy
    context: Dict[str, Any]
    matched_rules: List[str] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.matched_rules is None:
            self.matched_rules = []
        if self.metadata is None:
            self.metadata = {}


# =============================================================================
# Router Interface
# =============================================================================

class AgentRouter(ABC):
    """Abstract base class for agent routers."""
    
    @abstractmethod
    def route(
        self,
        request_type: str,
        context: Dict[str, Any],
        available_agents: Dict[str, Any],
    ) -> RouteResult:
        """
        Route a request to an appropriate agent.
        
        Args:
            request_type: Type of request (e.g., "process_transcript", "validate_answer")
            context: Context dictionary with request data and state
            available_agents: Dictionary of available agents by name
            
        Returns:
            RouteResult with routing decision
        """
        pass


# =============================================================================
# Rule-Based Router Implementation
# =============================================================================

class RuleBasedRouter(AgentRouter):
    """
    Rule-based router that routes requests based on predefined rules.
    
    Rules are evaluated in priority order, and the first matching rule determines
    the routing decision.
    """
    
    def __init__(self, rules: Optional[List[RouteRule]] = None):
        """
        Initialize router with routing rules.
        
        Args:
            rules: List of routing rules (optional, can be added later)
        """
        self.rules: List[RouteRule] = rules or []
        self.default_agent: Optional[str] = None
    
    def add_rule(self, rule: RouteRule) -> None:
        """Add a routing rule."""
        self.rules.append(rule)
        # Sort by priority (higher priority first)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
    
    def add_rules(self, rules: List[RouteRule]) -> None:
        """Add multiple routing rules."""
        for rule in rules:
            self.add_rule(rule)
    
    def set_default_agent(self, agent_name: str) -> None:
        """Set default agent for fallback routing."""
        self.default_agent = agent_name
    
    def route(
        self,
        request_type: str,
        context: Dict[str, Any],
        available_agents: Dict[str, Any],
    ) -> RouteResult:
        """
        Route request based on rules.
        
        Args:
            request_type: Type of request
            context: Request context
            available_agents: Available agents
            
        Returns:
            RouteResult with routing decision
        """
        # Add request_type to context for rule matching
        context_with_type = {**context, "request_type": request_type}
        
        # Evaluate rules in priority order
        matched_rules = []
        for rule in self.rules:
            if rule.matches(context_with_type):
                # Check if agent is available
                if rule.agent_name in available_agents:
                    matched_rules.append(f"{rule.condition} -> {rule.agent_name}")
                    logger.info(
                        f"Routing {request_type} to {rule.agent_name} "
                        f"(matched: {rule.condition})"
                    )
                    return RouteResult(
                        agent_name=rule.agent_name,
                        strategy=RoutingStrategy.RULE_BASED,
                        context=context_with_type,
                        matched_rules=matched_rules,
                        confidence=1.0,
                        metadata={"rule_priority": rule.priority},
                    )
                else:
                    logger.warning(
                        f"Rule matched but agent {rule.agent_name} not available"
                    )
        
        # Fallback to default agent
        if self.default_agent and self.default_agent in available_agents:
            logger.info(f"Using default agent {self.default_agent} for {request_type}")
            return RouteResult(
                agent_name=self.default_agent,
                strategy=RoutingStrategy.RULE_BASED,
                context=context_with_type,
                matched_rules=["default"],
                confidence=0.5,
                metadata={"fallback": True},
            )
        
        # No rule matched and no default
        raise ValueError(
            f"No routing rule matched for request_type={request_type} "
            f"and no default agent set"
        )


# =============================================================================
# Priority-Based Router Implementation
# =============================================================================

class PriorityBasedRouter(AgentRouter):
    """
    Priority-based router that routes to agents based on priority scores.
    
    Each agent is assigned a priority score based on context, and the agent
    with the highest score is selected.
    """
    
    def __init__(self, priority_functions: Optional[Dict[str, Callable]] = None):
        """
        Initialize router with priority functions.
        
        Args:
            priority_functions: Dict mapping agent names to priority calculation functions
        """
        self.priority_functions = priority_functions or {}
    
    def set_priority_function(
        self, agent_name: str, func: Callable[[Dict[str, Any]], float]
    ) -> None:
        """Set priority calculation function for an agent."""
        self.priority_functions[agent_name] = func
    
    def route(
        self,
        request_type: str,
        context: Dict[str, Any],
        available_agents: Dict[str, Any],
    ) -> RouteResult:
        """
        Route request based on priority scores.
        
        Args:
            request_type: Type of request
            context: Request context
            available_agents: Available agents
            
        Returns:
            RouteResult with routing decision
        """
        context_with_type = {**context, "request_type": request_type}
        
        # Calculate priorities for available agents
        agent_priorities = {}
        for agent_name, agent in available_agents.items():
            if agent_name in self.priority_functions:
                try:
                    priority = self.priority_functions[agent_name](context_with_type)
                    agent_priorities[agent_name] = priority
                except Exception as e:
                    logger.warning(
                        f"Error calculating priority for {agent_name}: {e}"
                    )
                    agent_priorities[agent_name] = 0.0
            else:
                # Default priority if no function defined
                agent_priorities[agent_name] = 0.5
        
        if not agent_priorities:
            raise ValueError("No agents available for routing")
        
        # Select agent with highest priority
        best_agent = max(agent_priorities.items(), key=lambda x: x[1])
        agent_name, priority = best_agent
        
        logger.info(
            f"Routing {request_type} to {agent_name} "
            f"(priority score: {priority:.2f})"
        )
        
        return RouteResult(
            agent_name=agent_name,
            strategy=RoutingStrategy.PRIORITY_BASED,
            context=context_with_type,
            confidence=min(priority, 1.0),
            metadata={"priority_scores": agent_priorities},
        )


# =============================================================================
# Conditional Router Implementation
# =============================================================================

class ConditionalRouter(AgentRouter):
    """
    Conditional router that uses custom logic to determine routing.
    
    Allows for complex routing logic through custom condition functions.
    """
    
    def __init__(self, routing_function: Callable[[str, Dict[str, Any], Dict[str, Any]], RouteResult]):
        """
        Initialize router with custom routing function.
        
        Args:
            routing_function: Function that takes (request_type, context, available_agents)
                            and returns RouteResult
        """
        self.routing_function = routing_function
    
    def route(
        self,
        request_type: str,
        context: Dict[str, Any],
        available_agents: Dict[str, Any],
    ) -> RouteResult:
        """
        Route request using custom routing function.
        
        Args:
            request_type: Type of request
            context: Request context
            available_agents: Available agents
            
        Returns:
            RouteResult with routing decision
        """
        return self.routing_function(request_type, context, available_agents)


# =============================================================================
# Router Factory
# =============================================================================

def create_router(
    strategy: RoutingStrategy = RoutingStrategy.RULE_BASED,
    **kwargs
) -> AgentRouter:
    """
    Factory function to create routers.
    
    Args:
        strategy: Routing strategy to use
        **kwargs: Additional arguments for router initialization
        
    Returns:
        Configured AgentRouter instance
        
    Examples:
        # Rule-based router
        router = create_router(
            RoutingStrategy.RULE_BASED,
            rules=[
                RouteRule(
                    condition=RouteCondition.CONFIDENCE_HIGH,
                    agent_name="confidence_agent",
                    priority=10
                )
            ]
        )
        
        # Priority-based router
        router = create_router(RoutingStrategy.PRIORITY_BASED)
    """
    if strategy == RoutingStrategy.RULE_BASED:
        return RuleBasedRouter(rules=kwargs.get("rules"))
    elif strategy == RoutingStrategy.PRIORITY_BASED:
        return PriorityBasedRouter(priority_functions=kwargs.get("priority_functions"))
    elif strategy == RoutingStrategy.CONDITIONAL:
        routing_func = kwargs.get("routing_function")
        if not routing_func:
            raise ValueError("routing_function required for ConditionalRouter")
        return ConditionalRouter(routing_func)
    else:
        raise ValueError(f"Unsupported routing strategy: {strategy}")


# =============================================================================
# Default Routing Rules for WAFR
# =============================================================================

def create_default_wafr_rules() -> List[RouteRule]:
    """
    Create default routing rules for WAFR pipeline.
    
    Returns:
        List of RouteRule instances configured for WAFR workflow
    """
    return [
        # High confidence -> use confidence agent for validation
        RouteRule(
            condition=RouteCondition.CONFIDENCE_HIGH,
            agent_name="confidence_agent",
            priority=10,
            context_required=["confidence"],
        ),
        # Low confidence -> use understanding agent for re-analysis
        RouteRule(
            condition=RouteCondition.CONFIDENCE_LOW,
            agent_name="understanding_agent",
            priority=9,
            context_required=["confidence"],
        ),
        # Has gaps -> use gap detection agent
        RouteRule(
            condition=RouteCondition.HAS_GAPS,
            agent_name="gap_detection_agent",
            priority=8,
            context_required=["gaps"],
        ),
        # PDF input -> use PDF processor
        RouteRule(
            condition=RouteCondition.INPUT_TYPE_PDF,
            agent_name="pdf_processor",
            priority=7,
            context_required=["input_type"],
        ),
        # Text input -> use understanding agent
        RouteRule(
            condition=RouteCondition.INPUT_TYPE_TEXT,
            agent_name="understanding_agent",
            priority=6,
            context_required=["input_type"],
        ),
        # Error occurred -> use report agent for error handling
        RouteRule(
            condition=RouteCondition.ERROR_OCCURRED,
            agent_name="report_agent",
            priority=5,
            context_required=["errors"],
        ),
    ]

