"""
Workflow Logger - Comprehensive CloudWatch logging for WAFR agentic workflow.

Provides structured logging for:
- Every pipeline step (start, progress, completion, errors)
- AWS API calls (WA Tool, S3, Bedrock)
- Agent decisions and reasoning
- Performance metrics
- Error diagnostics

Usage:
    from wafr.utils.workflow_logger import WorkflowLogger
    
    wf_logger = WorkflowLogger(session_id="abc123")
    wf_logger.step_start("understanding", {"transcript_length": 5000})
    wf_logger.step_complete("understanding", {"insights_count": 15}, duration=2.5)
"""

import json
import logging
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional
from functools import wraps

logger = logging.getLogger("wafr.workflow")


class WorkflowLogger:
    """
    Structured workflow logger for comprehensive CloudWatch visibility.
    
    All log entries include:
    - session_id: Unique session identifier
    - timestamp: ISO format timestamp
    - step_name: Current pipeline step
    - event_type: step_start, step_progress, step_complete, step_error, aws_api, agent_decision
    """
    
    def __init__(self, session_id: str, client_name: Optional[str] = None):
        """
        Initialize workflow logger.
        
        Args:
            session_id: Unique session identifier for log correlation
            client_name: Optional client name for context
        """
        self.session_id = session_id
        self.client_name = client_name or "unknown"
        self.step_timers: Dict[str, float] = {}
        self.step_counts: Dict[str, int] = {}
        
        # Log session start
        self._log("SESSION_START", {
            "client_name": self.client_name,
            "message": f"WAFR assessment session started for {self.client_name}"
        })
    
    def _log(self, event_type: str, data: Dict[str, Any], level: str = "INFO"):
        """Internal log method with structured format."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "client_name": self.client_name,
            "event_type": event_type,
            **data
        }
        
        # Format message for readability
        message = f"[{event_type}] session={self.session_id} | {data.get('message', json.dumps(data, default=str)[:200])}"
        
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, message, extra={"structured_data": log_entry})
    
    # =========================================================================
    # Pipeline Step Logging
    # =========================================================================
    
    def step_start(self, step_name: str, context: Optional[Dict] = None):
        """
        Log the start of a pipeline step.
        
        Args:
            step_name: Name of the step (e.g., 'understanding', 'mapping', 'wa_tool')
            context: Optional context data (input sizes, parameters, etc.)
        """
        self.step_timers[step_name] = time.time()
        self.step_counts[step_name] = self.step_counts.get(step_name, 0) + 1
        
        self._log("STEP_START", {
            "step_name": step_name,
            "step_attempt": self.step_counts[step_name],
            "context": context or {},
            "message": f"Starting step: {step_name}"
        })
    
    def step_progress(self, step_name: str, progress_pct: int, message: str, details: Optional[Dict] = None):
        """
        Log progress within a step.
        
        Args:
            step_name: Name of the step
            progress_pct: Progress percentage (0-100)
            message: Human-readable progress message
            details: Optional additional details
        """
        elapsed = time.time() - self.step_timers.get(step_name, time.time())
        
        self._log("STEP_PROGRESS", {
            "step_name": step_name,
            "progress_pct": progress_pct,
            "elapsed_seconds": round(elapsed, 2),
            "details": details or {},
            "message": f"{step_name}: {progress_pct}% - {message}"
        })
    
    def step_complete(self, step_name: str, results: Optional[Dict] = None, duration: Optional[float] = None):
        """
        Log successful completion of a step.
        
        Args:
            step_name: Name of the step
            results: Summary of results (counts, key outputs)
            duration: Optional explicit duration (otherwise calculated)
        """
        if duration is None:
            duration = time.time() - self.step_timers.get(step_name, time.time())
        
        # Summarize results to avoid huge log entries
        summary = self._summarize_results(results or {})
        
        self._log("STEP_COMPLETE", {
            "step_name": step_name,
            "duration_seconds": round(duration, 2),
            "results_summary": summary,
            "message": f"Completed step: {step_name} in {duration:.2f}s"
        })
    
    def step_error(self, step_name: str, error: Exception, context: Optional[Dict] = None):
        """
        Log an error during a step.
        
        Args:
            step_name: Name of the step
            error: The exception that occurred
            context: Optional context for debugging
        """
        elapsed = time.time() - self.step_timers.get(step_name, time.time())
        
        self._log("STEP_ERROR", {
            "step_name": step_name,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "error_traceback": traceback.format_exc()[-1000:],  # Last 1000 chars
            "elapsed_seconds": round(elapsed, 2),
            "context": context or {},
            "message": f"Error in {step_name}: {type(error).__name__}: {str(error)[:200]}"
        }, level="ERROR")
    
    def step_skip(self, step_name: str, reason: str):
        """Log that a step was skipped."""
        self._log("STEP_SKIP", {
            "step_name": step_name,
            "reason": reason,
            "message": f"Skipped step: {step_name} - {reason}"
        })
    
    # =========================================================================
    # AWS API Call Logging
    # =========================================================================
    
    def aws_api_start(self, service: str, operation: str, params: Optional[Dict] = None):
        """
        Log the start of an AWS API call.
        
        Args:
            service: AWS service name (e.g., 'wellarchitected', 's3', 'bedrock')
            operation: API operation (e.g., 'create_workload', 'update_answer')
            params: Key parameters (sanitized - no secrets)
        """
        api_key = f"{service}:{operation}"
        self.step_timers[api_key] = time.time()
        
        # Sanitize params - remove any sensitive data
        safe_params = self._sanitize_params(params or {})
        
        self._log("AWS_API_START", {
            "aws_service": service,
            "aws_operation": operation,
            "parameters": safe_params,
            "message": f"AWS API call: {service}.{operation}"
        })
    
    def aws_api_complete(self, service: str, operation: str, result_summary: Optional[Dict] = None):
        """Log successful completion of AWS API call."""
        api_key = f"{service}:{operation}"
        duration = time.time() - self.step_timers.get(api_key, time.time())
        
        self._log("AWS_API_COMPLETE", {
            "aws_service": service,
            "aws_operation": operation,
            "duration_seconds": round(duration, 2),
            "result_summary": result_summary or {},
            "message": f"AWS API complete: {service}.{operation} in {duration:.2f}s"
        })
    
    def aws_api_error(self, service: str, operation: str, error: Exception):
        """Log AWS API error."""
        api_key = f"{service}:{operation}"
        duration = time.time() - self.step_timers.get(api_key, time.time())
        
        self._log("AWS_API_ERROR", {
            "aws_service": service,
            "aws_operation": operation,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "duration_seconds": round(duration, 2),
            "message": f"AWS API error: {service}.{operation} - {str(error)[:200]}"
        }, level="ERROR")
    
    # =========================================================================
    # Agent Decision Logging
    # =========================================================================
    
    def agent_decision(self, agent_name: str, decision: str, reasoning: Optional[str] = None, data: Optional[Dict] = None):
        """
        Log an agent's decision or reasoning.
        
        Args:
            agent_name: Name of the agent making the decision
            decision: The decision made
            reasoning: Optional reasoning explanation
            data: Optional supporting data
        """
        self._log("AGENT_DECISION", {
            "agent_name": agent_name,
            "decision": decision,
            "reasoning": reasoning[:500] if reasoning else None,
            "data": self._summarize_results(data or {}),
            "message": f"Agent {agent_name} decided: {decision[:100]}"
        })
    
    def agent_invoke(self, agent_name: str, input_summary: Optional[Dict] = None):
        """Log agent invocation."""
        self._log("AGENT_INVOKE", {
            "agent_name": agent_name,
            "input_summary": self._summarize_results(input_summary or {}),
            "message": f"Invoking agent: {agent_name}"
        })
    
    def llm_call(self, model_id: str, prompt_tokens: int, purpose: str):
        """Log LLM/Bedrock model call."""
        self._log("LLM_CALL", {
            "model_id": model_id,
            "prompt_tokens": prompt_tokens,
            "purpose": purpose,
            "message": f"LLM call to {model_id} for {purpose} (~{prompt_tokens} tokens)"
        })
    
    # =========================================================================
    # Metric Logging
    # =========================================================================
    
    def metric(self, metric_name: str, value: float, unit: str = "count", dimensions: Optional[Dict] = None):
        """
        Log a metric value.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            unit: Unit of measurement
            dimensions: Optional dimensions for the metric
        """
        self._log("METRIC", {
            "metric_name": metric_name,
            "value": value,
            "unit": unit,
            "dimensions": dimensions or {},
            "message": f"Metric: {metric_name}={value} {unit}"
        })
    
    # =========================================================================
    # Session Lifecycle
    # =========================================================================
    
    def session_complete(self, total_duration: float, results_summary: Dict):
        """Log successful session completion."""
        self._log("SESSION_COMPLETE", {
            "total_duration_seconds": round(total_duration, 2),
            "results_summary": results_summary,
            "message": f"Session completed successfully in {total_duration:.2f}s"
        })
    
    def session_error(self, error: Exception, partial_results: Optional[Dict] = None):
        """Log session failure."""
        self._log("SESSION_ERROR", {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "error_traceback": traceback.format_exc()[-2000:],
            "partial_results": self._summarize_results(partial_results or {}),
            "message": f"Session failed: {type(error).__name__}: {str(error)[:200]}"
        }, level="ERROR")
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def _summarize_results(self, results: Dict) -> Dict:
        """Summarize results to avoid huge log entries."""
        summary = {}
        for key, value in results.items():
            if isinstance(value, list):
                summary[key] = f"list[{len(value)}]"
            elif isinstance(value, dict):
                summary[key] = f"dict[{len(value)} keys]"
            elif isinstance(value, str) and len(value) > 100:
                summary[key] = f"str[{len(value)} chars]"
            else:
                summary[key] = value
        return summary
    
    def _sanitize_params(self, params: Dict) -> Dict:
        """Remove sensitive data from parameters."""
        sensitive_keys = {'password', 'secret', 'token', 'key', 'credential', 'auth'}
        sanitized = {}
        for k, v in params.items():
            if any(s in k.lower() for s in sensitive_keys):
                sanitized[k] = "***REDACTED***"
            elif isinstance(v, dict):
                sanitized[k] = self._sanitize_params(v)
            elif isinstance(v, str) and len(v) > 500:
                sanitized[k] = f"{v[:100]}... ({len(v)} chars)"
            else:
                sanitized[k] = v
        return sanitized


# =============================================================================
# Decorator for automatic step logging
# =============================================================================

def log_step(step_name: str):
    """
    Decorator to automatically log step start, completion, and errors.
    
    Usage:
        @log_step("understanding")
        def _step_extract_insights(self, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Get or create workflow logger
            wf_logger = getattr(self, '_wf_logger', None)
            if wf_logger is None:
                session_id = kwargs.get('session_id', 'unknown')
                if hasattr(self, 'session_id'):
                    session_id = self.session_id
                wf_logger = WorkflowLogger(session_id)
            
            # Log start
            wf_logger.step_start(step_name, {
                "args_count": len(args),
                "kwargs_keys": list(kwargs.keys())
            })
            
            try:
                result = func(self, *args, **kwargs)
                
                # Log completion
                result_summary = {}
                if isinstance(result, dict):
                    result_summary = {"keys": list(result.keys())[:10]}
                elif isinstance(result, list):
                    result_summary = {"count": len(result)}
                
                wf_logger.step_complete(step_name, result_summary)
                return result
                
            except Exception as e:
                wf_logger.step_error(step_name, e)
                raise
        
        return wrapper
    return decorator


# =============================================================================
# Global workflow logger instance (for convenience)
# =============================================================================

_workflow_loggers: Dict[str, WorkflowLogger] = {}


def get_workflow_logger(session_id: str, client_name: Optional[str] = None) -> WorkflowLogger:
    """
    Get or create a workflow logger for a session.
    
    Args:
        session_id: Session identifier
        client_name: Optional client name
    
    Returns:
        WorkflowLogger instance
    """
    if session_id not in _workflow_loggers:
        _workflow_loggers[session_id] = WorkflowLogger(session_id, client_name)
    return _workflow_loggers[session_id]


def cleanup_workflow_logger(session_id: str):
    """Remove workflow logger for a completed session."""
    if session_id in _workflow_loggers:
        del _workflow_loggers[session_id]
