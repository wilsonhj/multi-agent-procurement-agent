"""Supplier and model identity resolution — clarifications D-4, issue #9.

Deterministic and auditable, with no fuzzy matching. A wrong merge either
fabricates a conflict or hides one, and neither is visible afterwards.

Five facts force the design, all measured against the CEC list (D-4):

1. **One datasheet is not one product.** The Trina `TSM-NEG21C.20` sheet covers
   6 bins and CEC carries 22 rows for the family. Jinko's sheet is titled only
   "66HL4M-BDV / 605-630 Watt" - the per-bin model number appears nowhere on it.
2. 97.5% of CEC rows embed their own Pmax in the model string.
3. **Families split across entity strings.** Trina bins 635-725 W sit under
   `Trina Solar Co.,Ltd`, bins 730/735/740 under `Trina Solar`, so looking up
   (`Trina Solar`, `TSM-700NEG21C.20`) returns nothing. D-4 names this as the
   matcher's regression test; it is `test_the_trina_entity_split` below.
4. 157 model numbers appear under more than one manufacturer name.
5. 100% of CEC inverter rows carry a `{Vac}` suffix, and the same base model at
   different voltages can carry different kW.

**Not implemented here: the data.** D-4 says to seed the alias table from CEC's
`Notes` column ("Formerly listed under Hanwha Q CELLS", 627 rows) rather than
hand-authoring it, and to derive the per-manufacturer suffix rules from measured
electrical agreement. Neither dataset is in this repo. `MANUFACTURER_ALIASES` and
`SUFFIX_RULES` are therefore the mechanism plus the entries D-4 states outright -
they are meant to be *loaded*, and `score` degrades honestly when they are empty
rather than guessing.

**Not implemented here either: D-4a.** Everything below is the PV-module
algorithm. Inverters and BESS break it in ways D-4a measured across six vendors,
and pretending otherwise is worse than an empty table. `UNIMPLEMENTED_D4A`
records that rather than leaving a reader to infer it from silence.

Four defects in the first version are worth keeping in view, because each passed
a green suite:

- Legal suffixes were stripped **positionally**, from anywhere in the name, so
  Norwegian `AS Solar` and `Solar, Inc.` both normalised to `solar` — a false
  merge of two unrelated companies, in the one place D-4 says false merges are
  the failure to avoid.
- Stage 2 was not a decomposition: variant tokens stayed inside `family`, so a
  suffix measured SAFE could never lift a pair past 0.70 and the entire
  `SUFFIX_RULES` table was inert.
- `decompose` masked the bin token using one side's nameplate, so the same model
  string produced different family keys depending on what it was compared
  against — and that is exactly the Jinko case, where one side has no bin at all.
- `ELECTRICAL_ROWS` keyed corroboration on `voc` and `isc`, which the frozen
  contract does not have. Third instance of the invented-key defect.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ...schema import ConflictCandidate, SourceRef, SourceTier
from ..conflict_hitl import tolerance_for, values_conflict
from ..conflict_hitl.tolerance import DEFAULT_TOLERANCE, FieldTolerance

#: Legal-form tokens stripped from the **end** of a manufacturer name.
#:
#: **Legal suffixes only. Never descriptive tokens.** Measured: stripping legal
#: forms takes 408 CEC names to 394 keys with 14 collisions, all true positives.
#: Adding solar/energy/power/technology gives 382 keys *with false merges*, and
#: drives `POWER ELECTRONICS`, `Solar Power (SPI)` and `Energy America, LLC` to
#: the empty string. The `Co./Ltd` cluster alone has 20 distinct spellings in CEC
#: data, one of them ending in U+2002 EN SPACE - hence NFKD and a unicode-aware
#: whitespace split rather than `str.split(" ")`.
#:
#: `holdings`, `group`, `international` and `intl` were in this set and are not
#: legal forms in any jurisdiction - they are part of a trading name, and
#: stripping them merges `X Group` with `X`. D-4's rule is not "strip the words
#: that look corporate"; it is legal forms and nothing else.
LEGAL_SUFFIXES: frozenset[str] = frozenset(
    {
        "co",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "ltd",
        "limited",
        "llc",
        "lp",
        "llp",
        "plc",
        "gmbh",
        "ag",
        "kg",
        "bv",
        "nv",
        "sa",
        "sas",
        "srl",
        "spa",
        "ab",
        "as",
        "oy",
        "oyj",
        "aps",
        "pty",
        "kk",
        "sdn",
        "bhd",
        "pte",
        "jsc",
        "ojsc",
        "pjsc",
    }
)

#: Manufacturer keys that denote the same entity. Seed from CEC's `Notes` column.
#:
#: The four D-4 names outright, with their row counts, as a shape example. This
#: is not a complete table and is not meant to be hand-grown.
MANUFACTURER_ALIASES: dict[str, str] = {
    "hanwha q cells": "qcells",
    "q cells": "qcells",
    "csi solar": "canadian solar",
    "neo solar power": "united renewable energy",
}


class SuffixVerdict(StrEnum):
    """What a model-number suffix means for identity, per manufacturer."""

    NEVER_STRIP = "never_strip"
    """Electrically different every time it was measured. `-TV` 0/83 identical,
    `-Q` 0/62, `-R` 0/36, `-P` 0/35. Vetoes auto-merge: a token measured
    different in every observed pair is a stronger statement than a weighted
    score, and letting the score outvote it makes the measurement decorative."""

    SAFE = "safe"
    """Electrically identical every time. `-I` 27/0, ` XV` 27/0, `-3BB` 13/0.
    A pair differing only by a SAFE token can reach auto-merge - which requires
    that the token is *not* part of the family key, or the family signal is lost
    first and the ceiling is 0.70."""


#: Entity strings the seed rules below were measured against, kept verbatim so
#: the keys can be *derived* rather than transcribed. See `SUFFIX_RULES`.
_REC = "REC Solar Pte. Ltd."
_MAXEON = "Maxeon Solar Technologies, Ltd."

#: D-4a and Stage 5's downstream consumers, recorded rather than left to silence.
#:
#: The tolerance table's invented keys were invisible for four commits because
#: nothing said what was missing. Same remedy: name it, and let a test assert the
#: note still exists.
UNIMPLEMENTED_D4A: dict[str, str] = {
    "inverter identity key": (
        "D-4a: a utility inverter's model number is usually kVA at one AC voltage "
        "tap on identical hardware - SMA `SC 4000/4200/4400/4600 UP-US` are all "
        "3850 A. So power-number equality is not identity and inequality is not "
        "difference, and Stage 2's bin masking actively misleads. D-4a's key is "
        "`(manufacturer, family, dc_voltage_class, ac_nominal_voltage, "
        "ac_nominal_current, mppt_count, certification_set)`, and three of those "
        "have no frozen-contract field. `score` implements the module algorithm; "
        "applying it to an inverter pair is out of scope until that key exists."
    ),
    "BESS group B and C": (
        "D-4a: Fluence, Wartsila and CATL publish marketing names with no model "
        "number, so there is no string to decompose. Group A (Sungrow "
        "PowerTitan, BYD, HiTHIUM, EVE, LG) would parse, but a matcher that "
        "silently works for one of three groups is worse than one that says so."
    ),
    "Enphase -DOM- same-product rule": (
        "D-4a's cleanest same-product case: `IQ8PLUS-72-M-DOM-US` is electrically "
        "identical to the non-DOM part and differs only in domestic-content "
        "origin. The matcher must call it the same product *while* the compliance "
        "fields stay different. That needs the suffix table to carry a "
        "'same product, different compliance' verdict distinct from SAFE, and it "
        "needs the Tax Incentives tab not to merge the fields it discriminates on."
    ),
    "VARIANT_MISMATCH has no ConflictClass": (
        "D-4 is explicit that a variant mismatch is *not* a spec conflict. "
        "Nothing downstream can yet express that distinction, so a caller has to "
        "read `MatchOutcome` directly rather than seeing it in the conflict "
        "queue."
    ),
}

_PUNCT = re.compile(r"[^0-9a-z+*]+")
_TOKENS = re.compile(r"[0-9]+|[a-z+*]+")

#: Characters that separate name tokens without being spaces.
#:
#: `-` was absent, so `Trina-Solar Co.,Ltd` produced the single token
#: `trina-solar`, which matches nothing and leaves the entity split unresolved -
#: the failure this normalisation exists to fix, reintroduced by a missing
#: character in a character class. The unicode dashes are here because CEC data
#: contains them and NFKD does not fold them to ASCII `-`.
_NAME_SEPARATORS = re.compile(r"[.,()/&+\-‐‑‒–—―−]+")


def manufacturer_key(name: str) -> str:
    """Stage 1. NFKD-fold, casefold, strip trailing legal forms, collapse.

    **Trailing only.** The first version removed a legal token from anywhere in
    the name, which made Norwegian `AS Solar` and `Solar, Inc.` both normalise to
    `solar`. `as`, `sa`, `ab`, `co`, `ag`, `kg` and `lp` are all common words or
    initials in a leading position, and a false merge is the one outcome D-4
    optimises against - it either fabricates a conflict between two companies'
    products or hides a real one, invisibly.

    Raises on an empty result rather than returning `""`: a key that folds a
    manufacturer to nothing merges it with every other such manufacturer, which
    is the false merge D-4 measured when descriptive tokens were included.

    **Format characters are deleted, not carried through.** `schema.field.
    _normalise_token` already strips these and the contract's Conditions section
    says why: "the zero-width and byte-order marks PDF and XLSX extraction leaves
    behind". Here they cost more than the rejected token they cost there - a
    byte-order mark on the front of a name yields a *different key*, so the Trina
    entity split D-4 names as the regression test reopens on any document whose
    extractor left one behind, and a zero-width space inside `Co.,Ltd` defeats
    the legal-form strip outright. Unicode category `Cf` rather than a
    hand-listed set, because that is precisely what these characters are: BOM,
    ZWSP, ZWNJ, ZWJ, word joiner, soft hyphen and the bidi marks all carry it,
    and none of them is part of a name.
    """
    folded = unicodedata.normalize("NFKD", name).casefold()
    folded = "".join(
        ch for ch in folded if not unicodedata.combining(ch) and unicodedata.category(ch) != "Cf"
    )
    # Punctuation becomes a separator rather than being stripped in place:
    # `Trina Solar Co.,Ltd` has no space between `Co.` and `Ltd`, so stripping
    # gives the single token `coltd`, which matches no legal suffix and leaves
    # the entity split D-4 names as the regression test unresolved. Splitting on
    # unicode whitespace afterwards also folds the CEC entry ending in U+2002.
    kept = _NAME_SEPARATORS.sub(" ", folded).split()
    while kept and kept[-1] in LEGAL_SUFFIXES:
        kept.pop()
    key = " ".join(kept).strip()
    if not key:
        raise ValueError(f"manufacturer name {name!r} normalises to an empty key")
    return MANUFACTURER_ALIASES.get(key, key)


#: Suffix rules keyed on `(manufacturer_key, token)` — **never globally.**
#:
#: `BLK` is electrically identical for REC (22/0) and always different for Maxeon
#: (0/27). A global strip-list is provably wrong, which is why the key is a pair.
#: `-V` (72/189), `-BB` (264/15) and `-BW` (412/9) are manufacturer-dependent and
#: are deliberately absent: an unknown pair is treated as significant.
#:
#: **The keys are computed, not transcribed.** Writing `("rec", "blk")` by hand
#: made the row unreachable the moment `group` left `LEGAL_SUFFIXES`, because the
#: real entity string normalises to `rec solar` and nothing said so - the same
#: silent-orphan defect as the tolerance table's 19 invented keys, one table
#: over. Deriving the key from `manufacturer_key` means a change to stage 1
#: cannot leave a rule stranded, and
#: `test_every_suffix_rule_key_is_a_fixed_point` checks it.
SUFFIX_RULES: dict[tuple[str, str], SuffixVerdict] = {
    (manufacturer_key(_REC), "blk"): SuffixVerdict.SAFE,
    (manufacturer_key(_MAXEON), "blk"): SuffixVerdict.NEVER_STRIP,
}


def same_manufacturer(left: str, right: str) -> bool:
    """Whether two entity strings denote one manufacturer.

    The Trina case: `Trina Solar` and `Trina Solar Co.,Ltd` differ only by legal
    form, so the family split across the two entity strings resolves.
    """
    return manufacturer_key(left) == manufacturer_key(right)


class ModelParts(BaseModel):
    """Stage 2. A model number decomposed into D-4's three disjoint parts.

    `family` and `variant_tokens` do not overlap. The first version put every
    alphabetic token in `variant_tokens` *and* left it in `family`, which is not
    a decomposition: `Alpha Pure-R 410` and `Alpha Pure-R 410 BLK` then had
    different families, the 0.30 family weight was lost before the suffix table
    was ever consulted, and the pair's ceiling was 0.70 - below auto-merge. The
    `("rec", "blk"): SAFE` row could not change any outcome it was written for.
    """

    model_config = ConfigDict(frozen=True)

    family: str = Field(
        description="Tokens up to and including the masked bin, with the bin as `#`"
    )
    bin_watts: float | None = Field(default=None, description="The masked token, if one matched")
    variant_tokens: tuple[str, ...] = Field(
        default=(),
        description=(
            "The tokens *after* the bin, **numeric ones included**. D-4's measured "
            "suffix rules are all trailing modifiers, so with no bin there is no "
            "principled split point and this stays empty rather than guessing "
            "one. Filtering digits out of it looked harmless and was not: "
            "`family` stops at the bin, so a digit run behind the bin reached no "
            "signal at all - not family, not bin, not variant - and two model "
            "strings differing only there scored a clean 1.00 and auto-merged. "
            "Jinko's format code is that shape, with the bin second in "
            "`JKM605N-66HL4M-BDV` and the 66- or 78-cell code behind it."
        ),
    )
    verbatim: str = Field(description="Unfolded original. The decision reads this, not `family`.")


def decompose(model: str, *nameplates: float | None) -> ModelParts:
    """Split a model number into `(family, bin, variant_tokens)`.

    **Only a token equal to a nameplate Pmax (+/-1 W) is masked** — not every 3-4
    digit run, which would collide First Solar `FS-267` with `FS-367`. 97.5% of
    CEC rows embed their own Pmax, so this recovers the family for almost all of
    them and leaves the rest intact.

    Variadic in `nameplates` because a comparison must mask with **both** sides'
    bins. The first version took one, so `TSM-700NEG21C.20` decomposed against
    nameplate 700 gave family `tsm # neg 21 c 20` while the same string with no
    nameplate gave `tsm 700 neg 21 c 20` — the same model with two family keys,
    decided by what it happened to be compared against. That is precisely the
    Jinko case, whose sheet carries the range and not the per-bin number, so the
    one pairing D-4 says must work was the one that could not.

    **Only the first nameplate given wins**; the rest are consulted only when the
    earlier ones are `None`. Callers pass this model's own nameplate first, so a
    product that declares its bin is decomposed against that bin and nothing
    else. Matching against whichever nameplate happens to fit would let
    `ABC-267-500` at 500 W mask its `267` because the *other* product is a 267,
    and would let a 705 W listing record a bin of 700 because the other side
    declared one — a bin the product does not claim.
    """
    folded = _PUNCT.sub(" ", unicodedata.normalize("NFKD", model).casefold())
    tokens = _TOKENS.findall(folded)

    masked: list[str] = list(tokens)
    found: float | None = None
    bin_index: int | None = None
    target = next((n for n in nameplates if n is not None), None)
    if target is not None:
        for index, token in enumerate(tokens):
            if token.isdigit() and abs(float(token) - target) <= 1.0:
                found, bin_index = float(token), index
                masked[index] = "#"
                break

    if bin_index is None:
        return ModelParts(family=" ".join(masked), bin_watts=None, verbatim=model)
    return ModelParts(
        family=" ".join(masked[: bin_index + 1]),
        bin_watts=found,
        variant_tokens=tuple(tokens[bin_index + 1 :]),
        verbatim=model,
    )


class MatchOutcome(StrEnum):
    """Stage 4's three bands."""

    SAME_PRODUCT = "same_product"
    """>= 0.90, with electrical corroboration. Auto-merge."""

    VARIANT_MISMATCH = "variant_mismatch"
    """0.70-0.90, or a higher score held back by a veto. Same family, different
    variant. Surfaced as a *variant mismatch*, **not** as a spec conflict - the
    two are different findings and collapsing them sends a reviewer looking for a
    disagreement that is really a different product."""

    DISTINCT = "distinct"
    """< 0.70. No comparison."""


class Candidate(BaseModel):
    """One side of a match. The electricals are optional because a datasheet
    frequently omits them for a bin it covers only by range."""

    model_config = ConfigDict(frozen=True)

    manufacturer: str
    model: str
    nameplate: float | None = None
    pmax: float | None = None
    voc: float | None = None
    isc: float | None = None


class MatchScore(BaseModel):
    """A scored comparison, with the contributing signals kept.

    The breakdown is retained rather than reduced to a float: a reviewer asked to
    confirm a 0.85 needs to see *which* signal was missing, and an auto-merge at
    0.92 has to be auditable after the fact.
    """

    model_config = ConfigDict(frozen=True)

    score: float
    outcome: MatchOutcome
    signals: dict[str, float]
    notes: tuple[str, ...] = ()


#: Stage 4 weights, verbatim from D-4.
WEIGHTS: dict[str, float] = {
    "manufacturer": 0.35,
    "family": 0.30,
    "bin": 0.15,
    "variant": 0.10,
    "electrical": 0.10,
}

AUTO_MERGE_THRESHOLD = 0.90
VARIANT_THRESHOLD = 0.70


def _variant_delta(
    left: ModelParts, right: ModelParts, mfr_key: str | None
) -> tuple[bool, bool, tuple[str, ...]]:
    """Whether the variant tokens agree, allowing `(mfr, token)`-safe differences.

    Returns `(agree, vetoed, notes)`. Every differing token is evaluated, not
    just up to the first significant one: the first version returned inside the
    loop, so which notes a reviewer saw depended on sort order, and a NEVER_STRIP
    token after an unknown one was never reported.

    `mfr_key` is `None` when the two manufacturers differ. There is then no
    `(mfr, token)` to key on - the rules are per-manufacturer by construction,
    and D-4's whole point is that a global reading of them is provably wrong.
    Passing one side's key was also what made `score` asymmetric.
    """
    extra = set(left.variant_tokens) ^ set(right.variant_tokens)
    if not extra:
        return True, False, ()

    notes: list[str] = []
    agree = True
    vetoed = False
    for token in sorted(extra):
        if mfr_key is None:
            notes.append(f"{token!r} differs across two manufacturers; no rule applies")
            agree = False
            continue
        verdict = SUFFIX_RULES.get((mfr_key, token))
        if verdict is SuffixVerdict.SAFE:
            notes.append(f"{token!r} is electrically safe for {mfr_key!r}")
        elif verdict is SuffixVerdict.NEVER_STRIP:
            notes.append(f"{token!r} is always a different product for {mfr_key!r}")
            agree = False
            vetoed = True
        else:
            notes.append(f"{token!r} has no measured rule for {mfr_key!r}; treated as significant")
            agree = False
    return agree, vetoed, tuple(notes)


#: Which D-2 row governs each corroborating electrical parameter.
#:
#: **Only `pmax` has one.** The frozen contract has no `voc` and no `isc` field -
#: it carries `temp_coeff_voc` and `temp_coeff_isc`, which are different
#: quantities. The first version keyed this map on `"voc"` and `"isc"`, so
#: `tolerance_for` fell through to the default; the *behaviour* was right by
#: accident and the map said something false, which is the same defect class as
#: the tolerance table's 19 invented keys. `ELECTRICAL_FALLBACK` now states the
#: fallback as the decision it is.
ELECTRICAL_ROWS: dict[str, str] = {
    "pmax": "nameplate_power",
}

#: The rule for a corroborating parameter with no contract field, hence no D-2
#: row: exact, i.e. compared at printed precision.
#:
#: Two listings of one product should agree to the precision they are printed at.
#: D-4 says "within D-2 tolerance" for Voc and Isc; D-2 has nothing to say about
#: either, and inventing a band here would be the global tolerance D-2 exists to
#: remove, reintroduced one module over.
ELECTRICAL_FALLBACK: FieldTolerance = DEFAULT_TOLERANCE


def _tolerance_for_electrical(name: str) -> FieldTolerance:
    row = ELECTRICAL_ROWS.get(name)
    return tolerance_for(row) if row is not None else ELECTRICAL_FALLBACK


def _corroborates(name: str, left_value: float, right_value: float) -> bool:
    """Whether two electrical readings agree under the governing tolerance."""
    pair = [
        ConflictCandidate(
            value=value,
            unit=None,
            verbatim_value=repr(value),
            source_tier=SourceTier.SYSTEM_OF_RECORD,
            source_ref=SourceRef(document_id=f"identity-{side}"),
            confidence=1.0,
        )
        for side, value in (("left", left_value), ("right", right_value))
    ]
    verdict = values_conflict(pair[0], pair[1], tolerance=_tolerance_for_electrical(name))
    return not verdict.conflicts


def _electrical_pairs(left: Candidate, right: Candidate) -> dict[str, tuple[float, float]]:
    both = {
        "pmax": (left.pmax, right.pmax),
        "voc": (left.voc, right.voc),
        "isc": (left.isc, right.isc),
    }
    return {k: (a, b) for k, (a, b) in both.items() if a is not None and b is not None}


def score(left: Candidate, right: Candidate) -> MatchScore:
    """Stage 4. Weighted score over five signals, with D-4's three bands.

    **Never auto-merges on manufacturer + model alone.** Identical model strings
    under two entity names are usually one product, but `ASB-M10-144-550` under
    the two Adani entities has PTC 509.9 vs 518.2 — genuinely different. The
    weights alone cannot honour that: manufacturer + family + bin + variant sum
    to exactly 0.90, so a pair whose electricals *positively disagree* still
    reaches the threshold. Corroboration is therefore a **veto**, not a weight.
    The score says how similar; the veto says what may merge unattended.

    **Variant agreement is the same kind of veto, for the same arithmetic
    reason.** The five weights sum to 1.00 and the band is 0.90, so losing any
    single 0.10 signal still lands exactly on the threshold: a pair differing by
    a token with *no measured rule* scored 0.90 and auto-merged, while
    `_variant_delta` recorded it as "treated as significant" and the note went
    nowhere. That made the SAFE-versus-unknown distinction inert — the second way
    `SUFFIX_RULES` could have no effect on any outcome, after the family/variant
    overlap. It also contradicts what the middle band *means*: `VARIANT_MISMATCH`
    is "same family, different variant", so a pair whose variant tokens differ is
    that finding by definition, whatever the arithmetic says. `variant_veto`
    (NEVER_STRIP) is a strictly stronger case and keeps its own note.

    **Case and punctuation folding is for retrieval, never the final decision.**
    108 within-manufacturer fold-collisions exist and 6 are genuinely different
    products: `SIL-380HC` vs `SIL-380HC+` differ at Isc 11.36 vs 10.28. `+` and
    `*` therefore survive tokenisation and separate the two variants, and no
    fold-only agreement can auto-merge without electricals — which is the same
    veto, doing the work a claimed-but-absent `verbatim` short-circuit was
    described as doing in the first version.

    Symmetric in its arguments by construction: `score(a, b) == score(b, a)`.
    """
    signals: dict[str, float] = {}
    notes: list[str] = []

    try:
        left_key, right_key = (
            manufacturer_key(left.manufacturer),
            manufacturer_key(right.manufacturer),
        )
    except ValueError as exc:
        return MatchScore(score=0.0, outcome=MatchOutcome.DISTINCT, signals={}, notes=(str(exc),))

    same_mfr = left_key == right_key
    signals["manufacturer"] = WEIGHTS["manufacturer"] if same_mfr else 0.0

    # Both nameplates on both sides: the bin token has to be masked out of a
    # model string even when only the *other* side knows what the bin is.
    left_parts = decompose(left.model, left.nameplate, right.nameplate)
    right_parts = decompose(right.model, right.nameplate, left.nameplate)
    signals["family"] = WEIGHTS["family"] if left_parts.family == right_parts.family else 0.0

    if left_parts.bin_watts is not None and right_parts.bin_watts is not None:
        bins_agree = abs(left_parts.bin_watts - right_parts.bin_watts) <= 1.0
    else:
        bins_agree = (
            left.nameplate is not None
            and right.nameplate is not None
            and (abs(left.nameplate - right.nameplate) <= 1.0)
        )
        if left.nameplate is None or right.nameplate is None:
            notes.append("no bin on at least one side; bin signal withheld")
    signals["bin"] = WEIGHTS["bin"] if bins_agree else 0.0

    variants_agree, variant_veto, variant_notes = _variant_delta(
        left_parts, right_parts, left_key if same_mfr else None
    )
    notes.extend(variant_notes)
    signals["variant"] = WEIGHTS["variant"] if variants_agree else 0.0

    measured = _electrical_pairs(left, right)
    if not measured:
        signals["electrical"] = 0.0
        notes.append(
            "no electrical corroboration available; D-4 forbids auto-merge on "
            "manufacturer and model alone"
        )
    else:
        corroboration = {k: _corroborates(k, a, b) for k, (a, b) in measured.items()}
        if all(corroboration.values()):
            signals["electrical"] = WEIGHTS["electrical"]
        else:
            signals["electrical"] = 0.0
            disagreeing = sorted(k for k, agrees in corroboration.items() if not agrees)
            notes.append(f"electrical disagreement beyond tolerance: {', '.join(disagreeing)}")

    total = round(sum(signals.values()), 10)
    corroborated = signals["electrical"] > 0.0

    if total >= AUTO_MERGE_THRESHOLD and corroborated and variants_agree:
        outcome = MatchOutcome.SAME_PRODUCT
    elif total >= VARIANT_THRESHOLD:
        outcome = MatchOutcome.VARIANT_MISMATCH
    else:
        outcome = MatchOutcome.DISTINCT

    if total >= AUTO_MERGE_THRESHOLD and not corroborated:
        notes.append(
            "score reaches the auto-merge threshold but electrical corroboration "
            "is absent or contradicted; held at variant mismatch for review"
        )
    if total >= AUTO_MERGE_THRESHOLD and variant_veto:
        notes.append(
            "score reaches the auto-merge threshold but a variant token is "
            "measured different in every observed pair for this manufacturer; "
            "held at variant mismatch for review"
        )
    elif total >= AUTO_MERGE_THRESHOLD and not variants_agree:
        notes.append(
            "score reaches the auto-merge threshold but the variant tokens differ "
            "with no measured rule for this manufacturer; held at variant "
            "mismatch for review"
        )
    return MatchScore(score=total, outcome=outcome, signals=signals, notes=tuple(notes))


class IdentityKeys(BaseModel):
    """The normalised keys Stage 5's ordering sorts on.

    Deliberately *not* a second `ordering_key` implementation. `ComponentInstance`
    already carries the AC-7 order, and `schema` sits below `services` so it
    cannot import this module. Duplicating the ordering here would give the
    repository two total orders free to drift — the failure mode this whole
    rewrite exists to close.

    Instead the schema declares the slots and this fills them, the way
    `surrogate_id` already worked: `ComponentInstance.ordering_key()` reads
    `manufacturer_key` and `model_family` when they are populated and falls back
    to the raw strings when they are not.
    """

    model_config = ConfigDict(frozen=True)

    manufacturer_key: str
    model_family: str
    surrogate_id: str = Field(
        description=(
            "Stage 5's tie-break, and **not** the primary key. "
            "`(category, supplier, model)` is provably not unique on real data - "
            "36 duplicated `(Manufacturer, Model Number)` pairs and 157 model "
            "numbers under more than one manufacturer name - so an ordering "
            "without a tie-break sorts unstably exactly where the data is most "
            "ambiguous. Leading with it would make the workbook's row order "
            "meaningless to a reader."
        )
    )


def identity_keys(supplier: str, model: str, nameplate: float | None) -> IdentityKeys:
    """The one place the normalised identity keys are computed.

    `surrogate_id` hashes the *normalised* manufacturer and family rather than
    the raw strings, so `Trina Solar` and `Trina Solar Co.,Ltd` give one id for
    one product — which is the entity split D-4 names as the regression test. A
    hash of the raw strings would reintroduce it in the tie-break after Stage 1
    had removed it everywhere else.
    """
    mfr = manufacturer_key(supplier)
    family = decompose(model, nameplate).family
    digest = hashlib.sha256(
        "\x1f".join((mfr, family, repr(nameplate))).encode("utf-8")
    ).hexdigest()[:16]
    return IdentityKeys(manufacturer_key=mfr, model_family=family, surrogate_id=digest)
