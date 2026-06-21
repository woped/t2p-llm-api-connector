"""Tests for the individual process-model validators (test-driven).

The baseline ``_valid_model`` must pass every check and the aggregate runner;
each other test breaks exactly one rule and asserts that the matching validator
reports it.
"""

from app.validation import (
    check_connectivity,
    check_event_flow_direction,
    check_explicit_joins,
    check_explicit_splits,
    check_flow_references,
    check_gateway_types,
    check_no_self_loops,
    check_single_start_and_end,
    check_unique_ids,
    validate_model,
)


def _valid_model():
    """A fully-valid workflow with an explicit XOR split and join:
    start -> t1 -> g1 -<t2, t3>-> g2 -> end."""
    return {
        "events": [
            {"id": "start", "type": "startEvent", "name": "Start"},
            {"id": "end", "type": "endEvent", "name": "End"},
        ],
        "tasks": [
            {"id": "t1", "type": "userTask", "name": "Do A"},
            {"id": "t2", "type": "userTask", "name": "Do B"},
            {"id": "t3", "type": "userTask", "name": "Do C"},
        ],
        "gateways": [
            {"id": "g1", "type": "exclusiveGateway", "name": "Split"},
            {"id": "g2", "type": "exclusiveGateway", "name": "Join"},
        ],
        "flows": [
            {"id": "f1", "type": "sequenceFlow", "source": "start", "target": "t1"},
            {"id": "f2", "type": "sequenceFlow", "source": "t1", "target": "g1"},
            {"id": "f3", "type": "sequenceFlow", "source": "g1", "target": "t2"},
            {"id": "f4", "type": "sequenceFlow", "source": "g1", "target": "t3"},
            {"id": "f5", "type": "sequenceFlow", "source": "t2", "target": "g2"},
            {"id": "f6", "type": "sequenceFlow", "source": "t3", "target": "g2"},
            {"id": "f7", "type": "sequenceFlow", "source": "g2", "target": "end"},
        ],
    }


_ALL_CHECKS = (
    check_flow_references,
    check_unique_ids,
    check_single_start_and_end,
    check_event_flow_direction,
    check_no_self_loops,
    check_connectivity,
    check_explicit_splits,
    check_explicit_joins,
    check_gateway_types,
)


# --- the valid baseline ---------------------------------------------------
def test_valid_model_passes_the_runner():
    model = _valid_model()
    assert validate_model(model) is model


def test_each_validator_accepts_the_valid_model():
    model = _valid_model()
    for check in _ALL_CHECKS:
        assert check(model) == [], f"{check.__name__} wrongly flagged the valid model"


# --- one broken rule per check -------------------------------------------
def test_flow_references_detects_unknown_node():
    model = _valid_model()
    model["flows"].append(
        {"id": "fx", "type": "sequenceFlow", "source": "t1", "target": "ghost"}
    )
    assert check_flow_references(model)


def test_unique_ids_detects_duplicate():
    model = _valid_model()
    model["tasks"].append({"id": "t1", "type": "userTask", "name": "Duplicate"})
    assert check_unique_ids(model)


def test_single_start_and_end_detects_extra_end():
    model = _valid_model()
    model["events"].append({"id": "end2", "type": "endEvent", "name": "End 2"})
    assert check_single_start_and_end(model)


def test_single_start_and_end_detects_missing_start():
    model = _valid_model()
    model["events"] = [e for e in model["events"] if e["type"] != "startEvent"]
    assert check_single_start_and_end(model)


def test_event_flow_direction_detects_incoming_to_start():
    model = _valid_model()
    model["flows"].append(
        {"id": "fx", "type": "sequenceFlow", "source": "t2", "target": "start"}
    )
    assert check_event_flow_direction(model)


def test_event_flow_direction_detects_outgoing_from_end():
    model = _valid_model()
    model["flows"].append(
        {"id": "fx", "type": "sequenceFlow", "source": "end", "target": "t1"}
    )
    assert check_event_flow_direction(model)


def test_no_self_loops_detects_self_loop():
    model = _valid_model()
    model["flows"].append(
        {"id": "fx", "type": "sequenceFlow", "source": "t1", "target": "t1"}
    )
    assert check_no_self_loops(model)


def test_connectivity_detects_orphan():
    model = _valid_model()
    model["tasks"].append({"id": "orphan", "type": "userTask", "name": "Orphan"})
    assert any("orphan" in issue for issue in check_connectivity(model))


def test_connectivity_detects_dead_end():
    model = _valid_model()
    model["tasks"].append({"id": "dead", "type": "userTask", "name": "Dead end"})
    model["flows"].append(
        {"id": "fx", "type": "sequenceFlow", "source": "start", "target": "dead"}
    )
    assert any("dead" in issue for issue in check_connectivity(model))


def test_explicit_splits_detects_task_fork():
    model = _valid_model()
    # t1 now forks to both g1 and end with no gateway in between.
    model["flows"].append(
        {"id": "fx", "type": "sequenceFlow", "source": "t1", "target": "end"}
    )
    assert check_explicit_splits(model)


def test_explicit_joins_detects_task_join():
    model = _valid_model()
    # A second arrow into "end" makes it an implicit join with no gateway.
    model["flows"].append(
        {"id": "fx", "type": "sequenceFlow", "source": "t2", "target": "end"}
    )
    assert check_explicit_joins(model)


def test_gateway_types_rejects_inclusive_or():
    model = _valid_model()
    model["gateways"][0]["type"] = "inclusiveGateway"
    assert check_gateway_types(model)
