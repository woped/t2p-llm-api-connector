import logging
import threading
import time

import prometheus_client
from flasgger import swag_from
from flask import current_app, jsonify, request

from app.api import bp
from app.services import model_registry
from app.services.async_jobs import AsyncJobStore
from app.services.llm_service import EmptyResponseError, LLMService

logger = logging.getLogger(__name__)

# Prometheus Metriken
REQUEST_COUNT = prometheus_client.Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = prometheus_client.Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"]
)

# Single, stateless LLMService instance shared across requests. Building it once
# avoids re-reading and re-parsing the few-shot template file on every request
# (the per-call provider clients are still created inside each call_* method,
# keeping per-request API keys isolated).
_llm_service = LLMService()
_SUPPORTED_PROMPTING_STRATEGIES = {"zero_shot", "few_shot"}


def _job_store():
    return AsyncJobStore(
        redis_url=current_app.config["REDIS_URL"],
        ttl_seconds=current_app.config.get("ASYNC_JOB_TTL_SECONDS", 3600),
        use_mock=current_app.config.get("REDIS_USE_MOCK", False),
    )


def _validate_generate_payload(api_key, data):
    if api_key is None:
        return _v2_error(401, "unauthorized", "Missing or malformed Authorization header.")

    if not isinstance(data, dict):
        return _v2_error(400, "invalid_request", "Request body must be JSON.")

    missing = [f for f in ("user_text", "provider", "model") if not data.get(f)]
    if missing:
        return _v2_error(
            400,
            "invalid_request",
            f"Missing or empty field(s): {', '.join(missing)}.",
        )

    if data.get("prompting_strategy", "zero_shot") not in _SUPPORTED_PROMPTING_STRATEGIES:
        allowed = ", ".join(sorted(_SUPPORTED_PROMPTING_STRATEGIES))
        return _v2_error(
            400,
            "invalid_request",
            f"Invalid prompting_strategy '{data.get('prompting_strategy')}'. Allowed values: {allowed}.",
        )

    provider = data["provider"]
    model = data["model"]
    try:
        model_registry.refresh_model_cache(provider=provider, api_key=api_key)
    except Exception as refresh_err:
        logger.warning(
            "Model cache refresh failed for provider %s: %s",
            provider,
            refresh_err,
        )

    if not model_registry.is_valid(provider, model):
        return _v2_error(
            400,
            "invalid_provider",
            f"Unknown provider/model: {provider}/{model}.",
        )

    return None


def _run_async_generate(app, job_id, api_key, data):
    with app.app_context():
        store = _job_store()
        store.update_status(job_id, "running")
        try:
            raw_response = _llm_service.generate(
                api_key=api_key,
                provider=data["provider"],
                model=data["model"],
                user_text=data["user_text"],
                system_prompt=current_app.config["SYSTEM_PROMPT"],
                prompting_strategy=data.get("prompting_strategy", "zero_shot"),
            )
            store.update_status(
                job_id,
                "succeeded",
                result={"raw_response": raw_response},
                error=None,
            )
        except EmptyResponseError as e:
            store.update_status(
                job_id,
                "failed",
                error={
                    "code": "invalid_request",
                    "message": "The LLM provider returned an empty response.",
                    "detail": str(e),
                },
            )
        except Exception as e:
            error_code = "rate_limited" if _is_quota_error(e) else "upstream_error"
            error_message = (
                "Provider quota or rate limit exceeded. Try again later or use another model."
                if error_code == "rate_limited"
                else "The LLM provider call failed."
            )
            store.update_status(
                job_id,
                "failed",
                error={"code": error_code, "message": error_message, "detail": str(e)},
            )


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


def _is_quota_error(exc):
    """Return True for provider quota/rate-limit style exceptions."""
    text = str(exc or "").lower()
    indicators = (
        "quota",
        "resourceexhausted",
        "too many requests",
        "rate limit",
        "perday",
    )
    return any(token in text for token in indicators)


@bp.route("/generate", methods=["POST"])
@swag_from(
    {
        "tags": ["v2-contract"],
        "summary": "Generate process model",
        "description": "Generate a structured BPMN JSON model from process text.",
        "security": [{"bearerAuth": []}],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["user_text", "provider", "model"],
                        "properties": {
                            "user_text": {"type": "string"},
                            "provider": {"type": "string"},
                            "model": {"type": "string"},
                            "prompting_strategy": {
                                "type": "string",
                                "enum": ["zero_shot", "few_shot"],
                                "default": "zero_shot",
                            },
                        },
                    }
                }
            },
        },
        "responses": {
            "200": {
                "description": "Successful provider response",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"raw_response": {"type": "string"}},
                        }
                    }
                },
            },
            "400": {"description": "Invalid request or provider/model"},
            "401": {"description": "Missing or malformed Authorization header"},
            "429": {"description": "Provider quota or rate limit exceeded"},
            "500": {"description": "Upstream provider failure"},
        },
    }
)
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
        data = request.get_json(silent=True)
        validation_error = _validate_generate_payload(api_key, data)
        if validation_error is not None:
            status = str(validation_error[1])
            return validation_error

        provider = data["provider"]
        model = data["model"]
        prompting_strategy = data.get("prompting_strategy", "zero_shot")

        # Refresh the model cache with the caller's key so is_valid reflects
        # the live model list for that key rather than a stale startup cache.
        try:
            model_registry.refresh_model_cache(provider=provider, api_key=api_key)
        except Exception as refresh_err:
            logger.warning(
                "Model cache refresh failed for provider %s: %s",
                provider,
                refresh_err,
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
            prompting_strategy=prompting_strategy,
        )
        return jsonify({"raw_response": raw_response}), 200

    except Exception as e:
        if isinstance(e, EmptyResponseError):
            status = "400"
            logger.warning("/generate rejected empty provider response: %s", e)
            return _v2_error(
                400,
                "invalid_request",
                "The LLM provider returned an empty response.",
            )

        if _is_quota_error(e):
            status = "429"
            logger.warning("/generate provider quota exceeded: %s", e)
            return _v2_error(
                429,
                "rate_limited",
                (
                    "Provider quota or rate limit exceeded. "
                    "Try again later or use another model."
                ),
            )

        status = "500"
        logger.exception("/generate failed: %s", e)
        return _v2_error(500, "upstream_error", "The LLM provider call failed.")
    finally:
        REQUEST_COUNT.labels(method="POST", endpoint="/generate", status=status).inc()
        REQUEST_LATENCY.labels(method="POST", endpoint="/generate").observe(
            time.time() - start_time
        )


@bp.route("/internal/jobs/generate", methods=["POST"])
def internal_generate_submit():
    """Internal-only async submit endpoint used by t2p orchestration."""
    if not current_app.config.get("INTERNAL_ASYNC_ENABLED", True):
        return _v2_error(404, "not_found", "Internal async endpoint is disabled.")

    api_key = _extract_bearer_key()
    data = request.get_json(silent=True)
    validation_error = _validate_generate_payload(api_key, data)
    if validation_error is not None:
        return validation_error

    store = _job_store()
    job_id = store.create()

    app_obj = current_app._get_current_object()
    worker = threading.Thread(
        target=_run_async_generate,
        args=(app_obj, job_id, api_key, data),
        daemon=True,
    )
    worker.start()

    return (
        jsonify(
            {
                "job_id": job_id,
                "status": "queued",
                "status_url": f"/internal/jobs/{job_id}",
            }
        ),
        202,
    )


@bp.route("/internal/jobs/<job_id>", methods=["GET"])
def internal_generate_status(job_id):
    """Internal-only async status endpoint used by t2p orchestration."""
    if not current_app.config.get("INTERNAL_ASYNC_ENABLED", True):
        return _v2_error(404, "not_found", "Internal async endpoint is disabled.")

    store = _job_store()
    payload = store.get(job_id)
    if payload is None:
        return _v2_error(404, "not_found", "Unknown or expired job id.")

    response = {
        "job_id": payload["job_id"],
        "status": payload["status"],
        "created_at": payload["created_at"],
        "updated_at": payload["updated_at"],
    }
    if payload.get("result") is not None:
        response["result"] = payload["result"]
    if payload.get("error") is not None:
        response["error"] = payload["error"]
    return jsonify(response), 200


@bp.route("/models", methods=["GET"])
@swag_from(
    {
        "tags": ["v2-contract"],
        "summary": "List models",
        "description": "Return supported provider/model pairs.",
        "responses": {
            "200": {
                "description": "Models listed",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "models": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "provider": {"type": "string"},
                                            "model": {"type": "string"},
                                        },
                                    },
                                }
                            },
                        }
                    }
                },
            },
            "500": {"description": "Internal error"},
        },
    }
)
def models():
    """Return the advertised provider/model pairs from the registry.

    If an ``Authorization: Bearer <key>`` header is present the key is used for
    live discovery so the caller sees the model list available to their key.
    Without a key the endpoint falls back to the env-level key (startup cache).
    """
    start_time = time.time()
    status = "200"
    try:
        provider = request.args.get("provider") or None
        api_key = _extract_bearer_key()
        model_registry.refresh_model_cache(provider=provider, api_key=api_key)
        return (
            jsonify({"models": model_registry.get_cached_models(provider=provider)}),
            200,
        )
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
@swag_from(
    {
        "tags": ["operations"],
        "summary": "Health check",
        "description": "Operational liveness endpoint.",
        "responses": {
            "200": {
                "description": "Service is reachable",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"success": {"type": "boolean"}},
                        }
                    }
                },
            }
        },
    }
)
def echo():
    """Health check endpoint"""
    logger.debug("Health check hit: /_/_/echo")
    REQUEST_COUNT.labels(method="GET", endpoint="/_/_/echo", status="200").inc()
    return jsonify(success=True)


@bp.route("/health/providers", methods=["GET"])
@swag_from(
    {
        "tags": ["operations"],
        "summary": "Provider reachability",
        "description": (
            "Checks OpenAI/Gemini host reachability without provider secrets. "
            "HTTP auth errors (for example 401) still count as reachable."
        ),
        "parameters": [
            {
                "name": "provider",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": ["openai", "gemini"]},
            },
            {
                "name": "timeout",
                "in": "query",
                "required": False,
                "schema": {"type": "integer", "minimum": 1, "maximum": 30},
                "description": "Probe timeout in seconds (default 5).",
            },
        ],
        "responses": {
            "200": {"description": "All requested providers reachable"},
            "400": {"description": "Invalid query parameter"},
            "503": {"description": "One or more providers unreachable"},
        },
    }
)
def provider_health():
    """Return non-secret connectivity diagnostics for provider hosts."""
    start_time = time.time()
    status = "200"
    try:
        provider = request.args.get("provider") or None
        timeout_raw = request.args.get("timeout") or "5"

        try:
            timeout_seconds = int(timeout_raw)
        except ValueError:
            status = "400"
            return _v2_error(400, "invalid_request", "timeout must be an integer.")

        try:
            diagnostics = model_registry.provider_connectivity(
                provider=provider,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as exc:
            status = "400"
            return _v2_error(400, "invalid_request", str(exc))

        all_reachable = all(item.get("reachable") for item in diagnostics)
        response = {
            "all_reachable": all_reachable,
            "providers": diagnostics,
        }

        if all_reachable:
            return jsonify(response), 200

        status = "503"
        return jsonify(response), 503
    except Exception as exc:
        status = "500"
        logger.exception("/health/providers failed: %s", exc)
        return _v2_error(500, "internal_error", "Provider health check failed.")
    finally:
        REQUEST_COUNT.labels(
            method="GET", endpoint="/health/providers", status=status
        ).inc()
        REQUEST_LATENCY.labels(method="GET", endpoint="/health/providers").observe(
            time.time() - start_time
        )


@bp.route("/health/ready", methods=["GET"])
@swag_from(
    {
        "tags": ["operations"],
        "summary": "Readiness probe",
        "description": (
            "Compact readiness check based on provider host connectivity. "
            "Returns 200 when all providers are reachable, otherwise 503."
        ),
        "responses": {
            "200": {"description": "Service is ready"},
            "503": {"description": "Service is not ready"},
        },
    }
)
def readiness_health():
    """Readiness probe suitable for orchestrators/load balancers."""
    start_time = time.time()
    status = "200"
    try:
        diagnostics = model_registry.provider_connectivity(
            provider=None, timeout_seconds=3
        )
        all_reachable = all(item.get("reachable") for item in diagnostics)

        response = {
            "ready": all_reachable,
            "checked_providers": [item.get("provider") for item in diagnostics],
        }

        if all_reachable:
            return jsonify(response), 200

        status = "503"
        return jsonify(response), 503
    except Exception as exc:
        status = "503"
        logger.exception("/health/ready failed: %s", exc)
        return jsonify({"ready": False, "checked_providers": []}), 503
    finally:
        REQUEST_COUNT.labels(
            method="GET", endpoint="/health/ready", status=status
        ).inc()
        REQUEST_LATENCY.labels(method="GET", endpoint="/health/ready").observe(
            time.time() - start_time
        )


@bp.route("/metrics")
def metrics():
    """Expose Prometheus metrics."""
    logger.debug("Metrics scraped: /metrics")
    REQUEST_COUNT.labels(method="GET", endpoint="/metrics", status="200").inc()
    return (
        prometheus_client.generate_latest(),
        200,
        {"Content-Type": prometheus_client.CONTENT_TYPE_LATEST},
    )
