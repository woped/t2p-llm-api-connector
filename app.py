from flask import Flask, request, jsonify
import openai
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

@app.route('/call_openai', methods=['POST'])
def call_openai():
    """Mapping route for OpenAI API call."""
    start_time = time.time()
    data = request.get_json()
    api_key = data.get('api_key')
    system_prompt = data.get('system_prompt')
    user_text = data.get('user_text')

    # Create the OpenAI client with the API key provided in the request
    client = openai.OpenAI(api_key=api_key)

    try:
        logger.info("OpenAI API call received")
        call_start_time = time.time()
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
        logger.info("AI Response: %s", response_text)
        CALL_OPENAI_DURATION.observe(time.time() - call_start_time)
        REQUEST_COUNT.labels(method='POST', endpoint='/call_openai', status='200').inc()
        return jsonify({'message': response_text})
    except Exception as e:
        logger.error("OpenAI API call failed", extra={"error": str(e)})
        REQUEST_COUNT.labels(method='POST', endpoint='/call_openai', status='500').inc()
        return jsonify({"error": str(e)}), 500
    finally:
        REQUEST_LATENCY.labels(method='POST', endpoint='/call_openai').observe(time.time() - start_time)

@app.route('/_/_/echo')
def echo():
    return jsonify(success=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0')
    