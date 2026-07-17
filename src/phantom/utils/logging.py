"""Structured logging configuration with secret redaction."""

from __future__ import annotations

import re

import structlog

# Patterns that should be redacted from all log output.
SECRET_PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9_]{36,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"gho_[A-Za-z0-9_]{36,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"sk-[A-Za-z0-9]{40,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"Bearer [A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), "[REDACTED_BEARER]"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "[REDACTED_AWS_KEY]"),
]


def redact_secrets(
    _logger: object, _method_name: str, event_dict: dict[str, object]
) -> dict[str, object]:
    """Structlog processor that redacts known secret patterns from all string values."""
    for key, value in event_dict.items():
        if isinstance(value, str):
            for pattern, replacement in SECRET_PATTERNS:
                value = pattern.sub(replacement, value)
            event_dict[key] = value
    return event_dict


def configure_logging(
    *, verbose: bool = False, json_output: bool = False, level: str | None = None
) -> None:
    """Configure structlog for Phantom.

    Args:
        verbose: If True, set log level to DEBUG. Otherwise INFO.
        json_output: If True, output JSON lines. Otherwise human-readable.
        level: Explicit level name (e.g. ``"error"``) that overrides ``verbose``.
            Used by commands like ``doctor`` that do their own reporting and want
            to suppress internal dependency-probe warnings.
    """
    min_level = structlog.processors.NAME_TO_LEVEL[
        level if level is not None else ("debug" if verbose else "info")
    ]
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_secrets,  # type: ignore[list-item]
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=40,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # For direct structlog usage (not via stdlib)
    structlog.configure(
        processors=[
            *shared_processors,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
