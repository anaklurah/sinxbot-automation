"""
OSAP Structured Logging Setup
==============================
Configures Python's standard :mod:`logging` module with a :class:`RichHandler`
for colourful, human-readable console output and an optional :class:`FileHandler`
for persistent log files.

Usage::

    from osap.utils.logger import setup_logging, get_logger

    # Call once at application startup:
    setup_logging(level="DEBUG", log_file="osap.log")

    # In each module:
    log = get_logger(__name__)
    log.info("Ready.")
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

# ---------------------------------------------------------------------------
# Module-level console shared across all Rich output in OSAP
# ---------------------------------------------------------------------------

#: Shared Rich :class:`~rich.console.Console` instance (stderr, full colour).
console: Console = Console(stderr=True)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_LOG_FORMAT: str = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str | int = "INFO",
    log_file: str | Path | None = None,
) -> logging.Logger:
    """
    Configure the root logger with Rich console output and an optional file sink.

    This function is **idempotent**: calling it more than once replaces the
    handlers on the root logger rather than adding duplicates.

    Parameters
    ----------
    level:
        Logging level as a string (``"DEBUG"``, ``"INFO"``, ``"WARNING"``,
        ``"ERROR"``, ``"CRITICAL"``) or an integer constant from
        :mod:`logging`.  Defaults to ``"INFO"``.
    log_file:
        Optional path to a log file.  If provided, a :class:`logging.FileHandler`
        is added that writes every log record in the full ``%(asctime)s | …``
        format.  The file is opened in **append** mode with UTF-8 encoding.
        Parent directories are created automatically.

    Returns
    -------
    logging.Logger
        The configured root logger.

    Notes
    -----
    * The :class:`~rich.logging.RichHandler` shows coloured level names,
      module paths, and log messages but omits timestamps from the message
      itself (Rich renders time in its own column).
    * The file handler uses the full ``%(asctime)s | %(name)s | %(levelname)s
      | %(message)s`` format for easier ``grep`` / post-processing.
    """
    root_logger = logging.getLogger()

    # Resolve string level to integer
    numeric_level: int = (
        level if isinstance(level, int) else getattr(logging, level.upper(), logging.INFO)
    )
    root_logger.setLevel(numeric_level)

    # Remove any previously installed handlers to avoid duplication on reload.
    root_logger.handlers.clear()

    # ------------------------------------------------------------------
    # 1. Rich console handler
    # ------------------------------------------------------------------
    rich_handler = RichHandler(
        console=console,
        level=numeric_level,
        show_time=True,           # Rich renders time in its own column
        show_level=True,
        show_path=True,           # show module/file path
        rich_tracebacks=True,     # render tracebacks with Rich formatting
        tracebacks_show_locals=False,
        markup=True,              # allow Rich markup in log messages
        log_time_format=_DATE_FORMAT,
    )
    # Rich handler uses its own internal format; we keep the message clean.
    rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt=_DATE_FORMAT))
    root_logger.addHandler(rich_handler)

    # ------------------------------------------------------------------
    # 2. Optional file handler
    # ------------------------------------------------------------------
    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(
            filename=str(log_path),
            mode="a",
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(
            logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
        )
        root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers at WARNING unless the caller asked for DEBUG.
    for noisy_lib in ("urllib3", "httpx", "httpcore", "playwright", "asyncio"):
        logging.getLogger(noisy_lib).setLevel(
            logging.DEBUG if numeric_level <= logging.DEBUG else logging.WARNING
        )

    root_logger.debug(
        "Logging initialised — level=%s, file=%s",
        logging.getLevelName(numeric_level),
        log_file,
    )
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Return a named :class:`logging.Logger` for use inside an OSAP module.

    This is a thin wrapper around :func:`logging.getLogger` provided for
    consistency and discoverability.

    Parameters
    ----------
    name:
        Logger name — conventionally ``__name__`` of the calling module.

    Returns
    -------
    logging.Logger
        The named logger.  If :func:`setup_logging` has not been called yet,
        messages will propagate to the root logger's default ``lastResort``
        handler (stderr, WARNING+).

    Example
    -------
    ::

        from osap.utils.logger import get_logger

        log = get_logger(__name__)
        log.info("Processing video id=%d", video_id)
    """
    return logging.getLogger(name)
