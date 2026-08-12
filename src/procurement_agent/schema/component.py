"""Component instances and source documents held in the canonical store.

TRS section 5: "Per component instance: supplier, model, component_category, and
a field set (section 7)." The per-category parameter sets from TRS section 7 are
not yet enumerated here; locking them for PV modules, inverters and BESS is the
Stage 1 exit condition, so they belong in a follow-up rather than in scaffolding.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import ComponentCategory, DocumentType
from .field import CanonicalField
from .registry import require_contract_key


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

    @field_validator("ingested_at", "data_vintage")
    @classmethod
    def _must_name_an_instant(cls, value: datetime | None) -> datetime | None:
        """The same constraint `SourceRef.retrieved_at` carries, for the same
        reason: `encode_value` refuses a naive datetime because one names no
        instant, so a schema that accepts one accepts a value the canonical
        encoder cannot encode.

        Applied here as well as there because the defect is the type, not the
        file - `data_vintage` is what FR-OUT-06 reports and what temporal conflict
        detection compares, and a wall-clock reading with no zone cannot order
        two revisions. Nothing constructs a `SourceDocument` yet, which is exactly
        why this would otherwise have been found by whoever wrote the first
        ingestion boundary, after the naive timestamps were already stored.
        """
        if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
            raise ValueError(
                "SourceDocument timestamps must be timezone-aware; a naive datetime "
                "names no instant. Attach the zone at the boundary that produced it."
            )
        return value


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

    @model_validator(mode="after")
    def _keys_are_on_contract(self) -> ComponentInstance:
        """Contract C2's first enforcement point: `fields` is where a key is
        *used as a key*, so it is where an off-contract one has to be refused.

        Nothing checked this, and the type could not: `dict[str, ...]` admits any
        string. Downstream that is not a validation nuisance but a permanent one -
        claims are append-only, so a parameter stored under `nameplate_power_w`
        yields rows that can be superseded and never corrected, and the B.9 gold
        set gets labelled against a key no table looks up.

        **Checked against the category, not the union of all keys.** `chemistry`
        is a genuine contract key and nonsense on a PV module, and a union check
        passes it. The category is what makes a key mean something - see
        `registry.spec_for`, and the two `insulation_type` rows it exists for.

        Known limit, stated rather than implied: this runs at construction and on
        `model_validate`, so `instance.fields["junk"] = [...]` afterwards is not
        seen. Closing that needs `validate_assignment` plus a `fields` that is not
        a bare dict, which is a wider change than this contract needs - the
        boundary that matters is the one values arrive through.
        """
        for key in self.fields:
            require_contract_key(key, self.component_category)
        return self

    @field_validator("nameplate")
    @classmethod
    def _reject_non_finite(cls, value: float | None) -> float | None:
        """Same reasoning as `ConditionDimensions` and `DeclaredBand`, applied to
        the one float left in the total order.

        NaN compares false against everything, so it is not a sort key at all:
        three instances whose category, manufacturer and family tie come out in
        four different orders depending on the order they arrive in, and AC-7
        wants byte-identical output from an unchanged store. `-0.0` is folded for
        the same repr-stability reason the other two give.

        `None` stays legal - a nameplate is often not known yet, and
        `ordering_key` maps it to `-inf`, which *is* totally ordered.
        """
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("nameplate must be finite (no NaN or infinity)")
        return value + 0.0

    def _stored_values(self) -> str:
        """A canonical rendering of everything this instance actually says.

        Not a second serialisation invented for the sort: it is
        `model_dump(mode="json")` under `json.dumps(sort_keys=True)`, which is the
        form `tests/test_fixtures.py` byte-compares the committed fixtures
        against. One answer to "what does this row say", not two.

        `sort_keys` is what makes it a *function of the content*. The contract has
        three dict-valued parameters, and a dict iterates in insertion order, so
        two extractions that read one cooling table's rows in different orders
        hold equal values that render differently without it -
        `services.claims._render` records the same hazard on the claim-identity
        side. `Condition.derived` is a frozenset and is sorted on the way out by
        its own serialiser, for the same reason one level down.

        Deliberately reads `fields` and nothing else. The raw `supplier` and
        `model` are excluded because D-4 stage 1 exists to make `Trina Solar` and
        `Trina Solar Co.,Ltd` sort together, and a tie-break that read them would
        undo the entity split silently - the obvious way to make a key unique is
        the one that breaks the thing the key was normalised for.
        """
        return json.dumps(
            {
                name: [value.model_dump(mode="json") for value in values]
                for name, values in self.fields.items()
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def ordering_key(self) -> tuple[str, str, str, float, str, str]:
        """Canonical sort position for deterministic workbook regeneration.

        AC-7 requires byte-identical output from an unchanged store, which needs a
        total order over component instances. `sorted-key JSON` orders keys *within*
        an object; it says nothing about row order *across* instances.

        `surrogate_id` is the tie-break rather than the primary key because
        (category, supplier, model) is provably not unique on real data - two Adani
        entities publish `ASB-M10-144-550` with genuinely different specs (PTC 509.9
        vs 518.2). Without the tie-break the sort is unstable exactly where the data
        is most ambiguous.

        **`surrogate_id` alone was not a tie-break, and the sentence above says
        why.** It falls back to `""`, which is the value on *both* sides whenever
        nothing has run the matcher yet - the state a freshly ingested store is
        in. `sorted` is stable, so a complete tie does not reorder: it leaks
        arrival order, and the workbook differs run to run with no value having
        changed. The cited Adani pair is exactly such a tie, because PTC lives in
        `fields` and the key did not read `fields`. **The tie-break did not cover
        the scenario it was written for**, and the test covering it happened to
        give both sides a surrogate.

        So `_stored_values()` is the final element, and the order is now total *up
        to equality*: two instances that still tie agree on category, identity,
        nameplate, surrogate and every stored value, so they produce identical
        rows and their relative order cannot be observed in the output at all.
        That is the strongest guarantee available and the only one AC-7 needs.

        D-4 stage 5 sorts on the *normalised* keys, not the raw strings: sorting on
        `supplier` puts `Trina Solar` and `Trina Solar Co.,Ltd` far apart, so the
        entity split stage 1 exists to close reopens in the row order. The raw
        strings remain the fallback for an instance nobody has run the matcher over
        - a partially-normalised store must still have a total order, and falling
        back is visible where raising would only move the failure.

        **This key is in-memory only; it can order rows and can never itself be
        projected or hashed.** An absent nameplate becomes `float("-inf")`, which
        is totally ordered and which `encode_value` refuses - no injective
        encoding of a non-finite float exists. Anything wanting canonical bytes
        for a row must build them from the instance rather than from this tuple.
        """
        return (
            self.component_category.value,
            self.manufacturer_key or self.supplier,
            self.model_family or self.model,
            self.nameplate if self.nameplate is not None else float("-inf"),
            self.surrogate_id or "",
            self._stored_values(),
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
