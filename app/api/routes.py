import json
import logging
import time
from app import log_utils
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
    error = {"code": code, "message": message}
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
            # Log what actually arrived so a malformed client request is
            # diagnosable from the server logs: this rejection happens before any
            # LLM call or retry, so an empty/wrong-shaped body lands here, not in
            # the generation loop.
            logger.warning(
                "/generate rejected (invalid_request): missing/empty %s; "
                "body keys received: %s",
                missing,
                sorted(data.keys()),
            )
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
            # Not an upstream failure: the provider answered, but no attempt
            # produced a valid workflow net. That is unprocessable *input*, so it
            # is a 422 (client-actionable: rephrase) rather than a 5xx. The
            # friendly message is for the end user; the concrete, repair-oriented
            # validator problems ride along in ``details`` for diagnostics.
            status = "422"
            return _v2_error(
                422,
                "model_unprocessable",
                "Could not generate a valid process model from the description "
                f"after {_MAX_GENERATION_ATTEMPTS} attempts. The description may "
                "be too ambiguous or describe a flow that cannot be expressed as "
                "a sound workflow net (e.g. branches or merges without a gateway, "
                "or more than one possible ending). Try rephrasing or "
                "simplifying it.",
                details=e.issues,
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
