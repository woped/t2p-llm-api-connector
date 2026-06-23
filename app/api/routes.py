import json
import logging
import time
from app.api import bp
from app.services.llm_service import LLMService, ProviderError
from app.services import model_registry
from app.validation import validate_model, ValidationError
from flask import request, jsonify, current_app
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Logging is configured centrally in the entrypoint (see app/__init__.py);
# modules only obtain a logger here.
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

# A failed validation re-runs the whole LLM generation. Total attempts include
# the first try, so this is one initial call plus two retries.
_MAX_GENERATION_ATTEMPTS = 3

# Temperature used when regenerating after a validation failure. The first
# attempt runs deterministically (temperature 0); without a bump the identical
# prompt would yield the identical invalid output, wasting the retries. Kept
# small so the output still tracks the prompt closely. (Reasoning models that
# reject temperature are unaffected — the provider call drops it for them.)
_RETRY_TEMPERATURE = 0.3


def _generate_validated(**generate_kwargs):
    """Generate a process model, regenerating until it passes validation.

    Calls the LLM up to ``_MAX_GENERATION_ATTEMPTS`` times; the first response
    that passes validation is returned unchanged. A response that fails a
    validator triggers a fresh generation. Returns ``None`` if every attempt
    fails, so the caller can return a single generic error.

    Validation runs on the parsed model; a response that is not JSON is returned
    as-is (JSON-ness is the downstream contract's concern, and will be covered by
    enforced structured output).

    Raises ``ValidationError`` carrying the last attempt's problems if every
    attempt fails, so the caller can surface a meaningful reason instead of a
    generic error.
    """
    feedback = None
    for attempt in range(1, _MAX_GENERATION_ATTEMPTS + 1):
        # Deterministic first attempt; regenerations use a small non-zero
        # temperature so a rejected output is not reproduced verbatim, and carry
        # the previous attempt's validation problems so the model corrects them.
        generate_kwargs["temperature"] = 0.0 if attempt == 1 else _RETRY_TEMPERATURE
        raw_response = _llm_service.generate(**generate_kwargs, feedback=feedback)
        try:
            model = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError):
            return raw_response
        try:
            validate_model(model)
            return raw_response
        except ValidationError as e:
            feedback = str(e)
            logger.info(
                "Generation attempt %d/%d failed validation; retrying. Issues: %s",
                attempt,
                _MAX_GENERATION_ATTEMPTS,
                feedback,
            )
    raise ValidationError(feedback)


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
        try:
            raw_response = _generate_validated(
                api_key=api_key,
                provider=provider,
                model=model,
                user_text=data["user_text"],
                system_prompt=current_app.config["SYSTEM_PROMPT"],
                prompting_strategy=data.get("prompting_strategy", "few_shot"),
            )
        except ValidationError as e:
            status = "502"
            return _v2_error(
                502,
                "upstream_error",
                f"Could not generate a valid model after {_MAX_GENERATION_ATTEMPTS} "
                f"attempts. Last validation problems: {e}",
            )
        return jsonify({"raw_response": raw_response}), 200

    except ProviderError as e:
        # The upstream provider (OpenAI / Google) rejected or failed the call.
        # Forward its real error text and mirror the upstream status so the
        # calling service can debug and react (429 is retryable; otherwise it is
        # a bad-gateway condition). The traceback is already logged in the
        # service layer.
        http_status = 429 if e.upstream_status == 429 else 502
        status = str(http_status)
        return _v2_error(http_status, "upstream_error", str(e))
    except Exception as e:
        status = "500"
        logger.exception("/generate failed: %s", e)
        return _v2_error(500, "internal_error", "An unexpected error occurred.")
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
