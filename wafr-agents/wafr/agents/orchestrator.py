"""
Agent Orchestrator - Coordinates multi-agent workflow.

Uses Strands framework for agent coordination to process WAFR assessments
through a pipeline of specialized agents.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# Optional strands import (not used directly, but may be needed by agents)
try:
    from strands import Agent
except ImportError:
    Agent = None

from wafr.agents.answer_synthesis_agent import create_answer_synthesis_agent
from wafr.agents.confidence_agent import create_confidence_agent
from wafr.agents.gap_detection_agent import create_gap_detection_agent
from wafr.agents.mapping_agent import create_mapping_agent
from wafr.agents.prompt_generator_agent import create_prompt_generator_agent
from wafr.agents.report_agent import create_report_agent
from wafr.agents.scoring_agent import create_scoring_agent
from wafr.agents.understanding_agent import create_understanding_agent
from wafr.agents.utils import cache_result
from wafr.agents.wa_tool_agent import WAToolAgent

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_ENVIRONMENT = "PRODUCTION"
DEFAULT_LENS_ALIAS = "wellarchitected"

SCHEMA_CACHE_TTL_SECONDS = 3600.0
MAX_GAPS_TO_PROCESS = 10
MIN_CONFIDENCE_THRESHOLD = 0.4
MIN_LENS_DETECTION_CONFIDENCE = 0.2
MAX_AUTO_SELECT_LENSES = 3

# User choice constants
CHOICE_MANUAL = "manual"
CHOICE_PROCEED = "proceed"
CHOICE_CONSOLE = "console"
CHOICE_SKIP = "skip"

# Status constants
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"
STATUS_ERROR = "error"
STATUS_EXISTING = "existing"
STATUS_CREATED = "created"

# Confidence levels
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

logger = logging.getLogger(__name__)

# Schema cache (module-level for persistence across instances)
_schema_cache: Dict[str, Any] = {}


# -----------------------------------------------------------------------------
# Main Orchestrator Class
# -----------------------------------------------------------------------------


class WafrOrchestrator:
    """Orchestrates the multi-agent WAFR processing pipeline."""

    def __init__(
        self,
        wafr_schema: Optional[Dict] = None,
        lens_context: Optional[Dict] = None,
    ):
        """
        Initialize orchestrator with all agents.

        Args:
            wafr_schema: Complete WAFR schema (loaded from file/database).
            lens_context: Optional lens context for multi-lens support.
        """
        if wafr_schema is None:
            from wafr.agents.wafr_context import load_wafr_schema
            wafr_schema = load_wafr_schema()

        self.wafr_schema = wafr_schema
        self.lens_context = lens_context or {}
        self.logger = logger

        self._initialize_agents()

    def _initialize_agents(self) -> None:
        """Initialize all processing agents with schema and lens context."""
        # Core processing agents
        self.understanding_agent = create_understanding_agent(
            self.wafr_schema,
            lens_context=self.lens_context,
        )
        self.mapping_agent = create_mapping_agent(
            self.wafr_schema,
            lens_context=self.lens_context,
        )
        self.confidence_agent = create_confidence_agent(self.wafr_schema)
        self.gap_detection_agent = create_gap_detection_agent(
            self.wafr_schema,
            lens_context=self.lens_context,
        )
        self.answer_synthesis_agent = create_answer_synthesis_agent(
            self.wafr_schema,
            lens_context=self.lens_context,
        )
        self.prompt_generator_agent = create_prompt_generator_agent(self.wafr_schema)
        self.scoring_agent = create_scoring_agent(self.wafr_schema)
        self.report_agent = create_report_agent(
            self.wafr_schema,
            lens_context=self.lens_context,
        )

        # Tool agents
        self.wa_tool_agent = WAToolAgent()

    # -------------------------------------------------------------------------
    # Main Processing Methods
    # -------------------------------------------------------------------------

    def process_transcript(
        self,
        transcript: str,
        session_id: str,
        generate_report: bool = True,
        client_name: Optional[str] = None,
        environment: str = DEFAULT_ENVIRONMENT,
        existing_workload_id: Optional[str] = None,
        progress_callback: Optional[Callable[[str, str, Optional[Dict]], None]] = None,
        fast_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Process transcript through complete agent pipeline.

        Args:
            transcript: Workshop transcript text (text input only).
            session_id: Session identifier.
            generate_report: Whether to generate final report.
            client_name: Client/company name for WA Tool workload.
            environment: Environment type (PRODUCTION, PREPRODUCTION, DEVELOPMENT).
            existing_workload_id: Existing WA Tool workload ID to use.
            progress_callback: Optional callback for progress updates.
            fast_mode: If True, skips non-essential steps for faster processing.

        Returns:
            Complete assessment results dictionary.
        """
        start_time = time.time()
        mode_str = "FAST MODE" if fast_mode else "STANDARD MODE"
        self.logger.info(f"[SESSION:{session_id}] Orchestrator: Starting processing ({mode_str})")

        results = self._create_initial_results(session_id)
        results["fast_mode"] = fast_mode

        # Initialize user context from session parameters
        try:
            from wafr.agents.user_context import get_user_context_manager
            user_context_manager = get_user_context_manager()
            user_context_manager.set_context(
                session_id=session_id,
                client_name=client_name,
                environment=environment,
            )
        except Exception as e:
            self.logger.debug(f"Could not initialize user context: {e}")

        try:
            # Use transcript directly (text input only - no PDF processing)
            enhanced_transcript = transcript

            # Step 0.5: Infer user context from transcript
            try:
                from wafr.agents.user_context import get_user_context_manager
                user_context_manager = get_user_context_manager()
                user_context_manager.infer_from_transcript(
                    session_id=session_id,
                    transcript=enhanced_transcript,
                )
            except Exception as e:
                self.logger.debug(f"Could not infer user context: {e}")

            # Step 0.6: Auto-detect relevant lenses (including GenAI lens) based on use case
            # Skip in fast_mode to save time
            if not fast_mode:
                self._auto_detect_lenses(enhanced_transcript)
                if self.lens_context:
                    detected_lenses = list(self.lens_context.get('lenses', {}).keys())
                    self.logger.info(f"Auto-detected lenses for assessment: {detected_lenses}")
                    results["detected_lenses"] = detected_lenses
                    # Re-initialize agents with lens context if lenses were detected
                    if detected_lenses and len(detected_lenses) > 1:
                        self._initialize_agents()
                        self.logger.info(f"Re-initialized agents with lens context: {detected_lenses}")
            else:
                self.logger.info("Skipping lens detection (fast_mode=True)")

            # Step 1-6: Core pipeline processing
            insights = self._step_extract_insights(
                enhanced_transcript,
                session_id, results, progress_callback
            )
            
            # Update user context with inferred insights
            try:
                from wafr.agents.user_context import get_user_context_manager
                user_context_manager = get_user_context_manager()
                user_context_manager.infer_from_transcript(
                    session_id=session_id,
                    transcript=enhanced_transcript,
                    insights=insights,
                )
            except Exception as e:
                self.logger.debug(f"Could not update user context with insights: {e}")

            mappings = self._step_map_insights(
                insights, session_id, results, progress_callback
            )

            validated_answers = self._step_validate_confidence(
                mappings, transcript, session_id, results, progress_callback
            )

            gap_result = self._step_detect_gaps(
                validated_answers, transcript, insights, session_id, results, progress_callback
            )

            # Step 6: Generate AI answers for gaps (NEW - HITL workflow)
            synthesized_answers = self._step_synthesize_gap_answers(
                gap_result, transcript, insights, validated_answers,
                session_id, results, progress_callback
            )

            # Step 6.5: Auto-populate answers using synthesized answers (NEW)
            all_answers = self._step_auto_populate_answers(
                validated_answers, synthesized_answers, session_id,
                results, progress_callback
            )

            # Skip prompt generation in fast_mode (not essential for results)
            if not fast_mode:
                self._step_generate_prompts(
                    gap_result, results, progress_callback
                )
            else:
                results["steps"]["gap_prompts"] = []
                self.logger.info("Skipping prompt generation (fast_mode=True)")

            # Use all_answers (includes synthesized) for scoring
            self._step_score_answers(
                all_answers, session_id, results, progress_callback
            )

            # Step 7: Report generation (optional)
            if generate_report:
                # Use all_answers (includes synthesized) for report generation
                self._step_generate_report(
                    all_answers, gap_result, results,
                    session_id, progress_callback
                )
            else:
                results["steps"]["report"] = None

            # Step 8: WA Tool integration (OPTIONAL - only when generate_report=True)
            # Creates an AWS Well-Architected Tool workload and generates the official report.
            # Skip this step when generate_report=False for faster assessments (e.g., frontend testing)
            if generate_report:
                self.logger.info(f"WA Tool integration enabled - client_name: {client_name}")
                self.logger.info("Calling _step_wa_tool_integration...")
                self._step_wa_tool_integration(
                    insights, mappings, all_answers, transcript,
                    session_id, client_name, environment, existing_workload_id,
                    generate_report, results, progress_callback, fast_mode
                )
                # Ensure we record status if WA integration didn't populate
                if results["steps"].get("wa_workload") is None:
                    self.logger.error("WA Tool integration failed - setting error status")
                    results["steps"]["wa_workload"] = {
                        "status": "failed",
                        "error": "WA Tool integration did not return a workload",
                    }
                else:
                    self.logger.info(f"WA Tool integration completed - workload: {results['steps'].get('wa_workload', {}).get('workload_id', 'N/A')}")
            else:
                self.logger.info("WA Tool integration skipped (generate_report=False)")
                results["steps"]["wa_workload"] = {
                    "status": "skipped",
                    "reason": "generate_report=False"
                }

            # Finalize results (use all_answers to include synthesized answers)
            self._finalize_results(
                results, insights, mappings, all_answers,
                gap_result, start_time
            )

            return results

        except Exception as e:
            self.logger.error(f"[SESSION:{session_id}] Orchestrator processing failed: {e}", exc_info=True)
            results["status"] = STATUS_ERROR
            results["error"] = str(e)
            results["processing_time"]["total"] = round(time.time() - start_time, 2)
            return results

    def process_user_answer(
        self,
        session_id: str,
        question_id: str,
        answer: str,
        wafr_schema: Dict,
    ) -> Dict[str, Any]:
        """
        Process user-provided answer for a gap question.

        Args:
            session_id: Session identifier.
            question_id: Question ID.
            answer: User's answer text.
            wafr_schema: WAFR schema.

        Returns:
            Processing result with score.
        """
        self.logger.info(f"Processing user answer for question {question_id}")

        question_data = self._get_question_data(question_id, wafr_schema)
        if not question_data:
            return {"error": f"Question {question_id} not found"}

        answer_dict = {
            "question_id": question_id,
            "question_text": question_data.get("text", ""),
            "pillar": question_data.get("pillar_id", "UNKNOWN"),
            "answer_content": answer,
            "evidence_quotes": [],
            "source": "user_input",
        }

        scoring_result = self.scoring_agent.process(
            answers=[answer_dict],
            wafr_schema=wafr_schema,
            session_id=session_id,
        )

        scored_answers = scoring_result.get("scored_answers", [])
        scores = scored_answers[0] if scored_answers else {}

        return {
            "question_id": question_id,
            "answer": answer,
            "scores": scores,
            "status": "scored",
        }

    # -------------------------------------------------------------------------
    # Pipeline Step Methods
    # -------------------------------------------------------------------------

    def _step_extract_insights(
        self,
        enhanced_transcript: str,
        session_id: str,
        results: Dict,
        progress_callback: Optional[Callable],
    ) -> List[Dict]:
        """Step 1: Extract insights from transcript."""
        step_start = time.time()
        self.logger.info(f"[SESSION:{session_id}] Step 1: Extracting insights from transcript")

        if progress_callback:
            progress_callback("understanding", "Extracting insights from transcript...", {"progress_percentage": 10})

        insights = []
        try:
            insights_result = self.understanding_agent.process(enhanced_transcript, session_id)
            results["steps"]["understanding"] = insights_result
            insights = insights_result.get("insights", [])

            if not insights:
                self.logger.warning(f"[SESSION:{session_id}] No insights extracted, continuing with empty list")

            self.logger.info(f"[SESSION:{session_id}] Extracted {len(insights)} insights")

        except Exception as e:
            self.logger.error(f"[SESSION:{session_id}] Understanding agent failed: {e}", exc_info=True)
            results["steps"]["understanding"] = {
                "error": str(e),
                "insights": [],
                "agent": "understanding",
            }

        results["processing_time"]["understanding"] = round(time.time() - step_start, 2)
        return insights

    def _step_map_insights(
        self,
        insights: List[Dict],
        session_id: str,
        results: Dict,
        progress_callback: Optional[Callable],
    ) -> List[Dict]:
        """Step 2: Map insights to WAFR questions."""
        step_start = time.time()
        self.logger.info(f"[SESSION:{session_id}] Step 2: Mapping insights to WAFR questions")

        if progress_callback:
            progress_callback("mapping", "Mapping insights to WAFR questions...", {"progress_percentage": 25})

        mappings = []
        try:
            if insights:
                mapping_result = self.mapping_agent.process(insights, session_id)
                results["steps"]["mapping"] = mapping_result
                mappings = mapping_result.get("mappings", [])
            else:
                results["steps"]["mapping"] = {
                    "session_id": session_id,
                    "total_mappings": 0,
                    "mappings": [],
                    "pillar_coverage": {},
                    "agent": "mapping",
                }

        except Exception as e:
            self.logger.error(f"[SESSION:{session_id}] Mapping agent failed: {e}", exc_info=True)
            results["steps"]["mapping"] = {"error": str(e), "mappings": []}

        results["processing_time"]["mapping"] = round(time.time() - step_start, 2)
        return mappings

    def _step_validate_confidence(
        self,
        mappings: List[Dict],
        transcript: str,
        session_id: str,
        results: Dict,
        progress_callback: Optional[Callable],
    ) -> List[Dict]:
        """Step 3: Validate evidence and confidence scores."""
        step_start = time.time()
        self.logger.info(f"[SESSION:{session_id}] Step 3: Validating evidence and confidence")

        if progress_callback:
            progress_callback("confidence", "Validating evidence and confidence scores...", {"progress_percentage": 40})

        validated_answers = []
        try:
            if mappings:
                confidence_result = self.confidence_agent.process(
                    mappings, transcript, session_id
                )
                results["steps"]["confidence"] = confidence_result
            else:
                confidence_result = {
                    "session_id": session_id,
                    "summary": {"average_score": 0, "total_answers": 0},
                    "all_validations": [],
                    "agent": "confidence",
                }
                results["steps"]["confidence"] = confidence_result

            validated_answers = self._extract_validated_answers(mappings, confidence_result)
            
            # Fallback: If confidence validation failed or returned empty, use mappings directly
            if not validated_answers and mappings:
                self.logger.warning(f"[SESSION:{session_id}] Confidence validation returned no results, using mappings as fallback")
                validated_answers = [
                    {
                        **m,
                        "confidence_score": m.get("relevance_score", 0.6),
                        "confidence_level": "medium",
                        "evidence_verified": True,
                        "validation_passed": True,
                        "source": "mapping_fallback",
                    }
                    for m in mappings
                ]

        except Exception as e:
            self.logger.error(f"[SESSION:{session_id}] Confidence agent failed: {e}", exc_info=True)
            results["errors"].append({"step": "confidence", "error": str(e)})
            results["steps"]["confidence"] = {
                "error": str(e),
                "all_validations": [],
                "agent": "confidence",
            }
            
            # Fallback: Use mappings directly if confidence agent completely fails
            if mappings:
                self.logger.warning(f"[SESSION:{session_id}] Using mappings as fallback after confidence agent failure")
                validated_answers = [
                    {
                        **m,
                        "confidence_score": m.get("relevance_score", 0.6),
                        "confidence_level": "medium",
                        "evidence_verified": True,
                        "validation_passed": True,
                        "source": "error_fallback",
                    }
                    for m in mappings
                ]
            else:
                validated_answers = []

        results["processing_time"]["confidence"] = round(time.time() - step_start, 2)
        return validated_answers

    def _step_detect_gaps(
        self,
        validated_answers: List[Dict],
        transcript: str,
        insights: List[Dict],
        session_id: str,
        results: Dict,
        progress_callback: Optional[Callable],
    ) -> Dict:
        """Step 4: Detect gaps in WAFR coverage (only relevant gaps)."""
        step_start = time.time()
        self.logger.info(f"[SESSION:{session_id}] Step 4: Detecting gaps")

        if progress_callback:
            progress_callback("gap_detection", "Detecting gaps in WAFR coverage...", {"progress_percentage": 50})

        gap_result = {"gaps": []}
        try:
            answered_questions = [
                a.get("question_id")
                for a in validated_answers
                if a.get("question_id")
            ]

            pillar_coverage = results["steps"].get("mapping", {}).get("pillar_coverage", {})
            normalized_coverage = self._normalize_pillar_coverage(pillar_coverage)

            gap_result = self.gap_detection_agent.process(
                answered_questions=answered_questions,
                pillar_coverage=normalized_coverage,
                session_id=session_id,
                transcript=transcript,
                insights=insights,  # Pass insights for relevance checking
                progress_callback=progress_callback,  # Pass progress callback for SSE updates
            )
            results["steps"]["gap_detection"] = gap_result

        except Exception as e:
            self.logger.error(f"[SESSION:{session_id}] Gap detection agent failed: {e}", exc_info=True)
            results["steps"]["gap_detection"] = {"error": str(e), "gaps": []}

        results["processing_time"]["gap_detection"] = round(time.time() - step_start, 2)
        return gap_result

    def _step_synthesize_gap_answers(
        self,
        gap_result: Dict,
        transcript: str,
        insights: List[Dict],
        validated_answers: List[Dict],
        session_id: str,
        results: Dict,
        progress_callback: Optional[Callable],
    ) -> List[Dict]:
        """Step 6: Generate AI answers for all gap questions."""
        step_start = time.time()
        self.logger.info(f"[SESSION:{session_id}] Step 6: Synthesizing answers for gap questions")

        if progress_callback:
            progress_callback("answer_synthesis", "Generating AI answers for gap questions...", {"progress_percentage": 55})

        synthesized_answers = []
        try:
            gaps = gap_result.get("gaps", [])
            
            if gaps:
                # Create a progress callback wrapper for synthesis
                def synthesis_progress_callback(current: int, total: int, question_id: str = ""):
                    """Emit progress during synthesis."""
                    if progress_callback:
                        # Calculate progress within the 55-60% range
                        synthesis_progress = 55 + (5 * current / max(total, 1))
                        progress_callback(
                            "answer_synthesis",
                            f"Synthesizing answer {current}/{total}: {question_id}",
                            {
                                "progress_percentage": int(synthesis_progress),
                                "current": current,
                                "total": total,
                                "question_id": question_id
                            }
                        )
                
                # Create a heartbeat callback to keep SSE connection alive
                def heartbeat_callback():
                    """Send heartbeat event to keep SSE connection alive during long operations."""
                    # Heartbeat events are filtered in orchestrator_integration.py
                    # They don't emit progress events, just keep the connection alive
                    if progress_callback:
                        # Send a minimal heartbeat marker (filtered by orchestrator integration)
                        progress_callback(
                            "answer_synthesis",
                            "",  # Empty message
                            {"heartbeat": True, "silent": True}  # Mark as silent to avoid logging
                        )
                
                # Convert SynthesizedAnswer objects to dicts for storage
                synthesized_objects = self.answer_synthesis_agent.synthesize_gaps(
                    gaps=gaps,
                    transcript=transcript,
                    insights=insights,
                    validated_answers=validated_answers,
                    session_id=session_id,
                    progress_callback=synthesis_progress_callback,  # Pass progress callback
                    heartbeat_callback=heartbeat_callback,  # Pass heartbeat callback to keep connection alive
                )
                
                # Convert to dict format for storage
                synthesized_answers = [sa.to_dict() for sa in synthesized_objects]
                
                results["steps"]["answer_synthesis"] = {
                    "session_id": session_id,
                    "total_synthesized": len(synthesized_answers),
                    "synthesized_answers": synthesized_answers,
                    "agent": "answer_synthesis",
                }
                
                self.logger.info(f"[SESSION:{session_id}] Synthesized {len(synthesized_answers)} answers for gap questions")
            else:
                results["steps"]["answer_synthesis"] = {
                    "session_id": session_id,
                    "total_synthesized": 0,
                    "synthesized_answers": [],
                    "agent": "answer_synthesis",
                }
                self.logger.info(f"[SESSION:{session_id}] No gaps to synthesize answers for")

        except Exception as e:
            self.logger.error(f"[SESSION:{session_id}] Answer synthesis agent failed: {e}", exc_info=True)
            results["steps"]["answer_synthesis"] = {
                "error": str(e),
                "synthesized_answers": [],
                "agent": "answer_synthesis",
            }

        results["processing_time"]["answer_synthesis"] = round(time.time() - step_start, 2)
        return synthesized_answers
    
    def _step_auto_populate_answers(
        self,
        validated_answers: List[Dict],
        synthesized_answers: List[Dict],
        session_id: str,
        results: Dict,
        progress_callback: Optional[Callable],
    ) -> List[Dict]:
        """
        Step 6.5: Automatically merge synthesized answers with validated answers.
        
        This step automatically answers questions using the synthesized answers,
        merging them with validated answers from the transcript.
        
        Args:
            validated_answers: Answers extracted from transcript
            synthesized_answers: Answers synthesized for gaps
            session_id: Session identifier
            results: Results dictionary
            progress_callback: Optional progress callback
            
        Returns:
            Combined list of all answers (validated + synthesized)
        """
        step_start = time.time()
        self.logger.info(f"[SESSION:{session_id}] Step 6.5: Auto-populating answers from synthesized answers")

        if progress_callback:
            progress_callback("auto_populate", "Auto-populating answers from synthesis...", {"progress_percentage": 60})

        all_answers = validated_answers  # Default to validated answers only
        try:
            # Merge synthesized answers into validated answers
            all_answers = self._merge_synthesized_answers(
                validated_answers, synthesized_answers
            )
            
            results["steps"]["auto_populate"] = {
                "session_id": session_id,
                "validated_count": len(validated_answers),
                "synthesized_count": len(synthesized_answers),
                "total_count": len(all_answers),
                "all_answers": all_answers,  # Store all_answers for review items endpoint
                "merged": True,
            }
            
            self.logger.info(
                f"[SESSION:{session_id}] Merged {len(synthesized_answers)} synthesized answers with "
                f"{len(validated_answers)} validated answers = {len(all_answers)} total"
            )
            
        except Exception as e:
            self.logger.error(f"[SESSION:{session_id}] Auto-populate answers failed: {e}", exc_info=True)
            results["steps"]["auto_populate"] = {
                "error": str(e),
                "merged": False,
            }
            # Keep all_answers as validated_answers (already set as default)

        results["processing_time"]["auto_populate"] = round(time.time() - step_start, 2)
        return all_answers
    
    def _merge_synthesized_answers(
        self,
        validated_answers: List[Dict],
        synthesized_answers: List[Dict],
    ) -> List[Dict]:
        """
        Merge synthesized answers with validated answers.
        
        Strategy:
        - Validated answers from transcript are kept as-is
        - Synthesized answers are converted to validated answer format
        - No duplicates (synthesized answers override if same question_id exists)
        
        Args:
            validated_answers: Answers from transcript
            synthesized_answers: AI-synthesized answers for gaps
            
        Returns:
            Merged list of all answers
        """
        # Create a map of validated answers by question_id
        validated_map = {
            ans.get("question_id", ""): ans
            for ans in validated_answers
        }
        
        # Convert synthesized answers to validated answer format
        for synth_ans in synthesized_answers:
            question_id = synth_ans.get("question_id", "")
            if not question_id:
                continue
            
            # Convert synthesized answer to validated answer format
            validated_format = {
                "question_id": question_id,
                "question_text": synth_ans.get("question_text", ""),
                "pillar": synth_ans.get("pillar", ""),
                "answer_content": synth_ans.get("synthesized_answer", ""),
                "source": "AI_SYNTHESIZED",
                "confidence": synth_ans.get("confidence", 0.5),
                "synthesis_method": synth_ans.get("synthesis_method", "INFERENCE"),
                "reasoning_chain": synth_ans.get("reasoning_chain", []),
                "assumptions": synth_ans.get("assumptions", []),
                "evidence_quotes": [
                    {
                        "text": eq.get("text", ""),
                        "location": eq.get("location", ""),
                        "relevance": eq.get("relevance", ""),
                    }
                    for eq in synth_ans.get("evidence_quotes", [])
                ],
                "requires_attention": synth_ans.get("requires_attention", []),
                "confidence_justification": synth_ans.get("confidence_justification", ""),
            }
            
            # Add to map (synthesized answers don't override validated answers)
            # Only add if question_id not already in validated answers
            if question_id not in validated_map:
                validated_map[question_id] = validated_format
        
        # Return all answers as a list
        return list(validated_map.values())

    def _step_generate_prompts(
        self,
        gap_result: Dict,
        results: Dict,
        progress_callback: Optional[Callable],
    ) -> None:
        """Step 5: Generate smart prompts for gaps."""
        step_start = time.time()
        self.logger.info("Step 5: Generating smart prompts for gaps")

        if progress_callback:
            progress_callback("prompt_generator", "Generating smart prompts for gaps...", {"progress_percentage": 65})

        gap_prompts = []
        try:
            gaps = gap_result.get("gaps", [])[:MAX_GAPS_TO_PROCESS]

            # Process prompts in parallel for better performance
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import threading
            
            gap_prompts_with_index = []
            lock = threading.Lock()
            
            def generate_prompt_for_gap(gap: Dict, index: int) -> tuple:
                """Generate prompt for a single gap with its own agent instance."""
                try:
                    question_data = gap.get("question_data", {})
                    if question_data:
                        # Create a new agent instance for this thread to avoid concurrent invocation issues
                        from wafr.agents.prompt_generator_agent import PromptGeneratorAgent
                        thread_agent = PromptGeneratorAgent(self.wafr_schema)
                        prompt = thread_agent.process(gap, question_data)
                        return (index, prompt)
                    return (index, None)
                except Exception as e:
                    self.logger.warning(f"Error generating prompt for gap {gap.get('question_id', 'unknown')}: {e}")
                    return (index, None)
            
            # Use parallel processing with max 5 workers
            max_workers = min(5, len(gaps))
            if max_workers > 1:
                self.logger.info(f"Generating prompts for {len(gaps)} gaps in parallel (max {max_workers} workers)...")
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all tasks
                    future_to_gap = {
                        executor.submit(generate_prompt_for_gap, gap, i): (i, gap)
                        for i, gap in enumerate(gaps)
                    }
                    
                    # Collect results as they complete
                    for future in as_completed(future_to_gap):
                        idx, gap = future_to_gap[future]
                        try:
                            result_idx, prompt = future.result()
                            if prompt:
                                with lock:
                                    gap_prompts_with_index.append((result_idx, prompt))
                        except Exception as e:
                            self.logger.error(f"Exception generating prompt for gap {idx}: {e}")
                
                # Sort by original index to maintain order
                gap_prompts_with_index.sort(key=lambda x: x[0])
                gap_prompts = [p[1] for p in gap_prompts_with_index]
            else:
                # Sequential processing for single gap
                for gap in gaps:
                    try:
                        question_data = gap.get("question_data", {})
                        if question_data:
                            prompt = self.prompt_generator_agent.process(gap, question_data)
                            gap_prompts.append(prompt)
                    except Exception as e:
                        self.logger.warning(f"Error generating prompt for gap: {e}")

            results["steps"]["gap_prompts"] = gap_prompts

        except Exception as e:
            self.logger.error(f"Prompt generator failed: {e}", exc_info=True)
            results["steps"]["gap_prompts"] = []

        results["processing_time"]["prompt_generator"] = round(time.time() - step_start, 2)

    def _step_score_answers(
        self,
        validated_answers: List[Dict],
        session_id: str,
        results: Dict,
        progress_callback: Optional[Callable],
    ) -> None:
        """Step 6: Score and rank answers."""
        step_start = time.time()
        self.logger.info("Step 6: Scoring and ranking answers")

        if progress_callback:
            progress_callback("scoring", "Scoring and ranking answers...", {"progress_percentage": 70})

        try:
            if validated_answers:
                scoring_result = self.scoring_agent.process(
                    answers=validated_answers,
                    wafr_schema=self.wafr_schema,
                    session_id=session_id,
                )
                results["steps"]["scoring"] = scoring_result
            else:
                results["steps"]["scoring"] = {
                    "session_id": session_id,
                    "total_answers": 0,
                    "scored_answers": [],
                    "review_queues": {},
                    "agent": "scoring",
                }

        except Exception as e:
            self.logger.error(f"Scoring agent failed: {e}", exc_info=True)
            results["steps"]["scoring"] = {"error": str(e)}

        results["processing_time"]["scoring"] = round(time.time() - step_start, 2)

    def _step_generate_report(
        self,
        validated_answers: List[Dict],
        gap_result: Dict,
        results: Dict,
        session_id: str,
        progress_callback: Optional[Callable],
    ) -> None:
        """Step 7: Generate comprehensive report."""
        step_start = time.time()
        self.logger.info("Step 7: Generating report")

        if progress_callback:
            progress_callback("report", "Generating comprehensive report...", {"progress_percentage": 75})

        try:
            pillar_coverage = results["steps"].get("mapping", {}).get("pillar_coverage", {})

            assessment_data = {
                "answers": validated_answers,
                "scores": results["steps"].get("confidence", {}).get("summary", {}),
                "gaps": gap_result.get("gaps", []),
                "pillar_coverage": pillar_coverage,
            }

            report_result = self.report_agent.process(assessment_data, session_id)

            if isinstance(report_result, dict):
                report_result = self._sanitize_dict_recursive(report_result)

            results["steps"]["report"] = report_result
            
            # Persist report to disk (JSON) for download fallback
            try:
                # Use /tmp/ for Lambda/AgentCore (only writable location)
                report_dir = "/tmp/reports"
                os.makedirs(report_dir, exist_ok=True)
                report_file_path = os.path.join(report_dir, f"wafr_report_{session_id}.json")
                with open(report_file_path, "w", encoding="utf-8") as f:
                    json.dump(report_result, f, indent=2, ensure_ascii=False, default=str)
                results["steps"]["report"]["file_path"] = report_file_path
                self.logger.info(f"Wrote internal report to {report_file_path}")
            except Exception as e:
                self.logger.warning(f"Failed to write internal report file: {e}", exc_info=True)

            # Upload regular report to S3 if file path is available
            try:
                report_file_path = None
                if isinstance(report_result, dict):
                    report_file_path = (
                        report_result.get("file_path") or 
                        report_result.get("report_path") or 
                        report_result.get("report_filename")
                    )
                
                if report_file_path and os.path.exists(report_file_path):
                    from wafr.utils.s3_storage import get_s3_storage
                    s3_storage = get_s3_storage()
                    s3_key = s3_storage.upload_report(
                        file_path=report_file_path,
                        session_id=session_id,
                        report_type="wafr_report",
                        metadata={
                            "report_type": "comprehensive",
                            "generated_by": "report_agent"
                        }
                    )
                    if s3_key:
                        results["steps"]["report"]["s3_key"] = s3_key
                        results["steps"]["report"]["s3_bucket"] = s3_storage.bucket_name
                        self.logger.info(f"Report uploaded to S3: {s3_key}")
                        
                        # Generate presigned URL for JSON report download
                        try:
                            json_download_url = s3_storage.get_report_url(s3_key, expires_in=86400)
                            if json_download_url:
                                results["steps"]["report"]["download_url"] = json_download_url
                        except Exception:
                            pass  # Not critical
                else:
                    self.logger.debug(f"Report file path not found or file doesn't exist: {report_file_path}")
            except Exception as e:
                self.logger.warning(f"Failed to upload report to S3: {e}", exc_info=True)
                # Don't fail the pipeline if S3 upload fails

        except Exception as e:
            self.logger.error(f"Report agent failed: {e}", exc_info=True)
            error_msg = self._sanitize_error_message(str(e))
            results["steps"]["report"] = {"error": error_msg}

        results["processing_time"]["report"] = round(time.time() - step_start, 2)

    def _step_wa_tool_integration(
        self,
        insights: List[Dict],
        mappings: List[Dict],
        validated_answers: List[Dict],
        transcript: str,
        session_id: str,
        client_name: Optional[str],
        environment: str,
        existing_workload_id: Optional[str],
        generate_report: bool,
        results: Dict,
        progress_callback: Optional[Callable],
        fast_mode: bool = False,
    ) -> None:
        """Step 8: WA Tool workload integration with sub-step progress updates."""
        import sys
        
        step_start = time.time()
        self.logger.info("Step 8: WA Tool workload integration")
        print(f"[WA_TOOL] Starting: session={session_id}", file=sys.stderr, flush=True)

        # Send initial progress WITH progress_percentage
        if progress_callback:
            progress_callback("wa_tool", "Initializing WA Tool integration...", {"progress_percentage": 82})

        try:
            synthesized_answers = results["steps"].get("answer_synthesis", {}).get("synthesized_answers", [])
            
            transcript_analysis = {
                "session_id": session_id,
                "insights": insights,
                "mappings": mappings,
                "validated_answers": validated_answers,
                "synthesized_answers": synthesized_answers,
                "confidence": results["steps"].get("confidence", {}),
                "lens_context": self.lens_context,
            }

            # Sub-step 1: Get or create workload
            if progress_callback:
                progress_callback("wa_tool_workload", "Creating/getting AWS workload...", {"progress_percentage": 85})
            
            print(f"[WA_TOOL] Getting/creating workload...", file=sys.stderr, flush=True)
            
            workload_id, verified_lenses = self._get_or_create_workload(
                existing_workload_id, client_name, environment,
                transcript_analysis, results
            )
            
            if not workload_id:
                error_msg = "Failed to create/get workload - workload_id is None"
                self.logger.error(error_msg)
                print(f"[WA_TOOL] ERROR: {error_msg}", file=sys.stderr, flush=True)
                if progress_callback:
                    progress_callback("error", error_msg, {"error": error_msg, "step": "wa_tool_workload"})
                results["steps"]["wa_workload"] = {"error": error_msg, "status": "failed"}
                return
            
            print(f"[WA_TOOL] Workload ready: {workload_id}", file=sys.stderr, flush=True)
            self.logger.info(f"WA Tool sub-step: workload ready - {workload_id}")

            # Sub-step 2: Populate answers and generate report
            if progress_callback:
                progress_callback("wa_tool_populate", "Populating WAFR answers...", {"progress_percentage": 88})
            
            self._populate_workload_answers(
                workload_id, transcript_analysis, transcript,
                generate_report, client_name, session_id, results, fast_mode,
                progress_callback=progress_callback,
                verified_lenses=verified_lenses
            )
            
            # Check for errors after populate
            wa_result = results.get("steps", {}).get("wa_workload", {})
            if wa_result.get("report_status") == "failed" or wa_result.get("populate_error"):
                error_msg = wa_result.get("report_error") or wa_result.get("populate_error") or "WA Tool failed"
                self.logger.error(f"WA Tool failed: {error_msg}")
                print(f"[WA_TOOL] FAILED: {error_msg}", file=sys.stderr, flush=True)
                if progress_callback:
                    progress_callback("error", f"WA Tool failed: {error_msg}", {"error": error_msg, "step": "wa_tool"})
                return

            # Final success progress
            if progress_callback:
                progress_callback("wa_tool_complete", "WA Tool integration complete!", {"progress_percentage": 99})
            
            print(f"[WA_TOOL] Completed successfully: {workload_id}", file=sys.stderr, flush=True)
            self.logger.info(f"WA Tool workload processed: {workload_id}")

        except Exception as e:
            error_msg = f"WA Tool integration failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            print(f"[WA_TOOL] EXCEPTION: {error_msg}", file=sys.stderr, flush=True)
            
            import traceback
            traceback.print_exc()
            
            # CRITICAL: Emit error to WebSocket
            if progress_callback:
                progress_callback("error", error_msg, {"error": str(e), "step": "wa_tool"})
            
            results["steps"]["wa_workload"] = {"error": str(e), "status": "failed"}

        results["processing_time"]["wa_tool"] = round(time.time() - step_start, 2)

    # -------------------------------------------------------------------------
    # Helper Methods - WA Tool Integration
    # -------------------------------------------------------------------------

    def _get_or_create_workload(
        self,
        existing_workload_id: Optional[str],
        client_name: Optional[str],
        environment: str,
        transcript_analysis: Dict,
        results: Dict,
    ) -> tuple[Optional[str], Optional[List[str]]]:
        """
        Get existing workload or create a new one.
        
        Returns:
            Tuple of (workload_id, verified_lenses) where verified_lenses is None for existing workloads
        """
        try:
            if existing_workload_id:
                self.logger.info(f"Using existing workload: {existing_workload_id}")
                workload = self.wa_tool_agent.wa_client.get_workload(existing_workload_id)
                console_url = f"https://console.aws.amazon.com/wellarchitected/home?#/workloads/{existing_workload_id}"
                results["steps"]["wa_workload"] = {
                    "workload_id": existing_workload_id,
                    "workload_arn": workload.get("Workload", {}).get("WorkloadArn"),
                    "status": STATUS_EXISTING,
                    "console_url": console_url,
                }
                return existing_workload_id, None

            # Ensure client_name has a default value if None
            if not client_name:
                client_name = "WAFR-Client"
                self.logger.warning(f"No client_name provided, using default: {client_name}")

            self.logger.info("Creating new WA Tool workload...")
            workload = self.wa_tool_agent.create_workload_from_transcript(
                transcript_analysis=transcript_analysis,
                client_name=client_name,
                environment=environment,
            )
            workload_id = workload.get("WorkloadId")
            verified_lenses = workload.get("_verified_lenses", [])
            console_url = f"https://console.aws.amazon.com/wellarchitected/home?#/workloads/{workload_id}"
            results["steps"]["wa_workload"] = {
                "workload_id": workload_id,
                "workload_arn": workload.get("WorkloadArn"),
                "status": STATUS_CREATED,
                "console_url": console_url,
                "verified_lenses": verified_lenses,
            }
            return workload_id, verified_lenses
        except Exception as e:
            self.logger.error(f"Error getting/creating workload: {e}", exc_info=True)
            results["steps"]["wa_workload"] = {
                "error": str(e),
                "status": "failed",
            }
            return None, None

    def _populate_workload_answers(
        self,
        workload_id: str,
        transcript_analysis: Dict,
        transcript: str,
        generate_report: bool,
        client_name: Optional[str],
        session_id: str,
        results: Dict,
        fast_mode: bool = False,
        progress_callback: Optional[Callable] = None,
        verified_lenses: Optional[List[str]] = None,
    ) -> None:
        """Populate answers in WA Tool workload and generate report with progress updates."""
        import sys
        
        logger.info("Auto-filling all WAFR questions from transcript...")
        print(f"[POPULATE] Starting for workload {workload_id}", file=sys.stderr, flush=True)

        try:
            # Sub-step: Populate answers
            if progress_callback:
                progress_callback("wa_tool_answers", "Auto-filling WAFR answers from transcript...", {"progress_percentage": 89})
            
            print(f"[POPULATE] Calling populate_answers_from_analysis...", file=sys.stderr, flush=True)
            
            populate_result = self.wa_tool_agent.populate_answers_from_analysis(
                workload_id=workload_id,
                transcript_analysis=transcript_analysis,
                transcript=transcript,
                mapping_agent=self.mapping_agent,
                lens_context=self.lens_context,
                verified_lenses=verified_lenses,
            )
            results["steps"]["wa_workload"]["answers_populated"] = populate_result

            updated_count = populate_result.get("updated_answers", 0)
            total_count = populate_result.get("total_questions", 0)
            skipped_count = populate_result.get("skipped_answers", 0)

            logger.info(f"Auto-filled {updated_count} out of {total_count} questions")
            print(f"[POPULATE] Filled {updated_count}/{total_count} questions", file=sys.stderr, flush=True)

            # Handle remaining questions if needed (only in interactive mode)
            if skipped_count > 0 and generate_report:
                # Check if we're in interactive mode (has a TTY)
                import sys
                is_interactive = sys.stdin.isatty() if hasattr(sys.stdin, 'isatty') else False
                
                if is_interactive:
                    try:
                        self._handle_remaining_questions(
                            workload_id, updated_count, total_count, skipped_count, results
                        )
                    except Exception as e:
                        logger.warning(f"Error handling remaining questions: {e}")
                else:
                    logger.info(
                        f"Skipping user prompt for remaining questions (non-interactive mode). "
                        f"{skipped_count} questions remain unanswered."
                    )
                    results["steps"]["wa_workload"]["remaining_questions"] = {
                        "skipped": skipped_count,
                        "reason": "non_interactive_mode",
                        "message": "Questions can be answered manually in AWS Console"
                    }

            # Sub-step: Create milestone
            if progress_callback:
                progress_callback("wa_tool_milestone", "Creating milestone in AWS WA Tool...", {"progress_percentage": 92})
            
            print(f"[POPULATE] Creating milestone and report...", file=sys.stderr, flush=True)
            
            try:
                self._create_milestone_and_report(
                    workload_id, client_name, session_id, results, progress_callback
                )
            except Exception as e:
                logger.error(f"Error creating milestone and report: {e}", exc_info=True)
                print(f"[POPULATE] Milestone/report FAILED: {e}", file=sys.stderr, flush=True)
                results["steps"]["wa_workload"]["report_error"] = str(e)
                results["steps"]["wa_workload"]["report_status"] = "failed"
                
                # Emit error via callback
                if progress_callback:
                    progress_callback("error", f"Report generation failed: {e}", {"error": str(e), "step": "wa_tool_report"})
                return  # Don't continue if report fails
            
            # Validate HRIs (skip in fast_mode)
            if not fast_mode:
                if progress_callback:
                    progress_callback("wa_tool_hri", "Validating high-risk issues...", {"progress_percentage": 96})
                try:
                    self._validate_workload_hris(
                        workload_id, transcript, transcript_analysis, results, session_id
                    )
                except Exception as e:
                    logger.warning(f"Error validating HRIs: {e}")
            else:
                logger.info("Skipping HRI validation (fast_mode=True)")
                results["steps"]["hri_validation"] = {"skipped": True, "reason": "fast_mode"}
            
            print(f"[POPULATE] Completed successfully", file=sys.stderr, flush=True)
            
        except Exception as e:
            logger.error(f"Error populating workload answers: {e}", exc_info=True)
            print(f"[POPULATE] EXCEPTION: {e}", file=sys.stderr, flush=True)
            results["steps"]["wa_workload"]["populate_error"] = str(e)
            
            if progress_callback:
                progress_callback("error", f"Answer population failed: {e}", {"error": str(e), "step": "wa_tool_answers"})

    def _handle_remaining_questions(
        self,
        workload_id: str,
        updated_count: int,
        total_count: int,
        skipped_count: int,
        results: Dict,
    ) -> None:
        """Handle remaining unanswered questions."""
        user_choice = self._prompt_user_for_remaining_questions(
            updated_count=updated_count,
            total_count=total_count,
            skipped_count=skipped_count,
            workload_id=workload_id,
        )

        if user_choice == CHOICE_MANUAL:
            logger.info("Starting manual question answering...")
            manual_result = self._manual_answer_questions(
                workload_id=workload_id,
                skipped_count=skipped_count,
            )
            results["steps"]["wa_workload"]["manual_answers"] = manual_result
            logger.info(
                f"Manually answered {manual_result.get('updated', 0)} additional questions"
            )

    def _create_milestone_and_report(
        self,
        workload_id: str,
        client_name: Optional[str],
        session_id: str,
        results: Dict,
        progress_callback: Optional[Callable] = None,
    ) -> None:
        """Create milestone and generate official WAFR report with progress updates."""
        import sys
        
        logger.info("Creating milestone and generating official WAFR report...")
        print(f"[MILESTONE] Starting for workload {workload_id}", file=sys.stderr, flush=True)
        
        if progress_callback:
            progress_callback("wa_tool_report", "Generating official AWS WAFR report...", {"progress_percentage": 94})

        # Use /tmp/ for Lambda/AgentCore (only writable location)
        report_dir = "/tmp/reports"
        os.makedirs(report_dir, exist_ok=True)
        report_filename = os.path.join(report_dir, f"wafr_report_{workload_id}_{session_id[:8]}.pdf")
        milestone_name = f"WAFR Assessment - {client_name or 'Workload'}"

        try:
            # Wait for AWS to release workload lock after answer population
            # AWS WA Tool locks workloads during updates, and the lock may not be released immediately
            import time
            logger.info(f"[SESSION:{session_id}] Waiting 3 seconds for AWS to release workload lock...")
            time.sleep(3)
            
            print(f"[MILESTONE] Calling create_milestone_and_review...", file=sys.stderr, flush=True)
            
            review_result = self.wa_tool_agent.create_milestone_and_review(
                workload_id=workload_id,
                milestone_name=milestone_name,
                save_report_path=report_filename,
            )
            
            print(f"[MILESTONE] Got review_result: {type(review_result)}", file=sys.stderr, flush=True)

            # Validate that report was actually generated
            report_base64 = review_result.get("report_base64") if isinstance(review_result, dict) else None
            if not report_base64:
                error_msg = "AWS report generation failed: No report_base64 in review_result"
                logger.error(error_msg)
                print(f"[MILESTONE] ERROR: {error_msg}", file=sys.stderr, flush=True)
                raise RuntimeError(error_msg)
            
            # Verify report file exists and is not empty
            if not os.path.exists(report_filename):
                error_msg = f"WA Tool report file not found: {report_filename}"
                logger.error(error_msg)
                print(f"[MILESTONE] ERROR: {error_msg}", file=sys.stderr, flush=True)
                raise FileNotFoundError(error_msg)
            
            file_size = os.path.getsize(report_filename)
            if file_size == 0:
                error_msg = f"WA Tool report file is empty: {report_filename}"
                logger.error(error_msg)
                print(f"[MILESTONE] ERROR: {error_msg}", file=sys.stderr, flush=True)
                raise RuntimeError(error_msg)
            
            results["steps"]["wa_workload"]["review"] = review_result
            results["steps"]["wa_workload"]["report_file"] = report_filename
            results["steps"]["wa_workload"]["report_status"] = "generated"
            results["steps"]["wa_workload"]["report_size_bytes"] = file_size
            
            print(f"[MILESTONE] Report generated: {report_filename} ({file_size} bytes)", file=sys.stderr, flush=True)
            logger.info(f"Official WAFR report generated: {report_filename} ({file_size} bytes)")
            
            # Sub-step: Upload to S3
            if progress_callback:
                progress_callback("wa_tool_upload", "Uploading report to S3...", {"progress_percentage": 97})
            
            print(f"[MILESTONE] Uploading to S3...", file=sys.stderr, flush=True)
            
            from wafr.utils.s3_storage import get_s3_storage
            s3_storage = get_s3_storage()
            
            s3_key = s3_storage.upload_wa_tool_report(
                file_path=report_filename,
                session_id=session_id,
                workload_id=workload_id,
                milestone_number=review_result.get("milestone_number") if isinstance(review_result, dict) else None
            )
            
            if not s3_key:
                error_msg = "Failed to upload WA Tool report to S3"
                logger.error(error_msg)
                print(f"[MILESTONE] S3 upload FAILED", file=sys.stderr, flush=True)
                raise RuntimeError(error_msg)
            
            results["steps"]["wa_workload"]["s3_key"] = s3_key
            results["steps"]["wa_workload"]["s3_bucket"] = s3_storage.bucket_name
            
            print(f"[MILESTONE] Uploaded to S3: {s3_key}", file=sys.stderr, flush=True)
            logger.info(f"WA Tool report uploaded to S3: s3://{s3_storage.bucket_name}/{s3_key}")
            
            # Generate presigned URL
            try:
                download_url = s3_storage.get_report_url(s3_key, expires_in=86400)
                if download_url:
                    results["steps"]["wa_workload"]["download_url"] = download_url
                    results["steps"]["wa_workload"]["download_url_expires_in"] = 86400
                    print(f"[MILESTONE] Presigned URL generated", file=sys.stderr, flush=True)
                    logger.info("Generated presigned download URL (expires in 24h)")
            except Exception as url_error:
                logger.warning(f"Failed to generate presigned URL: {url_error}")
                print(f"[MILESTONE] Presigned URL failed: {url_error}", file=sys.stderr, flush=True)
            
        except Exception as e:
            logger.error(f"Failed to create milestone and report: {e}", exc_info=True)
            print(f"[MILESTONE] EXCEPTION: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            
            import traceback
            traceback.print_exc()
            
            results["steps"]["wa_workload"]["review"] = {"error": str(e)}
            results["steps"]["wa_workload"]["report_status"] = "failed"
            results["steps"]["wa_workload"]["report_error"] = str(e)
            
            # RE-RAISE so the caller knows it failed
            raise

    def _validate_workload_hris(
        self,
        workload_id: str,
        transcript: str,
        transcript_analysis: Dict,
        results: Dict,
        session_id: str
    ) -> None:
        """
        Validate High-Risk Issues using Claude to identify only tangible, actionable HRIs.
        
        Args:
            workload_id: Workload ID
            transcript: Original transcript
            transcript_analysis: Transcript analysis results
            results: Results dict to store validation results
            session_id: Session ID
        """
        try:
            self.logger.info("Validating High-Risk Issues using Claude...")
            
            # Get potential HRIs from WA Tool (after milestone creation)
            # Get milestone number from review result
            review_result = results.get("steps", {}).get("wa_workload", {}).get("review", {})
            milestone_number = review_result.get("milestone_number")
            
            potential_hris = self.wa_tool_agent.get_high_risk_issues(
                workload_id,
                milestone_number=milestone_number
            )

            self.logger.info(f"Retrieved {len(potential_hris) if potential_hris else 0} potential HRIs from WA Tool for validation")

            if not potential_hris:
                self.logger.info("No High-Risk Issues found in workload")
                results["steps"]["hri_validation"] = {
                    "validated_hris": [],
                    "filtered_hris": [],
                    "total_potential": 0,
                    "total_validated": 0,
                    "total_filtered": 0
                }
                return
            
            # Get confidence results for context
            confidence_results = results.get("steps", {}).get("confidence", {})

            self.logger.info(f"Starting Claude-based HRI validation for {len(potential_hris)} potential HRIs...")

            # Validate HRIs using Claude
            validation_result = self._validate_hris_with_claude(
                potential_hris=potential_hris,
                transcript=transcript,
                transcript_analysis=transcript_analysis,
                confidence_results=confidence_results
            )
            
            # Store validation results
            results["steps"]["hri_validation"] = validation_result
            
            validated_count = validation_result.get("total_validated", 0)
            filtered_count = validation_result.get("total_filtered", 0)
            total_potential = validation_result.get("total_potential", 0)
            
            self.logger.info(
                f"HRI Validation complete: {validated_count} tangible HRIs validated, "
                f"{filtered_count} filtered out (false positives/non-tangible)"
            )
            
            if filtered_count > 0:
                self.logger.info(
                    f"  Filtered {filtered_count}/{total_potential} HRIs as non-tangible "
                    f"({filtered_count/total_potential*100:.0f}% reduction)"
                )
            
        except Exception as e:
            self.logger.error(f"Error validating HRIs: {e}", exc_info=True)
            # Don't fail the pipeline if HRI validation fails
            results["steps"]["hri_validation"] = {
                "error": str(e),
                "validated_hris": [],
                "filtered_hris": []
            }
    
    def _validate_hris_with_claude(
        self,
        potential_hris: List[Dict],
        transcript: str,
        transcript_analysis: Dict,
        confidence_results: Dict
    ) -> Dict[str, Any]:
        """
        Validate High-Risk Issues using Claude to identify only tangible, actionable HRIs.
        
        Args:
            potential_hris: List of potential HRIs from WA Tool
            transcript: Original transcript text
            transcript_analysis: Transcript analysis results
            confidence_results: Confidence validation results
            
        Returns:
            Dict with validated_hris, filtered_hris, and counts
        """
        import json
        import re
        import boto3
        from wafr.agents.config import BEDROCK_REGION, DEFAULT_MODEL_ID
        
        try:
            # Prepare HRI data for validation
            hri_data = []
            for hri in potential_hris:
                hri_data.append({
                    "question_id": hri.get("question_id", ""),
                    "question_title": hri.get("question_title", ""),
                    "question_description": hri.get("question_description", ""),
                    "selected_choices": hri.get("selected_choices", []),
                    "answer_notes": hri.get("notes", ""),
                    "risk_level": hri.get("risk", "HIGH"),
                    "pillar": hri.get("pillar", "UNKNOWN")
                })

            self.logger.info(f"Prepared {len(hri_data)} HRIs for Claude validation")

            # Get relevant insights and mappings
            insights = transcript_analysis.get("insights", [])
            mappings = transcript_analysis.get("mappings", [])
            
            # Build context
            insights_text = "\n".join([
                f"- {insight.get('content', '')[:200]}"
                for insight in insights[:20]
            ])
            
            mappings_text = "\n".join([
                f"- Q: {m.get('question_id', '')} - {m.get('answer_content', '')[:200]}"
                for m in mappings[:20]
            ])
            
            # Create validation prompt
            prompt = f"""You are an AWS Well-Architected Framework expert validating High-Risk Issues (HRIs).

CRITICAL: Only identify TANGIBLE, ACTIONABLE HRIs that represent real, significant risks.

TANGIBLE HRI CRITERIA:
1. REAL RISK: Represents an actual, significant risk to the workload (not theoretical or minor)
2. EVIDENCE-BASED: Has clear evidence in transcript that supports the risk
3. ACTIONABLE: Can be addressed with specific, concrete actions
4. IMPACT: Would have meaningful negative impact if not addressed
5. NOT FALSE POSITIVE: Not a misunderstanding, missing context, or overly cautious assessment

NON-TANGIBLE HRIs TO FILTER OUT:
- Missing information where transcript doesn't provide enough context (not a real risk)
- Theoretical risks without evidence in transcript
- Minor gaps that don't represent significant risks
- Issues that are already addressed but not explicitly stated
- Overly cautious assessments without real evidence
- Questions where transcript is neutral/unclear (not a risk, just lack of information)

TRANSCRIPT CONTEXT:
{transcript[:6000]}

RELEVANT INSIGHTS:
{insights_text}

RELEVANT MAPPINGS:
{mappings_text}

POTENTIAL HRIs TO VALIDATE:
{json.dumps(hri_data, indent=2)}

TASK: For each potential HRI, determine if it is a TANGIBLE, ACTIONABLE HRI.

For EACH HRI, evaluate:
1. Is there EVIDENCE in transcript that supports this as a real risk?
2. Is this a SIGNIFICANT risk (not minor or theoretical)?
3. Is this ACTIONABLE (can be addressed with specific actions)?
4. Is this a FALSE POSITIVE (misunderstanding, missing context, overly cautious)?

Return ONLY a JSON array with validation results:
[
  {{
    "question_id": "question_id_1",
    "is_tangible_hri": true/false,
    "justification": "Clear explanation of why this is or is not a tangible HRI. If tangible, explain the real risk and evidence. If not, explain why it's a false positive.",
    "risk_severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "NOT_TANGIBLE",
    "evidence_in_transcript": "Specific quotes or references from transcript that support or refute this HRI",
    "actionable": true/false,
    "recommended_actions": ["action 1", "action 2"] if tangible, [] if not
  }}
]

STRICT RULES:
- Only mark as tangible if there is CLEAR EVIDENCE in transcript
- Filter out false positives aggressively
- Be conservative - better to filter out a borderline case than report a false positive
- Only report HRIs that represent REAL, SIGNIFICANT risks
- If transcript doesn't provide enough context, it's NOT a tangible HRI (it's just missing information)

Return ONLY the JSON array, no other text."""

            # Use bedrock runtime
            bedrock_runtime = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION)
            model_id = DEFAULT_MODEL_ID

            self.logger.info(f"Invoking Bedrock model {model_id} for HRI validation...")

            response = bedrock_runtime.invoke_model(
                modelId=model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4000,
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

            # Log token usage if available
            usage = response_body.get('usage', {})
            if usage:
                self.logger.info(
                    f"HRI validation model response - input_tokens: {usage.get('input_tokens', 'N/A')}, "
                    f"output_tokens: {usage.get('output_tokens', 'N/A')}"
                )

            content = response_body.get('content', [])
            if content:
                text = content[0].get('text', '')
                validations = self._parse_hri_validation_response(text)

                self.logger.info(f"Parsed {len(validations)} HRI validation results from Claude response")

                # Separate validated and filtered HRIs
                validated_hris = []
                filtered_hris = []
                
                for validation in validations:
                    question_id = validation.get("question_id")
                    is_tangible = validation.get("is_tangible_hri", False)
                    
                    # Find original HRI
                    original_hri = next(
                        (hri for hri in potential_hris if hri.get("question_id") == question_id),
                        None
                    )
                    
                    if original_hri:
                        # Add validation metadata
                        validated_hri = {
                            **original_hri,
                            "hri_validation": {
                                "is_tangible": is_tangible,
                                "justification": validation.get("justification", ""),
                                "risk_severity": validation.get("risk_severity", "UNKNOWN"),
                                "evidence_in_transcript": validation.get("evidence_in_transcript", ""),
                                "actionable": validation.get("actionable", False),
                                "recommended_actions": validation.get("recommended_actions", [])
                            }
                        }
                        
                        if is_tangible:
                            validated_hris.append(validated_hri)
                            self.logger.debug(
                                f"HRI {question_id} validated as TANGIBLE - "
                                f"severity: {validation.get('risk_severity', 'UNKNOWN')}"
                            )
                        else:
                            filtered_hris.append(validated_hri)
                            self.logger.debug(
                                f"HRI {question_id} FILTERED as non-tangible - "
                                f"reason: {validation.get('justification', 'N/A')[:100]}"
                            )
                
                self.logger.info(
                    f"HRI validation processing complete - "
                    f"tangible: {len(validated_hris)}, filtered: {len(filtered_hris)}, "
                    f"total processed: {len(potential_hris)}"
                )

                return {
                    "validated_hris": validated_hris,
                    "filtered_hris": filtered_hris,
                    "total_potential": len(potential_hris),
                    "total_validated": len(validated_hris),
                    "total_filtered": len(filtered_hris)
                }

            # Fallback: if validation fails, return all as potential (conservative)
            self.logger.warning("HRI validation failed, returning all potential HRIs")
            return {
                "validated_hris": potential_hris,
                "filtered_hris": [],
                "total_potential": len(potential_hris),
                "total_validated": len(potential_hris),
                "total_filtered": 0
            }
            
        except Exception as e:
            self.logger.error(f"Error in HRI validation: {str(e)}", exc_info=True)
            # Fallback: return all as potential (conservative)
            return {
                "validated_hris": potential_hris,
                "filtered_hris": [],
                "total_potential": len(potential_hris),
                "total_validated": len(potential_hris),
                "total_filtered": 0
            }
    
    def _parse_hri_validation_response(self, text: str) -> List[Dict]:
        """Parse Claude's HRI validation response with robust error handling."""
        import json
        import re
        
        if not text:
            return []
        
        # Strategy 1: Try to find JSON array with regex
        try:
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                # Fix common JSON issues
                json_str = self._fix_json_string(json_str)
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.debug(f"Strategy 1 failed: {e}")
        
        # Strategy 2: Try direct JSON parse
        try:
            fixed_text = self._fix_json_string(text)
            return json.loads(fixed_text)
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.debug(f"Strategy 2 failed: {e}")
        
        # Strategy 3: Extract from markdown code blocks
        try:
            cleaned = re.sub(r'```json\s*', '', text)
            cleaned = re.sub(r'```\s*', '', cleaned)
            cleaned = self._fix_json_string(cleaned)
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.debug(f"Strategy 3 failed: {e}")
        
        # Strategy 4: Try to extract partial valid JSON
        try:
            # Find the last complete object before the error
            json_match = re.search(r'\[.*?\{.*?\}.*?\]', text, re.DOTALL)
            if json_match:
                partial = json_match.group()
                # Try to close any unclosed strings or objects
                partial = self._fix_json_string(partial)
                # Try to parse what we have
                return json.loads(partial)
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.debug(f"Strategy 4 failed: {e}")
        
        self.logger.warning("Failed to parse HRI validation response as JSON")
        self.logger.error(f"Could not parse HRI validation response after all strategies")
        return []
    
    def _fix_json_string(self, json_str: str) -> str:
        """Fix common JSON string issues."""
        import re
        
        # Remove any trailing commas before closing brackets
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*\]', ']', json_str)
        
        # Try to close unterminated strings by finding unmatched quotes
        # This is a simple heuristic - count quotes and add closing quote if odd
        quote_count = json_str.count('"') - json_str.count('\\"')
        if quote_count % 2 != 0:
            # Find the last quote position
            last_quote_pos = json_str.rfind('"')
            # Check if it's likely an unterminated string (not followed by : or ,)
            if last_quote_pos > 0:
                after_quote = json_str[last_quote_pos+1:].strip()
                if after_quote and after_quote[0] not in [':', ',', '}', ']']:
                    # Try to close the string at a reasonable point
                    # Look for newline or end of meaningful content
                    close_pos = json_str.find('\n', last_quote_pos)
                    if close_pos == -1:
                        close_pos = len(json_str)
                    # Insert closing quote
                    json_str = json_str[:close_pos] + '"' + json_str[close_pos:]
        
        # Try to close unclosed objects/arrays
        open_braces = json_str.count('{') - json_str.count('}')
        open_brackets = json_str.count('[') - json_str.count(']')
        
        if open_braces > 0:
            json_str += '}' * open_braces
        if open_brackets > 0:
            json_str += ']' * open_brackets
        
        return json_str

    # -------------------------------------------------------------------------
    # Helper Methods - Answer Validation
    # -------------------------------------------------------------------------

    def _extract_validated_answers(
        self,
        mappings: List[Dict],
        confidence_result: Dict,
    ) -> List[Dict]:
        """Extract validated answers from mappings and confidence results."""
        validation_map = self._build_validation_map(confidence_result)

        answers = []
        for mapping in mappings:
            question_id = mapping.get("question_id")
            validation = validation_map.get(question_id, {})

            if self._should_accept_answer(validation):
                answer = self._build_validated_answer(mapping, validation)
                answers.append(answer)

        return answers

    def _build_validation_map(self, confidence_result: Dict) -> Dict[str, Dict]:
        """Build a map of question_id to validation data."""
        validations = confidence_result.get("all_validations", [])
        approved = confidence_result.get("approved_answers", [])
        review_needed = confidence_result.get("review_needed", [])

        validation_map = {
            v.get("question_id"): v
            for v in validations
            if v.get("question_id")
        }

        # Include approved and review_needed answers
        for answer in approved + review_needed:
            question_id = answer.get("question_id")
            if question_id and question_id not in validation_map:
                validation_map[question_id] = answer

        return validation_map

    def _should_accept_answer(self, validation: Dict) -> bool:
        """Determine if an answer should be accepted based on validation."""
        evidence_verified = validation.get("evidence_verified", False)
        confidence_score = validation.get("confidence_score", 0)
        confidence_level = validation.get("confidence_level", CONFIDENCE_LOW)
        validation_passed = validation.get("validation_passed", False)

        # Accept if:
        # 1. Evidence verified AND confidence >= threshold
        # 2. OR validation explicitly passed
        # 3. OR high/medium confidence with verified evidence
        return (
            (evidence_verified and confidence_score >= MIN_CONFIDENCE_THRESHOLD)
            or validation_passed
            or (confidence_level in [CONFIDENCE_HIGH, CONFIDENCE_MEDIUM] and evidence_verified)
        )

    def _build_validated_answer(self, mapping: Dict, validation: Dict) -> Dict:
        """Build a validated answer dictionary."""
        return {
            "question_id": mapping.get("question_id"),
            "question_text": mapping.get("question_text", ""),
            "pillar": mapping.get("pillar", "UNKNOWN"),
            "answer_content": mapping.get("answer_content", ""),
            "evidence_quotes": [mapping.get("evidence_quote", "")],
            "source": "transcript_direct",
            "confidence_score": validation.get("confidence_score", 0),
            "confidence_level": validation.get("confidence_level", CONFIDENCE_LOW),
            "evidence_verified": validation.get("evidence_verified", False),
            "validation_passed": validation.get("validation_passed", False),
        }

    # -------------------------------------------------------------------------
    # Helper Methods - User Interaction
    # -------------------------------------------------------------------------

    def _prompt_user_for_remaining_questions(
        self,
        updated_count: int,
        total_count: int,
        skipped_count: int,
        workload_id: str,
    ) -> str:
        """
        Handle remaining questions - auto-proceeds with current answers.

        Returns:
            'proceed' (always defaults to proceeding with current answers).
        """
        coverage_pct = (updated_count / total_count * 100) if total_count else 0

        # Log summary info
        self.logger.info(
            f"Question auto-fill summary - auto-filled: {updated_count}, "
            f"skipped: {skipped_count}, total: {total_count}, coverage: {coverage_pct:.1f}%"
        )
        self.logger.info("Auto-proceeding with current answers (default behavior)")

        return CHOICE_PROCEED

    def _print_question_summary(
        self,
        updated_count: int,
        skipped_count: int,
        total_count: int,
        coverage_pct: float,
    ) -> None:
        """
        Print the question auto-fill summary.
        
        Note: This method uses print() statements for interactive CLI output.
        This is intentional for user-facing console interactions.
        """
        print("\n" + "=" * 70)
        print("  QUESTION AUTO-FILL SUMMARY")
        print("=" * 70)
        print(f"  ✅ Auto-filled: {updated_count} questions")
        print(f"  ⏭️  Skipped: {skipped_count} questions")
        print(f"  📊 Total: {total_count} questions")
        print(f"  📈 Coverage: {coverage_pct:.1f}%")
        print("=" * 70)
        print("\n  The transcript may not contain answers to all questions.")
        print("  You have two options:\n")
        print("  1. MANUALLY ANSWER remaining questions")
        print("     → Answer the skipped questions interactively")
        print("     → Then generate the complete report")
        print("\n  2. PROCEED WITH CURRENT ANSWERS")
        print("     → Generate report with auto-filled questions only")
        print("     → Skipped questions will remain unanswered")
        print("\n" + "-" * 70)

    def _manual_answer_questions(
        self,
        workload_id: str,
        skipped_count: int,
    ) -> Dict[str, Any]:
        """
        Interactive interface for manually answering remaining questions.

        Returns:
            Dict with updated count and details.
        """
        self._print_manual_answer_header()

        while True:
            try:
                method = input(
                    "\n  Choose method (1/2 or 'console'/'skip'): "
                ).strip().lower()

                if method in ["1", "interactive", "cli"]:
                    return self._interactive_answer_questions(workload_id)
                elif method in ["2", "console", "c"]:
                    return self._handle_console_answering(workload_id)
                elif method in ["skip", "s", ""]:
                    print("  ⏭️  Skipping manual answers. Proceeding with current state...")
                    return {"updated": 0, "method": "skipped"}
                else:
                    print("  ❌ Invalid choice. Please enter 1, 2, 'console', or 'skip'")

            except (EOFError, KeyboardInterrupt):
                print("\n  ⚠️  Interrupted. Skipping manual answers...")
                return {"updated": 0, "method": "interrupted"}

    def _print_manual_answer_header(self) -> None:
        """Print the manual answering header."""
        print("\n" + "=" * 70)
        print("  MANUAL QUESTION ANSWERING")
        print("=" * 70)
        print("  You can answer questions via:")
        print("  1. Interactive CLI (answer questions one by one)")
        print("  2. AWS Console (then continue)")
        print("\n" + "-" * 70)

    def _handle_console_answering(self, workload_id: str) -> Dict[str, Any]:
        """Handle answering via AWS Console."""
        console_url = (
            f"https://console.aws.amazon.com/wellarchitected/home"
            f"?#/workloads/{workload_id}"
        )
        print(f"\n  📋 Please answer questions in AWS Console:")
        print(f"     {console_url}")
        input("\n  Press Enter when you've finished answering questions in the console...")
        return {
            "updated": 0,
            "method": CHOICE_CONSOLE,
            "note": "User answered via AWS Console",
        }

    def _interactive_answer_questions(self, workload_id: str) -> Dict[str, Any]:
        """
        Interactive CLI to answer questions one by one.

        Returns:
            Dict with updated count.
        """
        print("\n" + "=" * 70)
        print("  INTERACTIVE QUESTION ANSWERING")
        print("=" * 70)
        print("  Answer questions one by one. Type 'skip' to skip a question.")
        print("  Type 'done' when finished.\n")

        try:
            unanswered_questions = self._get_unanswered_questions(workload_id)

            if not unanswered_questions:
                print("  ✅ All questions are already answered!")
                return {
                    "updated": 0,
                    "method": "interactive",
                    "note": "All questions already answered",
                }

            print(f"  Found {len(unanswered_questions)} unanswered questions.\n")
            return self._process_unanswered_questions(workload_id, unanswered_questions)

        except Exception as e:
            logger.error(f"Error in interactive answering: {e}")
            return {"updated": 0, "method": "interactive", "error": str(e)}

    def _get_unanswered_questions(self, workload_id: str) -> List[Dict]:
        """Get list of unanswered questions for a workload."""
        all_questions = self.wa_tool_agent._get_all_questions(
            workload_id=workload_id,
            lens_alias=DEFAULT_LENS_ALIAS,
        )

        answered_question_ids = set()

        for question_summary in all_questions:
            question_id = question_summary.get("QuestionId")
            if not question_id:
                continue

            try:
                answer_details = self.wa_tool_agent.wa_client.get_answer(
                    workload_id=workload_id,
                    lens_alias=DEFAULT_LENS_ALIAS,
                    question_id=question_id,
                )
                selected_choices = answer_details.get("Answer", {}).get("SelectedChoices", [])
                if selected_choices:
                    answered_question_ids.add(question_id)
            except (KeyError, AttributeError, TypeError) as e:
                # Silently skip invalid question data structure
                self.logger.debug(f"Could not parse question answer: {e}")

        return [
            q for q in all_questions
            if q.get("QuestionId") not in answered_question_ids
        ]

    def _process_unanswered_questions(
        self,
        workload_id: str,
        unanswered_questions: List[Dict],
    ) -> Dict[str, Any]:
        """Process unanswered questions interactively."""
        updated_count = 0
        total_questions = len(unanswered_questions)

        for idx, question_summary in enumerate(unanswered_questions, 1):
            result = self._process_single_question(
                workload_id, question_summary, idx, total_questions, updated_count
            )

            if result == "done":
                break
            elif result == "updated":
                updated_count += 1
            elif result == "interrupted":
                return {
                    "updated": updated_count,
                    "method": "interactive",
                    "interrupted": True,
                }

        print(f"\n  ✅ Finished answering questions. Updated {updated_count} questions.")
        return {"updated": updated_count, "method": "interactive"}

    def _process_single_question(
        self,
        workload_id: str,
        question_summary: Dict,
        idx: int,
        total: int,
        current_count: int,
    ) -> str:
        """
        Process a single question interactively.

        Returns:
            'updated', 'skipped', 'done', or 'interrupted'.
        """
        question_id = question_summary.get("QuestionId")
        question_title = question_summary.get("QuestionTitle", "")
        pillar_name = question_summary.get("PillarName", "Unknown")

        print(f"\n  [{idx}/{total}] {pillar_name}")
        print(f"  Question: {question_title}")
        print(f"  ID: {question_id}")
        print("-" * 70)

        try:
            answer_details = self.wa_tool_agent.wa_client.get_answer(
                workload_id=workload_id,
                lens_alias=DEFAULT_LENS_ALIAS,
                question_id=question_id,
            )
            choices = answer_details.get("Answer", {}).get("Choices", [])

            self._print_choices(choices)

            return self._get_user_answer_choice(
                workload_id, question_id, choices, current_count
            )

        except Exception as e:
            logger.warning(f"Error getting question details for {question_id}: {e}")
            return "skipped"

    def _print_choices(self, choices: List[Dict]) -> None:
        """Print available choices for a question."""
        print("\n  Available Choices:")
        for i, choice in enumerate(choices, 1):
            choice_id = choice.get("ChoiceId", "")
            title = choice.get("Title", "")
            desc = choice.get("Description", "")
            print(f"    {i}. [{choice_id}] {title}")
            if desc:
                print(f"       {desc[:80]}...")

    def _get_user_answer_choice(
        self,
        workload_id: str,
        question_id: str,
        choices: List[Dict],
        current_count: int,
    ) -> str:
        """Get user's answer choice and update the workload."""
        while True:
            try:
                user_input = input(
                    "\n  Enter choice number(s) (comma-separated) or 'skip': "
                ).strip()

                if user_input.lower() in ["skip", "s", ""]:
                    print("  ⏭️  Skipped")
                    return "skipped"

                if user_input.lower() == "done":
                    print(f"\n  ✅ Finished. Updated {current_count} questions.")
                    return "done"

                choice_numbers = self._parse_choice_numbers(user_input)

                if not choice_numbers:
                    print("  ❌ Invalid input. Please enter choice number(s) or 'skip'")
                    continue

                if not self._validate_choice_numbers(choice_numbers, len(choices)):
                    print(f"  ❌ Invalid choice number(s). Please enter 1-{len(choices)}")
                    continue

                selected_choice_ids = [
                    choices[n - 1].get("ChoiceId")
                    for n in choice_numbers
                ]

                notes = input("  Enter notes (optional, press Enter to skip): ").strip()

                self.wa_tool_agent.wa_client.update_answer(
                    workload_id=workload_id,
                    lens_alias=DEFAULT_LENS_ALIAS,
                    question_id=question_id,
                    selected_choices=selected_choice_ids,
                    notes=notes or "",
                    is_applicable=True,
                )

                print(f"  ✅ Updated answer for {question_id}")
                return "updated"

            except (EOFError, KeyboardInterrupt):
                print(f"\n  ⚠️  Interrupted. Updated {current_count} questions so far.")
                return "interrupted"
            except ValueError:
                print("  ❌ Invalid input. Please enter numbers or 'skip'")
            except Exception as e:
                print(f"  ❌ Error updating answer: {e}")

    def _parse_choice_numbers(self, user_input: str) -> List[int]:
        """Parse comma-separated choice numbers from user input."""
        return [
            int(x.strip())
            for x in user_input.split(",")
            if x.strip().isdigit()
        ]

    def _validate_choice_numbers(
        self,
        choice_numbers: List[int],
        num_choices: int,
    ) -> bool:
        """Validate that all choice numbers are within valid range."""
        return all(1 <= n <= num_choices for n in choice_numbers)

    # -------------------------------------------------------------------------
    # Helper Methods - Utilities
    # -------------------------------------------------------------------------

    def _create_initial_results(self, session_id: str) -> Dict[str, Any]:
        """Create initial results dictionary."""
        return {
            "session_id": session_id,
            "status": STATUS_PROCESSING,
            "steps": {},
            "processing_time": {},
            "errors": [],
            "pdf_processing": {},
        }

    def _finalize_results(
        self,
        results: Dict,
        insights: List,
        mappings: List,
        validated_answers: List,
        gap_result: Dict,
        start_time: float,
    ) -> None:
        """Finalize results with status and summary."""
        if results.get("errors"):
            results["status"] = STATUS_COMPLETED_WITH_ERRORS
            self.logger.warning(f"Processing completed with {len(results['errors'])} errors")
        else:
            results["status"] = STATUS_COMPLETED

        results["processing_time"]["total"] = round(time.time() - start_time, 2)

        # Build summary with safe defaults
        confidence_summary = results["steps"].get("confidence", {}).get("summary", {})
        gaps = gap_result.get("gaps", []) if isinstance(gap_result, dict) else []

        results["summary"] = {
            "total_insights": len(insights) if insights else 0,
            "total_mappings": len(mappings) if mappings else 0,
            "total_answers": len(validated_answers) if validated_answers else 0,
            "total_gaps": len(gaps),
            "confidence_score": confidence_summary.get("average_score", 0) if confidence_summary else 0,
        }

    def _normalize_pillar_coverage(self, pillar_coverage: Dict) -> Dict[str, float]:
        """Normalize pillar coverage to simple float percentages."""
        return {
            k: v.get("coverage_pct", 0) if isinstance(v, dict) else 0
            for k, v in pillar_coverage.items()
        }

    def _generate_session_id(self, prefix: str) -> str:
        """Generate a unique session ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        return f"{prefix}-{timestamp}-{unique_id}"

    def _auto_detect_lenses(self, content: str) -> None:
        """
        Auto-detect relevant lenses from content including GenAI lens.
        
        This method analyzes the transcript/content to identify if specialized
        lenses like GenAI, Serverless, Machine Learning, etc. should be added
        to the workload in addition to the standard Well-Architected Framework.
        """
        if self.lens_context or not content:
            return

        try:
            from wafr.agents.lens_manager import create_lens_manager

            aws_region = getattr(self, "aws_region", DEFAULT_AWS_REGION)
            lens_manager = create_lens_manager(aws_region=aws_region)

            self.logger.info("Analyzing transcript to detect relevant specialized lenses...")
            detected = lens_manager.detect_relevant_lenses(
                content,
                min_confidence=MIN_LENS_DETECTION_CONFIDENCE,
            )

            if detected:
                self.logger.info(
                    f"Auto-detected {len(detected)} relevant lenses from transcript"
                )
                # Log each detected lens with confidence
                for lens in detected:
                    lens_alias = lens.get("lens_alias", "unknown")
                    confidence = lens.get("confidence", 0)
                    self.logger.info(f"  - {lens_alias}: {confidence*100:.1f}% confidence")
                    
                    # Special log for GenAI lens detection
                    if lens_alias in ["genai", "generative-ai"]:
                        self.logger.info(f"  [GenAI Lens Detected] - Will be added to workload")
                
                selected_lenses = lens_manager.auto_select_lenses(
                    content,
                    max_lenses=MAX_AUTO_SELECT_LENSES,
                )
                self.lens_context = lens_manager.get_lens_context_for_agents(selected_lenses)
                self.logger.info(f"Auto-selected lenses for workload: {', '.join(selected_lenses)}")

        except Exception as e:
            self.logger.warning(f"Failed to auto-detect lenses: {e}")

    def _build_input_metadata(self, processed_input) -> Dict[str, Any]:
        """Build input metadata dictionary from processed input."""
        return {
            "source_type": processed_input.input_type.value,
            "source_file": processed_input.source_file,
            "word_count": processed_input.word_count,
            "extraction_confidence": processed_input.confidence,
            "processing_metadata": processed_input.metadata,
        }

    def _get_question_data(
        self,
        question_id: str,
        wafr_schema: Dict,
    ) -> Optional[Dict]:
        """Get question data from schema by question ID."""
        if not wafr_schema or "pillars" not in wafr_schema:
            return None

        for pillar in wafr_schema["pillars"]:
            for question in pillar.get("questions", []):
                if question.get("id") == question_id:
                    question["pillar_id"] = pillar.get("id", "UNKNOWN")
                    return question

        return None

    def _sanitize_dict_recursive(self, data: Any) -> Any:
        """Recursively sanitize dictionary values for Unicode safety."""
        if isinstance(data, dict):
            return {k: self._sanitize_dict_recursive(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_dict_recursive(item) for item in data]
        elif isinstance(data, str):
            return self._sanitize_string(data)
        return data

    def _sanitize_string(self, text: str) -> str:
        """Sanitize a string for Unicode safety."""
        try:
            text.encode("utf-8")
            return text
        except UnicodeEncodeError:
            return text.encode("utf-8", errors="replace").decode("utf-8")

    def _sanitize_error_message(self, error_msg: str) -> str:
        """Sanitize error message for Unicode safety."""
        try:
            error_msg.encode("utf-8")
            return error_msg
        except UnicodeEncodeError:
            return error_msg.encode("utf-8", errors="replace").decode("utf-8")


# -----------------------------------------------------------------------------
# Factory Functions
# -----------------------------------------------------------------------------


def _load_schema_from_file(schema_path: str) -> Dict[str, Any]:
    """Load schema from file with caching."""
    def load() -> Dict[str, Any]:
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading schema from {schema_path}: {e}")
            return {"pillars": []}

    cache_key = f"schema_{schema_path}"
    return cache_result(_schema_cache, cache_key, load, ttl=SCHEMA_CACHE_TTL_SECONDS)


def create_orchestrator(
    wafr_schema: Optional[Dict] = None,
    aws_region: str = DEFAULT_AWS_REGION,
    lens_context: Optional[Dict] = None,
) -> WafrOrchestrator:
    """
    Factory function to create WAFR orchestrator.

    Args:
        wafr_schema: Optional WAFR schema (loads from AWS API first, then file).
        aws_region: AWS region for services.
        lens_context: Optional lens context for multi-lens support.

    Returns:
        Configured WafrOrchestrator instance.
    """
    if wafr_schema is None:
        from wafr.agents.wafr_context import load_wafr_schema, get_schema_source

        wafr_schema = load_wafr_schema(use_aws_api=True)
        source = get_schema_source()

        if source == "aws_api":
            logger.info("Using official AWS Well-Architected Framework schema from AWS API")
        elif source == "file":
            logger.info("Using WAFR schema from file (AWS API not available)")
        else:
            logger.warning("WAFR schema not found, using empty schema")
            wafr_schema = {"pillars": []}

    return WafrOrchestrator(
        wafr_schema,
        lens_context=lens_context,
    )