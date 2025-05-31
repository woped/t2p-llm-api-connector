from flask import Flask, request, jsonify
from openai import OpenAI
from config.settings import FEW_SHOT_TEMPLATES, SYSTEM_PROMPT

app = Flask(__name__)

def run_openai(api_key, system_prompt, user_text):
    client = OpenAI(api_key=api_key)
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        temperature=0,
        model="gpt-4o",
        max_tokens=4096
    )
    return chat_completion.choices[0].message.content.strip()

def build_prompt_with_templates(user_input):
    prompt = ""
    for example in FEW_SHOT_TEMPLATES:
        prompt += f"Beschreibung:\n{example['description']}\n\n"
        prompt += f"BPMN:\n{example['bpmn']}\n\n"
    prompt += f"Beschreibung:\n{user_input}\n\nBPMN:\n"
    return prompt

@app.route('/call_openai', methods=['POST'])
def call_openai():
    data = request.get_json()
    api_key = data.get('api_key')
    user_text = data.get('user_text')

    try:
        # Few-Shot Prompt generieren
        prompt = build_prompt_with_templates(user_text)

        # OpenAI anfragen
        response_text = run_openai(api_key, SYSTEM_PROMPT, prompt)
        print("AI Response:", response_text)  # Optionales Logging
        return jsonify({'message': response_text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/_/_/echo')
def echo():
    return jsonify(success=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0')
