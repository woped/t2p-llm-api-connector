from openai import OpenAI
import google.generativeai as genai
from app.utils.prompt_builder import PromptBuilder


class LLMService:
    """Service class for handling LLM API calls"""
    
    def __init__(self):
        self.prompt_builder = PromptBuilder()
    
    def call_openai(self, api_key, system_prompt, user_text, prompting_strategy):
        """Call OpenAI GPT model"""
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        client = OpenAI(api_key=api_key)
        
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            model="gpt-4o",
            max_tokens=4096
        )
        return chat_completion.choices[0].message.content.strip()
    
    def call_gemini(self, api_key, system_prompt, user_text, prompting_strategy):
        """Call Google Gemini model"""
        prompt = self.prompt_builder.build_prompt(prompting_strategy, user_text)
        
        genai.configure(api_key=api_key)
        
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            system_instruction=system_prompt
        )
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,
                top_k=1,
                top_p=1.0,
                max_output_tokens=2048
            )
        )
        return response.text.strip()
