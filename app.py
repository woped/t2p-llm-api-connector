from flask import Flask, request, jsonify
from openai import OpenAI
import google.generativeai as genai
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


# === Shared Call Handler ===
def handle_model_call(model_runner, api_key, system_prompt, user_text, prompting_strategy):
    try:
        response_text = model_runner(api_key, system_prompt, user_text, prompting_strategy)
        
        # Clean and process JSON response
        cleaned_response = clean_json_response(response_text)
        
        # Always return as string (cleaned_response is always a string now)
        return jsonify({'message': cleaned_response})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === JSON Post-processing ===
def clean_json_response(response_text):
    """Clean and validate JSON response from AI models, returning a nicely formatted JSON string."""
    import json
    
    # Remove any markdown code blocks if present
    if response_text.startswith('```json') or response_text.startswith('```'):
        lines = response_text.split('\n')
        # Find the first line that starts with { and the last line that ends with }
        start_idx = 0
        end_idx = len(lines) - 1
        for i, line in enumerate(lines):
            if line.strip().startswith('{'):
                start_idx = i
                break
        for i in range(len(lines) - 1, -1, -1):
            if line.strip().endswith('}'):
                end_idx = i
                break
        response_text = '\n'.join(lines[start_idx:end_idx + 1])
    
    # Remove any leading/trailing whitespace
    response_text = response_text.strip()
    
    # Handle double-escaped JSON strings
    if response_text.startswith('"{') and response_text.endswith('}"'):
        try:
            # Remove outer quotes and unescape
            inner_json = response_text[1:-1]
            # Replace escaped quotes
            inner_json = inner_json.replace('\\"', '"')
            # Parse and reformat the JSON
            parsed_json = json.loads(inner_json)
            # Return as nicely formatted JSON string
            return json.dumps(parsed_json, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    
    # If the response is a JSON string (with escaped quotes), parse it
    if response_text.startswith('"') and response_text.endswith('"'):
        try:
            # First parse to get the actual JSON string
            parsed_string = json.loads(response_text)
            # Then parse the actual JSON
            parsed_json = json.loads(parsed_string)
            # Return as nicely formatted JSON string
            return json.dumps(parsed_json, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    
    # Try to parse as direct JSON
    try:
        parsed_json = json.loads(response_text)
        # Return as nicely formatted JSON string
        return json.dumps(parsed_json, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        # If parsing fails, return original response
        return response_text


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