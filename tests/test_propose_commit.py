"""Workers propose, they do not commit — contract C8, issue #8.

Every case marked "review" below is a defect two independent reviews found in
the first version of this module. They are kept as tests rather than as
changelog, because each one passed a green suite.
"""

import inspect
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from procurement_agent.schema import (
    CanonicalField,
    Condition,
    ConflictStatus,
    MeasurementBasis,
    SourceRef,
    SourceTier,
)
from procurement_agent.services import claims as claims_module
from procurement_agent.services.claims import (
    ClaimWriter,
    FieldClaim,
    ProposalError,
    canonical_claims,
    commit_claims,
    project,
    takes_a_write_handle,
)
from procurement_agent.services.conflict_hitl import AutonomousOverwriteError, comparison_pairs


class _Store:
    def __init__(self) -> None:
        self.committed: dict[str, list[CanonicalField]] = {}
        self.writes = 0

    def commit(self, field_name: str, values: Sequence[CanonicalField]) -> None:
        self.committed[field_name] = list(values)
        self.writes += 1

    def current(self, field_name: str) -> list[CanonicalField]:
        return self.committed.get(field_name, [])


def _claim(
    value: object,
    *,
    tier: SourceTier = SourceTier.SYSTEM_OF_RECORD,
    doc: str = "doc-a",
    version: str = "extract@1",
    confidence: float = 0.9,
    condition: Condition | None = None,
    field: str = "nameplate_power",
    page: int | None = None,
    unit: str | None = "Wp",
    verbatim: str | None = None,
) -> FieldClaim:
    return FieldClaim(
        document_id=doc,
        field_name=field,
        extractor_version=version,
        condition=condition or Condition(),
        value=value,
        unit=unit,
        verbatim_value=verbatim,
        source_tier=tier,
        source_ref=SourceRef(document_id=doc, page=page),
        confidence=confidence,
    )


def _sungrow() -> list[FieldClaim]:
    """D-1's worked example: one datasheet, one field, three ambients."""
    return [
        _claim(
            v,
            field="rated_ac_power",
            doc="sungrow-eu-ds",
            condition=Condition(temperature_c=t),
        )
        for v, t in ((352.0, 30.0), (320.0, 40.0), (295.0, 50.0))
    ]


# --- contract C2: a claim carries its condition ---------------------------------


def test_a_claim_carries_its_condition() -> None:
    """C2, "including `condition` per D-1". The first version omitted it."""
    assert "condition" in FieldClaim.model_fields


def test_the_sungrow_trio_raises_no_conflict() -> None:
    """Review: without `condition`, every candidate came out `is_unstated()` and
    `comparison_pairs` returned **3 pairs** on the case D-1 opens with — "four
    apparent conflicts and zero real ones". The condition gate was defeated on
    the only path that reaches it."""
    candidates = [c.as_candidate() for c in _sungrow()]
    assert not any(c.condition.is_unstated() for c in candidates)
    assert comparison_pairs(candidates) == []


def test_three_ambients_are_three_claims_not_a_contradiction() -> None:
    """Review: `claim_key` was `(document_id, field_name, extractor_version)`, so
    one datasheet stating one parameter at three ambients raised `ProposalError`
    — and a test asserted that was correct."""
    assert len({c.claim_key() for c in _sungrow()}) == 3
    assert len(canonical_claims(_sungrow())) == 3


def test_the_sungrow_trio_stores_three_values() -> None:
    """`ComponentInstance.fields` is list-valued precisely so this is three
    stored values rather than one value and two discarded."""
    projected = project(_sungrow())
    assert [f.value for f in projected] == [352.0, 320.0, 295.0]
    assert [f.condition.temperature_c for f in projected] == [30.0, 40.0, 50.0]
    assert {f.conflict_status for f in projected} == {ConflictStatus.NONE}


def test_condition_reaches_the_store() -> None:
    projected = project([_claim(700.0, condition=Condition(basis=MeasurementBasis.STC))])
    assert projected[0].condition.basis is MeasurementBasis.STC


# --- what the projection decides, and what it refuses to decide -----------------


def test_a_populated_value_is_never_lost_to_a_missing_one() -> None:
    """Review: `distinct` filtered `None` before counting and the winner was the
    alphabetically-first document, so "A found nothing, B found 650 W" stored
    `None` **and** reported `NONE`. `is_missing()` then called it missing data
    and the 650 was unrecoverable."""
    projected = project([_claim(None, doc="a-datasheet"), _claim(650.0, doc="b-datasheet")])
    assert len(projected) == 1
    assert projected[0].value == 650.0
    assert projected[0].conflict_status is ConflictStatus.OPEN
    assert not projected[0].is_missing()


def test_a_web_claim_contradicting_the_record_is_queued() -> None:
    """Review: the status was computed over the system-of-record subset, so a
    contradicting web value came back `NONE`. FR-WEB-04 says that disagreement is
    queued for a human, and `assert_no_autonomous_overwrite`'s own docstring says
    the same."""
    projected = project(
        [
            _claim(650.0, doc="contract"),
            _claim(700.0, doc="web-1", tier=SourceTier.WEB_SUPPLEMENT),
        ]
    )
    assert projected[0].value == 650.0, "the record still supplies the value"
    assert projected[0].source_tier is SourceTier.SYSTEM_OF_RECORD
    assert projected[0].conflict_status is ConflictStatus.OPEN


def test_the_record_supplies_the_value_even_when_the_web_looks_better() -> None:
    """Mutation: deleting the source-tier term from `_preferred`'s sort key left
    the suite green, because in every case tested the record also happened to
    have the alphabetically-first `document_id` — the very defect this module was
    rewritten to remove, hiding inside its own regression test.

    Here the web claim wins on confidence *and* on filename, so only the
    source-of-record rule (TRS section 1, FR-HITL-02) can produce 650.
    """
    projected = project(
        [
            _claim(650.0, doc="zzz-contract", confidence=0.5),
            _claim(700.0, doc="aaa-web", tier=SourceTier.WEB_SUPPLEMENT, confidence=0.99),
        ]
    )
    assert projected[0].value == 650.0
    assert projected[0].source_tier is SourceTier.SYSTEM_OF_RECORD
    assert projected[0].conflict_status is ConflictStatus.OPEN


def test_the_canonical_value_does_not_depend_on_the_filename() -> None:
    """Review: `winners[0]` over an order led by `document_id` meant renaming a
    document changed the stored answer — and AC-7 then made it reproducibly
    wrong."""
    high = project([_claim(650.0, doc="aaa"), _claim(655.0, doc="zzz", confidence=0.5)])
    low = project([_claim(650.0, doc="mmm"), _claim(655.0, doc="bbb", confidence=0.5)])
    assert high[0].value == low[0].value == 650.0


def test_two_record_claims_that_disagree_are_not_arbitrated() -> None:
    """Picking one would be the auto-arbitration FR-HITL-02 forbids."""
    projected = project([_claim(650.0, doc="contract"), _claim(700.0, doc="datasheet")])
    assert projected[0].conflict_status is ConflictStatus.OPEN


def test_agreeing_claims_leave_the_field_clean() -> None:
    projected = project([_claim(650.0, doc="contract"), _claim(650.0, doc="datasheet")])
    assert projected[0].conflict_status is ConflictStatus.NONE


@pytest.mark.parametrize(
    "value",
    [["UL 61730", "IEC 61215"], {"onan": 100.0, "onaf": 125.0}, None, 650.0, "Dyn11"],
)
def test_every_contract_value_shape_projects(value: object) -> None:
    """Review: `set(claims)` raised `TypeError: unhashable type: 'list'`. The
    contract has at least nine list- and dict-valued parameters, and
    `certifications` is Tier A — the projection crashed on the fields the repo
    classifies as most critical."""
    projected = project([_claim(value)])
    assert projected[0].value == value


# --- append-only, and what counts as a contradiction ----------------------------


def test_an_identical_claim_from_two_workers_is_one_assertion() -> None:
    claim = _claim(650.0)
    assert len(canonical_claims([claim, claim, claim])) == 1


def test_the_same_figure_printed_twice_in_one_document_is_not_a_defect() -> None:
    """Review: any two claims sharing a key and differing in *any* field raised —
    including `source_ref.page`. A datasheet printing the same figure in a
    summary table and again in the electrical-characteristics table is normal."""
    both = canonical_claims([_claim(650.0, page=2), _claim(650.0, page=7)])
    assert len(both) == 2
    assert len(project(both)) == 1


def test_two_values_under_one_condition_is_still_a_defect() -> None:
    """The case the error was written for: one extractor version, one condition,
    two different answers."""
    with pytest.raises(ProposalError):
        canonical_claims([_claim(650.0), _claim(700.0)])


def test_a_unit_mismatch_is_not_agreement() -> None:
    """Review: `_status_for` compared `repr(value)` and nothing else, so two
    claims reading `650 W` and `650 kW` were one answer and the field was stored
    `NONE` — with whichever unit `_preferred` happened to pick.

    `values_conflict` calls exactly this a `UNIT_NORMALIZATION` conflict that "is
    never resolved by tolerance (FR-ING-08)", and `canonical_claims` already
    counts the unit as part of the asserted value. The projection was the one
    place that did not.
    """
    projected = project(
        [
            _claim(650.0, doc="contract", unit="W"),
            _claim(650.0, doc="datasheet", unit="kW"),
        ]
    )
    assert projected[0].conflict_status is ConflictStatus.OPEN


def test_two_dicts_with_the_same_entries_are_one_assertion() -> None:
    """Review: value identity was `repr`, and `repr` of a dict follows insertion
    order. Two extractions of one cooling table that read the rows in different
    orders produced values that are `==` and reprs that are not, so they counted
    as a disagreement.

    The contract has three dict-valued parameters - `rating_mva_by_cooling`,
    `harmonic_spectrum` and `ercot_compliance_items` - and this module's own
    docstring names the first of them.
    """
    left = {"onan": 100.0, "onaf": 125.0}
    right = {"onaf": 125.0, "onan": 100.0}
    assert left == right
    projected = project(
        [
            _claim(left, field="rating_mva_by_cooling", doc="d-1"),
            _claim(right, field="rating_mva_by_cooling", doc="d-2"),
        ]
    )
    assert projected[0].conflict_status is ConflictStatus.NONE

    # Same key, so the mismatch would have aborted the whole field rather than
    # merely mis-reporting it.
    assert len(canonical_claims([_claim(left, page=2), _claim(right, page=7)])) == 2


def test_a_self_referential_value_does_not_blow_the_stack() -> None:
    """Whatever renders a claim's value has to be total. `repr` guards its own
    cycles; a hand-rolled canonical rendering has to guard them too."""
    looping: list[object] = []
    looping.append(looping)
    assert len(canonical_claims([_claim(looping)])) == 1


def test_the_same_figure_printed_twice_may_differ_in_source_text() -> None:
    """Review: `verbatim_value` was part of the same-key contradiction signature,
    so the summary table's `650 W` and the electrical table's `650` raised
    `ProposalError` and the whole field was lost.

    `test_the_same_figure_printed_twice_in_one_document_is_not_a_defect` passed
    only because both claims carried `verbatim_value=None`: it varied `page`,
    which was already excluded, and never the thing that still failed. Verbatim
    text is the source text at a location, which is provenance in exactly the way
    the page number is.
    """
    both = canonical_claims(
        [_claim(650.0, page=2, verbatim="650 W"), _claim(650.0, page=7, verbatim="650")]
    )
    assert len(both) == 2
    assert len(project(both)) == 1


def test_re_extraction_appends_rather_than_overwrites() -> None:
    assert len(canonical_claims([_claim(650.0, version="v1"), _claim(655.0, version="v2")])) == 2


def test_the_projection_does_not_depend_on_completion_order() -> None:
    """Two workers finishing in different orders must not give different stores."""
    trio = _sungrow()
    assert project(trio) == project(list(reversed(trio)))


def test_a_claim_cannot_be_revised_in_place() -> None:
    with pytest.raises(ValidationError):
        _claim(650.0).value = 700.0


# --- the structural property ----------------------------------------------------


def test_only_the_reducer_takes_a_write_handle() -> None:
    public = {
        name: obj
        for name, obj in vars(claims_module).items()
        if not name.startswith("_") and inspect.isfunction(obj)
    }
    assert "commit_claims" in public
    writers = {name for name, obj in public.items() if takes_a_write_handle(obj)}
    assert writers == {"commit_claims"}, sorted(writers)


@pytest.mark.parametrize("name", ["writer", "store", "storage", "claim_writer"])
def test_the_common_write_handle_names_are_detected(name: str) -> None:
    """Review: substring matching flagged `restore` and missed `storage`."""
    assert takes_a_write_handle(eval(f"lambda {name}: None"))  # noqa: S307


def test_an_annotated_handle_is_detected_whatever_it_is_called() -> None:
    def worker(sink: ClaimWriter) -> None: ...

    assert takes_a_write_handle(worker)


def test_a_lookalike_name_is_not_flagged() -> None:
    """`restore` and `history` contain no write handle."""
    assert not takes_a_write_handle(lambda restore, history: None)


def test_the_lint_does_not_claim_to_be_a_proof() -> None:
    """Review: the first version was described as asserting the property "for
    every present and future worker". A signature check cannot see a module
    global, a closure cell or `self.writer`, and saying otherwise is the honour
    system with extra steps."""
    captured = _Store()

    def worker_with_a_closure() -> None:
        captured.commit("x", [])

    assert not takes_a_write_handle(worker_with_a_closure)
    assert "lint, not a proof" in (takes_a_write_handle.__doc__ or "")


def test_the_write_handle_is_keyword_only() -> None:
    assert (
        inspect.signature(commit_claims).parameters["writer"].kind is inspect.Parameter.KEYWORD_ONLY
    )


def test_the_reducer_applies_the_guard_per_condition() -> None:
    store = _Store()
    commit_claims("nameplate_power", [_claim(650.0)], writer=store)
    with pytest.raises(AutonomousOverwriteError):
        commit_claims(
            "nameplate_power",
            [_claim(700.0, tier=SourceTier.WEB_SUPPLEMENT, doc="web-1")],
            writer=store,
        )
    assert store.writes == 1, "the rejected commit must not have reached the store"


def test_a_web_value_under_a_new_condition_is_not_an_overwrite() -> None:
    """The guard is keyed per condition group: a web claim at 40 degC does not
    overwrite a record claim at 30 degC, because it does not replace it.

    Review: this asserted only `store.writes == 2`, which a store that had just
    *deleted* the 30 degC record value satisfies exactly as well as one that kept
    it. `commit` replaces the whole field, so the write count says nothing about
    what survived it. The end state is the claim, so the end state is what is
    asserted.
    """
    store = _Store()
    record = _claim(352.0, field="rated_ac_power", condition=Condition(temperature_c=30.0))
    commit_claims("rated_ac_power", [record], writer=store)
    commit_claims(
        "rated_ac_power",
        [
            record,
            _claim(
                320.0,
                field="rated_ac_power",
                condition=Condition(temperature_c=40.0),
                tier=SourceTier.WEB_SUPPLEMENT,
            ),
        ],
        writer=store,
    )
    assert store.writes == 2
    stored = {
        f.condition.temperature_c: (f.value, f.source_tier) for f in store.current("rated_ac_power")
    }
    assert stored == {
        30.0: (352.0, SourceTier.SYSTEM_OF_RECORD),
        40.0: (320.0, SourceTier.WEB_SUPPLEMENT),
    }


def test_a_later_run_may_not_drop_a_stored_condition_group() -> None:
    """Review: `commit` replaces the whole field, and the guard is keyed on the
    condition group, so it only ever saw groups present in *both*. A web claim
    under a condition group the record does not have therefore reached
    `writer.commit` unopposed and the record value was deleted with it — the
    autonomous overwrite FR-WEB-03 and FR-HITL-02 forbid, achieved by changing
    the condition rather than the value.

    The projection is a pure function of the claim set, and claims are
    append-only, so a group can only vanish because the caller passed a subset.
    That is a programming error and it is raised as one; merging the leftovers
    back in would make the store a function of commit history instead.
    """
    store = _Store()
    commit_claims(
        "rated_ac_power",
        [_claim(352.0, field="rated_ac_power", condition=Condition(temperature_c=30.0))],
        writer=store,
    )
    with pytest.raises(ProposalError, match="drop|complete"):
        commit_claims(
            "rated_ac_power",
            [
                _claim(
                    320.0,
                    field="rated_ac_power",
                    condition=Condition(temperature_c=40.0),
                    tier=SourceTier.WEB_SUPPLEMENT,
                    doc="web-1",
                )
            ],
            writer=store,
        )
    assert store.writes == 1
    assert [f.value for f in store.current("rated_ac_power")] == [352.0]


def test_the_projection_is_for_one_field_at_a_time() -> None:
    """Review: `project` grouped by condition alone and ignored `field_name`
    entirely, so two claims about *different parameters* with the same (commonly
    empty) condition landed in one group. One of the two values was then silently
    discarded and the survivor was reported OPEN — a conflict between a nameplate
    and an efficiency, which is not a comparison at all.
    """
    with pytest.raises(ProposalError, match="one field"):
        project(
            [
                _claim(650.0, field="nameplate_power"),
                _claim(21.5, field="module_efficiency"),
            ]
        )


def test_the_reducer_refuses_a_claim_about_another_field() -> None:
    """The field name is the store key. Nothing checked that the claims agreed
    with it, so a `module_efficiency` claim committed cleanly under
    `nameplate_power` and the store held a percentage labelled as watts."""
    store = _Store()
    with pytest.raises(ProposalError, match="module_efficiency"):
        commit_claims("nameplate_power", [_claim(21.5, field="module_efficiency")], writer=store)
    assert store.writes == 0


def test_a_store_satisfies_the_protocol_structurally() -> None:
    assert isinstance(_Store(), ClaimWriter)


def test_no_claims_is_no_value() -> None:
    assert project([]) == []
    assert commit_claims("nameplate_power", [], writer=_Store()) == []


# --- contract C3: provenance survives the projection -----------------------------


def test_the_extractor_version_reaches_the_store() -> None:
    """C3 is `(document_id, page, span, extractor_version)`. The first three lived
    on `SourceRef`; the fourth lived only on the claim, so `project` dropped it
    and a stored value could not be traced to the code that produced it. A
    regression is then invisible in the store while the claim recording it is
    still sitting there."""
    projected = project([_claim(650.0, version="extract@3", page=4)])
    assert projected[0].source_ref.extractor_version == "extract@3"
    assert projected[0].source_ref.page == 4


def test_the_queue_entry_carries_it_too() -> None:
    """A reviewer comparing two candidates needs to see which extractor produced
    each, or 'these disagree' is missing the commonest explanation."""
    candidate = _claim(650.0, version="extract@3").as_candidate()
    assert candidate.source_ref.extractor_version == "extract@3"


def test_the_claim_is_the_single_authority_for_it() -> None:
    """Stamped from the claim rather than set twice, so the two cannot drift."""
    claim = FieldClaim(
        document_id="doc-a",
        field_name="nameplate_power",
        extractor_version="extract@3",
        value=650.0,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-a", extractor_version="extract@1"),
        confidence=0.9,
    )
    assert claim.provenance().extractor_version == "extract@3"
