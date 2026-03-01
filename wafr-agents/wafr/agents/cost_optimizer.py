"""
Cost Optimization Utilities

Provides caching and optimization utilities to reduce Claude Sonnet API costs.
"""

import hashlib
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Response Caching
# =============================================================================

class ResponseCache:
    """
    Cache LLM responses to avoid duplicate calls.
    
    Caches responses based on prompt hash and model ID.
    Reduces costs by avoiding redundant API calls for similar inputs.
    """
    
    _cache: Dict[str, Tuple[Any, float]] = {}
    _ttl: float = 3600.0  # 1 hour default TTL
    _stats: Dict[str, int] = {
        "hits": 0,
        "misses": 0,
        "sets": 0,
    }
    
    @classmethod
    def get_cache_key(cls, prompt: str, model_id: str, additional_context: Optional[str] = None) -> str:
        """
        Generate cache key from prompt, model, and optional context.
        
        Args:
            prompt: LLM prompt text
            model_id: Model identifier
            additional_context: Optional additional context (e.g., transcript hash)
            
        Returns:
            MD5 hash of the cache key
        """
        content = f"{model_id}:{prompt}"
        if additional_context:
            content += f":{additional_context}"
        return hashlib.md5(content.encode()).hexdigest()
    
    @classmethod
    def get(
        cls,
        prompt: str,
        model_id: str,
        additional_context: Optional[str] = None,
        ttl: Optional[float] = None,
    ) -> Optional[Any]:
        """
        Get cached response if available and not expired.
        
        Args:
            prompt: LLM prompt text
            model_id: Model identifier
            additional_context: Optional additional context
            ttl: Optional custom TTL (overrides default)
            
        Returns:
            Cached response if available and valid, None otherwise
        """
        key = cls.get_cache_key(prompt, model_id, additional_context)
        cache_ttl = ttl if ttl is not None else cls._ttl
        
        if key in cls._cache:
            response, timestamp = cls._cache[key]
            age = time.time() - timestamp
            
            if age < cache_ttl:
                cls._stats["hits"] += 1
                logger.debug(f"Cache HIT: {key[:16]}... (age: {age:.1f}s)")
                return response
            else:
                # Expired, remove from cache
                del cls._cache[key]
                logger.debug(f"Cache EXPIRED: {key[:16]}... (age: {age:.1f}s)")
        
        cls._stats["misses"] += 1
        logger.debug(f"Cache MISS: {key[:16]}...")
        return None
    
    @classmethod
    def set(
        cls,
        prompt: str,
        model_id: str,
        response: Any,
        additional_context: Optional[str] = None,
    ) -> None:
        """
        Cache response.
        
        Args:
            prompt: LLM prompt text
            model_id: Model identifier
            response: Response to cache
            additional_context: Optional additional context
        """
        key = cls.get_cache_key(prompt, model_id, additional_context)
        cls._cache[key] = (response, time.time())
        cls._stats["sets"] += 1
        logger.debug(f"Cache SET: {key[:16]}...")
    
    @classmethod
    def clear(cls) -> None:
        """Clear all cached responses."""
        count = len(cls._cache)
        cls._cache.clear()
        logger.info(f"Cache cleared: {count} entries removed")
    
    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        total_requests = cls._stats["hits"] + cls._stats["misses"]
        hit_rate = (cls._stats["hits"] / total_requests * 100) if total_requests > 0 else 0.0
        
        return {
            "hits": cls._stats["hits"],
            "misses": cls._stats["misses"],
            "sets": cls._stats["sets"],
            "entries": len(cls._cache),
            "hit_rate": hit_rate,
            "total_requests": total_requests,
        }
    
    @classmethod
    def set_ttl(cls, ttl: float) -> None:
        """Set default TTL in seconds."""
        cls._ttl = ttl
        logger.info(f"Cache TTL set to {ttl}s")
    
    @classmethod
    def cleanup_expired(cls) -> int:
        """
        Remove expired entries from cache.
        
        Returns:
            Number of entries removed
        """
        now = time.time()
        expired_keys = [
            key for key, (_, timestamp) in cls._cache.items()
            if now - timestamp >= cls._ttl
        ]
        
        for key in expired_keys:
            del cls._cache[key]
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
        
        return len(expired_keys)


# =============================================================================
# Transcript Hash Utilities
# =============================================================================

def hash_transcript_segment(transcript: str, start: int = 0, length: int = 1000) -> str:
    """
    Generate hash for a transcript segment.
    
    Useful for caching based on transcript content.
    
    Args:
        transcript: Full transcript text
        start: Start position (default: 0)
        length: Segment length in characters (default: 1000)
        
    Returns:
        MD5 hash of the segment
    """
    segment = transcript[start:start + length]
    return hashlib.md5(segment.encode()).hexdigest()


def hash_transcript_full(transcript: str) -> str:
    """
    Generate hash for full transcript.
    
    Args:
        transcript: Full transcript text
        
    Returns:
        MD5 hash of the transcript
    """
    return hashlib.md5(transcript.encode()).hexdigest()


# =============================================================================
# Question/Mapping Hash Utilities
# =============================================================================

def hash_question_context(question_id: str, question_text: str, transcript_hash: Optional[str] = None) -> str:
    """
    Generate hash for question context.
    
    Args:
        question_id: Question identifier
        question_text: Question text
        transcript_hash: Optional transcript hash
        
    Returns:
        MD5 hash of the question context
    """
    content = f"{question_id}:{question_text}"
    if transcript_hash:
        content += f":{transcript_hash}"
    return hashlib.md5(content.encode()).hexdigest()


# =============================================================================
# Cached Model Invocation Wrapper
# =============================================================================

def cached_model_invoke(
    prompt: str,
    model_id: str,
    invoke_func: callable,
    additional_context: Optional[str] = None,
    cache_enabled: bool = True,
    ttl: Optional[float] = None,
) -> Any:
    """
    Invoke model with caching.
    
    Args:
        prompt: LLM prompt text
        model_id: Model identifier
        invoke_func: Function to invoke if cache miss
        additional_context: Optional additional context for cache key
        cache_enabled: Whether to use cache (default: True)
        ttl: Optional custom TTL
        
    Returns:
        Model response (from cache or invocation)
    """
    if cache_enabled:
        cached = ResponseCache.get(prompt, model_id, additional_context, ttl)
        if cached is not None:
            return cached
    
    # Cache miss or disabled, invoke model
    response = invoke_func()
    
    if cache_enabled:
        ResponseCache.set(prompt, model_id, response, additional_context)
    
    return response


# =============================================================================
# Module-level Cache Instance
# =============================================================================

# Global cache instance
cache = ResponseCache()
