"""
Audit logger — append-only structured log of all document reads and queries.

Security decisions:
- FileHandler opened in 'a' (append) mode: no existing entries can be
  overwritten or truncated within this process.
- Log entries are newline-delimited JSON for easy parsing and tamper detection.
- Sensitive query content is included (required for audit), so the log file
  itself must be protected at the OS level (chmod 640, root-owned directory).
- Logs are never emitted to stdout/stderr to avoid accidental exposure in
  environments that capture process output.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Module-level logger instance; initialised once via get_audit_logger()
_audit_logger: logging.Logger | None = None


def get_audit_logger() -> logging.Logger:
    """Return the configured audit logger, initialising it on first call."""
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger

    log_path = Path(os.getenv("LOG_PATH", "./logs/audit.log"))

    # Security: ensure the log directory exists before opening the file.
    # Parents are created automatically; exist_ok prevents race conditions.
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("enterprise_knowledge_audit")
    logger.setLevel(logging.INFO)

    # Security: 'a' (append) mode — never 'w' (write/truncate).
    # Each restart appends to the existing log rather than erasing history.
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    # Security: prevent log records from propagating to the root logger,
    # which could write to stdout/stderr or other unintended destinations.
    logger.propagate = False

    _audit_logger = logger
    return logger


def log_event(
    event_type: str,
    input_data: Any,
    output_data: Any,
    source_document: str | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    """
    Write a structured JSON audit entry.

    Args:
        event_type:      One of 'read_document', 'query', 'ingest'.
        input_data:      The raw input (file path, question, etc.).
        output_data:     Summary of the output (character count, answer excerpt).
        source_document: The file name(s) involved, if applicable.
        success:         Whether the operation completed without error.
        error:           Error message if success=False.
    """
    logger = get_audit_logger()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "input": input_data,
        "output": output_data,
        "source_document": source_document,
        "success": success,
        "error": error,
    }

    # ensure_ascii=False preserves non-ASCII characters in document names/content
    logger.info(json.dumps(entry, ensure_ascii=False))
