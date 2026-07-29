"""The canonical field object.

TRS section 5 specifies this exactly:

    Each field is an object:
    { value, unit, verbatim_value, source_tier, source_ref, confidence,
      conflict_status, resolution }

Those eight keys are reproduced verbatim. The canonical store built from them is
the single source for Excel regeneration and the audit trail, so FR-OUT-06's
determinism requirement rests on this type being stable.
"""

from __future__ import annotations

import math
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .enums import ConflictClass, ConflictStatus, ResolutionAction, Severity, SourceTier


class SourceRef(BaseModel):
    """Where a value came from. NFR-01 permits no unsourced values.

    A document reference carries doc_id plus page and table/section (FR-ING-07).
    A web reference carries url, page_title and retrieved_at (FR-WEB-02).
    """

    model_config = ConfigDict(frozen=True)

    document_id: str | None = None
    page: int | None = None
    section: str | None = Field(default=None, description="Table or section locator")
    bounding_box: tuple[float, float, float, float] | None = Field(
        default=None, description="OCR bbox retained per FR-ING-04"
    )

    url: str | None = None
    page_title: str | None = None
    retrieved_at: datetime | None = None
    source_authority: str | None = Field(
        default=None,
        description=(
            "FR-WEB-05 authority tier, e.g. manufacturer datasheet, UL/TUV/Intertek, "
            "IEEE/NFPA, ERCOT/PUCT/TCEQ, IRS/Treasury"
        ),
    )

    @model_validator(mode="after")
    def _must_identify_a_source(self) -> SourceRef:
        """NFR-01: every value traces to a source. An empty ref is never valid."""
        if self.document_id is None and self.url is None:
            raise ValueError("SourceRef requires either document_id or url (NFR-01)")
        return self


class Resolution(BaseModel):
    """A human decision on a queued conflict. Logged immutably per FR-HITL-06."""

    model_config = ConfigDict(frozen=True)

    action: ResolutionAction
    resolved_by: str
    resolved_at: datetime
    rationale: str
    value_before: object | None = None
    value_after: object | None = None


class ConditionDimensions(BaseModel):
    """The machine-comparable dimensions of a measurement condition.

    Membership of this model *is* the definition of what gates comparison, so a
    new dimension participates automatically and a new human-readable annotation
    automatically does not. See clarifications.md D-1.

    Not intended as a field annotation anywhere: annotate with `Condition`. A
    field typed as this class accepts a `Condition` but serialises through the
    parent schema and silently drops `note`.
    """

    model_config = ConfigDict(frozen=True)

    basis: str | None = Field(
        default=None,
        description="Measurement basis, e.g. stc, nmot, noct, bnpi, fat, sat, bol, eol",
    )
    temperature_c: float | None = Field(
        default=None, description="Ambient the rating is stated at, e.g. 30 / 40 / 50"
    )
    side: str | None = Field(default=None, description="ac or dc - load-bearing for BESS")
    duration_h: float | None = Field(
        default=None, description="Rated duration; BESS RTE is duration-dependent"
    )
    weighting: str | None = Field(
        default=None, description="Efficiency weighting, e.g. cec, european, max"
    )
    standards_regime: str | None = Field(
        default=None,
        description=(
            "ieee or iec. Determines which multi-cooling rating is canonical, the "
            "loss reference temperature, and the vector-group phase convention. "
            "See clarifications.md D-6."
        ),
    )
    reference_temperature_c: float | None = Field(
        default=None, description="Loss reference temperature: 20 + rise (IEEE) or 75 (IEC)"
    )
    base_mva: float | None = Field(
        default=None,
        description=(
            "Rating the transformer's %Z and losses are referred to. A grouping "
            "dimension, not a note: IEEE refers impedance to the ONAN base and IEC "
            "to the top rating, so two %Z figures on different bases differ by "
            "1.25-1.67x - far beyond the +/-7.5% tolerance. See clarifications.md D-6."
        ),
    )

    @field_validator("temperature_c", "duration_h", "reference_temperature_c", "base_mva")
    @classmethod
    def _reject_non_finite(cls, value: float | None) -> float | None:
        """NaN would break the equivalence relation `grouping_key` depends on.

        `NaN != NaN`, so two identically-conditioned values would land in separate
        groups and never compare - and pydantic serialises NaN to JSON `null`, so
        the same record would group differently before and after a store
        round-trip. That is precisely the FR-OUT-06 purity `grouping_key` exists to
        guarantee, so a non-finite condition is rejected at the boundary instead.
        """
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("condition dimensions must be finite (no NaN or infinity)")
        # -0.0 == 0.0 and hashes alike, so they are one dict key - but they have
        # different reprs, which flipped the order of a repr-sorted partition.
        return value + 0.0

    @field_validator("basis", "side", "weighting", "standards_regime")
    @classmethod
    def _normalise_vocabulary(cls, value: str | None) -> str | None:
        """Fold case and strip padding so `STC` and `stc` share a group.

        Under exact-key grouping an unnormalised case variant does not raise a
        false conflict - it silently forms its own group and suppresses the
        comparison, which is the failure direction that cannot be reviewed.
        """
        if value is None:
            return None
        normalised = value.strip().casefold()
        # An extractor emitting "" rather than None would otherwise read as a
        # stated dimension and strand the value in its own group.
        return normalised or None


class Condition(ConditionDimensions):
    """The measurement conditions a value holds under.

    A ninth key beyond the eight TRS section 5 fixes. Two values are comparable
    only when their conditions match; a mismatch is not a conflict, it is not a
    comparison. Rationale and the Sungrow SG350HX worked case: clarifications.md
    D-1. Which dimensions each parameter family requires: the Conditions table in
    contracts/canonical-parameters.md.
    """

    note: str | None = Field(default=None, description="Any condition not captured above")
    derived: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "Dimensions filled by convention rather than read from the source. "
            "Lives on this subclass, not on ConditionDimensions, so it is excluded "
            "from grouping by construction: a defaulted STC value and a stated STC "
            "value group together while the provenance stays honest for a reviewer."
        ),
    )

    @field_serializer("derived")
    def _sort_derived(self, value: frozenset[str]) -> list[str]:
        """Sorted on the way out: a frozenset serialises in hash order, which is
        randomised per process, so the same record would produce different JSON
        bytes every run - defeating the FR-OUT-06 purity this model exists for."""
        return sorted(value)

    def is_unstated(self) -> bool:
        """Whether no comparable dimension is known at all.

        Detection does not partition, so nothing needs rescuing: see
        `services.conflict_hitl.comparison_pairs`, which compares an unstated
        condition against every condition it does not contradict.
        """
        return all(value is None for value in self.grouping_key())

    def grouping_key(self) -> tuple[object, ...]:
        """A canonical key for *displaying* candidates grouped by condition.

        Equality over this tuple is an equivalence relation - reflexive because
        non-finite floats are rejected at construction, and transitive because it
        is plain tuple equality - so partitioning by it does not depend on the
        order candidates arrive in. FR-OUT-06 requires that, since composition
        must be a pure function of the store.

        Grouping by this key alone is *comparison-losing*, though: a value whose
        conditions are merely less specific strands in its own group and is
        compared against nothing. That is why detection uses
        `services.conflict_hitl.comparison_pairs` and this key is for display.

        `note` and `derived` are excluded: free text is provenance for a human,
        and how a dimension came to be filled does not change what it says.
        """
        return tuple(getattr(self, name) for name in ConditionDimensions.model_fields)

    def comparable_with(self, other: Condition) -> bool:
        """Whether these two specific values may be compared.

        Any dimension set on both sides must agree; a dimension absent on one side
        is unknown rather than contradictory.

        **This relation is deliberately not transitive, so it must never be used to
        partition a candidate set.** `@30 degC` and `@40 degC` are both comparable
        with an unstated condition but not with each other, so first-fit bucketing
        over the same three values yields different groups depending on the order
        they arrive - and therefore a different conflict queue from the same store.
        This is the detection predicate - `services.conflict_hitl.comparison_pairs`
        applies it to every unordered pair. Do not use it to bucket candidates;
        first-fit bucketing over a non-transitive relation gives a different
        conflict queue per document order. See issue #12.
        """
        for name in ConditionDimensions.model_fields:
            mine, theirs = getattr(self, name), getattr(other, name)
            if mine is not None and theirs is not None and mine != theirs:
                return False
        return True


class CanonicalField(BaseModel):
    """One extracted parameter, with provenance, conditions and conflict state.

    Nine keys: the eight fixed by TRS section 5, plus `condition`. The deviation
    is recorded in analysis.md A-1.
    """

    value: object | None = None
    unit: str | None = Field(default=None, description="Canonical unit per FR-ING-08")
    verbatim_value: str | None = Field(
        default=None, description="Original text as written, retained per FR-ING-08"
    )
    condition: Condition = Field(
        default_factory=Condition, description="Conditions the value holds under - see D-1"
    )
    source_tier: SourceTier
    source_ref: SourceRef
    confidence: float = Field(ge=0.0, le=1.0)
    conflict_status: ConflictStatus = ConflictStatus.NONE
    resolution: Resolution | None = None

    @model_validator(mode="after")
    def _resolution_matches_status(self) -> CanonicalField:
        if self.conflict_status is ConflictStatus.RESOLVED and self.resolution is None:
            raise ValueError("a resolved field must carry its Resolution (FR-HITL-06)")
        return self

    def is_missing(self) -> bool:
        """FR-OUT-04 missing-data flag."""
        return self.value is None

    def is_web_supplemented(self) -> bool:
        """FR-OUT-04 web-supplemented flag."""
        return self.source_tier is SourceTier.WEB_SUPPLEMENT


class ConflictCandidate(BaseModel):
    """One competing value for a field, as presented in the queue (FR-HITL-03)."""

    model_config = ConfigDict(frozen=True)

    value: object | None
    unit: str | None
    verbatim_value: str | None = Field(
        default=None, description="FR-HITL-03 requires the verbatim source text"
    )
    condition: Condition = Field(
        default_factory=Condition,
        description=(
            "The conditions this candidate holds under. Required for the queue to "
            "explain itself (FR-HITL-03): '352 kVA vs 320.865 kW' is unreadable "
            "without @30 degC / @40 degC attached. Also what "
            "services.conflict_hitl.comparison_groups partitions on."
        ),
    )
    source_tier: SourceTier
    source_ref: SourceRef
    confidence: float = Field(ge=0.0, le=1.0)


class ConflictQueueEntry(BaseModel):
    """An item awaiting human resolution.

    FR-HITL-03 fixes the payload: canonical field, component/supplier, all
    candidate values with verbatim source text, source tier, source authority,
    doc/page/URL, timestamps and a generated explanation.
    """

    entry_id: str
    field_name: str
    supplier: str
    model: str
    component_category: str
    conflict_class: ConflictClass
    severity: Severity = Field(
        description=(
            "Drives the compose gate (issue #14). Assigned from the field's "
            "criticality tier, not from the size of the divergence - see D-3. "
            "Deliberately REQUIRED: this is a safety interlock, and any default "
            "at or below the gate threshold would make a forgotten severity "
            "silently unable to block."
        ),
    )
    candidates: list[ConflictCandidate]
    explanation: str = Field(description="Generated rationale shown to the reviewer")
    detected_at: datetime
    resolution: Resolution | None = None
