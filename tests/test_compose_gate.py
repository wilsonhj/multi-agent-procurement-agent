"""The compose gate is the only place a human decision holds up the pipeline.

Issue #14. It gates on unresolved conflicts *strictly above* a threshold
(plan.md Decision 2, tasks.md I.3), on an explicitly ordered scale, and it
returns the blocking entries so FR-HITL-05's completeness manifest can name them.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from procurement_agent.config import Settings
from procurement_agent.orchestrator import blocking_conflicts, compose_gate_blocks
from procurement_agent.schema import (
    ComponentCategory,
    ConflictCandidate,
    ConflictClass,
    ConflictQueueEntry,
    Resolution,
    ResolutionAction,
    Severity,
    SourceRef,
    SourceTier,
)


def _isolated_settings(**overrides: Any) -> Settings:
    """`Settings` built without reading the ambient environment or a local `.env`.

    A bare `Settings()` reads both, so a default-value test fails for anyone who
    followed `.env.example` - which this branch ships. `_env_file` is a real
    pydantic-settings argument that mypy does not model, hence the single ignore
    here rather than one at every call site.
    """
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _entry(severity: Severity, entry_id: str = "c-1") -> ConflictQueueEntry:
    return ConflictQueueEntry(
        entry_id=entry_id,
        field_name="nameplate_power_w",
        supplier="Trina Solar",
        model="TSM-NEG21C.20",
        component_category=ComponentCategory.PV_MODULES,
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


def test_blockers_keep_input_order_rather_than_being_re_sorted() -> None:
    """The ids above happen to be alphabetical, so sorting the result was
    indistinguishable from preserving order. FR-HITL-05's manifest names the
    blockers in the order the queue holds them; re-sorting silently reorders a
    reviewer's worklist."""
    entries = [_entry(Severity.HIGH, "zebra"), _entry(Severity.HIGH, "alpha")]
    blockers = blocking_conflicts(entries, threshold=Severity.MEDIUM)
    assert [entry.entry_id for entry in blockers] == ["zebra", "alpha"]


def test_gate_agrees_with_its_primitive() -> None:
    """Both outcomes, and both pinned to a literal.

    `compose_gate_blocks(...) is bool(blocking_conflicts(...))` restates the
    gate's own one-line definition, so it passed with `blocking_conflicts`
    replaced by `list(unresolved)` — the gate wide open."""
    blocking = [_entry(Severity.HIGH)]
    assert compose_gate_blocks(blocking, threshold=Severity.MEDIUM) is True
    assert len(blocking_conflicts(blocking, threshold=Severity.MEDIUM)) == 1

    passing = [_entry(Severity.LOW), _entry(Severity.MEDIUM, "at-threshold")]
    assert compose_gate_blocks(passing, threshold=Severity.MEDIUM) is False
    assert blocking_conflicts(passing, threshold=Severity.MEDIUM) == []


def test_threshold_has_a_configured_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every caller inventing its own threshold was half of issue #14.

    `_env_file=None` plus a cleared env var on purpose: a bare `Settings()` reads
    the ambient environment and any local `.env`, so this test would fail for any
    developer who followed `.env.example` - which the same change ships.
    """
    monkeypatch.delenv("PROCUREMENT_COMPOSE_GATE_THRESHOLD", raising=False)
    assert _isolated_settings().compose_gate_threshold is Severity.MEDIUM


def test_threshold_reads_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The path .env.example documents, and the one nothing covered."""
    monkeypatch.setenv("PROCUREMENT_COMPOSE_GATE_THRESHOLD", "3")
    assert _isolated_settings().compose_gate_threshold is Severity.HIGH


def test_the_gate_cannot_be_disabled_by_configuration() -> None:
    """With a strict '>', threshold=CRITICAL would switch the gate off entirely.

    Decision 2 requires the override to be a recorded, audited decision; an
    environment variable is neither, so CRITICAL is out of range."""
    with pytest.raises(ValidationError):
        _isolated_settings(compose_gate_threshold=Severity.CRITICAL)


def test_severity_is_required_on_a_queue_entry() -> None:
    """A default at or below the gate threshold would make a forgotten severity
    silently unable to block - the one value that fails open."""
    payload = _entry(Severity.HIGH).model_dump()
    payload.pop("severity")
    with pytest.raises(ValidationError):
        ConflictQueueEntry(**payload)


def test_a_resolved_critical_conflict_does_not_block() -> None:
    """The parameter was named `unresolved` and the filter only checked severity,
    so a CRITICAL conflict a human had already decided went on refusing to
    compose - with no way to clear it."""
    entry = _entry(Severity.CRITICAL).model_copy(
        update={
            "resolution": Resolution(
                action=ResolutionAction.KEEP_SYSTEM_OF_RECORD,
                resolved_by="procurement.lead",
                resolved_at=datetime(2026, 1, 2, tzinfo=UTC),
                rationale="Contract supersedes the CEC listing.",
            )
        }
    )
    assert blocking_conflicts([entry], threshold=Severity.MEDIUM) == []
    assert not compose_gate_blocks([entry], threshold=Severity.MEDIUM)


def test_an_unresolved_critical_conflict_still_blocks() -> None:
    assert compose_gate_blocks([_entry(Severity.CRITICAL)], threshold=Severity.MEDIUM)
