from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)
# app.config['APPLICATION_ROOT'] = '/llm-api-connector'

@app.route('/call_openai', methods=['POST'])
def call_openai():
    data = request.get_json()
    api_key = data.get('api_key')
    system_prompt = data.get('system_prompt')
    user_text = data.get('user_text')

    # Create the OpenAI client with the API key provided in the request
    client = OpenAI(api_key=api_key)
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0,
            model="gpt-4o",
            max_tokens=4096
        )
        response_text = chat_completion.choices[0].message.content.strip()
        print("AI Response:", response_text)  # Debug print
        return jsonify({'message': response_text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/_/_/echo')
def echo():
    return jsonify(success=True)


if __name__ == '__main__':
    app.run(host='0.0.0.0')