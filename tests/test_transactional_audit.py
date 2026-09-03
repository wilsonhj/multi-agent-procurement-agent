"""The service-level same-transaction boundary for business and audit writes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, LiteralString

import pytest

from procurement_agent.audit import AuditConnection, AuditEvent
from procurement_agent.services.transactional_audit import write_and_append_event


class _Cursor:
    def __init__(self, row: Any = None) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _Connection:
    def __init__(
        self,
        *,
        autocommit: bool = False,
        fail_business: bool = False,
        fail_audit: bool = False,
    ) -> None:
        self._autocommit = autocommit
        self.fail_business = fail_business
        self.fail_audit = fail_audit
        self.calls: list[tuple[str, Sequence[Any] | None]] = []
        self.commits = 0

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    def execute(self, query: LiteralString, params: Sequence[Any] | None = None) -> _Cursor:
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))
        if normalized == "INSERT BUSINESS ROW" and self.fail_business:
            raise RuntimeError("business insert failed")
        if normalized.startswith("INSERT INTO audit.event") and self.fail_audit:
            raise RuntimeError("audit insert failed")
        # The chain has no tip, so this is a genesis event.
        return _Cursor(None)

    def commit(self) -> None:
        self.commits += 1


def _business_write(conn: AuditConnection) -> str:
    conn.execute("INSERT BUSINESS ROW")
    return "claim-1"


def _call(conn: _Connection) -> tuple[str, AuditEvent]:
    return write_and_append_event(
        conn,
        write=_business_write,
        document_id="pv-doc-1",
        event_type="extraction",
        actor="vertical-slice",
        payload={"field": "nameplate_power", "claim_count": 1},
        recorded_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )


def test_the_business_write_precedes_the_audit_lock_tip_and_insert() -> None:
    conn = _Connection()

    result, event = _call(conn)

    statements = [query for query, _ in conn.calls]
    assert result == "claim-1"
    assert event.document_id == "pv-doc-1"
    assert statements[0] == "INSERT BUSINESS ROW"
    assert statements[1].startswith("SELECT pg_advisory_xact_lock")
    assert statements[2].startswith("SELECT seq, hash FROM audit.event")
    assert statements[3].startswith("INSERT INTO audit.event")


def test_the_boundary_never_commits_the_callers_transaction() -> None:
    conn = _Connection()

    _call(conn)

    assert conn.commits == 0


def test_autocommit_is_refused_before_the_business_write() -> None:
    conn = _Connection(autocommit=True)

    with pytest.raises(ValueError, match="before its audit record"):
        _call(conn)

    assert conn.calls == []


def test_a_failed_business_write_never_emits_an_audit_event() -> None:
    conn = _Connection(fail_business=True)

    with pytest.raises(RuntimeError, match="business insert failed"):
        _call(conn)

    assert [query for query, _ in conn.calls] == ["INSERT BUSINESS ROW"]


def test_a_failed_audit_append_propagates_without_committing() -> None:
    conn = _Connection(fail_audit=True)

    with pytest.raises(RuntimeError, match="audit insert failed"):
        _call(conn)

    assert conn.commits == 0
    assert conn.calls[0][0] == "INSERT BUSINESS ROW"
    assert conn.calls[-1][0].startswith("INSERT INTO audit.event")
