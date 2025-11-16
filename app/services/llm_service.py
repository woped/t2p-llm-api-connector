import logging
import time
from openai import OpenAI
import google.generativeai as genai
from app.utils.prompt_builder import PromptBuilder


logger = logging.getLogger(__name__)


class LLMService:
    """Service class for handling LLM API calls"""
    
    def __init__(self):
        self.prompt_builder = PromptBuilder()
    
    def call_openai(self, api_key, system_prompt, user_text, prompting_strategy):
        """Call OpenAI GPT model"""
        if not user_text:
            logger.warning("call_openai: empty user_text provided")
        start_time = time.time()
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        logger.debug(
            "call_openai: strategy=%s, user_text_len=%d, prompt_len=%d",
            prompting_strategy,
            len(user_text or ""),
            len(prompt or ""),
        )
        client = OpenAI(api_key=api_key)

        try:
            logger.info("Calling OpenAI chat.completions (model=gpt-4o)")
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                model="gpt-4o",
                max_tokens=4096
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
    
    def call_gemini(self, api_key, system_prompt, user_text, prompting_strategy):
        """Call Google Gemini model"""
        if not user_text:
            logger.warning("call_gemini: empty user_text provided")
        start_time = time.time()
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        logger.debug(
            "call_gemini: strategy=%s, user_text_len=%d, prompt_len=%d",
            prompting_strategy,
            len(user_text or ""),
            len(prompt or ""),
        )

        genai.configure(api_key=api_key)

        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            system_instruction=system_prompt
        )

        try:
            logger.info("Calling Gemini generate_content (model=gemini-1.5-pro)")
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0,
                    top_k=1,
                    top_p=1.0,
                    max_output_tokens=2048
                )
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
