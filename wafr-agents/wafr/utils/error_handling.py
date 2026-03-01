"""
Production-Ready Error Handling System

Provides:
- Retry mechanisms with exponential backoff
- Circuit breakers for fault tolerance
- Graceful degradation
- Error classification and recovery strategies
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, Type, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Error Classification
# =============================================================================

class ErrorCategory(Enum):
    """Error categories for different handling strategies."""
    
    TRANSIENT = "transient"  # Retryable (network, timeout)
    PERMANENT = "permanent"  # Not retryable (validation, auth)
    THROTTLED = "throttled"  # Rate limited (backoff required)
    RESOURCE_EXHAUSTED = "resource_exhausted"  # Out of resources
    UNKNOWN = "unknown"  # Unknown error type


@dataclass
class ErrorInfo:
    """Error information for classification."""
    
    category: ErrorCategory
    retryable: bool
    backoff_required: bool
    max_retries: int = 3
    initial_delay: float = 1.0


def classify_error(error: Exception) -> ErrorInfo:
    """
    Classify error and determine handling strategy.
    
    Args:
        error: Exception to classify
        
    Returns:
        ErrorInfo with handling strategy
    """
    error_str = str(error).lower()
    error_type = type(error).__name__
    
    # Transient errors (retryable)
    if any(keyword in error_str for keyword in [
        "timeout", "connection", "network", "temporary",
        "service unavailable", "503", "502", "504"
    ]):
        return ErrorInfo(
            category=ErrorCategory.TRANSIENT,
            retryable=True,
            backoff_required=True,
            max_retries=5,
            initial_delay=1.0,
        )
    
    # Throttled errors (backoff required)
    if any(keyword in error_str for keyword in [
        "throttle", "rate limit", "429", "too many requests",
        "quota", "limit exceeded"
    ]):
        return ErrorInfo(
            category=ErrorCategory.THROTTLED,
            retryable=True,
            backoff_required=True,
            max_retries=3,
            initial_delay=5.0,
        )
    
    # Resource exhausted
    if any(keyword in error_str for keyword in [
        "resource", "memory", "out of", "capacity"
    ]):
        return ErrorInfo(
            category=ErrorCategory.RESOURCE_EXHAUSTED,
            retryable=True,
            backoff_required=True,
            max_retries=2,
            initial_delay=10.0,
        )
    
    # Permanent errors (not retryable)
    if any(keyword in error_str for keyword in [
        "validation", "invalid", "unauthorized", "forbidden",
        "404", "400", "401", "403"
    ]):
        return ErrorInfo(
            category=ErrorCategory.PERMANENT,
            retryable=False,
            backoff_required=False,
            max_retries=0,
        )
    
    # Unknown - conservative approach
    return ErrorInfo(
        category=ErrorCategory.UNKNOWN,
        retryable=True,
        backoff_required=True,
        max_retries=2,
        initial_delay=2.0,
    )


# =============================================================================
# Retry Mechanism
# =============================================================================

@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on: Optional[tuple[Type[Exception], ...]] = None
    retry_on_result: Optional[Callable[[Any], bool]] = None


def retry_with_backoff(
    config: Optional[RetryConfig] = None,
    error_classifier: Optional[Callable[[Exception], ErrorInfo]] = None,
) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        config: Retry configuration
        error_classifier: Optional custom error classifier
        
    Returns:
        Decorated function with retry logic
    """
    config = config or RetryConfig()
    error_classifier = error_classifier or classify_error
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_error = None
            
            for attempt in range(config.max_attempts):
                try:
                    result = func(*args, **kwargs)
                    
                    # Check if result indicates retry needed
                    if config.retry_on_result and config.retry_on_result(result):
                        if attempt < config.max_attempts - 1:
                            delay = _calculate_delay(attempt, config)
                            logger.warning(
                                f"{func.__name__} result indicates retry needed "
                                f"(attempt {attempt + 1}/{config.max_attempts}), "
                                f"waiting {delay:.2f}s"
                            )
                            time.sleep(delay)
                            continue
                    
                    return result
                    
                except Exception as e:
                    last_error = e
                    
                    # Check if error is retryable
                    error_info = error_classifier(e)
                    
                    if not error_info.retryable:
                        logger.error(f"{func.__name__} failed with non-retryable error: {e}")
                        raise
                    
                    # Check if error type matches retry_on
                    if config.retry_on and not isinstance(e, config.retry_on):
                        logger.error(f"{func.__name__} failed with non-retryable error type: {e}")
                        raise
                    
                    if attempt < config.max_attempts - 1:
                        delay = _calculate_delay(attempt, config, error_info)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{config.max_attempts}): {e}. "
                            f"Retrying in {delay:.2f}s"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"{func.__name__} failed after {config.max_attempts} attempts: {e}")
                        raise
            
            # Should never reach here, but just in case
            if last_error:
                raise last_error
            raise RuntimeError(f"{func.__name__} failed after {config.max_attempts} attempts")
        
        return wrapper
    
    return decorator


def async_retry_with_backoff(
    config: Optional[RetryConfig] = None,
    error_classifier: Optional[Callable[[Exception], ErrorInfo]] = None,
) -> Callable:
    """
    Decorator for retrying async functions with exponential backoff.
    
    Args:
        config: Retry configuration
        error_classifier: Optional custom error classifier
        
    Returns:
        Decorated async function with retry logic
    """
    config = config or RetryConfig()
    error_classifier = error_classifier or classify_error
    
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error = None
            
            for attempt in range(config.max_attempts):
                try:
                    result = await func(*args, **kwargs)
                    
                    # Check if result indicates retry needed
                    if config.retry_on_result and config.retry_on_result(result):
                        if attempt < config.max_attempts - 1:
                            delay = _calculate_delay(attempt, config)
                            logger.warning(
                                f"{func.__name__} result indicates retry needed "
                                f"(attempt {attempt + 1}/{config.max_attempts}), "
                                f"waiting {delay:.2f}s"
                            )
                            await asyncio.sleep(delay)
                            continue
                    
                    return result
                    
                except Exception as e:
                    last_error = e
                    
                    # Check if error is retryable
                    error_info = error_classifier(e)
                    
                    if not error_info.retryable:
                        logger.error(f"{func.__name__} failed with non-retryable error: {e}")
                        raise
                    
                    # Check if error type matches retry_on
                    if config.retry_on_result and not isinstance(e, config.retry_on):
                        logger.error(f"{func.__name__} failed with non-retryable error type: {e}")
                        raise
                    
                    if attempt < config.max_attempts - 1:
                        delay = _calculate_delay(attempt, config, error_info)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{config.max_attempts}): {e}. "
                            f"Retrying in {delay:.2f}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"{func.__name__} failed after {config.max_attempts} attempts: {e}")
                        raise
            
            # Should never reach here, but just in case
            if last_error:
                raise last_error
            raise RuntimeError(f"{func.__name__} failed after {config.max_attempts} attempts")
        
        return wrapper
    
    return decorator


def _calculate_delay(
    attempt: int,
    config: RetryConfig,
    error_info: Optional[ErrorInfo] = None,
) -> float:
    """Calculate delay for retry attempt."""
    if error_info:
        base_delay = error_info.initial_delay
    else:
        base_delay = config.initial_delay
    
    # Exponential backoff
    delay = base_delay * (config.exponential_base ** attempt)
    
    # Cap at max delay
    delay = min(delay, config.max_delay)
    
    # Add jitter to prevent thundering herd
    if config.jitter:
        import random
        jitter = random.uniform(0, delay * 0.1)
        delay += jitter
    
    return delay


# =============================================================================
# Circuit Breaker
# =============================================================================

class CircuitState(Enum):
    """Circuit breaker states."""
    
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    
    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 2  # Successes before closing
    timeout: float = 60.0  # Time before half-open
    expected_exception: tuple[Type[Exception], ...] = (Exception,)


class CircuitBreaker:
    """
    Circuit breaker for fault tolerance.
    
    Prevents cascading failures by stopping requests when service is failing.
    """
    
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize circuit breaker.
        
        Args:
            name: Name of the circuit breaker
            config: Configuration
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute function through circuit breaker.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open or function fails
        """
        async with self._lock:
            # Check if circuit should transition
            await self._check_state()
            
            # Reject if circuit is open
            if self.state == CircuitState.OPEN:
                raise RuntimeError(
                    f"Circuit breaker '{self.name}' is OPEN. "
                    f"Service is unavailable."
                )
        
        # Execute function
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # Record success
            async with self._lock:
                await self._record_success()
            
            return result
            
        except self.config.expected_exception as e:
            # Record failure
            async with self._lock:
                await self._record_failure()
            raise
    
    async def _check_state(self) -> None:
        """Check and update circuit breaker state."""
        current_time = time.time()
        
        if self.state == CircuitState.OPEN:
            # Check if timeout has passed
            if (self.last_failure_time and
                current_time - self.last_failure_time >= self.config.timeout):
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN")
        
        elif self.state == CircuitState.HALF_OPEN:
            # Already checked, will transition based on results
            pass
    
    async def _record_success(self) -> None:
        """Record successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                logger.info(f"Circuit breaker '{self.name}' transitioned to CLOSED")
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0
    
    async def _record_failure(self) -> None:
        """Record failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            # Any failure in half-open goes back to open
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker '{self.name}' transitioned to OPEN (half-open failure)")
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker '{self.name}' transitioned to OPEN "
                    f"({self.failure_count} failures)"
                )


# =============================================================================
# Graceful Degradation
# =============================================================================

def with_fallback(
    fallback_func: Callable[..., T],
    fallback_on: Optional[tuple[Type[Exception], ...]] = None,
) -> Callable:
    """
    Decorator for graceful degradation with fallback function.
    
    Args:
        fallback_func: Fallback function to call on failure
        fallback_on: Exception types to catch (default: all)
        
    Returns:
        Decorated function with fallback
    """
    fallback_on = fallback_on or (Exception,)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except fallback_on as e:
                logger.warning(
                    f"{func.__name__} failed, using fallback: {e}",
                    exc_info=True
                )
                return fallback_func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def async_with_fallback(
    fallback_func: Callable[..., Any],
    fallback_on: Optional[tuple[Type[Exception], ...]] = None,
) -> Callable:
    """
    Decorator for graceful degradation with async fallback function.
    
    Args:
        fallback_func: Async fallback function to call on failure
        fallback_on: Exception types to catch (default: all)
        
    Returns:
        Decorated async function with fallback
    """
    fallback_on = fallback_on or (Exception,)
    
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except fallback_on as e:
                logger.warning(
                    f"{func.__name__} failed, using fallback: {e}",
                    exc_info=True
                )
                if asyncio.iscoroutinefunction(fallback_func):
                    return await fallback_func(*args, **kwargs)
                else:
                    return fallback_func(*args, **kwargs)
        
        return wrapper
    
    return decorator
