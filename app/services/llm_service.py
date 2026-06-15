import logging
import time
from openai import OpenAI
from google import genai
from app.utils.prompt_builder import PromptBuilder
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

    def call_openai(
        self, api_key, system_prompt, user_text, prompting_strategy, model="gpt-4o"
    ):
        """Call an OpenAI model via the Responses API.

        Uses ``client.responses.create`` — the interface OpenAI now recommends
        for new projects — rather than the legacy Chat Completions endpoint. The
        Responses API unifies the output-token parameter as ``max_output_tokens``
        for every model, so the only model-dependent knob left is ``temperature``:
        GPT-5.x / o-series reasoning models reject it, while ``gpt-4o`` accepts
        it. That capability comes from the registry instead of a name heuristic.

        ``model`` defaults to ``gpt-4o`` so existing (v1) callers and tests keep
        working; the v2 ``/generate`` flow passes the model selected from the
        registry.
        """
        prompt, start_time = self._prepare(
            "call_openai", prompting_strategy, user_text, model
        )
        client = OpenAI(api_key=api_key)

        request_params = {
            "model": model,
            "instructions": system_prompt,
            "input": prompt,
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
        }
        if model_registry.supports_temperature("openai", model):
            request_params["temperature"] = 0

        try:
            logger.info("Calling OpenAI responses.create (model=%s)", model)
            response = client.responses.create(**request_params)
            content = response.output_text or ""
            duration = time.time() - start_time
            logger.info(
                "OpenAI response received in %.3fs (len=%d)",
                duration,
                len(content),
            )
            return content.strip()
        except Exception as e:
            logger.exception("OpenAI call failed: %s", e)
            raise ProviderError(str(e), _upstream_status(e)) from e

    def call_gemini(
        self,
        api_key,
        system_prompt,
        user_text,
        prompting_strategy,
        model="gemini-3.5-flash",
    ):
        """Call a Google Gemini model via the unified ``google-genai`` SDK.

        Uses a per-call ``genai.Client(api_key=...)`` instead of the deprecated
        ``google-generativeai`` SDK's global ``genai.configure(...)``. The old
        global configuration was process-wide mutable state: under concurrent
        requests carrying different API keys it was a race condition. A
        per-request client isolates each call's credentials.

        ``model`` defaults to ``gemini-3.5-flash`` (the current standard flash
        tier); the v2 ``/generate`` flow passes the model selected from the
        registry.
        """
        prompt, start_time = self._prepare(
            "call_gemini", prompting_strategy, user_text, model
        )

        client = genai.Client(api_key=api_key)

        config_kwargs = {
            "system_instruction": system_prompt,
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
        }
        if model_registry.supports_temperature("gemini", model):
            config_kwargs["temperature"] = 0.0
            config_kwargs["top_k"] = 1
            config_kwargs["top_p"] = 1.0

        try:
            logger.info("Calling Gemini generate_content (model=%s)", model)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(**config_kwargs),
            )
            text = (response.text or "") if hasattr(response, "text") else ""
            duration = time.time() - start_time
            logger.info(
                "Gemini response received in %.3fs (len=%d)",
                duration,
                len(text),
            )
            return text.strip()
        except Exception as e:
            logger.exception("Gemini call failed: %s", e)
            raise ProviderError(str(e), _upstream_status(e)) from e

    def generate(self, api_key, provider, model, user_text, system_prompt,
                 prompting_strategy="few_shot"):
        """Provider-agnostic entry point used by the v2 ``/generate`` route.

        Looks up the dispatch method for ``provider`` in the registry and calls
        it with the registry-selected ``model``. Raises ``ValueError`` if the
        provider has no dispatch mapping (the route validates the pair against
        the registry first, so this is a defensive guard).
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
        )
