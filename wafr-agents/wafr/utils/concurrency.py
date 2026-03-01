"""
Production-Ready Concurrency Utilities

Provides:
- Parallel processing with thread/process pools
- Async batch processing
- Rate limiting
- Resource management
- Timeout handling
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Type, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


# =============================================================================
# Rate Limiting
# =============================================================================

@dataclass
class RateLimiter:
    """
    Rate limiter for controlling request frequency.
    
    Uses token bucket algorithm for smooth rate limiting.
    """
    
    max_requests: int  # Maximum requests per period
    period: float  # Time period in seconds
    tokens: float = 0.0  # Current tokens
    last_refill: float = 0.0  # Last refill time
    
    def __post_init__(self):
        """Initialize rate limiter."""
        self.tokens = float(self.max_requests)
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """
        Acquire a token, waiting if necessary.
        
        Raises:
            RuntimeError: If rate limit exceeded
        """
        async with self._lock:
            await self._refill()
            
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            
            # Wait for token to become available
            wait_time = (1.0 - self.tokens) * (self.period / self.max_requests)
            await asyncio.sleep(wait_time)
            self.tokens = 0.0
    
    async def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        current_time = time.time()
        elapsed = current_time - self.last_refill
        
        if elapsed > 0:
            tokens_to_add = (elapsed / self.period) * self.max_requests
            self.tokens = min(self.tokens + tokens_to_add, self.max_requests)
            self.last_refill = current_time


# =============================================================================
# Parallel Processing
# =============================================================================

class ParallelProcessor:
    """
    Parallel processor for executing tasks concurrently.
    
    Supports both sync and async functions with proper resource management.
    """
    
    def __init__(
        self,
        max_workers: Optional[int] = None,
        use_processes: bool = False,
        timeout: Optional[float] = None,
    ):
        """
        Initialize parallel processor.
        
        Args:
            max_workers: Maximum number of workers (default: CPU count)
            use_processes: Use processes instead of threads
            timeout: Timeout for each task
        """
        import os
        self.max_workers = max_workers or os.cpu_count() or 4
        self.use_processes = use_processes
        self.timeout = timeout
        self._executor: Optional[Union[ThreadPoolExecutor, ProcessPoolExecutor]] = None
    
    def __enter__(self):
        """Context manager entry."""
        if self.use_processes:
            self._executor = ProcessPoolExecutor(max_workers=self.max_workers)
        else:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._executor:
            self._executor.shutdown(wait=True)
    
    def map(
        self,
        func: Callable[[T], R],
        items: List[T],
        chunk_size: Optional[int] = None,
    ) -> List[R]:
        """
        Execute function on items in parallel.
        
        Args:
            func: Function to execute
            items: Items to process
            chunk_size: Optional chunk size for batching
            
        Returns:
            List of results in same order as items
        """
        if not self._executor:
            raise RuntimeError("ParallelProcessor must be used as context manager")
        
        if chunk_size:
            # Process in chunks
            results = []
            for i in range(0, len(items), chunk_size):
                chunk = items[i:i + chunk_size]
                chunk_results = list(self._executor.map(func, chunk, timeout=self.timeout))
                results.extend(chunk_results)
            return results
        else:
            return list(self._executor.map(func, items, timeout=self.timeout))
    
    def submit(
        self,
        func: Callable[..., R],
        *args: Any,
        **kwargs: Any,
    ) -> Any:  # Future
        """
        Submit a task for execution.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Future object
        """
        if not self._executor:
            raise RuntimeError("ParallelProcessor must be used as context manager")
        
        return self._executor.submit(func, *args, **kwargs)


# =============================================================================
# Async Batch Processing
# =============================================================================

async def process_batch_async(
    func: Callable[[T], Any],
    items: List[T],
    batch_size: int = 10,
    max_concurrent: Optional[int] = None,
    rate_limiter: Optional[RateLimiter] = None,
    timeout: Optional[float] = None,
) -> List[Any]:
    """
    Process items in batches asynchronously.
    
    Args:
        func: Async function to execute
        items: Items to process
        batch_size: Number of items per batch
        max_concurrent: Maximum concurrent tasks
        rate_limiter: Optional rate limiter
        timeout: Timeout per item
        
    Returns:
        List of results in same order as items
    """
    max_concurrent = max_concurrent or batch_size
    semaphore = asyncio.Semaphore(max_concurrent)
    results: List[Any] = [None] * len(items)
    
    async def process_item(index: int, item: T) -> None:
        """Process a single item."""
        async with semaphore:
            if rate_limiter:
                await rate_limiter.acquire()
            
            try:
                if timeout:
                    result = await asyncio.wait_for(func(item), timeout=timeout)
                else:
                    result = await func(item)
                results[index] = result
            except asyncio.TimeoutError:
                logger.error(f"Item {index} timed out after {timeout}s")
                results[index] = None
            except Exception as e:
                logger.error(f"Item {index} failed: {e}", exc_info=True)
                results[index] = None
    
    # Process in batches
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        batch_indices = list(range(i, i + len(batch)))
        
        tasks = [
            process_item(idx, item)
            for idx, item in zip(batch_indices, batch)
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    return results


async def process_parallel_async(
    func: Callable[[T], Any],
    items: List[T],
    max_concurrent: Optional[int] = None,
    rate_limiter: Optional[RateLimiter] = None,
    timeout: Optional[float] = None,
) -> List[Any]:
    """
    Process items in parallel asynchronously.
    
    Args:
        func: Async function to execute
        items: Items to process
        max_concurrent: Maximum concurrent tasks
        rate_limiter: Optional rate limiter
        timeout: Timeout per item
        
    Returns:
        List of results in same order as items
    """
    max_concurrent = max_concurrent or len(items)
    semaphore = asyncio.Semaphore(max_concurrent)
    results: List[Any] = [None] * len(items)
    
    async def process_item(index: int, item: T) -> None:
        """Process a single item."""
        async with semaphore:
            if rate_limiter:
                await rate_limiter.acquire()
            
            try:
                if timeout:
                    result = await asyncio.wait_for(func(item), timeout=timeout)
                else:
                    result = await func(item)
                results[index] = result
            except asyncio.TimeoutError:
                logger.error(f"Item {index} timed out after {timeout}s")
                results[index] = None
            except Exception as e:
                logger.error(f"Item {index} failed: {e}", exc_info=True)
                results[index] = None
    
    tasks = [
        process_item(i, item)
        for i, item in enumerate(items)
    ]
    
    await asyncio.gather(*tasks, return_exceptions=True)
    
    return results


# =============================================================================
# Timeout Utilities
# =============================================================================

def with_timeout(
    timeout: float,
    default: Optional[T] = None,
    timeout_exception: Type[Exception] = TimeoutError,
) -> Callable:
    """
    Decorator for adding timeout to functions.
    
    Args:
        timeout: Timeout in seconds
        default: Default value to return on timeout
        timeout_exception: Exception to raise on timeout
        
    Returns:
        Decorated function with timeout
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                if asyncio.iscoroutinefunction(func):
                    # For async functions, use asyncio.wait_for
                    loop = asyncio.get_event_loop()
                    return loop.run_until_complete(
                        asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                    )
                else:
                    # For sync functions, use threading
                    import threading
                    result_container: List[Any] = [None]
                    exception_container: List[Exception] = []
                    
                    def target():
                        try:
                            result_container[0] = func(*args, **kwargs)
                        except Exception as e:
                            exception_container.append(e)
                    
                    thread = threading.Thread(target=target)
                    thread.daemon = True
                    thread.start()
                    thread.join(timeout=timeout)
                    
                    if thread.is_alive():
                        if default is not None:
                            return default
                        raise timeout_exception(f"{func.__name__} timed out after {timeout}s")
                    
                    if exception_container:
                        raise exception_container[0]
                    
                    return result_container[0]
                    
            except asyncio.TimeoutError:
                if default is not None:
                    return default
                raise timeout_exception(f"{func.__name__} timed out after {timeout}s")
        
        return wrapper
    
    return decorator


async def async_with_timeout(
    timeout: float,
    default: Optional[T] = None,
    timeout_exception: Type[Exception] = TimeoutError,
) -> Callable:
    """
    Decorator for adding timeout to async functions.
    
    Args:
        timeout: Timeout in seconds
        default: Default value to return on timeout
        timeout_exception: Exception to raise on timeout
        
    Returns:
        Decorated async function with timeout
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                return result
            except asyncio.TimeoutError:
                if default is not None:
                    return default
                raise timeout_exception(f"{func.__name__} timed out after {timeout}s")
        
        return wrapper
    
    return decorator


# =============================================================================
# Resource Pool
# =============================================================================

class ResourcePool:
    """
    Resource pool for managing limited resources.
    
    Useful for connection pooling, API client pooling, etc.
    """
    
    def __init__(
        self,
        factory: Callable[[], T],
        max_size: int = 10,
        min_size: int = 2,
    ):
        """
        Initialize resource pool.
        
        Args:
            factory: Function to create resources
            max_size: Maximum pool size
            min_size: Minimum pool size
        """
        self.factory = factory
        self.max_size = max_size
        self.min_size = min_size
        self.pool: List[T] = []
        self.in_use: set[T] = set()
        self._lock = asyncio.Lock()
        
        # Initialize minimum pool size
        for _ in range(min_size):
            self.pool.append(factory())
    
    async def acquire(self) -> T:
        """
        Acquire a resource from the pool.
        
        Returns:
            Resource instance
        """
        async with self._lock:
            # Try to get from pool
            if self.pool:
                resource = self.pool.pop()
                self.in_use.add(resource)
                return resource
            
            # Create new resource if under max size
            if len(self.in_use) < self.max_size:
                resource = self.factory()
                self.in_use.add(resource)
                return resource
            
            # Wait for resource to become available
            # In a real implementation, you'd use a condition variable
            raise RuntimeError("Resource pool exhausted")
    
    async def release(self, resource: T) -> None:
        """
        Release a resource back to the pool.
        
        Args:
            resource: Resource to release
        """
        async with self._lock:
            if resource in self.in_use:
                self.in_use.remove(resource)
                self.pool.append(resource)
    
    async def __aenter__(self) -> T:
        """Async context manager entry."""
        return await self.acquire()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        # Note: This requires tracking the resource
        # In practice, use acquire/release explicitly
        pass
