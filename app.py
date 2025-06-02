from flask import Flask, request, jsonify
from openai import OpenAI
from config.settings import FEW_SHOT_TEMPLATES

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
    sections = []

    for example in FEW_SHOT_TEMPLATES:
        section = (
            f"Beschreibung:\n{example['description']}\n\n"
            f"BPMN:\n{example['bpmn']}\n"
        )
        sections.append(section)

    sections.append(f"Beschreibung:\n{user_input}\n\nBPMN:\n")
    return "\n".join(sections)

@app.route('/call_openai', methods=['POST'])
def call_openai():
    data = request.get_json()
    api_key = data.get('api_key')
    system_prompt = data.get('system_prompt')
    user_text = data.get('user_text')

    if not api_key or not system_prompt or not user_text:
        return jsonify({'error': 'Missing required parameters'}), 400

    try:
        prompt = build_prompt_with_templates(user_text)
        response_text = run_openai(api_key, system_prompt, prompt)
        print("AI Response:", response_text) 
        return jsonify({'message': response_text})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/_/_/echo')
def echo():
    return jsonify(success=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0')
