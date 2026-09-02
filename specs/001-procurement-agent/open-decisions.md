# Open decisions — recommended defaults

Seven decisions the specs left to a human. Each carries a recommendation, the
reasoning, and a confidence marking. Nothing here is adopted; adopting means
folding it into `clarifications.md` and deleting the entry.

Items 8-10 existed here for one day (2026-09-02): three defects reproduced
against the running code whose fix needed a contract choice. They were adopted
as [D-16, D-17 and D-18](clarifications.md) and deleted, per the rule above.

> ⚠️ **"Nothing here is adopted" is no longer true of item 1, and the entry was
> not deleted (noted 2026-09-02).** `services/conflict_hitl/severity.py` implements
> item 1's lookup - its module docstring cites "open-decisions.md section 1" as its
> specification, `CRITICALITY` is the table below row for row, and
> `tests/test_severity.py` parses the frozen contract and fails on any key in
> either that is missing from the other. Item 7 shows the intended end state: it
> carries a **RATIFIED** block and stays for the record. Items 1 and 2 have neither
> been ratified in writing nor folded into `clarifications.md`, so the code is
> ahead of the decision record - the same shape as C7, where `sql/` enforced the
> label model months before D-15 wrote it down. A maintainer should ratify or
> retire them; this note does not do it for them.

Sourcing caveat: egress returned HTTP 403 for standards bodies, `ecfr.gov`, CEC
and manufacturer domains throughout, so **no standard, regulation or datasheet
was read verbatim**. External claims rest on search summarisation.

---

## 1. Severity assignment — a lookup, not a formula

**Confidence: firm on shape, reasoned on the assignments.**

`Severity` and the compose gate now exist in code; what assigns a severity does
not. The transferable finding from the triage literature is negative: AIAG-VDA's
2019 FMEA handbook **deleted** RPN (severity × occurrence × detection) in favour
of an Action Priority lookup, because a product collapses distinguishable risk
profiles onto one number and lets a low severity be inflated by detection. So
**do not multiply criticality by divergence.**

**Base severity from the field's criticality class**, one row per contract key:

| Class | Base | Examples |
|---|---|---|
| Attestation / eligibility | `CRITICAL` | certifications, BABA/FEOC status, domestic content, country of origin, ERCOT compliance items |
| Commercial | `HIGH` | $/W, price, all warranty terms, material-assistance cost ratio |
| Decision-driving performance | `MEDIUM` | nameplate power, efficiency, MVA, usable energy, RTE, cycle life, ampacity, TRD |
| Secondary comparison | `LOW` | MPPT count, harmonic spectrum, enclosure rating, conductor size, protocols |
| Descriptive | `INFORMATIONAL` | verbatim names, datasheet revision, stow strategy, support terms |

One exception worth calling out: **`vector_group` is `HIGH`, not descriptive.** It
looks like a string field and is a buildability field — D-6a establishes `Dyn1`
and `Dyn11` are 60° apart and cannot be paralleled.

**Then bounded ±1 modifiers**, summed and clamped: `+1` for divergence ≥10× the
D-2 tolerance (usually a decimal-comma error, D-5's highest-risk trap); `+1` for
inter-document where **both** sides are `system_of_record`; `+1` for ≥3 distinct
values in one group (a matcher failure, not a data disagreement); `−2` where a
unit mismatch reconciles after conversion (an extraction defect — fix the
normaliser, do not hold the workbook).

**Then floors nothing can lower.** Any D-3 Tier A field floors at `HIGH`.
Certification presence-vs-absence is `CRITICAL`, always: "not extracted" is not
"not certified".

**Invariant worth a test:** severity must be a **pure function of
`(field_name, conflict_class, condition_group, candidate_set)`** — no clock, no
reviewer identity, no queue state. FR-OUT-06 makes composition pure and the gate
reads severity, so a reviewer who could nudge severity would make the same store
produce different workbooks.

Not derived from source-tier pair alone (record-vs-web on a UL 9540A listing
beats inter-document on module weight) and not from magnitude alone (the RPN
error). Keep severity separate from queue priority, which folds in age and SLA.

---

## 2. Condition defaulting — resolve before grouping

**Confidence: reasoned; per-row below.**

`grouping_key()` fixed transitivity; it did not fix comparability. Add
`resolve_condition(field_key, category, raw, context) -> Condition` at extraction
time, filling in strict precedence: **stated** (never overridden) → **field-implied**
(the canonical field's own definition fixes it — `stc_rating` ⇒ `basis="stc"`) →
**convention** (only where a marking rule demonstrably exists) → **unknown**.

Record what was filled in `Condition.derived`, which already lives on the
subclass and is therefore excluded from `grouping_key()` by construction — so a
defaulted-STC and a stated-STC value group together while provenance stays honest.

**Safe to default:** unqualified PV electrical values ⇒ `stc` (IEC 61730-1's
marking clause requires nameplate electrical parameters to refer to STC);
unqualified MPPT window ⇒ `full_range`; transformer regime derived from the
instance's own `standards` list; IEC load-loss reference ⇒ 75 °C regardless of
rise; `no_load_loss` reference temperature ⇒ permanently `None` (IEC 60076-1
cl. 11.1: "shall not be corrected for any effect of temperature").

**Never default:** inverter `rated_ac_power` temperature — EN 50524 treats the
higher-ambient rating as an *optional* statement with its own duration, so no
reference ambient is mandated, and observed practice spans 25–50 °C. Defaulting
would recreate the exact Sungrow false conflict D-1 exists to kill. Likewise BESS
`usable_energy` basis and side, RTE (four distinct boundaries all called
"round-trip efficiency", worth 2–7 pp), and `cycle_life` EOL threshold.

**Never alias `nmot` and `noct`** — IEC 61215:2016 replaced one with the other;
same nominal conditions, different method, NMOT runs 1–2 °C lower.

**Still unmodelled:** cabling `ampacity` has no Conditions row, and an ampacity
figure is meaningless without reference ambient (NEC 310.16 assumes 30 °C, MV
tables 40 °C), conductor temperature rating and installation method. Structurally
the same error as inverter kVA without a temperature.

---

## 3. D-10 reviewer edits — resolve in the application

**Confidence: firm.** The argument is internal to the spec, not a preference.

**An Excel cell edit cannot satisfy FR-HITL-06**, which demands every HITL
decision be logged immutably with user, timestamp, before/after and rationale. A
typed-over cell carries no authenticated identity once the file has left the auth
boundary, no rationale, and no reliable before-value. Round-tripping would import
decisions that fail the audit requirement, and NFR-02 forbids repairing the log
afterwards. Option 2 is not weaker determinism — it is unauditable resolution.

Comparable tools agree: Document AI and Label Studio keep model output and human
correction as separate first-class records. The RFP tools that *do* round-trip
Excel round-trip supplier answers — source data, not a derived comparison.

Ship with three mitigations: worksheet protection plus an honest note that it is
a signpost rather than a control; a deep link per conflict row into the queue
entry (`entry_id` exists); and **`diff_workbook(returned, regenerated)`** — since
composition is pure you can regenerate exactly what someone was sent and turn
their markup into a worklist instead of losing it.

Costs, stated plainly: every resolution is a context switch out of the artifact;
no offline review; and no home for commentary on the Executive Summary tab. If
you want the last one later, add an `annotation` table now even though nothing
writes to it.

---

## 4. D-9 workbook shape — eight tabs, close the question

**Confidence: firm.** Not a genuine three-way disagreement.

The FRD's §6 table is headed *"plain-language comparison criteria"* and defers
explicitly to the TRS. The FRD's **own §7 tab table** names eight. Two knockdown
arguments beyond the vote:

1. The FRD's own acceptance criterion is "13 tabs present". Seven categories
   gives 7 + 5 = 12, so merging breaks the FRD against itself.
2. The parameter sets have **empty intersection** — cabling is conductor,
   insulation, ampacity, shielding; combiner boxes are inputs, fuses, monitoring,
   enclosure, SPD, disconnect. Zero shared keys. A merged tab would carry ~10
   `MISSING_DATA` flags on every row, destroying the meaning of one of only four
   conditional-formatting states — the reviewer-desensitisation failure D-1 names
   as the worst outcome for a HITL tool.

No code change; `ComponentCategory` and `WorkbookTab` are already correct.

---

## 5. BABA under unconfirmed funding

**Confidence: firm on behaviour and on the capture list.**

Keep `baba_status = unconfirmed`. Never `not_applicable` (that asserts a funding
fact) and never blank (collides with `MISSING_DATA`). Banner tab 13 with the
unconfirmed status, and **suppress BABA from the Executive Summary scorecard** —
a provisional ranking column changes when a funding fact arrives.

**Populate the evidence columns regardless of funding status**, because 48E
domestic content and FEOC consume the same data. On resolution: federal funding
⇒ compute from captured evidence, and a supplier missing certification is
`unconfirmed`, **never** `non_compliant` (absence of evidence is not evidence of
non-compliance — and under §1 that gap is `CRITICAL`, so it blocks until a human
decides). Privately financed ⇒ `not_applicable`, grey the section, keep the data.

**Capture now, because it is unobtainable later:** component-level cost breakdown
per manufactured product; place of final manufacture per SKU including plant;
a signed certification letter plus a *contractual obligation to re-issue
project-specific on request*; iron/steel content declaration for structural items
(100% US, a different rule from the cost test); 48E direct-cost data **and which
basis it uses**; FEOC/PFE status; and the SKU revision each attestation binds to.

The asymmetry is the whole point: this data is obtainable at RFQ while you have
leverage and close to unobtainable after award. The IRS effectively conceded it —
Notice 2024-41 created an elective safe harbour *because* manufacturers were
reluctant to disclose direct-cost data. If they withhold it from a tax filing,
they will withhold it from a post-award query.

---

## 6. Naming in a frozen contract

**Confidence: firm on both, and they resolve in opposite directions.**

Correction to the premise: the frozen contract **already says**
`reference_temperature_c`. `load_loss_ref_temp_c` appears once, in
`clarifications.md` D-6 prose. So this is contract-vs-decision-record, and the
code already agrees with the contract.

**Rule 1 — authority.** The frozen contract outranks decision records, plan prose
and docstrings. Only one artifact is declared frozen; the rest are how it got
there.

**Rule 2 — specificity is decided by whether the name is a grouping dimension.**
Where two names differ along a dimension grouping is performed on, the *specific*
name wins, because a coarse token silently merges genuinely different
measurements. Where they differ along a merely descriptive dimension, the
*generic* name wins, because a specific name on a shared model invites misuse by
every other category.

Applied: **`reference_temperature_c` wins** — it lives on `ConditionDimensions`,
which every category uses, and grouping is always within one `(category, field)`
so a transformer's 85 °C can never group with a cable's 30 °C. It is also needed
generically, since cable ampacity has the same dimension. **`sat_1mo` / `sat_3mo`
win** — `basis` *is* a grouping dimension, and a bare `sat` would silently merge
one-month and three-month site-acceptance measurements, the same class of merge
`bol`-vs-`eol` exists to prevent. Add `sat` as a third legal member meaning
"SAT, epoch not stated", never aliased to either.

Underlying defect to fix either way: `field.py`'s `basis` description restates a
partial merge of the per-family vocabularies and omits `nameplate`. It should
point at the contract's Conditions table rather than restate it — that drift is
the source of the `sat` mismatch. Tracked as #16.

**Status: both applied under #16.** `reference_temperature_c` kept; `sat` added
alongside `sat_1mo`/`sat_3mo` as a third member meaning "epoch not stated", never
aliased — which closing the vocabulary made load-bearing, since its absence would
otherwise reject any datasheet printing an undated "SAT". The `basis` description
now points at the Conditions table instead of restating it, and the contract's
Conditions table is now checked against the model in both directions, so a member
that exists in one and not the other fails the suite. (`sat` shipped for one
commit in exactly that state — in the enum, absent from the contract, while this
paragraph claimed both had been done. The reverse check exists because of it.)

**Unresolved consequence, worth a human's eye.** `sat` denotes a *partially*
unknown epoch, but it is encoded as a known value, and `comparable_with` treats
two stated-and-different dimensions as a contradiction. So:

    basis unset  vs  sat_1mo   ->  comparable
    basis = sat  vs  sat_1mo   ->  not comparable

An extractor that faithfully records what the datasheet said therefore gets
*fewer* comparisons than one that records nothing — the opposite of the incentive
the schema should create, and against the table's own "absent is unknown, not
contradictory" rule. The alternatives are both worse in a different direction:
aliasing `sat` onto a dated member is the silent merge decision 6 rejects, and
rejecting undated SAT drops the document. A third option — a `basis_precision`
marker letting a value declare itself partially stated — would fix the incentive
and is a larger change than #16's scope.

---

## 7. `basis` for BESS cycle life — a token where the contract wrote a percentage

**Confidence: firm on the encoding, open on whether it is the right reading.**

The Conditions table wrote this family as `basis` = EOL SOH threshold (60/70/80%)
— a percentage, where every other `basis` value in the table is a token. Closing
the vocabulary under #16 forced a choice, because a percentage cannot be a member
of the same enum as `stc` and `bol` without `basis` becoming `str | float`.

**Recommended: `soh_60` / `soh_70` / `soh_80` as tokens.** It keeps `basis` one
type across all eight categories, and the three thresholds are the ones the
industry actually quotes, so a numeric field would buy range it never uses. The
contract's Conditions table has been amended to match.

**Why it is still listed here.** This is an *interpretation* of a frozen
artifact, not a reading of it — the only such edit in this branch. The two ways
it could be wrong:

- **A threshold outside the three.** A supplier quoting cycle life to 65 % SOH is
  now a validation failure rather than a value. That is the correct failure
  direction (loud, not silent), but it is a failure a numeric field would not
  have had.
- **The threshold is arguably not a `basis`.** It qualifies a *count*, not a
  measurement basis; an alternative is a `soh_threshold_pct: float | None`
  dimension of its own, which would compare correctly and admit any threshold.
  That is the cleaner model and the larger change: it adds a dimension used by
  one family, where `basis` is already there.

Adopting either means editing a frozen contract, which is why it is a human's
call and not a default.

> **RATIFIED 2026-08-07** by the lead architect: the `soh_60` / `soh_70` / `soh_80`
> tokens stand as amended. The edit to the Conditions table is blessed rather than
> reverted, and this item is closed.
>
> The loud-failure direction was the deciding factor — a supplier quoting to 65 %
> SOH now fails validation instead of silently comparing against a different
> threshold, and a wrong comparison of cycle life between two BESS bids is exactly
> the class of error the conflict engine exists to surface.
>
> **The `soh_threshold_pct` alternative is not rejected on merit** — it remains the
> cleaner model, and the second objection above still stands: a threshold qualifies
> a count, not a measurement basis. It is rejected on cost and timing. Revisit it if
> a real supplier document quotes a threshold outside the three, which would be the
> evidence this decision currently lacks.
