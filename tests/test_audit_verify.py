"""H.5 - what the chain verifier detects, and what it provably cannot.

Every test here runs against rows held in memory rather than against a server.
That is not a convenience: verification is a pure function of the stored
columns, and keeping it one means the property that "a superuser can edit a row
but cannot make the chain re-verify" (plan Decision 9) is checkable everywhere,
including in an environment with no database at all.

The last two tests are the honest half. A chain walk cannot detect a *truncated
tail*, and it cannot detect that non-canonical text was substituted for
canonical text carrying the same value - the second because D-13 hashes the
parsed payload object, so the stored bytes of `payload_canonical` are not
themselves covered by the digest. Both are asserted rather than argued, because
a limitation that only exists in a comment is one nobody knows they are relying
on.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import types
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from procurement_agent.audit import (
    ENVELOPE_VERSION,
    ChainTip,
    DefectKind,
    StoredEvent,
    build_event,
    build_preimage,
    digest_of,
    format_recorded_at,
    verify_events,
)
from procurement_agent.audit.verify import main as verify_main

STREAM = "doc:open-1"
RECORDED_AT = datetime(2026, 8, 6, 15, 4, 5, tzinfo=UTC)


def _chain(length: int = 3) -> list[StoredEvent]:
    """A well-formed chain of `length` events, built by the writer's own path."""
    stored: list[StoredEvent] = []
    tip: ChainTip | None = None
    for index in range(length):
        event = build_event(
            document_id="open-1",
            event_type="document_ingested" if index == 0 else "extraction",
            actor=f"worker-{index}",
            payload={"index": index, "value": 0.19},
            recorded_at=RECORDED_AT,
            tip=tip,
        )
        stored.append(
            StoredEvent(
                event_id=index + 1,
                seq=event.seq,
                prev_hash=event.prev_hash,
                hash=event.hash,
                event_type=event.event_type,
                actor=event.actor,
                payload_canonical=event.payload_canonical,
                recorded_at=event.recorded_at,
            )
        )
        tip = ChainTip(seq=event.seq, hash=event.hash)
    return stored


def _kinds(rows: list[StoredEvent]) -> set[DefectKind]:
    return {defect.kind for defect in verify_events(STREAM, rows).defects}


# --- the chain verifies when nothing has been touched --------------------------


def test_a_an_untouched_chain_verifies() -> None:
    report = verify_events(STREAM, _chain())
    assert report.ok
    assert report.events == 3
    assert report.defects == ()


def test_a_an_empty_stream_verifies_vacuously() -> None:
    """Zero events is not a defect, and saying so is not a formality.

    The verification CLI walks every stream it finds; a stream that reports
    "failed" because nothing has been written to it yet would train its operator
    to ignore failures, which is the only way this tool stops working.
    """
    report = verify_events(STREAM, [])
    assert report.ok
    assert report.events == 0


# --- each hashed field is actually covered by the digest -----------------------


#: One edit per field D-13 section 2 puts inside the preimage. Written as
#: callables rather than as (name, value) pairs so each is type-checked against
#: `StoredEvent` - a `**{name: value}` splat is exactly the construct that would
#: let a typo name a field that does not exist and still pass, by editing
#: nothing and then failing for the wrong reason.
HASHED_FIELD_EDITS = [
    ("actor", lambda row: dataclasses.replace(row, actor="someone-else")),
    ("event_type", lambda row: dataclasses.replace(row, event_type="resolution")),
    ("seq", lambda row: dataclasses.replace(row, seq=99)),
    (
        "recorded_at",
        lambda row: dataclasses.replace(
            row, recorded_at=datetime(2026, 8, 6, 15, 4, 6, tzinfo=UTC)
        ),
    ),
]


@pytest.mark.parametrize(
    ("field", "edit"), HASHED_FIELD_EDITS, ids=[e[0] for e in HASHED_FIELD_EDITS]
)
def test_a_editing_a_hashed_field_breaks_the_digest(
    field: str, edit: Callable[[StoredEvent], StoredEvent]
) -> None:
    """One case per field D-13 section 2 puts inside the preimage.

    Parameterised rather than written once because the failure being guarded
    against is a field quietly dropping *out* of the preimage - which no test of
    a single field would notice, and which the `...` in the sketch D-13 replaced
    made easy to do by accident.
    """
    rows = _chain()
    rows[1] = edit(rows[1])
    assert DefectKind.HASH_MISMATCH in _kinds(rows), f"{field} is not covered by the digest"


def test_a_editing_the_payload_breaks_the_digest() -> None:
    """The row content NFR-03 and NFR-02 both care about.

    `payload` is a generated column, so a tamperer has to go through
    `payload_canonical` - which is what the digest is recomputed from.
    """
    rows = _chain()
    tampered = json.loads(rows[1].payload_canonical)
    tampered["value"] = 0.11
    rows[1] = dataclasses.replace(
        rows[1], payload_canonical=json.dumps(tampered, separators=(",", ":"))
    )
    assert DefectKind.HASH_MISMATCH in _kinds(rows)


def test_a_the_recorded_at_round_trip_is_exact() -> None:
    """The hashed timestamp is a *string*; the column stores an *instant*.

    D-13 section 4 justifies pinning the format by two callers otherwise
    disagreeing. The stronger reason is this one: `recorded_at` is `timestamptz`,
    so the bytes that were hashed are not stored anywhere and the verifier has
    to reconstruct them from the instant. That is only possible because the
    format is a total function of the instant - which is what makes the pin
    load-bearing rather than tidy.
    """
    rows = _chain(1)
    assert format_recorded_at(rows[0].recorded_at) == "2026-08-06T15:04:05.000000Z"
    assert verify_events(STREAM, rows).ok


# --- the shape of the chain itself ---------------------------------------------


def test_a_a_broken_link_is_reported() -> None:
    """The linkage `audit_event_parent_exists` enforces at write time.

    Checked again here because the FK is enforced by a server that a superuser
    can also disable - Decision 9's whole argument for the chain is that it
    survives that, and it only survives it if something recomputes the link.
    """
    rows = _chain()
    rows[2] = dataclasses.replace(rows[2], prev_hash=bytes.fromhex("ff" * 32))
    assert DefectKind.BROKEN_LINK in _kinds(rows)


def test_a_a_seq_gap_is_reported() -> None:
    """`seq` is hashed, so a gap is a writer bug rather than tampering.

    The DDL constrains `seq` to be unique and to be zero exactly at genesis, but
    never to be contiguous. A writer that skipped a number would produce a chain
    that links correctly and numbers wrongly, and nothing else in the system
    would ever say so.
    """
    rows = _chain()
    rows[2] = _rehash(dataclasses.replace(rows[2], seq=7))
    assert DefectKind.SEQ_GAP in _kinds(rows)


def test_a_a_chain_that_does_not_start_at_genesis_is_reported() -> None:
    """A stream whose first row has a parent is a stream missing its head.

    Deleting the genesis row is the cheapest way to make a chain shorter, and
    every remaining link still verifies - so the *absence* has to be what is
    detected.
    """
    rows = _chain()[1:]
    assert DefectKind.BAD_GENESIS in _kinds(rows)


def test_a_an_event_type_outside_the_v1_taxonomy_is_reported() -> None:
    """D-13 section 5 forbids removing a value; this catches an addition, too.

    A row carrying a type this library does not know means either the CHECK was
    widened without amending D-13, or the row predates a removal that was not
    supposed to happen. Both are worth a line in the report.
    """
    rows = _chain()
    rows[1] = _rehash(dataclasses.replace(rows[1], event_type="workbook_composed"))
    assert DefectKind.UNKNOWN_EVENT_TYPE in _kinds(rows)


def test_a_non_canonical_payload_text_is_reported_even_though_it_still_hashes() -> None:
    """A gap in D-13, closed here rather than left implicit.

    D-13 embeds the *parsed* payload object in the preimage, so any JSON text
    with the same parse yields the same digest - meaning the exact bytes of
    `payload_canonical` are **not** covered by the hash, despite the column
    being named for being canonical. The digest below still matches; only the
    separate canonicality check notices.

    It is not a forgery risk on its own, since the value is unchanged. It is
    worth reporting because a column that has quietly stopped being canonical is
    a column some later reader will hash directly, and by then the drift is
    historical and unfixable.
    """
    rows = _chain()
    loosened = json.dumps(json.loads(rows[1].payload_canonical), separators=(", ", ": "))
    rows[1] = dataclasses.replace(rows[1], payload_canonical=loosened)

    kinds = _kinds(rows)
    assert DefectKind.PAYLOAD_NOT_CANONICAL in kinds
    assert DefectKind.HASH_MISMATCH not in kinds, (
        "the digest is computed over the parsed object, so it cannot see this"
    )


def test_a_payload_text_that_is_not_json_is_reported() -> None:
    """`payload jsonb` makes this unreachable through the DDL, which is the point.

    A row in this state means something wrote to the table without going through
    the generated column - so the verifier must report it rather than raise, or
    one corrupt row stops the walk and hides every row after it.
    """
    rows = _chain()
    rows[1] = dataclasses.replace(rows[1], payload_canonical="{not json")
    assert DefectKind.PAYLOAD_NOT_JSON in _kinds(rows)


def test_a_every_defect_names_the_row_it_was_found_on() -> None:
    """A report that says "failed" and not "where" costs an operator the walk.

    The chain can be long, and the row that fails is the row that was edited.
    """
    rows = _chain()
    rows[1] = dataclasses.replace(rows[1], actor="someone-else")
    (defect,) = verify_events(STREAM, rows).defects
    assert defect.seq == 1
    assert defect.event_id == 2


# --- what a chain walk provably cannot detect ----------------------------------


def test_a_a_truncated_tail_is_not_detectable_and_that_is_expected() -> None:
    """The limit of the mechanism, asserted so nobody has to rediscover it.

    Dropping the last N events leaves a chain that is internally perfect. No
    hash chain can detect this without an external witness of the expected
    length, and this repo has none. What covers it is the GRANT in `sql/07`
    (no DELETE, no TRUNCATE to any role) plus the tripwire triggers - which is
    Decision 9's own position that privilege separation is the boundary and the
    chain is tamper-*evidence* layered on top, not a replacement for it.
    """
    assert verify_events(STREAM, _chain()[:2]).ok


def test_a_the_cli_refuses_a_stream_that_cannot_exist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A typo must not come back as a clean bill of health.

    `--stream global` would otherwise select zero rows and report OK, which is
    the single worst output this tool can produce: it is indistinguishable from
    a verified chain, and it is what an operator would see after mistyping a
    document id. Checked before connecting, so this test needs no server - and
    so the answer never depends on reaching one.
    """
    assert verify_main(["--dsn", "postgresql:///unused", "--stream", "global"]) == 2
    assert "doc:" in capsys.readouterr().out


def _rehash(row: StoredEvent) -> StoredEvent:
    """Recompute a row's own digest after editing it, so it is self-consistent.

    Used where the point of the test is a *structural* defect rather than a
    digest one: without this the row would fail on `hash_mismatch` first and the
    test would pass for the wrong reason. It goes through `build_preimage`
    rather than `build_event` deliberately - this is a forger's path, not a
    writer's, and the writer must not grow a `seq` override or a taxonomy escape
    hatch merely so a test can take it.
    """
    preimage = build_preimage(
        version=ENVELOPE_VERSION,
        stream=STREAM,
        seq=row.seq,
        event_type=row.event_type,
        actor=row.actor,
        recorded_at=format_recorded_at(row.recorded_at),
        prev_hash=row.prev_hash,
        payload=json.loads(row.payload_canonical),
    )
    return dataclasses.replace(row, hash=digest_of(preimage))


# --- the CLI's "verified nothing" outputs ---------------------------------------


class _EmptyCursor:
    """Every query returns no rows - an empty log, or a stream that is not there."""

    def fetchone(self) -> None:
        return None


class _EmptyConn:
    def execute(self, query: object, params: object = None) -> _EmptyCursor:
        return _EmptyCursor()

    def __enter__(self) -> _EmptyConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def _empty_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reachable server holding nothing, injected as `psycopg`.

    `verify.main` imports psycopg inside the function so the module stays
    importable without the `store` extra, which is also what makes this
    substitutable without a database.
    """
    fake = types.ModuleType("psycopg")
    fake.connect = lambda *a, **k: _EmptyConn()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", fake)


def test_a_named_stream_that_is_not_there_is_a_failure_not_an_ok(
    _empty_server: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The half `test_a_stream_that_cannot_exist_is_refused` does not cover.

    That test's docstring names the hazard correctly - "what an operator would
    see after mistyping a document id" - but `document_id_for_stream` only
    validates the `doc:` **prefix**. Document ids are UUIDs, so the realistic
    typo is *inside* the id, which passes the prefix check, selects zero rows,
    and produced `OK (0 events)` with exit 0: the one output the comment above
    that check says an operator must never get.

    A cron pinned to a single document would report success forever.
    """
    code = verify_main(
        ["--dsn", "postgresql:///unused", "--stream", "doc:11111111-1111-4111-8111-111111111112"]
    )
    out = capsys.readouterr().out
    assert "OK" not in out, out
    assert code != 0


def test_an_empty_log_says_so_rather_than_printing_nothing(
    _empty_server: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no `--stream` and nothing discovered, `main` printed **nothing at
    all** and exited 0 - indistinguishable from a clean pass over a real log.

    Exit 0 stays: an empty log is a legitimate state for a fresh deployment, and
    failing CI on it would be wrong. What must change is the silence, because
    "I verified nothing" and "I verified everything and it was fine" had the
    same output.
    """
    code = verify_main(["--dsn", "postgresql:///unused"])
    out = capsys.readouterr().out
    assert out.strip(), "printed nothing at all"
    assert "no audit streams" in out.lower()
    assert code == 0
