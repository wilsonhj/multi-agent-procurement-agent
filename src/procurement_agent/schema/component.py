"""Component instances and source documents held in the canonical store.

TRS section 5: "Per component instance: supplier, model, component_category, and
a field set (section 7)." The per-category parameter sets from TRS section 7 are
not yet enumerated here; locking them for PV modules, inverters and BESS is the
Stage 1 exit condition, so they belong in a follow-up rather than in scaffolding.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import ComponentCategory, DocumentType
from .field import CanonicalField


class SourceDocument(BaseModel):
    """An ingested file. Identity is content-addressed so re-ingest is a no-op.

    FR-ING-09 requires stable IDs with timestamps and source URI; NFR-05 and AC-5
    require that re-ingesting an unchanged document creates no duplicates.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str
    content_hash: str = Field(description="Dedup key per FR-ING-09 / NFR-05")
    source_uri: str
    document_type: DocumentType
    ingested_at: datetime
    data_vintage: datetime | None = Field(
        default=None,
        description="Publication or revision date of the source, reported per FR-OUT-06",
    )
    access_restricted: bool = Field(
        default=False,
        description=(
            "NFR-03: contract and pricing documents are confidential. Enforced at "
            "retrieval time via metadata filtering, not only at the API edge."
        ),
    )


class ComponentInstance(BaseModel):
    """One supplier's offering in one category, as a set of canonical fields."""

    supplier: str
    model: str
    component_category: ComponentCategory
    nameplate: float | None = Field(
        default=None,
        description=(
            "Bin discriminator. One datasheet routinely covers several SKUs - a Trina "
            "TSM-NEG21C.20 sheet spans 6 bins and 22 CEC rows - so supplier+model alone "
            "does not identify a product."
        ),
    )
    surrogate_id: str | None = Field(
        default=None,
        description=(
            "hash(normalised_supplier, normalised_model, nameplate). There is no stable "
            "ID upstream: CEC publishes none, and (Manufacturer, Model Number) is not "
            "unique - 36 duplicated pairs measured, plus 157 model numbers appearing "
            "under more than one manufacturer. See clarifications.md D-4 and D-8."
        ),
    )
    manufacturer_key: str | None = Field(
        default=None,
        description=(
            "D-4 stage 1's normalised supplier. Filled by `services.identity."
            "identity_keys`; `schema` sits below `services` and cannot import it, "
            "so the slot is declared here and populated from outside - the same "
            "arrangement `surrogate_id` already used."
        ),
    )
    model_family: str | None = Field(
        default=None,
        description="D-4 stage 2's family, i.e. the model string with the bin token masked.",
    )
    fields: dict[str, list[CanonicalField]] = Field(
        default_factory=dict,
        description=(
            "Contract key -> every conditioned value for it. **List-valued, not "
            "one entry per key.** D-1 makes `condition` part of what a value *is*, "
            "and one datasheet routinely states one parameter several times under "
            "different conditions - the Sungrow SG350HX prints `352 kVA @30 degC / "
            "320 @40 degC / 295 @50 degC` for a single `rated_ac_power`. Collapsing "
            "those to one entry either loses two real values or forces a new "
            "contract key per condition, which is what the ad-hoc encodings "
            "(`stc_rating` vs `nmot_rating`, `rated_ac_power_temp`) already do. "
            "The contract keeps those; this is the general mechanism beside them."
        ),
    )

    def ordering_key(self) -> tuple[str, str, str, float, str]:
        """Canonical sort position for deterministic workbook regeneration.

        AC-7 requires byte-identical output from an unchanged store, which needs a
        total order over component instances. `sorted-key JSON` orders keys *within*
        an object; it says nothing about row order *across* instances.

        `surrogate_id` is the tie-break rather than the primary key because
        (category, supplier, model) is provably not unique on real data - two Adani
        entities publish `ASB-M10-144-550` with genuinely different specs (PTC 509.9
        vs 518.2). Without the tie-break the sort is unstable exactly where the data
        is most ambiguous.

        D-4 stage 5 sorts on the *normalised* keys, not the raw strings: sorting on
        `supplier` puts `Trina Solar` and `Trina Solar Co.,Ltd` far apart, so the
        entity split stage 1 exists to close reopens in the row order. The raw
        strings remain the fallback for an instance nobody has run the matcher over
        - a partially-normalised store must still have a total order, and falling
        back is visible where raising would only move the failure.
        """
        return (
            self.component_category.value,
            self.manufacturer_key or self.supplier,
            self.model_family or self.model,
            self.nameplate if self.nameplate is not None else float("-inf"),
            self.surrogate_id or "",
        )

    def unresolved_conflicts(self) -> list[str]:
        """Field names still awaiting a human decision.

        FR-HITL-05: unresolved conflicts and insufficient-evidence fields are
        flagged in the output, never silently resolved or omitted.
        """
        from .enums import ConflictStatus

        blocking = {ConflictStatus.OPEN, ConflictStatus.INSUFFICIENT_EVIDENCE}
        return sorted(
            {
                name
                for name, values in self.fields.items()
                for value in values
                if value.conflict_status in blocking
            }
        )
