import logging
import os
import time
from openai import OpenAI
from google import genai
from app.utils.prompt_builder import PromptBuilder
from app.schemas import ProcessModel
from app.services import model_registry


logger = logging.getLogger(__name__)

# Upper bound on generated tokens, shared by both providers so the output budget
# is consistent regardless of which model handles the request. This is a ceiling,
# not a target — callers are billed only for the tokens actually generated — so it
# is set generously to give large process models room rather than truncating their
# JSON. Truncation against this bound is detected and surfaced per provider below.
# Kept within every registered model's output limit (e.g. gpt-4o caps at 16384).
_MAX_OUTPUT_TOKENS = 8192


class ProviderError(Exception):
    """Raised when an upstream LLM provider (OpenAI / Google) call fails.

    Carries the provider's own error text (via ``str``) and, when the SDK
    exposes it, the upstream HTTP status — enough for the calling service to
    debug the failure and react (e.g. retry on 429).
    """

    def __init__(self, message, upstream_status=None):
        self.upstream_status = upstream_status  # int HTTP status, if known
        super().__init__(message)


def _token_logging_enabled():
    """Whether per-call token usage should be logged.

    Opt-in by design: it is on automatically when running in development (the
    local ``flask run`` / ``FLASK_ENV=development`` case), and can be forced on
    or off regardless of environment via ``LOG_TOKEN_USAGE`` (``1/true/yes/on``
    vs anything else). Evaluated per call so the env var takes effect without a
    restart and tests can flip it freely.
    """
    flag = os.environ.get("LOG_TOKEN_USAGE")
    if flag is not None:
        return flag.strip().lower() in ("1", "true", "yes", "on")
    return os.environ.get("FLASK_ENV", "development").lower() == "development"


def _upstream_status(exc):
    """Best-effort upstream HTTP status from an SDK exception, else None.

    The OpenAI SDK exposes an int ``status_code``; the google-genai SDK exposes
    an int ``code``. Returns None when neither is a usable int.
    """
    status = getattr(exc, "status_code", None)
    if status is None and isinstance(getattr(exc, "code", None), int):
        status = exc.code
    return status if isinstance(status, int) else None


class LLMService:
    """Service class for handling LLM API calls"""

    def __init__(self):
        self.prompt_builder = PromptBuilder()

    def _prepare(
        self,
        provider,
        prompting_strategy,
        user_text,
        model,
        feedback=None,
        previous_model=None,
    ):
        """Build the prompt and emit the shared pre-call logging.

        Returns ``(prompt, start_time)``. Factored out so both provider methods
        share identical input handling, logging and timing.

        ``feedback`` carries the validation problems from a rejected previous
        attempt and ``previous_model`` the rejected model itself. They are
        appended to the description so the regeneration applies the specific
        fixes to that exact model instead of generating a fresh structure that
        diverges and reintroduces other errors.
        """
        if not user_text:
            logger.warning("%s: empty user_text provided", provider)
        start_time = time.time()
        if feedback:
            correction = (
                "The previous attempt was rejected for these workflow-net "
                f"problems:\n{feedback}\n"
            )
            if previous_model:
                correction += (
                    "Here is the exact model you returned previously:\n"
                    f"{previous_model}\n"
                    "Return that SAME model with ONLY the fixes above applied: add "
                    "the named gateways and re-route the listed flows. Change "
                    "nothing else - keep every other node id, name and flow "
                    "identical, do not rename tasks, and do not restructure "
                    "branches that were not flagged.\n"
                )
            else:
                correction += (
                    "Apply each instruction exactly: add the named gateways and "
                    "re-route the listed flows.\n"
                )
            correction += (
                "Control flow must never split or join directly on a task or "
                "event - only a gateway may have more than one incoming or "
                "outgoing flow."
            )
            user_text = f"{user_text}\n\n{correction}"
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        logger.debug(
            "%s: strategy=%s, model=%s, user_text_len=%d, prompt_len=%d",
            provider,
            prompting_strategy,
            model,
            len(user_text or ""),
            len(prompt or ""),
        )
        return prompt, start_time

    def _finish(self, provider, text, start_time):
        """Normalise a successful response and log its timing.

        Single source for the ``or ""`` + ``strip()`` and the duration log,
        shared by both provider methods.
        """
        text = (text or "").strip()
        logger.info(
            "%s response received in %.3fs (len=%d)",
            provider,
            time.time() - start_time,
            len(text),
        )
        return text

    def _record_usage(
        self,
        provider,
        model,
        usage_out,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        cached_tokens=0,
    ):
        """Emit a successful call's token usage and accumulate it for the caller.

        Provider-agnostic: each call site reads the counts from that provider's
        own usage object and passes them in. No-op unless token logging is
        enabled (see ``_token_logging_enabled``), so production stays quiet. The
        per-call cost is estimated from the registry's pricing and appended to
        the log line (omitted when the model is unpriced). When an ``usage_out``
        list is supplied the counts and cost are also appended to it, so the
        retry loop can total tokens and cost across all attempts of a request.
        """
        if not _token_logging_enabled():
            return
        cost = model_registry.estimate_cost(
            provider, model, prompt_tokens, completion_tokens, cached_tokens
        )
        cost_str = f" cost=${cost:.6f}" if cost is not None else ""
        logger.info(
            "%s token usage (model=%s): prompt=%s completion=%s total=%s%s",
            provider,
            model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            cost_str,
        )
        if usage_out is not None:
            usage_out.append(
                {
                    "prompt": prompt_tokens or 0,
                    "completion": completion_tokens or 0,
                    "total": total_tokens or 0,
                    "cost": cost,
                }
            )

    def _fail(self, provider, exc):
        """Log the traceback and build a ProviderError for the failed call.

        Call sites raise the returned error with ``from exc`` to keep the cause
        chain intact.
        """
        logger.exception("%s call failed: %s", provider, exc)
        return ProviderError(str(exc), _upstream_status(exc))

    def call_openai(
        self,
        api_key,
        system_prompt,
        user_text,
        prompting_strategy,
        model="gpt-5.4-mini",
        temperature=0.0,
        feedback=None,
        previous_model=None,
        usage_out=None,
    ):
        """Call an OpenAI model via the Responses API with Structured Outputs.

        Uses ``client.responses.parse`` — the interface OpenAI now recommends
        for new projects — rather than the legacy Chat Completions endpoint, and
        passes ``text_format=ProcessModel`` so the model is constrained to the
        BPMN-JSON schema (a strict JSON schema is compiled from the Pydantic
        model). This guarantees valid JSON and the exact element/flow ``type``
        values, replacing the prompt's hand-written "only return JSON" rules.

        The Responses API unifies the output-token parameter as
        ``max_output_tokens`` for every model, so the only model-dependent knob
        left is ``temperature``: GPT-5.x / o-series reasoning models reject it,
        while ``gpt-4o`` accepts it. That capability comes from the registry
        instead of a name heuristic.

        ``temperature`` defaults to ``0.0`` (deterministic). The retry loop
        passes a small non-zero value on regeneration so a failed attempt is
        not reproduced verbatim; it is only applied when the model accepts it.

        Returns ``response.output_text`` — the raw JSON string — so the calling
        service keeps receiving a string it can hand on unchanged.

        ``model`` defaults to ``gpt-5.4-mini`` — the registry's recommended
        default — for direct (v1) callers and tests; the v2 ``/generate`` flow
        passes the model selected from the registry.
        """
        prompt, start_time = self._prepare(
            "openai", prompting_strategy, user_text, model, feedback, previous_model
        )
        client = OpenAI(api_key=api_key)

        request_params = {
            "model": model,
            "instructions": system_prompt,
            "input": prompt,
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "text_format": ProcessModel,
        }
        if model_registry.supports_temperature("openai", model):
            request_params["temperature"] = temperature

        try:
            logger.info("Calling OpenAI responses.parse (model=%s)", model)
            response = client.responses.parse(**request_params)
        except Exception as e:
            raise self._fail("openai", e) from e

        # A truncated (max_output_tokens) or content-filtered response comes back
        # with status "incomplete" and partial/empty output. Returning that
        # partial text would hand broken JSON to the caller, so fail explicitly.
        if getattr(response, "status", None) == "incomplete":
            reason = getattr(
                getattr(response, "incomplete_details", None), "reason", None
            )
            raise ProviderError(
                f"OpenAI returned an incomplete response (reason={reason}); the "
                f"model likely hit max_output_tokens={_MAX_OUTPUT_TOKENS}."
            )

        usage = getattr(response, "usage", None)
        if usage is not None:
            cached = getattr(
                getattr(usage, "input_tokens_details", None), "cached_tokens", 0
            )
            self._record_usage(
                "openai",
                model,
                usage_out,
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
                getattr(usage, "total_tokens", None),
                cached,
            )
        return self._finish("openai", response.output_text, start_time)

    def call_gemini(
        self,
        api_key,
        system_prompt,
        user_text,
        prompting_strategy,
        model="gemini-3.5-flash",
        temperature=0.0,
        feedback=None,
        previous_model=None,
        usage_out=None,
    ):
        """Call a Google Gemini model via the unified ``google-genai`` SDK.

        Uses a per-call ``genai.Client(api_key=...)`` instead of the deprecated
        ``google-generativeai`` SDK's global ``genai.configure(...)``. The old
        global configuration was process-wide mutable state: under concurrent
        requests carrying different API keys it was a race condition. A
        per-request client isolates each call's credentials.

        Enforces structured output via ``response_mime_type="application/json"``
        plus ``response_schema=ProcessModel`` — the same Pydantic schema the
        OpenAI path uses — so Gemini is constrained to the BPMN-JSON shape and
        ``type`` values instead of relying on the prompt's hand-written rules.
        ``response.text`` is still the raw JSON string the caller hands on.

        ``temperature`` defaults to ``0.0``; the retry loop passes a small
        non-zero value on regeneration. At ``0.0`` we also pin ``top_k=1`` /
        ``top_p=1.0`` for fully greedy, deterministic decoding. When a non-zero
        temperature is requested those are left at the model defaults — pinning
        ``top_k=1`` would force greedy selection regardless of temperature, so
        keeping them would make the retry's temperature bump a no-op.

        ``model`` defaults to ``gemini-3.5-flash`` (the current standard flash
        tier); the v2 ``/generate`` flow passes the model selected from the
        registry.
        """
        prompt, start_time = self._prepare(
            "gemini", prompting_strategy, user_text, model, feedback, previous_model
        )
        client = genai.Client(api_key=api_key)

        # Gemini nests the generation settings in a `config` object — the only
        # structural difference from OpenAI's flat request params.
        config = {
            "system_instruction": system_prompt,
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "response_mime_type": "application/json",
            "response_schema": ProcessModel,
        }
        if model_registry.supports_temperature("gemini", model):
            config["temperature"] = temperature
            if temperature == 0.0:
                # Greedy decoding for a deterministic first attempt. Omitted on
                # retries so the temperature bump can actually vary the output.
                config["top_k"] = 1
                config["top_p"] = 1.0

        request_params = {
            "model": model,
            "contents": prompt,
            "config": genai.types.GenerateContentConfig(**config),
        }

        try:
            logger.info("Calling Gemini generate_content (model=%s)", model)
            response = client.models.generate_content(**request_params)
        except Exception as e:
            raise self._fail("gemini", e) from e

        # Anything other than a clean STOP (e.g. MAX_TOKENS truncation or a
        # SAFETY block) means the JSON is partial or absent; reading
        # ``response.text`` would yield broken/empty output, so fail explicitly.
        # Compared by name so a non-STOP reason surfaces regardless of SDK enum.
        candidate = response.candidates[0] if response.candidates else None
        finish = getattr(getattr(candidate, "finish_reason", None), "name", None)
        if finish is not None and finish not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            raise ProviderError(
                f"Gemini did not finish cleanly (finish_reason={finish}); output "
                f"may exceed max_output_tokens={_MAX_OUTPUT_TOKENS} or was blocked."
            )

        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            cached = getattr(usage, "cached_content_token_count", 0)
            self._record_usage(
                "gemini",
                model,
                usage_out,
                getattr(usage, "prompt_token_count", None),
                getattr(usage, "candidates_token_count", None),
                getattr(usage, "total_token_count", None),
                cached,
            )
        return self._finish("gemini", response.text, start_time)

    def generate(
        self,
        api_key,
        provider,
        model,
        user_text,
        system_prompt,
        prompting_strategy="few_shot",
        temperature=0.0,
        feedback=None,
        previous_model=None,
        usage_out=None,
    ):
        """Provider-agnostic entry point used by the v2 ``/generate`` route.

        Looks up the dispatch method for ``provider`` in the registry and calls
        it with the registry-selected ``model``. Raises ``ValueError`` if the
        provider has no dispatch mapping (the route validates the pair against
        the registry first, so this is a defensive guard).

        ``temperature`` is forwarded to the provider call; the retry loop raises
        it above ``0.0`` on regeneration so a rejected attempt is not produced
        verbatim again. ``feedback`` is likewise forwarded so the regeneration
        sees the previous attempt's validation problems.
        """
        method_name = model_registry.dispatch_method(provider)
        if method_name is None:
            raise ValueError(f"Unsupported provider: {provider}")
        method = getattr(self, method_name)
        return method(
            api_key=api_key,
            system_prompt=system_prompt,
            user_text=user_text,
            prompting_strategy=prompting_strategy,
            model=model,
            temperature=temperature,
            feedback=feedback,
            previous_model=previous_model,
            usage_out=usage_out,
        )
