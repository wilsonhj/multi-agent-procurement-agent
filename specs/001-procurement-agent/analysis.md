# Cross-artifact analysis

**Date:** 2026-07-28
**Artifacts checked:** [spec.md](spec.md) · [plan.md](plan.md) · [clarifications.md](clarifications.md) ·
[contracts/canonical-parameters.md](contracts/canonical-parameters.md) · the existing scaffolding
in `src/procurement_agent/` · `pyproject.toml` · `docs/requirements-traceability.md` ·
`docs/open-questions.md`

Findings are ranked by severity. **C = critical** (will produce wrong behaviour or blocks
parallel work), **H = high** (contradiction between artifacts), **M = medium** (drift or
duplication).

---

## Summary

| ID | Severity | Finding | Status |
|---|---|---|---|
| A-1 | **C** | `CanonicalField` has no `condition` — the schema cannot represent the distinction that D-1 shows causes most false conflicts | **Fixed** |
| A-2 | **C** | `pyproject.toml` depends on `langgraph`, which plan Decision 1 rejects | **Fixed** |
| A-3 | **C** | `INTERRUPTING_STAGES` contains a stage that Decision 2 removes from the pipeline | **Fixed** |
| A-4 | **H** | `numeric_conflict_tolerance` is a single global float; D-2 requires a per-field table with three kinds | **Fixed** |
| A-5 | **H** | `hitl_confidence_threshold: 0.80` is the wrong shape per D-3 | **Fixed** |
| A-6 | **H** | `openpyxl>=3.1` is unpinned; Decision 8 requires `==3.1.5` exactly | **Fixed** |
| A-7 | **H** | `chunk_overlap_ratio = 0.15` is outside the 0–10% band Decision 6 sets | **Fixed** |
| A-8 | **H** | spec.md FR-RAG-01 says tables kept whole *"where feasible"*; Decision 6 says never token-chunk | **Resolved in plan** |
| A-9 | **H** | Two research streams gave *different* determinism fixes and *different* epochs | **Resolved** |
| A-10 | **M** | `canonical-parameters.md` predates D-1 and has no `condition` column | **Fixed** |
| A-11 | **M** | `flags_for()` takes one confidence threshold; D-3 tiers τ by field criticality | **Deferred** |
| A-12 | **M** | `docs/open-questions.md` is now largely superseded by `clarifications.md` | **Fixed** |
| A-13 | **M** | `requirements-traceability.md` marks FR-WEB-04 "open"; D-2 resolves it | **Fixed** |
| A-14 | **M** | `pvlib` extra is misleading without the D-8a caveat | **Fixed** |

---

## A-1 (Critical) — The canonical field cannot express `condition`

**Artifacts:** `src/procurement_agent/schema/field.py` vs [clarifications.md D-1](clarifications.md)

`CanonicalField` carries `value`, `unit` and `verbatim_value`. It has no way to record *under
what conditions* a value holds.

The research shows this is not a nicety. For the Sungrow SG350HX, the EU datasheet, the US
datasheet and the CEC listing produce **four apparent conflicts and zero real ones** — every one
is a condition mismatch (30 °C vs 40 °C, full-power vs full MPPT window, CEC vs European
weighting). The same pattern holds for PV (STC vs NOCT) and BESS (AC vs DC side, BOL vs EOL).

Without `condition`, the conflict engine generates spurious items at a rate that trains reviewers
to ignore the queue — which defeats the tool's entire premise (C-3).

**Note this contradicts the TRS**, which fixes the field object at eight keys in section 5. The
addition is justified: the TRS's own section 7 lists parameters like
*"rated AC kVA @temp"* and *"STC/NMOT ratings"* that cannot be represented without it. The eight
TRS keys are preserved; `condition` is a ninth.

**Fixed** — `condition` added to `CanonicalField`, and a `test_canonical_field_has_the_eight_spec_keys`
test updated to assert nine with a comment explaining the deviation.

---

## A-2 (Critical) — Dependency contradicts the orchestration decision

**Artifacts:** `pyproject.toml` vs [plan.md Decision 1](plan.md)

The `agent` extra declares `langgraph>=0.2`. Decision 1 rejects LangGraph as the pipeline
orchestrator on the grounds that NFR-02 and FR-OUT-06 already force canonical state into
application tables, making a checkpointer a second copy of state we already own.

Leaving the dependency in place would have a team reach for it.

**Fixed** — `agent` extra renamed `extract`, `langgraph` removed, `instructor` + `openai` added
for the vLLM `json_schema` path per Decision 7.

---

## A-3 (Critical) — Pipeline contains a stage the design removes

**Artifacts:** `src/procurement_agent/orchestrator/__init__.py` vs [plan.md Decision 2](plan.md)

`Stage.AWAIT_HUMAN_RESOLUTION` exists and sits in `INTERRUPTING_STAGES`. Decision 2 makes the
human gate a **policy check at compose time**, not a pipeline pause — because "defer" is a
mandated resolution action (FR-HITL-04) and a blocking workflow has no coherent semantics for
indefinite deferral.

**Fixed** — the stage is removed and `INTERRUPTING_STAGES` is replaced by a documented
`compose_gate` concept.

---

## A-4 (High) — Global tolerance float versus per-field table

**Artifacts:** `src/procurement_agent/config.py` vs [clarifications.md D-2](clarifications.md)

`numeric_conflict_tolerance: 0.02` applies one relative band to every field. Measured data shows
this is wrong in both directions: a ±2% band on a 650 W nameplate is ±13 W, which **merges three
adjacent 5 W SKUs**; the same band on a −0.29 %/°C temperature coefficient is ±0.006, **below
datasheet precision**.

**Fixed** — replaced with a reference to the per-field table, and the placeholder float removed
so nobody uses it by accident.

---

## A-5 (High) — Confidence threshold is the wrong shape

**Artifacts:** `src/procurement_agent/config.py` vs [clarifications.md D-3](clarifications.md)

`hitl_confidence_threshold: 0.80` presumes a single calibrated score exists on day one. It does
not, and a hardcoded float is not derived from anything. D-3 specifies a target precision on
auto-accepted fields with τ read off a risk–coverage curve, tiered by field criticality.

**Fixed** — replaced with `target_precision_auto_accepted: 0.99` and
`review_budget_fraction: 0.20`, both of which are *targets* the calibration fits to.

---

## A-6 (High) — `openpyxl` must be pinned exactly

**Artifacts:** `pyproject.toml` vs [plan.md Decision 8c](plan.md)

`docProps/app.xml` literally embeds the string `Openpyxl 3.1.5`. A patch bump silently changes
the output hash and breaks every historical AC-7 assertion with zero data change. `>=3.1` permits
exactly that.

**Fixed** — pinned to `==3.1.5`.

---

## A-7 (High) — Chunk overlap outside the researched band

**Artifacts:** `src/procurement_agent/config.py` vs [plan.md Decision 6](plan.md)

`chunk_overlap_ratio = 0.15` sits inside the TRS's 10–20% guidance but outside Decision 6's
revised 0–10%. Systematic analysis found overlap gave no measurable benefit; Docling supplies
real section boundaries, which is most of what overlap compensated for.

**Fixed** — default 0.05, `le` bound tightened to 0.10 so the out-of-band value cannot be set.

---

## A-8 (High) — "Tables kept whole where feasible" is too weak

**Artifacts:** [spec.md](spec.md) FR-RAG-01 vs [plan.md](plan.md) Decision 6

spec.md carries the TRS wording verbatim. Decision 6 hardens it: tables are **never**
token-chunked, and each is indexed three ways (`table_full`, `table_row`, `table_summary`).

**Resolved, deliberately not "fixed".** spec.md states the *requirement* as the source documents
express it; plan.md states *how it is met*, and may be stricter. Recording the escalation here
rather than editing the requirement keeps spec.md faithful to the FRD/TRS. Flagged so no
implementer reads "where feasible" as permission.

---

## A-9 (High) — Two research streams disagreed on the determinism fix

**Artifacts:** the Excel research stream vs the orchestration research stream

Both independently found the same root cause — `save_workbook()` re-stamps
`properties.modified = now()` unconditionally *after* the caller sets it — and both verified
byte-identical output. But they proposed **different fixes** and **different epochs**:

| | Excel stream | Orchestration stream |
|---|---|---|
| Fix | Post-save regex rewrite of `docProps/core.xml` | Drive `ExcelWriter` directly, bypassing `save_workbook` |
| Epoch | `(1980, 1, 1, 0, 0, 0)` | `1980-01-01 **12:00**` |
| Entry order | Preserve `namelist()` order | Sort, then force `[Content_Types].xml` first |

**Resolution — take the orchestration stream on all three**, recorded in plan.md Decision 8c:

- **`ExcelWriter` direct** over regex-rewriting XML. Both work, but parsing generated XML with a
  regex to undo a library's own write is the more fragile of two verified options.
- **12:00, not midnight.** The orchestration stream gave a reason the Excel stream did not: DOS
  timestamps are *local*, so midnight underflows the 1980 floor in negative UTC offsets. This is
  also what `strip-nondeterminism` does, which is independent corroboration.
- **Entry ordering** is a genuine toss-up; sorted-with-`[Content_Types]`-first matches the OPC
  preference, so it is marginally safer against strict readers.

This disagreement is worth recording rather than silently picking a winner — if the chosen
approach fails in desktop Excel, the other is a verified fallback.

---

## A-10 (Medium) — Parameter contract predates the `condition` decision

**Artifacts:** [contracts/canonical-parameters.md](contracts/canonical-parameters.md) vs D-1

The contract was frozen before D-1 landed and specifies only key/type/unit. Several of its own
entries already imply a condition — `rated_ac_power_temp`, `stc_rating` vs `nmot_rating`,
`usable_energy_per_container` vs `nameplate_energy_per_container`.

**Fixed** — a `condition` column and a section explaining which parameter families require one.
Note this makes the earlier ad-hoc `rated_ac_power_temp` field redundant with the general
mechanism; it is retained as a convenience but documented as derivable.

---

## A-11 (Medium) — Output flagging assumes one global threshold

**Artifacts:** `src/procurement_agent/services/output/flags_for()` vs D-3

`flags_for(field, confidence_threshold=...)` takes a single float. D-3 tiers τ by field
criticality, so the low-confidence flag should be computed against the *field's own* threshold.

**Deferred, not fixed.** The signature change is cheap, but the tiering policy it depends on is
itself an output of the calibration work in WP-B. Changing the signature now would freeze a
guess. Tracked as a task dependency instead: WP-G takes a `threshold_for(field_name)` callable
once WP-B defines it.

---

## A-12 (Medium) — `docs/open-questions.md` is now superseded

Written during scaffolding, before any research. Eight of its twelve items are resolved in
`clarifications.md`; leaving both invites a team to work from the stale one.

**Fixed** — reduced to a pointer at `clarifications.md`, retaining only the items that remain
genuinely open.

---

## A-13 (Medium) — Traceability marks resolved requirements as open

`docs/requirements-traceability.md` lists FR-WEB-04 as **open** and FR-OUT-05 as **open**. D-2
resolves the first; the second is now covered by the certification fields in the parameter
contract.

**Fixed** — statuses updated, with links to the deciding clarification.

---

## A-14 (Medium) — The `pvlib` extra is a trap without its caveat

`solar = ["pvlib>=0.11"]` reads as an endorsement. D-8a measured that pvlib's bundled CEC library
is frozen at March 2019 and contains **zero modules ≥600 W**, while this project's modules are
600–740 W. `retrieve_sam('CECMod')` would return a library with not one candidate product, and
pvlib's own name normaliser is currently broken against SAM's curly-brace format.

**Fixed** — comment added at the dependency pointing at D-8a.

---

## Consistency checks that passed

- All 26 FR IDs in spec.md match the TRS analysis; none invented, none dropped.
- All 13 `WorkbookTab` members match FR-OUT-02, in order, and the first eight match
  `ComponentCategory` (asserted by test).
- The five `ConflictClass` and five `ResolutionAction` members match FR-HITL-01 and FR-HITL-04
  exactly.
- The eight `DocumentType` members match FR-ING-06.
- The six `ports/` Protocols match NFR-04's six named swap points exactly.
- `SourceTier` has exactly the two tiers the source-of-record rule requires.
- AC-7 and AC-8, added in spec.md beyond the TRS's six, each trace to an existing requirement
  (FR-OUT-06 and NFR-03 respectively) rather than inventing scope.
- No requirement in spec.md lacks a home in either the code, the plan, or tasks.md.

## Coverage gaps that are real but intentional

- **AC-1, AC-5, AC-6 have no tests.** They need the ingestion path and a labelled corpus, which
  is WP-B and D-11 work. Recorded as open in the traceability doc rather than papered over.
- **FR-ING-02 and FR-ING-05 have no home in code yet** beyond `ParserPort`. Correct at
  scaffolding stage; assigned to WP-A.
- **NFR-06 and NFR-07 have no verification.** Both are scale/latency properties that need a
  running system. Assigned to WP-I.
