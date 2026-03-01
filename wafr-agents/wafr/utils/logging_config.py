"""
Production-Ready Logging Configuration

Provides structured logging with:
- JSON formatting for production
- Log levels configuration
- Request/response logging
- Performance metrics
- Error tracking
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    
    Useful for log aggregation systems like CloudWatch, ELK, etc.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
        
        # Add request context if available
        if hasattr(record, "session_id"):
            log_data["session_id"] = record.session_id
        
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        
        return json.dumps(log_data)


class ProductionLogger:
    """
    Production logger with structured logging and metrics.
    """
    
    def __init__(
        self,
        name: str,
        level: str = "INFO",
        json_format: bool = False,
        include_context: bool = True,
    ):
        """
        Initialize production logger.
        
        Args:
            name: Logger name
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            json_format: Use JSON formatting
            include_context: Include context in logs
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.include_context = include_context
        
        # Remove existing handlers
        self.logger.handlers.clear()
        
        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))
        
        if json_format:
            formatter = JSONFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
    
    def log_request(
        self,
        method: str,
        endpoint: str,
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Log incoming request."""
        extra = {
            "event_type": "request",
            "method": method,
            "endpoint": endpoint,
        }
        if session_id:
            extra["session_id"] = session_id
        extra.update(kwargs)
        
        self.logger.info(f"Request: {method} {endpoint}", extra={"extra_fields": extra})
    
    def log_response(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration: float,
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Log response."""
        extra = {
            "event_type": "response",
            "method": method,
            "endpoint": endpoint,
            "status_code": status_code,
            "duration_ms": duration * 1000,
        }
        if session_id:
            extra["session_id"] = session_id
        extra.update(kwargs)
        
        level = logging.INFO if status_code < 400 else logging.ERROR
        self.logger.log(
            level,
            f"Response: {method} {endpoint} - {status_code} ({duration:.3f}s)",
            extra={"extra_fields": extra},
        )
    
    def log_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Log error with context."""
        extra = {
            "event_type": "error",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        if context:
            extra.update(context)
        if session_id:
            extra["session_id"] = session_id
        
        self.logger.error(
            f"Error: {type(error).__name__}: {error}",
            exc_info=True,
            extra={"extra_fields": extra},
        )
    
    def log_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "count",
        tags: Optional[Dict[str, str]] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Log metric."""
        extra = {
            "event_type": "metric",
            "metric_name": metric_name,
            "value": value,
            "unit": unit,
        }
        if tags:
            extra["tags"] = tags
        if session_id:
            extra["session_id"] = session_id
        
        self.logger.info(
            f"Metric: {metric_name}={value} {unit}",
            extra={"extra_fields": extra},
        )
    
    def __getattr__(self, name: str) -> Any:
        """Delegate to underlying logger."""
        return getattr(self.logger, name)


def configure_production_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None,
) -> None:
    """
    Configure production logging for the entire application.
    
    Args:
        level: Log level
        json_format: Use JSON formatting
        log_file: Optional log file path
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Set levels for noisy libraries
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
