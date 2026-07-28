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

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ConflictClass, ConflictStatus, ResolutionAction, SourceTier


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


class Condition(BaseModel):
    """The measurement conditions a value holds under.

    A ninth key beyond the eight the TRS fixes in section 5, and the most
    consequential addition in the design. Research found that *most false
    conflicts in this domain are condition errors, not unit errors*.

    The Sungrow SG350HX is the worked case: its EU datasheet, its US datasheet
    and its CEC listing produce four apparent conflicts (352 vs 320 kVA,
    1500 vs 1330 V, 98.8 vs 98.5 %, 1 vs 3 % THD) and **zero real ones** - CEC
    simply anchors on the 40 degC rating and the full-power MPPT window.

    Without this, the conflict engine floods the queue with spurious items and
    reviewers learn to ignore it, which defeats the tool's premise (FR-HITL-02).

    The TRS's own section 7 requires this: it lists parameters like
    "rated AC kVA @temp" and "STC/NMOT ratings" that cannot otherwise be
    represented. See clarifications.md D-1.
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
    note: str | None = Field(default=None, description="Any condition not captured above")

    def comparable_with(self, other: Condition) -> bool:
        """Whether two values may be compared at all.

        Mismatched conditions are **not a conflict** - they are not a
        comparison. Any field set on both sides must agree; a field absent on
        one side is unknown rather than contradictory.
        """
        for name in type(self).model_fields:
            if name == "note":
                continue
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
    candidates: list[ConflictCandidate]
    explanation: str = Field(description="Generated rationale shown to the reviewer")
    detected_at: datetime
    resolution: Resolution | None = None
