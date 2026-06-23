"""Validation of the process model the connector parses from the LLM.

A validator is a function ``(model) -> list[str]`` returning problem messages
(an empty list means it passed). Validators never mutate the model. Register one
in ``VALIDATORS``; ``validate_model`` runs them all and raises ``ValidationError``
with every problem found.

The checks enforce what a WoPeD workflow net requires and what the BPMN->PNML
transformer can represent. Shape and type correctness (valid JSON, known element
types) is the connector's structured-output concern and is not re-checked here.
"""

_NODE_GROUPS = ("events", "tasks", "gateways")


class ValidationError(ValueError):
    """Raised when the model fails one or more validators."""


# --- helpers --------------------------------------------------------------


def _nodes(model):
    return [el for group in _NODE_GROUPS for el in model.get(group, [])]


def _node_ids(model):
    return {node.get("id") for node in _nodes(model)}


def _events_of_type(model, event_type):
    return [e for e in model.get("events", []) if e.get("type") == event_type]


def _adjacency(model, from_key, to_key):
    adjacency = {}
    for flow in model.get("flows", []):
        adjacency.setdefault(flow.get(from_key), []).append(flow.get(to_key))
    return adjacency


def _reachable(starts, adjacency):
    seen, stack = set(), list(starts)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    return seen


# --- checks ---------------------------------------------------------------


def check_flow_references(model):
    """Every flow endpoint must be an existing node."""
    node_ids = _node_ids(model)
    return [
        f"Flow '{flow.get('id')}' references unknown node '{flow.get(end)}'."
        for flow in model.get("flows", [])
        for end in ("source", "target")
        if flow.get(end) not in node_ids
    ]


def check_unique_ids(model):
    """Every element id (node or flow) must be unique."""
    seen, duplicates = set(), []
    for element in _nodes(model) + list(model.get("flows", [])):
        element_id = element.get("id")
        if element_id in seen:
            duplicates.append(element_id)
        else:
            seen.add(element_id)
    return [f"Duplicate element id '{dup}'." for dup in dict.fromkeys(duplicates)]


def check_single_start_and_end(model):
    """A workflow net has exactly one start event and exactly one end event."""
    issues = []
    starts = _events_of_type(model, "startEvent")
    ends = _events_of_type(model, "endEvent")
    if len(starts) != 1:
        issues.append(
            f"Process must have exactly one start event, found {len(starts)}."
        )
    if len(ends) != 1:
        issues.append(f"Process must have exactly one end event, found {len(ends)}.")
    return issues


def check_event_flow_direction(model):
    """Start events take no incoming flow; end events take no outgoing flow."""
    start_ids = {e.get("id") for e in _events_of_type(model, "startEvent")}
    end_ids = {e.get("id") for e in _events_of_type(model, "endEvent")}
    issues = []
    for flow in model.get("flows", []):
        if flow.get("target") in start_ids:
            issues.append(f"Start event '{flow.get('target')}' has an incoming flow.")
        if flow.get("source") in end_ids:
            issues.append(f"End event '{flow.get('source')}' has an outgoing flow.")
    return issues


def check_no_self_loops(model):
    """A flow may not connect a node to itself."""
    return [
        f"Flow '{flow.get('id')}' connects node '{flow.get('source')}' to itself."
        for flow in model.get("flows", [])
        if flow.get("source") is not None and flow.get("source") == flow.get("target")
    ]


def check_connectivity(model):
    """Every node must be reachable from the start and able to reach the end."""
    start_ids = {e.get("id") for e in _events_of_type(model, "startEvent")}
    end_ids = {e.get("id") for e in _events_of_type(model, "endEvent")}
    if not start_ids or not end_ids:
        return []  # a missing start/end is reported by check_single_start_and_end
    reachable = _reachable(start_ids, _adjacency(model, "source", "target"))
    co_reachable = _reachable(end_ids, _adjacency(model, "target", "source"))
    issues = []
    for node_id in _node_ids(model):
        if node_id not in reachable:
            issues.append(f"Node '{node_id}' is not reachable from the start event.")
        if node_id not in co_reachable:
            issues.append(f"Node '{node_id}' cannot reach the end event.")
    return issues


def check_explicit_splits(model):
    """A split (more than one outgoing flow) must go through a gateway.

    The message names the offending flows and the exact repair so a regeneration
    can act on it directly instead of guessing where the gateway belongs.
    """
    gateway_ids = {g.get("id") for g in model.get("gateways", [])}
    outgoing = {}
    for flow in model.get("flows", []):
        outgoing.setdefault(flow.get("source"), []).append(flow.get("id"))
    issues = []
    for node in _nodes(model):
        node_id = node.get("id")
        flows = [f for f in outgoing.get(node_id, []) if f]
        if node_id not in gateway_ids and len(flows) > 1:
            flow_list = ", ".join(flows)
            issues.append(
                f"Node '{node_id}' has multiple outgoing flows ({flow_list}); a split "
                "must use a gateway. Insert one exclusiveGateway (XOR) or "
                f"parallelGateway (AND) whose single incoming flow comes from "
                f"'{node_id}' and re-route {flow_list} to start at that gateway."
            )
    return issues


def check_explicit_joins(model):
    """A join (more than one incoming flow) must go through a gateway.

    The message names the offending flows and the exact repair so a regeneration
    can act on it directly instead of guessing where the gateway belongs.
    """
    gateway_ids = {g.get("id") for g in model.get("gateways", [])}
    incoming = {}
    for flow in model.get("flows", []):
        incoming.setdefault(flow.get("target"), []).append(flow.get("id"))
    issues = []
    for node in _nodes(model):
        node_id = node.get("id")
        flows = [f for f in incoming.get(node_id, []) if f]
        if node_id not in gateway_ids and len(flows) > 1:
            flow_list = ", ".join(flows)
            issues.append(
                f"Node '{node_id}' has multiple incoming flows ({flow_list}); a join "
                "must use a gateway. Insert one exclusiveGateway (XOR) or "
                f"parallelGateway (AND), re-route {flow_list} to target that gateway, "
                f"and add one new flow from that gateway to '{node_id}'."
            )
    return issues


VALIDATORS = [
    check_flow_references,
    check_unique_ids,
    check_single_start_and_end,
    check_event_flow_direction,
    check_no_self_loops,
    check_connectivity,
    check_explicit_splits,
    check_explicit_joins,
]


def validate_model(model):
    """Run all validators; raise ``ValidationError`` if any report a problem.

    Returns *model* unchanged on success so callers can validate inline.
    """
    issues = [problem for validator in VALIDATORS for problem in validator(model)]
    if issues:
        raise ValidationError("; ".join(issues))
    return model
