from flask import Flask, request, jsonify
import openai
import time
import logging
import sys
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger
import os

# Prometheus Metriken
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', ['method', 'endpoint'])
CALL_OPENAI_DURATION = Histogram('call_openai_duration_seconds', 'OpenAI call duration')

# Logging Setup
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Stdout handler with JSON formatter
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
stdout_handler.setFormatter(stdout_formatter)
logger.addHandler(stdout_handler)

app = Flask(__name__)

@app.before_request
def suppress_metrics_logging():
    """Suppress logging for /metrics endpoint to avoid log spam."""
    if request.path == '/metrics':
        app.logger.disabled = True

@app.after_request
def restore_logging(response):
    """Restore logging after request is processed."""
    app.logger.disabled = False
    return response

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
    