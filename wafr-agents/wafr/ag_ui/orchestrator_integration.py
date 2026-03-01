"""
AG-UI Integration for WAFR Orchestrator

This module provides AG-UI event emission integration for the WAFR orchestrator,
adding real-time event streaming throughout the pipeline execution.

Usage:
    from ag_ui.orchestrator_integration import create_agui_orchestrator
    
    orchestrator = create_agui_orchestrator()
    emitter = orchestrator.emitter
    
    # Process with AG-UI events
    results = await orchestrator.process_transcript_with_agui(
        transcript=transcript,
        session_id=session_id,
    )
"""

from typing import Any, Dict, List, Optional, Callable
import asyncio
import logging
import uuid
import sys
from datetime import datetime

from wafr.ag_ui.emitter import WAFREventEmitter

# Configure logging to also write to console with detailed format
# Configure logging - check if we're in Lambda environment
import os
is_lambda = os.environ.get('AWS_LAMBDA_FUNCTION_NAME') is not None

if is_lambda:
    # In Lambda: only use StreamHandler (logs go to CloudWatch)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
else:
    # Local development: use both StreamHandler and FileHandler
    try:
        # Try to write to /tmp in Lambda, or current directory locally
        log_file = '/tmp/wafr_state_debug.log' if os.path.exists('/tmp') else 'wafr_state_debug.log'
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(log_file, mode='a')
            ]
        )
    except (OSError, PermissionError):
        # Fallback to StreamHandler only if file logging fails
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
from wafr.ag_ui.core import (
    WAFRTool,
    get_wafr_tool,
    WAFRMessage,
)
from wafr.ag_ui.events import (
    WAFRPipelineStep,
    SynthesisProgress,
)
from wafr.agents.routing_agui_integration import create_routing_agui_integration
from wafr.agents.autonomous_agent import create_autonomous_agent

logger = logging.getLogger(__name__)


class AGUIOrchestratorWrapper:
    """
    Wrapper for WafrOrchestrator that adds AG-UI event emission.
    
    This wrapper enhances the orchestrator with AG-UI events while
    maintaining backward compatibility with the existing orchestrator API.
    """
    
    def __init__(
        self,
        orchestrator,
        emitter: Optional[WAFREventEmitter] = None,
        thread_id: Optional[str] = None,
    ):
        """
        Initialize AG-UI orchestrator wrapper.
        
        Args:
            orchestrator: Base WafrOrchestrator instance
            emitter: Optional WAFREventEmitter (created if not provided)
            thread_id: Thread/session ID for emitter
        """
        self.orchestrator = orchestrator
        self.thread_id = thread_id or str(uuid.uuid4())
        
        if emitter is None:
            self.emitter = WAFREventEmitter(thread_id=self.thread_id)
        else:
            self.emitter = emitter
        
        # Create routing integration
        self.routing_integration = create_routing_agui_integration(
            emitter=self.emitter,
        )
        
        logger.info(f"AG-UI orchestrator wrapper initialized: thread={self.thread_id}")
    
    async def process_transcript_with_agui(
        self,
        transcript: str,
        session_id: str,
        generate_report: bool = True,
        client_name: Optional[str] = None,
        environment: str = "PRODUCTION",
        existing_workload_id: Optional[str] = None,
        progress_callback: Optional[Callable[[str, str, Optional[Dict]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Process transcript with full AG-UI event streaming.
        
        This is an async wrapper around the sync orchestrator.process_transcript,
        adding AG-UI events throughout the pipeline.
        """
        # Start run
        await self.emitter.run_started()
        await self.emitter.state_snapshot()
        
        try:
            # Create enhanced progress callback that also emits AG-UI events
            async def agui_progress_callback(step: str, message: str, data: Optional[Dict] = None):
                """Progress callback that emits AG-UI events."""
                # Check if this is a heartbeat event (keep-alive during long operations)
                # Filter it out BEFORE calling outer progress_callback to prevent SSE emission
                if data and data.get("heartbeat"):
                    # Heartbeat events are silent - don't emit any events
                    # The emitter's stream_events method handles SSE keep-alive separately
                    return
                
                if progress_callback:
                    progress_callback(step, message, data)
                
                # Emit step events
                step_name = step.lower().replace(" ", "_")
                await self.emitter.step_started(step_name, metadata=data or {})
                
                # Emit text message for progress
                msg_id = f"msg-{step_name}-{uuid.uuid4().hex[:8]}"
                await self.emitter.text_message_start(msg_id, role="assistant")
                await self.emitter.text_message_content(msg_id, f"[{step}] {message}")
                await self.emitter.text_message_end(msg_id)
            
            # Run orchestrator in executor to avoid blocking
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.orchestrator.process_transcript(
                    transcript=transcript,
                    session_id=session_id,
                    generate_report=generate_report,
                    client_name=client_name,
                    environment=environment,
                    existing_workload_id=existing_workload_id,
                    # Orchestrator sometimes calls progress_callback(step, message)
                    # and sometimes progress_callback(step, message, data). Accept both.
                    progress_callback=lambda s, m, d=None: asyncio.run_coroutine_threadsafe(
                        agui_progress_callback(s, m, d), loop
                    ).result(),
                )
            )
            
            # Update state with results BEFORE emitting final snapshot
            # ALWAYS update transcript info first
            self.emitter.state.content.transcript_loaded = True
            self.emitter.state.content.transcript_length = len(transcript)
            print(f"[DEBUG] Transcript info updated: loaded=True, length={len(transcript)}")
            logger.info(f"Transcript info updated: loaded=True, length={len(transcript)}")
            
            try:
                if results and isinstance(results, dict):
                    status = results.get("status", "")
                    steps = results.get("steps", {})
                    
                    print(f"[DEBUG] Updating state: status={status}, steps={list(steps.keys()) if steps else 'empty'}")
                    logger.info(f"Updating state: status={status}, steps={list(steps.keys()) if steps else 'empty'}")
                    
                    print(f"[DEBUG] Results type: {type(results)}, has 'steps': {'steps' in results}, steps type: {type(steps)}")
                    if steps:
                        print(f"[DEBUG] Steps keys: {list(steps.keys())}")
                        for step_key, step_value in list(steps.items())[:3]:  # Show first 3 steps
                            print(f"[DEBUG] Step '{step_key}': type={type(step_value)}, is_dict={isinstance(step_value, dict)}")
                    
                    # Update insights count
                    if "understanding" in steps:
                        understanding_result = steps["understanding"]
                        if isinstance(understanding_result, dict):
                            insights = understanding_result.get("insights", [])
                            if insights:
                                self.emitter.state.set_insights_count(len(insights))
                                logger.info(f"Updated insights_count: {len(insights)}")
                            else:
                                logger.warning("Understanding step has no insights")
                    else:
                        logger.warning("No 'understanding' step in results")
                    
                    # Update mappings/questions answered
                    if "mapping" in steps:
                        mapping_result = steps["mapping"]
                        if isinstance(mapping_result, dict):
                            mappings = mapping_result.get("mappings", [])
                            if mappings:
                                self.emitter.state.content.questions_answered = len(mappings)
                                logger.info(f"Updated questions_answered: {len(mappings)}")
                                # Update total questions from pillar coverage if available
                                pillar_coverage = mapping_result.get("pillar_coverage", {})
                                if pillar_coverage:
                                    total_questions = sum(
                                        v.get("total_questions", 0) if isinstance(v, dict) else 0
                                        for v in pillar_coverage.values()
                                    )
                                    if total_questions > 0:
                                        self.emitter.state.content.questions_total = total_questions
                                        logger.info(f"Updated questions_total: {total_questions}")
                            else:
                                logger.warning("Mapping step has no mappings")
                    else:
                        logger.warning("No 'mapping' step in results")
                    
                    # Update gaps count
                    if "gap_detection" in steps:
                        gap_result = steps["gap_detection"]
                        if isinstance(gap_result, dict):
                            gaps = gap_result.get("gaps", [])
                            if gaps:
                                self.emitter.state.content.gaps_count = len(gaps)
                                logger.info(f"Updated gaps_count: {len(gaps)}")
                    
                    # Update synthesized answers count
                    if "answer_synthesis" in steps:
                        synthesis_result = steps["answer_synthesis"]
                        if isinstance(synthesis_result, dict):
                            synthesized = synthesis_result.get("synthesized_answers", [])
                            if synthesized:
                                self.emitter.state.content.synthesized_count = len(synthesized)
                                logger.info(f"Updated synthesized_count: {len(synthesized)}")
                    
                    # Update scores
                    if "scoring" in steps:
                        scoring_result = steps["scoring"]
                        if isinstance(scoring_result, dict):
                            scores = scoring_result.get("scores", {})
                            if isinstance(scores, dict):
                                overall = scores.get("overall_score", 0.0)
                                auth = scores.get("authenticity_score", 0.0)
                                self.emitter.state.scores.overall_score = overall
                                self.emitter.state.scores.authenticity_score = auth
                                logger.info(f"Updated scores: overall={overall}, authenticity={auth}")
                                pillar_scores = scores.get("pillar_scores", {})
                                if pillar_scores:
                                    self.emitter.state.scores.pillar_scores = pillar_scores
                            else:
                                logger.warning(f"Scoring step scores is not a dict: {type(scores)}")
                    else:
                        logger.warning("No 'scoring' step in results")
                    
                    # Update pipeline progress
                    if status in ("completed", "completed_with_errors"):
                        self.emitter.state.pipeline.current_step = ""
                        self.emitter.state.pipeline.completed_steps = list(steps.keys())
                        # progress_percentage is computed automatically from completed_steps
                        progress = self.emitter.state.pipeline.progress_percentage
                        logger.info(f"Updated pipeline: completed_steps={list(steps.keys())}, progress={progress}%")
                    
                    logger.info(f"State update complete: {len(steps)} steps processed, status: {status}")
                    print(f"[DEBUG] State update complete: {len(steps)} steps processed")
                else:
                    print(f"[DEBUG] Results is not a dict or is None: {type(results)}, value: {results}")
                    logger.error(f"Results is not a dict or is None: {type(results)}")
            except Exception as e:
                print(f"[DEBUG] ERROR updating state: {e}")
                logger.error(f"Error updating state: {e}", exc_info=True)
                import traceback
                traceback.print_exc()
            
            # Force state update to be reflected in snapshot
            # Ensure state is synced before emitting snapshot
            print(f"[DEBUG] State before snapshot - transcript_loaded: {self.emitter.state.content.transcript_loaded}, insights: {self.emitter.state.content.insights_count}, questions: {self.emitter.state.content.questions_answered}, progress: {self.emitter.state.pipeline.progress_percentage}")
            logger.info(f"State before snapshot - transcript_loaded: {self.emitter.state.content.transcript_loaded}, insights: {self.emitter.state.content.insights_count}")
            
            # CRITICAL: Create snapshot directly from state object to ensure we get the latest data
            # Don't rely on to_snapshot() if there's any caching or reference issues
            final_snapshot = {
                "session": self.emitter.state.session.to_dict(),
                "pipeline": self.emitter.state.pipeline.to_dict(),
                "content": self.emitter.state.content.to_dict(),
                "review": self.emitter.state.review.to_dict(),
                "scores": self.emitter.state.scores.to_dict(),
                "report": self.emitter.state.report.to_dict(),
            }
            
            snapshot_content = final_snapshot.get('content', {})
            print(f"[DEBUG] Final snapshot data - transcript_loaded: {snapshot_content.get('transcript_loaded')}, insights: {snapshot_content.get('insights_count')}, questions: {snapshot_content.get('questions_answered')}, progress: {final_snapshot.get('pipeline', {}).get('progress_percentage')}")
            logger.info(f"Final snapshot data - transcript_loaded: {snapshot_content.get('transcript_loaded')}, insights: {snapshot_content.get('insights_count')}")
            
            # Update report state if report was generated
            if results and isinstance(results, dict):
                steps = results.get("steps", {})
                
                # Check for report file path
                if "report" in steps:
                    report_step = steps["report"]
                    if isinstance(report_step, dict):
                        report_path = report_step.get("file_path") or report_step.get("report_path")
                        if report_path:
                            self.emitter.state.report.generated = True
                            self.emitter.state.report.file_path = report_path
                            self.emitter.state.report.generated_at = datetime.utcnow().isoformat() + "Z"
                            logger.info(f"Updated report state: file_path={report_path}")
                
                # Check for WA Tool workload info
                if "wa_workload" in steps:
                    wa_step = steps["wa_workload"]
                    if isinstance(wa_step, dict):
                        workload_id = wa_step.get("workload_id")
                        if workload_id:
                            logger.info(f"WA Tool workload created: {workload_id}")
                            # Store WA Tool report if available
                            wa_report = wa_step.get("report_file")
                            if wa_report and not self.emitter.state.report.file_path:
                                self.emitter.state.report.generated = True
                                self.emitter.state.report.file_path = wa_report
                                self.emitter.state.report.generated_at = datetime.utcnow().isoformat() + "Z"
                                logger.info(f"Updated report state from WA Tool: file_path={wa_report}")
            
            # Emit snapshot with explicitly created data
            await self.emitter.state_snapshot(snapshot=final_snapshot)
            await self.emitter.run_finished()
            
            print(f"[DEBUG] State after snapshot - transcript_loaded: {self.emitter.state.content.transcript_loaded}, insights: {self.emitter.state.content.insights_count}")
            logger.info(f"State after snapshot - transcript_loaded: {self.emitter.state.content.transcript_loaded}, insights: {self.emitter.state.content.insights_count}")
            
            return results
            
        except Exception as e:
            logger.error(f"AG-UI orchestrator error: {e}", exc_info=True)
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"Full traceback: {error_trace}")
            
            # Emit error event
            try:
                await self.emitter.run_error(str(e), code="ORCHESTRATOR_ERROR")
            except Exception as emit_error:
                logger.error(f"Failed to emit error event: {emit_error}")
            
            # Still return partial results if available
            if 'results' in locals() and results:
                logger.warning("Returning partial results despite error")
                return results
            
            raise
    
    async def _emit_agent_tool_call(
        self,
        agent_type: str,
        tool_name: str,
        args: Dict[str, Any],
        result: Any = None,
    ):
        """
        Emit tool call events for an agent operation.
        
        Args:
            agent_type: Type of agent (understanding, mapping, etc.)
            tool_name: Name of the tool/agent
            args: Tool arguments
            result: Tool result (if available)
        """
        tool_call_id = f"tool-{agent_type}-{uuid.uuid4().hex[:8]}"
        
        # Get tool definition
        tool = get_wafr_tool(agent_type)
        if tool:
            tool_name = tool.name
        
        # Emit tool call start
        await self.emitter.tool_call_start(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        
        # Emit tool call args (streamed)
        args_json = str(args)[:500]  # Truncate for display
        await self.emitter.tool_call_args(tool_call_id, args_json)
        
        # Emit tool call result if available
        if result is not None:
            result_summary = str(result)[:1000] if result else None
            await self.emitter.tool_call_result(tool_call_id, result_summary)
        
        # Emit tool call end with result
        result_str = str(result)[:1000] if result else None
        await self.emitter.tool_call_end(tool_call_id, result_str)
    
    async def _emit_step_with_tool_calls(
        self,
        step_name: str,
        agent_type: str,
        operation: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """
        Execute a step with AG-UI tool call events.
        
        Args:
            step_name: Name of the step
            agent_type: Type of agent being used
            operation: Function to execute
            *args, **kwargs: Arguments for operation
        
        Returns:
            Result from operation
        """
        # Emit step started
        await self.emitter.step_started(step_name)
        
        # Emit tool call start
        await self._emit_agent_tool_call(
            agent_type=agent_type,
            tool_name=step_name,
            args={"step": step_name, "args_count": len(args)},
        )
        
        try:
            # Execute operation
            if asyncio.iscoroutinefunction(operation):
                result = await operation(*args, **kwargs)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: operation(*args, **kwargs))
            
            # Emit step finished
            await self.emitter.step_finished(
                step_name,
                result={"status": "success", "has_result": result is not None},
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Step {step_name} error: {e}", exc_info=True)
            await self.emitter.step_finished(
                step_name,
                result={"status": "error", "error": str(e)},
            )
            raise
    
    async def _emit_synthesis_progress(
        self,
        current: int,
        total: int,
        question_id: str = "",
        pillar: str = "",
    ):
        """Emit synthesis progress event."""
        progress = SynthesisProgress(
            current=current,
            total=total,
            question_id=question_id,
            pillar=pillar,
        )
        await self.emitter.synthesis_progress(progress)
    
    # Delegate other methods to base orchestrator
    def __getattr__(self, name):
        """Delegate attribute access to base orchestrator."""
        return getattr(self.orchestrator, name)


def create_agui_orchestrator(
    orchestrator=None,
    emitter: Optional[WAFREventEmitter] = None,
    thread_id: Optional[str] = None,
) -> AGUIOrchestratorWrapper:
    """
    Create AG-UI enabled orchestrator.
    
    Args:
        orchestrator: Base orchestrator (created if not provided)
        emitter: Optional event emitter
        thread_id: Optional thread ID
    
    Returns:
        AGUIOrchestratorWrapper instance
    """
    if orchestrator is None:
        from wafr.agents.orchestrator import create_orchestrator
        orchestrator = create_orchestrator()
    
    return AGUIOrchestratorWrapper(
        orchestrator=orchestrator,
        emitter=emitter,
        thread_id=thread_id,
    )


__all__ = [
    "AGUIOrchestratorWrapper",
    "create_agui_orchestrator",
]

