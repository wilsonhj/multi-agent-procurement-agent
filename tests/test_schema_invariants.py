"""Invariants the canonical schema must hold regardless of implementation."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement_agent.schema import (
    CATEGORY_TO_TAB,
    CanonicalField,
    ComponentCategory,
    ConflictCandidate,
    ConflictClass,
    ConflictQueueEntry,
    ConflictStatus,
    Resolution,
    ResolutionAction,
    Severity,
    SourceRef,
    SourceTier,
    WorkbookTab,
)


def _resolution(resolved_by: str) -> Resolution:
    return Resolution(
        action=ResolutionAction.KEEP_SYSTEM_OF_RECORD,
        resolved_by=resolved_by,
        resolved_at=datetime.now(UTC),
        rationale="Contract supersedes the CEC listing.",
    )


def _entry(**overrides: object) -> ConflictQueueEntry:
    payload: dict[str, object] = {
        "entry_id": "c-1",
        "field_name": "nameplate_power",
        "supplier": "Trina Solar",
        "model": "TSM-NEG21C.20",
        "component_category": ComponentCategory.PV_MODULES,
        "conflict_class": ConflictClass.RECORD_VS_WEB,
        "severity": Severity.HIGH,
        "candidates": [
            ConflictCandidate(
                value=650,
                unit="Wp",
                source_tier=SourceTier.SYSTEM_OF_RECORD,
                source_ref=SourceRef(document_id="doc-1", page=3),
                confidence=0.95,
            )
        ],
        "explanation": "Datasheet and CEC listing disagree.",
        "detected_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return ConflictQueueEntry(**payload)  # type: ignore[arg-type]


def test_source_ref_requires_a_source() -> None:
    """NFR-01: no unsourced values permitted."""
    with pytest.raises(ValidationError):
        SourceRef()


def test_canonical_field_has_the_eight_spec_keys_plus_condition() -> None:
    """TRS section 5 fixes eight keys. We carry nine.

    `condition` is a deliberate deviation, recorded in analysis.md A-1: most
    false conflicts in this domain are condition mismatches, not unit errors,
    and the TRS's own section 7 lists parameters ("rated AC kVA @temp",
    "STC/NMOT ratings") that cannot be represented without it.

    The eight spec keys must all still be present and named exactly as written.
    """
    spec_keys = {
        "value",
        "unit",
        "verbatim_value",
        "source_tier",
        "source_ref",
        "confidence",
        "conflict_status",
        "resolution",
    }
    assert spec_keys <= set(CanonicalField.model_fields)
    assert set(CanonicalField.model_fields) - spec_keys == {"condition"}


def test_resolved_field_must_carry_its_resolution() -> None:
    """FR-HITL-06: decisions are logged with user, timestamp, before/after, rationale."""
    with pytest.raises(ValidationError):
        CanonicalField(
            value=650,
            source_tier=SourceTier.SYSTEM_OF_RECORD,
            source_ref=SourceRef(document_id="doc-1"),
            confidence=0.9,
            conflict_status=ConflictStatus.RESOLVED,
        )


def test_resolved_field_accepts_a_resolution() -> None:
    field = CanonicalField(
        value=650,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
        conflict_status=ConflictStatus.RESOLVED,
        resolution=Resolution(
            action=ResolutionAction.KEEP_SYSTEM_OF_RECORD,
            resolved_by="procurement.lead",
            resolved_at=datetime.now(UTC),
            rationale="Contract supersedes the web datasheet revision.",
            value_before=655,
            value_after=650,
        ),
    )
    # Echoing the constructor kwarg back tests pydantic, not the validator. What
    # `_resolution_matches_status` actually enforces is the *other* direction:
    # RESOLVED without a Resolution is the state FR-HITL-06 forbids, because a
    # decision with no record of who made it is not auditable.
    assert field.resolution is not None
    with pytest.raises(ValidationError):
        CanonicalField(
            value=650,
            source_tier=SourceTier.SYSTEM_OF_RECORD,
            source_ref=SourceRef(document_id="doc-1"),
            confidence=0.9,
            conflict_status=ConflictStatus.RESOLVED,
        )


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        CanonicalField(
            value=1,
            source_tier=SourceTier.SYSTEM_OF_RECORD,
            source_ref=SourceRef(document_id="d"),
            confidence=1.5,
        )


def test_every_category_maps_to_a_tab() -> None:
    assert set(CATEGORY_TO_TAB) == set(ComponentCategory)
    assert len(set(CATEGORY_TO_TAB.values())) == len(ComponentCategory)


def test_workbook_has_thirteen_tabs() -> None:
    """AC-3: the workbook contains all thirteen tabs."""
    assert len(WorkbookTab) == 13


def test_first_eight_tabs_are_the_category_tabs() -> None:
    """FR-OUT-02 orders category tabs 1-8 ahead of the five summary tabs."""
    assert list(WorkbookTab)[:8] == list(CATEGORY_TO_TAB.values())


def test_resolution_invariant_survives_assignment() -> None:
    """`_resolution_matches_status` ran only at construction, so the state
    FR-HITL-06 forbids was one attribute assignment away.

    `test_resolved_field_must_carry_its_resolution` covers the constructor and
    passed throughout: the model simply never re-validated. A field mutated to
    RESOLVED with no `Resolution` is a decision with no record of who made it,
    which is precisely what the validator exists to refuse.
    """
    field = CanonicalField(
        value=650,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
    )
    with pytest.raises(ValidationError):
        field.conflict_status = ConflictStatus.RESOLVED


def test_attaching_a_resolution_then_resolving_is_allowed() -> None:
    """The happy path, which `validate_assignment` must not have broken.

    A validator tight enough to forbid every assignment would pass every test
    that only checks rejection, and the pipeline would be unable to record a
    decision at all. Resolution first, then status - the order the class
    docstring prescribes, because the reverse passes through the forbidden
    intermediate state.
    """
    field = CanonicalField(
        value=650,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
    )
    field.resolution = _resolution("procurement.lead")
    field.conflict_status = ConflictStatus.RESOLVED
    assert field.conflict_status is ConflictStatus.RESOLVED
    assert field.resolution is not None and field.resolution.resolved_by == "procurement.lead"


def test_a_resolved_field_cannot_have_its_resolution_cleared() -> None:
    """The other direction of the same invariant.

    `test_resolution_invariant_survives_assignment` drives `conflict_status`
    toward RESOLVED; this drives `resolution` away from a value while the status
    already says RESOLVED. Both reach the state FR-HITL-06 forbids - a decision
    with no record of who made it - and a validator that checked only one field's
    assignment would catch only one of them.
    """
    field = CanonicalField(
        value=650,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
        conflict_status=ConflictStatus.RESOLVED,
        resolution=_resolution("procurement.lead"),
    )
    with pytest.raises(ValidationError):
        field.resolution = None


def test_a_recorded_resolution_cannot_be_replaced() -> None:
    """FR-HITL-06's log is immutable, and freezing `Resolution` alone does not
    deliver that: the *pointer* to it was assignable, so a second write replaced
    a reviewer's decision with no trace the first had ever existed.

    Every other model in this module is frozen; these two were the exceptions.
    """
    entry = _entry(resolution=_resolution("alice"))
    with pytest.raises(ValidationError):
        entry.resolution = _resolution("mallory")


def test_a_queue_entry_category_is_the_closed_vocabulary() -> None:
    """The frozen contract types this field `ComponentCategory`, and
    `ComponentInstance` already did; only the queue entry took a bare `str`.

    So a human-readable label like "PV Modules" validated cleanly while being no
    member of the vocabulary `CATEGORY_TO_TAB` is keyed on - the invisible failure
    this schema closes its vocabularies to prevent, waiting for the composition
    path to be written.
    """
    with pytest.raises(ValidationError):
        _entry(component_category="PV Modules")
