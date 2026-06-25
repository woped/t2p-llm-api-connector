import os
from pathlib import Path


def _load_system_prompt_from_txt():
    """Load system prompt text from the zero-shot prompt template file."""
    prompt_file = (
        Path(__file__).parent
        / "app"
        / "utils"
        / "zero-shot-prompts"
        / "00_zero_shot_prompt.txt"
    )
    try:
        return prompt_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _env_bool(name, default=False):
    """Parse common truthy/falsey string values from environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# === Base Configuration ===
class BaseConfig:
    SYSTEM_PROMPT = _load_system_prompt_from_txt()
    # Optional provider hosts/base URLs (useful for proxies, gateways, or
    # enterprise endpoints).
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_HOST")
    GEMINI_API_ENDPOINT = os.environ.get("GEMINI_API_ENDPOINT") or os.environ.get(
        "GEMINI_HOST"
    )
    TESTING = False
    WTF_CSRF_ENABLED = _env_bool("WTF_CSRF_ENABLED", default=False)
    REDIS_HOST = os.environ.get("REDIS_HOST") or "127.0.0.1"
    REDIS_PORT = int(os.environ.get("REDIS_PORT") or 6379)
    REDIS_DB = int(os.environ.get("REDIS_DB") or 0)
    REDIS_URL = os.environ.get("REDIS_URL") or (
        f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    )
    REDIS_USE_MOCK = _env_bool("REDIS_USE_MOCK", default=False)
    INTERNAL_ASYNC_ENABLED = _env_bool("INTERNAL_ASYNC_ENABLED", default=True)
    ASYNC_JOB_TTL_SECONDS = int(os.environ.get("ASYNC_JOB_TTL_SECONDS") or 3600)
    SECRET_KEY = (
        os.environ.get("SECRET_KEY")
        or "fj92348759t182htpoihf9sd8gu98341hrpasdhuq8gpsiodfh9823r"
    )


# === Development Configuration ===
class DevelopmentConfig(BaseConfig):
    DEBUG = True
    REDIS_USE_MOCK = _env_bool("REDIS_USE_MOCK", default=True)


# === Production Configuration ===
class ProductionConfig(BaseConfig):
    DEBUG = False


# === Testing Configuration ===
class TestingConfig(BaseConfig):
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "test-openai-key"
    GEMINI_API_KEY = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or "test-gemini-key"
    )
    REDIS_USE_MOCK = True


# === Select Configuration Class Based on Environment ===
def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()

    if env == "production":
        return ProductionConfig
    elif env == "testing":
        return TestingConfig
    else:
        return DevelopmentConfig
