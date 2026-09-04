"""Invariants the canonical schema must hold regardless of implementation."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement_agent.schema import (
    CATEGORY_TO_TAB,
    CanonicalField,
    ComponentCategory,
    ComponentInstance,
    Condition,
    ConflictCandidate,
    ConflictClass,
    ConflictQueueEntry,
    ConflictStatus,
    DeclaredBand,
    DocumentType,
    Resolution,
    ResolutionAction,
    Severity,
    SourceDocument,
    SourceRef,
    SourceTier,
    ToleranceKind,
    UnresolvedStatus,
    WorkbookTab,
)
from procurement_agent.services.output import expected_tabs


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
    field = CanonicalField(
        value=650,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
    )
    on_the_wire = set(field.model_dump())
    assert spec_keys <= on_the_wire
    assert on_the_wire - spec_keys == {"condition"}
    # D-18: `conflict_status` is computed from `resolution` and the stored
    # `unresolved_status`, which is excluded from the dump. The contract's key
    # set is the wire shape, not the storage layout.
    assert "conflict_status" in CanonicalField.model_computed_fields
    assert "unresolved_status" in CanonicalField.model_fields
    assert "unresolved_status" not in on_the_wire


def test_resolved_field_must_carry_its_resolution() -> None:
    """FR-HITL-06: decisions are logged with user, timestamp, before/after, rationale."""
    with pytest.raises(ValidationError):
        CanonicalField.model_validate(
            {
                "value": 650,
                "source_tier": SourceTier.SYSTEM_OF_RECORD,
                "source_ref": SourceRef(document_id="doc-1"),
                "confidence": 0.9,
                "conflict_status": ConflictStatus.RESOLVED,
            }
        )


def test_resolved_field_accepts_a_resolution() -> None:
    field = CanonicalField.model_validate(
        {
            "value": 650,
            "source_tier": SourceTier.SYSTEM_OF_RECORD,
            "source_ref": SourceRef(document_id="doc-1"),
            "confidence": 0.9,
            "conflict_status": ConflictStatus.RESOLVED,
            "resolution": Resolution(
                action=ResolutionAction.KEEP_SYSTEM_OF_RECORD,
                resolved_by="procurement.lead",
                resolved_at=datetime.now(UTC),
                rationale="Contract supersedes the web datasheet revision.",
                value_before=655,
                value_after=650,
            ),
        }
    )
    # Echoing the constructor kwarg back tests pydantic, not the validator. What
    # `_resolution_matches_status` actually enforces is the *other* direction:
    # RESOLVED without a Resolution is the state FR-HITL-06 forbids, because a
    # decision with no record of who made it is not auditable.
    assert field.resolution is not None
    with pytest.raises(ValidationError):
        CanonicalField.model_validate(
            {
                "value": 650,
                "source_tier": SourceTier.SYSTEM_OF_RECORD,
                "source_ref": SourceRef(document_id="doc-1"),
                "confidence": 0.9,
                "conflict_status": ConflictStatus.RESOLVED,
            }
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


def test_expected_tabs_returns_all_thirteen_in_order() -> None:
    """`services.output.expected_tabs()` is the sequence a writer iterates to
    satisfy FR-OUT-02, and it had no assertion anywhere: truncating its body to
    `list(WorkbookTab)[:3]` left all 228 tests green. A workbook with ten tabs
    missing would have shipped while the docs called the tab order tested.

    The two tests above check the *enum*; this one checks the *helper*, which is
    a different failure. The names are pinned as literals rather than compared
    against `list(WorkbookTab)` because that comparison is the helper's own body
    restated - it would still pass if the enum lost or reordered a member.
    """
    assert [tab.value for tab in expected_tabs()] == [
        "PV Modules",
        "Inverters-PCS",
        "Trackers & Mounting",
        "Transformers",
        "Cabling & Wiring",
        "Combiner Boxes",
        "BESS",
        "EMS-SCADA & Controls",
        "Executive Summary",
        "Conflicts & Open Items",
        "Sources & Provenance",
        "Compliance Matrix",
        "Tax Incentives",
    ]


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
    with pytest.raises(ValueError, match="must carry its Resolution"):
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
    field = CanonicalField.model_validate(
        {
            "value": 650,
            "source_tier": SourceTier.SYSTEM_OF_RECORD,
            "source_ref": SourceRef(document_id="doc-1"),
            "confidence": 0.9,
            "conflict_status": ConflictStatus.RESOLVED,
            "resolution": _resolution("procurement.lead"),
        }
    )
    with pytest.raises(ValueError):
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


def _field(value: object, status: ConflictStatus, temp: float | None = None) -> CanonicalField:
    return CanonicalField(
        value=value,
        unit="kVA",
        condition=Condition(temperature_c=temp),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="ds-1"),
        confidence=0.9,
        unresolved_status=UnresolvedStatus(status.value),
    )


def test_unresolved_conflicts_reads_every_conditioned_value() -> None:
    """Mutation: replacing the inner iteration with `for value in [values]` — i.e.
    treating `fields` as single-valued again — survived the whole suite, because
    nothing called this method with a populated store at all.

    FR-HITL-05 says unresolved conflicts are flagged in the output, never
    silently omitted. `fields` is list-valued per D-1, so a conflict on the
    *second* condition of a parameter is exactly the one a single-valued reader
    would drop.
    """
    instance = ComponentInstance(
        supplier="Sungrow",
        model="SG350HX",
        component_category=ComponentCategory.INVERTERS_PCS,
        fields={
            "rated_ac_power": [
                _field(352.0, ConflictStatus.NONE, 30.0),
                _field(320.0, ConflictStatus.OPEN, 40.0),
            ],
            "max_efficiency": [_field(99.0, ConflictStatus.NONE)],
            "cec_efficiency": [_field(None, ConflictStatus.INSUFFICIENT_EVIDENCE)],
        },
    )
    assert instance.unresolved_conflicts() == ["cec_efficiency", "rated_ac_power"]


def test_a_clean_store_has_no_unresolved_conflicts() -> None:
    instance = ComponentInstance(
        supplier="Sungrow",
        model="SG350HX",
        component_category=ComponentCategory.INVERTERS_PCS,
        fields={"rated_ac_power": [_field(352.0, ConflictStatus.NONE, 30.0)]},
    )
    assert instance.unresolved_conflicts() == []


def _resolved_field() -> CanonicalField:
    return CanonicalField(
        value=650,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
    )


def test_model_copy_update_is_refused_on_a_canonical_field() -> None:
    """GAP closed: pydantic's `model_copy(update=...)` re-runs no validators, so
    before this fix `field.model_copy(update={"conflict_status": RESOLVED})`
    produced a RESOLVED field carrying no `Resolution` - exactly the state
    `_resolution_matches_status` exists to forbid - and it serialised to the
    audit trail with no error at all. `validate_assignment` does not touch this
    route at all, because `model_copy` never goes through `__setattr__`.

    `CanonicalField` now overrides `model_copy` to refuse the `update=` form
    outright rather than silently reproducing that hole, and points the caller
    at `evolve`, which does revalidate.
    """
    field = _resolved_field()
    with pytest.raises(TypeError):
        field.model_copy(update={"conflict_status": ConflictStatus.RESOLVED})


def test_model_copy_without_update_is_unaffected() -> None:
    """Only the validation-skipping `update=` form is refused. A bare copy (or
    `deep=True`) changes no data - the source was already valid - so there is
    nothing to revalidate and pydantic's own copy still works."""
    field = _resolved_field()
    copy = field.model_copy()
    assert copy == field
    assert copy is not field
    deep_copy = field.model_copy(deep=True)
    assert deep_copy == field


def test_evolve_reruns_validation_and_still_forbids_the_state() -> None:
    """`evolve` is the revalidating replacement for `model_copy(update=...)`:
    routing the merged data back through `model_validate` reruns
    `_resolution_matches_status`, so the same illegal state still raises here -
    this time because the invariant was actually re-checked, not because the
    call was refused outright.
    """
    field = _resolved_field()
    with pytest.raises(ValidationError):
        field.evolve(conflict_status=ConflictStatus.RESOLVED)


def test_evolve_applies_a_consistent_update_without_mutating_the_original() -> None:
    """The happy path: attaching `conflict_status` and `resolution` together in
    one call sidesteps the assignment-order trap the class docstring warns
    about entirely, because both land in the same validated snapshot. `evolve`
    builds a new object rather than mutating the receiver, matching every other
    "update" in this module (`model_copy`, `ConflictQueueEntry` resolutions)."""
    field = _resolved_field()
    resolved = field.evolve(
        conflict_status=ConflictStatus.RESOLVED,
        resolution=Resolution(
            action=ResolutionAction.KEEP_SYSTEM_OF_RECORD,
            resolved_by="procurement.lead",
            resolved_at=datetime.now(UTC),
            rationale="Contract supersedes the web datasheet revision.",
        ),
    )
    assert resolved.conflict_status is ConflictStatus.RESOLVED
    assert resolved.resolution is not None
    assert resolved.resolution.resolved_by == "procurement.lead"
    assert field.conflict_status is ConflictStatus.NONE
    assert field.resolution is None


def test_resolution_fields_are_frozen() -> None:
    """FR-HITL-06's log is immutable, but until now nothing asserted `Resolution`'s
    own field-level frozen-ness - only the *pointer* to a `Resolution` was
    covered, by `test_a_recorded_resolution_cannot_be_replaced`. Without this,
    a caller with a reference to a live `Resolution` could rewrite who resolved
    a conflict, or when, with no trace the original value ever existed - the
    same audit-trail defect `frozen=True` on `ConflictQueueEntry` exists to
    prevent one level up.
    """
    resolution = _resolution("alice")
    with pytest.raises(ValidationError):
        resolution.resolved_by = "mallory"


# --- evolve() must not quietly change what a value *is* -------------------------


def _band_field() -> CanonicalField:
    return CanonicalField(
        value=DeclaredBand(low=0.0, high=5.0, kind=ToleranceKind.ABSOLUTE, unit="W"),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
    )


def test_evolve_preserves_a_model_typed_value() -> None:
    """Review: `evolve` was `model_validate({**self.model_dump(), **changes})`.

    `value` is typed `object | None`, so it has no schema to validate back
    against - `model_dump()` serialised whatever was in it and `model_validate`
    stored the serialised form. A `DeclaredBand` came back as a plain `dict`,
    silently, with no warning even under `simplefilter("always")`.

    Not hypothetical: the frozen contract types `power_tolerance` and
    `bifaciality_tolerance` as `DeclaredBand`. It was also a regression against
    the `model_copy(update=...)` that `evolve` replaces, which shallow-copied
    `__dict__` and preserved the object.
    """
    evolved = _band_field().evolve(confidence=0.8)
    assert isinstance(evolved.value, DeclaredBand)
    assert evolved.value.resolve(650.0, nominal_unit="W") == (650.0, 655.0)


def test_evolve_still_revalidates() -> None:
    """The property the live-attribute snapshot must not cost."""
    with pytest.raises(ValidationError):
        _band_field().evolve(conflict_status=ConflictStatus.RESOLVED)


def test_evolve_preserves_decimal_precision() -> None:
    """`_decimals` depends on `Decimal` not collapsing to `float`."""
    field = CanonicalField(
        value=Decimal("22.35"),
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
    )
    assert field.evolve(confidence=0.8).value == Decimal("22.35")
    assert isinstance(field.evolve(confidence=0.8).value, Decimal)


def test_evolve_refuses_an_unknown_field() -> None:
    """Review: `model_config` sets no `extra="forbid"`, so `model_validate` drops
    unknown keys - `evolve(conflict_stauts=RESOLVED)` returned a field with the
    change silently not applied. For an FR-HITL-06 audit path a no-op update is
    the worse direction, and the route this replaces would at least have set the
    key."""
    with pytest.raises(ValueError, match="unknown field"):
        _band_field().evolve(conflict_stauts=ConflictStatus.RESOLVED)


def test_the_component_models_refuse_an_unknown_field() -> None:
    """A mistyped optional field must not vanish.

    Pydantic's default is `extra='ignore'`, and every canonical-store model was
    on it. The cost is not cosmetic: `ComponentInstance(nameplate_w=550)` leaves
    `nameplate` as `None`, which `ordering_key()` maps to `float('-inf')` - so a
    typo silently discards the bin discriminator that exists because "one
    datasheet routinely covers several SKUs".

    This is the same class as issue #16 one level up: #16 closed the condition
    *vocabulary*, so an invalid `basis` value is refused, while the field *name*
    stayed open-world. `config.py`'s `extra="ignore"` is deliberate and correct -
    unknown environment variables must not break startup - and no schema model
    documents such a reason.

    `schema/field.py`'s models are covered by their own suite; these are the two
    that live here.
    """
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ComponentInstance(
            supplier="Adani",
            model="ASB-M10-144-550",
            component_category=ComponentCategory.PV_MODULES,
            nameplate_w=550.0,  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceDocument(
            document_id="d",
            content_hash="h",
            source_uri="file:///x.pdf",
            document_type=DocumentType.SPEC_SHEET,
            ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
            access_restrictedd=True,  # type: ignore[call-arg]
        )
