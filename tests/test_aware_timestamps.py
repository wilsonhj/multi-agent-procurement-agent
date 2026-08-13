"""Every stored timestamp names an instant, checked where it is constructed.

Track 1b's finding: `encode_value` refuses a naive datetime, because a naive
datetime is a wall-clock reading with no zone and so identifies no moment. The
schema accepted one anyway, so `SourceRef(retrieved_at=<naive>)` validated
cleanly and then raised from the conflict sort path - a value the schema called
legal that the canonical encoder could not encode. `repr()` had ordered it
without complaint before D-14, which is why nothing noticed.

Raising is the right direction and the constraint belongs at construction: the
honest fix is to attach the zone at the boundary that produced the timestamp,
and a validator is the first place that can say so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from procurement_agent.schema import SourceDocument, SourceRef
from procurement_agent.schema.encoding import encode_value
from procurement_agent.schema.enums import DocumentType

NAIVE = datetime(2026, 8, 4, 12, 0, 0)
AWARE = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)


def test_a_naive_retrieved_at_is_refused() -> None:
    """FR-WEB-02 records *when* a web value was fetched, and FR-WEB-04's temporal
    comparisons rest on that answer being a moment rather than a reading."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        SourceRef(url="https://example.invalid/x", retrieved_at=NAIVE)


def test_an_aware_retrieved_at_survives_the_encoder() -> None:
    """The other half of the rejection: a constraint that refused everything
    would satisfy the test above, and the point is that what the schema accepts
    is exactly what `encode_value` can encode."""
    ref = SourceRef(url="https://example.invalid/x", retrieved_at=AWARE)
    encoded = encode_value(ref)
    assert isinstance(encoded, dict)
    assert encoded["retrieved_at"] == {"$datetime": "2026-08-04T12:00:00.000000Z"}


def test_an_offset_that_is_not_utc_is_still_an_instant() -> None:
    """The constraint is awareness, not UTC. `14:00+02:00` and `12:00Z` are one
    instant written two ways, and `_rfc3339` converts before formatting - so
    refusing a non-UTC zone here would reject a correct timestamp and push
    callers into converting by hand, which is where offsets get lost."""
    berlin = datetime(2026, 8, 4, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    ref = SourceRef(url="https://example.invalid/x", retrieved_at=berlin)
    assert encode_value(ref) == encode_value(
        SourceRef(url="https://example.invalid/x", retrieved_at=AWARE)
    )


def test_retrieved_at_stays_optional() -> None:
    """A document reference has no fetch time at all, and the fixtures all carry
    `retrieved_at: null`. A validator that made it required would invalidate
    every committed claim fixture."""
    assert SourceRef(document_id="doc-1").retrieved_at is None


def test_the_same_constraint_holds_on_a_source_document() -> None:
    """The adjacent instance of the identical defect. `SourceDocument` carries
    two datetimes - `ingested_at`, and `data_vintage` which FR-OUT-06 reports and
    temporal conflict detection compares - and nothing constructs one yet, which
    is precisely why it would have been fixed late.

    Scoping the fix to the file that was named rather than to the defect is the
    mistake Track 0 recorded twice, so both are closed here.
    """
    with pytest.raises(ValidationError, match="timezone-aware"):
        SourceDocument(
            document_id="doc-1",
            content_hash="sha256:abc",
            source_uri="file:///doc-1.pdf",
            document_type=DocumentType.SPEC_SHEET,
            ingested_at=NAIVE,
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        SourceDocument(
            document_id="doc-1",
            content_hash="sha256:abc",
            source_uri="file:///doc-1.pdf",
            document_type=DocumentType.SPEC_SHEET,
            ingested_at=AWARE,
            data_vintage=NAIVE,
        )
    document = SourceDocument(
        document_id="doc-1",
        content_hash="sha256:abc",
        source_uri="file:///doc-1.pdf",
        document_type=DocumentType.SPEC_SHEET,
        ingested_at=AWARE,
    )
    assert document.data_vintage is None
