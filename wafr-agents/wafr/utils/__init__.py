"""
Production-Ready Utilities

Provides:
- Error handling with retries and circuit breakers
- Concurrency utilities for parallel processing
- Resource management
"""

from wafr.utils.error_handling import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    ErrorCategory,
    ErrorInfo,
    RetryConfig,
    async_retry_with_backoff,
    async_with_fallback,
    classify_error,
    retry_with_backoff,
    with_fallback,
)
from wafr.utils.concurrency import (
    ParallelProcessor,
    RateLimiter,
    ResourcePool,
    async_with_timeout,
    process_batch_async,
    process_parallel_async,
    with_timeout,
)

from wafr.utils.s3_storage import (
    S3ReportStorage,
    get_s3_storage,
)

__all__ = [
    # Error handling
    "ErrorCategory",
    "ErrorInfo",
    "RetryConfig",
    "retry_with_backoff",
    "async_retry_with_backoff",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "classify_error",
    "with_fallback",
    "async_with_fallback",
    # Concurrency
    "ParallelProcessor",
    "RateLimiter",
    "ResourcePool",
    "process_batch_async",
    "process_parallel_async",
    "with_timeout",
    "async_with_timeout",
    # S3 Storage
    "S3ReportStorage",
    "get_s3_storage",
]
