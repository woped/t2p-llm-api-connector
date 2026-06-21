"""Building blocks for validating a decoded LLM process model.

A *validator* inspects the decoded model (the dict the connector parses from the
LLM's reply) and reports problems as ``ValidationIssue`` objects. Validators are
stateless, never mutate the model, and never raise for an invalid model -- they
return their issues so the runner can collect every problem in a single pass.
Only the runner turns a non-empty issue list into a raised ``ValidationError``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationIssue:
    """A single problem found in a process model.

    code:    stable, machine-readable identifier (e.g. ``unknown_node_reference``)
    message: human-readable description, safe to log or return to the caller
    """

    code: str
    message: str


class ValidationError(Exception):
    """Raised when a model fails validation; carries every collected issue."""

    def __init__(self, issues):
        self.issues = list(issues)
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        super().__init__(summary or "Process model failed validation.")


class Validator(ABC):
    """One independent check over a decoded process model.

    Implementations are stateless and side-effect free: given a model, return the
    issues they find. An empty list means the check passed.
    """

    #: stable name for logging / metrics; override per validator
    name = "validator"

    @abstractmethod
    def validate(self, model):
        """Return a list of ``ValidationIssue`` for *model* (empty if valid)."""
        raise NotImplementedError
