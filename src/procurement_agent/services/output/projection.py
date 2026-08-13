"""The canonical workbook projection - contract C6, frozen as D-14.

The whole store, plus the policy it is rendered under, reduced to one JSON
object whose SHA-256 is the artifact of record. `services.claims.project` is a
different projection (claims to canonical fields, contract C8); this one is the
projection AC-7's byte-identity claim is made about.

**Bytes.** UTF-8 output of `json.dumps(obj, sort_keys=True, ensure_ascii=False,
separators=(",", ":"), allow_nan=False)`. That is the "sorted-key JSON, floats
via `repr()`" already frozen in plan Decision 8c - Python's JSON encoder uses
`float.__repr__`, which distinguishes `0.1 + 0.2` from `0.3` where `'%.16g'`
collides them. `allow_nan=False` so a stray NaN is loud rather than silently
`NaN`, which is not JSON at all.

**Why not JCS**, when D-13 mandates it for the audit chain: ECMAScript number
rules collapse `650.0` to `650`, erasing the int/float distinction the store's
`value: object` genuinely carries. The two contracts want different things -
cross-language verifiability there, lossless Python round-trip here.

**Two properties this module exists to hold, both of which have been got wrong
before:**

*Policy is inside the hash.* The workbook is a function of *(store, policy)*, so
hashing only the store certifies AC-7 while the artifact silently varies with
configuration - the false-integrity claim C6 exists to prevent. The computed
`CellFlag`s go in as well as the threshold that produced them, because
`flags_for`'s code is policy too and a change to it would otherwise alter every
rendered workbook under an unchanged hash. This follows Bazel's action key, Nix's
input hashing and SLSA v1's `subject`/`externalParameters` split rather than
inventing a rule. The objection that re-tuning tau should not invalidate
historical hashes is a category error: each hash certifies the artifact that
carried it. What re-tuning breaks is using this hash as a cross-policy *store*
identity, which is a job for the separately recorded inputs.

*`generated_on` is store-derived and folded from inside the projection.* See
`fold_generated_on`.

**No `repr()` may reach these bytes.** `repr(MeasurementBasis.STC)` is
`<MeasurementBasis.STC: 'stc'>` - CPython's enum repr, an implementation detail
the stdlib reworked as recently as 3.11, so a routine Python upgrade would
re-baseline every golden hash with zero data change. That is the A-6 defect
class, and it has landed here three times: an unpinned `openpyxl` stamping
`docProps/app.xml`, `repr(grouping_key())`, and `_ordering_key` reintroducing
enum repr inside the fix for the second. Everything here routes through
`schema.encoding.encode_value` instead.

**This module does not import `services.conflict_hitl`.** D-14 specifies that
candidates sort by the *field sequence* `_ordering_key` uses, with every
component routed through `encode_value()` - not by `_ordering_key` itself, whose
first component is `repr(candidate.condition.grouping_key())`. Prescribing that
function verbatim would reintroduce the exact hazard the rule above closes, so
the sequence is restated in `_value_sort_key` and the dependency does not exist.

Ships the projection, not the xlsx writer. G.2-G.8 and the gating G.6
desktop-Excel test follow now that the hashed artifact of record exists; the
second hash plan 8c calls for, `sha256(normalized xlsx)`, is a renderer-
regression check only and never the integrity claim.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ...schema import (
    CanonicalField,
    ComponentInstance,
    ConflictCandidate,
    ConflictQueueEntry,
    SourceDocument,
    encode_value,
)
from . import flags_for

__all__ = [
    "PROJECTION_VERSION",
    "STORE_WRITTEN_AT",
    "ProjectionPolicy",
    "fold_generated_on",
    "project_store",
    "projection_bytes",
    "projection_digest",
]

#: Bumped whenever the shape or the byte format changes. D-14's answer to the
#: strongest objection against a Python-repr format - that it is unverifiable
#: from another language - is that this key exists precisely so a second-language
#: consumer can force the question later.
PROJECTION_VERSION = 1

#: The one key every projected store row carries its write timestamp under.
#:
#: Uniform rather than each row keeping its own column name (`ingested_at`,
#: `detected_at`, `resolved_at`), because `fold_generated_on` has to find them
#: without being told where to look. The projection is a different artifact from
#: the store, so renaming the column here costs nothing a reader needs: which
#: kind of row it is, is already told by which array it sits in.
STORE_WRITTEN_AT = "store_written_at"

#: `_rfc3339` pins a fixed-width UTC format, which is what makes `max()` over
#: these strings the same answer as `max()` over the instants they denote. The
#: guarantee is worth checking rather than assuming: `strftime("%Y")` is not
#: required to zero-pad years below 1000 on every platform, and a stamp that lost
#: its padding would sort before everything and silently under-report the
#: vintage. A store timestamp outside this shape is a bug upstream, so it raises.
_RFC3339_UTC = re.compile(r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z\Z")


class ProjectionPolicy(BaseModel):
    """The configuration half of *(store, policy)*, hashed alongside the store.

    Deliberately a model rather than a loose dict, so adding a knob is a schema
    change somebody reviews rather than a key that appears in the bytes one day.

    `policy_version` is a caller-supplied label, and golden fixtures pin their
    own: D-14 requires that production re-tuning never re-baselines a committed
    hash, and `tasks.md` sequences tau tuning after WP-B, which is exactly when
    fixture churn would otherwise be worst. The same decision makes the B.10 tau
    table **versioned, append-only data** - otherwise historical projections
    become unrecomputable the first time tau moves. That table joins this model
    when it lands.

    What is *not* here: conflict severity. `assign_severity` is policy too, but
    its output is persisted on `ConflictQueueEntry.severity` and so reaches the
    bytes as store data. Recomputing it here would both duplicate it and take the
    `conflict_hitl` dependency this module does not have.
    """

    model_config = ConfigDict(frozen=True)

    policy_version: str = Field(
        description="Identifies the tuned constants this artifact was rendered under."
    )
    confidence_threshold: float = Field(
        ge=0.0, le=1.0, description="FR-OUT-04's tau, the LOW_CONFIDENCE boundary."
    )


def project_store(
    *,
    components: Sequence[ComponentInstance],
    conflicts: Sequence[ConflictQueueEntry],
    sources: Sequence[SourceDocument],
    policy: ProjectionPolicy,
) -> dict[str, object]:
    """Reduce a store and its policy to D-14's canonical object.

    Keyword-only, because the three sequences are all `Sequence[BaseModel]` and
    swapping two positionally would produce a projection that is wrong in a way
    no type checker and no test of a *single* store would catch.

    Order is meaning in every array here, so every one of them is sorted by
    content: components by `ComponentInstance.ordering_key()` (D-4 stage 5),
    fields by name, values by the sequence in `_value_sort_key`, and the
    remaining rows by their own canonical text. Nothing is left in arrival order,
    which FR-OUT-06 forbids outright - composition is a pure function of the
    store, so any list has to be arranged by what a row *is*, never by when it
    arrived.
    """
    body: dict[str, object] = {
        "projection_version": PROJECTION_VERSION,
        "policy": encode_value(policy),
        "components": _sorted_components(components, policy=policy),
        "conflicts": _by_canonical_text(_conflict_row(entry) for entry in conflicts),
        "sources": _by_canonical_text(_source_row(document) for document in sources),
    }
    # Folded from the body, then attached - so the stamp never sees itself, and
    # `fold_generated_on` gives the same answer applied to the finished artifact.
    return {**body, "generated_on": fold_generated_on(body)}


def projection_bytes(projection: Mapping[str, object]) -> bytes:
    """D-14's canonical bytes: the hashed artifact, exactly as written."""
    return _canonical_text(projection).encode("utf-8")


def projection_digest(projection: Mapping[str, object]) -> str:
    """`sha256(projection)` - the artifact of record.

    Plan 8c stores a second digest over the normalised xlsx. That one is a
    renderer-regression check and never the integrity claim: it moves when
    openpyxl changes how it writes a cell, which is not a fact about the data.
    """
    return hashlib.sha256(projection_bytes(projection)).hexdigest()


def fold_generated_on(node: object) -> dict[str, str] | None:
    """The maximum store write-timestamp among the rows `node` actually contains.

    **A fold over the projection, never a parallel query.** D-14 recommends
    `max(document.ingested_at, claim.extracted_at, conflict.detected_at,
    resolution.resolved_at)`, and the derivation matters less than where it is
    computed: a query alongside the projection drifts silently the day someone
    adds a row type and forgets to widen it, whereas a fold over what was
    actually emitted covers the new rows the moment they carry their timestamp.
    The structural property is the requirement, not merely the value.

    It also makes the stamp checkable from the artifact alone. This function
    takes plain parsed JSON, so a reader holding only the published bytes can
    recompute `generated_on` without the store or this codebase.

    **Why the maximum over reflected rows, and not the two obvious
    alternatives.** `max(ingested_at)` does not move when a conflict is resolved,
    yet FR-HITL-04 persists a resolution into field provenance, so the workbook's
    content changed and the artifact would be dated by an ingest that is no
    longer its newest fact. The audit tip is worse: it is self-invalidating,
    because plan Decision 2 requires the `--accept-incomplete` override to be
    recorded and audited, so composing writes an event and the stamp moves on
    every override-bearing generation - breaking AC-7 in precisely the scenario
    the override exists for. `seq` is also per-stream and so globally ill-defined.

    **Only write timestamps count.** `SourceDocument.data_vintage` is a
    publication date and `SourceRef.retrieved_at` is when a page was fetched;
    neither is a store write, and a fold that swept up every datetime in the
    projection would let a future-dated datasheet revision stamp the workbook
    with a date on which nothing was written. That is why the fold reads one
    reserved key rather than every `$datetime` tag it can find.

    Returns `None` for a store with nothing in it. D-14 decides that explicitly:
    an empty store has no maximum, so the field renders as null and the workbook
    shows *no sources*. Never a placeholder or an epoch date - an epoch-like
    value is indistinguishable from a real vintage to a reader, and the whole
    point of the field is that a reader can trust what it says.

    Two costs, stated so nobody "fixes" them later: the stamp moves *backwards*
    when scope shrinks, which is acceptable because its job is vintage and the
    projection hash is the change detector; and reclassification
    (`UPDATE access_restricted`) has no store timestamp at all, so no derivation
    captures it. That is a known limit, not a defect in this choice.
    """
    stamps = sorted(_write_timestamps(node))
    return {"$datetime": stamps[-1]} if stamps else None


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _store_row(payload: dict[str, object], *, written_at: datetime | None) -> dict[str, object]:
    """Attach a row's write timestamp under the one key the fold reads.

    `written_at` is keyword-only with **no default on purpose**. The failure D-14
    names is a row type added to the projection without its timestamp, silently
    contributing nothing to the vintage; making the argument mandatory turns that
    into a `TypeError` at the call site. `None` is a legitimate answer - it says
    this row type has no store write timestamp - but it has to be written down.
    """
    return {**payload, STORE_WRITTEN_AT: encode_value(written_at)}


def _component_row(component: ComponentInstance, *, policy: ProjectionPolicy) -> dict[str, object]:
    """One `ComponentInstance`, with its fields sorted by name.

    `ordering_key()` is not emitted even though the components are sorted by it.
    It substitutes `float("-inf")` for an absent nameplate, and `allow_nan=False`
    rejects that - correctly, since infinity is not JSON. It is recomputable from
    the five keys below in any case, all of which are here.

    `written_at=None` because `ComponentInstance` carries no store write
    timestamp. Neither does `CanonicalField`, which is why D-14's
    `claim.extracted_at` term is not reachable from the canonical store today -
    the timestamp lives on `FieldClaim`, and the projection to a `CanonicalField`
    does not carry it across. Emitting the slot as an explicit null records that
    as a stated absence, and means the term joins the fold automatically if the
    column ever becomes reachable.
    """
    return _store_row(
        {
            "supplier": component.supplier,
            "model": component.model,
            "component_category": encode_value(component.component_category),
            "nameplate": component.nameplate,
            "surrogate_id": component.surrogate_id,
            "manufacturer_key": component.manufacturer_key,
            "model_family": component.model_family,
            "fields": [
                {
                    "name": name,
                    "values": _sorted_values(component.fields[name], policy=policy),
                }
                for name in sorted(component.fields)
            ],
        },
        written_at=None,
    )


def _field_row(field: CanonicalField, *, policy: ProjectionPolicy) -> dict[str, object]:
    """One conditioned value, with the `CellFlag`s the policy computes for it.

    The flags are the artifact-affecting half of D-14 decision 1. They are
    rendered as a **sorted** list because `flags_for` returns a `set`, whose
    iteration order Python does not promise to hold across runs - shipping it
    unsorted would put the A-6 defect back one level down.
    """
    return _store_row(
        {
            "value": encode_value(field.value),
            "unit": field.unit,
            "verbatim_value": field.verbatim_value,
            "condition": encode_value(field.condition),
            "source_tier": encode_value(field.source_tier),
            "source_ref": encode_value(field.source_ref),
            "confidence": field.confidence,
            "conflict_status": encode_value(field.conflict_status),
            "resolution": _resolution_row(field.resolution),
            "flags": sorted(
                flag.value
                for flag in flags_for(field, confidence_threshold=policy.confidence_threshold)
            ),
        },
        written_at=None,
    )


def _resolution_row(resolution: object) -> dict[str, object] | None:
    """A human decision, carrying `resolved_at` into the fold.

    This is the row type that eliminates `max(ingested_at)`: resolving a conflict
    changes what the workbook says without any document being re-ingested.
    """
    if resolution is None:
        return None
    resolved_at = getattr(resolution, "resolved_at", None)
    assert isinstance(resolved_at, datetime)
    dumped = encode_value(resolution)
    assert isinstance(dumped, dict)
    # `resolved_at` moves to the reserved key rather than being duplicated: the
    # same instant written twice in one canonical object is two things to keep in
    # step for no gain.
    return _store_row(
        {key: value for key, value in dumped.items() if key != "resolved_at"},
        written_at=resolved_at,
    )


def _conflict_row(entry: ConflictQueueEntry) -> dict[str, object]:
    """One queue entry. `severity` is store data - see `ProjectionPolicy`."""
    return _store_row(
        {
            "entry_id": entry.entry_id,
            "field_name": entry.field_name,
            "supplier": entry.supplier,
            "model": entry.model,
            "component_category": encode_value(entry.component_category),
            "conflict_class": encode_value(entry.conflict_class),
            "severity": encode_value(entry.severity),
            "candidates": [_candidate_row(candidate) for candidate in entry.candidates],
            "explanation": entry.explanation,
            "resolution": _resolution_row(entry.resolution),
        },
        written_at=entry.detected_at,
    )


def _candidate_row(candidate: ConflictCandidate) -> dict[str, object]:
    """A competing value inside a queue entry.

    Candidate order is **not** sorted here. FR-HITL-03 makes the candidate list
    the payload a reviewer reads, and `conflict_groupings` fixes each entry at
    exactly one comparable pair whose orientation is already content-derived
    upstream. Re-sorting would be this module inventing a second opinion about an
    order that is already a pure function of the store.
    """
    return _store_row(
        {
            "value": encode_value(candidate.value),
            "unit": candidate.unit,
            "verbatim_value": candidate.verbatim_value,
            "condition": encode_value(candidate.condition),
            "source_tier": encode_value(candidate.source_tier),
            "source_ref": encode_value(candidate.source_ref),
            "confidence": candidate.confidence,
        },
        written_at=None,
    )


def _source_row(document: SourceDocument) -> dict[str, object]:
    """One ingested document. `data_vintage` is publication date, not a write -
    it is reported per FR-OUT-06 and deliberately does not reach the fold."""
    return _store_row(
        {
            "document_id": document.document_id,
            "content_hash": document.content_hash,
            "source_uri": document.source_uri,
            "document_type": encode_value(document.document_type),
            "data_vintage": encode_value(document.data_vintage),
            "access_restricted": document.access_restricted,
        },
        written_at=document.ingested_at,
    )


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


def _sorted_components(
    components: Sequence[ComponentInstance], *, policy: ProjectionPolicy
) -> list[dict[str, object]]:
    """D-4 stage 5's order, with a content tiebreak that it needs and lacks.

    `ordering_key()` is documented as the canonical sort position, but it is not
    *total*: two instances agreeing on category, normalised manufacturer, family,
    nameplate and surrogate id tie completely - and D-4 records that
    (category, supplier, model) is provably non-unique on real data, with two
    Adani entities publishing `ASB-M10-144-550` with different specs. `sorted` is
    stable, so a tie preserves arrival order rather than breaking it, which is
    the precise defect FR-OUT-06 forbids. The row's own canonical text breaks it
    by content instead.
    """
    rows = [
        (component.ordering_key(), _component_row(component, policy=policy))
        for component in components
    ]
    # Sorted by a key *function*, never by comparing the tuples directly: a tuple
    # comparison that reached the third element would be comparing two dicts,
    # which raises. Building the tiebreak into the key keeps the payload out of
    # the comparison entirely.
    return [row for _, row in sorted(rows, key=lambda pair: (pair[0], _canonical_text(pair[1])))]


def _sorted_values(
    values: Sequence[CanonicalField], *, policy: ProjectionPolicy
) -> list[dict[str, object]]:
    """Conditioned values for one field key, in D-14's candidate order."""
    rows = [(_value_sort_key(field), _field_row(field, policy=policy)) for field in values]
    return [row for _, row in sorted(rows, key=lambda pair: pair[0])]


def _value_sort_key(field: CanonicalField) -> str:
    """`conflict_hitl._ordering_key`'s field sequence, encoded rather than `repr`'d.

    D-14 prescribes the *sequence*, not the function: `_ordering_key`'s first
    component is `repr(candidate.condition.grouping_key())`, so calling it would
    put CPython's enum repr straight into what decides hashed array order - the
    A-50 hazard the encoding rule exists to close. Restating the sequence here is
    what lets this module keep D-14's ordering without importing that one, and is
    why Track 3 does not wait on the A-50 convergence.

    Every element of that sequence is kept, including the three an earlier
    version of `_ordering_key` dropped. `None` and `""` stay distinct - they are
    distinct candidate states, and folding them together tied two values that
    genuinely differ, so the key stopped being total and arrival order leaked
    back in through the stable sort.

    The key is canonical *text* rather than the encoded tuple, because the
    encoded elements are heterogeneous - `None`, `str`, `float`, `list`, `dict`
    all appear in the same position across fields - and Python refuses to order
    those against each other. Comparing their canonical JSON is total,
    deterministic across processes, and injective wherever `encode_value` is,
    which D-14 requires it to be. `schema.encoding` orders `frozenset` members
    the same way for the same reason.

    **Text order is not numeric order**, and that is fine but worth saying, since
    the output looks numeric on small examples: `100.0` sorts before `30.0` here.
    What FR-OUT-06 asks of this key is that it be total and depend only on what a
    candidate *is* - a reader-friendly ordering is the renderer's job, and the
    workbook is free to present values in any order it likes over these rows.
    """
    return _canonical_text(
        [
            encode_value(field.condition.grouping_key()),
            encode_value(field.value),
            field.unit,
            encode_value(field.source_tier),
            encode_value(field.source_ref),
            field.verbatim_value,
            field.confidence,
            field.condition.note,
            sorted(field.condition.derived),
        ]
    )


def _by_canonical_text(rows: Iterator[dict[str, object]]) -> list[dict[str, object]]:
    """Order rows by their own canonical bytes.

    Used where D-14 names no key. Sorting on a natural one - `entry_id`,
    `document_id` - would order by an identifier whose assignment need not be
    content-derived, and would tie whenever two rows shared it. The full row is
    content by construction and ties only for rows that are genuinely identical.
    """
    return sorted(rows, key=_canonical_text)


def _canonical_text(value: object) -> str:
    """D-14's serialisation, shared by the emitted bytes and every sort key.

    One function on purpose: a sort key computed under different `json.dumps`
    options than the output would order rows by bytes nobody ever sees.
    """
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------


def _write_timestamps(node: object) -> Iterator[str]:
    """Every store write timestamp inside `node`, at any depth.

    Recursive rather than a pass over the three top-level arrays, because a
    `Resolution` is not a top-level row - it hangs off a field or a queue entry -
    and it is the one that moves the stamp when nothing was re-ingested.
    """
    if isinstance(node, dict):
        stamp = node.get(STORE_WRITTEN_AT)
        if stamp is not None:
            yield _checked_stamp(stamp)
        for key, value in node.items():
            if key != STORE_WRITTEN_AT:
                yield from _write_timestamps(value)
    elif isinstance(node, list):
        for item in node:
            yield from _write_timestamps(item)


def _checked_stamp(stamp: object) -> str:
    """Unwrap an encoded datetime, refusing anything `max()` would mis-order."""
    if not isinstance(stamp, dict) or set(stamp) != {"$datetime"}:
        raise ValueError(
            f"{STORE_WRITTEN_AT} must hold an encoded datetime, got {stamp!r}. The "
            "vintage fold reads this key and nothing else, so a row storing "
            "something else here contributes silently nothing."
        )
    text = stamp["$datetime"]
    if not isinstance(text, str) or not _RFC3339_UTC.fullmatch(text):
        raise ValueError(
            f"{text!r} is not the fixed-width RFC 3339 UTC form the fold orders by. "
            "See _RFC3339_UTC: lexicographic maximum is only the chronological "
            "maximum while every stamp is the same width."
        )
    return text
