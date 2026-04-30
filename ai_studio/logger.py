"""Logging configuration for the AI Studio orchestrator.

Output mode is chosen by ``LOG_FORMAT`` (``json`` | ``console``) and
defaults to ``json`` when stderr is not a TTY (Docker, k8s) and
``console`` otherwise (developer terminals). All records are pushed
through a ``QueueHandler`` so log I/O happens on a background thread
rather than blocking the asyncio event loop.
"""

import atexit
import copy
import json
import logging
import logging.handlers
import os
import re
import sys
import time
import traceback
from logging.config import dictConfig
from typing import Any

from ai_studio.context import REQUEST_ID_VAR

_TRUE_VALUES = {"1", "true", "yes", "on"}
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STANDARD_LOGRECORD_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }
)


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable using common truthy strings."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _resolve_format() -> str:
    """Resolve the active log format from environment or stderr interactivity."""
    explicit = os.environ.get("LOG_FORMAT", "").strip().lower()
    if explicit in ("json", "console"):
        return explicit
    return "console" if sys.stderr.isatty() else "json"


class PassThroughQueueHandler(logging.handlers.QueueHandler):
    """QueueHandler that defers all formatting to the listener thread.

    The default ``QueueHandler.prepare`` eagerly calls ``self.format(record)``
    and then clears ``exc_info``/``args`` on the record. That destroys the
    exception info our JSON formatter wants and forces formatting onto the
    asyncio thread — the opposite of why we have a queue at all.

    We still copy the record so any subsequent mutation by the producer
    can't race the listener.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        """Copy the record without formatting or stripping exception state."""
        return copy.copy(record)


class RequestIDFilter(logging.Filter):
    """Stamp every record with the active request id, validated.

    Defense in depth: even if something bypasses middleware sanitization
    and writes a hostile value into the contextvar, the filter rejects
    anything that doesn't match a strict allowlist before it reaches
    the formatter.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add a sanitized request_id attribute and keep the record."""
        raw = REQUEST_ID_VAR.get()
        record.request_id = raw if _VALID_REQUEST_ID.fullmatch(raw) else "-"
        return True


class JsonFormatter(logging.Formatter):
    """Emit each record as a single JSON line.

    Includes timestamp, level, logger, message, request_id, and any
    keyword arguments passed via ``extra=``. Exception info, when
    present, is rendered as a plain-text traceback string under
    ``exception``.
    """

    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as one JSON object per line."""
        payload: dict[str, Any] = {
            "timestamp": (
                self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
                + f".{int(record.msecs):03d}Z"
            ),
            "level": record.levelname,
            "logger": record.name,
            "lineno": record.lineno,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            ).rstrip()
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOGRECORD_ATTRS or key in payload:
                continue
            if key.startswith("_"):
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


def _build_rich_console_formatter():
    """Subclass uvicorn's DefaultFormatter to render exceptions with rich."""
    from rich.console import Console
    from rich.traceback import Traceback
    from uvicorn.logging import DefaultFormatter

    show_locals = _env_bool("LOG_TRACEBACK_LOCALS")
    console = Console(stderr=True)

    class _RichTracebackFormatter(DefaultFormatter):
        """Console formatter that renders exception tracebacks with rich."""

        def formatException(self, ei) -> str:
            """Render exception information as rich console text."""
            exc_type, exc_value, tb = ei
            tb_obj = Traceback.from_exception(
                exc_type,
                exc_value,
                tb,
                show_locals=show_locals,
                width=console.width,
            )
            with console.capture() as capture:
                console.print(tb_obj)
            return capture.get().rstrip()

    return _RichTracebackFormatter


def _start_listeners(*handler_names: str) -> None:
    """Start QueueListeners installed by dictConfig and register shutdown."""
    for name in handler_names:
        handler = logging.getHandlerByName(name)
        listener = getattr(handler, "listener", None)
        if listener is None:
            continue
        listener.start()
        atexit.register(listener.stop)


def configure_logger() -> None:
    """Apply the orchestrator logging configuration.

    Reads:
        LOG_LEVEL: default ``INFO``.
        LOG_FORMAT: ``json`` | ``console``. Default: auto by ``sys.stderr.isatty()``.
        LOG_TRACEBACK_LOCALS: include local variables in rich tracebacks.
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    fmt = _resolve_format()

    if fmt == "console":
        from rich.console import Console
        from rich.traceback import install as install_rich_traceback

        install_rich_traceback(
            show_locals=_env_bool("LOG_TRACEBACK_LOCALS"),
            console=Console(stderr=True),
        )
        default_formatter: dict[str, Any] = {
            "()": _build_rich_console_formatter(),
            "fmt": (
                "%(levelprefix)s %(name)s:%(lineno)d "
                "[rid=%(request_id)s] %(message)s"
            ),
            "use_colors": None,
        }
        access_formatter: dict[str, Any] = {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": (
                "%(levelprefix)s [rid=%(request_id)s] "
                '%(client_addr)s - "%(request_line)s" %(status_code)s'
            ),
            "use_colors": None,
        }
    else:
        default_formatter = {"()": JsonFormatter}
        access_formatter = {"()": JsonFormatter}

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIDFilter}},
            "formatters": {
                "default": default_formatter,
                "access": access_formatter,
            },
            "handlers": {
                "stderr": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                    "formatter": "default",
                },
                "stdout_access": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "access",
                },
                "queue_default": {
                    "class": "ai_studio.logger.PassThroughQueueHandler",
                    "handlers": ["stderr"],
                    "respect_handler_level": True,
                    "filters": ["request_id"],
                },
                "queue_access": {
                    "class": "ai_studio.logger.PassThroughQueueHandler",
                    "handlers": ["stdout_access"],
                    "respect_handler_level": True,
                    "filters": ["request_id"],
                },
            },
            "loggers": {
                "": {
                    "handlers": ["queue_default"],
                    "level": level,
                },
                "ai_studio": {"handlers": [], "level": level, "propagate": True},
                "uvicorn": {"handlers": [], "level": level, "propagate": True},
                "uvicorn.error": {
                    "handlers": [],
                    "level": level,
                    "propagate": True,
                },
                "uvicorn.access": {
                    "handlers": ["queue_access"],
                    "level": level,
                    "propagate": False,
                },
                "httpx": {"handlers": [], "level": "WARNING", "propagate": True},
                "sqlalchemy": {
                    "handlers": [],
                    "level": "WARNING",
                    "propagate": True,
                },
            },
        }
    )

    _start_listeners("queue_default", "queue_access")
