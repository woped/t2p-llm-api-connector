import json
import threading
import time
import uuid

try:
    import redis
except ImportError:  # pragma: no cover - exercised in minimal runtime envs
    redis = None

try:
    import fakeredis
except ImportError:  # pragma: no cover - optional dev/test dependency
    fakeredis = None


class _InMemoryRedis:
    """Tiny Redis-like fallback for tests/dev when no Redis client is available."""

    def __init__(self):
        self._lock = threading.Lock()
        self._store = {}

    def setex(self, key, ttl, value):
        expires_at = time.time() + float(ttl)
        with self._lock:
            self._store[key] = (value, expires_at)

    def get(self, key):
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            value, expires_at = item
            if time.time() >= expires_at:
                self._store.pop(key, None)
                return None
            return value


class AsyncJobStore:
    """Redis-backed job storage for internal async generation workflows."""

    def __init__(
        self,
        redis_url,
        ttl_seconds=3600,
        key_prefix="llm_async_job",
        use_mock=False,
    ):
        self._redis = self._build_client(redis_url=redis_url, use_mock=use_mock)
        self._ttl = int(ttl_seconds)
        self._prefix = key_prefix

    @staticmethod
    def _build_client(redis_url, use_mock=False):
        if use_mock:
            if fakeredis is not None:
                return fakeredis.FakeStrictRedis(decode_responses=True)
            return _InMemoryRedis()

        if redis is None:
            raise RuntimeError("redis package is required for async job storage")

        try:
            return redis.Redis.from_url(redis_url, decode_responses=True)
        except Exception:
            # Local dev fallback: if explicitly enabled, continue with mock.
            if use_mock:
                if fakeredis is not None:
                    return fakeredis.FakeStrictRedis(decode_responses=True)
                return _InMemoryRedis()
            raise

    def _key(self, job_id):
        return f"{self._prefix}:{job_id}"

    def create(self):
        job_id = str(uuid.uuid4())
        now = time.time()
        payload = {
            "job_id": job_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": None,
        }
        self._redis.setex(self._key(job_id), self._ttl, json.dumps(payload))
        return job_id

    def get(self, job_id):
        raw = self._redis.get(self._key(job_id))
        if raw is None:
            return None
        return json.loads(raw)

    def update_status(self, job_id, status, *, result=None, error=None):
        payload = self.get(job_id)
        if payload is None:
            return False

        payload["status"] = status
        payload["updated_at"] = time.time()
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error

        self._redis.setex(self._key(job_id), self._ttl, json.dumps(payload))
        return True