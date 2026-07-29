"""FR-OUT-04: conditional formatting distinguishes four states."""

from procurement_agent.schema import (
    CanonicalField,
    CellFlag,
    ConflictStatus,
    SourceRef,
    SourceTier,
)
from procurement_agent.services.output import flags_for

THRESHOLD = 0.80


def _field(**kwargs: object) -> CanonicalField:
    defaults: dict[str, object] = {
        "value": 650,
        "source_tier": SourceTier.SYSTEM_OF_RECORD,
        "source_ref": SourceRef(document_id="doc-1", page=2),
        "confidence": 0.95,
    }
    return CanonicalField(**(defaults | kwargs))  # type: ignore[arg-type]


def test_clean_value_has_no_flags() -> None:
    assert flags_for(_field(), confidence_threshold=THRESHOLD) == set()


def test_missing_value_is_flagged() -> None:
    flags = flags_for(_field(value=None), confidence_threshold=THRESHOLD)
    assert CellFlag.MISSING_DATA in flags


def test_web_supplemented_value_is_flagged() -> None:
    flags = flags_for(
        _field(
            source_tier=SourceTier.WEB_SUPPLEMENT,
            source_ref=SourceRef(url="https://example.com"),
        ),
        confidence_threshold=THRESHOLD,
    )
    assert CellFlag.WEB_SUPPLEMENTED in flags


def test_low_confidence_value_is_flagged() -> None:
    flags = flags_for(_field(confidence=0.4), confidence_threshold=THRESHOLD)
    assert CellFlag.LOW_CONFIDENCE in flags


def test_open_conflict_is_flagged() -> None:
    flags = flags_for(_field(conflict_status=ConflictStatus.OPEN), confidence_threshold=THRESHOLD)
    assert CellFlag.UNRESOLVED_CONFLICT in flags


def test_insufficient_evidence_is_flagged_not_silently_dropped() -> None:
    """FR-RAG-04 / FR-HITL-05: an insufficient-evidence result reaches the output."""
    flags = flags_for(
        _field(value=None, conflict_status=ConflictStatus.INSUFFICIENT_EVIDENCE),
        confidence_threshold=THRESHOLD,
    )
    assert CellFlag.UNRESOLVED_CONFLICT in flags
    assert CellFlag.MISSING_DATA in flags


def test_flags_combine() -> None:
    """A cell can be web-sourced and low-confidence at once."""
    flags = flags_for(
        _field(
            source_tier=SourceTier.WEB_SUPPLEMENT,
            source_ref=SourceRef(url="https://example.com"),
            confidence=0.3,
        ),
        confidence_threshold=THRESHOLD,
    )
    assert {CellFlag.WEB_SUPPLEMENTED, CellFlag.LOW_CONFIDENCE} <= flags


def test_confidence_exactly_at_the_threshold_is_not_low() -> None:
    """FR-OUT-04 flags values *below* the threshold. `<` mutated to `<=` survived
    every other test here, because none of them sits on the boundary — and the
    boundary is the one value a configured threshold is chosen to land on."""
    at = _field(confidence=0.80)
    assert CellFlag.LOW_CONFIDENCE not in flags_for(at, confidence_threshold=0.80)
    just_below = _field(confidence=0.7999)
    assert CellFlag.LOW_CONFIDENCE in flags_for(just_below, confidence_threshold=0.80)
