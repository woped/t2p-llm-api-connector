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
# * ``pricing`` — USD per 1,000,000 tokens, used to estimate per-call cost in the
#   logs (see ``estimate_cost``). Keys: ``input``, ``output`` and the optional
#   reduced ``cached_input`` rate. OpenAI rates are from openai.com/api pricing;
#   Gemini rates from Google's published API pricing. Gemini does not advertise a
#   separate cached-input rate here, so it is omitted (cached tokens, which this
#   connector rarely produces, then fall back to the standard input rate).
_REGISTRY = {
    "openai": {
        # newest general-purpose standard
        "gpt-5.5": {
            "supports_temperature": False,
            "pricing": {"input": 5.00, "cached_input": 0.50, "output": 30.00},
        },
        # recommended default here
        "gpt-5.4-mini": {
            "supports_temperature": False,
            "pricing": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
        },
        # cheapest, high-volume
        "gpt-5.4-nano": {
            "supports_temperature": False,
            "pricing": {"input": 0.20, "cached_input": 0.02, "output": 1.25},
        },
        # legacy, backward compatibility
        "gpt-4o": {
            "supports_temperature": True,
            "pricing": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
        },
    },
    "gemini": {
        # best price/performance
        "gemini-3.5-flash": {
            "supports_temperature": True,
            "pricing": {"input": 1.50, "output": 9.00},
        },
        # cheapest
        "gemini-3.1-flash-lite": {
            "supports_temperature": True,
            "pricing": {"input": 0.25, "output": 1.50},
        },
    },
}

# Maps a provider to the LLMService method name that dispatches the call.
_DISPATCH = {
    "openai": "call_openai",
    "gemini": "call_gemini",
}


def list_models():
    """Return the advertised models as a flat list of dicts.

    Shape (matches the connector contract / openapi.yaml)::

        [{"provider": str, "model": str,
          "supports_temperature": bool,
          "pricing": {"input": float, "output": float,
                      "cached_input": float?}}, ...]

    Each model carries its full registry metadata so a client can show pricing
    and parameter support without a second lookup. ``provider``/``model`` always
    come first; the remaining capability keys are spread from the registry entry,
    so any future metadata is advertised automatically. ``pricing`` is USD per
    1,000,000 tokens and ``cached_input`` is present only where a model offers a
    reduced cached-input rate.
    """
    return [
        {"provider": provider, "model": model, **meta}
        for provider, models in _REGISTRY.items()
        for model, meta in models.items()
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


def price(provider, model):
    """Return the per-1M-token pricing dict for a model, or None if unpriced."""
    return _REGISTRY.get(provider, {}).get(model, {}).get("pricing")


def _is_count(value):
    """True only for a real, non-boolean integer token count."""
    return isinstance(value, int) and not isinstance(value, bool)


def estimate_cost(provider, model, prompt_tokens, completion_tokens, cached_tokens=0):
    """Estimate the USD cost of a single call from its token counts.

    Returns ``None`` when the model has no registered pricing or the token counts
    are not real integers (e.g. an SDK that did not report usage), so callers can
    omit the cost cleanly instead of printing a bogus figure.

    Cached input tokens are billed at the model's reduced ``cached_input`` rate
    when one is known, otherwise at the standard ``input`` rate. Registry prices
    are USD per 1,000,000 tokens.
    """
    pricing = price(provider, model)
    if pricing is None or not (_is_count(prompt_tokens) and _is_count(completion_tokens)):
        return None
    cached = cached_tokens if _is_count(cached_tokens) else 0
    billable_input = max(prompt_tokens - cached, 0)
    cached_rate = pricing.get("cached_input", pricing["input"])
    cost = (
        billable_input * pricing["input"]
        + cached * cached_rate
        + completion_tokens * pricing["output"]
    ) / 1_000_000
    return cost
