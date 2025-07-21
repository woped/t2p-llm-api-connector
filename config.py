import os
from app.utils import LLM_SYSTEM_PROMPT

# === Base Configuration ===
class BaseConfig:
    SYSTEM_PROMPT = LLM_SYSTEM_PROMPT
    DEBUG = True
    TESTING = False
    WTF_CSRF_ENABLED = True 

# === Development Configuration ===
class DevelopmentConfig(BaseConfig):
    DEBUG = True
    WTF_CSRF_ENABLED = False

# === Production Configuration ===
class ProductionConfig(BaseConfig):
    DEBUG = False
    WTF_CSRF_ENABLED = True

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
