"""H.5 - chain verification, and the CLI that runs it.

Decision 9 leans on this chain as "the only mechanism that survives the
superuser bypass - a superuser can edit a row but cannot make the chain
re-verify". That claim is only worth something if something actually
re-verifies, and only checks it can perform from the stored columns count: the
verifier gets the same row a superuser would leave behind, and has to notice.

**Verification is a pure function of the rows** (`verify_events`), with the
database reduced to a `SELECT`. That keeps every property testable without a
server, and it means the CLI is a transport rather than a place where checks can
hide.

**What it cannot detect, stated plainly.** A *truncated tail* leaves a chain
that is internally perfect - no hash chain detects that without an external
witness of the expected length, and this repo has none. What covers it is the
GRANT in `sql/07` (no DELETE, no TRUNCATE, to any role) plus the tripwire
triggers, which is Decision 9's own position: privilege separation is the
boundary, and the chain is tamper-evidence layered on top. The durable answer to
a real superuser is shipping this log out to a write-once sink, which `sql/07`
also says and which is not attempted here.

**Confidentiality.** `sql/07`'s RLS policy hides restricted documents from
`procurement_app`, so a verification run must connect as an identity entitled to
see them and set `app.allow_restricted` - "exactly as the confidentiality model
intends, and a chain walk that skipped rows would fail to verify rather than
pass quietly". The CLI sets it; a run that could not would report broken links
on every restricted stream.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .canonical import JsonObject, canonical_text
from .envelope import (
    EVENT_TYPES_V1,
    KNOWN_ENVELOPE_VERSIONS,
    build_preimage,
    digest_of,
    document_id_for_stream,
    format_recorded_at,
)
from .writer import AuditConnection

__all__ = [
    "ChainDefect",
    "ChainReport",
    "DefectKind",
    "StoredEvent",
    "main",
    "read_events",
    "read_streams",
    "verify_events",
    "verify_stream",
]


class DefectKind(StrEnum):
    """What a walk can find. Named rather than free text so a report is greppable.

    A `StrEnum` because these values are printed, matched in tests and would
    plausibly be logged as structured fields - all three want the member to *be*
    its own name.
    """

    HASH_MISMATCH = "hash_mismatch"
    BROKEN_LINK = "broken_link"
    SEQ_GAP = "seq_gap"
    BAD_GENESIS = "bad_genesis"
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    PAYLOAD_NOT_JSON = "payload_not_json"
    PAYLOAD_NOT_CANONICAL = "payload_not_canonical"


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """One `audit.event` row, as the verifier reads it.

    `payload` is deliberately absent. It is a generated column, and `sql/07`
    says it is "never used to reverify the hash: casting back through jsonb is
    exactly the round-trip H.2's own reasoning warns against trusting as a
    canonicalisation step". Not selecting it is how that stays true.
    """

    event_id: int
    seq: int
    prev_hash: bytes | None
    hash: bytes
    event_type: str
    actor: str
    payload_canonical: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ChainDefect:
    """One finding, with enough to locate the row it was found on.

    Both `seq` and `event_id`: `seq` is the chain position a reader thinks in,
    `event_id` is what a `WHERE` clause needs, and a report that gives only one
    of them costs whoever is holding the pager the translation.
    """

    kind: DefectKind
    seq: int
    event_id: int
    detail: str

    def __str__(self) -> str:
        return f"seq {self.seq} (event_id {self.event_id}): {self.kind} - {self.detail}"


@dataclass(frozen=True, slots=True)
class ChainReport:
    stream: str
    events: int
    defects: tuple[ChainDefect, ...]

    @property
    def ok(self) -> bool:
        return not self.defects


def verify_events(stream: str, rows: Sequence[StoredEvent]) -> ChainReport:
    """Recompute every digest and every link in `rows`, in `seq` order.

    Collects defects rather than raising on the first: a walk that stops at the
    first bad row hides every row after it, and "how far does the damage go" is
    the first question anyone asks. An empty stream is not a defect - the CLI
    walks every stream it finds, and a stream reported as failing because
    nothing has been written to it yet is how an operator learns to ignore this
    tool.
    """
    defects: list[ChainDefect] = []
    previous: StoredEvent | None = None

    for row in sorted(rows, key=lambda event: event.seq):
        payload = _check_payload(row, defects)

        if row.event_type not in EVENT_TYPES_V1:
            defects.append(
                ChainDefect(
                    DefectKind.UNKNOWN_EVENT_TYPE,
                    row.seq,
                    row.event_id,
                    f"{row.event_type!r} is not in C4's v1 taxonomy; either the CHECK was "
                    "widened without amending D-13, or a value was removed",
                )
            )

        defects.extend(_check_position(row, previous))
        if payload is not None:
            defects.extend(_check_digest(stream, row, payload))
        previous = row

    return ChainReport(stream=stream, events=len(rows), defects=tuple(defects))


def _check_payload(row: StoredEvent, defects: list[ChainDefect]) -> JsonObject | None:
    """Parse `payload_canonical`, and check it deserves the name.

    Returns `None` when the text will not parse, which is the one defect that
    makes the digest uncheckable - the walk carries on to the next row rather
    than aborting.

    **The canonicality check closes a gap D-13 leaves open.** The preimage
    embeds the *parsed* payload object, so any JSON text with the same parse
    produces the same digest: the exact bytes of `payload_canonical` are not
    covered by the hash, despite the column being named for being canonical.
    That is not a forgery risk by itself - the value is unchanged - but a column
    that has quietly stopped being canonical is one some later reader will hash
    directly, and by then the drift is historical and unfixable.
    """
    try:
        parsed = json.loads(row.payload_canonical)
    except ValueError as exc:
        defects.append(
            ChainDefect(
                DefectKind.PAYLOAD_NOT_JSON,
                row.seq,
                row.event_id,
                f"payload_canonical does not parse as JSON ({exc}); the generated `payload` "
                "column makes this unreachable through the DDL, so something wrote around it",
            )
        )
        return None

    if not isinstance(parsed, dict):
        defects.append(
            ChainDefect(
                DefectKind.PAYLOAD_NOT_JSON,
                row.seq,
                row.event_id,
                f"payload_canonical is a JSON {type(parsed).__name__}, not an object; "
                "D-13's preimage embeds an object",
            )
        )
        return None

    payload: JsonObject = parsed
    if canonical_text(payload) != row.payload_canonical:
        defects.append(
            ChainDefect(
                DefectKind.PAYLOAD_NOT_CANONICAL,
                row.seq,
                row.event_id,
                "payload_canonical is not the JCS form of its own value. The digest cannot "
                "see this, because D-13 hashes the parsed object rather than these bytes",
            )
        )
    return payload


def _check_position(row: StoredEvent, previous: StoredEvent | None) -> list[ChainDefect]:
    """Genesis, linkage and `seq` contiguity - the shape rather than the bytes.

    Contiguity is checked even though no constraint requires it. The DDL makes
    `seq` unique and zero exactly at genesis, so a writer that skipped a number
    would produce a chain that links correctly and numbers wrongly, and nothing
    else in the system would ever say so.
    """
    if previous is None:
        if row.prev_hash is not None or row.seq != 0:
            return [
                ChainDefect(
                    DefectKind.BAD_GENESIS,
                    row.seq,
                    row.event_id,
                    f"the first event in this stream has seq {row.seq} and "
                    f"{'a' if row.prev_hash else 'no'} parent; a chain starts at seq 0 with "
                    "prev_hash NULL, so its head is missing",
                )
            ]
        return []

    defects: list[ChainDefect] = []
    if row.prev_hash != previous.hash:
        defects.append(
            ChainDefect(
                DefectKind.BROKEN_LINK,
                row.seq,
                row.event_id,
                f"prev_hash {_hex(row.prev_hash)} does not name the preceding event "
                f"{previous.hash.hex()}",
            )
        )
    if row.seq != previous.seq + 1:
        defects.append(
            ChainDefect(
                DefectKind.SEQ_GAP,
                row.seq,
                row.event_id,
                f"seq jumps from {previous.seq} to {row.seq}",
            )
        )
    return defects


def _check_digest(stream: str, row: StoredEvent, payload: JsonObject) -> list[ChainDefect]:
    """Recompute the digest under every envelope version this code knows.

    A loop over one version today. It is a loop because D-13 section 3 promises
    per-version dispatch and `audit.event` stores no version, so the only way to
    identify a row's version is to find the one whose preimage reproduces its
    digest - which is sound precisely because `v` is inside the hash. See
    `envelope.KNOWN_ENVELOPE_VERSIONS`.
    """
    for version in KNOWN_ENVELOPE_VERSIONS:
        preimage = build_preimage(
            version=version,
            stream=stream,
            seq=row.seq,
            event_type=row.event_type,
            actor=row.actor,
            recorded_at=format_recorded_at(row.recorded_at),
            prev_hash=row.prev_hash,
            payload=payload,
        )
        if digest_of(preimage) == row.hash:
            return []

    return [
        ChainDefect(
            DefectKind.HASH_MISMATCH,
            row.seq,
            row.event_id,
            f"stored digest {row.hash.hex()} is not reproduced by any known envelope version "
            f"{KNOWN_ENVELOPE_VERSIONS}; this row's hashed fields have been altered",
        )
    ]


def _hex(value: bytes | None) -> str:
    return "NULL" if value is None else value.hex()


# --- reading rows --------------------------------------------------------------

_STREAMS_SQL = "SELECT DISTINCT stream FROM audit.event ORDER BY stream"

_EVENTS_SQL = """
SELECT event_id, seq, prev_hash, hash, event_type, actor, payload_canonical, recorded_at
  FROM audit.event WHERE stream = %s ORDER BY seq
"""


def read_streams(conn: AuditConnection) -> list[str]:
    cursor = conn.execute(_STREAMS_SQL)
    return [str(row[0]) for row in _rows(cursor)]


def read_events(conn: AuditConnection, stream: str) -> list[StoredEvent]:
    cursor = conn.execute(_EVENTS_SQL, (stream,))
    return [
        StoredEvent(
            event_id=int(row[0]),
            seq=int(row[1]),
            prev_hash=None if row[2] is None else bytes(row[2]),
            hash=bytes(row[3]),
            event_type=str(row[4]),
            actor=str(row[5]),
            payload_canonical=str(row[6]),
            recorded_at=row[7],
        )
        for row in _rows(cursor)
    ]


def _rows(cursor: Any) -> list[Any]:
    """Drain a cursor through `fetchone`.

    `AuditConnection` promises only `fetchone`, deliberately - the same minimal
    surface that lets `tests/test_audit_writer.py` assert the caller sequence
    against a stand-in with no driver installed. Paying for that here is the
    right side of the trade: audit chains are per document and short.
    """
    rows: list[Any] = []
    while (row := cursor.fetchone()) is not None:
        rows.append(row)
    return rows


def verify_stream(conn: AuditConnection, stream: str) -> ChainReport:
    return verify_events(stream, read_events(conn, stream))


# --- the CLI --------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Verify one stream, or every stream, and exit non-zero if any fails.

    The exit code is the interface. This runs from cron or from a release check,
    where nobody reads the output until it is already too late, so a verifier
    that prints "FAILED" and exits 0 has the longest possible time to detection
    of any failure mode available to it.
    """
    parser = argparse.ArgumentParser(
        prog="python -m procurement_agent.audit",
        description="Verify the audit.event hash chains (WP-H H.5, contract C4).",
    )
    parser.add_argument(
        "--dsn",
        required=True,
        help="PostgreSQL connection string. Use an identity entitled to read restricted "
        "documents: a walk that silently skipped rows would report broken links.",
    )
    parser.add_argument(
        "--stream",
        action="append",
        dest="streams",
        metavar="doc:ID",
        help="Verify only this stream. Repeatable. Defaults to every stream present.",
    )
    args = parser.parse_args(argv)

    # A stream that cannot exist would otherwise return zero rows and report OK,
    # which is the one output an operator must never get from a typo. Checked
    # before connecting, so the answer does not depend on reaching a server.
    for stream in args.streams or ():
        try:
            document_id_for_stream(stream)
        except ValueError as exc:
            print(exc)
            return 2

    # Imported here rather than at module scope so the verification logic above
    # stays importable without the `store` extra - see writer.AuditConnection.
    try:
        import psycopg
    except ImportError:  # pragma: no cover - depends on the install, not the code
        print("psycopg is not installed; install the `store` extra to run the verifier.")
        return 2

    failed = 0
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        # sql/07: the verifier runs as an operator identity that sets this,
        # "exactly as the confidentiality model intends".
        conn.execute("SET app.allow_restricted = 'true'")
        streams = args.streams or read_streams(conn)
        for stream in streams:
            report = verify_stream(conn, stream)
            status = "OK" if report.ok else "FAILED"
            print(f"{report.stream}: {status} ({report.events} events)")
            for defect in report.defects:
                print(f"  {defect}")
            if not report.ok:
                failed += 1

    if failed:
        print(f"{failed} of {len(streams)} stream(s) failed verification.")
    return 1 if failed else 0
