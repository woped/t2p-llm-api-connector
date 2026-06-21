import logging
import time
from openai import OpenAI
from google import genai
from app.utils.prompt_builder import PromptBuilder
from app.schemas import ProcessModel
from app.services import model_registry


logger = logging.getLogger(__name__)

# Upper bound on generated tokens, shared by both providers so the output budget
# is consistent regardless of which model handles the request.
_MAX_OUTPUT_TOKENS = 4096


class ProviderError(Exception):
    """Raised when an upstream LLM provider (OpenAI / Google) call fails.

    Carries the provider's own error text (via ``str``) and, when the SDK
    exposes it, the upstream HTTP status — enough for the calling service to
    debug the failure and react (e.g. retry on 429).
    """

    def __init__(self, message, upstream_status=None):
        self.upstream_status = upstream_status  # int HTTP status, if known
        super().__init__(message)


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

    def _prepare(self, provider, prompting_strategy, user_text, model):
        """Build the prompt and emit the shared pre-call logging.

        Returns ``(prompt, start_time)``. Factored out so both provider methods
        share identical input handling, logging and timing.
        """
        if not user_text:
            logger.warning("%s: empty user_text provided", provider)
        start_time = time.time()
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
        model="gpt-4o",
        temperature=0.0,
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

        ``model`` defaults to ``gpt-4o`` so existing (v1) callers and tests keep
        working; the v2 ``/generate`` flow passes the model selected from the
        registry.
        """
        prompt, start_time = self._prepare(
            "openai", prompting_strategy, user_text, model
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
            return self._finish("openai", response.output_text, start_time)
        except Exception as e:
            raise self._fail("openai", e) from e

    def call_gemini(
        self,
        api_key,
        system_prompt,
        user_text,
        prompting_strategy,
        model="gemini-3.5-flash",
        temperature=0.0,
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
            "gemini", prompting_strategy, user_text, model
        )
        client = genai.Client(api_key=api_key)

        # Gemini nests the generation settings in a `config` object (the only
        # structural difference from OpenAI's flat params); everything else
        # follows the same build-request_params-then-call(**request_params)
        # pattern.
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
            return self._finish("gemini", response.text, start_time)
        except Exception as e:
            raise self._fail("gemini", e) from e

    def generate(self, api_key, provider, model, user_text, system_prompt,
                 prompting_strategy="few_shot", temperature=0.0):
        """Provider-agnostic entry point used by the v2 ``/generate`` route.

        Looks up the dispatch method for ``provider`` in the registry and calls
        it with the registry-selected ``model``. Raises ``ValueError`` if the
        provider has no dispatch mapping (the route validates the pair against
        the registry first, so this is a defensive guard).

        ``temperature`` is forwarded to the provider call; the retry loop raises
        it above ``0.0`` on regeneration so a rejected attempt is not produced
        verbatim again.
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
        )
