"""
Gap Detection Agent - Identifies unanswered WAFR questions.

Uses Strands framework to detect gaps in WAFR coverage and prioritize
which questions need answers most urgently.
"""

import json
import logging
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError
from strands import Agent, tool

from wafr.agents.config import BEDROCK_REGION, DEFAULT_MODEL_ID
from wafr.agents.model_config import get_strands_model
from wafr.agents.utils import retry_with_backoff, extract_json_from_text
from wafr.agents.wafr_context import get_wafr_context_summary, load_wafr_schema

logger = logging.getLogger(__name__)


# =============================================================================
# Priority Scoring Constants
# =============================================================================

CRITICALITY_SCORES: dict[str, int] = {
    "critical": 40,
    "high": 30,
    "medium": 20,
    "low": 10,
}

# Weight multipliers for priority calculation
PILLAR_COVERAGE_WEIGHT = 0.3
HRI_INDICATOR_WEIGHT = 20
BEST_PRACTICE_WEIGHT = 2
BEST_PRACTICE_MAX = 10
MAX_PRIORITY_SCORE = 100.0


# =============================================================================
# System Prompt
# =============================================================================

GAP_DETECTION_BASE_PROMPT = """
You are an expert in AWS Well-Architected Framework Reviews (WAFR). Your job is to 
identify gaps - questions that haven't been adequately answered based on the 
transcript and current answers.

GAP DETECTION PROCESS:
1. Compare answered questions against complete WAFR schema
2. Identify unanswered questions (gaps)
3. Calculate priority score for each gap based on:
   - Question criticality (critical=40, high=30, medium=20, low=10)
   - Pillar coverage (lower coverage = higher priority)
   - High Risk Issue (HRI) indicators (presence increases priority)
   - Best practice count (more practices = higher priority)

PRIORITY CALCULATION:
- Criticality weight: 40 points max
- Pillar coverage weight: 30 points max (inverse: lower coverage = higher priority)
- HRI indicator weight: 20 points max
- Best practice count: 10 points max
- Total: 0-100 (higher = more urgent)

GAP IDENTIFICATION:
- A gap is a WAFR question that has NO answer or only partial answer
- Check transcript for context hints (keywords, related services)
- Prioritize critical and high-criticality questions
- Focus on pillars with low coverage

Use identify_gap() to record each gap with priority score.
"""


def get_gap_detection_system_prompt(wafr_schema: dict[str, Any] | None = None) -> str:
    """
    Generate enhanced system prompt with WAFR context.
    
    Args:
        wafr_schema: Optional WAFR schema for additional context
        
    Returns:
        Complete system prompt string
    """
    if not wafr_schema:
        return GAP_DETECTION_BASE_PROMPT

    wafr_context = get_wafr_context_summary(wafr_schema)
    return f"{GAP_DETECTION_BASE_PROMPT}\n\n{wafr_context}\n\nUse this WAFR context to identify all gaps comprehensively."


# =============================================================================
# Tools
# =============================================================================

@tool
def calculate_priority_score(
    question_id: str,
    criticality: str,
    pillar_coverage: float,
    has_hri_indicators: bool,
    best_practice_count: int,
) -> float:
    """
    Calculate priority score for a gap (0-100). Higher score = more urgent.
    
    Args:
        question_id: Question identifier
        criticality: "critical", "high", "medium", or "low"
        pillar_coverage: Current coverage percentage for pillar (0-100)
        has_hri_indicators: Whether question has HRI indicators
        best_practice_count: Number of best practices for question
        
    Returns:
        Priority score (0-100)
    """
    score = 0.0

    # Criticality weight (40 points max)
    score += CRITICALITY_SCORES.get(criticality, CRITICALITY_SCORES["medium"])

    # Pillar coverage weight (30 points max) - lower coverage = higher priority
    score += (100 - pillar_coverage) * PILLAR_COVERAGE_WEIGHT

    # HRI indicator weight (20 points max)
    if has_hri_indicators:
        score += HRI_INDICATOR_WEIGHT

    # Best practice count (10 points max)
    score += min(best_practice_count * BEST_PRACTICE_WEIGHT, BEST_PRACTICE_MAX)

    return min(score, MAX_PRIORITY_SCORE)


@tool
def identify_gap(
    question_id: str,
    question_text: str,
    pillar: str,
    criticality: str,
    priority_score: float,
    context_hint: str | None = None,
) -> dict[str, Any]:
    """
    Record an identified gap.
    
    Args:
        question_id: Question identifier
        question_text: Full question text
        pillar: Pillar ID
        criticality: Criticality level
        priority_score: Calculated priority score
        context_hint: Optional context from transcript
        
    Returns:
        Gap dictionary with all metadata
    """
    return {
        "question_id": question_id,
        "question_text": question_text,
        "pillar": pillar,
        "criticality": criticality,
        "priority_score": priority_score,
        "context_hint": context_hint,
        "status": "pending",
    }


# =============================================================================
# Gap Detection Agent
# =============================================================================

class GapDetectionAgent:
    """Agent that detects gaps in WAFR coverage."""

    def __init__(
        self,
        wafr_schema: dict[str, Any] | None = None,
        lens_context: dict[str, Any] | None = None,
        region_name: str = BEDROCK_REGION,
    ):
        """
        Initialize Gap Detection Agent.
        
        Args:
            wafr_schema: Complete WAFR question schema
            lens_context: Optional lens context for multi-lens support
            region_name: AWS region for Bedrock client
        """
        if wafr_schema is None:
            wafr_schema = load_wafr_schema()

        self.wafr_schema = wafr_schema or self._load_default_schema()
        self.lens_context = lens_context or {}
        self.region_name = region_name
        self.model_id = DEFAULT_MODEL_ID
        self._bedrock_client = None
        self.agent = self._create_agent()
    
    @property
    def bedrock(self) -> Any:
        """Lazily initialize Bedrock client on first use."""
        if self._bedrock_client is None:
            self._bedrock_client = boto3.client(
                "bedrock-runtime", region_name=self.region_name
            )
        return self._bedrock_client

    def _create_agent(self) -> Agent | None:
        """Create and configure Strands agent with tools."""
        system_prompt = get_gap_detection_system_prompt(self.wafr_schema)

        try:
            model = get_strands_model(DEFAULT_MODEL_ID)
            agent = Agent(
                system_prompt=system_prompt,
                name="GapDetectionAgent",
                **({"model": model} if model else {}),
            )
            self._register_tools(agent)
            return agent

        except Exception as e:
            logger.warning("Strands Agent initialization issue: %s, using direct Bedrock", e)
            return None

    def _register_tools(self, agent: Agent) -> None:
        """Register tools with agent, trying available methods."""
        tools = [calculate_priority_score, identify_gap]

        for method_name in ("add_tool", "register_tool"):
            if not hasattr(agent, method_name):
                continue

            try:
                for t in tools:
                    getattr(agent, method_name)(t)
                return
            except Exception as e:
                logger.warning("Could not add tools via %s: %s", method_name, e)

    def process(
        self,
        answered_questions: list[str],
        pillar_coverage: dict[str, float],
        session_id: str,
        transcript: str | None = None,
        insights: list[dict] | None = None,
        progress_callback: Optional[callable] = None,
    ) -> dict[str, Any]:
        """
        Identify gaps in WAFR coverage.
        
        Only includes gaps that are relevant to the transcript/use case.
        Uses Claude with transcript summary to determine answerable questions.
        
        Args:
            answered_questions: List of question IDs that have answers
            pillar_coverage: Dict mapping pillar IDs to coverage percentages
            session_id: Session identifier
            transcript: Optional transcript for context hints
            insights: Optional extracted insights for relevance checking
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dictionary with identified gaps sorted by priority (only relevant gaps)
        """
        logger.info("GapDetectionAgent: Detecting gaps for session %s", session_id)

        # Generate transcript summary for Claude analysis
        transcript_summary = None
        if transcript:
            try:
                transcript_summary = self._generate_transcript_summary(transcript, insights)
                logger.info(f"Generated transcript summary for gap analysis ({len(transcript_summary)} chars)")
            except Exception as e:
                logger.warning(f"Failed to generate transcript summary: {e}, using keyword matching only")

        all_questions = self._get_all_questions()
        answered_set = set(answered_questions)
        gaps = []
        filtered_count = 0
        claude_checked = 0
        keyword_matched = 0
        
        # Calculate total unanswered questions for progress tracking
        unanswered_questions = [q for q in all_questions if q["id"] not in answered_set]
        total_unanswered = len(unanswered_questions)
        logger.info(f"Analyzing {total_unanswered} unanswered questions for relevance...")

        # Process questions in parallel for better performance
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        gaps = []
        lock = threading.Lock()
        filtered_count = 0
        claude_checked = 0
        keyword_matched = 0
        processed_count = 0
        
        # Maximum parallel question analysis (adjust based on Bedrock rate limits)
        MAX_PARALLEL_GAP_ANALYSIS = 5
        
        logger.info(f"Analyzing {total_unanswered} unanswered questions for relevance in parallel (max {MAX_PARALLEL_GAP_ANALYSIS} concurrent)...")
        
        def analyze_single_question(question: dict, index: int) -> Optional[dict]:
            """Analyze a single question for relevance and create gap record if relevant."""
            question_id = question["id"]
            
            try:
                # Check if question is relevant using Claude + keyword matching
                is_relevant = self._check_question_relevance(
                    question, transcript, insights, transcript_summary
                )
                
                if not is_relevant:
                    logger.debug(
                        f"Filtered out question {question_id}: no evidence or assumptions from transcript"
                    )
                    return None
                
                # Track which method found the relevance
                relevance_method = "claude" if transcript_summary else "keyword"
                
                # This is a relevant gap - calculate priority and create gap record
                gap = self._create_gap_record(question, pillar_coverage, transcript)
                gap["relevance_method"] = relevance_method
                
                return gap
                
            except Exception as e:
                logger.error(f"Error analyzing question {question_id}: {e}")
                return None
        
        # Process questions in parallel with controlled concurrency
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_GAP_ANALYSIS) as executor:
            # Submit all tasks
            future_to_question = {
                executor.submit(analyze_single_question, question, i): (i, question)
                for i, question in enumerate(unanswered_questions, 1)
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_question):
                idx, question = future_to_question[future]
                
                with lock:
                    processed_count += 1
                    
                    # Emit progress callback every 5 questions
                    if progress_callback and (processed_count % 5 == 0 or processed_count == total_unanswered):
                        progress_pct = 50 + int((processed_count / total_unanswered) * 5)  # 50-55% range
                        progress_callback(
                            "gap_detection",
                            f"Analyzing question relevance: {processed_count}/{total_unanswered}",
                            {
                                "progress_percentage": progress_pct,
                                "current": processed_count,
                                "total": total_unanswered
                            }
                        )
                    
                    # Log progress every 10 questions
                    if processed_count % 10 == 0 or processed_count == total_unanswered:
                        logger.info(f"Gap analysis progress: {processed_count}/{total_unanswered} questions checked ({(processed_count/total_unanswered)*100:.0f}%)")
                
                try:
                    result = future.result()
                    if result:
                        with lock:
                            gaps.append(result)
                            # Track method used
                            if result.get("relevance_method") == "claude":
                                claude_checked += 1
                            else:
                                keyword_matched += 1
                    else:
                        with lock:
                            filtered_count += 1
                except Exception as e:
                    logger.error(f"Exception collecting result for question {idx}: {e}")
                    with lock:
                        filtered_count += 1

        # Sort by priority (highest first)
        gaps.sort(key=lambda x: x["priority_score"], reverse=True)

        logger.info(
            f"Gap detection: {len(gaps)} relevant gaps found, {filtered_count} filtered out "
            f"(Claude-checked: {claude_checked}, keyword-matched: {keyword_matched})"
        )

        return {
            "session_id": session_id,
            "total_gaps": len(gaps),
            "gaps": gaps,
            "filtered_count": filtered_count,
            "transcript_summary_used": transcript_summary is not None,
            "agent": "gap_detection",
        }

    def _generate_transcript_summary(
        self,
        transcript: str,
        insights: list[dict] | None = None,
    ) -> str:
        """
        Generate a logical summary of the transcript for gap analysis.
        
        Args:
            transcript: Workshop transcript
            insights: Extracted insights
            
        Returns:
            Summary string with key architectural information
        """
        # Build insights summary
        insights_text = ""
        if insights:
            insights_summary = []
            for insight in insights[:20]:  # Top 20 insights
                insights_summary.append({
                    "type": insight.get("insight_type", ""),
                    "content": insight.get("content", "")[:200],
                    "pillar": insight.get("pillar", ""),
                })
            insights_text = json.dumps(insights_summary, indent=2)
        
        prompt = f"""Analyze this AWS Well-Architected Framework workshop transcript and create a logical summary that captures:
1. Workload/use case type and purpose
2. Key architectural decisions and patterns
3. AWS services and technologies mentioned
4. Operational practices discussed
5. Security measures mentioned
6. Reliability and scalability approaches
7. Cost optimization strategies
8. Any constraints, requirements, or risks identified

TRANSCRIPT (first 8000 chars):
{transcript[:8000]}

KEY INSIGHTS:
{insights_text[:2000] if insights_text else "No insights available"}

Create a concise but comprehensive summary (300-500 words) that captures the logical structure and key information from the transcript. Focus on information that would be relevant for answering WAFR questions.

Return ONLY the summary text, no markdown formatting, no JSON structure."""

        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1000,
                    "temperature": 0.2,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                }),
                contentType="application/json",
                accept="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            summary = response_body.get('content', [{}])[0].get('text', '')
            
            if summary:
                logger.debug(f"Generated transcript summary ({len(summary)} chars)")
                return summary
            else:
                logger.warning("Failed to generate transcript summary, using fallback")
                return transcript[:1000]  # Fallback to first 1000 chars
                
        except Exception as e:
            logger.warning(f"Error generating transcript summary: {e}, using fallback")
            return transcript[:1000]  # Fallback to first 1000 chars
    
    def _check_question_relevance_with_claude(
        self,
        question: dict[str, Any],
        transcript_summary: str,
        transcript: str,
        insights: list[dict] | None = None,
    ) -> bool:
        """
        Use Claude to determine if a question can be answered from transcript.
        
        Args:
            question: Question data from schema
            transcript_summary: Logical summary of transcript
            transcript: Full transcript
            insights: Extracted insights
            
        Returns:
            True if question can be answered, False otherwise
        """
        question_text = question.get("text", "")
        question_id = question.get("id", "")
        pillar = question.get("pillar_id", "")
        
        # Build insights context
        insights_context = ""
        if insights:
            relevant_insights = [
                insight for insight in insights
                if insight.get("pillar", "").lower() == pillar.lower()
            ][:5]
            if relevant_insights:
                insights_context = "\n".join([
                    f"- {insight.get('content', '')[:150]}"
                    for insight in relevant_insights
                ])
        
        prompt = f"""You are analyzing whether a WAFR question can be answered from a workshop transcript.

QUESTION:
{question_text}

Question ID: {question_id}
Pillar: {pillar}

TRANSCRIPT SUMMARY (Logical Summary):
{transcript_summary}

RELEVANT INSIGHTS:
{insights_context if insights_context else "No specific insights for this pillar"}

TRANSCRIPT EXCERPT (for reference):
{transcript[:3000]}

TASK:
Determine if this question can be answered from the transcript using EITHER:
1. Direct evidence (explicit statements, quotes, mentions)
2. Reasonable inference (logical conclusions based on transcript patterns)

CRITICAL RULES:
- Answer "yes" ONLY if there's evidence OR reasonable assumptions can be made
- Answer "no" if the question is not relevant to the use case/workload
- Answer "no" if you would need to guess or use only general AWS knowledge
- Consider the transcript summary as the logical representation of what was discussed

Return ONLY a JSON object:
{{
  "can_answer": true or false,
  "reasoning": "Brief explanation of why this can/cannot be answered",
  "evidence_type": "direct" or "inference" or "none",
  "confidence": 0.0-1.0
}}

Return ONLY the JSON, no other text."""

        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 500,
                    "temperature": 0.1,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                }),
                contentType="application/json",
                accept="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            response_text = response_body.get('content', [{}])[0].get('text', '')
            
            # Parse JSON response
            parsed = extract_json_from_text(response_text)
            if parsed and isinstance(parsed, dict):
                can_answer = parsed.get("can_answer", False)
                confidence = parsed.get("confidence", 0.0)
                reasoning = parsed.get("reasoning", "")
                
                # Only return True if Claude says yes AND confidence is reasonable
                if can_answer and confidence >= 0.3:
                    logger.debug(
                        f"Claude determined question {question_id} can be answered "
                        f"(confidence: {confidence:.2f}, reasoning: {reasoning[:100]})"
                    )
                    return True
                else:
                    logger.debug(
                        f"Claude determined question {question_id} cannot be answered "
                        f"(confidence: {confidence:.2f}, reasoning: {reasoning[:100]})"
                    )
                    return False
            else:
                logger.warning(f"Failed to parse Claude response for question {question_id}")
                return False
                
        except Exception as e:
            logger.warning(f"Error checking question relevance with Claude: {e}")
            return False
    
    def _check_question_relevance(
        self,
        question: dict[str, Any],
        transcript: str | None,
        insights: list[dict] | None = None,
        transcript_summary: str | None = None,
    ) -> bool:
        """
        Check if a question is relevant to the transcript/use case.
        
        Uses Claude analysis with transcript summary + keyword matching fallback.
        
        Args:
            question: Question data from schema
            transcript: Workshop transcript
            insights: Extracted insights
            transcript_summary: Optional pre-generated summary
            
        Returns:
            True if question is relevant, False otherwise
        """
        if not transcript:
            return False
        
        # First, try Claude-based analysis with summary
        if transcript_summary:
            claude_result = self._check_question_relevance_with_claude(
                question, transcript_summary, transcript, insights
            )
            if claude_result:
                return True
        
        # Fallback to keyword matching
        question_text = question.get("text", "").lower()
        question_keywords = question.get("keywords", [])
        transcript_lower = transcript.lower()
        
        # Check for direct keyword matches
        for keyword in question_keywords:
            if keyword.lower() in transcript_lower:
                return True
        
        # Check important words
        important_words = [
            word for word in question_text.split()
            if len(word) > 4 and word not in ["what", "how", "which", "when", "where", "does", "have", "are", "the", "this", "that"]
        ]
        matches = sum(1 for word in important_words[:5] if word in transcript_lower)
        if matches >= 2:
            return True
        
        # Check insights
        if insights:
            insight_text = " ".join([
                insight.get("content", "").lower() + " " + insight.get("transcript_quote", "").lower()
                for insight in insights[:10]
            ])
            for keyword in question_keywords:
                if keyword.lower() in insight_text:
                    return True
        
        return False
    
    def _create_gap_record(
        self,
        question: dict[str, Any],
        pillar_coverage: dict[str, float],
        transcript: str | None,
    ) -> dict[str, Any]:
        """
        Create a gap record for an unanswered question.
        
        Args:
            question: Question data from schema
            pillar_coverage: Current coverage by pillar
            transcript: Optional transcript for context hints
            
        Returns:
            Gap record with priority score
        """
        pillar = question.get("pillar_id", "UNKNOWN")
        criticality = question.get("criticality", "medium")
        has_hri = len(question.get("hri_indicators", [])) > 0
        bp_count = len(question.get("best_practices", []))
        coverage = pillar_coverage.get(pillar, 0.0)

        priority_score = calculate_priority_score(
            question_id=question["id"],
            criticality=criticality,
            pillar_coverage=coverage,
            has_hri_indicators=has_hri,
            best_practice_count=bp_count,
        )

        context_hint = self._find_context_hint(question, transcript) if transcript else None

        gap = identify_gap(
            question_id=question["id"],
            question_text=question["text"],
            pillar=pillar,
            criticality=criticality,
            priority_score=priority_score,
            context_hint=context_hint,
        )

        gap["question_data"] = question
        return gap

    def _get_all_questions(self) -> list[dict[str, Any]]:
        """
        Get all WAFR questions from schema and lens context.
        
        Returns:
            List of all questions with pillar and lens metadata
        """
        all_questions = []

        # Get standard WAFR questions
        all_questions.extend(self._get_schema_questions())

        # Add lens-specific questions
        all_questions.extend(self._get_lens_questions())

        return all_questions

    def _get_schema_questions(self) -> list[dict[str, Any]]:
        """Extract questions from WAFR schema."""
        questions = []

        if not self.wafr_schema or "pillars" not in self.wafr_schema:
            return questions

        for pillar in self.wafr_schema["pillars"]:
            pillar_id = pillar.get("id", "UNKNOWN")

            for question in pillar.get("questions", []):
                question["pillar_id"] = pillar_id
                question["lens_alias"] = "wellarchitected"
                questions.append(question)

        return questions

    def _get_lens_questions(self) -> list[dict[str, Any]]:
        """Extract questions from lens context."""
        questions = []

        if not self.lens_context or not self.lens_context.get("all_questions"):
            return questions

        for lens_q in self.lens_context["all_questions"]:
            # Skip standard WAFR questions (already included)
            if lens_q.get("lens_alias") == "wellarchitected":
                continue

            question_dict = {
                "id": lens_q.get("question_id", ""),
                "text": lens_q.get("question_title", ""),
                "pillar_id": lens_q.get("pillar_id", "UNKNOWN"),
                "criticality": "medium",
                "keywords": lens_q.get("best_practices", [])[:5],
                "best_practices": lens_q.get("best_practices", []),
                "hri_indicators": [],
                "lens_alias": lens_q.get("lens_alias", ""),
                "lens_name": lens_q.get("lens_name", ""),
            }
            questions.append(question_dict)

        return questions

    def _find_context_hint(
        self,
        question: dict[str, Any],
        transcript: str,
    ) -> str | None:
        """
        Find related context in transcript for a question.
        
        Uses keyword matching from question schema to identify
        relevant discussion in the transcript.
        
        Args:
            question: Question with keywords and related services
            transcript: Full transcript text
            
        Returns:
            Context hint string or None if no matches found
        """
        if not transcript or not question:
            return None

        keywords = question.get("keywords", [])
        related_services = question.get("related_services", [])
        search_terms = keywords + related_services

        if not search_terms:
            return None

        transcript_lower = transcript.lower()
        found_terms = [
            term for term in search_terms
            if term.lower() in transcript_lower
        ]

        if not found_terms:
            return None

        return f"Related terms found in transcript: {', '.join(found_terms[:3])}"

    def _load_default_schema(self) -> dict[str, Any]:
        """
        Load default WAFR schema structure.
        
        Returns:
            Empty schema structure as fallback
        """
        return {"pillars": []}


# =============================================================================
# Factory Function
# =============================================================================

def create_gap_detection_agent(
    wafr_schema: dict[str, Any] | None = None,
    lens_context: dict[str, Any] | None = None,
) -> GapDetectionAgent:
    """
    Factory function to create Gap Detection Agent.
    
    Args:
        wafr_schema: Optional WAFR schema
        lens_context: Optional lens context for multi-lens support
        
    Returns:
        Configured GapDetectionAgent instance
    """
    return GapDetectionAgent(wafr_schema=wafr_schema, lens_context=lens_context)