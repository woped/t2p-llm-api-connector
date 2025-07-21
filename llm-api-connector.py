from app import create_app
import logging
from pythonjsonlogger import jsonlogger


class MetricsFilter(logging.Filter):
    """Filter to exclude metrics endpoints from logs"""
    def filter(self, record):
        if record.name == "werkzeug":
            return "/metrics" not in record.getMessage()
        try:
            from flask import request
            return not request.path.startswith('/metrics')
        except RuntimeError:
            return True


def setup_logging():
    """Setup logging configuration"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.INFO)
    
    metrics_filter = MetricsFilter()
    
    console_handler = logging.StreamHandler()
    console_handler.addFilter(metrics_filter)
    
    console_formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(console_handler)
    werkzeug_logger.addHandler(console_handler)


app = create_app()
setup_logging()
