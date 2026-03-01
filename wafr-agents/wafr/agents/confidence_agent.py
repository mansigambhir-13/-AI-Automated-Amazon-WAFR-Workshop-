"""
Confidence Agent - Validates evidence and assigns confidence scores.

Anti-hallucination validation using Strands framework. Ensures WAFR answers
are properly supported by transcript evidence.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from strands import Agent, tool

from wafr.agents.config import DEFAULT_MODEL_ID, ModelSelectionStrategy
from wafr.agents.model_config import get_strands_model
from wafr.agents.utils import batch_process, extract_json_from_text, retry_with_backoff
from wafr.agents.wafr_context import get_question_context, load_wafr_schema

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Similarity thresholds
SIMILARITY_EXACT = 1.0
SIMILARITY_CASE_INSENSITIVE = 0.95
SIMILARITY_THRESHOLD = 0.6  # Minimum for acceptance
SIMILARITY_PHRASE_CAP = 0.9

# Confidence thresholds
CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.5
CONFIDENCE_LOW_REVIEW = 0.4
CONFIDENCE_CLARIFICATION = 0.3

# Processing limits
MAX_TRANSCRIPT_LENGTH = 8000  # Reduced from 15000 to prevent max_tokens limit errors
BATCH_SIZE = 12  # Optimized: 10-15 range per cost optimization plan
MAX_WORKERS = 2  # Limited workers to save parallel costs per plan
BATCH_TIMEOUT = 120.0  # Increased to accommodate larger batches
MIN_PHRASE_LENGTH = 3
MAX_VALIDATIONS = 100  # Limit validations to prevent excessive processing
USE_SMART_BATCHING = True  # Enable smart batching for optimal grouping


# =============================================================================
# Data Structures
# =============================================================================

class ConfidenceLevel(Enum):
    """Confidence level categories."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MatchType(Enum):
    """Evidence match types."""
    EXACT = "exact"
    CASE_INSENSITIVE = "case_insensitive"
    FUZZY = "fuzzy"
    PHRASE = "phrase"
    NONE = "none"


@dataclass
class EvidenceMatch:
    """Result of evidence verification."""
    verified: bool
    match_type: MatchType
    position: int = -1
    similarity: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "match_type": self.match_type.value,
            "position": self.position,
            "similarity": self.similarity,
            "confidence": self.confidence,
        }


@dataclass
class ValidationResult:
    """Result of answer validation."""
    validation_passed: bool
    confidence_score: float
    confidence_level: str
    evidence_verified: bool
    issues: list[str] = field(default_factory=list)
    requires_clarification: bool = False
    mapping_id: str | None = None
    pillar: str | None = None
    question_id: str | None = None
    clarification_request: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_passed": self.validation_passed,
            "confidence_score": self.confidence_score,
            "confidence_level": self.confidence_level,
            "evidence_verified": self.evidence_verified,
            "issues": self.issues,
            "requires_clarification": self.requires_clarification,
            "mapping_id": self.mapping_id,
            "pillar": self.pillar,
            "question_id": self.question_id,
            "clarification_request": self.clarification_request,
        }


# =============================================================================
# System Prompt
# =============================================================================

CONFIDENCE_SYSTEM_PROMPT = """
You are a rigorous fact-checker for WAFR (AWS Well-Architected Framework Review) assessments.
Your role is to validate that each answer is supported by transcript evidence and prevent hallucinations.

VALIDATION CRITERIA:
1. Evidence Verification: Does the quote appear in the transcript (verbatim or >60% similarity)?
2. Answer Support: Does the evidence actually support the answer?
3. Interpretation Accuracy: Is the interpretation accurate and not overstated?
4. Assumption Check: Are there unsupported assumptions?
5. WAFR Alignment: Does the answer align with WAFR best practices?

CONFIDENCE SCORING:
- HIGH (0.75-1.0): Evidence found verbatim/high similarity (>80%), answer directly reflects transcript
- MEDIUM (0.5-0.74): Evidence found (60-80% similarity), reasonable interpretation of client's words
- LOW (0.0-0.49): Evidence NOT found (<60% similarity), significant inference without support

VALIDATION RULES:
- ACCEPT: Verified evidence (>=60% similarity) that reflects client's actual words
- ACCEPT: Partial answers based on real transcript content
- REJECT: Evidence not found in transcript
- REJECT: Claims not supported by what client said

OUTPUT FORMAT:
- validation_passed: true if evidence verified AND confidence >= 0.5
- confidence_score: 0.0-1.0 numeric score
- confidence_level: "high", "medium", or "low"
- evidence_verified: true if quote found in transcript
- issues: List of concerns
- requires_clarification: true if answer needs more information
"""


# =============================================================================
# Tools
# =============================================================================

@tool
def verify_evidence_in_transcript(evidence_quote: str, transcript: str) -> dict:
    """
    Verify if evidence quote exists in transcript.
    
    Args:
        evidence_quote: Claimed evidence quote
        transcript: Full transcript text
        
    Returns:
        Verification result with match type and confidence
    """
    result = _verify_evidence(evidence_quote.strip(), transcript)
    return result.to_dict()


def _verify_evidence(evidence: str, transcript: str) -> EvidenceMatch:
    """Internal evidence verification logic."""
    if not evidence:
        return EvidenceMatch(verified=False, match_type=MatchType.NONE)

    # Strategy 1: Exact match
    if evidence in transcript:
        return EvidenceMatch(
            verified=True,
            match_type=MatchType.EXACT,
            position=transcript.find(evidence),
            similarity=SIMILARITY_EXACT,
            confidence=SIMILARITY_EXACT,
        )

    evidence_lower = evidence.lower()
    transcript_lower = transcript.lower()

    # Strategy 2: Case-insensitive match
    if evidence_lower in transcript_lower:
        return EvidenceMatch(
            verified=True,
            match_type=MatchType.CASE_INSENSITIVE,
            position=transcript_lower.find(evidence_lower),
            similarity=SIMILARITY_CASE_INSENSITIVE,
            confidence=SIMILARITY_CASE_INSENSITIVE,
        )

    # Strategy 3: Fuzzy word matching
    fuzzy_result = _fuzzy_word_match(evidence_lower, transcript_lower)
    if fuzzy_result.verified:
        return fuzzy_result

    # Strategy 4: Key phrase matching
    return _phrase_match(evidence_lower, transcript_lower)


def _fuzzy_word_match(evidence: str, transcript: str) -> EvidenceMatch:
    """Check for word overlap in sliding window."""
    evidence_words = set(evidence.split())
    transcript_words = transcript.split()

    if not evidence_words:
        return EvidenceMatch(verified=False, match_type=MatchType.NONE)

    window_size = len(evidence_words)
    max_matches = 0
    best_position = -1

    for i in range(len(transcript_words) - window_size + 1):
        window = set(transcript_words[i : i + window_size])
        matches = len(evidence_words & window)
        if matches > max_matches:
            max_matches = matches
            best_position = i

    similarity = max_matches / len(evidence_words)

    if similarity >= SIMILARITY_THRESHOLD:
        return EvidenceMatch(
            verified=True,
            match_type=MatchType.FUZZY,
            position=best_position,
            similarity=similarity,
            confidence=similarity,
        )

    return EvidenceMatch(verified=False, match_type=MatchType.NONE)


def _phrase_match(evidence: str, transcript: str) -> EvidenceMatch:
    """Check for consecutive word phrases."""
    words = evidence.split()
    if len(words) < MIN_PHRASE_LENGTH:
        return EvidenceMatch(verified=False, match_type=MatchType.NONE)

    matched_words = 0
    first_position = -1

    for i in range(len(words) - MIN_PHRASE_LENGTH + 1):
        phrase = " ".join(words[i : i + MIN_PHRASE_LENGTH])
        if phrase in transcript:
            matched_words += MIN_PHRASE_LENGTH
            if first_position == -1:
                first_position = transcript.find(phrase)

    if matched_words == 0:
        return EvidenceMatch(verified=False, match_type=MatchType.NONE)

    similarity = min(matched_words / len(words), SIMILARITY_PHRASE_CAP)

    if similarity >= SIMILARITY_THRESHOLD:
        return EvidenceMatch(
            verified=True,
            match_type=MatchType.PHRASE,
            position=first_position,
            similarity=similarity,
            confidence=similarity,
        )

    return EvidenceMatch(verified=False, match_type=MatchType.NONE)


@tool
def validate_answer(
    answer: str,
    evidence: str,
    transcript: str,
    validation_passed: bool,
    confidence_score: float,
    confidence_level: str,
    evidence_verified: bool,
    issues: list[str] | None = None,
    requires_clarification: bool = False,
) -> dict:
    """
    Record validation result for an answer.
    
    Args:
        answer: The answer being validated
        evidence: Evidence quote
        transcript: Full transcript
        validation_passed: Whether validation passed
        confidence_score: Score 0.0-1.0
        confidence_level: "high", "medium", or "low"
        evidence_verified: Whether evidence found in transcript
        issues: List of concerns
        requires_clarification: Whether clarification needed
        
    Returns:
        Validation result dictionary
    """
    return {
        "validation_passed": validation_passed,
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "evidence_verified": evidence_verified,
        "issues": issues or [],
        "requires_clarification": requires_clarification,
    }


# =============================================================================
# Confidence Agent
# =============================================================================

class ConfidenceAgent:
    """Agent that validates evidence and assigns confidence scores."""

    def __init__(self, wafr_schema: dict[str, Any] | None = None):
        """
        Initialize Confidence Agent.
        
        Args:
            wafr_schema: Optional WAFR schema for context
        """
        self.wafr_schema = wafr_schema or load_wafr_schema()
        self.agent = self._create_agent()

    def _create_agent(self, model_id: str | None = None) -> Agent | None:
        """Create Strands agent with tools."""
        # DISABLED: Bedrock agents don't support concurrent invocations
        # Using direct Bedrock calls instead to enable parallel processing

        # Force use of direct Bedrock calls (supports parallel execution)
        return None

    def _register_tools(self, agent: Agent) -> None:
        """Register tools with agent, trying multiple methods."""
        tools = [verify_evidence_in_transcript, validate_answer]
        
        for method_name in ("add_tool", "register_tool"):
            if hasattr(agent, method_name):
                for t in tools:
                    try:
                        getattr(agent, method_name)(t)
                    except Exception as e:
                        logger.debug("Tool registration via %s failed: %s", method_name, e)
                return

    def process(
        self,
        mappings: list[dict],
        transcript: str,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Validate mappings and assign confidence scores.
        
        Args:
            mappings: List of WAFR answer mappings
            transcript: Full transcript text
            session_id: Session identifier
            
        Returns:
            Dictionary with validation results
        """
        logger.info("ConfidenceAgent: Validating %d mappings for session %s", len(mappings), session_id)

        if not mappings:
            return self._empty_result(session_id)

        # Use shorter transcript sample to prevent max_tokens limit errors
        # MAX_TRANSCRIPT_LENGTH is now 8000, but add extra safety for agent loop
        transcript_sample = transcript[:MAX_TRANSCRIPT_LENGTH]
        if len(transcript_sample) > 7000:
            transcript_sample = transcript_sample[:7000]  # Additional safety limit for agent loop
        
        try:
            validations = self._process_mappings(mappings, transcript_sample)
        except Exception as e:
            logger.error(f"Error processing mappings: {e}", exc_info=True)
            # Return default validations for all mappings to ensure pipeline continues
            logger.warning("Using default validations due to processing error - pipeline will continue")
            validations = [self._default_validation(m) for m in mappings]
        
        return self._build_result(session_id, mappings, validations)

    def _empty_result(self, session_id: str) -> dict[str, Any]:
        """Return empty result structure."""
        return {
            "session_id": session_id,
            "summary": self._aggregate_confidence([]),
            "approved_answers": [],
            "review_needed": [],
            "clarification_needed": [],
            "all_validations": [],
            "clarification_requests": [],
            "agent": "confidence",
        }

    def _process_mappings(
        self,
        mappings: list[dict],
        transcript: str,
    ) -> list[dict]:
        """Process all mappings, using smart batch processing for optimal efficiency."""
        # Filter: Skip very low relevance mappings to speed up processing
        filtered_mappings = [
            m for m in mappings 
            if m.get("relevance_score", 0) >= 0.5  # Only validate mappings with relevance >= 0.5
        ]
        
        if len(filtered_mappings) < len(mappings):
            skipped = len(mappings) - len(filtered_mappings)
            logger.info(f"Skipping {skipped} low-relevance mappings (relevance < 0.5) for performance")
        
        # Limit mappings to prevent excessive processing
        if len(filtered_mappings) > MAX_VALIDATIONS:
            logger.warning(f"Limiting validations from {len(filtered_mappings)} to {MAX_VALIDATIONS} for performance")
            # Prioritize higher relevance scores
            filtered_mappings.sort(key=lambda m: m.get("relevance_score", 0), reverse=True)
            filtered_mappings = filtered_mappings[:MAX_VALIDATIONS]
        
        total = len(filtered_mappings)
        logger.info(f"Processing {total} mappings for validation...")
        
        processor = lambda m: self._validate_single_mapping(m, transcript)

        if len(filtered_mappings) > BATCH_SIZE:
            if USE_SMART_BATCHING:
                # Use smart batching: group similar items together
                from wafr.agents.batch_optimizer import smart_group_mappings
                smart_batches = smart_group_mappings(filtered_mappings)
                logger.info(f"Using smart batch processing: {len(smart_batches)} optimized batches (max {MAX_WORKERS} workers)")
                
                # Process smart batches with parallel execution
                validated_results = []
                for batch_idx, batch in enumerate(smart_batches):
                    logger.debug(f"Processing smart batch {batch_idx + 1}/{len(smart_batches)} ({len(batch)} items)")
                    batch_results = batch_process(
                        batch,
                        processor,
                        batch_size=min(BATCH_SIZE, len(batch)),  # Use actual batch size
                        max_workers=MAX_WORKERS,
                        timeout=BATCH_TIMEOUT,
                    )
                    validated_results.extend(batch_results)
            else:
                # Standard batch processing
                logger.info(f"Using standard batch processing ({BATCH_SIZE} per batch, {MAX_WORKERS} workers)")
            validated_results = batch_process(
                filtered_mappings,
                processor,
                batch_size=BATCH_SIZE,
                max_workers=MAX_WORKERS,
                timeout=BATCH_TIMEOUT,
            )
            
            # Fill in any missing results with default validations
            # This ensures we always return the same number of results as inputs
            results_map = {}
            for r in validated_results:
                if r:  # Skip None results
                    mapping_id = r.get("mapping_id") or r.get("question_id", "")
                    if mapping_id:
                        results_map[mapping_id] = r
            
            complete_results = []
            for m in filtered_mappings:
                mapping_id = m.get("mapping_id") or m.get("question_id", "") or m.get("id", "")
                if mapping_id in results_map:
                    complete_results.append(results_map[mapping_id])
                else:
                    # Use default validation for failed/timeout items
                    logger.debug(f"Using default validation for {mapping_id} (timeout or failure)")
                    complete_results.append(self._default_validation(m))
            
            logger.info(f"Validation complete: {len(complete_results)}/{len(filtered_mappings)} results")
            return complete_results

        # For small sets, process in parallel with timeout protection
        from wafr.agents.utils import timeout_wrapper
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        results = []
        lock = threading.Lock()
        success_count = 0
        timeout_count = 0
        error_count = 0
        
        # Use parallel processing even for small sets (max 3 workers for small batches)
        max_workers = min(3, total)
        logger.info(f"Processing {total} mappings in parallel (max {max_workers} workers)...")
        
        def validate_with_timeout(mapping: dict, index: int) -> dict:
            """Validate a single mapping with timeout and error handling."""
            try:
                result = timeout_wrapper(lambda: processor(mapping), timeout=BATCH_TIMEOUT)
                return result
            except TimeoutError:
                logger.warning(f"Mapping {index+1}/{total} timed out - using default validation")
                return self._default_validation(mapping)
            except Exception as e:
                logger.error(f"Mapping {index+1}/{total} failed: {str(e)} - using default validation")
                return self._default_validation(mapping)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_mapping = {
                executor.submit(validate_with_timeout, m, i): (i, m)
                for i, m in enumerate(filtered_mappings)
            }
            
            # Collect results as they complete
            completed = 0
            for future in as_completed(future_to_mapping):
                idx, mapping = future_to_mapping[future]
                
                try:
                    result = future.result()
                    with lock:
                        results.append((idx, result))  # Store with index to maintain order
                        completed += 1
                        
                        # Log progress every 5 items
                        if completed % 5 == 0 or completed == 1:
                            logger.info(f"Validated {completed}/{total} mappings...")
                        
                        # Count success/failure
                        if result.get("validation_passed", False):
                            success_count += 1
                        elif "timeout" in str(result.get("validation_notes", "")).lower():
                            timeout_count += 1
                        else:
                            error_count += 1
                            
                except Exception as e:
                    logger.error(f"Exception collecting result for mapping {idx+1}: {e}")
                    with lock:
                        results.append((idx, self._default_validation(mapping)))
                        error_count += 1
        
        # Sort results by original index to maintain order
        results.sort(key=lambda x: x[0])
        results = [r[1] for r in results]  # Extract just the results
        
        logger.info(f"Completed parallel validation: {success_count} succeeded, {timeout_count} timed out, {error_count} errors")
        return results

    def _validate_single_mapping(self, mapping: dict, transcript: str) -> dict:
        """Validate a single mapping against transcript."""
        from wafr.agents.cost_optimizer import ResponseCache, hash_transcript_segment
        
        answer = mapping.get("answer_content", "")
        evidence = mapping.get("evidence_quote", "")
        question_id = mapping.get("question_id")
        relevance_score = mapping.get("relevance_score", 0.5)

        question_context = self._get_question_context(question_id)
        prompt = self._build_validation_prompt(answer, evidence, question_id, question_context, transcript)

        # Select model based on complexity: Haiku for basic validation, Sonnet for complex
        # Use Haiku if: high relevance (>0.7) and short evidence (<200 chars) - basic validation
        is_basic_validation = (
            relevance_score >= 0.7 and 
            len(evidence) < 200 and 
            len(answer) < 500
        )
        
        # Determine model for this validation
        validation_model_id = ModelSelectionStrategy.get_model_for_confidence(
            confidence_score=relevance_score,
            is_basic=is_basic_validation
        )

        # Create cache context from question ID and transcript segment hash
        transcript_hash = hash_transcript_segment(transcript, length=1000)
        cache_context = f"{question_id}:{transcript_hash}:{validation_model_id}"

        try:
            # Try cache first (model-specific cache)
            cached_response = ResponseCache.get(
                prompt=prompt,
                model_id=validation_model_id,
                additional_context=cache_context,
                ttl=3600.0,  # 1 hour cache
            )
            
            if cached_response is not None:
                logger.debug(f"Using cached validation for question {question_id} (model: {validation_model_id.split('/')[-1]})")
                return self._parse_validation(cached_response, mapping)
            
            # Cache miss, invoke model (use selected model)
            # Use direct Bedrock call for Haiku (cost optimization), agent for Sonnet
            if "haiku" in validation_model_id.lower():
                # Use direct Bedrock call for Haiku (simpler, cheaper)
                response = self._call_bedrock_direct(prompt, validation_model_id)
                logger.debug(f"Used Haiku for basic validation (cost optimization)")
            else:
                # Use existing agent (Sonnet) for complex validation
                response = self._call_agent_with_retry(prompt)
            
            # Cache the response
            ResponseCache.set(
                prompt=prompt,
                model_id=validation_model_id,
                response=response,
                additional_context=cache_context,
            )
            
            return self._parse_validation(response, mapping)
        except RuntimeError as e:
            # Handle max_tokens limit errors gracefully
            if "max_tokens_limit" in str(e):
                logger.warning(f"Max tokens limit hit for {question_id} - using default validation")
                return self._default_validation(mapping)
            raise
        except Exception as e:
            logger.error("Error validating mapping: %s", e)
            return self._default_validation(mapping)

    def _get_question_context(self, question_id: str | None) -> str:
        """Get WAFR question context if available."""
        if not question_id or not self.wafr_schema:
            return ""

        context = get_question_context(question_id, self.wafr_schema)
        return f"\n\nWAFR QUESTION CONTEXT:\n{context}\n" if context else ""

    def _build_validation_prompt(
        self,
        answer: str,
        evidence: str,
        question_id: str | None,
        question_context: str,
        transcript: str,
    ) -> str:
        """Build the validation prompt - optimized to reduce token usage."""
        # Truncate transcript further if needed to prevent max_tokens errors
        # Use only first 6000 chars of transcript for validation
        transcript_sample = transcript[:6000] if len(transcript) > 6000 else transcript
        
        # Simplify question context if too long
        if question_context and len(question_context) > 500:
            question_context = question_context[:500] + "..."
        
        return f"""Validate this WAFR answer:

Answer: {answer[:500]}
Evidence: {evidence[:300]}
Question: {question_id or 'UNKNOWN'}
{question_context[:200] if question_context else ''}
Transcript: {transcript_sample}

STEPS:
1. Use verify_evidence_in_transcript() to check if evidence exists
2. Verify evidence supports the answer
3. Use validate_answer() with results

Keep validation concise. Focus on evidence verification."""

    def _call_agent_with_model(self, prompt: str, model_id: str) -> Any:
        """Call agent with specific model ID."""
        # If model changed, create new agent with that model
        if model_id != self.model_id:
            try:
                model = get_strands_model(model_id, max_tokens=8192)
                agent_kwargs = {
                    'system_prompt': CONFIDENCE_SYSTEM_PROMPT,
                    'name': 'ConfidenceAgent'
                }
                if model:
                    agent_kwargs['model'] = model
                
                temp_agent = Agent(**agent_kwargs)
                # Try to add tools
                try:
                    temp_agent.add_tool(verify_evidence_in_transcript)
                    temp_agent.add_tool(validate_answer)
                except (AttributeError, Exception):
                    pass  # Tools may be auto-detected
                
                # Use temporary agent for this call
                import sys
                import os
                from contextlib import redirect_stdout, redirect_stderr
                from io import StringIO
                from wafr.agents.utils import timeout_wrapper
                
                stdout_capture = StringIO()
                stderr_capture = StringIO()
                
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    result = timeout_wrapper(lambda: temp_agent(prompt), timeout=BATCH_TIMEOUT)
                
                logger.debug(f"Used {model_id.split('/')[-1]} for validation (basic: {ModelSelectionStrategy.is_haiku_task('confidence_basic_validation', 'simple')})")
                return result
            except Exception as e:
                logger.warning(f"Failed to use model {model_id}, falling back to default: {e}")
                # Fallback to default agent
                return self._call_agent_with_retry(prompt)
        else:
            # Use existing agent
            return self._call_agent_with_retry(prompt)
    
    def _call_bedrock_direct(self, prompt: str, model_id: str) -> str:
        """Call Bedrock directly with specified model (for Haiku cost optimization)."""
        import boto3
        import json
        from botocore.exceptions import ClientError
        from wafr.agents.config import BEDROCK_REGION
        
        bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        
        try:
            response = bedrock.invoke_model(
                modelId=model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "temperature": 0.1,  # Low temperature for validation
                    "system": CONFIDENCE_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )
            
            result = json.loads(response["body"].read())
            return result.get("content", [{}])[0].get("text", "")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"Bedrock direct call failed ({model_id}): {error_code} - {error_msg}")
            raise
        except Exception as e:
            logger.error(f"Bedrock direct call failed ({model_id}): {e}")
            raise

    def _call_agent_with_retry(self, prompt: str) -> Any:
        """Call agent with timeout protection - no retries for speed."""
        if not self.agent:
            # Fallback to direct Bedrock when agent is disabled (for parallel processing support)
            return self._call_bedrock_direct(prompt, model_id=DEFAULT_MODEL_ID)
        try:
            # Suppress verbose output from agent
            import sys
            import os
            from contextlib import redirect_stdout, redirect_stderr
            from io import StringIO
            
            # Redirect stdout/stderr to suppress verbose agent output
            stdout_capture = StringIO()
            stderr_capture = StringIO()
            
            # Wrap agent call with timeout directly - no retries for speed
            from wafr.agents.utils import timeout_wrapper
            
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                result = timeout_wrapper(lambda: self.agent(prompt), timeout=BATCH_TIMEOUT)
            
            return result
        except TimeoutError:
            logger.warning(f"Agent call timed out after {BATCH_TIMEOUT}s - skipping")
            raise
        except Exception as e:
            error_str = str(e)
            # Check for max_tokens limit errors specifically
            if "max_tokens" in error_str.lower() or "maxtokens" in error_str.lower():
                logger.warning(f"Agent hit max_tokens limit: {error_str[:200]} - using fallback")
                # Return a structured response that will be handled gracefully
                raise RuntimeError(f"max_tokens_limit: {error_str[:100]}")
            logger.debug(f"Agent call failed: {str(e)}")
            raise

    def _parse_validation(self, response: Any, mapping: dict) -> dict:
        """Parse validation response into structured result."""
        validation = self._extract_validation_dict(response)
        
        evidence_verified = validation.get("evidence_verified", False)
        confidence_score = validation.get("confidence_score", 0.0)

        # Set defaults if missing
        if "validation_passed" not in validation:
            validation["validation_passed"] = evidence_verified and confidence_score >= CONFIDENCE_LOW_REVIEW

        if "confidence_score" not in validation:
            validation["confidence_score"] = 0.5 if evidence_verified else 0.0

        if "confidence_level" not in validation:
            validation["confidence_level"] = self._score_to_level(validation["confidence_score"])

        # Add mapping context
        validation["mapping_id"] = mapping.get("id")
        validation["pillar"] = mapping.get("pillar")
        validation["question_id"] = mapping.get("question_id")

        return validation

    def _extract_validation_dict(self, response: Any) -> dict:
        """Extract validation dictionary from response."""
        if isinstance(response, dict):
            return response

        try:
            parsed = extract_json_from_text(str(response), strict=False)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:
            logger.debug("JSON extraction failed: %s", e)

        return {}

    def _default_validation(self, mapping: dict) -> dict:
        """Create default validation for errors/timeouts."""
        # Use relevance score if available, otherwise default to medium confidence
        relevance = mapping.get("relevance_score", 0.5)
        confidence_score = max(0.3, min(0.7, relevance))  # Clamp between 0.3 and 0.7
        
        return {
            "validation_passed": True,  # Allow to continue processing
            "confidence_score": confidence_score,
            "confidence_level": self._score_to_level(confidence_score),
            "evidence_verified": relevance >= 0.5,  # Assume verified if relevance is decent
            "issues": ["Validation skipped due to timeout/error - using mapping relevance"],
            "requires_clarification": False,
            "mapping_id": mapping.get("id") or mapping.get("mapping_id"),
            "pillar": mapping.get("pillar"),
            "question_id": mapping.get("question_id"),
        }

    def _score_to_level(self, score: float) -> str:
        """Convert confidence score to level."""
        if score >= CONFIDENCE_HIGH:
            return ConfidenceLevel.HIGH.value
        if score >= CONFIDENCE_MEDIUM:
            return ConfidenceLevel.MEDIUM.value
        return ConfidenceLevel.LOW.value

    def _build_result(
        self,
        session_id: str,
        mappings: list[dict],
        validations: list[dict],
    ) -> dict[str, Any]:
        """Build final result with categorized validations."""
        approved = []
        review_needed = []
        clarification_needed = []

        for v in validations:
            evidence_verified = v.get("evidence_verified", False)
            score = v.get("confidence_score", 0)
            level = v.get("confidence_level")

            if self._is_approved(evidence_verified, level, score):
                approved.append(v)
            elif self._needs_review(evidence_verified, score):
                review_needed.append(v)
            else:
                mapping = self._find_mapping(mappings, v.get("question_id"))
                v["clarification_request"] = self._generate_clarification(v, mapping)
                clarification_needed.append(v)

        return {
            "session_id": session_id,
            "summary": self._aggregate_confidence(validations),
            "approved_answers": approved,
            "review_needed": review_needed,
            "clarification_needed": clarification_needed,
            "all_validations": validations,
            "clarification_requests": [
                v["clarification_request"]
                for v in clarification_needed
                if v.get("clarification_request")
            ],
            "agent": "confidence",
        }

    def _is_approved(self, evidence_verified: bool, level: str, score: float) -> bool:
        """Check if validation is auto-approved."""
        if not evidence_verified:
            return False
        return level == "high" or (level == "medium" and score >= CONFIDENCE_MEDIUM)

    def _needs_review(self, evidence_verified: bool, score: float) -> bool:
        """Check if validation needs manual review."""
        return (
            evidence_verified
            and CONFIDENCE_LOW_REVIEW <= score < CONFIDENCE_MEDIUM
        )

    def _find_mapping(self, mappings: list[dict], question_id: str | None) -> dict:
        """Find mapping by question ID."""
        if not question_id:
            return {}
        return next((m for m in mappings if m.get("question_id") == question_id), {})

    def _generate_clarification(self, validation: dict, mapping: dict) -> dict[str, Any]:
        """Generate clarification request for incomplete validation."""
        question_id = validation.get("question_id") or mapping.get("question_id", "UNKNOWN")
        question_text = mapping.get("question_text", "Unknown question")
        evidence_verified = validation.get("evidence_verified", False)
        confidence_score = validation.get("confidence_score", 0)
        evidence_quote = mapping.get("evidence_quote", "")
        answer_content = mapping.get("answer_content", "")

        understood = []
        if evidence_verified and evidence_quote:
            understood.append(f'Found in discussion: "{evidence_quote[:150]}..."')
        if answer_content:
            understood.append(f"We understand: {answer_content[:200]}")

        missing = []
        if not evidence_verified:
            missing.append("No clear evidence found in transcript")
        if confidence_score < CONFIDENCE_LOW_REVIEW:
            missing.append("Information is partial or unclear")

        return {
            "question_id": question_id,
            "question_text": question_text,
            "understood_parts": understood,
            "missing_parts": missing,
            "evidence_verified": evidence_verified,
            "confidence_score": confidence_score,
            "clarification_text": self._format_clarification_text(
                question_id, question_text, understood, missing
            ),
        }

    def _format_clarification_text(
        self,
        question_id: str,
        question_text: str,
        understood: list[str],
        missing: list[str],
    ) -> str:
        """Format clarification request as readable text."""
        understood_text = "\n".join(f"- {p}" for p in understood) if understood else "- Limited information available."
        missing_text = "\n".join(f"- {p}" for p in missing) if missing else "- Please provide more details."

        return f"""# Clarification Request for {question_id}

## What We Understood
{understood_text}

## What We Need
{missing_text}

## Question
**{question_text}**

## Your Input Needed
Please provide specific examples, methodology details, or relevant implementation information.
"""

    def _aggregate_confidence(self, validations: list[dict]) -> dict[str, Any]:
        """Aggregate validation results into summary."""
        total = len(validations)
        
        if total == 0:
            return {
                "total_answers": 0,
                "high_confidence": 0,
                "medium_confidence": 0,
                "low_confidence": 0,
                "average_score": 0.0,
                "auto_approved": 0,
                "needs_review": 0,
                "needs_clarification": 0,
                "overall_readiness": "review_required",
            }

        counts = {"high": 0, "medium": 0, "low": 0}
        for v in validations:
            level = v.get("confidence_level", "low")
            counts[level] = counts.get(level, 0) + 1

        scores = [v.get("confidence_score", 0.0) for v in validations]
        avg_score = sum(scores) / total

        return {
            "total_answers": total,
            "high_confidence": counts["high"],
            "medium_confidence": counts["medium"],
            "low_confidence": counts["low"],
            "average_score": round(avg_score, 3),
            "auto_approved": counts["high"],
            "needs_review": counts["medium"],
            "needs_clarification": counts["low"],
            "overall_readiness": "ready" if counts["low"] == 0 else "review_required",
        }


# =============================================================================
# Factory
# =============================================================================

def create_confidence_agent(wafr_schema: dict[str, Any] | None = None) -> ConfidenceAgent:
    """Factory function to create Confidence Agent."""
    return ConfidenceAgent(wafr_schema)