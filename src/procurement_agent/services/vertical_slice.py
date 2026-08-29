"""A narrow, executable PV-module path over a trusted sanitized CSV export.

This is deliberately not a general document extractor.  It is the smallest
production-code path that exercises the existing contracts end to end: parse a
structured intake, append immutable claims, reduce them, detect conflicts, expose
a human review operation, and hand the canonical components to the workbook
writer.  PDF/OCR and model-backed extraction remain adapter work.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import cast

from ..audit import AuditConnection, AuditEvent, JsonObject, append_event
from ..schema import (
    ComponentCategory,
    ComponentInstance,
    Condition,
    ConflictQueueEntry,
    ConflictStatus,
    DocumentType,
    MeasurementBasis,
    Resolution,
    ResolutionAction,
    SourceDocument,
    SourceTier,
    encode_value,
)
from ..schema.registry import Shape, ValueType, spec_for
from .claims import FieldClaim, project
from .conflict_hitl import (
    assign_severity,
    comparison_groups,
    comparison_pairs,
    tolerance_for,
    values_conflict,
)
from .identity import identity_keys
from .output import write_workbook
from .output.projection import ProjectionPolicy, project_store
from .transactional_audit import write_and_append_event

__all__ = [
    "InMemoryClaimStore",
    "PendingAuditEvent",
    "SanitizedCSVError",
    "VerticalSliceResult",
    "persist_vertical_slice",
    "review_conflict",
    "run_sanitized_pv_csv",
]

EXTRACTOR_VERSION = "sanitized-pv-csv@1"
REQUIRED_COLUMNS = frozenset(
    {
        "document_id",
        "source_uri",
        "document_type",
        "supplier",
        "model",
        "nameplate",
        "field_name",
        "value",
        "unit",
        "verbatim_value",
        "basis",
        "section",
        "confidence",
    }
)


class SanitizedCSVError(ValueError):
    """The trusted intake is malformed or outside this slice's narrow contract."""


class InMemoryClaimStore:
    """An append-only reference store for immutable :class:`FieldClaim` values."""

    def __init__(self) -> None:
        self._claims: tuple[FieldClaim, ...] = ()

    @property
    def claims(self) -> tuple[FieldClaim, ...]:
        return self._claims

    def append(self, claim: FieldClaim) -> bool:
        """Append once; an exact replay is an idempotent no-op."""
        if claim in self._claims:
            return False
        self._claims = (*self._claims, claim)
        return True

    def extend(self, claims: Iterable[FieldClaim]) -> int:
        return sum(self.append(claim) for claim in claims)


@dataclass(frozen=True, slots=True)
class PendingAuditEvent:
    """An event to append in the caller's transaction with its business write."""

    document_id: str
    event_type: str
    actor: str
    payload: JsonObject
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class VerticalSliceResult:
    """The complete output of the narrow path, ready to persist or render."""

    sources: tuple[SourceDocument, ...]
    claims: tuple[FieldClaim, ...]
    components: tuple[ComponentInstance, ...]
    conflicts: tuple[ConflictQueueEntry, ...]
    audit_events: tuple[PendingAuditEvent, ...]

    def workbook_projection(self, *, policy: ProjectionPolicy) -> dict[str, object]:
        return project_store(
            components=self.components,
            conflicts=self.conflicts,
            sources=self.sources,
            policy=policy,
        )

    def write_workbook(self, destination: Path, *, confidence_threshold: float) -> Path:
        return write_workbook(
            list(self.components),
            destination,
            confidence_threshold=confidence_threshold,
        )


@dataclass(frozen=True, slots=True)
class _ParsedRow:
    document_id: str
    source_uri: str
    document_type: DocumentType
    supplier: str
    model: str
    nameplate: float
    field_name: str
    value: object
    unit: str | None
    verbatim_value: str
    condition: Condition
    section: str
    confidence: float


def run_sanitized_pv_csv(
    data: bytes,
    *,
    ingested_at: datetime,
    detected_at: datetime,
    actor: str,
    claim_store: InMemoryClaimStore | None = None,
    persist: Callable[[VerticalSliceResult], None] | None = None,
) -> VerticalSliceResult:
    """Parse and reduce one sanitized comparison CSV.

    ``persist`` is the explicit transaction boundary.  It is called only after
    every model, conflict and audit intent has validated; a database caller wraps
    it with the repository's transactional audit helper so the business rows and
    events commit or roll back together.
    """
    _require_aware(ingested_at, "ingested_at")
    _require_aware(detected_at, "detected_at")
    rows = _parse_rows(data)
    if not rows:
        raise SanitizedCSVError("the sanitized CSV contains no data rows")

    identities = {(row.supplier, row.model, row.nameplate) for row in rows}
    if len(identities) != 1:
        raise SanitizedCSVError(
            "this vertical slice accepts exactly one PV component identity per intake"
        )
    supplier, model, nameplate = identities.pop()

    source_rows: dict[str, list[_ParsedRow]] = {}
    for row in rows:
        source_rows.setdefault(row.document_id, []).append(row)
    sources = tuple(
        _source_document(document_id, grouped, ingested_at=ingested_at)
        for document_id, grouped in sorted(source_rows.items())
    )

    claims = tuple(_claim(row) for row in rows)
    store = claim_store if claim_store is not None else InMemoryClaimStore()
    store.extend(claims)
    relevant = tuple(
        claim
        for claim in store.claims
        if claim.document_id in source_rows and claim.field_name in {row.field_name for row in rows}
    )

    by_field: dict[str, list[FieldClaim]] = {}
    for claim in relevant:
        by_field.setdefault(claim.field_name, []).append(claim)
    fields = {name: project(field_claims) for name, field_claims in sorted(by_field.items())}
    keys = identity_keys(supplier, model, nameplate)
    component = ComponentInstance(
        supplier=supplier,
        model=model,
        component_category=ComponentCategory.PV_MODULES,
        nameplate=nameplate,
        surrogate_id=keys.surrogate_id,
        manufacturer_key=keys.manufacturer_key,
        model_family=keys.model_family,
        fields=fields,
    )
    conflicts = tuple(
        _detect_conflicts(
            supplier=supplier,
            model=model,
            field_name=field_name,
            claims=field_claims,
            detected_at=detected_at,
        )
        for field_name, field_claims in sorted(by_field.items())
    )
    flattened_conflicts = tuple(entry for group in conflicts for entry in group)
    audit_events = _audit_events(
        sources=sources,
        claims=relevant,
        conflicts=flattened_conflicts,
        actor=actor,
        recorded_at=detected_at,
    )
    result = VerticalSliceResult(
        sources=sources,
        claims=relevant,
        components=(component,),
        conflicts=flattened_conflicts,
        audit_events=audit_events,
    )
    if persist is not None:
        persist(result)
    return result


def persist_vertical_slice[ResultT](
    conn: AuditConnection,
    result: VerticalSliceResult,
    *,
    write: Callable[[AuditConnection, VerticalSliceResult], ResultT],
) -> tuple[ResultT, VerticalSliceResult, tuple[AuditEvent, ...]]:
    """Persist the slice and every audit intent in one caller-owned transaction.

    The first intent is bound to the business callback through
    :func:`write_and_append_event`; the rest append on the same connection before
    control returns.  Neither helper commits.  An exception therefore leaves the
    caller's transaction context to roll back the business rows and all events.
    """
    if not result.audit_events:
        raise ValueError("a vertical-slice persistence must carry at least one audit event")
    first, *remaining = result.audit_events
    written, first_event = write_and_append_event(
        conn,
        write=lambda connection: write(connection, result),
        document_id=first.document_id,
        event_type=first.event_type,
        actor=first.actor,
        payload=first.payload,
        recorded_at=first.recorded_at,
    )
    events = [first_event]
    for intent in remaining:
        events.append(
            append_event(
                conn,
                document_id=intent.document_id,
                event_type=intent.event_type,
                actor=intent.actor,
                payload=intent.payload,
                recorded_at=intent.recorded_at,
            )
        )
    # Audit intents are an outbox, not historical state.  Returning a fresh
    # result with the outbox cleared makes the safe continuation explicit: a
    # later review appends only its new resolution intent instead of replaying
    # document/extraction/conflict events that already committed.
    persisted = replace(result, audit_events=())
    return written, persisted, tuple(events)


def review_conflict(
    result: VerticalSliceResult, *, entry_id: str, resolution: Resolution
) -> VerticalSliceResult:
    """Apply the slice's minimal review action without mutating its input.

    The first operational review path supports choosing an existing candidate.
    Override entry needs a separately sourced value, and silently inventing
    provenance here would violate NFR-01.
    """
    if resolution.action not in {
        ResolutionAction.SELECT_VALUE,
        ResolutionAction.KEEP_SYSTEM_OF_RECORD,
    }:
        raise ValueError(
            "the initial review path supports selecting an existing value only; "
            "override and re-search require their own sourced persistence paths"
        )
    matches = [entry for entry in result.conflicts if entry.entry_id == entry_id]
    if len(matches) != 1:
        raise KeyError(f"expected one conflict with entry_id {entry_id!r}, found {len(matches)}")
    target = matches[0]
    if target.resolution is not None:
        raise ValueError(f"conflict {entry_id!r} already has an immutable resolution")
    eligible = [
        candidate
        for candidate in target.candidates
        if resolution.action is ResolutionAction.SELECT_VALUE
        or candidate.source_tier is SourceTier.SYSTEM_OF_RECORD
    ]
    selected_candidates = [
        candidate for candidate in eligible if candidate.value == resolution.value_after
    ]
    if not selected_candidates:
        raise ValueError("value_after must identify an eligible existing conflict candidate")
    if len(selected_candidates) > 1:
        raise ValueError(
            "value_after matches more than one eligible candidate; this minimal review "
            "operation cannot choose provenance unambiguously"
        )
    selected = selected_candidates[0]

    resolved_entry = target.model_copy(update={"resolution": resolution})
    components: list[ComponentInstance] = []
    for component in result.components:
        if component.supplier != target.supplier or component.model != target.model:
            components.append(component)
            continue
        fields = {name: list(values) for name, values in component.fields.items()}
        current = fields[target.field_name]
        fields[target.field_name] = [
            field.evolve(
                value=selected.value,
                unit=selected.unit,
                verbatim_value=selected.verbatim_value,
                condition=selected.condition,
                source_tier=selected.source_tier,
                source_ref=selected.source_ref,
                confidence=selected.confidence,
                conflict_status=ConflictStatus.RESOLVED,
                resolution=resolution,
            )
            if field.condition.grouping_key() == selected.condition.grouping_key()
            else field
            for field in current
        ]
        snapshot = {name: getattr(component, name) for name in type(component).model_fields}
        components.append(ComponentInstance.model_validate({**snapshot, "fields": fields}))
    conflicts = tuple(
        resolved_entry if entry.entry_id == entry_id else entry for entry in result.conflicts
    )
    event = PendingAuditEvent(
        document_id=selected.source_ref.document_id or result.sources[0].document_id,
        event_type="resolution",
        actor=resolution.resolved_by,
        payload=cast(
            JsonObject,
            {
                "entry_id": entry_id,
                "field_name": target.field_name,
                "resolution": encode_value(resolution),
            },
        ),
        recorded_at=resolution.resolved_at,
    )
    return replace(
        result,
        components=tuple(components),
        conflicts=conflicts,
        audit_events=(*result.audit_events, event),
    )


def _parse_rows(data: bytes) -> list[_ParsedRow]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SanitizedCSVError("sanitized CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text), strict=True)
    columns = frozenset(reader.fieldnames or ())
    missing = sorted(REQUIRED_COLUMNS - columns)
    extra = sorted(columns - REQUIRED_COLUMNS)
    if missing or extra:
        raise SanitizedCSVError(
            f"CSV columns differ from the frozen intake (missing={missing}, extra={extra})"
        )
    parsed: list[_ParsedRow] = []
    for line_number, raw in enumerate(reader, start=2):
        try:
            field_name = raw["field_name"].strip()
            spec = spec_for(field_name, ComponentCategory.PV_MODULES)
            if spec is None:
                raise SanitizedCSVError(f"{field_name!r} is not a PV-module contract key")
            value = _parse_value(raw["value"], spec.shape, spec.value_type)
            unit = raw["unit"].strip() or None
            if unit != spec.unit:
                raise SanitizedCSVError(
                    f"{field_name!r} requires canonical unit {spec.unit!r}, got {unit!r}"
                )
            parsed.append(
                _ParsedRow(
                    document_id=_required(raw, "document_id"),
                    source_uri=_required(raw, "source_uri"),
                    document_type=DocumentType(_required(raw, "document_type")),
                    supplier=_required(raw, "supplier"),
                    model=_required(raw, "model"),
                    nameplate=float(_required(raw, "nameplate")),
                    field_name=field_name,
                    value=value,
                    unit=unit,
                    verbatim_value=_required(raw, "verbatim_value"),
                    condition=Condition(
                        basis=(
                            MeasurementBasis(raw["basis"].strip()) if raw["basis"].strip() else None
                        )
                    ),
                    section=_required(raw, "section"),
                    confidence=float(_required(raw, "confidence")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, SanitizedCSVError):
                raise SanitizedCSVError(f"line {line_number}: {exc}") from exc
            raise SanitizedCSVError(f"line {line_number}: {exc}") from exc
    return parsed


def _parse_value(raw: str, shape: Shape, value_type: ValueType) -> object:
    if shape is not Shape.SCALAR:
        raise SanitizedCSVError("the initial CSV adapter accepts scalar contract fields only")
    text = raw.strip()
    if value_type is ValueType.FLOAT:
        return float(text)
    if value_type is ValueType.INT:
        return int(text)
    if value_type is ValueType.BOOL:
        if text.casefold() not in {"true", "false"}:
            raise SanitizedCSVError(f"boolean value must be true or false, got {text!r}")
        return text.casefold() == "true"
    if value_type is ValueType.STR:
        return text
    raise SanitizedCSVError(f"the initial CSV adapter does not parse {value_type.value}")


def _required(row: dict[str, str], name: str) -> str:
    value = row[name].strip()
    if not value:
        raise SanitizedCSVError(f"{name} is required")
    return value


def _source_document(
    document_id: str, rows: list[_ParsedRow], *, ingested_at: datetime
) -> SourceDocument:
    uris = {row.source_uri for row in rows}
    types = {row.document_type for row in rows}
    if len(uris) != 1 or len(types) != 1:
        raise SanitizedCSVError(
            f"document_id {document_id!r} must identify exactly one URI and document type"
        )
    encoded_rows = [_row_content(row) for row in rows]
    canonical_rows = json.dumps(
        sorted(
            encoded_rows,
            key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")),
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SourceDocument(
        document_id=document_id,
        content_hash="sha256:" + hashlib.sha256(canonical_rows).hexdigest(),
        source_uri=next(iter(uris)),
        document_type=next(iter(types)),
        ingested_at=ingested_at,
    )


def _claim(row: _ParsedRow) -> FieldClaim:
    from ..schema import SourceRef

    return FieldClaim(
        document_id=row.document_id,
        field_name=row.field_name,
        extractor_version=EXTRACTOR_VERSION,
        condition=row.condition,
        value=row.value,
        unit=row.unit,
        verbatim_value=row.verbatim_value,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id=row.document_id, section=row.section),
        confidence=row.confidence,
    )


def _row_content(row: _ParsedRow) -> dict[str, object]:
    return {
        "document_id": row.document_id,
        "source_uri": row.source_uri,
        "document_type": row.document_type.value,
        "supplier": row.supplier,
        "model": row.model,
        "nameplate": row.nameplate,
        "field_name": row.field_name,
        "value": encode_value(row.value),
        "unit": row.unit,
        "verbatim_value": row.verbatim_value,
        "condition": encode_value(row.condition),
        "section": row.section,
        "confidence": row.confidence,
    }


def _detect_conflicts(
    *,
    supplier: str,
    model: str,
    field_name: str,
    claims: list[FieldClaim],
    detected_at: datetime,
) -> tuple[ConflictQueueEntry, ...]:
    candidates = [claim.as_candidate() for claim in claims]
    groups = comparison_groups(candidates)
    entries: list[ConflictQueueEntry] = []
    for left, right in comparison_pairs(candidates, field_name=field_name):
        verdict = values_conflict(
            left,
            right,
            field_name=field_name,
            tolerance=tolerance_for(field_name),
        )
        if not verdict.conflicts:
            continue
        assert verdict.conflict_class is not None
        condition_group = next(
            (group for group in groups if left in group or right in group), [left, right]
        )
        pair = [left, right]
        entry_material = json.dumps(
            encode_value([field_name, pair]), sort_keys=True, separators=(",", ":")
        ).encode()
        entries.append(
            ConflictQueueEntry(
                entry_id="pv-" + hashlib.sha256(entry_material).hexdigest()[:16],
                field_name=field_name,
                supplier=supplier,
                model=model,
                component_category=ComponentCategory.PV_MODULES,
                conflict_class=verdict.conflict_class,
                severity=assign_severity(field_name, verdict.conflict_class, condition_group, pair),
                candidates=pair,
                explanation=verdict.reason,
                detected_at=detected_at,
            )
        )
    return tuple(entries)


def _audit_events(
    *,
    sources: tuple[SourceDocument, ...],
    claims: tuple[FieldClaim, ...],
    conflicts: tuple[ConflictQueueEntry, ...],
    actor: str,
    recorded_at: datetime,
) -> tuple[PendingAuditEvent, ...]:
    events: list[PendingAuditEvent] = []
    for source in sources:
        source_claims = [claim for claim in claims if claim.document_id == source.document_id]
        events.append(
            PendingAuditEvent(
                document_id=source.document_id,
                event_type="document_ingested",
                actor=actor,
                payload=cast(JsonObject, {"source": encode_value(source)}),
                recorded_at=source.ingested_at,
            )
        )
        events.append(
            PendingAuditEvent(
                document_id=source.document_id,
                event_type="extraction",
                actor=actor,
                payload=cast(JsonObject, {"claims": encode_value(source_claims)}),
                recorded_at=recorded_at,
            )
        )
    for conflict in conflicts:
        document_id = next(
            candidate.source_ref.document_id
            for candidate in conflict.candidates
            if candidate.source_ref.document_id is not None
        )
        events.append(
            PendingAuditEvent(
                document_id=document_id,
                event_type="conflict_detected",
                actor=actor,
                payload=cast(JsonObject, {"conflict": encode_value(conflict)}),
                recorded_at=recorded_at,
            )
        )
    return tuple(events)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware")
