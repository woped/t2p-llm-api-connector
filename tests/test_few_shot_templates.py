"""Guard: every shipped few-shot example must pass the connector's own validators.

Few-shot examples are the strongest signal the model imitates. If one violates
the rules ``app.validation`` enforces (single start/end, explicit split/join
gateways, connectivity, ...), it teaches the model to produce output the
connector then rejects — driving wasted regenerations. This test fails loudly,
naming the offending example, so a broken template can never ship again.
"""

import pytest

from app.utils.prompt_builder import PromptBuilder
from app.validation import ValidationError, validate_model

_TEMPLATES = PromptBuilder().few_shot_templates


def test_few_shot_templates_are_loaded():
    # A silent load failure degrades few-shot prompting to an empty example set;
    # guard against shipping zero templates as much as against broken ones.
    assert _TEMPLATES, "no few-shot templates loaded"


@pytest.mark.parametrize(
    "example",
    _TEMPLATES,
    ids=[ex.get("description", "")[:40] for ex in _TEMPLATES],
)
def test_few_shot_example_passes_validators(example):
    assert "bpmn" in example, "few-shot example is missing its 'bpmn' model"
    try:
        validate_model(example["bpmn"])
    except ValidationError as exc:
        pytest.fail(f"few-shot example violates the connector validators: {exc}")
