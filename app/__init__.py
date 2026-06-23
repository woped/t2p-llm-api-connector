import click, unittest, sys, logging, time
from config import get_config
from flask import Flask, request, g, redirect
from flask_wtf.csrf import CSRFProtect
from flasgger import Swagger

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app(config_class=None):
    """Application factory pattern"""
    app = Flask(__name__)

    # Load configuration
    if config_class is None:
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
        csrf = CSRFProtect(app)
        logger.info("CSRF protection enabled")

    # Register blueprints
    from app.api import bp as api_bp

    app.register_blueprint(api_bp)
    logger.info("Blueprints registered")

    # Flasgger / OpenAPI setup.
    swagger_template = {
        "openapi": "3.0.2",
        "info": {
            "title": "LLM API Connector",
            "version": "1.0.0",
            "description": "Internal API used by t2p-2.0 to call LLM providers.",
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Provider API key as Authorization: Bearer <api_key>.",
                }
            }
        },
    }
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": "openapi",
                "route": "/openapi.json",
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/docs/",
    }
    Swagger(app, template=swagger_template, config=swagger_config)

    @app.route("/openapi.yaml")
    def openapi_yaml_alias():
        # Compatibility alias for clients that still expect the old path.
        return redirect("/openapi.json", code=302)

    # Request logging
    @app.before_request
    def _log_request_start():
        g._start_time = time.time()
        logger.debug("%s %s -> start", request.method, request.path)

    @app.after_request
    def _log_request_end(response):
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
        """Run the unit tests."""
        logger.info("Running unit tests...")
        loader = unittest.TestLoader()
        start_dir = "tests"
        suite = loader.discover(start_dir)

        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        if result.wasSuccessful():
            logger.info("All tests passed.")
            return 0
        else:
            logger.error("Some tests failed.")
            sys.exit(1)

    return app