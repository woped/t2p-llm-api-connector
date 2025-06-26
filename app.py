from flask import Flask, request, jsonify
from openai import OpenAI
import google.genai as genai
from config.config import get_config
import json
from pathlib import Path
import time
import logging
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger

# Prometheus Metriken
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', ['method', 'endpoint'])
CALL_OPENAI_DURATION = Histogram('call_openai_duration_seconds', 'OpenAI call duration')

class MetricsFilter(logging.Filter):
    def filter(self, record):
        if record.name == "werkzeug":
            return "/metrics" not in record.getMessage()
        try:
            return not request.path.startswith('/metrics')
        except RuntimeError:
            return True

logger = logging.getLogger()
logger.setLevel(logging.INFO)

werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.INFO)

metrics_filter = MetricsFilter()

console_handler = logging.StreamHandler()
console_handler.addFilter(metrics_filter)  # <- Filter aktiv

console_formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(console_formatter)

logger.addHandler(console_handler)
werkzeug_logger.addHandler(console_handler)

app = Flask(__name__)

@app.route('/metrics')
def metrics():
    """Expose Prometheus metrics."""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

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
SYSTEM_PROMPT= get_config().SYSTEM_PROMPT

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