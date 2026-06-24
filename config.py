import os

from app.utils import LLM_SYSTEM_PROMPT


def _env_bool(name, default=False):
    """Parse common truthy/falsey string values from environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# === Base Configuration ===
class BaseConfig:
    SYSTEM_PROMPT = LLM_SYSTEM_PROMPT
    # Optional provider hosts/base URLs (useful for proxies, gateways, or
    # enterprise endpoints).
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_HOST")
    GEMINI_API_ENDPOINT = os.environ.get("GEMINI_API_ENDPOINT") or os.environ.get(
        "GEMINI_HOST"
    )
    TESTING = False
    WTF_CSRF_ENABLED = _env_bool("WTF_CSRF_ENABLED", default=False)
    SECRET_KEY = (
        os.environ.get("SECRET_KEY")
        or "fj92348759t182htpoihf9sd8gu98341hrpasdhuq8gpsiodfh9823r"
    )


# === Development Configuration ===
class DevelopmentConfig(BaseConfig):
    DEBUG = True


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


# === Select Configuration Class Based on Environment ===
def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()

    if env == "production":
        return ProductionConfig
    elif env == "testing":
        return TestingConfig
    else:
        return DevelopmentConfig
