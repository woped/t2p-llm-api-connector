"""Central registry of supported provider/model pairs.

This is the single source of truth used by both:

* ``GET /models`` — to advertise the available provider/model pairs, and
* ``POST /generate`` — to validate the requested ``provider``/``model`` and to
  decide which ``LLMService`` method handles the call.

Keeping the registry here (instead of inline in the routes) means the advertised
list and the accepted list can never drift apart.
"""

# Each entry: provider key -> {model name -> is_default}.
# Exactly one (provider, model) pair should be marked as the default; it mirrors
# the legacy default used by t2p-2.0 (provider=openai, model=gpt-4o).
_REGISTRY = {
    "openai": {
        "gpt-4o": True,
    },
    "gemini": {
        "gemini-1.5-pro": False,
    },
}

# Maps a provider to the LLMService method name that dispatches the call.
_DISPATCH = {
    "openai": "call_openai",
    "gemini": "call_gemini",
}


def list_models():
    """Return the advertised models as a flat list of dicts.

    Shape (matches the connector contract / openapi.yaml):
    ``[{"provider": str, "model": str, "default": bool}, ...]``
    """
    models = []
    for provider, model_map in _REGISTRY.items():
        for model, is_default in model_map.items():
            models.append(
                {"provider": provider, "model": model, "default": bool(is_default)}
            )
    return models


def is_valid(provider, model):
    """Return True if the given provider/model pair is supported."""
    return model in _REGISTRY.get(provider, {})


def dispatch_method(provider):
    """Return the LLMService method name for a provider, or None if unknown."""
    return _DISPATCH.get(provider)
