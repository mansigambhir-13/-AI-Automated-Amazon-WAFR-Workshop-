"""
Mapping Agent - Maps extracted insights to WAFR pillars and questions.

Uses Strands framework to intelligently map architecture insights
from workshop transcripts to specific WAFR questions.
"""

import json
import logging
import re
from typing import Any

import boto3
from botocore.exceptions import ClientError
from strands import Agent, tool

from wafr.agents.config import BEDROCK_REGION, DEFAULT_MODEL_ID
from wafr.agents.model_config import get_strands_model
from wafr.agents.utils import (
    batch_process,
    deduplicate_mappings,
    extract_json_from_text,
    retry_with_backoff,
    validate_mapping,
)
from wafr.agents.wafr_context import (
    get_question_context,
    get_wafr_context_summary,
    load_wafr_schema,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MIN_RELEVANCE_SCORE = 0.5
DEFAULT_RELEVANCE_SCORE = 0.5
MAX_QUESTIONS_IN_PROMPT = 20
MAX_CONTEXT_LENGTH = 500
MAX_QUESTION_CONTEXTS = 3
BATCH_SIZE = 5
MAX_WORKERS = 3
BATCH_TIMEOUT = 120.0


# =============================================================================
# System Prompt
# =============================================================================

MAPPING_BASE_PROMPT = """
You are a WAFR (AWS Well-Architected Framework Review) expert with deep knowledge of all six pillars and their questions.

Your task is to map architecture insights from workshop transcripts to specific WAFR questions.

THE 6 WAFR PILLARS:
1. Operational Excellence (OPS) - Running and monitoring systems to deliver business value
2. Security (SEC) - Protecting information and assets
3. Reliability (REL) - Recovering from failures and meeting demand
4. Performance Efficiency (PERF) - Using resources efficiently
5. Cost Optimization (COST) - Managing costs effectively
6. Sustainability (SUS) - Minimizing environmental impact

MAPPING PROCESS:
For each insight, you must:
1. Identify which pillar(s) it relates to (can be multiple)
2. Find the specific question(s) it addresses from the WAFR schema
3. Determine relevance_score (0.0-1.0) - how directly the insight answers the question
4. Assess answer_coverage: "complete" if fully answers, "partial" if partially answers
5. Synthesize answer_content: Create a clear answer text based on the insight
6. Extract evidence_quote: The exact transcript quote supporting the answer

MAPPING RULES:
- Be precise: Only map if there's a clear connection
- Multiple mappings allowed: One insight can map to multiple questions
- Prioritize direct answers over tangential connections
- Use question keywords and best practices to guide mapping
- Consider question criticality when determining relevance
- Map to lens-specific questions when insights are relevant to specialized lenses

OUTPUT FORMAT:
Return mappings as a JSON array. Each mapping must have:
- pillar: Pillar ID (OPS, SEC, REL, PERF, COST, SUS)
- question_id: Question ID (e.g., OPS_01, SEC_02, or lens-specific IDs)
- question_text: Full question text
- lens_alias: (optional) Lens alias if this is a lens-specific question
- relevance_score: 0.0-1.0 (how relevant)
- answer_coverage: "complete" or "partial"
- answer_content: Synthesized answer text
- evidence_quote: Exact transcript quote
"""


def get_mapping_system_prompt(
    wafr_schema: dict[str, Any] | None = None,
    lens_context: dict[str, Any] | None = None,
) -> str:
    """
    Generate enhanced system prompt with WAFR context and lens-specific questions.
    
    Args:
        wafr_schema: Optional WAFR schema for context
        lens_context: Optional lens context for multi-lens support
        
    Returns:
        Complete system prompt string
    """
    lens_question_context = _build_lens_question_context(lens_context)

    if wafr_schema:
        wafr_context = get_wafr_context_summary(wafr_schema)
        return (
            f"{MAPPING_BASE_PROMPT}\n\n{wafr_context}{lens_question_context}\n\n"
            "Use the WAFR schema and lens questions to find exact question IDs and match insights appropriately."
        )

    return MAPPING_BASE_PROMPT + lens_question_context


def _build_lens_question_context(lens_context: dict[str, Any] | None) -> str:
    """
    Build lens-specific question context for the prompt.
    
    Args:
        lens_context: Lens context with questions
        
    Returns:
        Formatted lens question context string
    """
    if not lens_context or not lens_context.get("all_questions"):
        return ""

    context_parts = [
        "\n\nLENS-SPECIFIC QUESTIONS AVAILABLE:",
        "In addition to standard WAFR questions, the following specialized lens questions are available:\n",
    ]

    # Group by lens
    questions_by_lens: dict[str, list[dict]] = {}
    for q in lens_context["all_questions"]:
        alias = q.get("lens_alias", "wellarchitected")
        if alias not in questions_by_lens:
            questions_by_lens[alias] = []
        questions_by_lens[alias].append(q)

    for alias, questions in questions_by_lens.items():
        if alias == "wellarchitected":
            continue

        lens_info = lens_context["lenses"].get(alias, {})
        lens_name = lens_info.get("name", alias)
        context_parts.append(f"{lens_name} ({len(questions)} questions):")

        # Show sample questions
        for q in questions[:5]:
            question_title = q.get("question_title", q.get("question_id", ""))
            context_parts.append(f"  - {question_title}")

        if len(questions) > 5:
            context_parts.append(f"  ... and {len(questions) - 5} more")

        context_parts.append("")

    context_parts.extend([
        "When mapping insights, consider both standard WAFR questions AND lens-specific questions.",
        "If an insight is relevant to a lens-specific question, include the lens_alias in the mapping.",
    ])

    return "\n".join(context_parts)


# =============================================================================
# Tools
# =============================================================================

@tool
def get_wafr_schema() -> dict[str, Any]:
    """
    Get WAFR question schema structure.
    
    Returns:
        WAFR schema with pillars and questions
    """
    return load_wafr_schema()


@tool
def map_insight_to_wafr(
    insight: dict[str, Any],
    pillar: str,
    question_id: str,
    question_text: str,
    relevance_score: float,
    answer_coverage: str,
    answer_content: str,
    evidence_quote: str,
) -> dict[str, Any]:
    """
    Map an insight to a WAFR question.
    
    Args:
        insight: Original insight dictionary
        pillar: Pillar ID (OPS, SEC, REL, etc.)
        question_id: Question identifier
        question_text: Full question text
        relevance_score: How relevant this insight is (0.0-1.0)
        answer_coverage: "partial" or "complete"
        answer_content: Synthesized answer text
        evidence_quote: Transcript quote supporting the answer
        
    Returns:
        Mapping dictionary
    """
    return {
        "pillar": pillar,
        "question_id": question_id,
        "question_text": question_text,
        "relevance_score": relevance_score,
        "answer_coverage": answer_coverage,
        "answer_content": answer_content,
        "evidence_quote": evidence_quote,
        "source_insight": insight.get("id") or insight.get("content"),
    }


# =============================================================================
# Mapping Agent
# =============================================================================

class MappingAgent:
    """Agent that maps insights to WAFR questions."""

    def __init__(
        self,
        wafr_schema: dict[str, Any] | None = None,
        lens_context: dict[str, Any] | None = None,
    ):
        """
        Initialize Mapping Agent with Strands.
        
        Args:
            wafr_schema: Optional WAFR schema for context
            lens_context: Optional lens context for multi-lens support
        """
        if wafr_schema is None:
            wafr_schema = load_wafr_schema()

        self.wafr_schema = wafr_schema
        self.lens_context = lens_context or {}
        self.agent = self._create_agent()

    def _create_agent(self) -> Agent | None:
        """Create and configure Strands agent with tools."""
        # DISABLED: Bedrock agents don't support concurrent invocations
        # Using direct Bedrock calls instead to enable parallel processing
        system_prompt = get_mapping_system_prompt(self.wafr_schema, lens_context=self.lens_context)

        # Force use of direct Bedrock calls (supports parallel execution)
        return None

    def _register_tools(self, agent: Agent) -> None:
        """Register tools with agent, trying available methods."""
        tools = [get_wafr_schema, map_insight_to_wafr]

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
        insights: list[dict[str, Any]],
        session_id: str,
    ) -> dict[str, Any]:
        """
        Map insights to WAFR questions.
        
        Args:
            insights: List of extracted insights
            session_id: Session identifier
            
        Returns:
            Dictionary with WAFR mappings and coverage statistics
        """
        logger.info("MappingAgent: Mapping %d insights for session %s", len(insights), session_id)

        if not insights:
            return self._empty_result(session_id)

        # Process insights
        all_mappings = self._process_all_insights(insights, session_id)

        # Deduplicate mappings
        all_mappings = deduplicate_mappings(all_mappings)

        # Calculate pillar coverage
        pillar_coverage = self._calculate_pillar_coverage(all_mappings)

        return {
            "session_id": session_id,
            "total_mappings": len(all_mappings),
            "mappings": all_mappings,
            "pillar_coverage": pillar_coverage,
            "agent": "mapping",
        }

    def _empty_result(self, session_id: str) -> dict[str, Any]:
        """Return empty result structure."""
        return {
            "session_id": session_id,
            "total_mappings": 0,
            "mappings": [],
            "pillar_coverage": {},
            "agent": "mapping",
        }

    def _process_all_insights(
        self,
        insights: list[dict[str, Any]],
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Process all insights, using batch processing for large sets."""
        processor = lambda insight: self._process_single_insight(insight, session_id)

        if len(insights) > 10:
            results = batch_process(
                insights,
                processor,
                batch_size=BATCH_SIZE,
                max_workers=MAX_WORKERS,
                timeout=BATCH_TIMEOUT,
            )
            return [mapping for result in results for mapping in result]

        # Process directly for small batches
        all_mappings = []
        for insight in insights:
            all_mappings.extend(processor(insight))
        return all_mappings

    def _process_single_insight(
        self,
        insight: dict[str, Any],
        session_id: str,
    ) -> list[dict[str, Any]]:
        """
        Process a single insight and return its mappings.
        
        Args:
            insight: Insight to process
            session_id: Session identifier
            
        Returns:
            List of validated mappings for this insight
        """
        question_contexts = self._find_relevant_question_contexts(insight)
        question_list = self._build_question_list()
        prompt = self._build_mapping_prompt(insight, question_list)

        try:
            response = self._get_mapping_response(prompt)
            mappings = self._parse_mappings(response, insight)

            # Validate and enrich mappings
            validated = []
            for mapping in mappings:
                if validate_mapping(mapping):
                    mapping["session_id"] = session_id
                    mapping["source_insight_id"] = insight.get("id")
                    validated.append(mapping)
                else:
                    logger.warning(
                        "Invalid mapping skipped: %s",
                        mapping.get("question_id", "unknown"),
                    )

            return validated

        except Exception as e:
            logger.error("Error mapping insight: %s", str(e))
            return []

    def _find_relevant_question_contexts(
        self,
        insight: dict[str, Any],
    ) -> list[str]:
        """Find relevant question contexts based on keyword matching."""
        question_contexts = []
        insight_content = insight.get("content", "").lower()
        insight_quote = insight.get("transcript_quote", "").lower()

        # Check standard WAFR questions
        if self.wafr_schema:
            for pillar in self.wafr_schema.get("pillars", []):
                for question in pillar.get("questions", []):
                    keywords = question.get("keywords", [])
                    if any(
                        kw.lower() in insight_content or kw.lower() in insight_quote
                        for kw in keywords
                    ):
                        q_context = get_question_context(question.get("id"), self.wafr_schema)
                        if q_context:
                            question_contexts.append(q_context[:MAX_CONTEXT_LENGTH])

        # Check lens-specific questions
        if self.lens_context and self.lens_context.get("all_questions"):
            insight_text = f"{insight_content} {insight_quote}"
            question_contexts.extend(
                self._find_lens_question_contexts(insight_text)
            )

        return question_contexts

    def _find_lens_question_contexts(self, insight_text: str) -> list[str]:
        """Find relevant lens-specific question contexts."""
        contexts = []

        for lens_q in self.lens_context["all_questions"]:
            question_title = lens_q.get("question_title", "").lower()
            question_desc = lens_q.get("question_description", "").lower()
            best_practices = " ".join(lens_q.get("best_practices", [])).lower()

            # Simple keyword matching
            title_words = question_title.split()[:5]
            desc_words = question_desc.split()[:10]
            bp_words = [bp for bp in best_practices.split()[:5] if len(bp) > 3]

            if (
                any(word in insight_text for word in title_words)
                or any(word in insight_text for word in desc_words)
                or any(bp in insight_text for bp in bp_words)
            ):
                lens_name = lens_q.get("lens_name", "Lens")
                q_title = lens_q.get("question_title", "")
                q_desc = lens_q.get("question_description", "")[:200]
                contexts.append(f"[{lens_name}] {q_title}: {q_desc}")

        return contexts

    def _build_question_list(self) -> list[dict[str, Any]]:
        """Build simplified question list for prompts."""
        question_list = []

        if not self.wafr_schema:
            return question_list

        for pillar in self.wafr_schema.get("pillars", []):
            pillar_id = pillar.get("id", "UNKNOWN")
            pillar_name = pillar.get("name", pillar_id)

            for question in pillar.get("questions", []):
                question_list.append({
                    "question_id": question.get("id", ""),
                    "question_text": question.get("text", ""),
                    "pillar": pillar_id,
                    "pillar_name": pillar_name,
                    "keywords": question.get("keywords", []),
                    "criticality": question.get("criticality", "medium"),
                })

        return question_list

    def _build_mapping_prompt(
        self,
        insight: dict[str, Any],
        question_list: list[dict[str, Any]],
    ) -> str:
        """Build the mapping prompt for a single insight."""
        questions_json = json.dumps(question_list[:MAX_QUESTIONS_IN_PROMPT], indent=2)
        evidence_preview = insight.get("transcript_quote", "")[:200]

        return f"""You are a WAFR expert mapping architecture insights to AWS Well-Architected Framework questions.

ARCHITECTURE INSIGHT TO MAP:
Type: {insight.get('insight_type', 'unknown')}
Content: {insight.get('content', '')}
Evidence Quote: {insight.get('transcript_quote', '')}

AVAILABLE WAFR QUESTIONS:
{questions_json}

TASK: Map this insight to relevant WAFR questions. Return ONLY a valid JSON array of mappings.

OUTPUT FORMAT - Return ONLY this JSON structure (no markdown, no explanations):
[
  {{
    "pillar": "OPS",
    "question_id": "OPS_02",
    "question_text": "How do you design your workload so that you can understand its state?",
    "relevance_score": 0.85,
    "answer_coverage": "partial",
    "answer_content": "Based on the transcript, they use X-Ray and CloudWatch for observability...",
    "evidence_quote": "{evidence_preview}"
  }}
]

MAPPING RULES:
1. Match based on keywords, content, and question intent
2. relevance_score: 0.0-1.0 (only include if >0.5 - lowered for better coverage)
3. answer_coverage: "complete" if fully answers, "partial" if partially answers
4. answer_content: Synthesize answer DIRECTLY from transcript quote - use client's actual words
5. evidence_quote: Use the EXACT quote from the insight transcript_quote field
6. Map to ALL relevant questions where transcript provides ANY answer (be comprehensive)
7. IMPORTANT: Only create answers based on what client actually said - use transcript quotes

Return ONLY the JSON array, nothing else."""

    def _get_mapping_response(self, prompt: str) -> Any:
        """Get mapping response from agent or direct Bedrock."""
        if self.agent:
            try:
                return self._call_agent_with_retry(prompt)
            except Exception as agent_error:
                logger.warning(
                    "Strands agent failed for mapping, falling back to direct Bedrock: %s",
                    str(agent_error),
                )
                return self._call_bedrock_direct(prompt)

        return self._call_bedrock_direct(prompt)

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def _call_agent_with_retry(self, prompt: str) -> Any:
        """Call agent with retry logic."""
        if not self.agent:
            raise RuntimeError("Agent not initialized")
        return self.agent(prompt)

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def _call_bedrock_direct(self, prompt: str) -> str:
        """Fallback: Call Bedrock directly using invoke_model API."""
        bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        system_prompt = get_mapping_system_prompt(self.wafr_schema)

        try:
            response = bedrock.invoke_model(
                modelId=DEFAULT_MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "temperature": 0.2,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )

            result = json.loads(response["body"].read())
            return result.get("content", [{}])[0].get("text", "")

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            if error_code in ['UnrecognizedClientException', 'InvalidClientTokenId', 'InvalidUserID.NotFound']:
                logger.error("Bedrock direct call failed due to invalid credentials: %s", error_msg)
                from wafr.agents.utils import validate_aws_credentials
                _, cred_error_msg = validate_aws_credentials()
                logger.error("\n%s", cred_error_msg)
                raise
            elif error_code == 'ExpiredToken':
                logger.error("Bedrock direct call failed due to expired token: %s", error_msg)
                logger.error("Please refresh your AWS credentials (e.g., run 'aws sso login' or 'aws configure')")
                raise
            else:
                logger.error("Bedrock direct call failed: %s - %s", error_code, error_msg)
                raise
        except Exception as e:
            logger.error("Bedrock direct call failed: %s", e)
            raise

    def _calculate_pillar_coverage(
        self,
        mappings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Calculate coverage statistics by pillar."""
        pillar_coverage: dict[str, dict[str, Any]] = {}

        for mapping in mappings:
            pillar = mapping.get("pillar", "UNKNOWN")

            if pillar not in pillar_coverage:
                pillar_coverage[pillar] = {
                    "total_mappings": 0,
                    "questions_addressed": set(),
                }

            pillar_coverage[pillar]["total_mappings"] += 1
            pillar_coverage[pillar]["questions_addressed"].add(mapping.get("question_id"))

        # Convert sets to lists and calculate percentages
        for pillar in pillar_coverage:
            questions_addressed = pillar_coverage[pillar]["questions_addressed"]
            pillar_coverage[pillar]["questions_addressed"] = list(questions_addressed)

            total_questions = max(self._get_total_questions_for_pillar(pillar), 1)
            pillar_coverage[pillar]["coverage_pct"] = (
                len(questions_addressed) / total_questions * 100
            )

        return pillar_coverage

    def _get_total_questions_for_pillar(self, pillar_id: str) -> int:
        """Get total number of questions for a pillar."""
        for pillar in self.wafr_schema.get("pillars", []):
            if pillar.get("id") == pillar_id:
                return len(pillar.get("questions", []))
        return 1  # Default to 1 to avoid division by zero

    def _parse_mappings(
        self,
        response: Any,
        insight: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Parse agent response to extract mappings with improved JSON extraction."""
        mappings: list[dict[str, Any]] = []

        try:
            response_text, mappings = self._extract_response_text(response)

            # If we have text but no mappings yet, try to extract JSON
            if response_text and not mappings:
                mappings = self._extract_mappings_from_text(response_text)

            # If still no mappings, try regex extraction
            if not mappings and response_text:
                mappings = self._extract_mappings_with_regex(response_text)

        except Exception as e:
            logger.error("Error parsing mappings: %s", str(e))
            logger.debug("Response type: %s, Response preview: %s", type(response), str(response)[:200])

        # Validate and enrich mappings
        return self._validate_and_enrich_mappings(mappings, insight)

    def _extract_response_text(
        self,
        response: Any,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Extract text and any direct mappings from response."""
        mappings: list[dict[str, Any]] = []
        response_text = ""

        if isinstance(response, str):
            response_text = response

        elif isinstance(response, dict):
            if "content" in response:
                content = response.get("content", "")
                if isinstance(content, str):
                    response_text = content
                elif isinstance(content, list) and content:
                    response_text = " ".join([
                        item.get("text", "") if isinstance(item, dict) else str(item)
                        for item in content
                    ])
            elif "text" in response:
                response_text = str(response.get("text", ""))
            elif "mappings" in response:
                candidate = response["mappings"]
                if isinstance(candidate, list):
                    mappings = candidate
                elif candidate:
                    mappings = [candidate]
            else:
                response_text = json.dumps(response, ensure_ascii=False)
        else:
            response_text = str(response)

        return response_text, mappings

    def _extract_mappings_from_text(self, text: str) -> list[dict[str, Any]]:
        """Extract mappings from text using JSON parsing."""
        cleaned = text.strip()

        # Remove markdown code blocks if present
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        # Try extraction
        parsed = extract_json_from_text(cleaned, strict=False)

        if not parsed:
            return []

        if isinstance(parsed, list):
            return parsed

        if isinstance(parsed, dict):
            if "mappings" in parsed:
                candidate = parsed["mappings"]
                return candidate if isinstance(candidate, list) else [candidate] if candidate else []
            if "items" in parsed:
                candidate = parsed["items"]
                return candidate if isinstance(candidate, list) else [candidate] if candidate else []
            if "pillar" in parsed or "question_id" in parsed:
                return [parsed]

        return []

    def _extract_mappings_with_regex(self, text: str) -> list[dict[str, Any]]:
        """Extract mappings using regex patterns as fallback."""
        mappings = []

        # Look for JSON arrays
        json_array_pattern = r"\[\s*\{[^}]+\}\s*(?:,\s*\{[^}]+\}\s*)*\]"
        for match in re.finditer(json_array_pattern, text, re.DOTALL):
            try:
                parsed_array = json.loads(match.group(0))
                if isinstance(parsed_array, list) and parsed_array:
                    return parsed_array
            except json.JSONDecodeError:
                continue

        # Try individual mapping objects
        mapping_pattern = r'\{\s*"pillar"[^}]+\}'
        for match in re.finditer(mapping_pattern, text, re.DOTALL):
            try:
                mapping_obj = json.loads(match.group(0))
                if isinstance(mapping_obj, dict) and "question_id" in mapping_obj:
                    mappings.append(mapping_obj)
            except json.JSONDecodeError:
                continue

        return mappings

    def _validate_and_enrich_mappings(
        self,
        mappings: list[dict[str, Any]],
        insight: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Validate mappings and enrich with insight data."""
        validated = []

        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue

            # Skip invalid mappings without question_id
            if "question_id" not in mapping:
                continue

            # Set defaults
            mapping.setdefault("pillar", "UNKNOWN")
            mapping.setdefault("relevance_score", DEFAULT_RELEVANCE_SCORE)
            mapping.setdefault("answer_coverage", "partial")

            # Ensure minimum relevance score
            if mapping.get("relevance_score", 0) < MIN_RELEVANCE_SCORE:
                mapping["relevance_score"] = MIN_RELEVANCE_SCORE

            # Enrich with insight data if missing
            if not mapping.get("answer_content"):
                mapping["answer_content"] = insight.get("content", "")

            if not mapping.get("evidence_quote"):
                mapping["evidence_quote"] = insight.get("transcript_quote", "")

            if "question_text" not in mapping:
                mapping["question_text"] = self._get_question_text(mapping.get("question_id"))

            validated.append(mapping)

        if validated:
            logger.info("Successfully parsed %d mappings from response", len(validated))
        else:
            logger.warning("No valid mappings parsed from response")

        return validated

    def _get_question_text(self, question_id: str | None) -> str:
        """Get question text from schema by ID."""
        if not question_id or not self.wafr_schema:
            return ""

        for pillar in self.wafr_schema.get("pillars", []):
            for question in pillar.get("questions", []):
                if question.get("id") == question_id:
                    return question.get("text", "")

        return ""


# =============================================================================
# Factory Function
# =============================================================================

def create_mapping_agent(
    wafr_schema: dict[str, Any] | None = None,
    lens_context: dict[str, Any] | None = None,
) -> MappingAgent:
    """
    Factory function to create Mapping Agent.
    
    Args:
        wafr_schema: Optional WAFR schema for context
        lens_context: Optional lens context for multi-lens support
        
    Returns:
        Configured MappingAgent instance
    """
    return MappingAgent(wafr_schema=wafr_schema, lens_context=lens_context)