"""Central registry of supported provider/model pairs.

This is the single source of truth used by both:

* ``GET /models`` — to advertise the available provider/model pairs, and
* ``POST /generate`` — to validate the requested ``provider``/``model`` and to
  decide which ``LLMService`` method handles the call.

Keeping the registry here (instead of inline in the routes) means the advertised
list and the accepted list can never drift apart.
"""

# Each entry: provider key -> list of supported model names.
_REGISTRY = {
    "openai": ["gpt-4o"],
    "gemini": ["gemini-1.5-pro"],
}

# Maps a provider to the LLMService method name that dispatches the call.
_DISPATCH = {
    "openai": "call_openai",
    "gemini": "call_gemini",
}


def list_models():
    """Return the advertised models as a flat list of dicts.

    Shape (matches the connector contract):
    ``[{"provider": str, "model": str}, ...]``
    """
    return [
        {"provider": provider, "model": model}
        for provider, models in _REGISTRY.items()
        for model in models
    ]


def is_valid(provider, model):
    """Return True if the given provider/model pair is supported."""
    return model in _REGISTRY.get(provider, ())


def dispatch_method(provider):
    """Return the LLMService method name for a provider, or None if unknown."""
    return _DISPATCH.get(provider)
