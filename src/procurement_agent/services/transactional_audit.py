"""Bind a business write and its audit event to one caller-owned transaction.

The audit package deliberately does not know what a business write is.  It can
lock a document stream and append a tamper-evident event, but the service that
changes canonical state must ensure both operations use the same connection.
This module is that narrow boundary.

It does not commit.  A successful call leaves both writes pending for the
caller's transaction context to commit; an exception lets that context roll
both back.  This is the invariant required by plan Decision 9: an audit record
must never survive a business write that did not happen.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ..audit import AuditConnection, AuditEvent, JsonObject, append_event

__all__ = ["write_and_append_event"]


def write_and_append_event[ResultT](
    conn: AuditConnection,
    *,
    write: Callable[[AuditConnection], ResultT],
    document_id: str,
    event_type: str,
    actor: str,
    payload: JsonObject,
    recorded_at: datetime,
) -> tuple[ResultT, AuditEvent]:
    """Execute ``write`` and append its audit event in the same transaction.

    ``write`` receives the exact connection later passed to ``append_event``.
    Requiring the callback to accept it, rather than merely closing over an
    arbitrary handle, makes the shared transaction visible in the signature and
    straightforward to test.

    The autocommit check happens before the business callback.  The audit writer
    would reject autocommit when taking its advisory lock, but discovering that
    only after the business statement ran would allow the statement to commit on
    its own with no audit record.  Refusing first closes that failure window.

    No exception is caught.  If either half fails, the caller's transaction
    context must roll back both; manufacturing an ``attempt_failed`` event is a
    separate transaction owned by the caller that handles the failure.
    """
    if conn.autocommit:
        raise ValueError(
            "business writes with audit events require autocommit=False; otherwise "
            "the business statement could commit before its audit record is appended"
        )

    result = write(conn)
    event = append_event(
        conn,
        document_id=document_id,
        event_type=event_type,
        actor=actor,
        payload=payload,
        recorded_at=recorded_at,
    )
    return result, event
