"""
AG-UI Core Integration - Official SDK Wrapper

This module provides integration with the official ag-ui-protocol SDK,
wrapping the core types and events for use in the WAFR project.

Official SDK: https://docs.ag-ui.com/sdk/python/core/overview
"""

from typing import Any, Dict, List, Optional, Union
import logging

logger = logging.getLogger(__name__)

# Try to import official AG-UI SDK
try:
    from ag_ui.core import (
        RunAgentInput,
        Message,
        Context,
        Tool,
        State,
    )
    from ag_ui.core.events import (
        RunStartedEvent,
        RunFinishedEvent,
        RunErrorEvent,
        StepStartedEvent,
        StepFinishedEvent,
        TextMessageStartEvent,
        TextMessageContentEvent,
        TextMessageEndEvent,
        ToolCallStartEvent,
        ToolCallArgsEvent,
        ToolCallEndEvent,
        StateSnapshotEvent,
        StateDeltaEvent,
        MessagesSnapshotEvent,
        RawEvent,
        CustomEvent,
    )
    AG_UI_AVAILABLE = True
    logger.info("Official AG-UI SDK imported successfully")
except ImportError:
    # Fallback: Create minimal stubs if SDK not available
    logger.warning(
        "Official ag-ui-protocol SDK not found. "
        "Install with: pip install ag-ui-protocol"
    )
    AG_UI_AVAILABLE = False
    
    # Minimal stubs for type hints
    class RunAgentInput:
        pass
    
    class Message:
        def __init__(self, content: str, role: str = "assistant"):
            self.content = content
            self.role = role
    
    class Context:
        pass
    
    class Tool:
        pass
    
    class State:
        pass
    
    # Event stubs
    class RunStartedEvent:
        pass
    
    class RunFinishedEvent:
        pass
    
    class RunErrorEvent:
        pass
    
    class StepStartedEvent:
        pass
    
    class StepFinishedEvent:
        pass
    
    class TextMessageStartEvent:
        pass
    
    class TextMessageContentEvent:
        pass
    
    class TextMessageEndEvent:
        pass
    
    class ToolCallStartEvent:
        pass
    
    class ToolCallArgsEvent:
        pass
    
    class ToolCallEndEvent:
        pass
    
    class StateSnapshotEvent:
        pass
    
    class StateDeltaEvent:
        pass
    
    class MessagesSnapshotEvent:
        pass
    
    class RawEvent:
        pass
    
    class CustomEvent:
        pass


# =============================================================================
# WAFR-Specific AG-UI Adapters
# =============================================================================

class WAFRRunAgentInput:
    """
    WAFR-specific RunAgentInput adapter.
    
    Wraps official RunAgentInput with WAFR-specific parameters.
    """
    
    def __init__(
        self,
        transcript: str,
        session_id: str,
        generate_report: bool = True,
        client_name: Optional[str] = None,
    ):
        self.transcript = transcript
        self.session_id = session_id
        self.generate_report = generate_report
        self.client_name = client_name
        
        # Create official RunAgentInput if SDK available
        if AG_UI_AVAILABLE:
            # Map WAFR parameters to AG-UI format
            self._agui_input = RunAgentInput(
                # Map transcript to messages
                messages=[Message(content=transcript, role="user")],
                # Add context
                context={
                    "session_id": session_id,
                    "generate_report": generate_report,
                    "create_wa_workload": True,  # Always enabled
                    "client_name": client_name,
                },
            )
        else:
            self._agui_input = None
    
    def to_agui_input(self) -> Optional[RunAgentInput]:
        """Convert to official RunAgentInput."""
        return self._agui_input


class WAFRMessage:
    """
    WAFR-specific Message adapter.
    
    Wraps official Message with WAFR-specific metadata.
    """
    
    def __init__(
        self,
        content: str,
        role: str = "assistant",
        message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.content = content
        self.role = role
        self.message_id = message_id
        self.metadata = metadata or {}
        
        # Create official Message if SDK available
        if AG_UI_AVAILABLE:
            self._agui_message = Message(
                content=content,
                role=role,
            )
        else:
            self._agui_message = None
    
    def to_agui_message(self) -> Optional[Message]:
        """Convert to official Message."""
        return self._agui_message
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "role": self.role,
            "message_id": self.message_id,
            "metadata": self.metadata,
        }


class WAFRContext:
    """
    WAFR-specific Context adapter.
    
    Wraps official Context with WAFR-specific context data.
    """
    
    def __init__(
        self,
        session_id: str,
        transcript: Optional[str] = None,
        insights: Optional[List[Dict[str, Any]]] = None,
        mappings: Optional[List[Dict[str, Any]]] = None,
        answers: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.session_id = session_id
        self.transcript = transcript
        self.insights = insights or []
        self.mappings = mappings or []
        self.answers = answers or []
        self.metadata = metadata or {}
        
        # Create official Context if SDK available
        if AG_UI_AVAILABLE:
            self._agui_context = Context(
                data={
                    "session_id": session_id,
                    "transcript": transcript,
                    "insights": insights,
                    "mappings": mappings,
                    "answers": answers,
                    **metadata,
                }
            )
        else:
            self._agui_context = None
    
    def to_agui_context(self) -> Optional[Context]:
        """Convert to official Context."""
        return self._agui_context
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "transcript": self.transcript,
            "insights": self.insights,
            "mappings": self.mappings,
            "answers": self.answers,
            "metadata": self.metadata,
        }


class WAFRTool:
    """
    WAFR-specific Tool adapter.
    
    Represents a WAFR agent as an AG-UI Tool.
    """
    
    def __init__(
        self,
        name: str,
        description: str,
        agent_type: str,  # understanding, mapping, confidence, etc.
        parameters: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.description = description
        self.agent_type = agent_type
        self.parameters = parameters or {}
        
        # Create official Tool if SDK available
        if AG_UI_AVAILABLE:
            self._agui_tool = Tool(
                name=name,
                description=description,
                parameters=parameters,
            )
        else:
            self._agui_tool = None
    
    def to_agui_tool(self) -> Optional[Tool]:
        """Convert to official Tool."""
        return self._agui_tool
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "agent_type": self.agent_type,
            "parameters": self.parameters,
        }


# =============================================================================
# WAFR Agent Tools Registry
# =============================================================================

WAFR_AGENT_TOOLS = {
    "understanding": WAFRTool(
        name="understanding_agent",
        description="Extracts insights and key information from workshop transcripts",
        agent_type="understanding",
        parameters={
            "type": "object",
            "properties": {
                "transcript": {"type": "string", "description": "Workshop transcript text"},
            },
        },
    ),
    "mapping": WAFRTool(
        name="mapping_agent",
        description="Maps extracted insights to AWS Well-Architected Framework questions",
        agent_type="mapping",
        parameters={
            "type": "object",
            "properties": {
                "insights": {"type": "array", "items": {"type": "object"}},
                "schema": {"type": "object", "description": "WAFR schema"},
            },
        },
    ),
    "confidence": WAFRTool(
        name="confidence_agent",
        description="Validates evidence and assigns confidence scores to mapped answers",
        agent_type="confidence",
        parameters={
            "type": "object",
            "properties": {
                "mappings": {"type": "array", "items": {"type": "object"}},
                "transcript": {"type": "string"},
            },
        },
    ),
    "gap_detection": WAFRTool(
        name="gap_detection_agent",
        description="Identifies gaps in WAFR coverage (unanswered questions)",
        agent_type="gap_detection",
        parameters={
            "type": "object",
            "properties": {
                "validated_answers": {"type": "array", "items": {"type": "object"}},
                "schema": {"type": "object"},
            },
        },
    ),
    "answer_synthesis": WAFRTool(
        name="answer_synthesis_agent",
        description="Synthesizes intelligent answers for gap questions using LLM reasoning",
        agent_type="answer_synthesis",
        parameters={
            "type": "object",
            "properties": {
                "gaps": {"type": "array", "items": {"type": "object"}},
                "transcript": {"type": "string"},
                "insights": {"type": "array", "items": {"type": "object"}},
            },
        },
    ),
    "scoring": WAFRTool(
        name="scoring_agent",
        description="Scores and ranks answers based on quality and completeness",
        agent_type="scoring",
        parameters={
            "type": "object",
            "properties": {
                "answers": {"type": "array", "items": {"type": "object"}},
            },
        },
    ),
    "report": WAFRTool(
        name="report_agent",
        description="Generates comprehensive PDF reports from assessment results",
        agent_type="report",
        parameters={
            "type": "object",
            "properties": {
                "answers": {"type": "array", "items": {"type": "object"}},
                "session_id": {"type": "string"},
            },
        },
    ),
    "wa_tool": WAFRTool(
        name="wa_tool_agent",
        description="Integrates with AWS Well-Architected Tool API for workload management",
        agent_type="wa_tool",
        parameters={
            "type": "object",
            "properties": {
                "workload_id": {"type": "string"},
                "answers": {"type": "array", "items": {"type": "object"}},
                "client_name": {"type": "string"},
            },
        },
    ),
}


def get_wafr_tool(agent_type: str) -> Optional[WAFRTool]:
    """Get WAFR tool by agent type."""
    return WAFR_AGENT_TOOLS.get(agent_type)


def get_all_wafr_tools() -> List[WAFRTool]:
    """Get all WAFR agent tools."""
    return list(WAFR_AGENT_TOOLS.values())


__all__ = [
    # Official SDK imports
    "RunAgentInput",
    "Message",
    "Context",
    "Tool",
    "State",
    "RunStartedEvent",
    "RunFinishedEvent",
    "RunErrorEvent",
    "StepStartedEvent",
    "StepFinishedEvent",
    "TextMessageStartEvent",
    "TextMessageContentEvent",
    "TextMessageEndEvent",
    "ToolCallStartEvent",
    "ToolCallArgsEvent",
    "ToolCallEndEvent",
    "StateSnapshotEvent",
    "StateDeltaEvent",
    "MessagesSnapshotEvent",
    "RawEvent",
    "CustomEvent",
    # WAFR adapters
    "WAFRRunAgentInput",
    "WAFRMessage",
    "WAFRContext",
    "WAFRTool",
    # Utilities
    "WAFR_AGENT_TOOLS",
    "get_wafr_tool",
    "get_all_wafr_tools",
    "AG_UI_AVAILABLE",
]

