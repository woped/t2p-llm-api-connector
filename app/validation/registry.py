"""Central registry and runner for process-model validators.

To add a check: implement a ``Validator`` in ``app.validation.validators`` and
append an instance to ``VALIDATORS`` below. ``validate_model`` runs every
registered validator and aggregates their issues; if any are found it raises a
single ``ValidationError`` carrying all of them. This is the only entry point the
generate flow needs in order to validate an LLM response.
"""

import logging

from app.validation.base import ValidationError

logger = logging.getLogger(__name__)

# Active validators, applied in order. Intentionally empty for now: which
# concrete checks we want (e.g. referential integrity, single end event) is
# decided separately and added here.
VALIDATORS = []


def collect_issues(model):
    """Run every registered validator and return all issues, without raising."""
    issues = []
    for validator in VALIDATORS:
        issues.extend(validator.validate(model))
    return issues


def validate_model(model):
    """Validate *model*; raise ``ValidationError`` if any issue is reported.

    Returns *model* unchanged on success so call sites can validate the decoded
    response inline. Validators never mutate the model.
    """
    issues = collect_issues(model)
    if issues:
        logger.info("Process model failed validation: %d issue(s)", len(issues))
        raise ValidationError(issues)
    return model
