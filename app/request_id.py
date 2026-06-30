"""Per-request correlation id for traceable logs under concurrent load.

A request id is bound at the start of every request — taken from the inbound
``X-Request-ID`` header when an upstream caller (t2p-2.0) forwards one, otherwise
freshly minted — and surfaced three ways: every log record carries it (via
``RequestIdFilter``), the response echoes it on the ``X-Request-ID`` header, and
error bodies include it. It lives in a ``ContextVar`` so concurrent requests,
each handled in its own worker/thread, never read each other's id, and a single
id ties together the connector's and t2p-2.0's log lines for one user request.
"""

import logging
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"
# Sentinel for "no request bound" (e.g. startup logs). Kept short so log columns
# stay narrow.
NO_REQUEST_ID = "-"
# Cap an inbound, client-supplied id so a hostile/oversized header cannot bloat
# every log line.
_MAX_LENGTH = 128

_request_id_var = ContextVar("request_id", default=NO_REQUEST_ID)


def set_request_id(incoming=None):
    """Bind a request id for the current context and return it.

    Honours a non-empty *incoming* value (the forwarded ``X-Request-ID``),
    trimmed and length-capped; otherwise mints a fresh one.
    """
    request_id = (incoming or "").strip()[:_MAX_LENGTH] or uuid.uuid4().hex
    _request_id_var.set(request_id)
    return request_id


def get_request_id():
    """Return the id bound to the current context, or ``"-"`` outside a request."""
    return _request_id_var.get()


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every record as ``record.request_id``.

    Added to the log handler so the field is always present at format time, even
    for records emitted outside a request (where it is ``"-"``).
    """

    def filter(self, record):
        record.request_id = get_request_id()
        return True
