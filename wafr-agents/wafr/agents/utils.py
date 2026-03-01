"""
Utility functions for agent processing - retry logic, JSON parsing, batching, etc.
"""
import json
import re
import logging
import time
import os
from typing import Dict, List, Any, Optional, Callable, Tuple
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


def validate_aws_credentials() -> Tuple[bool, str]:
    """
    Validate AWS credentials and return status with helpful error message.
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if credentials are valid, False otherwise
        - error_message: Descriptive error message if invalid, empty string if valid
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError
        
        # Try to create a session to validate credentials
        session = boto3.Session()
        credentials = session.get_credentials()
        
        if credentials is None:
            return False, (
                "AWS credentials not found. Please configure credentials using one of these methods:\n"
                "1. AWS CLI: Run 'aws configure'\n"
                "2. Environment variables: Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and optionally AWS_SESSION_TOKEN\n"
                "3. Credentials file: Create ~/.aws/credentials (Linux/Mac) or %USERPROFILE%\\.aws\\credentials (Windows)\n"
                "4. IAM role: If running on EC2/ECS/Lambda, use IAM role credentials"
            )
        
        # Check if credentials are expired (for temporary credentials)
        if hasattr(credentials, 'refresh'):
            try:
                credentials.refresh(None)
            except Exception as e:
                if "expired" in str(e).lower() or "invalid" in str(e).lower():
                    return False, (
                        f"AWS credentials have expired: {str(e)}\n"
                        "Please refresh your temporary credentials or reconfigure permanent credentials.\n"
                        "If using temporary credentials (STS), you may need to:\n"
                        "- Run 'aws sso login' if using SSO\n"
                        "- Refresh your session token\n"
                        "- Re-run 'aws configure' to set new credentials"
                    )
        
        # Try to validate credentials by calling STS GetCallerIdentity
        sts_client = session.client('sts', region_name='us-east-1')
        try:
            identity = sts_client.get_caller_identity()
            logger.debug(f"AWS credentials validated successfully for account: {identity.get('Account', 'Unknown')}")
            return True, ""
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            if error_code in ['InvalidClientTokenId', 'UnrecognizedClientException']:
                return False, (
                    f"AWS credentials are invalid: {error_msg}\n\n"
                    "This usually means:\n"
                    "1. The access key ID or secret access key is incorrect\n"
                    "2. The credentials have been deleted or rotated\n"
                    "3. The session token (if using temporary credentials) has expired\n\n"
                    "To fix this:\n"
                    "- Run 'aws configure' to set new credentials\n"
                    "- If using SSO, run 'aws sso login'\n"
                    "- Check your AWS account to ensure the credentials are still valid\n"
                    "- Verify your credentials file at ~/.aws/credentials (Linux/Mac) or %USERPROFILE%\\.aws\\credentials (Windows)"
                )
            elif error_code == 'ExpiredToken':
                return False, (
                    f"AWS session token has expired: {error_msg}\n\n"
                    "Temporary credentials (session tokens) expire after a set time.\n"
                    "To fix this:\n"
                    "- If using SSO: Run 'aws sso login'\n"
                    "- If using assume-role: Refresh your session\n"
                    "- If using permanent credentials: Run 'aws configure' to set them up"
                )
            else:
                return False, (
                    f"AWS credential validation failed: {error_code} - {error_msg}\n"
                    "Please check your AWS credentials configuration."
                )
        except (NoCredentialsError, PartialCredentialsError) as e:
            return False, (
                f"AWS credentials are incomplete: {str(e)}\n\n"
                "Please ensure you have set:\n"
                "- AWS_ACCESS_KEY_ID (or aws_access_key_id in credentials file)\n"
                "- AWS_SECRET_ACCESS_KEY (or aws_secret_access_key in credentials file)\n"
                "- AWS_SESSION_TOKEN (optional, only if using temporary credentials)\n\n"
                "Run 'aws configure' to set these up, or set them as environment variables."
            )
        except BotoCoreError as e:
            return False, (
                f"Error validating AWS credentials: {str(e)}\n"
                "Please check your AWS credentials and network connectivity."
            )
            
    except ImportError:
        return False, (
            "boto3 is not installed. Please install it with: pip install boto3"
        )
    except Exception as e:
        return False, (
            f"Unexpected error validating AWS credentials: {str(e)}\n"
            "Please check your AWS credentials configuration."
        )


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    Decorator for retrying functions with exponential backoff.
    Enhanced to handle timeout exceptions properly.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay after each retry
        exceptions: Tuple of exceptions to catch and retry on
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            # Include timeout exceptions
            import botocore.exceptions
            from urllib3.exceptions import ReadTimeoutError, ConnectTimeoutError
            from requests.exceptions import Timeout as RequestsTimeout
            
            timeout_exceptions = (
                ReadTimeoutError,
                ConnectTimeoutError,
                RequestsTimeout,
                TimeoutError,
            )
            
            # Combine with provided exceptions
            all_exceptions = exceptions + timeout_exceptions if exceptions != (Exception,) else timeout_exceptions + (Exception,)
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except all_exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {str(e)}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts")
            
            raise last_exception
        return wrapper
    return decorator


def extract_json_from_text(text: str, strict: bool = False) -> Dict[str, Any]:
    """
    Extract JSON from text, handling markdown code blocks and plain JSON.
    Robust extraction with multiple strategies.
    
    Args:
        text: Text that may contain JSON
        strict: If True, return None if JSON not found. If False, return dict with raw_text.
        
    Returns:
        Parsed JSON dictionary or None
    """
    if not text or not isinstance(text, str):
        return {} if not strict else None
    
    # Strategy 1: Try to extract JSON from markdown code blocks
    json_patterns = [
        (r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL),  # JSON object in code block
        (r'```(?:json)?\s*(\[.*?\])\s*```', re.DOTALL),   # JSON array in code block
        (r'```(?:python)?\s*(\[.*?\])\s*```', re.DOTALL), # Python-style array
    ]
    
    for pattern, flags in json_patterns:
        matches = re.finditer(pattern, text, flags)
        for match in matches:
            try:
                json_str = match.group(1).strip()
                parsed = json.loads(json_str)
                if isinstance(parsed, (dict, list)):
                    return parsed if isinstance(parsed, dict) else {'items': parsed}
            except (json.JSONDecodeError, IndexError, AttributeError):
                continue
    
    # Strategy 2: Find JSON arrays (more common for insights)
    array_pattern = r'\[\s*(?:\{[^}]*\}(?:\s*,\s*\{[^}]*\})*)\s*\]'
    matches = re.finditer(array_pattern, text, re.DOTALL)
    for match in matches:
        try:
            json_str = match.group(0).strip()
            parsed = json.loads(json_str)
            if isinstance(parsed, list) and parsed:
                return {'items': parsed}
        except json.JSONDecodeError:
            continue
    
    # Strategy 3: Find JSON objects
    object_pattern = r'\{\s*"[^"]+"\s*:\s*[^}]+\}'
    matches = re.finditer(object_pattern, text, re.DOTALL)
    objects = []
    for match in matches:
        try:
            json_str = match.group(0).strip()
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                objects.append(parsed)
        except json.JSONDecodeError:
            continue
    
    if objects:
        if len(objects) == 1:
            return objects[0]
        else:
            return {'items': objects}
    
    # Strategy 4: Try parsing entire text as JSON
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, (dict, list)):
            return parsed if isinstance(parsed, dict) else {'items': parsed}
    except json.JSONDecodeError:
        pass
    
    # Strategy 5: Try to find and fix common JSON issues
    # Remove trailing commas, fix quotes, etc.
    cleaned = text.strip()
    # Remove markdown if present
    cleaned = re.sub(r'```[a-z]*\s*', '', cleaned)
    cleaned = re.sub(r'```\s*$', '', cleaned)
    
    # Try to find JSON-like structures
    if '{' in cleaned and '}' in cleaned:
        # Try to extract the first complete JSON object/array
        start_idx = cleaned.find('[')
        if start_idx == -1:
            start_idx = cleaned.find('{')
        
        if start_idx != -1:
            # Try to find matching closing bracket
            bracket_stack = []
            end_idx = start_idx
            for i in range(start_idx, len(cleaned)):
                if cleaned[i] in '[{':
                    bracket_stack.append(cleaned[i])
                elif cleaned[i] in ']}':
                    if bracket_stack:
                        bracket_stack.pop()
                        if not bracket_stack:
                            end_idx = i + 1
                            break
            
            if end_idx > start_idx:
                try:
                    json_str = cleaned[start_idx:end_idx]
                    parsed = json.loads(json_str)
                    if isinstance(parsed, (dict, list)):
                        return parsed if isinstance(parsed, dict) else {'items': parsed}
                except json.JSONDecodeError:
                    pass
    
    if strict:
        return None
    
    # Return raw text wrapped in dict
    return {'raw_text': text.strip()}


def validate_insight(insight: Dict[str, Any]) -> bool:
    """
    Validate that an insight has required fields.
    
    Args:
        insight: Insight dictionary
        
    Returns:
        True if valid, False otherwise
    """
    required_fields = ['insight_type', 'content', 'transcript_quote']
    return all(field in insight and insight[field] for field in required_fields)


def validate_mapping(mapping: Dict[str, Any]) -> bool:
    """
    Validate that a mapping has required fields.
    
    Args:
        mapping: Mapping dictionary
        
    Returns:
        True if valid, False otherwise
    """
    required_fields = ['question_id', 'pillar', 'answer_content']
    return all(field in mapping and mapping[field] for field in required_fields)


def deduplicate_insights(insights: List[Dict[str, Any]], similarity_threshold: float = 0.8) -> List[Dict[str, Any]]:
    """
    Remove duplicate or highly similar insights.
    
    Args:
        insights: List of insight dictionaries
        similarity_threshold: Threshold for considering insights similar (0-1)
        
    Returns:
        Deduplicated list of insights
    """
    if not insights:
        return []
    
    # Simple deduplication based on content hash
    seen = set()
    unique_insights = []
    
    for insight in insights:
        # Create a hash based on content and quote
        content_key = (
            insight.get('content', '').lower().strip()[:100],
            insight.get('transcript_quote', '').lower().strip()[:100]
        )
        
        if content_key not in seen:
            seen.add(content_key)
            unique_insights.append(insight)
    
    return unique_insights


def deduplicate_mappings(mappings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remove duplicate mappings (same question_id with similar content).
    
    Args:
        mappings: List of mapping dictionaries
        
    Returns:
        Deduplicated list of mappings
    """
    if not mappings:
        return []
    
    # Group by question_id and keep best mapping
    question_map = {}
    
    for mapping in mappings:
        q_id = mapping.get('question_id')
        if not q_id:
            continue
        
        if q_id not in question_map:
            question_map[q_id] = mapping
        else:
            # Keep mapping with higher relevance score
            existing_score = question_map[q_id].get('relevance_score', 0)
            new_score = mapping.get('relevance_score', 0)
            if new_score > existing_score:
                question_map[q_id] = mapping
    
    return list(question_map.values())


def timeout_wrapper(func: Callable, timeout_seconds: float = None, timeout: float = None) -> Any:
    """
    Execute a function with a timeout using threading.
    More aggressive timeout handling with better interrupt capability.

    Args:
        func: Function to execute
        timeout_seconds: Maximum time to wait in seconds (deprecated, use timeout)
        timeout: Maximum time to wait in seconds

    Returns:
        Function result

    Raises:
        TimeoutError: If function doesn't complete within timeout
    """
    # Support both parameter names for backward compatibility
    effective_timeout = timeout or timeout_seconds
    if effective_timeout is None:
        raise ValueError("Must specify either 'timeout' or 'timeout_seconds'")
    import threading
    import signal
    
    result_container = [None]
    exception_container = [None]
    thread_done = threading.Event()
    
    def target():
        try:
            result_container[0] = func()
        except Exception as e:
            exception_container[0] = e
        finally:
            thread_done.set()
    
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    
    # Wait with timeout, checking periodically
    waited = 0.0
    check_interval = min(0.5, effective_timeout / 10)  # Check every 500ms or 10% of timeout

    while not thread_done.is_set() and waited < effective_timeout:
        thread_done.wait(timeout=check_interval)
        waited += check_interval
        if not thread.is_alive():
            break

    if not thread_done.is_set() or thread.is_alive():
        logger.warning(f"Function timed out after {effective_timeout}s - forcing failure")
        raise TimeoutError(f"Function timed out after {effective_timeout} seconds")
    
    if exception_container[0]:
        raise exception_container[0]
    
    return result_container[0]


def batch_process(
    items: List[Any],
    processor: Callable[[Any], Any],
    batch_size: int = 10,  # Increased from 5 to 10 for better throughput
    max_workers: int = 5,   # Increased from 3 to 5 for better parallelism
    timeout: Optional[float] = None
) -> List[Any]:
    """
    Process items in batches with parallel execution.
    Optimized with larger batches and more workers.
    
    Args:
        items: List of items to process
        processor: Function to process each item
        batch_size: Number of items per batch (default: 10, optimized)
        max_workers: Maximum parallel workers (default: 5, optimized)
        timeout: Timeout per item in seconds
        
    Returns:
        List of processed results
    """
    if not items:
        return []
    
    results = []
    
    # Process in batches
    effective_timeout = timeout or 90.0  # Increased to 90s for LLM processing
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        batch_num = i//batch_size + 1
        total_batches = (len(items) + batch_size - 1) // batch_size
        logger.info(f"Processing batch {batch_num}/{total_batches} with {len(batch)} items (timeout: {effective_timeout}s per item)")
        
        # Wrap processor with timeout to prevent hanging
        def timed_processor(item, item_idx):
            try:
                return timeout_wrapper(lambda: processor(item), timeout=effective_timeout)
            except TimeoutError:
                logger.warning(f"Batch {batch_num} item {item_idx+1} timed out after {effective_timeout}s - will use fallback")
                return None  # Return None to indicate failure, caller should handle
            except Exception as e:
                logger.error(f"Batch {batch_num} item {item_idx+1} failed: {str(e)} - will use fallback")
                return None  # Return None to indicate failure, caller should handle
        
        with ThreadPoolExecutor(max_workers=min(max_workers, len(batch))) as executor:
            futures = {executor.submit(timed_processor, item, idx): (item, idx) for idx, item in enumerate(batch)}
            
            # Calculate batch timeout: individual timeout * batch size, but cap at 2 minutes per batch
            batch_timeout = min(effective_timeout * len(batch), 120.0)
            
            completed_count = 0
            try:
                for future in as_completed(futures, timeout=batch_timeout):
                    item, idx = futures[future]
                    completed_count += 1
                    try:
                        result = future.result(timeout=1.0)  # Quick result retrieval
                        if result is not None:  # Only append non-None results
                            results.append(result)
                        logger.debug(f"Batch {batch_num}: Completed {completed_count}/{len(batch)} items")
                    except TimeoutError:
                        logger.warning(f"Batch {batch_num}: Item {idx+1} result retrieval timed out - skipping")
                    except Exception as e:
                        logger.error(f"Batch {batch_num}: Item {idx+1} error: {str(e)} - skipping")
            except TimeoutError:
                logger.warning(f"Batch {batch_num} timed out after {batch_timeout}s. {completed_count}/{len(batch)} items completed")
                # Get results from completed futures only
                for future, item in futures.items():
                    if future.done():
                        try:
                            result = future.result(timeout=1.0)
                            results.append(result)
                        except Exception as e:
                            logger.debug(f"Error getting result from completed future: {str(e)}")
                            results.append(None)
                    else:
                        # Cancel unfinished futures - they're taking too long
                        logger.warning(f"Batch {batch_num}: Cancelling stuck future")
                        future.cancel()
                        results.append(None)
    
    return [r for r in results if r is not None]


def smart_segment_transcript(
    transcript: str,
    max_segment_length: int = 5000,
    overlap: int = 200
) -> List[Dict[str, Any]]:
    """
    Intelligently segment transcript preserving sentence boundaries.
    
    Args:
        transcript: Full transcript text
        max_segment_length: Maximum characters per segment
        overlap: Overlap between segments in characters
        
    Returns:
        List of segment dictionaries with text and metadata
    """
    if not transcript or len(transcript) <= max_segment_length:
        return [{
            'text': transcript,
            'start': 0,
            'end': len(transcript),
            'index': 0
        }]
    
    segments = []
    lines = transcript.split('\n')
    current_segment = []
    current_length = 0
    segment_start = 0
    segment_index = 0
    
    for i, line in enumerate(lines):
        line_length = len(line) + 1  # +1 for newline
        
        if current_length + line_length > max_segment_length and current_segment:
            # Save current segment
            segment_text = '\n'.join(current_segment)
            segments.append({
                'text': segment_text,
                'start': segment_start,
                'end': segment_start + len(segment_text),
                'index': segment_index
            })
            
            # Start new segment with overlap
            overlap_lines = []
            overlap_length = 0
            for j in range(len(current_segment) - 1, -1, -1):
                if overlap_length + len(current_segment[j]) <= overlap:
                    overlap_lines.insert(0, current_segment[j])
                    overlap_length += len(current_segment[j]) + 1
                else:
                    break
            
            current_segment = overlap_lines + [line]
            current_length = overlap_length + line_length
            segment_start = segment_start + len(segment_text) - overlap_length
            segment_index += 1
        else:
            current_segment.append(line)
            current_length += line_length
    
    # Add final segment
    if current_segment:
        segment_text = '\n'.join(current_segment)
        segments.append({
            'text': segment_text,
            'start': segment_start,
            'end': segment_start + len(segment_text),
            'index': segment_index
        })
    
    return segments


class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.
    Implements CLOSED -> OPEN -> HALF_OPEN state transitions.
    """
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0, 
                 half_open_timeout: float = 30.0, half_open_success_threshold: int = 2):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Time in seconds before attempting half-open
            half_open_timeout: Time in seconds to stay in half-open state
            half_open_success_threshold: Successes needed to close circuit
        """
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_timeout = half_open_timeout
        self.half_open_success_threshold = half_open_success_threshold
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        self.success_count = 0
        self.half_open_start_time = None
    
    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open or function fails
        """
        if self.state == 'OPEN':
            if self.last_failure_time and (time.time() - self.last_failure_time) > self.timeout:
                # Transition to HALF_OPEN
                self.state = 'HALF_OPEN'
                self.success_count = 0
                self.half_open_start_time = time.time()
                logger.info("Circuit breaker: Transitioning to HALF_OPEN state")
            else:
                raise Exception(f"Circuit breaker is OPEN. Retry after {self.timeout - (time.time() - self.last_failure_time):.1f}s")
        
        try:
            result = func(*args, **kwargs)
            
            # Success - update state
            if self.state == 'HALF_OPEN':
                self.success_count += 1
                if self.success_count >= self.half_open_success_threshold:
                    self.state = 'CLOSED'
                    self.failure_count = 0
                    logger.info("Circuit breaker: Transitioning to CLOSED state")
            elif self.state == 'CLOSED':
                self.failure_count = 0  # Reset on success
            
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = 'OPEN'
                logger.warning(f"Circuit breaker: Opening circuit after {self.failure_count} failures")
            
            raise


# Enhanced caching for transcript segments
_segment_cache = {}
_mapping_cache = {}


def cache_transcript_segment(transcript_hash: str, segment_index: int, result: Any) -> None:
    """
    Cache processed transcript segment.
    
    Args:
        transcript_hash: Hash identifier for the transcript
        segment_index: Index of the segment
        result: Result to cache
    """
    cache_key = f"{transcript_hash}_{segment_index}"
    _segment_cache[cache_key] = {
        'value': result,
        'timestamp': time.time()
    }


def get_cached_segment(transcript_hash: str, segment_index: int, ttl: float = 3600.0) -> Optional[Any]:
    """
    Get cached transcript segment if not expired.
    
    Args:
        transcript_hash: Hash identifier for the transcript
        segment_index: Index of the segment
        ttl: Time to live in seconds (default: 3600.0)
        
    Returns:
        Cached result if available and not expired, None otherwise
    """
    cache_key = f"{transcript_hash}_{segment_index}"
    if cache_key in _segment_cache:
        cached_item = _segment_cache[cache_key]
        if time.time() - cached_item['timestamp'] < ttl:
            return cached_item['value']
        else:
            del _segment_cache[cache_key]
    return None


def cache_question_mapping(question_id: str, transcript_hash: str, mapping: Dict[str, Any]) -> None:
    """
    Cache question-to-transcript mappings.
    
    Args:
        question_id: Question identifier
        transcript_hash: Hash identifier for the transcript
        mapping: Mapping dictionary to cache
    """
    cache_key = f"{question_id}_{transcript_hash}"
    _mapping_cache[cache_key] = {
        'value': mapping,
        'timestamp': time.time()
    }


def get_cached_mapping(question_id: str, transcript_hash: str, ttl: float = 3600.0) -> Optional[Dict[str, Any]]:
    """
    Get cached question mapping if not expired.
    
    Args:
        question_id: Question identifier
        transcript_hash: Hash identifier for the transcript
        ttl: Time to live in seconds (default: 3600.0)
        
    Returns:
        Cached mapping if available and not expired, None otherwise
    """
    cache_key = f"{question_id}_{transcript_hash}"
    if cache_key in _mapping_cache:
        cached_item = _mapping_cache[cache_key]
        if time.time() - cached_item['timestamp'] < ttl:
            return cached_item['value']
        else:
            del _mapping_cache[cache_key]
    return None


def cache_result(cache: Dict[str, Any], key: str, generator: Callable[[], Any], ttl: Optional[float] = None) -> Any:
    """
    Cache a result with optional TTL.
    
    Args:
        cache: Cache dictionary
        key: Cache key
        generator: Function to generate value if not cached
        ttl: Time to live in seconds (None = no expiration)
        
    Returns:
        Cached or generated value
    """
    if key in cache:
        cached_item = cache[key]
        if ttl is None:
            return cached_item['value']
        
        if time.time() - cached_item['timestamp'] < ttl:
            return cached_item['value']
    
    # Generate and cache
    value = generator()
    cache[key] = {
        'value': value,
        'timestamp': time.time()
    }
    return value

