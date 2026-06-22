"""Central registry of supported provider/model pairs.

This is the single source of truth used by both:

* ``GET /models`` — to advertise the available provider/model pairs, and
* ``POST /generate`` — to validate the requested ``provider``/``model`` and to
  decide which ``LLMService`` method handles the call.

Keeping the registry here (instead of inline in the routes) means the advertised
list and the accepted list can never drift apart.
"""

# Each entry: provider key -> {model name -> capability metadata}.
#
# We list the current GPT-5.x / Gemini-3.x generations, but deliberately stay on
# the cost-effective *standard* tiers (mini / nano / flash) rather than the
# flagship Pro tiers, which are far more expensive than this connector's
# process-description workload needs. ``gpt-4o`` is the only legacy model kept,
# purely for backward compatibility.
#
# Capability metadata drives the request parameters in ``LLMService`` so we no
# longer rely on brittle model-name prefix heuristics:
#
# * ``supports_temperature`` — the GPT-5.x / o-series reasoning models reject
#   ``temperature`` (and sampling knobs); ``gpt-4o`` and the Gemini models still
#   accept them. With the OpenAI Responses API the token-limit parameter is
#   unified (``max_output_tokens``), so temperature is the only remaining split.
_REGISTRY = {
    "openai": {
        "gpt-5.5": {"supports_temperature": False},  # newest general-purpose standard
        "gpt-5.4-mini": {"supports_temperature": False},  # recommended default here
        "gpt-5.4-nano": {"supports_temperature": False},  # cheapest, high-volume
        "gpt-4o": {"supports_temperature": True},  # legacy, backward compatibility
    },
    "gemini": {
        "gemini-3.5-flash": {"supports_temperature": True},  # best price/performance
        "gemini-3.1-flash-lite": {"supports_temperature": True},  # cheapest
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
    ``[{"provider": str, "model": str}, ...]``
    """
    return [
        {"provider": provider, "model": model}
        for provider, models in _REGISTRY.items()
        for model in models
    ]


def is_valid(provider, model):
    """Return True if the given provider/model pair is supported."""
    return model in _REGISTRY.get(provider, {})


def supports_temperature(provider, model):
    """Return True if the model accepts a ``temperature`` (sampling) parameter.

    Reasoning models (GPT-5.x / o-series) reject it. Defaults to ``True`` for
    unknown pairs so the classic, widely-supported behaviour is the fallback;
    callers validate the pair against the registry first anyway.
    """
    return _REGISTRY.get(provider, {}).get(model, {}).get("supports_temperature", True)


def dispatch_method(provider):
    """Return the LLMService method name for a provider, or None if unknown."""
    return _DISPATCH.get(provider)
