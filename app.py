from flask import Flask, request, jsonify
from openai import OpenAI
import google.generativeai as genai
import json
from pathlib import Path

# === Load Few-Shot Templates ===
def load_few_shot_templates():
    template_path = Path(__file__).parent / "config" / "few_shot_templates.json"
    try:
        with open(template_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading few-shot templates: {e}")
        return []

FEW_SHOT_TEMPLATES = load_few_shot_templates()

# === Default System Prompt (can still be overridden via POST) ===
SYSTEM_PROMPT = """
You are an assistant for breaking down complex process descriptions into BPMN 2.0 elements. ...
(>> kürzen oder anpassen je nach Originalinhalt <<)
"""

app = Flask(__name__)

# === Prompt Builder ===
def build_prompt(strategy, user_input):
    if strategy == 'few_shot':
        sections = [
            f"Description:\n{example['description']}\n\nBPMN:\n{example['bpmn']}\n"
            for example in FEW_SHOT_TEMPLATES
            if 'description' in example and 'bpmn' in example
        ]
        sections.append(f"Description:\n{user_input}\n\nBPMN:\n")
        return "\n".join(sections)

    elif strategy == 'zero_shot':
        return f"Please generate a BPMN model for the following description:\n\n{user_input}\n\nBPMN:"

    else:
        raise ValueError(f"Unsupported prompting strategy: {strategy}")


# === OpenAI GPT Call ===
def run_openai(api_key, system_prompt, user_text, prompting_strategy):
    prompt = build_prompt(prompting_strategy, user_text)
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


# === Gemini Call ===
def run_gemini(api_key, system_prompt, user_text, prompting_strategy):
    prompt = build_prompt(prompting_strategy, user_text)

    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name="models/gemini-1.5-pro-latest",
        system_instruction=system_prompt
    )

    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.0,
            "top_k": 1,
            "top_p": 1.0,
            "max_output_tokens": 2048
        }
    )
    return response.text.strip()


# === Shared Call Handler ===
def handle_model_call(model_runner, api_key, system_prompt, user_text, prompting_strategy):
    try:
        response_text = model_runner(api_key, system_prompt, user_text, prompting_strategy)
        return jsonify({'message': response_text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === Flask Routes ===
@app.route('/call_openai', methods=['POST'])
def call_openai():
    data = request.get_json()
    return handle_model_call(
        run_openai,
        api_key=data.get('api_key'),
        system_prompt=data.get('system_prompt', SYSTEM_PROMPT),
        user_text=data.get('user_text'),
        prompting_strategy=data.get('prompting_strategie', 'few_shot')
    )


@app.route('/call_gemini', methods=['POST'])
def call_gemini():
    data = request.get_json()
    return handle_model_call(
        run_gemini,
        api_key=data.get('api_key'),
        system_prompt=data.get('system_prompt', SYSTEM_PROMPT),
        user_text=data.get('user_text'),
        prompting_strategy=data.get('prompting_strategie', 'few_shot')
    )


@app.route('/_/_/echo')
def echo():
    return jsonify(success=True)


if __name__ == '__main__':
    app.run(host='0.0.0.0')
