import logging
import os
import sys
import time
from flask import Flask, request, g, send_from_directory
from flask_wtf.csrf import CSRFProtect
from flask_swagger_ui import get_swaggerui_blueprint
from app.request_id import REQUEST_ID_HEADER, get_request_id, set_request_id

# Logging is configured once, centrally, by setup_logging() in the entrypoint
# (llm-api-connector.py). Modules only obtain a logger — calling basicConfig here
# installed a second root handler and every line was emitted twice (plain + JSON).
logger = logging.getLogger(__name__)

# Endpoints that are polled/automated rather than user-driven; they do not get a
# request separator so the console stays focused on real /generate traffic.
# ``str.startswith`` accepts this tuple directly.
_QUIET_PATHS = (
    "/metrics",
    "/docs",
    "/openapi.yaml",
    "/_/_/echo",
    "/static",
    "/favicon.ico",
)


def create_app(config_class=None):
    """Application factory pattern"""
    app = Flask(__name__)

    # Load configuration
    if config_class is None:
        from config import get_config

        config_class = get_config()
    app.config.from_object(config_class)
    try:
        logger.info(
            "Flask app created with config: %s",
            getattr(config_class, "__name__", str(config_class)),
        )
        logger.debug(
            "Config flags: DEBUG=%s TESTING=%s WTF_CSRF_ENABLED=%s",
            app.config.get("DEBUG"),
            app.config.get("TESTING"),
            app.config.get("WTF_CSRF_ENABLED", True),
        )
    except Exception as e:
        logger.warning("Unable to log config details: %s", e)

    # CSRF-Security
    if app.config.get("WTF_CSRF_ENABLED", True):
        CSRFProtect(app)  # registers itself on the app; no handle needed
        logger.info("CSRF protection enabled")

    # Register blueprints
    from app.api import bp as api_bp

    app.register_blueprint(api_bp)
    logger.info("Blueprints registered")

    # Swagger UI  — served at /docs, spec sourced from /openapi.yaml
    SWAGGER_URL = "/docs"
    SPEC_URL = "/openapi.yaml"
    swaggerui_bp = get_swaggerui_blueprint(
        SWAGGER_URL,
        SPEC_URL,
        config={"app_name": "LLM API Connector"},
    )
    app.register_blueprint(swaggerui_bp, url_prefix=SWAGGER_URL)

    _docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")

    @app.route("/openapi.yaml")
    def serve_openapi_yaml():
        return send_from_directory(_docs_dir, "openapi.yaml")

    # Request logging
    @app.before_request
    def _log_request_start():
        g._start_time = time.time()
        # Bind the correlation id first so every line below (and in the view)
        # carries it. Honours the id t2p-2.0 forwards, else mints one.
        set_request_id(request.headers.get(REQUEST_ID_HEADER))
        # Emit a visual separator so each request's log block is easy to spot in
        # the console. Skipped for noise endpoints (health/metrics/docs/static)
        # so only meaningful requests start a new block. The separator is
        # rendered only by the pretty console formatter (dropped in JSON mode).
        if not request.path.startswith(_QUIET_PATHS):
            logger.info("", extra={"separator": True})
        logger.debug("%s %s -> start", request.method, request.path)

    @app.after_request
    def _log_request_end(response):
        # Echo the correlation id so the caller (and ultimately the end user) can
        # quote it when reporting a failure.
        response.headers[REQUEST_ID_HEADER] = get_request_id()
        try:
            duration = None
            if hasattr(g, "_start_time"):
                duration = time.time() - g._start_time
            logger.info(
                "%s %s <- %s in %.3fs",
                request.method,
                request.path,
                response.status_code,
                duration if duration is not None else -1.0,
            )
        except Exception as e:
            logger.warning("Failed to log request end: %s", e)
        return response

    # CLI Commands
    @app.cli.command("test")
    def test():
        """Run the full test suite with pytest.

        Uses pytest rather than ``unittest`` discovery: several test modules are
        written as plain pytest functions (the validators and the few-shot
        guard), which ``unittest discover`` silently skips. Since CI runs this
        command (``coverage run -m flask test``), discovery would leave the
        whole validation layer untested there. pytest collects both styles.
        """
        import pytest

        logger.info("Running tests via pytest...")
        exit_code = pytest.main(["tests", "-q"])
        if exit_code != 0:
            sys.exit(int(exit_code))
        logger.info("All tests passed.")

    return app
