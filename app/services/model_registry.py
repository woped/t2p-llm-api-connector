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

import google.generativeai as genai
from openai import OpenAI

logger = logging.getLogger(__name__)

# Fallback entries used only when provider discovery is unavailable.
_FALLBACK_MODELS = {
    "openai": ["gpt-4o"],
    "gemini": ["gemini-1.5-pro"],
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


def _discover_openai_models(api_key):
    client = OpenAI(api_key=api_key)
    models = client.models.list()
    return sorted({item.id for item in models.data if getattr(item, "id", None)})


def _discover_gemini_models(api_key):
    genai.configure(api_key=api_key)
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
    if not resolved_api_key:
        return list(_FALLBACK_MODELS.get(provider, []))

    try:
        if provider == "openai":
            return _discover_openai_models(resolved_api_key)
        if provider == "gemini":
            return _discover_gemini_models(resolved_api_key)
    except Exception as exc:
        logger.warning("Model discovery failed for provider %s: %s", provider, exc)

    return list(_FALLBACK_MODELS.get(provider, []))


def refresh_model_cache(provider=None):
    """Refresh cached models for one provider or all supported providers.

    Discovery uses provider-specific environment keys so the cache can be warmed
    at startup and refreshed later without requiring per-request credentials.
    """
    providers = [provider] if provider else list(_supported_providers())
    for current_provider in providers:
        if current_provider not in _supported_providers():
            continue
        _MODEL_CACHE[current_provider] = discover_models(current_provider)
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
    """Return True if the provider is supported.

    Model-name validation is delegated to the provider so the connector can
    accept newly released models without code changes.
    """
    return provider in _supported_providers() and bool(model)


def dispatch_method(provider):
    """Return the LLMService method name for a provider, or None if unknown."""
    return _DISPATCH.get(provider)
