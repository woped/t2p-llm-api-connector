import logging
import os
import sys
from app import create_app, log_utils
from pythonjsonlogger import jsonlogger


# ANSI codes for the pretty console formatter. Kept inline (no extra dependency)
# so colour output works from a plain checkout.
_RESET = "\033[0m"
_DIM = "\033[2m"
_LEVEL_COLORS = {
    "DEBUG": "\033[36m",  # cyan
    "INFO": "\033[32m",  # green
    "WARNING": "\033[33m",  # yellow
    "ERROR": "\033[31m",  # red
    "CRITICAL": "\033[1;37;41m",  # white on red background
}


class ColorFormatter(logging.Formatter):
    """Human-readable, colourised console output for local/dev presentation.

    Mirrors the JSON formatter's fields (time, level, logger, message) but lays
    them out for eyeballs: dim timestamp and logger name, colour-coded level,
    plain message. Colour can be disabled (``use_color=False``), in which case it
    degrades to clean aligned plain text so redirected/piped logs stay readable.
    """

    def __init__(self, *, use_color=True):
        super().__init__(datefmt="%H:%M:%S")
        self.use_color = use_color

    def format(self, record):
        # A separator record (emitted at the start of each request) renders as a
        # blank line plus a dim rule instead of a normal timestamped line, so the
        # logs of consecutive requests are visually grouped.
        if getattr(record, "separator", False):
            rule = "-" * 72
            return f"\n{_DIM}{rule}{_RESET}" if self.use_color else f"\n{rule}"
        ts = self.formatTime(record, self.datefmt)
        level = record.levelname
        name = record.name
        msg = record.getMessage()
        if self.use_color:
            color = _LEVEL_COLORS.get(record.levelname, "")
            ts = f"{_DIM}{ts}{_RESET}"
            level = f"{color}{level:<8}{_RESET}"
            name = f"{_DIM}{name}{_RESET}"
        else:
            level = f"{level:<8}"
        line = f"{ts} {level} {name}  {msg}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class SeparatorFilter(logging.Filter):
    """Pass request-separator records only when output is the pretty formatter.

    The separator is a purely visual aid for the colourised console; in JSON
    mode it would just be a noise record, so it is dropped there.
    """

    def __init__(self, pretty):
        super().__init__()
        self.pretty = pretty

    def filter(self, record):
        if getattr(record, "separator", False):
            return self.pretty
        return True


class MetricsFilter(logging.Filter):
    """Filter to exclude metrics endpoints from logs"""

    def filter(self, record):
        if record.name == "werkzeug":
            return "/metrics" not in record.getMessage()
        try:
            from flask import request

            return not request.path.startswith("/metrics")
        except RuntimeError:
            return True


def _enable_windows_ansi():
    """Enable ANSI escape processing on legacy Windows consoles (no-op elsewhere).

    Windows Terminal / VS Code render ANSI natively, but the classic console
    needs virtual-terminal processing turned on first. Best-effort: any failure
    just means colour is skipped.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _select_console_formatter():
    """Choose the console log formatter from the environment.

    ``LOG_FORMAT=json``   -> structured JSON (machine-readable; the prod default)
    ``LOG_FORMAT=pretty`` -> colourised human-readable lines (the dev default)
    Unset -> ``pretty`` when ``FLASK_ENV=development``, otherwise ``json``.

    Within pretty mode, colour follows ``LOG_COLOR`` (``1/0``); when unset it is
    on only if stdout is a TTY, so redirecting logs to a file stays clean.
    """
    fmt = os.environ.get("LOG_FORMAT")
    if fmt is None:
        env = os.environ.get("FLASK_ENV", "development").lower()
        fmt = "pretty" if env == "development" else "json"
    fmt = fmt.strip().lower()

    if fmt in ("pretty", "color", "colour", "console", "dev"):
        color_flag = os.environ.get("LOG_COLOR")
        if color_flag is not None:
            use_color = color_flag.strip().lower() in ("1", "true", "yes", "on")
        else:
            use_color = sys.stdout.isatty()
        if use_color:
            _enable_windows_ansi()
        # Let in-message highlighting (token totals, cost) follow the same toggle.
        log_utils.set_color_enabled(use_color)
        return ColorFormatter(use_color=use_color)

    return jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )


def setup_logging():
    """Setup logging configuration"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Only set werkzeug's level. It propagates to the root logger, so the single
    # root handler below already formats and prints its request lines. Attaching
    # the same handler here too would emit every werkzeug record twice (once via
    # this handler, once via propagation) — the cause of the duplicated lines.
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.INFO)

    metrics_filter = MetricsFilter()

    console_handler = logging.StreamHandler()
    console_handler.addFilter(metrics_filter)
    formatter = _select_console_formatter()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SeparatorFilter(isinstance(formatter, ColorFormatter)))

    logger.addHandler(console_handler)


setup_logging()
app = create_app()

# The ``flask test`` CLI command is registered in app/__init__.py (it reports a
# non-zero exit code when tests fail); no duplicate registration here.
