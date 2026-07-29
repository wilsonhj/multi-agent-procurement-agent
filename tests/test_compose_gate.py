"""The compose gate is the only place a human decision holds up the pipeline.

Issue #14. It gates on unresolved conflicts *strictly above* a threshold
(plan.md Decision 2, tasks.md I.3), on an explicitly ordered scale, and it
returns the blocking entries so FR-HITL-05's completeness manifest can name them.
"""

from datetime import UTC, datetime

from procurement_agent.config import Settings
from procurement_agent.orchestrator import blocking_conflicts, compose_gate_blocks
from procurement_agent.schema import (
    ConflictCandidate,
    ConflictClass,
    ConflictQueueEntry,
    Severity,
    SourceRef,
    SourceTier,
)


def _entry(severity: Severity, entry_id: str = "c-1") -> ConflictQueueEntry:
    return ConflictQueueEntry(
        entry_id=entry_id,
        field_name="nameplate_power_w",
        supplier="Trina Solar",
        model="TSM-NEG21C.20",
        component_category="pv_modules",
        conflict_class=ConflictClass.RECORD_VS_WEB,
        severity=severity,
        candidates=[
            ConflictCandidate(
                value=650,
                unit="Wp",
                source_tier=SourceTier.SYSTEM_OF_RECORD,
                source_ref=SourceRef(document_id="doc-1", page=3),
                confidence=0.95,
            )
        ],
        explanation="Datasheet and CEC listing disagree.",
        detected_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_severity_is_ordered_higher_is_worse() -> None:
    """A bare int cannot carry this; the gate's correctness depends on it."""
    assert Severity.INFORMATIONAL < Severity.LOW < Severity.MEDIUM
    assert Severity.MEDIUM < Severity.HIGH < Severity.CRITICAL


def test_nothing_unresolved_does_not_block() -> None:
    assert not compose_gate_blocks([], threshold=Severity.MEDIUM)
    assert blocking_conflicts([], threshold=Severity.MEDIUM) == []


def test_threshold_is_exclusive_not_inclusive() -> None:
    """Both specs say "above a severity threshold". An entry AT the threshold
    must not block - the previous `>=` did, which is issue #14's off-by-one."""
    assert not compose_gate_blocks([_entry(Severity.MEDIUM)], threshold=Severity.MEDIUM)
    assert compose_gate_blocks([_entry(Severity.HIGH)], threshold=Severity.MEDIUM)


def test_informational_conflicts_never_block_at_the_lowest_threshold() -> None:
    """A 0-based scale must not let purely informational items stop the workbook."""
    entries = [_entry(Severity.INFORMATIONAL) for _ in range(3)]
    assert not compose_gate_blocks(entries, threshold=Severity.INFORMATIONAL)


def test_blocking_conflicts_names_the_blockers() -> None:
    """FR-HITL-05: a refusal has to say which conflicts refused it."""
    entries = [
        _entry(Severity.LOW, "low"),
        _entry(Severity.CRITICAL, "cert-missing"),
        _entry(Severity.HIGH, "pricing"),
    ]
    blockers = blocking_conflicts(entries, threshold=Severity.MEDIUM)
    assert [entry.entry_id for entry in blockers] == ["cert-missing", "pricing"]


def test_gate_agrees_with_its_primitive() -> None:
    entries = [_entry(Severity.HIGH)]
    assert compose_gate_blocks(entries, threshold=Severity.MEDIUM) is bool(
        blocking_conflicts(entries, threshold=Severity.MEDIUM)
    )


def test_threshold_has_a_configured_default() -> None:
    """Every caller inventing its own threshold was half of issue #14."""
    assert Settings().compose_gate_threshold is Severity.MEDIUM
