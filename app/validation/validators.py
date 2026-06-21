"""Concrete process-model validators.

Each validator subclasses ``app.validation.base.Validator`` and is registered in
``app.validation.registry.VALIDATORS``. None are implemented yet -- which checks
we actually want is decided separately. Add one here, for example::

    from app.validation.base import Validator, ValidationIssue


    class ReferentialIntegrity(Validator):
        name = "referential_integrity"

        def validate(self, model):
            node_ids = {n["id"] for group in ("events", "tasks", "gateways")
                        for n in model[group]}
            return [
                ValidationIssue(
                    "unknown_node_reference",
                    f"Flow '{flow['id']}' references unknown node '{flow[end]}'.",
                )
                for flow in model["flows"]
                for end in ("source", "target")
                if flow[end] not in node_ids
            ]

then append ``ReferentialIntegrity()`` to ``VALIDATORS`` in the registry.
"""
