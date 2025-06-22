from flask import Flask, request, jsonify
from openai import OpenAI
import google.generativeai as genai
from config.config import FEW_SHOT_TEMPLATES

app = Flask(__name__)

# === Prompt Builder ===

def build_prompt(strategy, user_input):
    if strategy == 'few_shot':
        sections = []
        for example in FEW_SHOT_TEMPLATES:
            sections.append(
                f"Description:\n{example['description']}\n\nBPMN:\n{example['bpmn']}\n"
            )
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


# === Shared Model Call Handler ===

def handle_model_call(model_runner, data):
    api_key = data.get('api_key')
    system_prompt = data.get('system_prompt')
    user_text = data.get('user_text')
    prompting_strategy = data.get('prompting_strategie', 'few_shot')

    if not api_key or not system_prompt or not user_text:
        return jsonify({'error': 'Missing required parameters'}), 400

    try:
        response_text = model_runner(api_key, system_prompt, user_text, prompting_strategy)
        return jsonify({'message': response_text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === Flask Routes ===

@app.route('/call_openai', methods=['POST'])
def call_openai():
    return handle_model_call(run_openai, request.get_json())

@app.route('/call_gemini', methods=['POST'])
def call_gemini():
    return handle_model_call(run_gemini, request.get_json())

@app.route('/_/_/echo')
def echo():
    return jsonify(success=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0')
