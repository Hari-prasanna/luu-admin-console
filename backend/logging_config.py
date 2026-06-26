"""
Structured JSON logging configuration for LUU Q-Console.

All services emit JSON logs with consistent envelope:
- timestamp, service, event, level, request_id, status, duration_ms, error details
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Context variable for request_id propagation across async tasks
request_id_context: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_request_id() -> Optional[str]:
    """Get current request_id from async context."""
    return request_id_context.get()


def set_request_id(request_id: Optional[str]) -> None:
    """Set request_id in async context."""
    request_id_context.set(request_id)


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured JSON."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Convert log record to JSON envelope."""
        # Base envelope
        envelope = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "service": self.service_name,
            "level": record.levelname,
        }

        # Extract event name from message or logger name
        event_name = record.name.split(".")[-1] if "." in record.name else "log"
        if record.getMessage():
            msg = record.getMessage()
            # If message is in format "event_name: details", extract event
            if ":" in msg:
                event_name, msg = msg.split(":", 1)
                event_name = event_name.strip()
            envelope["event"] = event_name
        else:
            envelope["event"] = event_name

        # Add request_id if available
        request_id = get_request_id()
        if request_id:
            envelope["request_id"] = request_id
        else:
            envelope["request_id"] = None

        # Extract extra fields from LogRecord attributes
        status = getattr(record, "status", None)
        if status:
            envelope["status"] = status

        duration_ms = getattr(record, "duration_ms", None)
        if duration_ms is not None:
            envelope["duration_ms"] = duration_ms

        error_code = getattr(record, "error_code", None)
        if error_code:
            envelope["error_code"] = error_code

        error_message = getattr(record, "error_message", None)
        if error_message:
            envelope["error_message"] = error_message
        elif record.exc_info and record.exc_text:
            envelope["error_message"] = record.exc_text.strip()

        # Add context object from extra
        context = getattr(record, "context", {})
        if context:
            envelope["context"] = context

        return json.dumps(envelope, default=str)


def setup_structured_logging(service_name: str, log_file: str) -> logging.Logger:
    """
    Configure structured JSON logging for a service.

    Args:
        service_name: Name of the service (e.g., "internal-transport-api")
        log_file: Path to rotating log file

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.DEBUG)

    # Remove existing handlers
    logger.handlers.clear()

    formatter = StructuredJsonFormatter(service_name)

    # Console handler (stderr)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (rotating)
    try:
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=7  # 10MB, keep 7 backups
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"could not_setup_file_handler: {e}", extra={"context": {"error": str(e)}})

    return logger


class StructuredLoggerAdapter(logging.LoggerAdapter):
    """Adapter to inject common context into log records."""

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """Process log message and kwargs."""
        if "extra" not in kwargs:
            kwargs["extra"] = {}

        # Ensure extra dict exists
        if not isinstance(kwargs["extra"], dict):
            kwargs["extra"] = {}

        # Add request_id to extra if not present
        request_id = get_request_id()
        if request_id and "request_id" not in kwargs["extra"]:
            kwargs["extra"]["request_id"] = request_id

        return msg, kwargs
