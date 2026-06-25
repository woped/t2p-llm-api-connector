"""Central registry of supported providers and model discovery.

This is the single source of truth used by both:

* ``GET /models`` — to advertise the available provider/model pairs, and
* ``POST /generate`` — to validate the requested provider and to decide which
    ``LLMService`` method handles the call.

Keeping the registry here (instead of inline in the routes) means the advertised
list and the accepted list can never drift apart.
"""

import logging
import os
import urllib.error
import urllib.request

import google.generativeai as genai
from openai import OpenAI

logger = logging.getLogger(__name__)

# Fallback entries used only when provider discovery is unavailable.
_FALLBACK_MODELS = {
    "openai": ["gpt-5-mini"],
    "gemini": ["gemini-2.0-flash"],
}

# Maps a provider to the LLMService method name that dispatches the call.
_DISPATCH = {
    "openai": "call_openai",
    "gemini": "call_gemini",
}

_MODEL_CACHE = {
    "openai": list(_FALLBACK_MODELS.get("openai", [])),
    "gemini": list(_FALLBACK_MODELS.get("gemini", [])),
}


def _supported_providers():
    return tuple(_DISPATCH.keys())


def _provider_env_api_key(provider):
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY")
    if provider == "gemini":
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return None


def _provider_env_host(provider):
    if provider == "openai":
        return os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_HOST")
    if provider == "gemini":
        return os.getenv("GEMINI_API_ENDPOINT") or os.getenv("GEMINI_HOST")
    return None


def _discover_openai_models(api_key, base_url=None):
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    models = client.models.list()
    return sorted({item.id for item in models.data if getattr(item, "id", None)})


def _discover_gemini_models(api_key, api_endpoint=None):
    kwargs = {"api_key": api_key}
    if api_endpoint:
        kwargs["client_options"] = {"api_endpoint": api_endpoint}
    genai.configure(**kwargs)
    discovered = []
    for item in genai.list_models():
        methods = getattr(item, "supported_generation_methods", []) or []
        if "generateContent" not in methods:
            continue
        name = getattr(item, "name", "") or ""
        discovered.append(name.removeprefix("models/"))
    return sorted(set(filter(None, discovered)))


def discover_models(provider, api_key=None):
    """Best-effort provider-backed model discovery with fallback."""
    if provider not in _supported_providers():
        return []

    resolved_api_key = api_key or _provider_env_api_key(provider)
    resolved_host = _provider_env_host(provider)
    if not resolved_api_key:
        return list(_FALLBACK_MODELS.get(provider, []))

    try:
        if provider == "openai":
            return _discover_openai_models(resolved_api_key, base_url=resolved_host)
        if provider == "gemini":
            return _discover_gemini_models(
                resolved_api_key,
                api_endpoint=resolved_host,
            )
    except Exception as exc:
        logger.warning("Model discovery failed for provider %s: %s", provider, exc)

    return list(_FALLBACK_MODELS.get(provider, []))


def refresh_model_cache(provider=None, api_key=None):
    """Refresh cached models for one provider or all supported providers.

    When *api_key* is supplied the discovery call uses that key instead of
    the environment key, so the cache always reflects what the caller's key
    can actually access.
    """
    providers = [provider] if provider else list(_supported_providers())
    for current_provider in providers:
        if current_provider not in _supported_providers():
            continue
        _MODEL_CACHE[current_provider] = discover_models(
            current_provider, api_key=api_key
        )
    return get_cached_models(provider=provider)


def get_cached_models(provider=None):
    """Return cached models as a flat list of dicts.

    Shape (matches the connector contract):
    ``[{"provider": str, "model": str}, ...]``
    """
    providers = [provider] if provider else list(_supported_providers())
    return [
        {"provider": current_provider, "model": model}
        for current_provider in providers
        for model in _MODEL_CACHE.get(current_provider, [])
    ]


def list_models(provider=None):
    """Backward-compatible cached model listing wrapper."""
    return get_cached_models(provider=provider)


def is_valid(provider, model):
    """Return True if provider is supported and model is in the current cache.

    The cache is refreshed with the request API key before this is called
    (see the /generate route), so it reflects the live model list.
    """
    if provider not in _supported_providers() or not model:
        return False
    cached = _MODEL_CACHE.get(provider, [])
    # If the cache is still only the static fallback sentinel, accept any
    # non-empty model name (discovery may have been skipped at startup).
    if cached == list(_FALLBACK_MODELS.get(provider, [])):
        return True
    return model in cached


def dispatch_method(provider):
    """Return the LLMService method name for a provider, or None if unknown."""
    return _DISPATCH.get(provider)


def _normalize_openai_probe_url(configured_host):
    raw = (configured_host or "https://api.openai.com/v1").strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    if raw.endswith("/models"):
        return raw
    return f"{raw}/models"


def _normalize_gemini_probe_url(configured_host):
    raw = (configured_host or "generativelanguage.googleapis.com").strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    if raw.endswith("/v1beta/models"):
        return raw
    if raw.endswith("/v1beta"):
        return f"{raw}/models"
    if raw.endswith("/models"):
        return raw
    return f"{raw}/v1beta/models"


def _probe_url(url, timeout_seconds):
    request = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return {
                "reachable": True,
                "http_status": int(getattr(response, "status", 200)),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": True,
            "http_status": int(getattr(exc, "code", 0) or 0),
            "error": None,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "http_status": None,
            "error": str(exc),
        }


def provider_connectivity(provider=None, timeout_seconds=5):
    """Probe provider hosts without secrets.

    A provider is considered reachable when a TCP/TLS/HTTP response is received,
    including 401/403 responses from unauthenticated calls.
    """
    providers = [provider] if provider else list(_supported_providers())
    for current_provider in providers:
        if current_provider not in _supported_providers():
            raise ValueError(f"Unsupported provider: {current_provider}")

    timeout_seconds = max(1, min(int(timeout_seconds), 30))

    diagnostics = []
    for current_provider in providers:
        host = _provider_env_host(current_provider)
        if current_provider == "openai":
            url = _normalize_openai_probe_url(host)
        else:
            url = _normalize_gemini_probe_url(host)

        probe = _probe_url(url, timeout_seconds=timeout_seconds)
        diagnostics.append(
            {
                "provider": current_provider,
                "url": url,
                "reachable": probe["reachable"],
                "http_status": probe["http_status"],
                "error": probe["error"],
            }
        )

    return diagnostics
