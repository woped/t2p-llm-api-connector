"""Structured-output schema for the BPMN-JSON process model.

A single Pydantic definition of the process model the LLM must return. It is the
shared source of truth for *shape and type* correctness across both providers:

* OpenAI's Responses API consumes it via ``text_format=ProcessModel``
  (``responses.parse``), which compiles it into a strict JSON schema.
* Google's ``google-genai`` SDK consumes the same class as ``response_schema``
  together with ``response_mime_type="application/json"``.

Using one Pydantic model for both keeps the enforced ``type`` literals, field
names and nesting identical regardless of which provider answers.

Scope: this schema guarantees valid JSON, the exact element/flow field names and
the allowed ``type`` values (the case-sensitivity and "only return JSON" rules
the prompt used to police by hand). It deliberately does NOT encode the semantic
graph rules — exactly one start/end, connectivity, explicit splits/joins — which
no JSON schema can express; those remain in ``app.validation``.
"""

from typing import Literal

from pydantic import BaseModel


class Event(BaseModel):
    id: str
    type: Literal["startEvent", "endEvent"]
    name: str


class Task(BaseModel):
    id: str
    type: Literal["userTask", "serviceTask", "task"]
    name: str


class Gateway(BaseModel):
    id: str
    type: Literal["exclusiveGateway", "parallelGateway"]
    name: str


class Flow(BaseModel):
    id: str
    type: Literal["sequenceFlow"]
    source: str
    target: str


class ProcessModel(BaseModel):
    events: list[Event]
    tasks: list[Task]
    gateways: list[Gateway]
    flows: list[Flow]
