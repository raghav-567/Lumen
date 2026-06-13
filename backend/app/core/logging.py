"""Structured logging configuration with correlation IDs.

Provides request-scoped correlation IDs that flow through
async handlers, Celery tasks, and background processing.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

# ── Correlation ID context ──────────────────────────────

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Get the current correlation ID (or empty string)."""
    return correlation_id_var.get()


def set_correlation_id(cid: str | None = None) -> str:
    """Set a correlation ID for the current context. Returns the ID."""
    cid = cid or str(uuid.uuid4())[:8]
    correlation_id_var.set(cid)
    return cid


# ── Structured formatter ────────────────────────────────


class StructuredFormatter(logging.Formatter):
    """JSON-like structured log formatter with correlation ID."""

    def format(self, record: logging.LogRecord) -> str:
        cid = correlation_id_var.get()
        prefix = f"[{cid}] " if cid else ""

        # Add module context
        module = record.module or ""
        func = record.funcName or ""
        location = f"{module}.{func}" if func != "<module>" else module

        return (
            f"{record.levelname:<8} {prefix}"
            f"[{location}] "
            f"{record.getMessage()}"
        )


def configure_logging(level: str = "INFO"):
    """Configure structured logging for the application."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)

    # Suppress noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
