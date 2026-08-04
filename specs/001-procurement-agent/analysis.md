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

---

# Round 2 — findings from open issues #1–#9 (2026-07-28)

Nine issues were reviewed against these artifacts. Most were already answered by the spec; four
found real defects, **three of them regressions introduced by round 1**.

| ID | Severity | Finding | Status |
|---|---|---|---|
| A-15 | **C** | README still documented the interrupt architecture and a `--extra agent` that no longer exists — while A-2/A-3 above claimed "Fixed" | **Fixed** |
| A-16 | **H** | `requirements-traceability.md` cited three symbols deleted in round 1, and marked eight rows `enforced` with no test covering the cited artifact | **Fixed** |
| A-17 | **H** | PV power tolerance modelled as `(min, max)` in watts cannot represent a relative declared band | **Fixed** |
| A-18 | **M** | `ports/__init__.py` documented an `adapters/` package that does not exist | **Fixed** |
| A-19 | **M** | No canonical row ordering across component instances; `ComponentInstance` had no ID | **Fixed** |
| A-20 | **M** | Sync vs async on the six Protocols was never decided | **Fixed** — plan Decision 10 |
| A-21 | **M** | No concurrency limits anywhere in config | **Fixed** |
| A-22 | **M** | C8 lacked the append-only claim invariant | **Fixed** |
| A-23 | **H** | **FR-RAG-02's ANN mandate was edited out of spec.md rather than registered.** The TRS says every chunk *shall* be stored in an ANN vector index (HNSW/IVF, cosine); plan Decision 3a reverses it. The decision is well-supported — pgvector's filtered search was measured silently under-returning on a filtered top-k, and an HNSW index cost more than the table — but a mandatory `shall` was paraphrased away instead of recorded here. | **Fixed** — TRS wording restored in spec.md, reversal marked inline |
| A-24 | **H** | **FR-RAG-03's BM25 clause was generalised to "keyword search".** Reversed by plan Decision 3b (no permissively licensed true-BM25 for PostgreSQL), also unregistered. | **Fixed** — TRS wording restored, reversal marked inline. The inline note's *description of the replacement* was itself wrong; that is a separate finding, [A-40](#a-40-low--a-24s-inline-note-named-the-wrong-replacement). |
| A-25 | **M** | **NFR-03's mechanism clause was dropped.** The TRS says access control *must* be enforced at retrieval time *via metadata filtering*; plan Decision 3c substitutes `FORCE ROW LEVEL SECURITY`. Defensible, but an unflagged change to a `must`. | **Fixed** — mechanism restored, substitution marked inline |
| A-26 | **H** | **AC-6 was weakened on the exact point the TRS calls its key correction.** "TRD against the correct IEEE 2800 voltage-class limit" became "harmonic distortion against the correct voltage-class limit", and spec.md mentioned TRD, TDD, IEEE 2800 and IEEE 519 zero times — while the frozen contract warns at length that getting TRD-vs-TDD wrong "produces a compliance matrix that passes suppliers it should fail", and tasks.md still said "AC-6 TRD". The one normative document generalised the distinction away. | **Fixed** |
| A-27 | **M** | **The coverage audit certified itself with the wrong count.** "All 26 FR IDs in spec.md match the TRS analysis" — spec.md contains **32** unique FR IDs (FR-ING-01..10, FR-RAG-01..05, FR-WEB-01..05, FR-HITL-01..06, FR-OUT-01..06); 26 is the count with FR-OUT-01..06 omitted. A full ID sweep found none missing and none invented, so only the arithmetic was wrong — but the claim that closes the audit was false, which left the audit unverified. | **Fixed** |

## A-15 (Critical) — the analysis claimed a fix that had not fully landed

The most serious finding of this round, because it is a defect *in this document*. A-2 and A-3
were marked **Fixed** on the strength of edits to `pyproject.toml` and `orchestrator/__init__.py`.
`README.md` was not checked, and still contained:

- `--extra agent` (LangGraph, Instructor) — an extra that no longer exists, so the documented
  install command would fail
- "Pipeline stages and interrupt policy" in the layout section
- a pipeline diagram showing `[interrupt: human approval]`

**Lesson worth recording:** "Fixed" was asserted from the edits made rather than from a search for
the symbol across the repository. A grep for the removed names would have caught all three.

## A-16 (High) — traceability overstated test coverage

Eleven rows corrected. Three cited deleted symbols — a round-1 regression: symbols were removed
without updating the document that referenced them. Eight claimed `enforced` while no test touched
the cited artifact; **no test imports `procurement_agent.ports` at all**, yet NFR-04 was marked
`enforced` with `ports/` as its entire citation.

A `partial` status was added, because several rows were genuinely half-covered and forcing them to
`enforced` or `declared` lost information.

## A-17 (High) — declared bands are not conflict tolerances

Verified from primary datasheet text that three power-tolerance conventions are in current use:
`0~+5 W` (Trina), `0~+10 W` (Canadian Solar, three sheets), and `0~+3%` (Jinko).

D-2's existing rebuttal — that Trina's `±3%` is a *measuring* tolerance rather than a label band —
is correct for Trina but **does not dispose of Jinko**, whose `0~+3%` sits in the electrical-data
table as the label tolerance itself. The rebuttal answered a coincidentally-equal number from a
different manufacturer and a different row.

Storing a relative band in watts is circular precisely where it matters: Pmax is the field most
likely to be disputed, and resolving a Pmax conflict would need a tolerance whose value depends on
which Pmax candidate was already chosen. Contract changed to a `DeclaredBand` with an explicit
`kind`.

## A-19 (Medium) — ordering, and why the obvious key is wrong

AC-7 needs a total order over component instances; "sorted-key JSON" orders keys *within* objects
only. The natural key `(category, manufacturer, model, field)` is **not unique** — 36 duplicated
`(Manufacturer, Model Number)` pairs and 157 model numbers appearing under more than one
manufacturer. A `surrogate_id` tie-break is required, placed **last** so row order stays readable.

## Relationship to PR #11

A second PR (`docs/agent-topology.md`, `docs/defaults.md`) was opened independently, 9 seconds
after this one, from the same parent commit. Neither references the other. It **merges cleanly at
the git level** — verified in an isolated clone, no conflict markers — but **merging both unedited
produces a self-contradicting repository.**

**It does not contradict our reading of the source documents.** It quotes our
`services/__init__.py` conclusion — that the TRS names services, not agents, with no roster or
message protocol — and calls it accurate. It then asks a different question: given that, *should*
there be an agent topology? Its answer is notably anti-inflationary: a genuine team of
differentiated agents earns its keep in exactly two places (the parser router, and the
compliance/tax tabs, which have disjoint authorities and no shared state). Everywhere else,
*"'agent' would be a persona wrapped around a function call."*

**Where it conflicts, and who is better evidenced:**

| Topic | PR #11 | This PR | Assessment |
|---|---|---|---|
| Orchestrator | LangGraph + Postgres checkpointer | Postgres state machine | **Ours.** PR #11 states LangGraph as a premise inherited from the scaffolding and never argues for it — its own confidence note covers the throughput figures and a config-key fact, not the choice. It offers no counter to Decision 1's two load-bearing arguments. |
| Vector index | HNSW with tuned parameters | No ANN index | **Ours.** Measured on a live container with the query plan reproduced. PR #11 never considers filtered-search recall or the RLS interaction. |
| Chunk overlap | 15% "(unchanged)" | 0–10% | **Ours**, though ours is self-marked medium confidence. Mechanically, 0.15 now raises a Pydantic validation error — merging both ships a doc unimplementable against code in the same commit. |
| Traceability statuses | Downgrades five rows, adds `partial` | Left them `enforced` | **Theirs, conceded without argument.** Verified: no test touches the cited symbols. Adopted as A-16. |
| Identity resolution | No non-exact merge at all | Scored auto-merge at ≥0.90 | **Split.** Ours is measurement-backed and requires electrical corroboration, so it is not fuzzy string matching — but their conservatism argument ("a wrong merge either fabricates a conflict or hides one, and neither is visible afterwards") is real and our D-4 does not rebut it. |

**Adopted from PR #11 this round:** the propose/commit invariant (C8), `declared_tolerance`
(A-17), the canonical sort key (A-19), the traceability corrections (A-16), the
`ports/__init__.py` docstring fix (A-18), union-not-vote (E.3a), OIDC subject claim (D-12a),
technology-specific bifaciality bands, and the `ef_construction >= 2*m` hard-error note.

**Also adopted: a licence-verification warning.** PR #11 demonstrated that the widely repeated
"CC BY-NC 4.0" label for Jina v4 is wrong — it is the Qwen Research License. Our v5 entry comes
from the same class of secondary source. The rejection is unaffected; the licence *name* is what
would reach procurement paperwork.

**Recommended sequence:** merge this PR first (it changes code, config and contracts), rebase
PR #11's docs onto it, keep `agent-topology.md` with three retargeting edits, and do **not** land
`defaults.md` as a peer of `clarifications.md` — two authoritative defaults documents is the
failure mode. Fold its non-overlapping parts in instead.

## Issues that needed no change

- **#1** (per-field tolerance) — already D-2, which argues from a downloaded CEC export rather
  than search snippets. Its proposed 0.5% relative on nameplate is *weaker* than D-2's ±1 W.
- **#3** (fuse deterministic signals) — already plan Decision 7, reached independently from the
  same evidence, with identical AUC figures. One real gap closed: a Tier A never-auto-accept class.
- **#4** (LangGraph `max_concurrency`) — moot under Decision 1, but the technical claim was
  verified and is worth knowing: it is a top-level `RunnableConfig` key, and nesting it under
  `configurable` disables the cap silently because `ensure_config()` sweeps unrecognised top-level
  keys *into* `configurable`. The hazard is langchain-core-wide, not LangGraph-specific.
- **#8** (propose/commit split) — core claim correct, prescribed remedy was LangGraph-shaped.
  Recorded as the C8 append-only invariant instead.
- **#9** (identity resolution) — already D-4/D-4a, which are strictly stronger. Its blocking claim
  was wrong: AC-7 is scoped to an *unchanged store*, and compose never re-runs the matcher.

---

---

# Round 3 — findings from the Phase 0 substrate review (2026-08-04)

The C1/C4 DDL, the severity lookup and the `CanonicalField` update paths were reviewed against a
**live PostgreSQL 16 cluster with pgvector 0.6.0** — the first time anything in `sql/` had been
executed rather than parsed. Every finding below was reproduced before being fixed and
re-reproduced after; the commands and results are in `sql/README.md`.

> **Renumbered 2026-08-04, A-23..A-30 → A-28..A-35.** This block originally restarted at A-23,
> which round 2 had already used, so five IDs each named two different findings and every citation
> of one resolved to the wrong finding half the time. Round 2 is the older block and is cited from
> outside this file — `spec.md`, `docs/architecture.md` and `services/{indexing,retrieval}`
> all cite A-23/A-24/A-25 for the FR-RAG-02, FR-RAG-03 and NFR-03 reversals — so it keeps its
> numbers and this block moved. A repository-wide grep found **no** in-tree reference to a Round 3
> ID, so nothing else needed editing; a citation made outside the tree before this date should add
> five. Registered below as [A-36](#a-36-high--five-finding-ids-each-named-two-findings).

| ID | Severity | Finding | Status |
|---|---|---|---|
| A-28 | **M** | `requirements-traceability.md` had no AC-7 or AC-8 row while `spec.md` defines eight acceptance criteria | **Fixed** — rows supplied on `agent/developer-documentation` (PR #22); see the note below |
| A-29 | **H** | RLS on `document`/`chunk` only: `claim.value`, `audit.event.payload`, `conflict.explanation`, `resolution.value_before`/`value_after` and `job.payload` all returned restricted content to a role that could not see the document | **Fixed** |
| A-30 | **H** | `INSERT ... ON CONFLICT`/`RETURNING` failed for `access_restricted = true` and succeeded for `false` — the schema penalised the safe action | **Fixed** — separate write role |
| A-31 | **M** | `00_roles.sql` never re-asserted role attributes, so a `procurement_app` carrying `SUPERUSER BYPASSRLS` survived a clean re-run of the file that exists to prevent exactly that | **Fixed** |
| A-32 | **M** | `08_job.sql` granted full-table `UPDATE`, including `idempotency_key` — the whole of I.2's at-least-once guarantee | **Fixed** — column-level grant |
| A-33 | **H** | `_gross_divergence` could not fire for 105 of 124 contract keys, including 22 of 24 Tier A and all 12 CRITICAL fields, while its docstring named the decimal-comma trap as its purpose | **Fixed** — order-of-magnitude fallback |
| A-34 | **M** | Five further routes reached the forbidden RESOLVED-with-no-`Resolution` state, and `evolve()` silently replaced a recorded `Resolution` | **Fixed**, except one undefendable route — see below |
| A-35 | **M** | 81 of 120 one-step mutants of the `CRITICALITY` table survived the suite: membership was checked both ways, values were pinned for ~36 keys | **Fixed** — all 124 pinned |
| A-40 | **L** | A-24 restored the FR-RAG-03 reversal but its inline note named the *replacement* wrongly — "the embedding model's sparse output", a Decision 5 reserve, where Decision 3b chose Postgres `tsvector`/`pg_trgm` fused with RRF (k=60). The `⚠️` note shipped as the register's own closed remedy | **Fixed** — `spec.md` note corrected against Decision 3b; A-24's row kept intact |

## A-28 (Medium) — the traceability table stopped at AC-6

`spec.md:194-197` defines AC-7 (byte-identical regeneration) and AC-8 (an uncleared user cannot
influence a retrieved result) as additions to the TRS's six, and `tasks.md` assigns owners for
both. `requirements-traceability.md`'s acceptance-criteria table listed AC-1 through AC-6 and
stopped, so the two criteria that exist *because* they "silently rot without a test" were the two
with no row saying whether a test existed.

The document's own audit note is the reason this matters more than a missing line: it promises a
closed vocabulary a reader can trust, where `enforced` means a regression test protects the
requirement. A criterion with no row at all is outside that vocabulary entirely — it reads as
though the table is complete when it is not.

**Fixed** — the rows landed on `agent/developer-documentation` (PR #22) while this branch was in
review, with statuses `partial` (AC-7: `test_workbook_determinism.py` covers `normalize_archive`,
but `write_workbook` raises `NotImplementedError` so no complete workbook is regenerated) and
`declared` (AC-8: `VectorStorePort.search(allowed_document_ids=...)` declares the parameter and no
adapter implements it). Both were checked against the code and left as written rather than
duplicated here, so the two branches merge without a conflict.

**AC-8's row needs one revision once both branches land**, and it is recorded here rather than
edited into a file another branch owns: this branch adds row-level security to all seven tables
that hold document content, with `FORCE ROW LEVEL SECURITY` and a live-verified confidentiality
derivation, plus `tests/test_sql_schema.py`. The *Where* column citing only `ports` is no longer
the whole story, and `declared` understates it. It is not `enforced` either — the enforcement is
DDL that CI does not execute.

**Closed 2026-08-04, and the last sentence above did not survive.** Both branches landed, and the
row is now `partial` with the RLS citation written out. But the reason given here for withholding
`enforced` — "DDL that CI does not execute" — expired when #25 added the `sql` job, which runs
`tests/test_sql_behaviour.py` against a pgvector service container and fails if the suite skips.
The conclusion stands on a different ground, recorded in the row itself: there is no retrieval
path, so nothing yet does the thing AC-8 constrains. Worth leaving both sentences visible rather
than editing the first away — a register entry whose *reasoning* silently changes underneath its
*verdict* is how A-15 happened.

## A-34 (Medium) — the forbidden state had five more doors than the count said

`requirements-traceability.md`'s FR-HITL-06 row said "two routes remain open". Measured, seven
did: `model_construct`, an instance `__dict__` write, `object.__setattr__`, `deepcopy` and
`pickle` round trips of either, and — separately — `evolve()` and plain assignment each replacing
a recorded `Resolution` with a different one, silently, because the resulting state is legal and
no validator can see a transition.

Six are closed at the point they occur. The route that remains is writing the instance `__dict__`
directly; `object.__setattr__` is the same write in a different spelling, not a second route, so
the honest count is one. No Python object can defend against it, and
`test_the_dict_write_route_is_documented_as_open` asserts it as open on purpose, so the gap is a
recorded fact rather than an oversight.

---

---

# Round 4 — the traceability audit after CI landed (2026-08-04)

`docs/requirements-traceability.md` was re-read row by row, opening each cited artifact and each
cited test. Prompted by #25, which made the `sql/` guarantees executable, and by the three service
modules (`claims`, `identity`, `confidence`) plus `conflict_hitl/severity.py` landing before it.

**The table holds 48 requirement rows and 8 acceptance-criterion rows**, counted from the file:
8 FRD + 10 FR-ING + 5 FR-RAG + 5 FR-WEB + 6 FR-HITL + 6 FR-OUT + 8 NFR. The brief for this audit
said 49, and A-27 is the standing reminder that a count asserted rather than computed is how an
audit certifies itself wrong. No ID is missing — the 48 reconcile against spec.md's 32 TRS FR IDs
plus the 8 FRD requirements and 8 NFRs.

| ID | Severity | Finding | Status |
|---|---|---|---|
| A-36 | **H** | **Five finding IDs each named two different findings.** Round 3 restarted numbering at A-23, which round 2 had already used, so A-23..A-27 were ambiguous — and this file is the document the contributor docs tell people to cite | **Fixed** — Round 3 renumbered A-28..A-35 |
| A-37 | **H** | **The traceability table understated merged work — A-16 with the sign reversed.** Ten rows sat below what the code and tests support, including NFR-02 reading "store not yet built" beside a nine-file schema whose tripwires run against a live server on every pull request | **Fixed** |
| A-38 | **M** | The table had no rule for weighing a live-database test against a structural one, and the two are not interchangeable: two of four reintroduced defects were invisible to `test_sql_schema.py` | **Fixed** — rule stated once, applied uniformly |
| A-39 | **M** | **A-31's fix covers role *attributes* and not role *memberships*.** `GRANT procurement_ingest TO procurement_app` survives a clean re-run of `00_roles.sql`, defeating the Decision 9 boundary, and no test names the cause | **Fixed** |

## A-36 (High) — five finding IDs each named two findings

The defect is in this file, which is what makes it high rather than tidy. `CONTRIBUTING.md` and
`docs/architecture.md` both direct contributors here and tell them to cite a register ID when a
plan decision reverses a normative requirement, and three of the five collided IDs are exactly
those citations: A-23 (FR-RAG-02's ANN mandate), A-24 (FR-RAG-03's BM25 clause), A-25 (NFR-03's
mechanism). A reader following one of those from `spec.md` had even odds of landing on a
PostgreSQL finding about role attributes.

Renumbering the *second* block is the resolution rather than a prefix scheme (`R3-1`, say),
because the collision is only in this file: a repository-wide grep found every in-tree citation
pointing at a round-2 ID, so moving round 3 costs nothing outside and a second ID format would be
a permanent tax on every future reader. Both prose sections below the round 3 table moved with
their entries.

**Lesson, and it is A-15's again in a new place:** the count was asserted from the block being
written rather than from a scan of the file it was being appended to. `grep -o '^| A-[0-9]*' |
sort | uniq -d` takes a second and is now the check.

## A-37 (High) — the register's own remedy, applied in the wrong direction only

A-16 established that `enforced` must mean a test exists, and the rows that overclaimed were
corrected downward. The vocabulary held. What did not hold is the other direction: between that
audit and this one, `sql/` gained row-level security on seven tables, an append-only
claim/resolution/audit trio with statement-level TRUNCATE tripwires, a separate ingest role, and —
in #25 — a CI job that executes all of it against a pgvector container and fails if the suite
skips rather than runs. `services/claims`, `services/confidence` and `services/identity` landed
alongside (1,458 lines, plus 565 in `conflict_hitl/severity.py`), each with a dedicated test file.
Ten rows should have risen and none did.

The asymmetry is worth naming because it is predictable: a demotion is prompted by an audit, while
a promotion is prompted by nothing at all — the author of a merged PR is not reading a traceability
table. Both directions cost the same thing, which is a reader's willingness to believe the column.
NFR-02's "store not yet built", sitting beside `sql/07_audit_event.sql` and four live tests that
walk its hash chain, is not a smaller error than an unearned `enforced`; it is the same error.

**Not raised, and deliberately.** FR-RAG-02 and FR-RAG-03 gained a genuine storage home in
`sql/03_chunk.sql` and stayed `declared`, because the only live test touching that table asserts
Decision 3a's *reversal* of FR-RAG-02 rather than the requirement. Counting it would be A-16's
defect reached by a new route.

## A-38 (Medium) — a structural test and a behavioural one are not the same evidence

`test_sql_schema.py` asserts DDL text; `test_sql_behaviour.py` runs the attack. Both are worth
keeping and the traceability table needs to cite them differently, which it had no rule for. The
difference was measured rather than assumed, by reintroducing four closed defects one at a time:

| defect reintroduced | `test_sql_schema.py` | `test_sql_behaviour.py` |
|---|---|---|
| `UNIQUE (content_hash)` dropped from `02_document.sql` | **green** | red |
| `claim`'s confidentiality policy widened to `USING (true)` | red | red |
| `resolution`'s statement-level TRUNCATE tripwire deleted | red | red |
| `GRANT procurement_ingest TO procurement_app` added | **green** | red |

Two of four are invisible to the structural suite — including the privilege-separation boundary
that Decision 9 rests on, where nothing in the DDL text changes at all and the grant is simply
added. So a `sql/` row cites the behavioural test where one exists and says so where only the
structural one does.

The second half of the rule is what a live test is *not* worth. It skips silently without
`PROCUREMENT_TEST_DSN` and runs only in CI's `sql` job, and — more importantly — it proves the
schema behaves, not that any Python path uses the schema. Every row in this position still has an
unimplemented application half, so each is `partial` and names which half is live-tested. `AC-5`
is the clearest case: the store refuses a duplicate `content_hash` under test, and
`services/ingestion.ingest` still raises `NotImplementedError`, so nothing re-ingests.

## A-39 (Medium) — A-31 normalises role attributes, not role memberships

> **Fixed 2026-08-04.** `00_roles.sql` now revokes every membership among the
> four project roles on each run, beside the `ALTER ROLE`s that normalise
> attributes, and `tests/test_sql_behaviour.py::test_no_project_role_is_a_member_of_another`
> asserts `pg_auth_members` is empty for them — naming the cause where
> `test_the_app_role_cannot_escalate_to_the_ingest_role` names the consequence.
>
> Verified by the discriminating case rather than by a plain revert: with a
> stray `GRANT procurement_ingest TO procurement_app` already in the cluster,
> the suite is **24 passed** with the revoke loop and **9 failed** without it.
> A plain revert cannot show this — the session fixture rebuilds the schema from
> scratch, so there is no pre-existing grant to revoke, which is exactly the
> state the fix exists for.

Found by accident, which is the only reason it is here: the fourth mutation above
(`GRANT procurement_ingest TO procurement_app`) was reverted in the *file* and the suite stayed
red, because the grant had been made in the *cluster* and nothing takes it back.

Reproduced deliberately afterwards, against PostgreSQL 16:

```
GRANT procurement_ingest TO procurement_app;   -- the stray grant
psql -f sql/00_roles.sql                       -- a clean re-run of the unmodified file
SELECT ... FROM pg_auth_members ...            -- procurement_app IS MEMBER OF procurement_ingest
```

The membership survives. Every attribute assertion passes at the same time — `rolsuper`,
`rolbypassrls`, `rolcanlogin` are all correct — because A-31 fixed exactly those, with
unconditional top-level `ALTER ROLE ... NOSUPERUSER NOBYPASSRLS ...` statements and a `pg_roles`
assertion block. `ALTER ROLE` does not touch `pg_auth_members`, and nothing else in the file does
either.

**This is A-31's own finding in the one form its fix does not reach**, stated in A-31's words: a
pre-existing over-privileged `procurement_app` survives a clean re-run of the file that exists to
prevent exactly that. The consequence is Decision 9's boundary: with the membership in place
`procurement_app` can `SET ROLE procurement_ingest` and read every restricted row through the
ingest read-back policy that `test_the_write_role_can_read_back_what_it_writes` requires. Eight of
the 23 live tests go red, so the *consequence* is caught loudly — but
`test_owner_roles_cannot_log_in_and_the_app_is_unprivileged` reads `rolsuper` and `rolbypassrls`
and not `pg_auth_members`, so nothing names the *cause*, and a reader sees eight confidentiality
failures rather than one role grant.

**Not a defect in the committed DDL**, which never issues that grant — it is a hardening gap, and
the same one A-31 judged worth closing. The remedy is symmetric with A-31's: an unconditional
`REVOKE` of the memberships the design forbids, plus a `pg_auth_members` clause in the existing
assertion block so a bootstrap identity that cannot revoke fails loudly instead of silently. A
matching assertion in `test_owner_roles_cannot_log_in_and_the_app_is_unprivileged` would name the
cause.

**Left open deliberately.** The fix is in `sql/00_roles.sql` and `tests/test_sql_behaviour.py`,
neither of which this branch owns. Registering it is the whole point of the register: A-15's
lesson was that a fix asserted from the edits made rather than from a search across the repository
is not a fix, and the converse holds too — a finding made in a file you cannot edit is still a
finding, and dropping it because it is inconvenient to fix is how it stays lost.

## A-40 (Low) — A-24's inline note named the wrong replacement

A-24 closed as **Fixed**: the FR-RAG-03 reversal was registered and the TRS `shall` was marked
overridden inline rather than paraphrased away. That much held. What its inline note got wrong is
the *replacement* — it read "lexical matching from the embedding model's sparse output, not BM25",
and Decision 3b chose no such thing. The plan's lexical leg is Postgres `tsvector`/GIN full-text
plus `pg_trgm` trigram (plan Decision 3b). *(This sentence read "…fused with Reciprocal Rank Fusion
(k=60)" until [A-43](#a-43-high--a-decision-no-declared-interface-could-reach) removed the fusion
stage. Amended here rather than left standing, because it is written in the present tense about the
plan's current content — see A-47, which counts this line as a carrier it had itself missed.)* The
embedding
model's sparse output is a *Decision 5 contingency* — swap Qwen3-Embedding-4B for `bge-m3` if
Postgres full-text proves weak on part numbers — held in reserve and not adopted.

This is filed as its own entry, not as an amendment to A-24, for the reason A-37 is its own entry:
a remedy that shipped and later proved defective is a new finding, and rewriting the closed row
would erase that A-24's `⚠️` note was wrong for the interval between the two. The register is an
audit trail; corrections append.

The three code docstrings that had repeated one or other stale position — `ports/__init__.py`,
`services/retrieval/__init__.py`, `services/indexing/__init__.py` — were already corrected against
Decision 3b. The `spec.md` note was the last carrier, and this change corrects it; `docs/
architecture.md`'s "inaccuracy" table, which had flagged the note and pointed at it as what
remained, now records the note as corrected and points here.

---

---

# Round 5 — four parallel reviews of the unwritten half (2026-08-04)

Six findings from four reviews run in parallel, each against a different seam, and the batch has a
shape worth naming: **every one is against a component no caller has exercised yet.** The retrieval
services raise `NotImplementedError`, `orchestrator.run` raises `NotImplementedError`,
`write_workbook` raises `NotImplementedError`, and C4's Python half does not exist, so nothing has
emitted an audit event. That is why these cost a signature line, a constraint clause, a docstring or
a paragraph here and would cost a migration, a re-embed of the corpus or a breaking interface change
once the first real caller exists.

Two qualifications, since the sentence above is tidier than the facts. A-41 is a **live defect in
shipped DDL** — the schema rejects claims C2 and D-1 exist to store, today, and only the absence of
an ingest path keeps it from being hit. And A-45, A-46 and A-47 are findings in *prose* —
`plan.md`, `spec.md`, `docs/` — rather than in code or DDL; they are cheap now for the different
reason that no implementer has built against the wrong text yet.

The four reviews were scoped to disjoint file sets and given pre-assigned ID ranges, because the
register has been renumbered once already (A-23…A-27, Round 3) after parallel work collided in it.
Three of the four still opened a block titled *Round 5* — the fourth was a behaviour-preserving
cleanup and filed no finding — and those three blocks are consolidated here, in ID order, rather
than left as three rounds bearing one number.

A seventh finding, **A-47**, was made at the integration of these four rather than inside any of
them: it is the `spec.md` edit A-43 identified and correctly refused to make from a branch that did
not own the file.

| ID | Severity | Finding | Status |
|---|---|---|---|
| A-41 | **H** | **`claim_natural_key` omitted `condition`, so the schema rejected the multi-condition claims C2/D-1 exist to store.** `FieldClaim.claim_key()` keys on `(document_id, field_name, extractor_version, condition.grouping_key())`; the DDL keyed on everything but the condition. Two claims for one field of one document at two ambients collided | **Fixed** — `condition` added, `NULLS NOT DISTINCT` adopted, four live tests |
| A-42 | **M** | **`audit.event.stream` was redundant with `document_id` by construction and served no requirement it did not.** A `CHECK (stream = 'doc:' \|\| document_id)` pinned its only degree of freedom to zero, and `sql/README.md` decision 8 already conceded the column bought no future capability | **Fixed** — column dropped, chain re-keyed on `document_id`, all six chain properties re-measured |
| A-43 | **H** | **The port contract could not express Decision 3b.** `VectorStorePort.search` took only a dense vector, so the `tsvector` and `pg_trgm` legs had no interface carrying the query *text*; the decision was implementable only by putting raw SQL in the retrieval service or fusing three round-trips in Python. Fusing in Python also put the ACL filter in three places, where NFR-03/AC-8 need one | **Fixed** — `query_text` added; hybrid specified as one statement in the adapter; RRF dropped |
| A-44 | **M** | **Decision 6's context prefix was LLM-generated: one call per chunk, on the one string that is baked into every embedding.** An imported ~67% figure bought an unbounded hallucination surface on the hot path — while D-11 states no benchmark exists for this task — and a prefix misstating a model number poisons dense retrieval for precisely the row-lookup queries C.2 exists to serve | **Fixed** — prefix built deterministically from the chunk row's own metadata; `table_summary` stays generated |
| A-45 | **M** | **WP-I specified a leased job queue whose justification three of this design's own decisions had already removed.** `FOR UPDATE SKIP LOCKED`, 15-minute leases plus a sweeper, backoff scheduling, poison quarantine as a job-row lifecycle and `idempotency_key UNIQUE` — a second idempotency mechanism over a store whose natural keys already make replay a no-op, and a second concurrency mechanism on a node the plan calls single-node sufficient | **Fixed** — plan Decision 1a; WP-I rescoped to a single-process driver; `job` retained as a ledger; leases, sweeper and backoff deferred until a second worker process exists |
| A-46 | **H** | **AC-7 was asserted against an artifact that cannot prove it.** "byte-identical files", universally read as the xlsx, while plan Decision 8c had *already* demoted the workbook hash internally — `%.16g` maps `0.1+0.2` and `0.3` to identical bytes. Two dependent contradictions travel with it: FR-OUT-06 mandates a "generated-on timestamp" that violates AC-7 outright if read as wall-clock, and Decision 8c/G.5's `ExcelWriter`-direct prescription had been superseded by the shipped, 15-test-covered `normalize_archive` | **Fixed** — AC-7 amended to name both layers; FR-OUT-06's stamp defined store-derived; the `ExcelWriter`-direct requirement deleted |
| A-49 | **H** | **Three defects under A-41/A-42, found by reviewing the merged tree.** `condition`'s `DEFAULT '{}'` made the commonest condition two jsonb values, and the comment excusing it said the projection "collapses" when it actually raises and fails the whole field; an audit event could be **its own parent**, satisfying the self-FK by itself, letting an INSERT-only role orphan a chain; and `VOCABULARY_ALIASES` rejected **both** printed spellings its own comment cites as the reason it exists | **Fixed** — `DEFAULT` dropped, `audit_event_no_self_parent` added, `euro_efficiency` aliased. Two residues recorded not fixed: the 2-cycle (belongs to H.5's walk) and the clause-bearing regime (belongs to the extraction boundary) |
| A-48 | **H** | **The integration pass closed three of the four branches' owed-lists and skipped A-45's.** `plan.md` Decision 9 — newly added prose, present tense — instructed an implementer to add `UNIQUE(stream, prev_hash)` on a column A-42 deleted in the same change; Decision 10 contradicted Decision 1a within one file; `ports/__init__.py` contradicted `orchestrator/__init__.py` within one package. Two of the five carriers were in files the pass had itself edited | **Fixed** — all five corrected; the check is a grep for the retired identifier across the merged tree, not the branches' owed-lists |
| A-47 | **L** | **The FR-RAG-03 deviation note went stale a second time in eight days.** A-43 dropped RRF as a fusion stage but could not edit `spec.md`; the note there and the narrating paragraph in `docs/architecture.md` were left naming "fused with Reciprocal Rank Fusion (k=60)". One clause, eight carriers — including a line of this register — and three entries about it in eight days | **Fixed** at integration — both carriers, plus A-40's own prose, now read union-and-dedup with no fusion stage, citing A-24, A-40 and A-43 |

`sql/` was re-read against the contracts it stores rather than against itself. Round 4 established
that the DDL's *behaviour* is now live-tested; this round asks the prior question — whether the
constraints encode what the Python side means. Both findings below are in that gap, and neither was
reachable from the SQL alone: one is a constraint that disagrees with a frozen key, the other a
column whose justification its own documentation had already withdrawn.

## A-41 (High) — the claim key and the claim contract disagree about `condition`

**Artifacts:** `sql/04_claim.sql` vs `src/procurement_agent/services/claims/__init__.py`

`FieldClaim.claim_key()` is frozen and its docstring states the reason in one line: "one datasheet
stating a parameter at three ambients is three claims, not one extractor contradicting itself." The
key is `(document_id, field_name, extractor_version, condition.grouping_key())`. `claim_natural_key`
was `(document_id, component_category, supplier, model, nameplate, field, extractor_version)` — the
component identity added deliberately (sql/README.md decision 2), and `condition` simply absent.

The consequence runs in two directions, and only one of them was visible.

**With `nameplate` set — the PV case, which is D-1's own.** Trina prints STC and NOCT nameplate
power side by side. One document, one field, one extractor version, one bin, two conditions.
Measured against PostgreSQL 16:

```
INSERT ... nameplate 700, field 'nameplate_power', condition '{"basis":"stc"}'
 INSERT 0 1
INSERT ... nameplate 700, field 'nameplate_power', condition '{"basis":"noct"}'
 ERROR:  duplicate key value violates unique constraint "claim_natural_key"
```

**With `nameplate` NULL — inverters and BESS.** An ordinary UNIQUE treats NULLs as distinct, so the
constraint was inert: the Sungrow SG350HX trio (352/320/295 kVA at 30/40/50 °C) inserted, and so did
a genuine same-condition duplicate. Both halves are wrong and they hide each other — the C2 case
survived off-PV only through the NULL gap, so a reviewer sampling inverters saw a healthy
constraint. That NULL half *was* documented (04_claim.sql, and README decision 2). The `condition`
omission was documented nowhere.

**Nothing caught it, and that is the more interesting half.** No Python persists claims yet, so the
projection layer never met the constraint; and `tests/test_sql_behaviour.py` inserted claims but
never two conditions for one field, so the live suite was green against a schema that refused the
central case of the layer above it. A test suite that seeds one row per shape cannot see a
constraint that is wrong about the second row.

**Fix.** `condition` added to the key, and `NULLS NOT DISTINCT` adopted with it. The two are one
change rather than two: the argument for leaving NULLs distinct was that a category with no bin
discriminator might hold more than one instance per supplier+model per document — but with
`condition` in the key, the realistic reason two such rows differ is now represented explicitly, and
what remains under a collapsed NULL is one document, one component identity, one field, one
extractor version and one condition. `claim_key()` calls that one assertion outright, since it does
not carry the component columns at all. `nameplate` is the only nullable column in the key, so the
modifier reaches nothing else.

**The DDL key stays deliberately looser than `claim_key()`, and the comment says so at length.**
It compares `condition` as whole jsonb where the contract compares `grouping_key()`, which excludes
`note` and `derived`; jsonb normalises key order and numeric spelling but treats `{"basis":null}`
and `{}` as different values. So the constraint permits rows the contract counts as one claim. On an
append-only table that is a duplicate the projection collapses, never a rejected valid claim — the
safe direction, and the reason the DDL must not later be "tightened" into a
`grouping_key()`-equivalent expression index.

Four live tests: two conditions of one field both insert; the Sungrow trio inserts; a same-key
same-condition duplicate is refused; the same with `nameplate` NULL is refused. Revert-checked
individually — restoring the old constraint line turns the first and the fourth red.

## A-42 (Medium) — a column whose one degree of freedom was constrained to zero

**Artifacts:** `sql/07_audit_event.sql`, `sql/README.md` decision 8

`audit.event` carried `stream text NOT NULL` beside a `document_id` foreign key whose own comment
read "Redundant with `stream` by construction", the two held equal by
`CHECK (stream = 'doc:' || document_id)`. `stream` then keyed all three UNIQUE constraints and the
self-referential foreign key.

Decision 9's requirement is that the chain be per document, "not globally, so cross-document
concurrency stays unconstrained". That is carried entirely by document-scoped uniqueness;
`document_id` is `NOT NULL` and a foreign key, so it is at least as strong an identity as a derived
text literal. The column's one hypothetical value — a future non-document audit stream — was already
foreclosed by the CHECK that kept it consistent, and `sql/README.md` decision 8 said so in as many
words: "this table cannot be reused for any future non-document audit stream as-is." A column whose
single degree of freedom is constrained to zero is redundancy, not capability.

**Timing is the whole argument for doing it rather than filing it.** tasks.md marks C4 partial —
"the bytes the `hash` column is computed over are still undefined; nothing may emit an event" — so
no chain exists to migrate and no hash is computed over the column. After the first real chain, it
is frozen in.

Re-keyed to `UNIQUE NULLS NOT DISTINCT (document_id, prev_hash)`, `UNIQUE (document_id, seq)`,
`UNIQUE (document_id, hash)` and a self-FK `(document_id, prev_hash) → (document_id, hash)`; the
documented advisory-lock idiom becomes `pg_advisory_xact_lock(hashtext(document_id))`.

**The load-bearing test was whether any chain property depended on the column.** All six were
re-measured against a live server after the change and all six still hold: a valid chain appends; a
fabricated parent is refused; a second disconnected root is refused; a duplicate hash is refused; a
fork is refused; a duplicate genesis is refused. A seventh was added rather than assumed — a second
document must still be able to start its own genesis row, which is the property a plausible
over-simplification (`UNIQUE NULLS NOT DISTINCT (prev_hash)` alone) would break, and which nothing
previously asserted.

**Left outstanding, deliberately.** `tasks.md` H.3 still writes per-document chaining as
`stream = 'doc:1234'`. That file is not this change's to edit, and A-39's lesson applies in the
same words: a finding made in a file you cannot edit is still a finding. The wording needs to follow
the schema.

**Closed at integration**, in the same pass that closed A-43's equivalent note as A-47. H.3 now
names `document_id` as the chain identity, and H.4's `UNIQUE(stream, prev_hash)` — which would have
had a reader adding a constraint on a column that no longer exists — is now
`UNIQUE NULLS NOT DISTINCT (document_id, prev_hash)`, with the advisory-lock idiom spelled out.
Filed under A-42 rather than as a new ID because the finding is A-42's and nothing new was
discovered; A-47 is a separate ID only because *it* required a `spec.md` edit, which the register
requires be entered on its own.

---

Decisions 3b and 6 were read against the interfaces that have to carry them —
`ports/__init__.py`, `services/retrieval`, `services/indexing`, `sql/03_chunk.sql` — rather than
against each other. Both findings are cheap here and expensive later. The retrieval services are
`NotImplementedError` stubs, no adapter implements `VectorStorePort`, and no test imports `ports`
(checked by grep across `src` and `tests` before the signature was touched), so A-43 costs one
signature line today and a breaking interface change once an adapter exists; A-44 costs a
docstring today and a full re-embed of the corpus once C.3 has run once.

## A-43 (High) — a decision no declared interface could reach

**Artifacts:** `src/procurement_agent/ports/__init__.py` vs [plan.md Decision 3b](plan.md) ·
`src/procurement_agent/services/retrieval/__init__.py`

Decision 3b names three legs. Two of them match text: `tsvector`/GIN over `chunk.tsv` and
`pg_trgm` over `chunk_text`. `VectorStorePort.search` took `vector: list[float]` and a filter set,
and `retrieve()` received `embedder`, `store` and `reranker` — the query string existed in the
service and stopped there. So the decision as written had exactly two implementations available:
raw SQL inside `services/retrieval`, which is a second path into the store that no adapter swap
follows and therefore straightforwardly against NFR-04's "vector store swappable behind a stable
interface"; or three store calls fused in Python.

The second is the one worth naming, because it looks harmless. `services/retrieval` already says
that filtering must happen **before** ranking so restricted content never influences a result
(NFR-03, AC-8). Three legs orchestrated in Python is three call sites that each have to remember
`allowed_document_ids`, and the failure is silent in the direction that matters — a leg that
forgets the predicate returns *more*, and the reranker happily orders it. One shared CTE is one
place. It also decides what C.9 is worth: `len(results) == k` on a filtered query covers all three
legs when there is one query, and one leg out of three when there are three.

**The fix is two sentences of contract.** `search` takes `query_text` beside `vector` — the same
query in two representations, both required, so a caller cannot silently get a third of Decision
3b. And the adapter implements the legs as *one statement*: shared filter CTE, three ranked legs
over it, union and dedup by `chunk_id` in SQL, `LIMIT` the rerank budget.

**RRF (k=60) is dropped in the same edit**, and this is the part that deserves an argument rather
than an assertion. Decision 3b's own case for tolerating weak per-leg ranking is that the
cross-encoder determines final order — the ranking function "barely matters" (plan.md, Decision
3b). Grant that, and RRF's only observable effect in this pipeline is *which candidates make the
rerank cut-off*. Size each leg at `budget // 3` and the deduped union is provably no larger than
the budget, so the whole union reaches the reranker; a fusion step applied to a set that already
fits can only drop members. **Union recall ≥ RRF recall by construction**, and the deleted stage
had no other observable output, since final order and `RetrievedChunk.score` were always going to
be the reranker's.

Two things this does **not** touch, deliberately:

- **The reranker stays.** FR-RAG-03's body mandates reranking, NFR-04 names it a swap point, and
  it is the thing that licenses both the missing BM25 (A-24) and now the missing fusion. Removing
  RRF makes the reranker more load-bearing, not less. The degraded path is written down for the
  same reason: reranker unavailable falls back to **dense-score order**, never to RRF, which would
  otherwise creep back as the fallback and be exercised only when nobody is looking.
- **Neither lexical leg is trimmed.** `pg_trgm` in particular is the leg the decision exists for
  (`JKM610N-66HL4M-V` against `JKM610N 66HL4M V`), and `tsvector` supplies recall into the
  candidate set. The revision changes how the legs are *combined*, not how many there are.

**Left open deliberately, and this branch cannot fix it.** `spec.md`'s FR-RAG-03 deviation note
and `docs/architecture.md` both still describe the replacement as "fused with Reciprocal Rank
Fusion (k=60)" — which was correct when A-40 corrected it and is now half-stale, naming a fusion
stage the plan no longer has. The requirement text is untouchable here (this is a plan-level
revision and `spec.md` is two ranks above `plan.md`), and correcting the note is itself a
`spec.md` edit that has to be registered on its own, exactly as A-40 was. Recording it rather than
reaching for the file is A-39's rule: a finding made in a file you do not own is still a finding.
The remedy is one clause — "unioned and deduped in a single statement, then reranked, not BM25" —
and it should cite A-24 and A-43 together.

**Closed at integration by [A-47](#a-47-low--the-fr-rag-03-note-went-stale-a-second-time) below**,
which is the entry this paragraph asks for.

## A-44 (Medium) — the one string you cannot cheaply change was the generated one

**Artifacts:** [plan.md Decision 6](plan.md) and [tasks.md C.3](tasks.md) vs `sql/03_chunk.sql`

Decision 6 asked for 1–2 LLM-generated sentences of document/section context per chunk, prepended
before embedding. `sql/03_chunk.sql` had already had to defuse half of that: `context_prefix` is a
separate column from `chunk_text` precisely so a citation never shows a reviewer generated framing
as if it were the source, and the lexical indexes run over `chunk_text` only. That split is right
and is kept exactly as designed.

What the split does not defuse is the embedding. The prefix is *inside* the vector, and the fields
a datasheet chunk is retrieved by — supplier, model, section — are the fields a generated sentence
is most likely to get subtly wrong. A prefix reading "Jinko JKM610N-66HL4M" on a chunk from a
`JKM610N-66HL4M-V` sheet is not a cosmetic error; it is a wrong part number embedded into the one
representation the dense leg searches, for exactly the row-lookup queries C.2 calls out ("what is
the Voc of module X"). The evidence on the other side is thin by the register's own standard: the
~67% retrieval-failure reduction is imported from large-corpus benchmarks, and D-11 states flatly
that no public benchmark exists for PV/inverter/BESS datasheet extraction and every accuracy
figure in the plan is extrapolated. A-9's rule applies: where two options both work, the one that
wins is the one with the less fragile failure mode.

**The chunk row already carries everything the sentence was going to say.** `supplier`, `model`,
`document_type`, `section` and `page` are denormalised onto `public.chunk` (sql/03_chunk.sql), so
the prefix is a join-free format string over validated metadata:

    "Jinko Solar JKM610N-66HL4M-V spec sheet - Electrical Characteristics (p. 4): "

Zero LLM calls, deterministic, reproducible from the row — a mismatch between prefix and metadata
becomes a bug with a cause rather than a generation artefact. `services.indexing.context_prefix`
declares it, and takes no `LLMPort`, which is what makes the decision enforceable rather than
merely written down.

**`table_summary` stays LLM-generated, and the asymmetry is the whole point.** Its case is the one
the prefix's was borrowed from and does not hold: query vocabulary like "temperature coefficient"
or "derating" genuinely appears nowhere in the cells, so there is real information to add, and it
is one call per *table* rather than per chunk. After this revision it is the only generated text
in the index path, which is a defensible resting point — one generator, one chunk kind, and it
never touches a `table_row` or `prose` embedding.

**Why now and not after the first corpus.** The prefix is baked into every embedding, so changing
strategy later is a full re-embed of every chunk — the single operation FR-RAG-05's incremental
add/update/delete philosophy exists to avoid, and the one thing `VectorStorePort.upsert`'s
stable-ID contract cannot make cheap. Today it is a docstring and a column comment.

**One wording left for the file's owner:** `sql/README.md` item 15, under "Design decisions made
here that the specs did not settle", justifies the `context_prefix`/`chunk_text` split as keeping
"a generated framing sentence" out of citations.
The split survives this revision unchanged and so does the reasoning, but "generated" is now the
wrong word for the prefix specifically — the honest form is that a citation shows source text and
nothing else, generated or derived. Not edited here; `sql/README.md` is not this branch's file.

---

Two revisions of the same shape, and neither rests on a new measurement: in both cases this
repository already contained the argument, and a higher-ranked artifact had not caught up with it.
One collapses a runner the design's own decisions had already made unnecessary; the other points
an acceptance criterion at the artifact that can actually carry it.

## A-45 (Medium) — the queue outlived the requirement that justified it

WP-I I.1–I.5 and `sql/08_job.sql` specify a durable work queue: workers claim rows with
`SELECT … FOR UPDATE SKIP LOCKED`, hold a 15-minute lease that a sweeper reclaims, retry on a
persisted backoff schedule, quarantine poison messages through a job-row lifecycle, and
deduplicate enqueues on `idempotency_key UNIQUE`. `sql/08_job.sql` is built and live-tested;
`orchestrator.run` raises `NotImplementedError`, so nothing has been written against it yet. That
is the cheapest moment this finding could have been made.

**Three of this design's best decisions already removed what makes a durable queue necessary.**

1. **Decision 2 detached the human gate.** The single thing that forces durable, resumable job
   state is a pipeline parked for days awaiting a person, and that was deliberately designed out:
   the gate is a compose-time query, `orchestrator.compose_gate_blocks`, not an interrupt. A-3
   removed `AWAIT_HUMAN_RESOLUTION` from `Stage` for the same reason.
2. **The store is already idempotent by natural key.** `document_content_hash_unique`
   (`sql/02_document.sql:50`, NFR-05/AC-5), append-only claims under `claim_natural_key`
   (`sql/04_claim.sql`, `claim_natural_key`), and composition a pure function of the store (FR-OUT-06).
   `job.idempotency_key` is therefore a *second* idempotency mechanism layered over a store whose
   own keys already make replay a no-op — which is the same duplication A-2 and A-3 were about,
   reached by a different route.
3. **Concurrency already lives elsewhere.** `Settings.max_concurrent_parse` and
   `Settings.max_concurrent_llm` (`src/procurement_agent/config.py:86-91`) bound a process pool
   and a thread pool, and `docs/agent-topology.md:34,40` finds the only dominant fan-out win is
   `ingest` — a process pool, because parse is CPU-bound — and says composition **must stay
   serial**. A `SKIP LOCKED` worker *fleet* is a second, redundant concurrency mechanism on a
   single node.

What the queue uniquely buys is crash-resume that skips completed documents. With natural-key
idempotency, crash recovery is "re-run the batch; completed work no-ops". The scale anchors are
all in-repo and all point the same way: NFR-06 says hundreds, "**Not thousands. Do not
over-engineer for volume**"; plan.md's technical context says "single-node is sufficient"; the
13-tab workbook builds in 0.10 s; exact vector search is 3.5–5.5 ms; parse averages 3.1 s/page,
so OCR-heavy ingest is the only stage where a re-run costs real wall-clock. The tool is run
occasionally, not continuously.

**One cost the collapse may not claim.** I.2's "every stage must be independently idempotent" is
required under *either* runner — a driver that re-runs needs it exactly as much as at-least-once
delivery did — so it is not a saving attributable to the queue. What the queue costs, and what
this removes, is the leases, the sweeper, the backoff scheduler and the `idempotency_key`
grant-hardening (`sql/08_job.sql`'s column-level `UPDATE` grant, A-32).

**The `job` table stays** as a progress and quarantine *ledger the driver writes*, not a queue
workers contend on. Poison handling becomes a recorded per-document status — a `quarantined` row
with `last_error` — which is the job-table expression of plan Decision 4's tier-3 rule that a
page failing every engine is recorded with its page reference, never dropped. The lease pair,
`next_attempt_at` and `idempotency_key` stay in the DDL unused, so adopting a second worker
process later is a runner change rather than a migration. Nothing in `sql/08_job.sql` needs to
change for this finding, which is why the collapse is cheap in both directions.

**Precondition, recorded as a dependency rather than assumed.** "Re-run is free" holds *because*
the `content_hash` UNIQUE constraint plus `INSERT … ON CONFLICT (content_hash) DO NOTHING` makes
the database refuse the duplicate. AC-5 needs that constraint anyway, so this adds no work — but
it **consumes** it, and if the constraint were ever relaxed the driver would become unsound
before AC-5 visibly failed. Written into WP-I as **I.1a** so it is a task dependency and not a
footnote. `docs/agent-topology.md:134-135` had already named transactional dedup as the prerequisite
for "retry-is-free"; this finding is what that prerequisite is now load-bearing *for*.

**Honest risk, recorded rather than argued away.** An OCR-heavy multi-hour batch that crashes
near the end repeats more wall-clock work than a resumable queue would. It is bounded by corpus
size, occasional, and paid only on a crash — against machinery that would otherwise be paid for
on every run and maintained forever. I.5's NFR-06/NFR-07 measurement against a real corpus is
also the measurement that would justify revisiting this.

**Explicitly NOT the conflict-claim leases.** `sql/05_conflict.sql`'s `lease_owner` /
`lease_expires_at` pair and tasks.md **F.1**/**F.4** (15-minute lease, D-12e) are a different
table with genuine **multi-human** contention: two reviewers must not be handed the same
conflict, and a reviewer who closes their laptop must not hold one forever. Every clause of the
argument above is false there — the actors are people rather than one process, the wait is
open-ended by design, and no natural key makes a second reviewer's work a no-op. Written out in
plan Decision 1a's closing paragraph and in the WP-I header so nobody over-applies this.

**Owed, in files this change does not own.** Registering these rather than dropping them is A-39's
rule: a finding made in a file you cannot edit is still a finding.

- `sql/08_job.sql:1-12,74-87` describes itself as the worker loop and documents the sweeper's hot
  path; the DDL is correct and only the prose needs retargeting to "ledger".
- Contract **C8** (tasks.md Phase 0) still reads "job states, claim/lease semantics, idempotency
  key". C8 is a frozen-ish contract row and changing it is a contract change per `CONTRIBUTING.md`,
  so it is named here rather than edited.
- plan **Decision 10** argues sync ports partly from "scaling it means more worker processes,
  which sidesteps the GIL entirely". **Its conclusion is unaffected and if anything strengthened**
  — the driver's parse pool is a `ProcessPoolExecutor`, which sidesteps the GIL by the same
  mechanism, and `max_concurrent_llm`'s thread pool is exactly the `ThreadPoolExecutor` overlap
  Decision 10 already names for `LLMPort`. Only the sentence's premise needs rewording.
- `README.md:96`, `docs/architecture.md:217`, `docs/agent-topology.md:7,89` and `docs/defaults.md:24`
  each describe the runner as a `SKIP LOCKED` loop, and `src/procurement_agent/ports/__init__.py:15`
  repeats it as the reason the ports are synchronous.

## A-46 (High) — the acceptance criterion pointed at the artifact that cannot carry it

AC-7 read: *"Generating the workbook twice from an unchanged canonical store produces
byte-identical files."* Everything downstream read "files" as the `.xlsx` — G.5 verifies AC-7 with
`sleep(1.1)` between two renders, and `docs/requirements-traceability.md:187` scores AC-7 on
`normalize_archive`.

Meanwhile plan Decision 8c had **already demoted the workbook hash**, in its own words: *"But hash
the canonical projection, not the workbook. The xlsx is lossy, so its hash cannot prove what AC-7
wants"* — `%.16g` maps `0.1+0.2` and `0.3` to identical bytes, so the store can hold two genuinely
different float64 values that render to an identical workbook. G.1 calls the sorted-key `repr()`
-float JSON *"the hashed artifact of record"*. The repository held the answer at rank 4 and rank 5
and stated something weaker at **rank 2**, which is the exact shape `README.md:271` warns about:
"a plan-level decision ends up quietly overriding a requirement".

**The amendment names both layers.** (a) The canonical projection is byte-identical across
regenerations of an unchanged store — *this is the acceptance criterion*. (b) The rendered xlsx
hash is pinned in CI as a **renderer-regression check** whose golden value may be deliberately and
auditably refreshed.

**It does not weaken determinism, and that is the point to check hardest.** Layer (a) is
*stricter* than the sentence it replaces: it is the layer that catches the float collision, which
no workbook hash can. Every line of built code is kept — `normalize_archive`'s five
normalizations each map to a verified nondeterminism source (clock, library version, compression,
member order, platform) with 15 tests behind them, several of which exist because a version
missing one of the five shipped first. What the split buys is that a future openpyxl security
patch, or a G.6 desktop-Excel failure forcing A-9's alternative entry ordering or epoch, becomes a
**recorded hash refresh of layer (b)** instead of an acceptance-criterion crisis — and that is
strictly better than the alternative outcome, which is a team quietly relaxing AC-7 under
schedule pressure because the criterion as written could not absorb a renderer change.

**Recorded as a deliberate amendment to a rank-2 artifact.** `docs/architecture.md`'s [Specification authority](../docs/architecture.md#specification-authority) section makes
this the register's job — A-23, A-24 and A-25 are the precedents, each a normative `shall`
reversed by a plan decision and filed here. The difference is that those three restored the TRS
wording and marked the reversal inline, because the TRS was the source. AC-7 is **not** TRS
wording: spec.md says so itself — "AC-7 and AC-8 are additions to the TRS's six" — so there is no
source text to preserve, and amending the sentence is the correct move rather than annotating it.
A-8's precedent (leave spec.md faithful, harden in the plan) does not apply for the same reason.

**FR-OUT-06's latent contradiction, resolved.** FR-OUT-06 requires the workbook to carry a
"generated-on timestamp", and `write_workbook`'s docstring repeated it. Nothing said what it is
derived from, and the obvious reading — wall clock — makes two generations of an unchanged store
differ *by construction*, violating AC-7 while satisfying the sentence that mandates the stamp.
Settled in the FR-OUT-06 text as **store-derived, never `now()`**: the high-water mark of the store
rows composition reads — `document.ingested_at`, `claim.extracted_at`, `resolution.resolved_at` —
which moves exactly when the store changes and not otherwise. Noted as a **C6 input** (tasks.md
T0.5, new task G.1a) because the stamp is a projection field, so freezing C6 fixes its derivation
once and both AC-7 layers inherit it, rather than the writer picking. Left deliberately as a rule
rather than a formula: which rows are "in scope" is a projection-scoping question C6 owns.

**The superseded `ExcelWriter`-direct requirement, deleted.** Decision 8c and G.5 prescribed
driving `ExcelWriter` directly to bypass `save_workbook`'s unconditional `modified = now()`
re-stamp, on A-9's reasoning that it beat "post-hoc rewriting `core.xml`". The implemented,
15-test-covered artifact does the post-hoc rewrite: `services/output.normalize_archive` regex-fixes
`docProps/core.xml` and `docProps/app.xml`. Keeping the shipped one is right for a reason neither
research stream had when A-9 chose: **the normalizer must rewrite the whole ZIP container
anyway** — member mtimes, entry order, compression level, `create_system` and `external_attr`
cannot be reached from inside openpyxl's writer at all — so the `core.xml` substitution rides
along for one regex, while `ExcelWriter`-direct fixes one of five sources and would *still* need
the container pass after it. Two mechanisms doing half the same job is how one of them silently
stops being exercised.

Filed inside A-46 rather than as an amendment to A-9, following A-40 and A-37: A-9 closed as
**Resolved** and was, on the evidence then available; that one of its three sub-choices was later
superseded by the built artifact is a new finding, and rewriting the closed entry would erase that
the plan and the code disagreed for the interval between them. A-9's other two choices — the
12:00 epoch and sorted-with-`[Content_Types]`-first ordering — are untouched. Only the ordering
one keeps a usable fallback for G.6: A-9's own reasoning rules out reverting the epoch to
midnight, because DOS timestamps are local and midnight underflows the 1980 floor in negative UTC
offsets, so a timestamp failure in desktop Excel would need a new value rather than the other
stream's.

**Correction to the openpyxl exact-pin rationale — the pin stays.** Decision 8 justifies
`openpyxl==3.1.5` on the grounds that `docProps/app.xml` embeds `Openpyxl 3.1.5`, and
`pyproject.toml:15-17` repeats it. That specific rationale is now **stale**: `normalize_archive`
rewrites both `<Application>` and `<AppVersion>`, and
`tests/test_workbook_determinism.py::test_library_version_is_not_embedded_in_the_output` asserts
the string is gone. The pin's real remaining job is cross-environment reproducibility against
silent XML-serialisation drift *between* versions — element ordering, attribute defaults,
whitespace and float formatting are outside openpyxl's compatibility promise and none of it is
stripped by the normalizer. Recorded in Decision 8c rather than fixed in place, because
`pyproject.toml` is outside this change's scope; the corrected wording is there for whoever next
edits that comment, and a reader who deletes the pin on the strength of the stale reason would be
deleting a live guarantee.

**Owed, in files this change does not own.** `tasks.md`'s acceptance-criteria ownership table
still scores AC-7 as "☐ gated on G.6"; under the amendment only layer (b) is gated on G.6, and
layer (a) is gated on C6 and G.1 instead. `docs/requirements-traceability.md:187` and
`docs/current-state.md:176` score AC-7 against `normalize_archive` alone and should name both
layers. None of these change a verdict — AC-7 is `partial` either way, since `write_workbook`
still raises `NotImplementedError` — so they are drift, not error.

**Two of the three closed at integration; the third deliberately not.** `tasks.md`'s ownership
table now carries AC-7 as two rows — (a) gated on G.1, (b) gated on G.6 — and
`docs/requirements-traceability.md` scores the layers separately, noting that the previous row
credited layer (b)'s partial coverage to what is now layer (a).

`docs/current-state.md` was left alone, and that is a decision rather than an omission. Its first
sentence pins it: "*This audit describes `main` at commit `72deacf` on 2026-08-04*", and its stated
baseline of "470 passing tests and 23 skipped" is already three merges behind (511 with a DSN, 482
plus 29 skips without). It is a dated snapshot, not a live status page. Patching one row inside it
would produce a document that is current about AC-7 and stale about its own commit pin, test
baseline and AC-5 row — the failure mode is a reader trusting the rest of it because one row looked
fresh. It needs a whole refresh against a named commit, which is a separate piece of work, and it is
recorded here as owed rather than done.

---

## A-47 (Low) — the FR-RAG-03 note went stale a second time

**Artifacts:** `specs/001-procurement-agent/spec.md:110` · `docs/architecture.md:263`

Found at the integration of this round, not during it, and it is the entry A-43 asks for above.
A-43 dropped RRF as a fusion stage but could not touch `spec.md`, so the deviation note beside
FR-RAG-03 — and the paragraph in `docs/architecture.md` that narrates the note's own history —
were left naming "fused with Reciprocal Rank Fusion (k=60)". Both now read as a union-and-dedup
with no fusion stage, citing A-24, A-40 and A-43 together.

**Severity Low because nothing downstream had consumed it.** Every code carrier
(`ports/__init__.py`, `services/retrieval/__init__.py`, `services/indexing/__init__.py`) was
already correct — A-43 wrote them — and the retrieval services are `NotImplementedError`, so no
adapter was built against the stale clause. What it cost was the register's credibility rather
than any behaviour: a reader checking whether FR-RAG-03 was honoured would have found the highest-
ranked artifact describing a stage the plan had removed.

**This is the same sentence going stale for the second time in eight days**, and that is the part
worth recording. A-24 reversed the requirement, A-40 corrected which replacement the note named,
A-47 removes the fusion stage from it. Three entries, one clause, because the clause is duplicated
across **seven** carriers, each free to drift: `spec.md`'s FR-RAG-03 note, `plan.md` Decision 3b,
`tasks.md` C.5, `docs/architecture.md`, and three docstrings (`ports/__init__.py`,
`services/retrieval/__init__.py`, `services/indexing/__init__.py`).

**An eighth was this register itself, and the first version of this entry missed it** while
counting five. A-40's prose at the top of this file asserted the fused form in the present tense;
it is now amended in place with the amendment marked. The lesson is not subtle: an entry whose
whole argument is *"one clause, many carriers, nobody enumerated them"* enumerated them wrong, and
did so while the correct enumeration sat in a table it cites. Counting carriers is exactly the step
that gets skipped, including by the person writing the finding about skipping it.

The structural answer already exists: the "where does this decision live" table at
`docs/architecture.md:245` enumerates the carriers, and working that table is what surfaced the
second file. The remaining exposure is that the table lists carriers for *this* decision only.
Recorded, not fixed — generalising it is a documentation change with no requirement behind it yet.

**Process note.** A-43 was written by a review scoped to `ports`/`services/retrieval`/
`services/indexing`, which correctly declined to edit `spec.md` and recorded the remedy instead
(A-39's rule). That worked: the finding survived the scope boundary and was closed by the one
party who owned both files. A-39's precedent is now load-bearing twice.

---

## A-48 (High) — the integration pass closed three branches' owed-lists and skipped the fourth

**Artifacts:** `specs/001-procurement-agent/plan.md` · `src/procurement_agent/ports/__init__.py` ·
`docs/architecture.md` · `sql/README.md` · `sql/07_audit_event.sql`

Found by a review of the integrated tree, after A-41…A-47 had been merged and pushed.

Every branch in Round 5 was scoped to a file set, and each recorded what it could see but not
reach under the heading **"in files this change does not own"** — A-39's rule, working as intended.
Integration is where those become reachable, and the pass closed A-42's (`tasks.md` H.3/H.4),
A-46's (the AC-7 scoring rows) and A-47's (both FR-RAG-03 carriers). **It did not close A-45's**,
and A-45's list was the largest.

The damage, in descending order:

| Carrier | Said | Should say |
|---|---|---|
| `plan.md` Decision 9 | `UNIQUE(stream, prev_hash)` is "load-bearing under the driver" | the column was deleted by A-42 in the same integrated change |
| `plan.md` Decision 10 | "Decision 1 makes the runner a … `SKIP LOCKED` worker loop — that pattern *is* the concurrency mechanism" | Decision 1a, ~600 lines earlier in the same file, retracts exactly that |
| `ports/__init__.py:13` | same `SKIP LOCKED` claim, contradicting `orchestrator/__init__.py:13` in the same package | Decision 1a's two pools |
| `docs/architecture.md:217` | "Workers claim jobs using `SELECT … FOR UPDATE SKIP LOCKED`" | the single-process driver; `job` as ledger |
| `sql/README.md` 17, 18 | the DAG is "the worker's responsibility at enqueue time"; the 15-minute lease | sequencing is a `for` loop; the lease columns are unused |

**Decision 9's is the one that matters**, and it is worse than staleness. It is *newly added* prose,
present tense, inside a blockquote whose entire stated purpose is to assert what survives Decision
1a — and it instructs an implementer to add a constraint on a column that no longer exists. That is
a build failure, not a documentation defect. `tasks.md` H.4 carried the identical instruction and
was caught; `plan.md` outranks `tasks.md`, and the higher-ranked copy was the one missed.

**Two of the five were in files the integration pass had already opened and edited.**
`docs/architecture.md` was edited for A-47 and `sql/README.md` for A-42, in the same sittings that
left their stale queue paragraphs untouched. So the failure is not "these files were out of reach"
— it is that *the owed-list was worked per-finding instead of per-file*. A-45's entries stayed
filed under "does not own" long after that had stopped being true, and nothing re-read the
justification once the merge made it false.

**A-45's own list also omitted `plan.md` Decision 9 entirely**, so two of the five were not merely
unclosed but unrecorded. A branch enumerating what it cannot reach will under-count, because the
enumeration is bounded by what that branch happened to read.

**The remedy is a check, not a resolution.** *Before merging a batch of scoped reviews, grep the
combined tree for the retired identifier itself* — here `stream` and `SKIP LOCKED`, two greps —
rather than working from the owed-lists the branches wrote. The lists are what each branch could
see; the grep is what is actually there. Both greps run clean now, and both would have caught all
five in seconds. Recorded as a check rather than added to CI: a literal grep for one retired name
is not a durable test, and inventing one to look rigorous would be worse than naming the step.

**Severity High** because Decision 9's clause is executable instruction in a rank-4 artifact, and
because the class — *a scoped review's owed-list going stale at the moment of integration* — will
recur every time this project fans work out, which it now does routinely.

---

## A-49 (High) — three defects the round's own fixes created or left standing

**Artifacts:** `sql/04_claim.sql` · `sql/07_audit_event.sql` ·
`src/procurement_agent/schema/field.py`

An adversarial review of the merged SQL half. It **could not refute** A-41's central argument —
3,063 `Condition` instances and 820 adversarial pairs produced zero cases the frozen contract calls
distinct and `NULLS NOT DISTINCT` rejects, so that tightening is sound — and then found three
things underneath it.

### (a) The `condition` default made "unstated" two values, not one

`Condition().model_dump(mode="json")` is `{"basis":null,…,"derived":[]}`. The column's
`DEFAULT '{}'::jsonb` is jsonb-**distinct** from that, while `grouping_key()` calls the two
identical. So a caller omitting the column and a caller serialising the model faithfully wrote two
rows for one claim, and `claim_natural_key` saw nothing wrong — on what `services/claims.project`'s
own docstring calls "the commonest condition by far".

**The comment's stated consequence was also wrong, in the reassuring direction.** It said a
duplicate "collapses (services/claims.canonical_claims), not a lost or corrupted value".
`canonical_claims` collapses only when the duplicates agree; when they disagree it raises
`ProposalError` and `project()` propagates, so the **whole field's projection fails**. Measured:

```
canonical_claims([claim("700"), claim("999")])   # identical grouping_key
→ ProposalError: two different values share the claim key
```

**Fixed** by dropping the `DEFAULT`, which closes the *silent* half — omission is now a
`NotNullViolation` rather than a second spelling. The explicit half (a caller writing a bare `'{}'`
on purpose) cannot be closed by any CHECK without hardcoding into the DDL the dimension list this
column exists to keep out of it. That residue is recorded as a **write-path obligation against
C2/C8**: serialise this column through one function, the same one `claim_key()` reads. It is free
to record now because no Python writer for this table exists yet.

### (b) The hash chain was still not walkable: an event could be its own parent

A row whose `prev_hash` equals its own `hash` satisfies the self-FK **by itself** — the parent it
names is the row being inserted — so every constraint passed and the INSERT succeeded as
`procurement_app`, the INSERT-only role. Not cosmetic: the documented tip read
(`ORDER BY seq DESC LIMIT 1`) returns the planted high-`seq` row, so every honest append afterwards
chains off the plant and the genuine chain is orphaned, and the H.5 walk from that tip revisits one
row forever without reaching genesis.

Pre-existing — `origin/main` accepts it too — but this round rewrote that block and presented
*"each is silent, and each produces a chain that can never be verified"* as closed. Three shapes
were closed; a fourth was not, and no foreign key can express "not yourself".

**Fixed** by `CHECK (prev_hash IS DISTINCT FROM hash)`. Revert-checked: removing it reds exactly
one test.

**A fifth remains open and is recorded rather than fixed.** Two rows inserted in one statement,
each naming the other, are accepted — the FK is checked at end-of-statement and every CHECK is
per-row. No constraint on the table can see the pair. What the cycle cannot hide is that
`audit_event_genesis_seq_zero` forces both members to a non-zero `seq`, leaving the document with
**zero** genesis rows. That is the detection property, and it belongs to **WP-H H.5**: the walk must
cap its hops and must assert exactly one genesis per document. A walk that merely follows
`prev_hash` until parents run out will hang instead of reporting. Pinned by a test that asserts the
hole, with instructions to delete it if a future constraint closes it.

### (c) The alias table rejected both spellings its own comment cites as its justification

`VOCABULARY_ALIASES` exists because "rejecting a real spelling is worse than folding a synonym", and
names two: Fronius/SMA sheets printing "Euro efficiency", and this repo's own text writing
"ANSI/IEEE (C57.12.00 5.4)". Both raised `ValidationError` — `euro_efficiency` was not in the table
(only bare `euro`), and the clause-bearing form matched nothing. The table dropped documents on its
own worked examples.

**`euro_efficiency` fixed** — a fixed industry term, folding it asserts nothing.

**The clause-bearing form deliberately left failing, and the attempt to fix it is the more useful
record.** A fallback stripping a trailing parenthetical *after* the whole token failed was written,
resolved the case correctly, and changed no currently-valid input — the ordering was the safety
property. It was reverted because a test written in the same pass caught it resolving
`IEC (but not really)`, and therefore `IEC (draft)` and `IEC (superseded)`, where the parenthetical
is the part that carries the meaning. Nothing textual distinguishes a citation from a qualifier, and
a wrong regime picks the wrong multi-cooling rating in silence. The obligation moves to the
extraction boundary: emit the regime and the citation as separate fields.

**Severity High** for (b) — an INSERT-only role could orphan an audit chain the design calls "the
only mechanism that survives the superuser bypass" — with (a) and (c) Medium on their own.

**What this round says about review.** The batch's own four reviews all reported clean on the
artifacts they built; A-48 and A-49 both came from reviewing the *merged* tree afterwards, against
the code rather than against the branches' summaries. Three of the five defects across the two
entries are **claims in comments that the code does not do** — the projection "collapses", the index
serves the RLS filter, the FK makes a document "never absent" under a bypass the same file names.
That class survives every test suite by construction, because nothing executes a comment.

---


## Consistency checks that passed

- All **32** FR IDs in spec.md match the TRS analysis; none invented, none dropped. (An earlier version of this line said 26, which is the count with FR-OUT-01..06 omitted — see A-27. The sweep itself was correct; the total was not.)
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

- **AC-1 and AC-6 have no tests.** They need the ingestion path and a labelled corpus, which
  is WP-B and D-11 work. Recorded as open in the traceability doc rather than papered over.
  (**AC-5 left this group on 2026-08-04** — see A-37. Its store-level invariant is live-tested by
  `test_a_duplicate_content_hash_is_refused`; only the ingest path that would exercise it is
  missing, so it is `partial` rather than `open`.)
- **FR-ING-02 and FR-ING-05 have no home in code yet** beyond `ParserPort`. Correct at
  scaffolding stage; assigned to WP-A.
- **NFR-06 and NFR-07 have no verification.** Both are scale/latency properties that need a
  running system. Assigned to WP-I.
