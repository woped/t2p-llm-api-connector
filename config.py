import os
from app.utils import LLM_SYSTEM_PROMPT


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


# === Base Configuration ===
class BaseConfig:
    SYSTEM_PROMPT = LLM_SYSTEM_PROMPT
    TESTING = False
    WTF_CSRF_ENABLED = os.environ.get("WTF_CSRF_ENABLED") or False
    SECRET_KEY = (
        os.environ.get("SECRET_KEY")
        or "fj92348759t182htpoihf9sd8gu98341hrpasdhuq8gpsiodfh9823r"
    )

    # --- Internal async generation (job submit + poll) ---
    # The long LLM generation runs in a background thread; its state is shared
    # across gunicorn workers via Redis (container-local by default).
    REDIS_HOST = os.environ.get("REDIS_HOST") or "127.0.0.1"
    REDIS_PORT = int(os.environ.get("REDIS_PORT") or 6379)
    REDIS_DB = int(os.environ.get("REDIS_DB") or 0)
    REDIS_URL = os.environ.get("REDIS_URL") or (
        f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    )
    # When true, use an in-memory/fakeredis backend instead of a real Redis
    # (dev/test convenience). Production runs a real Redis in the container.
    REDIS_USE_MOCK = _env_bool("REDIS_USE_MOCK", default=False)
    INTERNAL_ASYNC_ENABLED = _env_bool("INTERNAL_ASYNC_ENABLED", default=True)
    ASYNC_JOB_TTL_SECONDS = int(os.environ.get("ASYNC_JOB_TTL_SECONDS") or 3600)


# === Development Configuration ===
class DevelopmentConfig(BaseConfig):
    DEBUG = True
    # No real Redis needed for local dev.
    REDIS_USE_MOCK = _env_bool("REDIS_USE_MOCK", default=True)


# === Production Configuration ===
class ProductionConfig(BaseConfig):
    DEBUG = False


# === Testing Configuration ===
class TestingConfig(BaseConfig):
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False
    # Tests must never reach for a real Redis.
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
