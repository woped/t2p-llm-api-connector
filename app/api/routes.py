import logging
import time

from flask import Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.api import bp
from app.services.llm_service import LLMService
from config import get_config

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
SUPPORTED_MODELS = [
    {"provider": "openai", "model": "gpt-4o", "default": True},
    {"provider": "gemini", "model": "gemini-1.5-pro", "default": False},
]


def _error_response(status_code, code, message):
    return jsonify({"error": {"code": code, "message": message}}), status_code


def _extract_bearer_token():
    auth = request.headers.get("Authorization", "")
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
        return parts[1]
    return None


@bp.route("/models", methods=["GET"])
def models():
    return jsonify({"models": SUPPORTED_MODELS}), 200


@bp.route("/generate", methods=["POST"])
def generate():
    """Dispatch a contract-based generation request to a supported provider."""
    start_time = time.time()
    status = "200"
    try:
        api_key = _extract_bearer_token()
        if api_key is None:
            status = "400"
            return _error_response(
                400, "invalid_request", "Missing or malformed bearer token."
            )

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            status = "400"
            return _error_response(400, "invalid_request", "Request body must be JSON.")

        missing = [
            field for field in ("user_text", "provider", "model") if not data.get(field)
        ]
        if missing:
            status = "400"
            return _error_response(
                400,
                "invalid_request",
                f"Missing or empty field(s): {', '.join(missing)}.",
            )

        supported = any(
            item["provider"] == data["provider"] and item["model"] == data["model"]
            for item in SUPPORTED_MODELS
        )
        if not supported:
            status = "400"
            return _error_response(
                400,
                "invalid_provider",
                "Unsupported provider/model combination.",
            )

        config_instance = get_config()()
        strategy = data.get("prompting_strategy", "few_shot")
        service = LLMService()
        if data["provider"] == "openai":
            result = service.call_openai(
                api_key, config_instance.SYSTEM_PROMPT, data["user_text"], strategy
            )
        else:
            result = service.call_gemini(
                api_key, config_instance.SYSTEM_PROMPT, data["user_text"], strategy
            )
        return jsonify({"raw_response": result}), 200
    except ValueError as exc:
        status = "400"
        return _error_response(400, "invalid_request", str(exc))
    except Exception:
        status = "500"
        logger.exception("/generate failed")
        return _error_response(500, "upstream_error", "Provider request failed.")
    finally:
        REQUEST_COUNT.labels(method="POST", endpoint="/generate", status=status).inc()
        REQUEST_LATENCY.labels(method="POST", endpoint="/generate").observe(
            time.time() - start_time
        )


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
