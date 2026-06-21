"""Tests for the validation framework itself (not for any concrete check).

These assert the scaffold's contract: validators are aggregated, a non-empty
result raises ``ValidationError`` carrying every issue, and an empty registry is
a no-op pass-through.
"""

import pytest

from app.validation import (
    ValidationError,
    ValidationIssue,
    Validator,
    collect_issues,
    validate_model,
)


class _DummyValidator(Validator):
    name = "dummy"

    def __init__(self, issues):
        self._issues = list(issues)

    def validate(self, model):
        return list(self._issues)


def test_empty_registry_is_a_noop_passthrough():
    model = {"events": [], "tasks": [], "gateways": [], "flows": []}
    assert validate_model(model) is model


def test_collect_issues_aggregates_across_validators(monkeypatch):
    monkeypatch.setattr(
        "app.validation.registry.VALIDATORS",
        [
            _DummyValidator([ValidationIssue("a", "first")]),
            _DummyValidator([ValidationIssue("b", "second")]),
        ],
    )
    assert [issue.code for issue in collect_issues({})] == ["a", "b"]


def test_validate_model_raises_with_every_issue(monkeypatch):
    monkeypatch.setattr(
        "app.validation.registry.VALIDATORS",
        [
            _DummyValidator([ValidationIssue("a", "first")]),
            _DummyValidator([ValidationIssue("b", "second")]),
        ],
    )
    with pytest.raises(ValidationError) as exc_info:
        validate_model({})
    assert {issue.code for issue in exc_info.value.issues} == {"a", "b"}


def test_passing_validator_returns_model_unchanged(monkeypatch):
    monkeypatch.setattr("app.validation.registry.VALIDATORS", [_DummyValidator([])])
    model = {"ok": True}
    assert validate_model(model) is model
