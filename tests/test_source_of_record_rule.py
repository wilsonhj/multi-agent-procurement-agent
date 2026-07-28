"""AC-2: a web value contradicting an ingested spec value raises a conflict, and
the system-of-record value is unchanged.

This is the invariant the whole design rests on, so it is tested before anything
is implemented on top of it.
"""

import pytest

from procurement_agent.schema import CanonicalField, SourceRef, SourceTier
from procurement_agent.services.conflict_hitl import (
    AutonomousOverwriteError,
    assert_no_autonomous_overwrite,
)


def _record(value: object) -> CanonicalField:
    return CanonicalField(
        value=value,
        unit="Wp",
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1", page=3),
        confidence=0.95,
    )


def _web(value: object) -> CanonicalField:
    return CanonicalField(
        value=value,
        unit="Wp",
        source_tier=SourceTier.WEB_SUPPLEMENT,
        source_ref=SourceRef(url="https://example.com/datasheet", page_title="Datasheet"),
        confidence=0.70,
    )


def test_web_cannot_overwrite_system_of_record() -> None:
    with pytest.raises(AutonomousOverwriteError):
        assert_no_autonomous_overwrite(_record(650), _web(655))


def test_web_may_fill_an_empty_field() -> None:
    """FR-WEB-03: filling a gap is allowed; only overwriting is forbidden."""
    assert_no_autonomous_overwrite(None, _web(655))
    assert_no_autonomous_overwrite(_record(None), _web(655))


def test_record_may_overwrite_web() -> None:
    """The rule is directional. Ingesting a real datasheet supersedes a web guess."""
    assert_no_autonomous_overwrite(_web(655), _record(650))


def test_record_may_overwrite_record() -> None:
    """Two ingested documents disagreeing is an inter-document conflict, handled
    by the queue rather than by this guard."""
    assert_no_autonomous_overwrite(_record(650), _record(655))
