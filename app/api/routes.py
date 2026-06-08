import logging, time
from app.api import bp
from app.services.llm_service import LLMService
from app.services import model_registry
from flask import request, jsonify, current_app
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus Metriken
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"]
)

# Single, stateless LLMService instance shared across requests. Building it once
# avoids re-reading and re-parsing the few-shot template file on every request
# (the per-call provider clients are still created inside each call_* method,
# keeping per-request API keys isolated).
_llm_service = LLMService()


# --- v2 contract API (consumed by t2p-2.0) --------------------------------
#
# t2p-2.0's ConnectorClient calls these two endpoints:
#   POST <connector>/generate   body {user_text, provider, model}, Bearer auth
#   GET  <connector>/models     -> {"models": [{provider, model}]}
# The error body shape is {"error": {"code": str, "message": str}} so t2p-2.0
# can relay 4xx client errors unchanged.


def _v2_error(status_code, code, message):
    """Build the standard connector error body and status tuple."""
    return jsonify({"error": {"code": code, "message": message}}), status_code


def _extract_bearer_key():
    """Return the raw API key from a well-formed ``Authorization: Bearer <key>``.

    Returns None if the header is missing or malformed.
    """
    auth = request.headers.get("Authorization", "")
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
        return parts[1]
    return None


@bp.route("/generate", methods=["POST"])
def generate():
    """Generate a structured BPMN-JSON process model from a description.

    Provider/model are validated against the registry; the API key is taken
    from the Authorization header (never from the body). Returns
    ``{"raw_response": <string>}`` on success.
    """
    start_time = time.time()
    status = "200"
    try:
        api_key = _extract_bearer_key()
        if api_key is None:
            status = "401"
            return _v2_error(
                401, "unauthorized", "Missing or malformed Authorization header."
            )

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            status = "400"
            return _v2_error(400, "invalid_request", "Request body must be JSON.")

        missing = [f for f in ("user_text", "provider", "model") if not data.get(f)]
        if missing:
            status = "400"
            return _v2_error(
                400,
                "invalid_request",
                f"Missing or empty field(s): {', '.join(missing)}.",
            )

        provider = data["provider"]
        model = data["model"]
        if not model_registry.is_valid(provider, model):
            status = "400"
            return _v2_error(
                400,
                "invalid_provider",
                f"Unknown provider/model: {provider}/{model}.",
            )

        logger.info(
            "Invoking LLMService.generate (provider=%s, model=%s)", provider, model
        )
        raw_response = _llm_service.generate(
            api_key=api_key,
            provider=provider,
            model=model,
            user_text=data["user_text"],
            system_prompt=current_app.config["SYSTEM_PROMPT"],
            prompting_strategy=data.get("prompting_strategy", "few_shot"),
        )
        return jsonify({"raw_response": raw_response}), 200

    except Exception as e:
        status = "500"
        logger.exception("/generate failed: %s", e)
        return _v2_error(500, "upstream_error", "The LLM provider call failed.")
    finally:
        REQUEST_COUNT.labels(method="POST", endpoint="/generate", status=status).inc()
        REQUEST_LATENCY.labels(method="POST", endpoint="/generate").observe(
            time.time() - start_time
        )


@bp.route("/models", methods=["GET"])
def models():
    """Return the advertised provider/model pairs from the registry."""
    start_time = time.time()
    status = "200"
    try:
        return jsonify({"models": model_registry.list_models()}), 200
    except Exception as e:
        status = "500"
        logger.exception("/models failed: %s", e)
        return _v2_error(500, "internal_error", "Could not list models.")
    finally:
        REQUEST_COUNT.labels(method="GET", endpoint="/models", status=status).inc()
        REQUEST_LATENCY.labels(method="GET", endpoint="/models").observe(
            time.time() - start_time
        )


@bp.route("/_/_/echo")
def echo():
    """Health check endpoint"""
    logger.debug("Health check hit: /_/_/echo")
    REQUEST_COUNT.labels(method="GET", endpoint="/_/_/echo", status="200").inc()
    return jsonify(success=True)


@bp.route("/metrics")
def metrics():
    """Expose Prometheus metrics."""
    logger.debug("Metrics scraped: /metrics")
    REQUEST_COUNT.labels(method="GET", endpoint="/metrics", status="200").inc()
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
