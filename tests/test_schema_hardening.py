"""What the schema refuses to accept — the field-name door, and NaN.

Issue #16 closed the condition *vocabulary*: a token outside `basis`'s enum is a
validation failure rather than a silent group of one. The **field names** one
level up were still open, and they are the same defect through a different door:

    Condition(ambient_temperature_c=30.0)

is silently accepted (the real field is `temperature_c`, and the plan's own prose
says "reference ambient"), the resulting condition is `is_unstated()`, and it
reports `comparable_with` True against a genuine 40 degC reading. That is D-1's
silent merge, arrived at by misspelling rather than by omission - and nothing
surfaces a comparison that happened when it should not have.

The second half is `CanonicalField.value`, typed `object | None` with no
finiteness check while `encoding.encode_value`'s own error message says "The
schema rejects these at construction". It did not, so a store could hold a row
`project_store` cannot project - and the failure surfaces at composition time,
far from the extractor that wrote it.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from procurement_agent.schema import (
    CanonicalField,
    ComponentCategory,
    Condition,
    ConditionDimensions,
    ConflictCandidate,
    ConflictClass,
    ConflictQueueEntry,
    DeclaredBand,
    MeasurementBasis,
    Resolution,
    ResolutionAction,
    Severity,
    SourceRef,
    SourceTier,
    ToleranceKind,
    UnencodableValueError,
    encode_value,
)
from procurement_agent.schema.registry import condition_dimensions_for

REF = SourceRef(document_id="doc-a")


def _field(value: object = 650.0) -> CanonicalField:
    return CanonicalField(
        value=value,
        unit="Wp",
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=REF,
        confidence=0.9,
    )


# --------------------------------------------------------------------------
# extra="forbid": the field-name door
# --------------------------------------------------------------------------


def test_a_misspelt_condition_dimension_is_refused_rather_than_dropped() -> None:
    """The measured case. `ambient_temperature_c` is a plausible name for a field
    actually called `temperature_c` - the plan's prose calls it "reference
    ambient" - and it was accepted, dropped, and the resulting condition then
    compared equal to everything."""
    with pytest.raises(ValidationError):
        Condition(ambient_temperature_c=30.0)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Condition(bassis="stc")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ConditionDimensions(ambient_temperature_c=30.0)  # type: ignore[call-arg]


def test_the_dropped_dimension_was_a_silent_merge_not_a_loud_one() -> None:
    """Why it matters, stated as the behaviour rather than as the constructor.

    A dropped `temperature_c` leaves an unstated condition, and an unstated
    condition is comparable with *every* stated one - which is deliberate and
    right for a datasheet that genuinely says nothing, and exactly wrong for one
    that said 30 degC into a misspelt keyword."""
    honest = Condition(temperature_c=30.0)
    reading = Condition(temperature_c=40.0)
    dimensions = condition_dimensions_for("rated_ac_power")
    assert not honest.comparable_with(reading, dimensions=dimensions)
    # The typo used to produce `Condition()`, which is comparable with both:
    assert Condition().comparable_with(reading, dimensions=dimensions)
    assert Condition().is_unstated()


def test_note_is_still_spelled_note() -> None:
    """`extra="forbid"` must not have closed the door on the fields that are
    real. `note` and `derived` live on `Condition` and not on
    `ConditionDimensions`, which is what keeps them out of `grouping_key`."""
    assert Condition(note="page 3", derived=frozenset({"basis"})).note == "page 3"
    with pytest.raises(ValidationError):
        ConditionDimensions(note="page 3")  # type: ignore[call-arg]


#: Every model in `schema.field`, with a minimal legal payload for each. Written
#: out rather than discovered, because the point is that *this list* is complete:
#: a model added to the module and not added here is a door left open, and a
#: generated list would close it silently by never noticing.
_MODELS: list[tuple[type[BaseModel], dict[str, object]]] = [
    (SourceRef, {"document_id": "doc-a"}),
    (
        Resolution,
        {
            "action": ResolutionAction.KEEP_SYSTEM_OF_RECORD,
            "resolved_by": "reviewer",
            "resolved_at": datetime(2026, 1, 1, tzinfo=UTC),
            "rationale": "because",
        },
    ),
    (DeclaredBand, {"low": 0.0, "high": 5.0, "kind": ToleranceKind.ABSOLUTE, "unit": "W"}),
    (ConditionDimensions, {"basis": MeasurementBasis.STC}),
    (Condition, {"basis": MeasurementBasis.STC}),
    (
        CanonicalField,
        {
            "value": 650.0,
            "source_tier": SourceTier.SYSTEM_OF_RECORD,
            "source_ref": REF,
            "confidence": 0.9,
        },
    ),
    (
        ConflictCandidate,
        {
            "value": 650.0,
            "unit": "Wp",
            "source_tier": SourceTier.SYSTEM_OF_RECORD,
            "source_ref": REF,
            "confidence": 0.9,
        },
    ),
    (
        ConflictQueueEntry,
        {
            "entry_id": "e-1",
            "field_name": "nameplate_power",
            "supplier": "Trina",
            "model": "NEG21C.20",
            "component_category": ComponentCategory.PV_MODULES,
            "conflict_class": ConflictClass.INTER_DOCUMENT,
            "severity": Severity.HIGH,
            "candidates": [],
            "explanation": "two sheets disagree",
            "detected_at": datetime(2026, 1, 1, tzinfo=UTC),
        },
    ),
]


@pytest.mark.parametrize("model,payload", _MODELS, ids=[model.__name__ for model, _ in _MODELS])
def test_no_model_in_the_schema_silently_drops_a_key(
    model: type[BaseModel], payload: dict[str, object]
) -> None:
    """One door per model. Each payload is legal on its own - asserted first, so
    a fixture that was already invalid cannot pass this by raising for the wrong
    reason - and then fails with one key nobody declared."""
    assert model(**payload)
    with pytest.raises(ValidationError):
        model(**payload, definitely_not_a_field=1)


@pytest.mark.parametrize("model,payload", _MODELS, ids=[model.__name__ for model, _ in _MODELS])
def test_the_same_door_is_shut_on_the_deserialisation_path(
    model: type[BaseModel], payload: dict[str, object]
) -> None:
    """`model_validate` is the route a stored row comes back through, and it is
    the one that matters: a constructor typo is a bug someone is about to notice,
    while a stray key in a persisted record is a schema drift nobody sees."""
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "definitely_not_a_field": 1})


def test_evolve_still_names_the_field_it_did_not_recognise() -> None:
    """`extra="forbid"` makes `model_validate` raise where it used to drop, so
    `evolve`'s own check is now belt-and-braces - and worth keeping, because its
    message lists the known fields and pydantic's does not. The point of the
    check was never the raise, it was the diagnosis."""
    with pytest.raises(ValueError, match="conflict_stauts"):
        _field().evolve(conflict_stauts="resolved")


# --------------------------------------------------------------------------
# NaN: the value the encoder refuses and the schema accepted
# --------------------------------------------------------------------------


def test_the_encoder_still_says_the_schema_rejects_these() -> None:
    """The claim under test, read out of the encoder itself. If this message ever
    stops saying it, the assertions below are enforcing a promise nobody makes."""
    with pytest.raises(UnencodableValueError, match="schema rejects these at construction"):
        encode_value(float("nan"))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_canonical_field_refuses_the_value_the_encoder_refuses(bad: float) -> None:
    """A store that can hold a row `project_store` cannot project fails at
    composition time, far from the extractor that wrote it - and NaN is the worst
    of the three, because it is not equal to itself, so every "is this the value
    we stored" check the pipeline makes says no."""
    with pytest.raises(ValidationError):
        _field(bad)
    with pytest.raises(ValidationError):
        ConflictCandidate(
            value=bad,
            unit="Wp",
            source_tier=SourceTier.SYSTEM_OF_RECORD,
            source_ref=REF,
            confidence=0.9,
        )


@pytest.mark.parametrize(
    "bad",
    [
        [1.0, float("nan")],
        {"a": float("inf")},
        (1.0, [2.0, float("nan")]),
        [{"deep": [float("-inf")]}],
        Decimal("NaN"),
        [Decimal("Infinity")],
    ],
    ids=["list", "dict", "nested-tuple", "deeply-nested", "decimal", "decimal-in-list"],
)
def test_the_check_reaches_inside_a_container(bad: object) -> None:
    """`harmonic_spectrum` is `dict[int, float]` and eighteen contract rows are
    lists, so a shallow check would guard the least likely case and miss the ones
    the contract actually declares. `encode_value` walks the whole structure, so
    a schema that only checked the top level would still be handing it a value it
    refuses."""
    with pytest.raises(ValidationError):
        _field(bad)


def test_the_values_the_contract_does_declare_still_go_in() -> None:
    """The guard direction. Rejecting NaN must not reject a `DeclaredBand`, a
    harmonic spectrum, a certification list or a plain string.

    `-0.0` is the case worth naming: it is finite, so it goes in unchanged, and
    the fold to `+0.0` stays where it already lives - in `encode_value`, which
    calls it an *injectivity* fix rather than a cosmetic one. Folding here as
    well would be a second statement of one rule, and the one that drifts."""
    assert _field(650.0).value == 650.0
    assert _field(Decimal("650.0")).value == Decimal("650.0")
    assert _field(["IEC 61215", "UL 61730"]).value == ["IEC 61215", "UL 61730"]
    assert _field({3: 1.2, 5: 0.8}).value == {3: 1.2, 5: 0.8}
    band = DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE, unit="W")
    assert _field(band).value is band
    assert _field(None).value is None
    assert _field(True).value is True
    assert math.copysign(1.0, _field(-0.0).value) == -1.0  # type: ignore[arg-type]
    assert math.copysign(1.0, encode_value(_field(-0.0).value)) == 1.0  # type: ignore[arg-type]


def test_every_value_a_canonical_field_accepts_can_be_encoded() -> None:
    """The property the two halves add up to, rather than a list of cases: the
    schema's promise is exactly that anything it stores, the C6 projection can
    project. Stated over the values the contract's own type column declares."""
    for value in (
        650.0,
        650,
        Decimal("650.0"),
        "n_topcon",
        True,
        None,
        ["IEC 61215"],
        {3: 1.2},
        DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE, unit="W"),
    ):
        assert encode_value(_field(value).value) is not None or value is None
