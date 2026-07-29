"""Tolerance as the source printed it — issue #2.

There is no single industry convention. Trina prints `0~+5W`, Jinko prints
`0~+3%`, Canadian Solar prints `0~+10W`. Code assuming either convention is
wrong for at least two of the five largest suppliers, so the band is stored as
written and resolved against a nominal only at comparison time.
"""

import pytest
from pydantic import ValidationError

from procurement_agent.schema import (
    CanonicalField,
    ConflictCandidate,
    DeclaredBand,
    SourceRef,
    SourceTier,
    ToleranceKind,
)
from procurement_agent.services.conflict_hitl import comparison_pairs

#: `Power Tolerance 0 ~ +5` — Trina Vertex N NEG21C.20.
TRINA = DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE, unit="W")
#: `Power tolerance 0~+3%` — Jinko Tiger Neo 78HL4-BDV, one line covering 605–625 W.
JINKO = DeclaredBand(low=0.0, high=3.0, kind=ToleranceKind.RELATIVE)
#: `Power Tolerance 0 ~ + 10 W` — Canadian Solar HiKu6. Wider than one bin step.
CANADIAN = DeclaredBand(low=0.0, high=10.0, kind=ToleranceKind.ABSOLUTE, unit="W")


def test_a_relative_band_is_not_multiplied_out_at_extraction() -> None:
    """The contract's rule. One printed tolerance covers the whole 605–625 W
    family, so resolving early gives 18.15 W at one bin and 18.75 W at another —
    a disagreement between two rows whose source text is character-identical."""
    assert JINKO.high == 3.0
    assert JINKO.resolve(605.0) != JINKO.resolve(625.0)
    assert JINKO.resolve(620.0) == pytest.approx((620.0, 638.6))


def test_percent_and_watts_are_not_interchangeable() -> None:
    """3% of 620 W is 18.6 W — nearly four 5 W bin steps. This is the whole issue."""
    assert JINKO.resolve(620.0)[1] - 620.0 > 3 * (TRINA.resolve(620.0)[1] - 620.0)


def test_a_relative_band_on_a_negative_nominal_is_not_inverted() -> None:
    """A Pmax temperature coefficient is negative, so `low` maps to the *upper*
    bound. Returning the offsets unswapped hands the caller an interval whose
    low exceeds its high, which intersects nothing and silently agrees with
    nothing."""
    band = DeclaredBand(low=-3.0, high=3.0, kind=ToleranceKind.RELATIVE)
    low, high = band.resolve(-0.29)
    assert low < high
    assert low == pytest.approx(-0.2987)
    assert high == pytest.approx(-0.2813)


def test_touching_ranges_agree() -> None:
    """650 W and 655 W modules both declared `0~+5W` guarantee [650,655] and
    [655,660]. A part measuring exactly 655 W satisfies both labels."""
    assert TRINA.agrees(650.0, TRINA, 655.0)
    assert not TRINA.agrees(650.0, TRINA, 656.0)


def test_a_band_wider_than_the_bin_step_overlaps_by_construction() -> None:
    """Canadian Solar's `0~+10W` is two 5 W bin steps, so a nominal 650 and a
    nominal 655 have overlapping guaranteed ranges as printed. Not a defect to
    correct — a fact the comparison has to tolerate."""
    assert CANADIAN.agrees(650.0, CANADIAN, 655.0)
    assert CANADIAN.agrees(650.0, CANADIAN, 660.0)


def test_a_missing_band_on_the_other_side_is_a_point_not_a_free_pass() -> None:
    """No printed band means no evidence of one. Treating the other nominal as
    exact can raise a conflict a shared band would have absorbed — one extra
    queue item, where the permissive reading silently merges two SKUs."""
    assert TRINA.agrees(650.0, None, 653.0)
    assert not TRINA.agrees(650.0, None, 656.0)


def test_mismatched_conventions_still_compare() -> None:
    """Trina's absolute against Jinko's relative: the point of resolving late."""
    assert TRINA.agrees(650.0, JINKO, 652.0)
    assert not TRINA.agrees(650.0, JINKO, 700.0)


def test_an_absolute_band_without_a_unit_is_rejected() -> None:
    """`0 ~ +5` is not a quantity. The canonical field knows its unit, so an
    extractor emitting the band has one to write."""
    with pytest.raises(ValidationError):
        DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE)


def test_a_relative_band_may_not_carry_a_physical_unit() -> None:
    """`3` with unit `W` alongside kind=relative is the extractor confusing the
    two conventions, which is exactly the defect #2 reports."""
    with pytest.raises(ValidationError):
        DeclaredBand(low=0.0, high=3.0, kind=ToleranceKind.RELATIVE, unit="W")
    assert DeclaredBand(low=0.0, high=3.0, kind=ToleranceKind.RELATIVE, unit="%").unit == "%"


def test_an_inverted_band_is_rejected() -> None:
    """`0 ~ +5` read backwards produces an empty interval that agrees with
    nothing, including itself — every comparison would become a conflict."""
    with pytest.raises(ValidationError):
        DeclaredBand(low=5.0, high=0.0, kind=ToleranceKind.ABSOLUTE, unit="W")


def test_a_non_finite_bound_is_rejected() -> None:
    """A NaN bound compares false against everything, so `low <= other_high`
    fails both ways and the band would silently declare every value in
    agreement — the failure direction that cannot be reviewed."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            DeclaredBand(low=0.0, high=bad, kind=ToleranceKind.ABSOLUTE, unit="W")


def test_a_band_is_reflexive() -> None:
    """A value must agree with itself, or `power_tolerance` could never round-trip
    through the store without raising a conflict against its own prior state."""
    for band in (TRINA, JINKO, CANADIAN):
        for nominal in (650.0, -0.29, 0.0):
            assert band.agrees(nominal, band, nominal)


def test_a_band_survives_a_store_round_trip() -> None:
    """FR-OUT-06: composition is a pure function of the store, so a band that
    reloads differently moves the conflict queue."""
    revived = DeclaredBand.model_validate_json(JINKO.model_dump_json())
    assert revived == JINKO
    assert revived.resolve(620.0) == JINKO.resolve(620.0)


def test_a_band_is_a_field_value_not_a_second_key_on_the_field() -> None:
    """The contract types `power_tolerance` *as* a DeclaredBand rather than
    hanging a `declared_tolerance` off every field (issue #2 proposed the
    latter). It therefore carries its own provenance and conflict state, and
    there is no second copy to keep in sync."""
    field = CanonicalField(
        value=TRINA,
        unit=None,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="trina-neg21c"),
        confidence=0.95,
    )
    assert isinstance(field.value, DeclaredBand)
    assert "declared_tolerance" not in CanonicalField.model_fields


def test_two_bands_order_canonically_as_candidates() -> None:
    """`_ordering_key` reprs the value, so bands must order without a special
    case — otherwise two candidates differing only in their band tie, and stable
    sort leaks arrival order back into the queue (the `verbatim_value` bug)."""

    def candidate(band: DeclaredBand, doc: str) -> ConflictCandidate:
        return ConflictCandidate(
            value=band,
            unit=None,
            source_tier=SourceTier.SYSTEM_OF_RECORD,
            source_ref=SourceRef(document_id=doc),
            confidence=0.9,
        )

    a, b = candidate(TRINA, "datasheet"), candidate(CANADIAN, "supply-agreement")
    forward = comparison_pairs([a, b])
    backward = comparison_pairs([b, a])
    assert len(forward) == 1
    assert [(x.value, y.value) for x, y in forward] == [(x.value, y.value) for x, y in backward]
