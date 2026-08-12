"""The C6 canonical projection (D-14), and the properties the hash rests on.

Written before the implementation, so every assertion here failed first. The four
that carry the contract, rather than merely exercising it:

1. **Policy is inside the hash.** The workbook is a function of *(store, policy)*,
   so hashing only the store certifies AC-7 while the artifact silently varies
   with configuration. The computed `CellFlag`s go in too, not merely the
   threshold that produced them - `flags_for`'s *code* is policy, and a change to
   it would otherwise alter the rendered workbook under an unchanged hash.
2. **`generated_on` folds from inside the projection.** Not from a parallel query
   over the store, which drifts silently the day someone adds a row type and
   forgets it. The test recomputes the stamp from the *published bytes* and
   nothing else, which is the strongest form of the property: a reader holding
   only the artifact can check it.
3. **The zero-document sentinel is null**, never an epoch or a placeholder.
4. **No `repr()` artifact reaches the bytes** - concretely, no `<`. That is the
   A-6 defect class, which has hit this repo three times.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from procurement_agent.schema import (
    CanonicalField,
    CellFlag,
    ComponentCategory,
    ComponentInstance,
    Condition,
    ConflictCandidate,
    ConflictClass,
    ConflictQueueEntry,
    ConflictStatus,
    DeclaredBand,
    DocumentType,
    EfficiencyWeighting,
    MeasurementBasis,
    Resolution,
    ResolutionAction,
    Severity,
    SourceDocument,
    SourceRef,
    SourceTier,
    ToleranceKind,
    UnencodableValueError,
)
from procurement_agent.services.output import projection as projection_module
from procurement_agent.services.output.projection import (
    PROJECTION_VERSION,
    STORE_WRITTEN_AT,
    ProjectionPolicy,
    fold_generated_on,
    project_store,
    projection_bytes,
    projection_digest,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "workbooks"
FIXTURE_JSON = FIXTURE_DIR / "two-supplier-pv-store.json"
#: Named for what it covers. The committed `.json` is stored in the *fixtures'*
#: indented serialisation, because a single-line 21 kB artifact is unreviewable in
#: a diff and the whole fixture set is byte-compared; D-14's hash is over the
#: compact bytes. So this digest is deliberately **not** `sha256sum` of the file,
#: and the filename says so rather than leaving a reader to find out by running it.
FIXTURE_SHA256 = FIXTURE_DIR / "two-supplier-pv-store.canonical-bytes.sha256"

#: The fixture pins its own policy. D-14: production re-tuning of tau must never
#: re-baseline a golden hash, and `tasks.md` sequences tau tuning after WP-B -
#: exactly when fixture churn would otherwise be worst.
FIXTURE_POLICY = ProjectionPolicy(policy_version="fixture-2026-08-12", confidence_threshold=0.80)


def _at(text: str) -> datetime:
    """A store timestamp. Fixed, never `now()` - these files are byte-compared."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


SUNGROW_INGESTED = _at("2026-07-01T09:15:30.000000")
TRINA_INGESTED = _at("2026-07-02T14:22:05.500000")
#: Deliberately later than either ingest, so the fixture demonstrates D-14's own
#: table row: `max(ingested_at)` would date the artifact by an ingest that is no
#: longer its newest fact.
CONFLICT_DETECTED = _at("2026-07-03T08:00:00.000000")
WEB_RETRIEVED = _at("2026-06-28T11:00:00.000000")


def _stc() -> Condition:
    return Condition(basis=MeasurementBasis.STC)


def _ambient(celsius: float) -> Condition:
    return Condition(temperature_c=celsius)


def _sungrow_ref(page: int, section: str) -> SourceRef:
    return SourceRef(
        document_id="syn-sungrow-ds",
        page=page,
        section=section,
        extractor_version="fixture@1",
    )


def _trina_ref(page: int, section: str) -> SourceRef:
    return SourceRef(
        document_id="syn-trina-ds",
        page=page,
        section=section,
        extractor_version="fixture@1",
    )


def _trina_web_ref() -> SourceRef:
    return SourceRef(
        url="https://distributor.example.invalid/tsm-neg21c",
        page_title="TSM-NEG21C.20 product page",
        retrieved_at=WEB_RETRIEVED,
        source_authority="distributor listing",
        extractor_version="fixture@1",
    )


def synthetic_inverter() -> ComponentInstance:
    """Sungrow SG350HX, carrying D-1's trio.

    Synthetic per NFR-03 and `tests/fixtures/README.md`: the identifiers are from
    published specifications, the document ids and the extractor are invented, and
    nothing here is contract or pricing material.

    The trio is the reason this fixture exists. One datasheet stating one
    parameter at three ambients is three legitimate values under
    `fields["rated_ac_power"]`, so the projection is exercised on the
    list-valued case rather than the easy one-value-per-key one.
    """
    return ComponentInstance(
        supplier="Sungrow Power Supply Co., Ltd.",
        model="SG350HX",
        component_category=ComponentCategory.INVERTERS_PCS,
        nameplate=352.0,
        surrogate_id="syn-inverter-0001",
        manufacturer_key="sungrow",
        model_family="sg350hx",
        fields={
            "rated_ac_power": [
                CanonicalField(
                    value=352.0,
                    unit="kVA",
                    verbatim_value="352 kVA @30°C",
                    condition=_ambient(30.0),
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_sungrow_ref(2, "Table 2: AC Output"),
                    confidence=0.95,
                ),
                CanonicalField(
                    value=320.0,
                    unit="kVA",
                    verbatim_value="320 kVA @40°C",
                    condition=_ambient(40.0),
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_sungrow_ref(2, "Table 2: AC Output"),
                    confidence=0.95,
                ),
                CanonicalField(
                    value=295.0,
                    unit="kVA",
                    verbatim_value="295 kVA @50°C",
                    condition=_ambient(50.0),
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_sungrow_ref(2, "Table 2: AC Output"),
                    confidence=0.95,
                ),
            ],
            # `list[str]` is a real contract type on 18 fields. It is in the
            # fixture because D-14's table originally omitted `list` entirely.
            "certifications": [
                CanonicalField(
                    value=["IEC 62109-1", "IEC 62109-2", "UL 1741 SB"],
                    verbatim_value="IEC 62109-1/-2, UL 1741 SB",
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_sungrow_ref(4, "Certifications"),
                    confidence=0.90,
                )
            ],
            "cec_efficiency": [
                CanonicalField(
                    value=98.5,
                    unit="%",
                    verbatim_value="98.5 %",
                    condition=Condition(weighting=EfficiencyWeighting.CEC),
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_sungrow_ref(2, "Table 3: Efficiency"),
                    confidence=0.93,
                )
            ],
        },
    )


def synthetic_module() -> ComponentInstance:
    """Trina TSM-NEG21C.20, carrying the disagreement and three of the four flags.

    `nameplate_power` holds a system-of-record value and a web value that
    genuinely disagree under the same stated condition, both left OPEN - so the
    projection carries UNRESOLVED_CONFLICT and WEB_SUPPLEMENTED. `module_efficiency`
    sits under the pinned threshold (LOW_CONFIDENCE) and `bifaciality_factor` is
    an established absence (MISSING_DATA). A fixture that exercised no flag would
    let the whole of decision 1 regress green.
    """
    return ComponentInstance(
        supplier="Trina Solar Co., Ltd",
        model="TSM-NEG21C.20",
        component_category=ComponentCategory.PV_MODULES,
        nameplate=650.0,
        surrogate_id="syn-module-0001",
        manufacturer_key="trina_solar",
        model_family="tsm_neg21c",
        fields={
            "nameplate_power": [
                CanonicalField(
                    value=650.0,
                    unit="Wp",
                    verbatim_value="650 W",
                    condition=_stc(),
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_trina_ref(1, "Electrical Data (STC)"),
                    confidence=0.96,
                    conflict_status=ConflictStatus.OPEN,
                ),
                CanonicalField(
                    value=655.0,
                    unit="Wp",
                    verbatim_value="655 W",
                    condition=_stc(),
                    source_tier=SourceTier.WEB_SUPPLEMENT,
                    source_ref=_trina_web_ref(),
                    confidence=0.72,
                    conflict_status=ConflictStatus.OPEN,
                ),
            ],
            # A `DeclaredBand` value, so the fixture covers the model-recursion
            # case rather than only scalars.
            "power_tolerance": [
                CanonicalField(
                    value=DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE, unit="W"),
                    verbatim_value="0 ~ +5 W",
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_trina_ref(1, "Electrical Data (STC)"),
                    confidence=0.94,
                )
            ],
            "cell_technology": [
                CanonicalField(
                    value="n_topcon",
                    verbatim_value="n-type TOPCon",
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_trina_ref(1, "Mechanical Data"),
                    confidence=0.91,
                )
            ],
            "module_efficiency": [
                CanonicalField(
                    value=23.0,
                    unit="%",
                    verbatim_value="23.0 %",
                    condition=_stc(),
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_trina_ref(1, "Electrical Data (STC)"),
                    confidence=0.55,
                )
            ],
            "bifaciality_factor": [
                CanonicalField(
                    value=None,
                    unit="%",
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_trina_ref(1, "Electrical Data (STC)"),
                    confidence=0.30,
                )
            ],
            "product_warranty_years": [
                CanonicalField(
                    value=25,
                    unit="yr",
                    verbatim_value="25 years",
                    source_tier=SourceTier.SYSTEM_OF_RECORD,
                    source_ref=_trina_ref(3, "Warranty"),
                    confidence=0.88,
                )
            ],
        },
    )


def synthetic_conflict() -> ConflictQueueEntry:
    """The queue entry the Trina pair projects to.

    `severity` is written down rather than recomputed. D-14 routes this track
    around `conflict_hitl` deliberately - the projection sorts by
    `_ordering_key`'s *field sequence*, never by that function - so importing it
    here to cross-check a value would reintroduce the dependency at test time and
    couple this fixture to Track 1b's re-baselining.
    """
    return ConflictQueueEntry(
        entry_id="syn-conflict-0001",
        field_name="nameplate_power",
        supplier="Trina Solar Co., Ltd",
        model="TSM-NEG21C.20",
        component_category=ComponentCategory.PV_MODULES,
        conflict_class=ConflictClass.RECORD_VS_WEB,
        severity=Severity.MEDIUM,
        candidates=[
            ConflictCandidate(
                value=650.0,
                unit="Wp",
                verbatim_value="650 W",
                condition=_stc(),
                source_tier=SourceTier.SYSTEM_OF_RECORD,
                source_ref=_trina_ref(1, "Electrical Data (STC)"),
                confidence=0.96,
            ),
            ConflictCandidate(
                value=655.0,
                unit="Wp",
                verbatim_value="655 W",
                condition=_stc(),
                source_tier=SourceTier.WEB_SUPPLEMENT,
                source_ref=_trina_web_ref(),
                confidence=0.72,
            ),
        ],
        explanation=(
            "The datasheet states 650 W at STC; a distributor listing states 655 W "
            "under the same condition. FR-HITL-02 forbids auto-arbitration between "
            "a system-of-record value and a web value."
        ),
        detected_at=CONFLICT_DETECTED,
    )


def synthetic_sources() -> list[SourceDocument]:
    """Two ingested documents.

    `data_vintage` is set on both and is *publication* date, not a store write -
    D-14 lists four write columns and this is not one of them. A fold that
    collected every datetime in sight would let a future-dated revision stamp the
    workbook with a date nothing was written on.
    """
    return [
        SourceDocument(
            document_id="syn-sungrow-ds",
            content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000001",
            source_uri="file:///synthetic/sungrow-sg350hx.pdf",
            document_type=DocumentType.SPEC_SHEET,
            ingested_at=SUNGROW_INGESTED,
            data_vintage=_at("2026-03-01T00:00:00.000000"),
        ),
        SourceDocument(
            document_id="syn-trina-ds",
            content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000002",
            source_uri="file:///synthetic/trina-tsm-neg21c.pdf",
            document_type=DocumentType.SPEC_SHEET,
            ingested_at=TRINA_INGESTED,
            data_vintage=_at("2025-11-20T00:00:00.000000"),
        ),
    ]


def synthetic_store() -> dict[str, Any]:
    """The T0.5 store, rebuilt from scratch on every call.

    Rebuilt rather than shared, so `test_two_generations_...` compares two
    projections of two *distinct* object graphs. Projecting one graph twice would
    pass even if the projection cached something on the objects.
    """
    return {
        "components": [synthetic_inverter(), synthetic_module()],
        "conflicts": [synthetic_conflict()],
        "sources": synthetic_sources(),
    }


def _rows(projected: Mapping[str, object], section: str) -> list[Any]:
    """Narrow one top-level array of a projection.

    `project_store` returns `dict[str, object]` on purpose - a projection is
    encoded JSON, not a typed model, so `value` legitimately holds a `$decimal`
    tag on one row and a bare float on the next. A test reading into it says so
    once, here, rather than casting at every index.
    """
    rows = projected[section]
    assert isinstance(rows, list)
    return rows


def _project(**overrides: Any) -> dict[str, Any]:
    store = synthetic_store() | overrides
    policy = overrides.pop("policy", FIXTURE_POLICY)
    return project_store(
        components=store["components"],
        conflicts=store["conflicts"],
        sources=store["sources"],
        policy=policy,
    )


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------


def test_the_projection_has_d14s_top_level_shape() -> None:
    """D-14 fixes five top-level keys and judgement call 2 adds `generated_on`.

    Asserted as an exact set rather than a subset: an extra top-level key is a
    silent format change that re-baselines every golden hash, which is the whole
    class `projection_version` exists to make explicit.
    """
    assert set(_project()) == {
        "projection_version",
        "policy",
        "components",
        "conflicts",
        "sources",
        "generated_on",
    }
    assert _project()["projection_version"] == PROJECTION_VERSION == 1


def test_the_bytes_are_utf8_with_no_ascii_escaping() -> None:
    """`ensure_ascii=False` is part of D-14's byte format, not a preference.

    The Sungrow verbatim values carry `°`; the default `ensure_ascii=True`
    rewrites it to a `\\u00b0` escape - different bytes, identical structure. The
    committed fixtures already record that an earlier byte check missed exactly
    this.
    """
    raw = projection_bytes(_project())
    assert "352 kVA @30°C".encode() in raw
    # What `ensure_ascii=True` would have written instead, produced by asking
    # `json.dumps` for it rather than by spelling the escape out - the escape is
    # itself easy to mistype into a literal degree sign, which would assert the
    # opposite of the intent and still pass.
    escaped = json.dumps("@30°C").encode()
    assert escaped not in raw
    assert escaped != json.dumps("@30°C", ensure_ascii=False).encode()


def test_no_repr_artifact_reaches_the_bytes() -> None:
    """A-6, the defect class that has hit this repo three times.

    `repr(MeasurementBasis.STC)` is `<MeasurementBasis.STC: 'stc'>`; a routine
    Python upgrade reworking enum repr would then re-baseline every golden hash
    with zero data change. `<` cannot occur in any legitimate encoded value in
    this store, so its absence is a cheap total check on that whole class.
    """
    assert b"<" not in projection_bytes(_project())


def test_no_repr_artifact_reaches_what_decides_hashed_array_order() -> None:
    """D-14's rule is about *order*, not only about the emitted bytes.

    "Nothing that decides hashed array order may contain `repr()` of an enum" is
    the stronger half, and it is the half A-50 breached: `repr()` is fine as an
    in-memory sort key in general, but here the key decides a hashed array's
    order, so CPython's enum repr reaching it re-baselines the hash on a Python
    upgrade just as surely as if it had been written into the bytes.

    This is checked separately because checking the bytes does not cover it, and
    a mutation reinstating `repr(grouping_key())` in the sort key survived a suite
    that only checked the bytes. It survives *quietly*, too: every vocabulary in
    `schema/enums.py` names its members `value.upper()`, so repr order and encoded
    order coincide today and no ordering assertion can see the difference. They
    would stop coinciding at the first member whose name is not its upper-cased
    value - which is exactly the kind of change nobody would connect to a hash.
    """
    field = synthetic_module().fields["nameplate_power"][0]
    assert field.condition.basis is MeasurementBasis.STC, "needs an enum to be a real check"
    assert "<" not in projection_module._value_sort_key(field)


def test_the_sungrow_trio_stays_three_values_under_one_key() -> None:
    """The list-valued case T0.5 exists to exercise.

    Collapsing conditioned values to one entry per key either loses two real
    values or forces a contract key per condition. Both temperatures and values
    are pinned so the fixture cannot drift into a different worked example while
    still projecting cleanly.

    The order is the *condition* first and the value second, because that is the
    order of the sequence `_value_sort_key` restates - so the three rows come out
    by ambient, and the powers descend as a consequence rather than by design.
    Asserting both lists is what makes that visible: pinning the values alone
    would read as a numeric sort and quietly mislead the next reader.
    """
    inverter = next(
        component for component in _project()["components"] if component["model"] == "SG350HX"
    )
    rated = next(entry for entry in inverter["fields"] if entry["name"] == "rated_ac_power")
    assert [value["condition"]["temperature_c"] for value in rated["values"]] == [
        30.0,
        40.0,
        50.0,
    ]
    assert [value["value"] for value in rated["values"]] == [352.0, 320.0, 295.0]


def test_a_declared_band_value_encodes_through_its_leaves() -> None:
    """D-14 says `model_dump` for `DeclaredBand`; Track 1a corrected that to a
    recursive dump, because a plain one leaves `kind` as the enum member - one
    `repr()` away from the A-6 defect above."""
    module = next(
        component for component in _project()["components"] if component["model"] == "TSM-NEG21C.20"
    )
    band = next(entry for entry in module["fields"] if entry["name"] == "power_tolerance")
    assert band["values"][0]["value"] == {
        "low": 0.0,
        "high": 5.0,
        "kind": "absolute",
        "unit": "W",
    }


# --------------------------------------------------------------------------
# Determinism (AC-7)
# --------------------------------------------------------------------------


def test_two_generations_from_an_unchanged_store_are_byte_identical() -> None:
    """AC-7. Two distinct object graphs, so this cannot pass by caching."""
    assert projection_bytes(_project()) == projection_bytes(_project())


def test_arrival_order_does_not_reach_the_bytes() -> None:
    """FR-OUT-06: composition is a pure function of the store.

    Reversing every list the store is handed in must change nothing. `sorted` is
    stable, so a sort key that ties leaks arrival order silently - which is the
    defect `_ordering_key`'s own docstring records shipping twice.
    """
    store = synthetic_store()
    forward = project_store(
        components=store["components"],
        conflicts=store["conflicts"],
        sources=store["sources"],
        policy=FIXTURE_POLICY,
    )
    reversed_store = synthetic_store()
    for component in reversed_store["components"]:
        for values in component.fields.values():
            values.reverse()
    backward = project_store(
        components=list(reversed(reversed_store["components"])),
        conflicts=list(reversed(reversed_store["conflicts"])),
        sources=list(reversed(reversed_store["sources"])),
        policy=FIXTURE_POLICY,
    )
    assert projection_bytes(forward) == projection_bytes(backward)


def test_two_components_that_tie_on_ordering_key_still_order_by_content() -> None:
    """`ComponentInstance.ordering_key()` is not total, and stable sort is not a
    tiebreak - it is arrival order wearing one.

    Two instances agreeing on category, manufacturer, family, nameplate and
    surrogate id tie completely, so without a content tiebreak the projection of
    an unchanged store depends on the order rows came back from the database.
    """

    def _twin(supplier_verbatim: str, page: int) -> ComponentInstance:
        return ComponentInstance(
            supplier=supplier_verbatim,
            model="ASB-M10-144-550",
            component_category=ComponentCategory.PV_MODULES,
            manufacturer_key="adani",
            model_family="asb_m10_144",
            fields={
                "nameplate_power": [
                    CanonicalField(
                        value=550.0,
                        unit="Wp",
                        condition=_stc(),
                        source_tier=SourceTier.SYSTEM_OF_RECORD,
                        source_ref=SourceRef(document_id="syn-adani", page=page),
                        confidence=0.9,
                    )
                ]
            },
        )

    first, second = _twin("Adani Solar", 1), _twin("Adani Green", 2)
    assert first.ordering_key() == second.ordering_key()
    forward = project_store(
        components=[first, second], conflicts=[], sources=[], policy=FIXTURE_POLICY
    )
    backward = project_store(
        components=[second, first], conflicts=[], sources=[], policy=FIXTURE_POLICY
    )
    assert projection_bytes(forward) == projection_bytes(backward)


def test_the_digest_is_sha256_of_the_canonical_bytes() -> None:
    """`sha256(projection)` is the artifact of record. The xlsx digest, when G.2
    lands, is a renderer-regression check only and never the integrity claim."""
    built = _project()
    assert projection_digest(built) == hashlib.sha256(projection_bytes(built)).hexdigest()


# --------------------------------------------------------------------------
# Decision 1 - policy and the computed flags are inside the hash
# --------------------------------------------------------------------------


def test_the_policy_is_inside_the_projection() -> None:
    assert _project()["policy"] == {
        "policy_version": "fixture-2026-08-12",
        "confidence_threshold": 0.80,
    }


def test_retuning_the_threshold_changes_the_hash() -> None:
    """The workbook is a function of *(store, policy)*. Hashing only the store
    certifies AC-7 while the artifact silently varies with configuration - the
    false-integrity claim C6 exists to prevent."""
    retuned = ProjectionPolicy(policy_version="fixture-2026-08-12", confidence_threshold=0.50)
    assert projection_digest(_project()) != projection_digest(_project(policy=retuned))


def test_the_computed_flags_are_in_the_bytes_not_merely_the_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-14 decision 1's sharp edge: `flags_for`'s *code* is policy too.

    Pinning only the threshold version would let a change to how flags are
    computed alter every rendered workbook under an unchanged hash. This holds
    the store and the threshold fixed and changes only `flags_for`'s behaviour;
    the digest must move.
    """
    baseline = projection_digest(_project())

    def _no_flags(field: CanonicalField, *, confidence_threshold: float) -> set[CellFlag]:
        return set()

    monkeypatch.setattr(projection_module, "flags_for", _no_flags)
    assert projection_digest(_project()) != baseline


def test_every_flag_state_is_exercised_and_rendered() -> None:
    """All four FR-OUT-04 states appear, so a regression in any one is visible.

    A fixture exercising none would let the whole of decision 1 pass green while
    the flags it hashes were empty everywhere.
    """
    rendered = {
        flag
        for component in _project()["components"]
        for entry in component["fields"]
        for value in entry["values"]
        for flag in value["flags"]
    }
    assert rendered == {flag.value for flag in CellFlag}


def test_flags_are_sorted_so_a_set_cannot_leak_iteration_order() -> None:
    """`flags_for` returns a `set`, which iterates in an order Python does not
    promise across runs for mixed content. Sorting is what makes AC-7 hold."""
    for component in _project()["components"]:
        for entry in component["fields"]:
            for value in entry["values"]:
                assert value["flags"] == sorted(value["flags"])


# --------------------------------------------------------------------------
# Decision 2 - `generated_on` folds from inside the projection
# --------------------------------------------------------------------------


def test_generated_on_is_the_maximum_store_write_timestamp() -> None:
    """D-14's derivation, on the store that distinguishes it from the runner-up:
    `CONFLICT_DETECTED` is later than either ingest, so `max(ingested_at)` would
    date the artifact by an ingest that is no longer its newest fact."""
    assert _project()["generated_on"] == {"$datetime": "2026-07-03T08:00:00.000000Z"}


def test_generated_on_recomputes_from_the_published_bytes_alone() -> None:
    """The structural property, tested structurally.

    The fold runs over the *parsed artifact*, with no access to the store objects
    that produced it. That is what "a fold over timestamps already inside the
    projection" buys and a parallel query cannot: anyone holding the bytes can
    check the stamp, and a row type added tomorrow is covered the moment it
    carries its write timestamp, rather than the day someone remembers to widen a
    query.
    """
    parsed = json.loads(projection_bytes(_project()))
    assert fold_generated_on(parsed) == parsed["generated_on"]


def test_the_stamp_is_not_self_referential() -> None:
    """`generated_on` is folded from the body before it is attached, so folding
    the finished artifact must give the same answer rather than seeing itself."""
    built = _project()
    body = {key: value for key, value in built.items() if key != "generated_on"}
    assert fold_generated_on(body) == built["generated_on"]


def test_a_resolution_moves_the_stamp_when_max_ingested_at_does_not() -> None:
    """The row of D-14's comparison table that eliminates `max(ingested_at)`.

    A human resolution changes the workbook's content - FR-HITL-04 persists it
    into field provenance - so a derivation blind to it dates the artifact wrong.
    No committed fixture may carry a resolution (FR-HITL-06: a committed decision
    is a decision with nobody behind it), so this store is built here instead.
    """
    resolved_at = _at("2026-09-09T17:45:00.000000")
    store = synthetic_store()
    entry = store["conflicts"][0]
    store["conflicts"] = [
        entry.model_copy(
            update={
                "resolution": Resolution(
                    action=ResolutionAction.KEEP_SYSTEM_OF_RECORD,
                    resolved_by="test-reviewer",
                    resolved_at=resolved_at,
                    rationale="The datasheet outranks a distributor listing (FR-HITL-02).",
                )
            }
        )
    ]
    projected = project_store(
        components=store["components"],
        conflicts=store["conflicts"],
        sources=store["sources"],
        policy=FIXTURE_POLICY,
    )
    assert projected["generated_on"] == {"$datetime": "2026-09-09T17:45:00.000000Z"}
    assert max(document.ingested_at for document in store["sources"]) < resolved_at


def test_a_future_dated_data_vintage_does_not_move_the_stamp() -> None:
    """`data_vintage` is a publication date, not a store write.

    A fold that collected every datetime in sight would let a revision dated next
    year stamp the workbook with a date on which nothing was written - and
    `retrieved_at` would drag it the other way. D-14 names four write columns and
    neither of these is one.
    """
    store = synthetic_store()
    store["sources"] = [
        document.model_copy(update={"data_vintage": _at("2030-01-01T00:00:00.000000")})
        for document in store["sources"]
    ]
    projected = project_store(
        components=store["components"],
        conflicts=store["conflicts"],
        sources=store["sources"],
        policy=FIXTURE_POLICY,
    )
    assert projected["generated_on"] == {"$datetime": "2026-07-03T08:00:00.000000Z"}


def test_an_empty_store_renders_generated_on_as_null() -> None:
    """D-14's zero-document sentinel, decided rather than left to a default.

    Never a placeholder or an epoch date: an epoch-like value is indistinguishable
    from a real vintage to a reader, and the whole point of the field is that a
    reader can trust what it says. The workbook shows this as *no sources*.
    """
    empty = project_store(components=[], conflicts=[], sources=[], policy=FIXTURE_POLICY)
    assert empty["generated_on"] is None
    assert b'"generated_on":null' in projection_bytes(empty)
    assert empty["components"] == empty["conflicts"] == empty["sources"] == []


def test_generated_on_does_not_read_the_clock() -> None:
    """FR-OUT-06 demands the stamp; AC-7 and G.5's `sleep(1.1)` re-run demand
    byte-identity. A store-derived stamp satisfies both, and the cheapest proof
    that it is store-derived is that it sits far from now."""
    stamp = _project()["generated_on"]
    assert stamp is not None
    assert stamp["$datetime"] != datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    assert stamp["$datetime"] == "2026-07-03T08:00:00.000000Z"


def test_a_row_builder_cannot_silently_omit_its_write_timestamp() -> None:
    """The structural half of decision 2, asserted on the signature.

    The failure D-14 names is a row type added without its timestamp. Making the
    parameter keyword-only with no default is what turns that from a silent
    omission into a `TypeError` at the call site, so the guarantee is checked
    here rather than left as a convention.
    """
    parameter = inspect.signature(projection_module._store_row).parameters["written_at"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_every_row_in_the_projection_declares_a_write_timestamp_slot() -> None:
    """The slot is present and explicit even where it is null.

    `ComponentInstance` and `CanonicalField` carry no write timestamp at all, so
    D-14's `claim.extracted_at` term is not reachable from the canonical store
    today. Emitting the slot as null records that as a stated absence rather than
    an oversight, and means the term folds automatically the day the column
    becomes reachable.
    """
    built = _project()
    for section in ("components", "conflicts", "sources"):
        for row in built[section]:
            assert STORE_WRITTEN_AT in row, f"{section} row has no write-timestamp slot"
    assert all(row[STORE_WRITTEN_AT] is None for row in built["components"])
    assert all(row[STORE_WRITTEN_AT] is not None for row in built["sources"])


# --------------------------------------------------------------------------
# Closed world
# --------------------------------------------------------------------------


def test_a_value_outside_the_encoding_table_is_refused() -> None:
    """The projection inherits `encode_value`'s closed world rather than
    softening it: a new value type must be a loud decision recorded in D-14, not
    an artifact hashed over an encoding nobody wrote down."""
    store = synthetic_store()
    store["components"][0].fields["rated_ac_power"][0].value = {"kVA": 352}
    with pytest.raises(UnencodableValueError):
        project_store(
            components=store["components"],
            conflicts=store["conflicts"],
            sources=store["sources"],
            policy=FIXTURE_POLICY,
        )


def test_every_leaf_is_exactly_a_json_type_not_merely_equal_to_one() -> None:
    """The blind spot D-14's amendment tells every artifact-hashing track to assume.

    A raw enum member reaching the projection is **invisible to every other check
    here**. A `StrEnum` member equals its own value, `json.dumps` writes it as a
    plain string, so the bytes are identical, the digest is identical, and no
    equality assertion can see it. It also leaves no `<`, so the repr check above
    passes too. Track 1a found exactly this: of eight mutations against the
    encoder, the unrecursed `model_dump` was the one that survived the first
    suite.

    The leak matters because it is one `repr()` from the A-6 defect, and because
    the day someone adds a non-`str` enum or a `Decimal` field to a dumped model,
    the bytes silently change meaning. `type(x) is str` rather than `isinstance`
    is the whole point - `isinstance` is precisely what cannot tell a `StrEnum`
    member from a string.
    """

    def _leaves(node: object) -> Iterator[object]:
        if isinstance(node, dict):
            for key, value in node.items():
                assert type(key) is str, f"non-str key {key!r} of type {type(key).__name__}"
                yield from _leaves(value)
        elif isinstance(node, list):
            for item in node:
                yield from _leaves(item)
        else:
            yield node

    for leaf in _leaves(_project()):
        assert type(leaf) in (str, int, float, bool, type(None)), (
            f"{leaf!r} is a {type(leaf).__name__}, which is not exactly a JSON type. "
            "It may still serialise and hash identically today - that is what makes "
            "this the one check that can see it."
        )


def test_a_naive_retrieved_at_is_refused_rather_than_assumed_to_be_utc() -> None:
    """A boundary gap in `schema/field.py`, pinned here rather than papered over.

    `SourceRef.retrieved_at` is `datetime | None` with **no tz-awareness
    validator**, while `encode_value` refuses naive datetimes - so the schema
    admits a value the encoder will not encode. Nothing in the repo builds one
    today (every fixture has `retrieved_at: null`), but the projection encodes
    `SourceRef`, so this is the path that would meet it first.

    Failing loudly is the right end state either way: a naive datetime names no
    instant, and assuming UTC would encode it identically to an aware noon-UTC it
    is not equal to - breaking injectivity in the silent direction. Closing it at
    the boundary is Track 5's call (`schema/` is theirs), so this asserts the
    behaviour rather than changing it, and fails if the direction ever flips to a
    silent assumption.
    """
    store = synthetic_store()
    naive = SourceRef(
        url="https://distributor.example.invalid/tsm-neg21c",
        page_title="TSM-NEG21C.20 product page",
        retrieved_at=datetime(2026, 6, 28, 11, 0, 0),  # noqa: DTZ001 - the point of the test
    )
    store["components"][1].fields["nameplate_power"][1].source_ref = naive
    with pytest.raises(UnencodableValueError, match="naive datetime"):
        project_store(
            components=store["components"],
            conflicts=store["conflicts"],
            sources=store["sources"],
            policy=FIXTURE_POLICY,
        )


def test_a_decimal_value_keeps_its_declared_precision() -> None:
    """D-2's EXACT catalog values are naturally `Decimal`, and `Decimal("650")`
    against `Decimal("650.0")` is the difference between no conflict and a human
    being asked to review. The tag is what stops the projection collapsing them."""
    store = synthetic_store()
    store["components"][1].fields["nameplate_power"][0].value = Decimal("650.0")
    projected = project_store(
        components=store["components"],
        conflicts=store["conflicts"],
        sources=store["sources"],
        policy=FIXTURE_POLICY,
    )
    module = next(
        component
        for component in _rows(projected, "components")
        if component["model"] == "TSM-NEG21C.20"
    )
    power = next(entry for entry in module["fields"] if entry["name"] == "nameplate_power")
    assert {"$decimal": "650.0"} in [value["value"] for value in power["values"]]


# --------------------------------------------------------------------------
# T0.5 - the committed golden fixture
# --------------------------------------------------------------------------


def test_the_committed_fixture_is_what_the_synthetic_store_projects_to() -> None:
    """The behavioural check `tests/fixtures/README.md` requires.

    Schema-valid, byte-canonical JSON encoding the wrong worked example is the
    failure the structural checks cannot see, so this regenerates the artifact
    from the store and compares the committed bytes.
    """
    expected = json.dumps(_project(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert FIXTURE_JSON.read_text() == expected


def test_the_committed_hash_is_the_hash_of_d14s_canonical_bytes() -> None:
    """The fixture file is stored in the *fixtures'* pretty serialisation so the
    existing byte check covers it uniformly; the hash is over D-14's compact
    bytes, which is the artifact of record. Two serialisations, one artifact -
    and the sidecar is what stops them being confused for each other.
    """
    assert FIXTURE_SHA256.read_text().split()[0] == projection_digest(_project())


def test_the_fixture_hash_covers_the_committed_file_and_not_just_the_code() -> None:
    """Recompute the digest from the bytes on disk, not from a fresh projection.

    Without this the sidecar only ever certifies whatever the code just produced,
    so a hand-edit to the committed JSON would be caught by the regeneration test
    above but the hash would still be self-consistently wrong.
    """
    from_disk = json.loads(FIXTURE_JSON.read_text())
    canonical = json.dumps(
        from_disk, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    assert hashlib.sha256(canonical).hexdigest() == FIXTURE_SHA256.read_text().split()[0]
