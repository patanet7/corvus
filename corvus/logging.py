"""Central structlog configuration for the Corvus gateway.

Call ``configure_logging()`` once at each entry point (server, CLI, TUI) to
initialise structured logging with secret scrubbing, per-component level
filtering, and stdlib log routing.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog
from structlog.types import EventDict

from corvus.security.sanitizer import SANITIZER_PATTERNS

# ---------------------------------------------------------------------------
# Custom logger factory that preserves the logger name
# ---------------------------------------------------------------------------


class _NamedPrintLogger(structlog.PrintLogger):
    """A PrintLogger that carries a ``name`` attribute for processor access."""

    name: str

    def __init__(self, name: str, file: Any) -> None:
        super().__init__(file=file)
        self.name = name


class _NamedPrintLoggerFactory:
    """Factory that produces :class:`_NamedPrintLogger` instances.

    The first positional arg passed to ``structlog.get_logger(name)`` becomes
    the logger's ``name``.  This lets the ``_add_logger_name`` processor
    extract it without requiring stdlib logging.
    """

    def __init__(self, file: Any) -> None:
        self._file = file

    def __call__(self, *args: Any) -> _NamedPrintLogger:
        name = args[0] if args else ""
        return _NamedPrintLogger(name=str(name), file=self._file)

# ---------------------------------------------------------------------------
# Per-component log level map
# ---------------------------------------------------------------------------
# Maps LOG_LEVEL_<SUFFIX> env vars to logger name prefixes.  The first
# matching prefix wins (most-specific first).

COMPONENT_LEVEL_MAP: dict[str, str] = {
    "LOG_LEVEL_ROUTER": "corvus.router",
    "LOG_LEVEL_STREAM": "corvus.gateway.stream_processor",
    "LOG_LEVEL_GATEWAY": "corvus.gateway",
    "LOG_LEVEL_TUI": "corvus.tui",
    "LOG_LEVEL_CLI": "corvus.cli",
    "LOG_LEVEL_MEMORY": "corvus.memory",
    "LOG_LEVEL_SECURITY": "corvus.security",
    "LOG_LEVEL_ACP": "corvus.acp",
}

# Invert at import time: prefix -> env var name (sorted longest-prefix-first
# so the most specific match wins).
_PREFIX_TO_ENV: list[tuple[str, str]] = sorted(
    [(prefix, env_var) for env_var, prefix in COMPONENT_LEVEL_MAP.items()],
    key=lambda pair: len(pair[0]),
    reverse=True,
)

# Mapping from level name to numeric value (stdlib convention).
_LEVEL_NAMES: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


# ---------------------------------------------------------------------------
# Custom processors
# ---------------------------------------------------------------------------


def _add_logger_name(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:
    """Inject ``logger_name`` into the event dict from the bound logger."""
    if "logger_name" not in event_dict:
        # structlog stdlib integration sets ``_record`` on the event dict.
        record: logging.LogRecord | None = event_dict.get("_record")
        if record is not None:
            event_dict["logger_name"] = record.name
        else:
            # For pure structlog loggers, use the logger's name if present.
            name = getattr(logger, "name", None)
            if name:
                event_dict["logger_name"] = name
    return event_dict


def _component_level_filter(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:
    """Drop events whose level is below the per-component threshold.

    Raises ``structlog.DropEvent`` when the event should be suppressed.
    """
    logger_name: str = event_dict.get("logger_name", "")
    if not logger_name:
        return event_dict

    global_default = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Walk prefixes (longest first) to find the most specific override.
    for prefix, env_var in _PREFIX_TO_ENV:
        if logger_name == prefix or logger_name.startswith(prefix + "."):
            component_level_str = os.environ.get(env_var, "").upper()
            if component_level_str and component_level_str in _LEVEL_NAMES:
                # Explicit component override — use it as the threshold.
                threshold = _LEVEL_NAMES[component_level_str]
                event_level = _LEVEL_NAMES.get(
                    event_dict.get("level", "INFO").upper(), logging.INFO
                )
                if event_level < threshold:
                    raise structlog.DropEvent
                return event_dict
            # Component matched but no override set — fall through to
            # global default below.
            break

    # No component override matched — apply global default.
    threshold = _LEVEL_NAMES.get(global_default, logging.INFO)
    event_level = _LEVEL_NAMES.get(
        event_dict.get("level", "INFO").upper(), logging.INFO
    )
    if event_level < threshold:
        raise structlog.DropEvent

    return event_dict


def _scrub_secrets(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:
    """Redact credential patterns from ALL string values in the event dict."""
    for key in list(event_dict.keys()):
        value = event_dict[key]
        if isinstance(value, str):
            scrubbed = value
            for pattern, replacement in SANITIZER_PATTERNS:
                scrubbed = pattern.sub(replacement, scrubbed)
            if scrubbed is not value:
                event_dict[key] = scrubbed
    return event_dict


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(
    *,
    log_format: str | None = None,
    log_file: str | None = None,
) -> None:
    """Initialise structlog and stdlib logging for the entire process.

    Args:
        log_format: ``"console"`` (default, coloured key=value) or ``"json"``
            (machine-parseable JSONL).  Falls back to the ``LOG_FORMAT`` env
            var, then ``"console"``.
        log_file: Optional path to an additional log file.  When provided, a
            ``logging.FileHandler`` writing JSON lines is attached to the
            root stdlib logger.
    """
    fmt = (log_format or os.environ.get("LOG_FORMAT", "console")).lower()
    global_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    global_level = _LEVEL_NAMES.get(global_level_str, logging.INFO)

    # --- Shared processors (used by both structlog and stdlib bridge) ---
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_logger_name,
        _component_level_filter,
        _scrub_secrets,
        structlog.processors.StackInfoRenderer(),
    ]

    # --- Renderer ---
    # ConsoleRenderer handles exception formatting itself; format_exc_info
    # is only needed for JSONRenderer (which needs exc_info pre-serialised).
    if fmt == "json":
        shared_processors.append(structlog.processors.format_exc_info)
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    # --- Configure structlog ---
    # Use DEBUG as the bound-logger filter so that all events reach the
    # processor pipeline.  Actual level gating (both global and per-component)
    # is handled by ``_component_level_filter`` which reads env vars at
    # runtime and raises ``DropEvent`` as needed.
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=_NamedPrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )

    # --- Route stdlib logging through structlog formatting ---
    # This captures third-party logs (uvicorn, anthropic SDK, etc.).
    # ``foreign_pre_chain`` runs on log records coming from stdlib loggers
    # (i.e. not originating from structlog).  ``processors`` is the final
    # chain that produces the formatted string.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Clear existing handlers on root logger, attach ours.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(global_level)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)

    # Optional file handler (always JSON for machine parsing).
    if log_file:
        file_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
