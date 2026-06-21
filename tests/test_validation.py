"""Tests for the validation runner (not for any concrete check)."""

import pytest

from app.validation import ValidationError, validate_model


def test_empty_registry_passes_through():
    model = {"events": [], "tasks": [], "gateways": [], "flows": []}
    assert validate_model(model) is model


def test_raises_with_every_problem(monkeypatch):
    monkeypatch.setattr(
        "app.validation.VALIDATORS",
        [lambda m: ["first"], lambda m: ["second"]],
    )
    with pytest.raises(ValidationError) as exc_info:
        validate_model({})
    assert "first" in str(exc_info.value) and "second" in str(exc_info.value)


def test_passing_validator_returns_model(monkeypatch):
    monkeypatch.setattr("app.validation.VALIDATORS", [lambda m: []])
    model = {"ok": True}
    assert validate_model(model) is model
