"""Supplier and model identity resolution — D-4, issue #9.

Cases marked "review" are defects found in the first version. Each passed a
green suite, so they are kept as tests rather than as changelog.
"""

import pathlib
import re

import pytest

from procurement_agent.schema import ComponentCategory, ComponentInstance
from procurement_agent.services.identity import (
    AUTO_MERGE_THRESHOLD,
    ELECTRICAL_ROWS,
    LEGAL_SUFFIXES,
    SUFFIX_RULES,
    UNIMPLEMENTED_D4A,
    VARIANT_THRESHOLD,
    WEIGHTS,
    Candidate,
    MatchOutcome,
    SuffixVerdict,
    decompose,
    identity_keys,
    manufacturer_key,
    same_manufacturer,
    score,
)


def _contract_keys() -> set[str]:
    contract = pathlib.Path(__file__).parent.parent / (
        "specs/001-procurement-agent/contracts/canonical-parameters.md"
    )
    text = contract.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^\|\s*`([a-z0-9_]+)`\s*\|", text, re.MULTILINE)}


# --- stage 1: manufacturer normalisation ----------------------------------------


def test_the_trina_entity_split() -> None:
    """D-4 names this as the matcher's regression test. Bins 635-725 W sit under
    `Trina Solar Co.,Ltd` and 730/735/740 under `Trina Solar`, so a lookup of
    (`Trina Solar`, `TSM-700NEG21C.20`) returns nothing without it."""
    assert same_manufacturer("Trina Solar", "Trina Solar Co.,Ltd")
    assert manufacturer_key("Trina Solar Co.,Ltd") == "trina solar"


def test_a_leading_legal_token_is_part_of_the_name() -> None:
    """Review: legal suffixes were stripped from anywhere in the string, so the
    Norwegian `AS` in `AS Solar` was removed and the company became `solar` —
    identical to `Solar, Inc.`. A false merge between two unrelated companies is
    the one outcome D-4 optimises against, and it is invisible afterwards: it
    either fabricates a conflict between their products or hides a real one.

    `as`, `sa`, `ab`, `co`, `ag`, `kg` and `lp` are all ordinary words or
    initials in a leading position.
    """
    assert manufacturer_key("AS Solar") != manufacturer_key("Solar, Inc.")
    assert manufacturer_key("AS Solar") == "as solar"
    assert manufacturer_key("Solar, Inc.") == "solar"


def test_a_trailing_legal_form_is_stripped() -> None:
    for name in ("Qcells GmbH", "Qcells Co., Ltd.", "Qcells, Inc.", "Qcells Pte Ltd"):
        assert manufacturer_key(name) == "qcells"


def test_descriptive_tokens_are_never_stripped() -> None:
    """Review: `holdings`, `group`, `international` and `intl` were in the legal
    suffix set. None is a legal form in any jurisdiction — they are part of a
    trading name, and stripping them merges `X Group` with `X`. D-4's measured
    result is unambiguous: legal forms only, because adding descriptive tokens
    produced false merges and drove three real companies to the empty string."""
    assert not ({"holdings", "holding", "group", "international", "intl"} & LEGAL_SUFFIXES)
    assert manufacturer_key("Adani Group") != manufacturer_key("Adani")
    assert manufacturer_key("LONGi Holdings") != manufacturer_key("LONGi")


def test_the_names_d4_measured_folding_to_nothing_survive() -> None:
    """D-4: adding descriptive tokens drove `POWER ELECTRONICS`, `Solar Power
    (SPI)` and `Energy America, LLC` all to the empty string."""
    assert manufacturer_key("POWER ELECTRONICS") == "power electronics"
    assert manufacturer_key("Solar Power (SPI)") == "solar power spi"
    assert manufacturer_key("Energy America, LLC") == "energy america"


def test_a_hyphen_separates_tokens() -> None:
    """Review: the separator class held `.,()/&` and not `-`, so
    `Trina-Solar Co.,Ltd` produced the single token `trina-solar`, matched no
    legal suffix, and left the entity split unresolved — the failure the
    normalisation exists to fix, reintroduced by a missing character."""
    assert manufacturer_key("Trina-Solar Co.,Ltd") == "trina solar"
    assert manufacturer_key("Trina–Solar") == "trina solar"


def test_diacritics_fold() -> None:
    """Mutation: deleting the combining-mark strip after NFKD survived the whole
    suite. `Wärtsilä` is a real vendor in this corpus and appears both
    precomposed and decomposed, so without the strip one company has two keys."""
    assert manufacturer_key("Wärtsilä Corporation") == "wartsila"
    assert manufacturer_key("Wärtsilä Oyj") == "wartsila"
    assert same_manufacturer("Wärtsilä", "Wartsila")


def test_the_en_space_entry_folds() -> None:
    """D-4: the `Co./Ltd` cluster has 20 distinct spellings in CEC data, one
    ending in U+2002 EN SPACE. `str.split(" ")` does not see it."""
    assert manufacturer_key("Trina Solar Co., Ltd. ") == "trina solar"


def test_an_empty_key_raises_rather_than_merging_everything() -> None:
    for name in ("Co., Ltd.", "   ", "Inc.", "​‌"):
        with pytest.raises(ValueError, match="empty key"):
            manufacturer_key(name)


def test_the_invisible_characters_extraction_leaves_behind_fold_away() -> None:
    """Review: stage 1 folded NFKD, combining marks and unicode whitespace, and
    then left every zero-width and format character in place.

    `schema.field._normalise_token` strips exactly these, for exactly this
    reason - the contract's Conditions section names "the zero-width and
    byte-order marks PDF and XLSX extraction leaves behind", and a BOM was once a
    hard validation failure one module over. Here the cost is worse than a
    rejected token: a byte-order mark on the front of a name gives a *different
    manufacturer key*, so the Trina entity split D-4 names as the regression test
    reopens on any document whose extractor left one behind. A zero-width space
    inside `Co.,Ltd` defeats the legal-suffix strip outright.
    """
    for name in (
        "﻿Trina Solar Co.,Ltd",  # byte-order mark
        "Trina Solar Co.,​Ltd",  # zero-width space inside the legal form
        "Trina Solar Co.,Ltd‍",  # trailing zero-width joiner
        "Trina Sol­ar Co.,Ltd",  # soft hyphen from a justified PDF line break
        "‏Trina Solar Co.,Ltd",  # right-to-left mark
    ):
        assert manufacturer_key(name) == "trina solar", repr(name)


def test_the_alias_table_is_applied() -> None:
    assert manufacturer_key("Hanwha Q CELLS Co., Ltd.") == "qcells"
    assert same_manufacturer("CSI Solar Co., Ltd.", "Canadian Solar Inc.")


def test_normalisation_is_idempotent() -> None:
    for name in ("Trina Solar Co.,Ltd", "AS Solar", "Hanwha Q CELLS"):
        once = manufacturer_key(name)
        assert manufacturer_key(once) == once


# --- stage 2: decomposition -----------------------------------------------------


def test_family_and_variant_tokens_do_not_overlap() -> None:
    """Review: every alphabetic token went into `variant_tokens` *and* stayed in
    `family`, which is not a decomposition. `Alpha Pure-R 410` and `Alpha Pure-R
    410 BLK` then had different families, so the 0.30 family weight was lost
    before the suffix table was consulted and the pair's ceiling was 0.70 —
    below auto-merge. Every row of `SUFFIX_RULES` was inert."""
    parts = decompose("Alpha Pure-R 410 BLK", 410.0)
    assert parts.family == "alpha pure r #"
    assert parts.variant_tokens == ("blk",)
    for token in parts.variant_tokens:
        assert token not in parts.family


def test_only_the_bin_token_is_masked() -> None:
    """D-4: mask only the token equal to nameplate Pmax (+/-1 W), not every 3-4
    digit run — which would collide First Solar `FS-267` with `FS-367`.

    A digit run that is not *this* product's Pmax stays in the family, so the two
    do not fold together on a nameplate that belongs to neither.
    """
    assert decompose("FS-367", 267.0).family == "fs 367"
    assert decompose("FS-267", 267.0).family == "fs #"


def test_the_first_solar_pair_is_not_auto_merged() -> None:
    """Each masking its own bin gives one family — which is correct, they are one
    series — and the 0.15 bin signal is what separates them. The collision D-4
    warns about is a family match *with no bin discriminator*, so this checks the
    end state rather than the intermediate."""
    result = score(
        Candidate(manufacturer="First Solar", model="FS-267", nameplate=267.0, pmax=267.0),
        Candidate(manufacturer="First Solar", model="FS-367", nameplate=367.0, pmax=367.0),
    )
    assert result.signals["bin"] == 0.0
    assert result.outcome is not MatchOutcome.SAME_PRODUCT


def test_this_products_bin_is_preferred_to_the_other_sides() -> None:
    """Trying every nameplate against every token would let `ABC-267-500` at
    500 W mask its `267` because the other side happens to be a 267 — recording
    a bin this product does not have."""
    parts = decompose("ABC-267-500", 500.0, 267.0)
    assert parts.bin_watts == 500.0
    assert parts.family == "abc 267 #"


def test_a_declared_bin_is_never_overridden_by_the_other_side() -> None:
    """The other side's nameplate is a fallback for *no* bin, not a second guess
    at a bin that failed to match. A 705 W listing whose string says 700 must not
    come back claiming a 700 W bin because the product it is compared against
    declared one."""
    parts = decompose("TSM-700NEG21C.20", 705.0, 700.0)
    assert parts.bin_watts is None
    assert parts.family == "tsm 700 neg 21 c 20"


def test_the_fallback_only_applies_when_there_is_no_bin() -> None:
    with_own = decompose("TSM-700NEG21C.20", 700.0, 999.0)
    without_own = decompose("TSM-700NEG21C.20", None, 700.0)
    assert with_own.bin_watts == without_own.bin_watts == 700.0


def test_the_bin_tolerance_is_one_watt() -> None:
    assert decompose("TSM-700NEG21C.20", 699.0).bin_watts == 700.0
    assert decompose("TSM-700NEG21C.20", 698.0).bin_watts is None


def test_the_family_does_not_depend_on_which_bin_is_asked() -> None:
    """Review: `decompose` masked using one side's nameplate, so
    `TSM-700NEG21C.20` gave family `tsm # neg 21 c 20` against nameplate 700 and
    `tsm 700 neg 21 c 20` against nothing. The same model string had two family
    keys, decided by what it happened to be compared against.

    That is the Jinko case exactly: its sheet is titled `66HL4M-BDV / 605-630
    Watt` and carries no per-bin model number, so one side always has no bin —
    the one pairing D-4 says must work was the one that could not.
    """
    assert (
        decompose("TSM-700NEG21C.20", 700.0, None).family
        == decompose("TSM-700NEG21C.20", None, 700.0).family
    )


def test_two_bins_of_one_family_share_a_family_key() -> None:
    assert (
        decompose("TSM-700NEG21C.20", 700.0).family == decompose("TSM-705NEG21C.20", 705.0).family
    )


def test_no_bin_means_no_variant_split() -> None:
    """D-4's measured suffix rules are all trailing modifiers, so without a bin
    there is no principled split point. Guessing one is worse than an empty
    tuple, which at least says nothing rather than something wrong."""
    parts = decompose("66HL4M-BDV", None)
    assert parts.bin_watts is None
    assert parts.variant_tokens == ()


def test_plus_is_significant_not_a_footnote() -> None:
    """D-4: `SIL-380HC` vs `SIL-380HC+` differ at Isc 11.36 vs 10.28 and Voc
    42.17 vs 45.35. `+` is part of the model; `*` is a wafer size."""
    plain = decompose("SIL-380HC", 380.0)
    plus = decompose("SIL-380HC+", 380.0)
    assert plain.variant_tokens != plus.variant_tokens


def test_a_digit_run_after_the_bin_is_not_invisible() -> None:
    """Review: `variant_tokens` dropped every numeric token (`if not
    t.isdigit()`), and `family` stops at the bin. A digit run *after* the bin
    therefore reached no signal at all - not the family, not the variant, not the
    bin - so two model strings differing only there scored a clean 1.00 and
    auto-merged.

    Jinko's format code is exactly that shape: the bin is the second token of
    `JKM605N-66HL4M-BDV`, so `66` (66-cell) and `78` (78-cell) sit behind it.
    Those are physically different modules, and a false merge is the one outcome
    D-4 optimises against.
    """
    sixty_six = decompose("JKM605N-66HL4M-BDV", 605.0)
    seventy_eight = decompose("JKM605N-78HL4M-BDV", 605.0)
    assert sixty_six.family == seventy_eight.family, "the bin is the second token"
    assert sixty_six.variant_tokens != seventy_eight.variant_tokens

    result = score(
        Candidate(
            manufacturer="Jinko Solar", model="JKM605N-66HL4M-BDV", nameplate=605.0, pmax=605.0
        ),
        Candidate(
            manufacturer="Jinko Solar", model="JKM605N-78HL4M-BDV", nameplate=605.0, pmax=605.0
        ),
    )
    assert result.signals["variant"] == 0.0
    assert result.outcome is not MatchOutcome.SAME_PRODUCT


def test_the_verbatim_original_is_kept() -> None:
    assert decompose("TSM-700NEG21C.20", 700.0).verbatim == "TSM-700NEG21C.20"


# --- stage 3 and 4: suffix rules and scoring ------------------------------------


def _rec(model: str, **kwargs: float) -> Candidate:
    return Candidate(manufacturer="REC Solar Pte. Ltd.", model=model, nameplate=410.0, **kwargs)


def _maxeon(model: str, **kwargs: float) -> Candidate:
    return Candidate(
        manufacturer="Maxeon Solar Technologies, Ltd.", model=model, nameplate=410.0, **kwargs
    )


def test_every_suffix_rule_key_is_a_fixed_point() -> None:
    """Review: `SUFFIX_RULES` was keyed on hand-written `("rec", "blk")`. The
    real CEC entity string is `REC Solar Pte. Ltd.`, which normalises to
    `rec solar` — so the row matched nothing and the table was inert in a second,
    independent way. Deriving the keys from `manufacturer_key` means a change to
    stage 1 cannot strand a rule; this asserts the property directly."""
    for mfr_key, _token in SUFFIX_RULES:
        assert manufacturer_key(mfr_key) == mfr_key, (
            f"{mfr_key!r} is not what stage 1 produces, so the row is unreachable"
        )


def test_a_safe_suffix_can_actually_reach_auto_merge() -> None:
    """The point of the whole suffix table, and it could not fire before: `REC`
    + `blk` is measured 22/0 identical, so a pair differing only by it is the
    same product."""
    result = score(_rec("Alpha Pure-R 410", pmax=410.0), _rec("Alpha Pure-R 410 BLK", pmax=410.0))
    assert result.signals["family"] == WEIGHTS["family"]
    assert result.signals["variant"] == WEIGHTS["variant"]
    assert result.outcome is MatchOutcome.SAME_PRODUCT


def test_the_same_token_is_never_safe_for_a_different_manufacturer() -> None:
    """`BLK` is 22/0 identical for REC and 0/27 different for Maxeon. A global
    strip-list is provably wrong, which is why the key is a pair."""
    assert SUFFIX_RULES[(manufacturer_key("REC Solar Pte. Ltd."), "blk")] is SuffixVerdict.SAFE
    assert (
        SUFFIX_RULES[(manufacturer_key("Maxeon Solar Technologies, Ltd."), "blk")]
        is SuffixVerdict.NEVER_STRIP
    )
    result = score(_maxeon("SPR-X 410", pmax=410.0), _maxeon("SPR-X 410 BLK", pmax=410.0))
    assert result.outcome is not MatchOutcome.SAME_PRODUCT


def test_a_never_strip_token_vetoes_auto_merge() -> None:
    """A token measured different in every observed pair is a stronger statement
    than a weighted sum. Letting the score outvote it makes the measurement
    decorative — the pair still reaches 0.90 without the variant weight."""
    result = score(_maxeon("SPR-X 410", pmax=410.0), _maxeon("SPR-X 410 BLK", pmax=410.0))
    assert result.score >= AUTO_MERGE_THRESHOLD
    assert result.outcome is MatchOutcome.VARIANT_MISMATCH
    assert any("always a different product" in n for n in result.notes)


def test_an_unmeasured_token_is_treated_as_significant() -> None:
    """`-V` 72/189, `-BB` 264/15 and `-BW` 412/9 are manufacturer-dependent and
    deliberately absent from the table.

    Review: this asserted the signal and the note and stopped there, and the
    outcome was `SAME_PRODUCT`. The five weights sum to 1.00 against a 0.90 band,
    so dropping the 0.10 variant signal lands exactly *on* the threshold — the
    token was called significant and then auto-merged anyway, which made the
    difference between a SAFE token and an unmeasured one invisible in every
    outcome the matcher produces.
    """
    result = score(_rec("Alpha Pure-R 410", pmax=410.0), _rec("Alpha Pure-R 410 BW", pmax=410.0))
    assert result.signals["variant"] == 0.0
    assert any("no measured rule" in n for n in result.notes)
    assert result.score >= AUTO_MERGE_THRESHOLD
    assert result.outcome is MatchOutcome.VARIANT_MISMATCH


def test_a_safe_token_and_an_unmeasured_one_reach_different_outcomes() -> None:
    """The suffix table has to change an outcome, or it is decoration. `blk` is
    measured 22/0 identical for REC and `bw` is deliberately unmeasured, so the
    two must not land in the same band."""
    safe = score(_rec("Alpha Pure-R 410", pmax=410.0), _rec("Alpha Pure-R 410 BLK", pmax=410.0))
    unmeasured = score(
        _rec("Alpha Pure-R 410", pmax=410.0), _rec("Alpha Pure-R 410 BW", pmax=410.0)
    )
    assert safe.outcome is MatchOutcome.SAME_PRODUCT
    assert unmeasured.outcome is MatchOutcome.VARIANT_MISMATCH


def test_every_differing_token_is_reported() -> None:
    """Review: `_variant_delta` returned inside its loop, so which notes a
    reviewer saw depended on sort order and a measured NEVER_STRIP token sitting
    after an unknown one was never mentioned at all."""
    result = score(_maxeon("SPR-X 410", pmax=410.0), _maxeon("SPR-X 410 ZZZ BLK", pmax=410.0))
    assert any("blk" in n for n in result.notes)
    assert any("zzz" in n for n in result.notes)


def test_scoring_is_symmetric() -> None:
    """Review: `_variant_delta` was passed the *left* manufacturer key only, so
    `score(a, b)` and `score(b, a)` could differ. A matcher whose answer depends
    on argument order has no defined behaviour on an unordered pair."""
    pairs = [
        (_rec("Alpha Pure-R 410", pmax=410.0), _rec("Alpha Pure-R 410 BLK", pmax=410.0)),
        (_rec("Alpha Pure-R 410", pmax=410.0), _maxeon("SPR-X 410 BLK", pmax=410.0)),
        (
            Candidate(manufacturer="Trina Solar", model="TSM-700NEG21C.20", nameplate=700.0),
            Candidate(manufacturer="Trina Solar Co.,Ltd", model="TSM-700NEG21C.20"),
        ),
    ]
    for left, right in pairs:
        forward, backward = score(left, right), score(right, left)
        assert forward.score == backward.score
        assert forward.outcome is backward.outcome
        assert forward.signals == backward.signals


def test_the_jinko_pairing_resolves() -> None:
    """One side knows its bin, the other's sheet carries only the range."""
    result = score(
        Candidate(manufacturer="Jinko Solar", model="JKM605N-66HL4M-BDV", nameplate=605.0),
        Candidate(manufacturer="Jinko Solar Co., Ltd.", model="JKM605N-66HL4M-BDV"),
    )
    assert result.signals["family"] == WEIGHTS["family"]


def test_no_auto_merge_on_manufacturer_and_model_alone() -> None:
    """D-4's imperative, and the weights alone cannot honour it: manufacturer +
    family + bin + variant sum to exactly 0.90."""
    result = score(
        Candidate(manufacturer="Adani Solar", model="ASB-M10-144-550", nameplate=550.0),
        Candidate(manufacturer="Adani Green Energy", model="ASB-M10-144-550", nameplate=550.0),
    )
    assert result.outcome is not MatchOutcome.SAME_PRODUCT


def test_the_adani_pair_is_held_for_review() -> None:
    """One model string under two entity names, PTC 509.9 vs 518.2 — genuinely
    different products, and D-4's own counterexample."""
    result = score(
        Candidate(manufacturer="Adani Solar", model="ASB-M10-144-550", nameplate=550.0, pmax=509.9),
        Candidate(manufacturer="Adani Solar", model="ASB-M10-144-550", nameplate=550.0, pmax=518.2),
    )
    assert result.signals["electrical"] == 0.0
    assert result.score >= AUTO_MERGE_THRESHOLD
    assert result.outcome is MatchOutcome.VARIANT_MISMATCH


def test_a_fold_only_agreement_cannot_merge_unattended() -> None:
    """D-4: folding is for candidate retrieval, never the final decision. 108
    within-manufacturer fold-collisions exist and 6 are genuinely different
    products."""
    result = score(
        Candidate(manufacturer="Silfab", model="SIL-380HC", nameplate=380.0, isc=11.36),
        Candidate(manufacturer="Silfab", model="SIL-380HC+", nameplate=380.0, isc=10.28),
    )
    assert result.outcome is not MatchOutcome.SAME_PRODUCT


def test_the_bands_are_d4s() -> None:
    assert (AUTO_MERGE_THRESHOLD, VARIANT_THRESHOLD) == (0.90, 0.70)
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert WEIGHTS == {
        "manufacturer": 0.35,
        "family": 0.30,
        "bin": 0.15,
        "variant": 0.10,
        "electrical": 0.10,
    }


def test_unrelated_products_are_distinct() -> None:
    result = score(
        Candidate(manufacturer="First Solar", model="FS-267", nameplate=267.0),
        Candidate(manufacturer="Qcells", model="Q.PEAK DUO 405", nameplate=405.0),
    )
    assert result.outcome is MatchOutcome.DISTINCT
    assert result.score < VARIANT_THRESHOLD


def test_an_unnormalisable_manufacturer_is_distinct_not_a_crash() -> None:
    result = score(
        Candidate(manufacturer="Co., Ltd.", model="X-400", nameplate=400.0),
        Candidate(manufacturer="Qcells", model="X-400", nameplate=400.0),
    )
    assert result.outcome is MatchOutcome.DISTINCT
    assert result.score == 0.0


def test_the_bin_signal_is_withheld_rather_than_guessed() -> None:
    result = score(
        Candidate(manufacturer="Jinko Solar", model="66HL4M-BDV"),
        Candidate(manufacturer="Jinko Solar", model="66HL4M-BDV"),
    )
    assert result.signals["bin"] == 0.0
    assert any("bin signal withheld" in n for n in result.notes)


# --- corroboration keyed on the frozen contract ---------------------------------


def test_every_electrical_row_is_a_contract_key() -> None:
    """Review: the map was keyed on `voc` and `isc`, which the contract does not
    have — it carries `temp_coeff_voc` and `temp_coeff_isc`, different
    quantities. Third instance of the invented-key defect, after the tolerance
    table's 19 and the tier table's omissions."""
    unknown = set(ELECTRICAL_ROWS.values()) - _contract_keys()
    assert not unknown, f"electrical rows keyed on non-contract names: {unknown}"


def test_voc_and_isc_are_deliberately_absent() -> None:
    """Not an oversight: the contract has no scalar Voc or Isc field, so there is
    no D-2 row to key on and the fallback is exact-at-printed-precision. Naming
    it here means a future contract field forces this test to be revisited."""
    assert "voc" not in ELECTRICAL_ROWS
    assert "isc" not in ELECTRICAL_ROWS
    assert not ({"voc", "isc"} & _contract_keys())


def test_pmax_corroboration_uses_the_nameplate_band() -> None:
    """D-2 gives `nameplate_power` +/-1 Wp; 5 W bins mean a wider band merges
    adjacent SKUs."""
    near = score(
        Candidate(manufacturer="Qcells", model="Q.PEAK 410", nameplate=410.0, pmax=410.0),
        Candidate(manufacturer="Qcells", model="Q.PEAK 410", nameplate=410.0, pmax=410.5),
    )
    far = score(
        Candidate(manufacturer="Qcells", model="Q.PEAK 410", nameplate=410.0, pmax=410.0),
        Candidate(manufacturer="Qcells", model="Q.PEAK 410", nameplate=410.0, pmax=415.0),
    )
    assert near.signals["electrical"] == WEIGHTS["electrical"]
    assert far.signals["electrical"] == 0.0


# --- stage 5: one ordering, not two ---------------------------------------------


def test_the_surrogate_id_hashes_the_normalised_keys() -> None:
    """A hash of the raw strings would put the Trina entity split back into the
    tie-break after stage 1 had removed it everywhere else."""
    left = identity_keys("Trina Solar", "TSM-700NEG21C.20", 700.0)
    right = identity_keys("Trina Solar Co.,Ltd", "TSM-700NEG21C.20", 700.0)
    assert left.surrogate_id == right.surrogate_id


def test_different_bins_get_different_ids() -> None:
    assert (
        identity_keys("Trina Solar", "TSM-700NEG21C.20", 700.0).surrogate_id
        != identity_keys("Trina Solar", "TSM-705NEG21C.20", 705.0).surrogate_id
    )


def test_the_ordering_uses_the_normalised_keys_when_they_are_filled() -> None:
    """The composition this rewrite exists to make: identity computes the keys,
    the schema declares the slots, and there is exactly one total order rather
    than a second implementation free to drift."""
    keys = identity_keys("Trina Solar Co.,Ltd", "TSM-700NEG21C.20", 700.0)
    instance = ComponentInstance(
        supplier="Trina Solar Co.,Ltd",
        model="TSM-700NEG21C.20",
        component_category=ComponentCategory.PV_MODULES,
        nameplate=700.0,
        manufacturer_key=keys.manufacturer_key,
        model_family=keys.model_family,
        surrogate_id=keys.surrogate_id,
    )
    assert instance.ordering_key()[1] == "trina solar"
    assert instance.ordering_key()[2] == keys.model_family


def test_two_entity_spellings_sort_together() -> None:
    def _built(supplier: str) -> ComponentInstance:
        keys = identity_keys(supplier, "TSM-700NEG21C.20", 700.0)
        return ComponentInstance(
            supplier=supplier,
            model="TSM-700NEG21C.20",
            component_category=ComponentCategory.PV_MODULES,
            nameplate=700.0,
            manufacturer_key=keys.manufacturer_key,
            model_family=keys.model_family,
            surrogate_id=keys.surrogate_id,
        )

    assert _built("Trina Solar").ordering_key() == _built("Trina Solar Co.,Ltd").ordering_key()


def test_an_unnormalised_instance_still_has_a_total_order() -> None:
    """A partially-normalised store must still sort. Falling back to the raw
    string is visible; raising would only move the failure."""
    instance = ComponentInstance(
        supplier="Trina Solar",
        model="TSM-700NEG21C.20",
        component_category=ComponentCategory.PV_MODULES,
    )
    assert instance.ordering_key()[1] == "Trina Solar"


# --- what is not implemented ----------------------------------------------------


def test_d4a_is_recorded_rather_than_implied() -> None:
    """Silence is what made the tolerance table's invented keys invisible for
    four commits. Everything here is the PV-module algorithm; inverters and BESS
    break it in ways D-4a measured across six vendors."""
    assert "inverter identity key" in UNIMPLEMENTED_D4A
    assert "BESS group B and C" in UNIMPLEMENTED_D4A
    assert all(reason.strip() for reason in UNIMPLEMENTED_D4A.values())


def test_the_variant_mismatch_gap_is_named() -> None:
    """D-4 is explicit that a variant mismatch is *not* a spec conflict, and
    nothing downstream can express that yet."""
    assert any("ConflictClass" in key for key in UNIMPLEMENTED_D4A)


def test_the_surrogate_id_does_not_depend_on_the_nameplates_python_type() -> None:
    """One product, two spellings of its nameplate.

    `ComponentInstance.nameplate` is a `float` after its validator; a nameplate
    read from a JSON row or a CEC export arrives as an `int`. Hashing
    `repr(nameplate)` gave those two ids, so one SKU sorted as two rows and the
    workbook reordered on re-ingest with no data change - AC-7's failure mode
    reaching the tie-break.
    """
    assert (
        identity_keys("Trina Solar", "TSM-700NEG21C.20", 700).surrogate_id
        == identity_keys("Trina Solar", "TSM-700NEG21C.20", 700.0).surrogate_id
    )


def test_an_absent_nameplate_is_not_the_same_as_zero() -> None:
    """Normalising through `float` must not fold `None` onto a number: 'no
    nameplate stated' and 'a nameplate of 0' are different facts."""
    assert (
        identity_keys("Trina Solar", "TSM-700NEG21C.20", None).surrogate_id
        != identity_keys("Trina Solar", "TSM-700NEG21C.20", 0.0).surrogate_id
    )
