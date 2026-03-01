"""
Multi-Agent System for Automated WAFR Processing

This module provides the core agents and orchestration for WAFR assessments,
including the HITL (Human-in-the-Loop) workflow for AI-generated answer validation.

Key Components:
- WafrOrchestrator: Main pipeline coordinator
- AnswerSynthesisAgent: AI answer generation for gap questions
- ReviewOrchestrator: HITL review workflow management
- ReviewStorage: Persistence for review sessions

NOTE: This module uses lazy imports to avoid circular dependency issues.
Import specific components directly from their modules for best performance.
"""
__version__ = "1.1.0"

# Lazy imports - only load when accessed
_lazy_imports = {
    # Core agents
    "AnswerSynthesisAgent": "wafr.agents.answer_synthesis_agent",
    "create_answer_synthesis_agent": "wafr.agents.answer_synthesis_agent",
    # HITL components
    "ReviewOrchestrator": "wafr.agents.review_orchestrator",
    "ReviewSession": "wafr.agents.review_orchestrator",
    "create_review_orchestrator": "wafr.agents.review_orchestrator",
    # Configuration
    "settings": "wafr.agents.config",
    "hitl_settings": "wafr.agents.config",
    "HITL_AUTO_APPROVE_THRESHOLD": "wafr.agents.config",
    "HITL_QUICK_REVIEW_THRESHOLD": "wafr.agents.config",
    "HITL_MIN_AUTHENTICITY_SCORE": "wafr.agents.config",
    # Error classes
    "WAFRAgentError": "wafr.agents.errors",
    "SynthesisError": "wafr.agents.errors",
    "ReviewError": "wafr.agents.errors",
    "ValidationError": "wafr.agents.errors",
    "FinalizationError": "wafr.agents.errors",
    "SessionNotFoundError": "wafr.agents.errors",
    "ReviewItemNotFoundError": "wafr.agents.errors",
    # Routing components
    "AgentRouter": "wafr.agents.router",
    "RouteRule": "wafr.agents.router",
    "RouteResult": "wafr.agents.router",
    "RouteCondition": "wafr.agents.router",
    "RoutingStrategy": "wafr.agents.router",
    "RuleBasedRouter": "wafr.agents.router",
    "PriorityBasedRouter": "wafr.agents.router",
    "ConditionalRouter": "wafr.agents.router",
    "create_router": "wafr.agents.router",
    "create_default_wafr_rules": "wafr.agents.router",
    # AG-UI Review Orchestrator
    "AGUIReviewOrchestrator": "wafr.agents.review_orchestrator_agui",
    "create_agui_review_orchestrator": "wafr.agents.review_orchestrator_agui",
    # Session Learning
    "SessionLearningManager": "wafr.agents.session_learning",
    "SessionLearningContext": "wafr.agents.session_learning",
    "ReviewerGuidance": "wafr.agents.session_learning",
    "get_learning_manager": "wafr.agents.session_learning",
    # User Context
    "UserContext": "wafr.agents.user_context",
    "UserContextManager": "wafr.agents.user_context",
    "get_user_context_manager": "wafr.agents.user_context",
    # Production Orchestrator
    "ProductionOrchestrator": "wafr.agents.production_orchestrator",
    "create_production_orchestrator": "wafr.agents.production_orchestrator",
    # WA Tool Agent
    "WAToolAgent": "wafr.agents.wa_tool_agent",
    # Orchestrator
    "WafrOrchestrator": "wafr.agents.orchestrator",
    "create_orchestrator": "wafr.agents.orchestrator",
}

__all__ = [
    # Version
    "__version__",
    # Core agents
    "AnswerSynthesisAgent",
    "create_answer_synthesis_agent",
    # HITL
    "ReviewOrchestrator",
    "ReviewSession",
    "create_review_orchestrator",
    # Config
    "settings",
    "hitl_settings",
    "HITL_AUTO_APPROVE_THRESHOLD",
    "HITL_QUICK_REVIEW_THRESHOLD",
    "HITL_MIN_AUTHENTICITY_SCORE",
    # Errors
    "WAFRAgentError",
    "SynthesisError",
    "ReviewError",
    "ValidationError",
    "FinalizationError",
    "SessionNotFoundError",
    "ReviewItemNotFoundError",
    # Routing
    "AgentRouter",
    "RouteRule",
    "RouteResult",
    "RouteCondition",
    "RoutingStrategy",
    "RuleBasedRouter",
    "PriorityBasedRouter",
    "ConditionalRouter",
    "create_router",
    "create_default_wafr_rules",
    # AG-UI Review
    "AGUIReviewOrchestrator",
    "create_agui_review_orchestrator",
    # Session Learning
    "SessionLearningManager",
    "SessionLearningContext",
    "ReviewerGuidance",
    "get_learning_manager",
    # User Context
    "UserContext",
    "UserContextManager",
    "get_user_context_manager",
    # Production Orchestrator
    "ProductionOrchestrator",
    "create_production_orchestrator",
    # WA Tool Agent
    "WAToolAgent",
    # Orchestrator
    "WafrOrchestrator",
    "create_orchestrator",
]


def __getattr__(name):
    """Lazy import handler - imports modules only when accessed."""
    if name in _lazy_imports:
        module_path = _lazy_imports[name]
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, name)
    raise AttributeError(f"module 'wafr.agents' has no attribute '{name}'")
