"""Tests for the shared output schema.

The provider-native ``ProcessModel`` schema is the single source of truth for
element *types*. OR/inclusive gateways are excluded here, so the connector no
longer needs a separate ``check_gateway_types`` validator.
"""

import pytest
from pydantic import ValidationError

from app.schemas import ProcessModel


def _valid_payload():
    return {
        "events": [
            {"id": "start", "type": "startEvent", "name": "Start"},
            {"id": "end", "type": "endEvent", "name": "End"},
        ],
        "tasks": [{"id": "t1", "type": "userTask", "name": "Do A"}],
        "gateways": [{"id": "g1", "type": "exclusiveGateway", "name": "Split"}],
        "flows": [
            {"id": "f1", "type": "sequenceFlow", "source": "start", "target": "t1"},
        ],
    }


def test_schema_accepts_supported_gateway_types():
    ProcessModel.model_validate(_valid_payload())


def test_schema_rejects_inclusive_or_gateway():
    payload = _valid_payload()
    payload["gateways"][0]["type"] = "inclusiveGateway"
    with pytest.raises(ValidationError):
        ProcessModel.model_validate(payload)
