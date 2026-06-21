"""Validation of the process model the connector parses from the LLM.

A validator is just a function ``(model) -> list[str]`` that returns problem
messages (an empty list means it passed). Validators never mutate the model.
Add one to ``VALIDATORS``; ``validate_model`` runs them all and raises
``ValidationError`` with every problem found.
"""


class ValidationError(ValueError):
    """Raised when the model fails one or more validators."""


# Validators run in order. Empty for now -- add functions here as we decide
# which checks we want (e.g. referential integrity, single end event).
VALIDATORS = []


def validate_model(model):
    """Run all validators; raise ``ValidationError`` if any report a problem.

    Returns *model* unchanged on success so callers can validate inline.
    """
    issues = [problem for validator in VALIDATORS for problem in validator(model)]
    if issues:
        raise ValidationError("; ".join(issues))
    return model
