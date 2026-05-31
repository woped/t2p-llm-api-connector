import logging, time
from app.api import bp
from app.services.llm_service import LLMService
from app.services import model_registry
from config import get_config
from flask import request, jsonify, Response
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
CALL_OPENAI_DURATION = Histogram("call_openai_duration_seconds", "OpenAI call duration")


@bp.route("/call_openai", methods=["POST"])
def call_openai():
    """Call OpenAI GPT model"""
    start_time = time.time()
    logger.info("Received request to /call_openai")
    try:
        data = request.get_json()
        if data is None:
            logger.warning("/call_openai received no JSON body")
        else:
            req_keys = [k for k in data.keys() if k != "api_key"]
            user_text_len = len(data.get("user_text") or "")
            prompting_strategy = data.get("prompting_strategie", "few_shot")
            logger.debug(
                "call_openai payload: keys=%s, user_text_len=%d, prompting_strategy=%s",
                req_keys,
                user_text_len,
                prompting_strategy,
            )
        config_class = get_config()
        config_instance = config_class()

        llm_service = LLMService()
        logger.info("Invoking LLMService.call_openai")
        result = llm_service.call_openai(
            api_key=data.get("api_key"),
            system_prompt=data.get("system_prompt", config_instance.SYSTEM_PROMPT),
            user_text=data.get("user_text"),
            prompting_strategy=data.get("prompting_strategie", "few_shot"),
        )

        REQUEST_COUNT.labels(method="POST", endpoint="/call_openai", status="200").inc()
        duration = time.time() - start_time
        logger.info(
            "/call_openai succeeded in %.3fs (response_len=%d)",
            duration,
            len(result or ""),
        )
        if request.args.get("format") == "text":
            return Response(
                result or "", status=200, mimetype="text/plain; charset=utf-8"
            )
        return jsonify({"message": result})

    except Exception as e:
        REQUEST_COUNT.labels(method="POST", endpoint="/call_openai", status="500").inc()
        logger.exception("/call_openai failed: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        REQUEST_LATENCY.labels(method="POST", endpoint="/call_openai").observe(
            time.time() - start_time
        )


@bp.route("/call_gemini", methods=["POST"])
def call_gemini():
    """Call Google Gemini model"""
    start_time = time.time()
    try:
        data = request.get_json()
        if data is None:
            logger.warning("/call_gemini received no JSON body")
        else:
            req_keys = [k for k in data.keys() if k != "api_key"]
            user_text_len = len(data.get("user_text") or "")
            prompting_strategy = data.get("prompting_strategie", "few_shot")
            logger.debug(
                "call_gemini payload: keys=%s, user_text_len=%d, prompting_strategy=%s",
                req_keys,
                user_text_len,
                prompting_strategy,
            )
        config_class = get_config()
        config_instance = config_class()

        llm_service = LLMService()
        logger.info("Invoking LLMService.call_gemini")
        result = llm_service.call_gemini(
            api_key=data.get("api_key"),
            system_prompt=data.get("system_prompt", config_instance.SYSTEM_PROMPT),
            user_text=data.get("user_text"),
            prompting_strategy=data.get("prompting_strategie", "few_shot"),
        )

        REQUEST_COUNT.labels(method="POST", endpoint="/call_gemini", status="200").inc()
        duration = time.time() - start_time
        logger.info(
            "/call_gemini succeeded in %.3fs (response_len=%d)",
            duration,
            len(result or ""),
        )
        if request.args.get("format") == "text":
            return Response(
                result or "", status=200, mimetype="text/plain; charset=utf-8"
            )
        return jsonify({"message": result})

    except Exception as e:
        REQUEST_COUNT.labels(method="POST", endpoint="/call_gemini", status="500").inc()
        logger.exception("/call_gemini failed: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        REQUEST_LATENCY.labels(method="POST", endpoint="/call_gemini").observe(
            time.time() - start_time
        )


# --- v2 contract API (consumed by t2p-2.0) --------------------------------
#
# t2p-2.0's ConnectorClient calls these two endpoints:
#   POST <connector>/generate   body {user_text, provider, model}, Bearer auth
#   GET  <connector>/models     -> {"models": [{provider, model, default}]}
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
            status = "400"
            return _v2_error(
                400, "invalid_request", "Missing or malformed Authorization header."
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

        config_instance = get_config()()
        llm_service = LLMService()
        logger.info(
            "Invoking LLMService.generate (provider=%s, model=%s)", provider, model
        )
        raw_response = llm_service.generate(
            api_key=api_key,
            provider=provider,
            model=model,
            user_text=data["user_text"],
            system_prompt=config_instance.SYSTEM_PROMPT,
            prompting_strategy=data.get("prompting_strategie", "few_shot"),
        )
        return jsonify({"raw_response": raw_response}), 200

    except Exception as e:
        status = "500"
        logger.exception("/generate failed: %s", e)
        return _v2_error(
            500, "upstream_error", "The LLM provider call failed."
        )
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
