import os
from app.utils import LLM_SYSTEM_PROMPT


# === Base Configuration ===
class BaseConfig:
    SYSTEM_PROMPT = LLM_SYSTEM_PROMPT
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "test-openai-key"
    GEMINI_API_KEY = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or "test-gemini-key"
    )
    TESTING = False
    WTF_CSRF_ENABLED = os.environ.get("WTF_CSRF_ENABLED") or False
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


# === Select Configuration Class Based on Environment ===
def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()

    if env == "production":
        return ProductionConfig
    elif env == "testing":
        return TestingConfig
    else:
        return DevelopmentConfig
