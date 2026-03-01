"""
AG-UI (Agent User Interaction Protocol) Integration for WAFR.

This module provides AG-UI compliant event streaming for the WAFR pipeline,
enabling real-time progress updates and HITL (Human-in-the-Loop) interactions.

Components:
- core: Official AG-UI SDK wrapper and WAFR adapters
- events: Custom event definitions for WAFR/HITL workflow
- state: WAFRState class for state management
- emitter: WAFREventEmitter for streaming events
- orchestrator_integration: Orchestrator wrapper with AG-UI events
- server: FastAPI SSE endpoints

Usage:
    from ag_ui import WAFREventEmitter, WAFRState, HITLEvents, create_agui_orchestrator
    
    # Basic usage
    emitter = WAFREventEmitter(thread_id="session-123", run_id="run-456")
    await emitter.run_started()
    await emitter.step_started("understanding")
    await emitter.step_finished("understanding", {"insights_count": 15})
    await emitter.run_finished()
    
    # With orchestrator integration
    orchestrator = create_agui_orchestrator(thread_id="session-123")
    results = await orchestrator.process_transcript_with_agui(
        transcript=transcript_text,
        session_id="session-123",
    )
"""

# Core AG-UI SDK integration
from wafr.ag_ui.core import (
    # Official SDK types (if available)
    RunAgentInput,
    Message,
    Context,
    Tool,
    State,
    # WAFR adapters
    WAFRRunAgentInput,
    WAFRMessage,
    WAFRContext,
    WAFRTool,
    # Utilities
    get_wafr_tool,
    get_all_wafr_tools,
    WAFR_AGENT_TOOLS,
    AG_UI_AVAILABLE,
)

# Events
from wafr.ag_ui.events import (
    HITLEventType,
    HITLEvents,
    WAFRPipelineStep,
    ReviewQueueSummary,
    SynthesisProgress,
    ReviewDecisionData,
    ValidationStatus,
    create_hitl_event,
)

# State management
from wafr.ag_ui.state import (
    WAFRState,
    SessionStatus,
    ReviewQueueStatus,
    JSONPatch,
    PatchOp,
)

# Event emitter
from wafr.ag_ui.emitter import WAFREventEmitter

# Orchestrator integration
from wafr.ag_ui.orchestrator_integration import (
    AGUIOrchestratorWrapper,
    create_agui_orchestrator,
)

# Middleware
from wafr.ag_ui.middleware import (
    Middleware,
    MiddlewareChain,
    RateLimitMiddleware,
    LoggingMiddleware,
    EventTransformMiddleware,
    StreamThrottleMiddleware,
    FilterToolCallsMiddleware,
    ErrorRecoveryMiddleware,
    RetryStrategy,
    create_default_middleware_chain,
)

# Messages
from wafr.ag_ui.messages import (
    BaseMessage,
    UserMessage,
    AssistantMessage,
    ToolMessage,
    ActivityMessage,
    ReviewMessageBuilder,
    review_session_to_messages,
    review_item_to_messages,
)

# Review Messages Integration
from wafr.ag_ui.review_messages_integration import (
    ReviewMessagesIntegration,
    create_review_messages_integration,
)

# Shared State Management
from wafr.ag_ui.shared_state import (
    SharedWAFRState,
    SharedStateManager,
    UserContextState,
    LearningState,
    ProposalState,
    get_shared_state_manager,
)

__all__ = [
    # Core SDK
    "RunAgentInput",
    "Message",
    "Context",
    "Tool",
    "State",
    "WAFRRunAgentInput",
    "WAFRMessage",
    "WAFRContext",
    "WAFRTool",
    "get_wafr_tool",
    "get_all_wafr_tools",
    "WAFR_AGENT_TOOLS",
    "AG_UI_AVAILABLE",
    # Events
    "HITLEventType",
    "HITLEvents",
    "WAFRPipelineStep",
    "ReviewQueueSummary",
    "SynthesisProgress",
    "ReviewDecisionData",
    "ValidationStatus",
    "create_hitl_event",
    # State
    "WAFRState",
    "SessionStatus",
    "ReviewQueueStatus",
    "JSONPatch",
    "PatchOp",
    # Emitter
    "WAFREventEmitter",
    # Orchestrator
    "AGUIOrchestratorWrapper",
    "create_agui_orchestrator",
    # Middleware
    "Middleware",
    "MiddlewareChain",
    "RateLimitMiddleware",
    "LoggingMiddleware",
    "EventTransformMiddleware",
    "StreamThrottleMiddleware",
    "ErrorRecoveryMiddleware",
    "RetryStrategy",
    "create_default_middleware_chain",
    # Messages
    "BaseMessage",
    "UserMessage",
    "AssistantMessage",
    "ToolMessage",
    "ActivityMessage",
    "ReviewMessageBuilder",
    "review_session_to_messages",
    "review_item_to_messages",
    # Review Messages Integration
    "ReviewMessagesIntegration",
    "create_review_messages_integration",
    # Shared State Management
    "SharedWAFRState",
    "SharedStateManager",
    "UserContextState",
    "LearningState",
    "ProposalState",
    "get_shared_state_manager",
]

__version__ = "1.0.0"

