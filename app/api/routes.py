from flask import request, jsonify
from app.api import bp
from app.services.llm_service import LLMService
from config import get_config
import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Prometheus Metriken
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', ['method', 'endpoint'])
CALL_OPENAI_DURATION = Histogram('call_openai_duration_seconds', 'OpenAI call duration')


@bp.route('/call_openai', methods=['POST'])
def call_openai():
    """Call OpenAI GPT model"""
    start_time = time.time()
    try:
        data = request.get_json()
        config_class = get_config()
        config_instance = config_class()
        
        llm_service = LLMService()
        result = llm_service.call_openai(
            api_key=data.get('api_key'),
            system_prompt=data.get('system_prompt', config_instance.SYSTEM_PROMPT),
            user_text=data.get('user_text'),
            prompting_strategy=data.get('prompting_strategie', 'few_shot')
        )
        
        REQUEST_COUNT.labels(method='POST', endpoint='/call_openai', status='200').inc()
        return jsonify({'message': result})
        
    except Exception as e:
        REQUEST_COUNT.labels(method='POST', endpoint='/call_openai', status='500').inc()
        return jsonify({'error': str(e)}), 500
    finally:
        REQUEST_LATENCY.labels(method='POST', endpoint='/call_openai').observe(time.time() - start_time)


@bp.route('/call_gemini', methods=['POST'])
def call_gemini():
    """Call Google Gemini model"""
    start_time = time.time()
    try:
        data = request.get_json()
        config_class = get_config()
        config_instance = config_class()
        
        llm_service = LLMService()
        result = llm_service.call_gemini(
            api_key=data.get('api_key'),
            system_prompt=data.get('system_prompt', config_instance.SYSTEM_PROMPT),
            user_text=data.get('user_text'),
            prompting_strategy=data.get('prompting_strategie', 'few_shot')
        )
        
        REQUEST_COUNT.labels(method='POST', endpoint='/call_gemini', status='200').inc()
        return jsonify({'message': result})
        
    except Exception as e:
        REQUEST_COUNT.labels(method='POST', endpoint='/call_gemini', status='500').inc()
        return jsonify({'error': str(e)}), 500
    finally:
        REQUEST_LATENCY.labels(method='POST', endpoint='/call_gemini').observe(time.time() - start_time)


@bp.route('/_/_/echo')
def echo():
    """Health check endpoint"""
    REQUEST_COUNT.labels(method='GET', endpoint='/_/_/echo', status='200').inc()
    return jsonify(success=True)


@bp.route('/metrics')
def metrics():
    """Expose Prometheus metrics."""
    REQUEST_COUNT.labels(method='GET', endpoint='/metrics', status='200').inc()
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}
