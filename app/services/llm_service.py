import logging
import time
from openai import OpenAI
import google.generativeai as genai
from app.utils.prompt_builder import PromptBuilder
from app.services import model_registry


logger = logging.getLogger(__name__)


class LLMService:
    """Service class for handling LLM API calls"""

    def __init__(self):
        self.prompt_builder = PromptBuilder()

    def call_openai(
        self, api_key, system_prompt, user_text, prompting_strategy, model="gpt-4o"
    ):
        """Call OpenAI GPT model.

        ``model`` defaults to ``gpt-4o`` so existing (v1) callers and tests keep
        working; the v2 ``/generate`` flow passes the model selected from the
        registry.
        """
        if not user_text:
            logger.warning("call_openai: empty user_text provided")
        start_time = time.time()
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        logger.debug(
            "call_openai: strategy=%s, model=%s, user_text_len=%d, prompt_len=%d",
            prompting_strategy,
            model,
            len(user_text or ""),
            len(prompt or ""),
        )
        client = OpenAI(api_key=api_key)

        try:
            logger.info("Calling OpenAI chat.completions (model=%s)", model)
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                model=model,
                max_tokens=4096,
            )
            content = chat_completion.choices[0].message.content or ""
            duration = time.time() - start_time
            logger.info(
                "OpenAI response received in %.3fs (len=%d)",
                duration,
                len(content),
            )
            return content.strip()
        except Exception as e:
            logger.exception("OpenAI call failed: %s", e)
            raise

    def call_gemini(
        self,
        api_key,
        system_prompt,
        user_text,
        prompting_strategy,
        model="gemini-1.5-pro",
    ):
        """Call Google Gemini model.

        ``model`` defaults to ``gemini-1.5-pro`` for backward compatibility; the
        v2 ``/generate`` flow passes the model selected from the registry.
        """
        if not user_text:
            logger.warning("call_gemini: empty user_text provided")
        start_time = time.time()
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        logger.debug(
            "call_gemini: strategy=%s, model=%s, user_text_len=%d, prompt_len=%d",
            prompting_strategy,
            model,
            len(user_text or ""),
            len(prompt or ""),
        )

        genai.configure(api_key=api_key)

        model = genai.GenerativeModel(
            model_name=model, system_instruction=system_prompt
        )

        try:
            logger.info("Calling Gemini generate_content")
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0, top_k=1, top_p=1.0, max_output_tokens=2048
                ),
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
            raise

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
