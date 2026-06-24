import logging
import sys

from pythonjsonlogger import jsonlogger

from app import create_app

logger = logging.getLogger(__name__)


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


def setup_logging():
    """Setup logging configuration"""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.INFO)

    metrics_filter = MetricsFilter()

    # Ensure all runtime logs are emitted to stdout for container log collection.
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.addFilter(metrics_filter)

    console_formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)

    root_logger.handlers.clear()
    werkzeug_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    werkzeug_logger.addHandler(console_handler)
    logger.info("Logging configured to stdout")


setup_logging()
app = create_app()

# The ``flask test`` CLI command is registered in app/__init__.py (it reports a
# non-zero exit code when tests fail); no duplicate registration here.
