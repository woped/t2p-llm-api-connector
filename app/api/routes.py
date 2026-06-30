import json
import logging
import threading
import time
from app import log_utils
from app.api import bp
from app.services.async_jobs import AsyncJobStore
from app.services.llm_service import LLMService, ProviderError
from app.services import model_registry
from app.validation import validate_model, ValidationError
from app.request_id import get_request_id, set_request_id
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


def _format_issues(issues):
    """Render validation problems as an indented, one-per-line bulleted list.

    Produces output like::

        Issues:
          - first problem
          - second problem

    so a multi-problem rejection is readable in the console instead of a single
    semicolon-run line.
    """
    return "\n" + "\n".join(f"  - {issue}" for issue in issues)


def _log_total_token_usage(usage_records, provider, model):
    """Log the token usage summed across every attempt of one request.

    No-op when nothing was recorded (token logging disabled, or a mocked
    service in tests). Lives in the route rather than the service because the
    per-request total spans the multiple service calls the retry loop owns.
    """
    if not usage_records:
        return
    prompt = sum(u["prompt"] for u in usage_records)
    cached = sum(u.get("cached", 0) for u in usage_records)
    completion = sum(u["completion"] for u in usage_records)
    total = sum(u["total"] for u in usage_records)
    # Cost is omitted for any attempt on an unpriced model, so only sum the known
    # ones. ``cost`` is the actual (cache-discounted) figure; ``cost_full`` the
    # hypothetical no-cache figure, so the saving can be shown for comparison.
    costs = [u["cost"] for u in usage_records if u.get("cost") is not None]
    costs_full = [
        u["cost_full"] for u in usage_records if u.get("cost_full") is not None
    ]
    actual = sum(costs) if costs else None
    full = sum(costs_full) if costs_full else None
    cost_str = log_utils.format_cost(actual, full, cached, compare=True)
    # Logged as two separate records so each gets its own timestamp/level prefix.
    # The breakdown line starts with the arrow flush against the message (no
    # leading indent), so it reads as a clear continuation of the line above.
    logger.info(
        "Total token usage for request: %d LLM call(s) (provider=%s, model=%s)",
        len(usage_records),
        provider,
        model,
    )
    logger.info(
        "-> input=%d (cached=%d) output=%d total=%s%s",
        prompt,
        cached,
        completion,
        log_utils.emphasize(total, log_utils.BOLD, log_utils.CYAN),
        f" {cost_str}" if cost_str else "",
    )


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
    provider = generate_kwargs.get("provider")
    model_name = generate_kwargs.get("model")
    # Token usage of each attempt is collected here so the total across all
    # retries can be logged once when the request finishes (success or failure).
    usage_out = []
    feedback = None
    previous_model = None
    last_issues = []
    try:
        for attempt in range(1, _MAX_GENERATION_ATTEMPTS + 1):
            # Deterministic first attempt; regenerations use a small non-zero
            # temperature so a rejected output is not reproduced verbatim, and
            # carry the previous attempt's validation problems plus the rejected
            # model so the model fixes that exact model instead of diverging.
            temperature = 0.0 if attempt == 1 else _RETRY_TEMPERATURE
            generate_kwargs["temperature"] = temperature
            logger.info(
                "Generation attempt %d/%d (provider=%s, model=%s, temperature=%s, %s)",
                attempt,
                _MAX_GENERATION_ATTEMPTS,
                provider,
                model_name,
                temperature,
                "with correction feedback" if feedback else "first try, no feedback",
            )
            raw_response = _llm_service.generate(
                **generate_kwargs,
                feedback=feedback,
                previous_model=previous_model,
                usage_out=usage_out,
            )
            try:
                model = json.loads(raw_response)
            except (json.JSONDecodeError, TypeError):
                logger.info(
                    "Attempt %d/%d returned non-JSON output; passing through "
                    "unvalidated.",
                    attempt,
                    _MAX_GENERATION_ATTEMPTS,
                )
                return raw_response
            try:
                validate_model(model)
                logger.info(
                    "Generation attempt %d/%d passed validation.",
                    attempt,
                    _MAX_GENERATION_ATTEMPTS,
                )
                return raw_response
            except ValidationError as e:
                feedback = str(e)
                last_issues = e.issues
                previous_model = raw_response
                if attempt < _MAX_GENERATION_ATTEMPTS:
                    logger.warning(
                        "Generation attempt %d/%d failed validation; retrying with "
                        "feedback. Issues:%s",
                        attempt,
                        _MAX_GENERATION_ATTEMPTS,
                        _format_issues(e.issues),
                    )
                else:
                    logger.error(
                        "Generation attempt %d/%d failed validation; no attempts "
                        "left. Giving up. Last issues:%s",
                        attempt,
                        _MAX_GENERATION_ATTEMPTS,
                        _format_issues(e.issues),
                    )
        raise ValidationError(last_issues)
    finally:
        _log_total_token_usage(usage_out, provider, model_name)


# --- v2 contract API (consumed by t2p-2.0) --------------------------------
#
# t2p-2.0's ConnectorClient calls these two endpoints:
#   POST <connector>/generate   body {user_text, provider, model}, Bearer auth
#   GET  <connector>/models     -> {"models": [{provider, model}]}
# The error body shape is {"error": {"code": str, "message": str}} so t2p-2.0
# can relay 4xx client errors unchanged.


def _v2_error(status_code, code, message, details=None):
    """Build the standard connector error body and status tuple.

    ``details`` (optional) is a list of structured, machine-readable specifics
    for errors that carry them — e.g. the individual validation problems behind
    a ``model_unprocessable``. It is omitted from the body when not provided, so
    simple errors stay a flat ``{code, message}``.
    """
    error = {"code": code, "message": message, "request_id": get_request_id()}
    if details:
        error["details"] = list(details)
    return jsonify({"error": error}), status_code


def _extract_bearer_key():
    """Return the raw API key from a well-formed ``Authorization: Bearer <key>``.

    Returns None if the header is missing or malformed.
    """
    auth = request.headers.get("Authorization", "")
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
        return parts[1]
    return None


def _validate_request(api_key, data):
    """Pre-generation validation shared by the sync and async paths.

    Returns a normalized error dict ``{http_status, code, message, details}`` on
    rejection, or ``None`` when the request is well-formed. Request-free: it
    takes the already-extracted key and parsed body so the async worker (which
    runs without a request context) can reuse it.
    """
    if api_key is None:
        return {
            "http_status": 401,
            "code": "unauthorized",
            "message": "Missing or malformed Authorization header.",
            "details": None,
        }
    if not isinstance(data, dict):
        return {
            "http_status": 400,
            "code": "invalid_request",
            "message": "Request body must be JSON.",
            "details": None,
        }
    missing = [f for f in ("user_text", "provider", "model") if not data.get(f)]
    if missing:
        # Log what actually arrived so a malformed client request is diagnosable
        # from the server logs (this happens before any LLM call or retry).
        logger.warning(
            "/generate rejected (invalid_request): missing/empty %s; "
            "body keys received: %s",
            missing,
            sorted(data.keys()),
        )
        return {
            "http_status": 400,
            "code": "invalid_request",
            "message": f"Missing or empty field(s): {', '.join(missing)}.",
            "details": None,
        }
    if not model_registry.is_valid(data["provider"], data["model"]):
        return {
            "http_status": 400,
            "code": "invalid_provider",
            "message": f"Unknown provider/model: {data['provider']}/{data['model']}.",
            "details": None,
        }
    return None


def _generate_only(api_key, data):
    """Run the validated generation (assumes the request already passed
    ``_validate_request``).

    Returns ``(result, error)`` with exactly one set: ``result =
    {"raw_response": str}`` on success, else a normalized error dict. Request-free
    so the async worker can reuse it.
    """
    provider = data["provider"]
    model = data["model"]
    logger.info("Invoking LLMService.generate (provider=%s, model=%s)", provider, model)
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
        # The provider answered, but no attempt produced a valid workflow net.
        # Unprocessable *input* -> 422 (client-actionable: rephrase), with the
        # concrete validator problems in ``details`` for diagnostics.
        return None, {
            "http_status": 422,
            "code": "model_unprocessable",
            "message": (
                "Could not generate a valid process model from the description "
                f"after {_MAX_GENERATION_ATTEMPTS} attempts. The description may "
                "be too ambiguous or describe a flow that cannot be expressed as "
                "a sound workflow net (e.g. branches or merges without a gateway, "
                "or more than one possible ending). Try rephrasing or "
                "simplifying it."
            ),
            "details": list(e.issues),
        }
    except ProviderError as e:
        # Upstream provider rejected/failed. Mirror its status (429 retryable,
        # else bad-gateway). Traceback already logged in the service layer.
        http_status = 429 if e.upstream_status == 429 else 502
        return None, {
            "http_status": http_status,
            "code": "upstream_error",
            "message": str(e),
            "details": None,
        }
    return {"raw_response": raw_response}, None


def _job_store():
    return AsyncJobStore(
        redis_url=current_app.config["REDIS_URL"],
        ttl_seconds=current_app.config.get("ASYNC_JOB_TTL_SECONDS", 3600),
        use_mock=current_app.config.get("REDIS_USE_MOCK", False),
    )


def _run_async_generate(app, job_id, request_id, api_key, data):
    """Background worker: run the generation and record the outcome in the job
    store. Runs outside any request context, so it re-binds the correlation id
    and uses the request-free ``_generate_only``.
    """
    with app.app_context():
        set_request_id(request_id)
        store = _job_store()
        store.update_status(job_id, "running")
        try:
            result, error = _generate_only(api_key, data)
        except Exception as e:  # never let a worker thread die silently
            logger.exception("Async generation crashed: %s", e)
            result, error = (
                None,
                {
                    "http_status": 500,
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": None,
                },
            )
        if error is not None:
            store.update_status(job_id, "failed", error=error)
        else:
            store.update_status(job_id, "succeeded", result=result)


@bp.route("/generate", methods=["POST"])
def generate():
    """Generate a structured BPMN-JSON process model from a description.

    Provider/model are validated against the registry; the API key is taken
    from the Authorization header (never from the body). Returns
    ``{"raw_response": <string>}`` on success.

    This synchronous endpoint is kept as the stable contract and as the async
    fallback; t2p-2.0 normally drives generation through the internal async
    submit/poll endpoints below.
    """
    start_time = time.time()
    status = "200"
    try:
        api_key = _extract_bearer_key()
        data = request.get_json(silent=True)
        error = _validate_request(api_key, data)
        if error is None:
            result, error = _generate_only(api_key, data)
        if error is not None:
            status = str(error["http_status"])
            return _v2_error(
                error["http_status"],
                error["code"],
                error["message"],
                error.get("details"),
            )
        return jsonify(result), 200
    except Exception as e:
        status = "500"
        logger.exception("/generate failed: %s", e)
        return _v2_error(500, "internal_error", "An unexpected error occurred.")
    finally:
        REQUEST_COUNT.labels(method="POST", endpoint="/generate", status=status).inc()
        REQUEST_LATENCY.labels(method="POST", endpoint="/generate").observe(
            time.time() - start_time
        )


@bp.route("/internal/jobs/generate", methods=["POST"])
def internal_generate_submit():
    """Async submit: validate, enqueue a background generation, return a job id.

    Used by t2p-2.0 so the long, multi-attempt generation is not held open on a
    single HTTP request (the connection that would otherwise hit the gunicorn
    worker timeout). Pre-generation validation runs synchronously, so malformed
    requests still get an immediate 4xx instead of a queued job.
    """
    if not current_app.config.get("INTERNAL_ASYNC_ENABLED", True):
        return _v2_error(404, "not_found", "Internal async endpoint is disabled.")

    api_key = _extract_bearer_key()
    data = request.get_json(silent=True)
    error = _validate_request(api_key, data)
    if error is not None:
        return _v2_error(
            error["http_status"], error["code"], error["message"], error.get("details")
        )

    store = _job_store()
    job_id = store.create()
    worker = threading.Thread(
        target=_run_async_generate,
        args=(
            current_app._get_current_object(),
            job_id,
            get_request_id(),
            api_key,
            data,
        ),
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
    """Async status: return the job's terminal result/error, or its progress.

    The stored ``error`` keeps the same ``{http_status, code, message, details}``
    shape the sync endpoint would have returned, so t2p-2.0 can preserve the
    original 4xx semantics (e.g. 422 model_unprocessable) instead of collapsing
    every async failure to a generic 5xx.
    """
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
