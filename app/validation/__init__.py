"""Process-model validation for LLM responses.

The connector validates the model it parses from the LLM before returning it.
Building blocks live in ``app.validation.base``; the runner and registry live in
``app.validation.registry``; concrete checks go in ``app.validation.validators``.

Typical use in the generate flow::

    from app.validation import validate_model, ValidationError

    try:
        validate_model(model)
    except ValidationError as exc:
        ...  # map exc.issues to an error response or a re-prompt
"""

from app.validation.base import ValidationError, ValidationIssue, Validator
from app.validation.registry import VALIDATORS, collect_issues, validate_model

__all__ = [
    "Validator",
    "ValidationIssue",
    "ValidationError",
    "VALIDATORS",
    "collect_issues",
    "validate_model",
]
