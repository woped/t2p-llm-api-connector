"""Central registry of supported provider/model pairs.

This is the single source of truth used by both:

* ``GET /models`` — to advertise the available provider/model pairs, and
* ``POST /generate`` — to validate the requested ``provider``/``model`` and to
  decide which ``LLMService`` method handles the call.

Keeping the registry here (instead of inline in the routes) means the advertised
list and the accepted list can never drift apart.
"""

# Each entry: provider key -> list of supported model names.
#
# We list the current GPT-5.x / Gemini-3.x generations, but deliberately stay on
# the cost-effective *standard* tiers (mini / nano / flash) rather than the
# flagship Pro tiers, which are far more expensive than this connector's
# process-description workload needs. ``gpt-4o`` is the only legacy model kept,
# purely for backward compatibility.
#
# NOTE: the GPT-5.x models reject ``temperature`` and ``max_tokens`` and require
# ``max_completion_tokens`` instead; ``LLMService.call_openai`` handles that
# parameter split, so every model below works with the live dispatch.
_REGISTRY = {
    "openai": [
        "gpt-5.5",  # newest general-purpose standard model
        "gpt-5.4-mini",  # cost-effective, recommended default for this workload
        "gpt-5.4-nano",  # cheapest, high-volume / low-latency
        "gpt-4o",  # legacy, kept for backward compatibility
    ],
    "gemini": [
        "gemini-3.5-flash",  # newest flash tier, best price/performance
        "gemini-3.1-flash-lite",  # cheapest, high-volume / low-latency
    ],
}

# Maps a provider to the LLMService method name that dispatches the call.
_DISPATCH = {
    "openai": "call_openai",
    "gemini": "call_gemini",
}


def list_models():
    """Return the advertised models as a flat list of dicts.

    Shape (matches the connector contract / openapi.yaml):
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
