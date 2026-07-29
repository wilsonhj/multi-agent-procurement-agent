"""Invariants the canonical schema must hold regardless of implementation."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement_agent.schema import (
    CATEGORY_TO_TAB,
    CanonicalField,
    ComponentCategory,
    ConflictStatus,
    Resolution,
    ResolutionAction,
    SourceRef,
    SourceTier,
    WorkbookTab,
)


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
