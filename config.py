import os
from app.utils import BPMN_SYSTEM_PROMPT

# === Base Configuration ===
class BaseConfig:
    SYSTEM_PROMPT = BPMN_SYSTEM_PROMPT
    DEBUG = False
    TESTING = False 

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

# === Select Configuration Class Based on Environment ===
def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()

    if env == "production":
        return ProductionConfig
    elif env == "testing":
        return TestingConfig
    else:
        return DevelopmentConfig
