"""
Batch Processing Optimizer

Provides smart batching utilities to optimize LLM API calls by grouping
similar items together and processing them efficiently.
"""

import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Smart Batching
# =============================================================================

def group_by_pillar(items: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group items by pillar for efficient batch processing.
    
    Args:
        items: List of items with 'pillar' field
        
    Returns:
        Dictionary mapping pillar -> list of items
    """
    groups: Dict[str, List[Dict]] = defaultdict(list)
    
    for item in items:
        pillar = item.get("pillar", "UNKNOWN")
        groups[pillar].append(item)
    
    return dict(groups)


def group_by_question_type(items: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group items by question type/pattern for batching.
    
    Args:
        items: List of items with question-related fields
        
    Returns:
        Dictionary mapping question type -> list of items
    """
    groups: Dict[str, List[Dict]] = defaultdict(list)
    
    for item in items:
        # Use question_id prefix as type identifier (e.g., "SEC.1" -> "SEC")
        question_id = item.get("question_id", "")
        if question_id:
            question_type = question_id.split(".")[0] if "." in question_id else question_id[:3]
        else:
            question_type = "UNKNOWN"
        
        groups[question_type].append(item)
    
    return dict(groups)


def group_by_criticality(items: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group items by criticality level for priority-based batching.
    
    Args:
        items: List of items with 'criticality' field
        
    Returns:
        Dictionary mapping criticality -> list of items
    """
    groups: Dict[str, List[Dict]] = defaultdict(list)
    
    for item in items:
        criticality = item.get("criticality", "MEDIUM").upper()
        groups[criticality].append(item)
    
    return dict(groups)


def smart_group_mappings(mappings: List[Dict]) -> List[List[Dict]]:
    """
    Intelligently group mappings for optimal batch processing.
    
    Groups by:
    1. Pillar (primary grouping)
    2. Question type (secondary grouping)
    3. Criticality (tertiary grouping)
    
    Args:
        mappings: List of mapping dictionaries
        
    Returns:
        List of grouped batches, optimized for processing
    """
    if not mappings:
        return []
    
    # First: Group by pillar
    pillar_groups = group_by_pillar(mappings)
    
    batches: List[List[Dict]] = []
    
    for pillar, pillar_items in pillar_groups.items():
        # Within each pillar, group by question type
        type_groups = group_by_question_type(pillar_items)
        
        for question_type, type_items in type_groups.items():
            # Within each type, prioritize by criticality
            criticality_groups = group_by_criticality(type_items)
            
            # Create batches prioritizing HIGH criticality
            priority_order = ["HIGH", "MEDIUM", "LOW"]
            
            for criticality in priority_order:
                if criticality in criticality_groups:
                    batches.append(criticality_groups[criticality])
    
    # If we have very large batches, split them further
    max_batch_size = 15
    final_batches: List[List[Dict]] = []
    
    for batch in batches:
        if len(batch) <= max_batch_size:
            final_batches.append(batch)
        else:
            # Split large batches into smaller ones
            for i in range(0, len(batch), max_batch_size):
                final_batches.append(batch[i:i + max_batch_size])
    
    logger.debug(f"Smart grouped {len(mappings)} mappings into {len(final_batches)} optimized batches")
    return final_batches


def smart_group_gaps(gaps: List[Dict]) -> List[List[Dict]]:
    """
    Intelligently group gap questions for optimal batch processing.
    
    Groups by:
    1. Pillar (primary grouping)
    2. Criticality (secondary grouping)
    
    Args:
        gaps: List of gap question dictionaries
        
    Returns:
        List of grouped batches, optimized for processing
    """
    if not gaps:
        return []
    
    # Group by pillar first
    pillar_groups = group_by_pillar(gaps)
    
    batches: List[List[Dict]] = []
    max_batch_size = 10  # Optimal batch size for synthesis
    
    for pillar, pillar_items in pillar_groups.items():
        # Within pillar, group by criticality
        criticality_groups = group_by_criticality(pillar_items)
        
        # Prioritize HIGH criticality items
        priority_order = ["HIGH", "MEDIUM", "LOW"]
        
        for criticality in priority_order:
            if criticality in criticality_groups:
                items = criticality_groups[criticality]
                
                # Split if too large
                if len(items) <= max_batch_size:
                    batches.append(items)
                else:
                    for i in range(0, len(items), max_batch_size):
                        batches.append(items[i:i + max_batch_size])
    
    logger.debug(f"Smart grouped {len(gaps)} gaps into {len(batches)} optimized batches")
    return batches


def smart_group_questions(questions: List[Dict]) -> List[List[Dict]]:
    """
    Intelligently group WA Tool questions for optimal batch processing.
    
    Groups by:
    1. Pillar (primary grouping)
    2. Question complexity (based on description length)
    
    Args:
        questions: List of question dictionaries
        
    Returns:
        List of grouped batches, optimized for processing
    """
    if not questions:
        return []
    
    # Group by pillar
    pillar_groups = group_by_pillar(questions)
    
    batches: List[List[Dict]] = []
    max_batch_size = 15  # Optimal batch size for WA Tool questions
    
    for pillar, pillar_questions in pillar_groups.items():
        # Split large pillar groups
        if len(pillar_questions) <= max_batch_size:
            batches.append(pillar_questions)
        else:
            # For large groups, try to balance complexity
            # Sort by description length (complex questions first)
            sorted_questions = sorted(
                pillar_questions,
                key=lambda q: len(q.get("question", {}).get("QuestionDescription", "")),
                reverse=True
            )
            
            # Create balanced batches
            for i in range(0, len(sorted_questions), max_batch_size):
                batches.append(sorted_questions[i:i + max_batch_size])
    
    logger.debug(f"Smart grouped {len(questions)} questions into {len(batches)} optimized batches")
    return batches


# =============================================================================
# Parallel Batch Processor
# =============================================================================

def process_batches_parallel(
    batches: List[List[Any]],
    batch_processor: Callable[[List[Any]], List[Any]],
    max_parallel_batches: int = 2,
    batch_timeout: Optional[float] = None,
) -> List[Any]:
    """
    Process multiple batches in parallel for improved throughput.
    
    Args:
        batches: List of batches to process
        batch_processor: Function that processes a single batch and returns results
        max_parallel_batches: Maximum number of batches to process concurrently
        batch_timeout: Optional timeout per batch in seconds
        
    Returns:
        Flattened list of all results from all batches
    """
    if not batches:
        return []
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # Import timeout_wrapper - try both possible paths
    try:
        from wafr.agents.utils import timeout_wrapper
    except ImportError:
        from wafr.agents.utils import timeout_wrapper
    
    all_results: List[Any] = []
    effective_timeout = batch_timeout or 300.0  # Default 5 minutes per batch
    
    logger.info(f"Processing {len(batches)} batches in parallel (max {max_parallel_batches} concurrent)")
    
    # Process batches with controlled parallelism
    with ThreadPoolExecutor(max_workers=max_parallel_batches) as executor:
        # Submit all batches
        future_to_batch = {
            executor.submit(
                lambda b: timeout_wrapper(lambda: batch_processor(b), timeout=effective_timeout),
                batch
            ): (i, batch) for i, batch in enumerate(batches)
        }
        
        # Collect results as they complete
        completed = 0
        for future in as_completed(future_to_batch):
            batch_idx, batch = future_to_batch[future]
            try:
                batch_results = future.result()
                if batch_results:
                    all_results.extend(batch_results)
                completed += 1
                logger.debug(f"Completed batch {batch_idx + 1}/{len(batches)} ({len(batch)} items)")
            except TimeoutError:
                logger.warning(f"Batch {batch_idx + 1} timed out after {effective_timeout}s")
                # Add empty results for failed batch
                all_results.extend([None] * len(batch))
                completed += 1
            except Exception as e:
                logger.error(f"Batch {batch_idx + 1} failed: {e}")
                # Add empty results for failed batch
                all_results.extend([None] * len(batch))
                completed += 1
    
    logger.info(f"Completed all {len(batches)} batches: {len(all_results)} total results")
    return all_results


# =============================================================================
# Batch Size Optimizer
# =============================================================================

class BatchSizeOptimizer:
    """
    Dynamically adjusts batch sizes based on success rates and timeouts.
    """
    
    def __init__(self, initial_size: int = 10, min_size: int = 2, max_size: int = 20):
        """
        Initialize batch size optimizer.
        
        Args:
            initial_size: Starting batch size
            min_size: Minimum allowed batch size
            max_size: Maximum allowed batch size
        """
        self.initial_size = initial_size
        self.min_size = min_size
        self.max_size = max_size
        self.current_size = initial_size
        self.success_count = 0
        self.timeout_count = 0
        self.total_batches = 0
    
    def record_success(self) -> None:
        """Record a successful batch processing."""
        self.success_count += 1
        self.total_batches += 1
        self._adjust_size(up=True)
    
    def record_timeout(self) -> None:
        """Record a timeout during batch processing."""
        self.timeout_count += 1
        self.total_batches += 1
        self._adjust_size(up=False)
    
    def _adjust_size(self, up: bool) -> None:
        """Adjust batch size based on performance."""
        if up and self.current_size < self.max_size:
            # Increase size gradually (by 10% or 1, whichever is larger)
            increment = max(1, int(self.current_size * 0.1))
            self.current_size = min(self.max_size, self.current_size + increment)
            logger.debug(f"Increased batch size to {self.current_size}")
        elif not up and self.current_size > self.min_size:
            # Decrease size more aggressively (by 20% or 1, whichever is larger)
            decrement = max(1, int(self.current_size * 0.2))
            self.current_size = max(self.min_size, self.current_size - decrement)
            logger.warning(f"Decreased batch size to {self.current_size} due to timeouts")
    
    def get_optimal_size(self) -> int:
        """Get current optimal batch size."""
        return self.current_size
    
    def get_stats(self) -> Dict[str, Any]:
        """Get batch processing statistics."""
        success_rate = (self.success_count / self.total_batches * 100) if self.total_batches > 0 else 0.0
        return {
            "current_size": self.current_size,
            "success_count": self.success_count,
            "timeout_count": self.timeout_count,
            "total_batches": self.total_batches,
            "success_rate": success_rate,
        }
    
    def reset(self) -> None:
        """Reset optimizer to initial state."""
        self.current_size = self.initial_size
        self.success_count = 0
        self.timeout_count = 0
        self.total_batches = 0
