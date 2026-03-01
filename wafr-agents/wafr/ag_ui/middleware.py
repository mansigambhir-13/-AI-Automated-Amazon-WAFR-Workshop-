"""
AG-UI Middleware System for WAFR

Provides middleware infrastructure for transforming, filtering, and augmenting
event streams in the WAFR agent system.

Based on AG-UI middleware patterns: https://docs.ag-ui.com/concepts/middleware
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from wafr.ag_ui.emitter import BaseEvent, WAFREventEmitter, EventType
else:
    # Import at runtime to avoid circular import
    BaseEvent = None
    WAFREventEmitter = None
    EventType = None

logger = logging.getLogger(__name__)


# =============================================================================
# Middleware Base Classes
# =============================================================================

class Middleware(ABC):
    """
    Base class for AG-UI middleware.
    
    Middleware sits between agent execution and event consumer, allowing
    transformation, filtering, and augmentation of event streams.
    """
    
    def __init__(self, name: Optional[str] = None):
        """
        Initialize middleware.
        
        Args:
            name: Optional name for this middleware (for logging)
        """
        self.name = name or self.__class__.__name__
        self._next: Optional['Middleware'] = None
    
    def set_next(self, middleware: 'Middleware') -> None:
        """Set next middleware in chain."""
        self._next = middleware
    
    @abstractmethod
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """
        Process an event.
        
        Args:
            event: Event to process
            context: Processing context (session_id, agent_name, etc.)
            
        Returns:
            Processed event (or None to filter out)
        """
        pass
    
    async def handle(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """
        Handle event and pass to next middleware.
        
        Args:
            event: Event to handle
            context: Processing context
            
        Returns:
            Processed event or None
        """
        # Process this middleware
        processed = await self.process(event, context)
        
        if processed is None:
            return None  # Filtered out
        
        # Pass to next middleware
        if self._next:
            return await self._next.handle(processed, context)
        
        return processed


class MiddlewareFunction:
    """
    Function-based middleware wrapper.
    
    Allows simple functions to be used as middleware.
    """
    
    def __init__(self, func: Callable[[Any, Dict[str, Any]], Any], name: Optional[str] = None):  # BaseEvent
        """
        Initialize function middleware.
        
        Args:
            func: Function that takes (event, context) and returns event or None
            name: Optional name for logging
        """
        self.func = func
        self.name = name or func.__name__
    
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """Process event using function."""
        result = self.func(event, context)
        if asyncio.iscoroutine(result):
            return await result
        return result


# =============================================================================
# Middleware Chain
# =============================================================================

class MiddlewareChain:
    """
    Chain of middleware to process events.
    
    Events flow through middleware in order, with each middleware
    able to transform or filter events.
    """
    
    def __init__(self, middleware: List[Middleware]):
        """
        Initialize middleware chain.
        
        Args:
            middleware: List of middleware in execution order
        """
        self.middleware = middleware
        self._build_chain()
    
    def _build_chain(self) -> None:
        """Build middleware chain by linking them together."""
        for i in range(len(self.middleware) - 1):
            self.middleware[i].set_next(self.middleware[i + 1])
    
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """
        Process event through middleware chain.
        
        Args:
            event: Event to process
            context: Processing context
            
        Returns:
            Processed event or None if filtered out
        """
        if not self.middleware:
            return event
        
        return await self.middleware[0].handle(event, context)
    
    def add(self, middleware: Middleware) -> None:
        """Add middleware to end of chain."""
        if self.middleware:
            self.middleware[-1].set_next(middleware)
        self.middleware.append(middleware)


# =============================================================================
# Rate Limiting Middleware
# =============================================================================

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    
    min_interval: float = 0.2  # Minimum seconds between calls (5 req/sec)
    per_agent: bool = True  # Track rate limits per agent
    per_model: bool = True  # Track rate limits per model
    burst_size: int = 10  # Allow burst of N requests


class RateLimitMiddleware(Middleware):
    """
    Rate limiting middleware to prevent AWS Bedrock API throttling.
    
    Tracks last call time per agent/model and enforces minimum intervals.
    """
    
    def __init__(
        self,
        min_interval: float = 0.2,
        per_agent: bool = True,
        per_model: bool = True,
        burst_size: int = 10,
        name: Optional[str] = None,
    ):
        """
        Initialize rate limit middleware.
        
        Args:
            min_interval: Minimum seconds between calls
            per_agent: Track rate limits per agent
            per_model: Track rate limits per model
            burst_size: Allow burst of N requests
            name: Optional name
        """
        super().__init__(name)
        self.config = RateLimitConfig(
            min_interval=min_interval,
            per_agent=per_agent,
            per_model=per_model,
            burst_size=burst_size,
        )
        
        # Track last call times
        self._last_calls: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    def _get_rate_limit_key(self, context: Dict[str, Any]) -> str:
        """Get rate limit key based on context."""
        parts = []
        if self.config.per_agent:
            parts.append(context.get("agent_name", "unknown"))
        if self.config.per_model:
            parts.append(context.get("model_id", "unknown"))
        return ":".join(parts) if parts else "default"
    
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """
        Process event with rate limiting.
        
        Only rate limits TOOL_CALL_START events (actual API calls).
        """
        # Only rate limit tool call starts (actual API invocations)
        # Import EventType at runtime to avoid circular import
        from wafr.ag_ui.emitter import EventType as ET
        if event.type != ET.TOOL_CALL_START:
            return event
        
        async with self._lock:
            key = self._get_rate_limit_key(context)
            now = time.time()
            
            # Clean old entries (keep last burst_size)
            calls = self._last_calls[key]
            calls = [t for t in calls if now - t < self.config.min_interval * self.config.burst_size]
            calls.append(now)
            self._last_calls[key] = calls[-self.config.burst_size:]
            
            # Check if we need to wait
            if len(calls) > 1:
                time_since_last = now - calls[-2]
                if time_since_last < self.config.min_interval:
                    wait_time = self.config.min_interval - time_since_last
                    logger.debug(
                        f"Rate limiting: waiting {wait_time:.3f}s "
                        f"(key={key}, interval={self.config.min_interval})"
                    )
                    await asyncio.sleep(wait_time)
        
        return event


# =============================================================================
# Logging Middleware
# =============================================================================

class LoggingMiddleware(Middleware):
    """
    Logging middleware for structured event logging.
    
    Logs all events with metadata for debugging and monitoring.
    """
    
    def __init__(
        self,
        log_level: str = "INFO",
        include_metadata: bool = True,
        log_event_types: Optional[Set[str]] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize logging middleware.
        
        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
            include_metadata: Include event metadata in logs
            log_event_types: Set of event types to log (None = all)
            name: Optional name
        """
        super().__init__(name)
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.include_metadata = include_metadata
        self.log_event_types = log_event_types
        self.logger = logging.getLogger(f"{__name__}.{self.name}")
    
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """Log event."""
        # Filter by event type if specified
        if self.log_event_types and event.type not in self.log_event_types:
            return event
        
        # Build log message
        log_data = {
            "event_type": event.type,
            "timestamp": event.timestamp,
        }
        
        if self.include_metadata:
            log_data.update({
                "session_id": context.get("session_id"),
                "agent_name": context.get("agent_name"),
                "run_id": context.get("run_id"),
            })
        
        # Log based on level
        if self.log_level <= logging.DEBUG:
            self.logger.debug(f"Event: {event.type}", extra=log_data)
        elif self.log_level <= logging.INFO:
            self.logger.info(f"Event: {event.type}", extra=log_data)
        elif self.log_level <= logging.WARNING:
            # Import EventType at runtime to avoid circular import
            from wafr.ag_ui.emitter import EventType as ET
            if event.type in [ET.RUN_ERROR, ET.TOOL_CALL_END]:
                self.logger.warning(f"Event: {event.type}", extra=log_data)
        
        return event


# =============================================================================
# Event Transformation Middleware
# =============================================================================

class EventTransformMiddleware(Middleware):
    """
    Event transformation middleware to enrich events with metadata.
    
    Adds session IDs, timestamps, agent metadata, and routing info to events.
    """
    
    def __init__(
        self,
        add_session_id: bool = True,
        add_timestamps: bool = True,
        add_agent_metadata: bool = True,
        add_routing_info: bool = True,
        name: Optional[str] = None,
    ):
        """
        Initialize transformation middleware.
        
        Args:
            add_session_id: Add session_id to event metadata
            add_timestamps: Ensure timestamps are present
            add_agent_metadata: Add agent name/type to metadata
            add_routing_info: Add routing decision info if available
            name: Optional name
        """
        super().__init__(name)
        self.add_session_id = add_session_id
        self.add_timestamps = add_timestamps
        self.add_agent_metadata = add_agent_metadata
        self.add_routing_info = add_routing_info
    
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """Transform event by adding metadata."""
        # Get event dict
        event_dict = event.to_dict()
        
        # Ensure metadata field exists in event dict
        if "metadata" not in event_dict:
            event_dict["metadata"] = {}
        
        metadata = event_dict["metadata"]
        
        # Add session ID
        if self.add_session_id and "session_id" in context:
            metadata["session_id"] = context["session_id"]
        
        # Ensure timestamp
        if self.add_timestamps and "timestamp" not in event_dict:
            event_dict["timestamp"] = datetime.utcnow().timestamp()
            event.timestamp = event_dict["timestamp"]
        
        # Add agent metadata
        if self.add_agent_metadata:
            if "agent_name" in context:
                metadata["agent_name"] = context["agent_name"]
            if "agent_type" in context:
                metadata["agent_type"] = context["agent_type"]
        
        # Add routing info
        if self.add_routing_info and "routing_decision" in context:
            metadata["routing"] = context["routing_decision"]
        
        # Update event's metadata if it has a metadata attribute
        # Most events don't have metadata field, so we'll store it in context
        # and the emitter can add it when serializing
        # For now, we store enriched metadata in context for later use
        context["_enriched_metadata"] = metadata
        
        # Return event (metadata will be added during serialization if needed)
        return event


# =============================================================================
# Stream Control/Throttling Middleware
# =============================================================================

class StreamThrottleMiddleware(Middleware):
    """
    Stream throttling middleware to prevent UI overload.
    
    Throttles rapid event streams, especially TEXT_MESSAGE_CONTENT events.
    """
    
    def __init__(
        self,
        throttle_time_ms: float = 50.0,
        event_types: Optional[List[str]] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize throttle middleware.
        
        Args:
            throttle_time_ms: Minimum milliseconds between throttled events
            event_types: Event types to throttle (None = all)
            name: Optional name
        """
        super().__init__(name)
        self.throttle_time = throttle_time_ms / 1000.0  # Convert to seconds
        self.event_types = set(event_types) if event_types else None
        self._last_event_time: Dict[str, float] = {}
        self._lock = asyncio.Lock()
    
    def _should_throttle(self, event_type: str) -> bool:
        """Check if event type should be throttled."""
        if self.event_types is None:
            return True
        return event_type in self.event_types
    
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """Throttle event if needed."""
        if not self._should_throttle(event.type):
            return event
        
        async with self._lock:
            now = time.time()
            last_time = self._last_event_time.get(event.type, 0)
            
            time_since_last = now - last_time
            if time_since_last < self.throttle_time:
                wait_time = self.throttle_time - time_since_last
                await asyncio.sleep(wait_time)
            
            self._last_event_time[event.type] = time.time()
        
        return event


# =============================================================================
# Tool Call Filtering Middleware
# =============================================================================

class FilterToolCallsMiddleware(Middleware):
    """
    Filter tool calls middleware to control which tool calls are allowed.
    
    Filters TOOL_CALL_START events based on allowed/blocked tool names.
    Useful for controlling which agents can be invoked.
    """
    
    def __init__(
        self,
        allowed_tool_calls: Optional[Set[str]] = None,
        blocked_tool_calls: Optional[Set[str]] = None,
        filter_by_pattern: Optional[List[str]] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize tool call filter middleware.
        
        Args:
            allowed_tool_calls: Set of allowed tool names (whitelist). If None, all allowed.
            blocked_tool_calls: Set of blocked tool names (blacklist). If None, none blocked.
            filter_by_pattern: List of patterns to match (e.g., ["*_agent", "confidence*"])
            name: Optional name for logging
        """
        super().__init__(name)
        self.allowed_tool_calls = allowed_tool_calls or set()
        self.blocked_tool_calls = blocked_tool_calls or set()
        self.filter_by_pattern = filter_by_pattern or []
        
        # If allowed list is empty, allow all (unless blocked)
        self.use_whitelist = len(self.allowed_tool_calls) > 0
    
    def _matches_pattern(self, tool_name: str, pattern: str) -> bool:
        """Check if tool name matches pattern (supports * wildcard)."""
        import fnmatch
        return fnmatch.fnmatch(tool_name.lower(), pattern.lower())
    
    def _is_tool_allowed(self, tool_name: str) -> bool:
        """
        Check if tool call is allowed.
        
        Args:
            tool_name: Name of the tool/agent
            
        Returns:
            True if allowed, False if filtered out
        """
        tool_name_lower = tool_name.lower()
        
        # Check blacklist first (highest priority)
        for blocked in self.blocked_tool_calls:
            if self._matches_pattern(tool_name_lower, blocked):
                logger.debug(f"Tool call '{tool_name}' blocked by blacklist pattern: {blocked}")
                return False
        
        # Check whitelist if enabled
        if self.use_whitelist:
            # Check exact matches first
            if tool_name_lower in {t.lower() for t in self.allowed_tool_calls}:
                return True
            
            # Check pattern matches
            for pattern in self.allowed_tool_calls:
                if self._matches_pattern(tool_name_lower, pattern):
                    return True
            
            # Check filter_by_pattern
            for pattern in self.filter_by_pattern:
                if self._matches_pattern(tool_name_lower, pattern):
                    return True
            
            # Not in whitelist
            logger.debug(f"Tool call '{tool_name}' not in whitelist, filtering out")
            return False
        
        # No whitelist, check filter_by_pattern if provided
        if self.filter_by_pattern:
            for pattern in self.filter_by_pattern:
                if self._matches_pattern(tool_name_lower, pattern):
                    return True
            # If filter_by_pattern is provided but no match, block
            logger.debug(f"Tool call '{tool_name}' doesn't match any filter pattern")
            return False
        
        # No restrictions, allow all
        return True
    
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """
        Filter tool call events.
        
        Filters TOOL_CALL_START events and related events (ARGS, RESULT, END)
        for blocked tool calls.
        """
        # Import EventType at runtime to avoid circular import
        from wafr.ag_ui.emitter import EventType as ET
        
        # Initialize blocked tool calls set in context
        if "_blocked_tool_calls" not in context:
            context["_blocked_tool_calls"] = set()
        
        # Filter TOOL_CALL_START events
        if event.type == ET.TOOL_CALL_START:
            # Extract tool name from event
            tool_name = getattr(event, "tool_name", "")
            if not tool_name:
                # Try to get from context
                tool_name = context.get("tool_name", context.get("agent_name", ""))
            
            if not tool_name:
                logger.warning("Tool call event has no tool_name, allowing through")
                return event
            
            # Check if tool is allowed
            if not self._is_tool_allowed(tool_name):
                logger.info(
                    f"Filtering out tool call: {tool_name} "
                    f"(allowed={self.allowed_tool_calls}, blocked={self.blocked_tool_calls})"
                )
                # Store blocked tool_call_id so we can filter related events
                tool_call_id = getattr(event, "tool_call_id", "")
                if tool_call_id:
                    context["_blocked_tool_calls"].add(tool_call_id)
                return None  # Filter out
            
            return event
        
        # Filter related events (ARGS, RESULT, END) for blocked tool calls
        tool_call_events = [
            ET.TOOL_CALL_ARGS,
            ET.TOOL_CALL_RESULT,
            ET.TOOL_CALL_END,
            ET.TOOL_CALL_CHUNK,
        ]
        
        if event.type in tool_call_events:
            tool_call_id = getattr(event, "tool_call_id", "")
            if tool_call_id and tool_call_id in context["_blocked_tool_calls"]:
                logger.debug(f"Filtering out {event.type} for blocked tool_call_id: {tool_call_id}")
                return None  # Filter out
        
        return event


# =============================================================================
# Error Handling/Recovery Middleware
# =============================================================================

@dataclass
class RetryStrategy:
    """Retry strategy configuration."""
    
    max_retries: int = 3
    initial_delay: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay: float = 60.0


class ErrorRecoveryMiddleware(Middleware):
    """
    Error handling middleware for centralized error recovery.
    
    Handles errors in event processing and implements retry strategies.
    """
    
    def __init__(
        self,
        retry_strategies: Optional[Dict[str, RetryStrategy]] = None,
        fallback_agents: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize error recovery middleware.
        
        Args:
            retry_strategies: Map of error types to retry strategies
            fallback_agents: Map of agent names to fallback agents
            name: Optional name
        """
        super().__init__(name)
        self.retry_strategies = retry_strategies or {}
        self.fallback_agents = fallback_agents or {}
        self.default_strategy = RetryStrategy()
    
    def _get_retry_strategy(self, error_type: str) -> RetryStrategy:
        """Get retry strategy for error type."""
        return self.retry_strategies.get(error_type, self.default_strategy)
    
    async def process(
        self,
        event: Any,  # BaseEvent
        context: Dict[str, Any],
    ) -> Optional[Any]:  # Optional[BaseEvent]
        """
        Process event with error handling.
        
        Note: This middleware handles errors in event processing.
        For agent execution errors, see agent-level error handling.
        """
        try:
            return event
        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"Error processing event {event.type}: {error_type} - {e}",
                exc_info=True
            )
            
            # Check if we should retry
            strategy = self._get_retry_strategy(error_type)
            
            # For now, just log and pass through
            # Actual retry logic would be implemented at agent level
            # This middleware is for event processing errors
            
            return event


# =============================================================================
# Middleware Factory
# =============================================================================

def create_default_middleware_chain(
    session_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    rate_limit_interval: float = 0.2,
    log_level: str = "INFO",
    allowed_tool_calls: Optional[Set[str]] = None,
    blocked_tool_calls: Optional[Set[str]] = None,
) -> MiddlewareChain:
    """
    Create default middleware chain for WAFR.
    
    Args:
        session_id: Session identifier
        agent_name: Agent name
        rate_limit_interval: Rate limit interval in seconds
        log_level: Logging level
        allowed_tool_calls: Optional set of allowed tool names (whitelist)
        blocked_tool_calls: Optional set of blocked tool names (blacklist)
        
    Returns:
        Configured middleware chain
    """
    context = {
        "session_id": session_id,
        "agent_name": agent_name,
    }
    
    # Import EventType at runtime to avoid circular import
    from wafr.ag_ui.emitter import EventType as ET
    
    middleware = [
        # 1. Rate limiting (first - prevent API throttling)
        RateLimitMiddleware(
            min_interval=rate_limit_interval,
            per_agent=True,
            name="rate_limit",
        ),
        
        # 2. Logging (log everything)
        LoggingMiddleware(
            log_level=log_level,
            include_metadata=True,
            name="logging",
        ),
        
        # 3. Event transformation (enrich events)
        EventTransformMiddleware(
            add_session_id=True,
            add_timestamps=True,
            add_agent_metadata=True,
            add_routing_info=True,
            name="transform",
        ),
        
        # 4. Stream throttling (UI performance)
        StreamThrottleMiddleware(
            throttle_time_ms=50.0,
            event_types=[ET.TEXT_MESSAGE_CONTENT, ET.TEXT_MESSAGE_CHUNK],
            name="throttle",
        ),
        
        # 5. Tool call filtering (control which agents can be invoked)
        FilterToolCallsMiddleware(
            allowed_tool_calls=allowed_tool_calls,
            blocked_tool_calls=blocked_tool_calls,
            name="filter_tool_calls",
        ),
        
        # 6. Error handling (recovery)
        ErrorRecoveryMiddleware(
            retry_strategies={
                "ThrottlingException": RetryStrategy(max_retries=5, initial_delay=1.0),
                "ModelInvocationError": RetryStrategy(max_retries=3, initial_delay=0.5),
            },
            name="error_recovery",
        ),
    ]
    
    return MiddlewareChain(middleware)
