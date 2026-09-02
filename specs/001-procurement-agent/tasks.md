# Tasks: parallel work breakdown

**Spec:** [spec.md](spec.md) · **Plan:** [plan.md](plan.md) · **Decisions:** [clarifications.md](clarifications.md) · **Analysis:** [analysis.md](analysis.md) · **Current execution plan:** [phase-1-execution.md](phase-1-execution.md)

Structured for several teams working simultaneously. Read **Phase 0 first** — nothing
parallelises until the contracts are frozen, and the most common way a plan like this fails is
teams shipping seven incompatible versions of the same record.

> **Anti-pattern, named explicitly:** do not assign teams by pipeline stage *and* let them define
> their own interfaces. **The contracts are the deliverable of week one; the stages are the
> deliverable of week two onward.**

---

## Phase 0 — Contract freeze (BLOCKING, ~1 week, 1–2 people)

The only true serialisation point in the plan. Everyone else reviews; nobody implements against
an unfrozen contract.

| ID | Contract | Gates | Status |
|---|---|---|---|
| **C1** | Postgres schema: `document`, `chunk`, `claim`, `conflict`, `resolution`, `audit.event` | Every WP | **done** — all six, plus `job` and `conflict_candidate`, in `sql/00`–`08`; both T0.1 checks recorded live-verified in `sql/README.md`, and CI reapplies all nine files each run |
| **C2** | Claim/extraction record — Pydantic + JSON Schema, including `condition` per D-1 | B, E, G | **partial** — `condition` landed on `FieldClaim` and `CanonicalField`; per-category models still do not exist |
| **C3** | Provenance reference — `(document_id, page, span, extractor_version)` | A, B, D, F, G | **done** — all four on `SourceRef`, **`span` under the name `section`**, stamped by `FieldClaim.provenance()` and pinned by `test_source_ref_carries_c3s_four_elements` |
| **C4** | Audit event envelope + `event_type` taxonomy + canonicalisation rule | All | **partial — decision half now closed.** [D-13](clarifications.md) (adopted 2026-08-07) settles the scheme (RFC 8785 via `rfc8785`), the preimage (one JCS object with `"v": 1`), the digest (SHA-256) and the taxonomy (v1, additive-only). What remains is code: no Python envelope, no canonicalisation library, no emitter. ⚠️ The version marker must exist **before the first event is ever emitted** |
| **C5** | Conflict record + the five resolution action shapes | E, F, G | **done** — `ConflictQueueEntry`, `ResolutionAction` |
| **C6** | Canonical workbook projection — sorted-key JSON, floats via `repr()` | G | ☐ **— format frozen, nothing built.** [D-14](clarifications.md) (adopted 2026-08-07) freezes the bytes, the shape, `encode_value()`, policy-inside-the-hash and the store-derived `generated_on`. `write_workbook()` still raises and no *workbook* projection function exists (`services.claims.project` is C8's claims→fields projection, a different thing) |
| **C7** | Retrieval interface + ACL/labelling model | A, C | **partial** — RLS enforces the one label the schema has (`access_restricted`). [D-15](clarifications.md) adopts that model **provisionally** and closes T0.4's written-decision criterion, but two facts remain outstanding and they are facts rather than preferences: whether any executed NDA exceeds "need to know", and whether any evaluator is conflicted with a specific bidder. **The two answers do not lead to the same place** — an NDA trigger makes the label `restricted_group`; a recusal alone wants a per-person deny-list with the boolean intact (D-15's own table) |
| **C8** | Stage runner contract — job states, claim/lease semantics, idempotency key, **plus the append-only claim invariant below** | A, B, D, E, I | **partial** — the append-only invariant is enforced in both halves; `job` is the DDL's own proposal and `orchestrator.run` raises `NotImplementedError` |

Three of the eight are done, four are partial and one is untouched. Read the four partials
carefully rather than by their marker: **C4 and C8 each have a finished SQL half and an unstarted
Python half**, and they are the pair most likely to be mistaken for finished, because `sql/` is
the visible artifact and what is missing — WP-H's canonicalisation library, WP-I's runner — is a
file nobody has opened yet.

> **C8 invariant — workers propose, they do not commit.** Each extraction writes an **immutable
> claim row** keyed by `(document_id, field, extractor_version)`; the canonical value is a
> **projection over claims**, never an in-place update. Only the reducer takes a store write
> handle, and it calls `assert_no_autonomous_overwrite` internally.
>
> This is a *structural* property; the guard alone gives only a *value* property. It is a pure
> predicate over two fields — it takes no store handle, performs no write, and **cannot enforce
> that it is called**. It also deliberately permits record-over-record (inter-document conflict is
> the queue's job), which under concurrent writers is a lost update it passes silently. And it has
> no notion of ordering: two workers finishing in different orders yield different
> last-writer-wins outcomes, making the store itself non-deterministic — which defeats FR-OUT-06
> even though composition is a pure function of that store.
>
> With append-only claims there is no overwrite to guard. The unreachability test ("the write API
> is not reachable from worker context") becomes writable once C1 and C8 land, and should gate
> them.

**C1, C2, C3 and C7 are the expensive ones to change.** C1 and C3 have since landed, which makes
them *more* expensive rather than retiring the warning — there is now DDL applied to a live
cluster, a CI suite pinning its behaviour, and a test asserting C3's fourth element survives the
projection. C2 and C7 are the two still open, and they are where the week is best spent.

> ⚠️ **C4 must ship before any stage emits events.** Changing the hashed field set later
> invalidates every existing chain. WP-H ships its library first, even if thin. **The table
> shipped without the library.** `sql/07_audit_event.sql` defines the envelope, the `event_type`
> CHECK and `payload_canonical`. **[D-13](clarifications.md) (adopted 2026-08-07) closed the
> decision half**: the scheme is RFC 8785, the preimage is one JCS object carrying `"v": 1`, the
> digest is SHA-256, and `sql/07`'s caller-sequence comment now carries that object literally —
> so the bytes the `hash` column covers are **defined**. The taxonomy is version 1 with
> additive-only amendment.
>
> What is missing is code: H.2's canonicalisation library does not exist in `src/`, and
> `rfc8785` is not yet a dependency. **Nothing may emit an event until that library exists** —
> not because the bytes are unknown, but because nothing can compute them yet.

> ⚠️ **C7 is a single decision constraining two work packages at opposite ends of the pipeline**
> (labelling at ingest, enforcement at retrieval). This is the most common place this kind of
> plan breaks. **The enforcement mechanism has now landed ahead of the decision**: `sql/`
> applies `FORCE ROW LEVEL SECURITY` to seven tables, keyed on the single boolean
> `SourceDocument.access_restricted` and gated by an `app.allow_restricted` session GUC, and
> `sql/README.md` says in as many words that this is C7 "implemented at its frozen minimum, not
> guessed at in full". That was the right way to have built it, and **T0.4 is now written as
> [D-15](clarifications.md) (2026-08-07)**, which ratifies that minimum rather than replacing it:
> one document-level label, per-principal clearance from the OIDC subject, labelling at ingest
> failing closed, and `VectorStorePort.search(allowed_document_ids=...)` as scoping *within* an
> entitlement rather than the boundary. It is **provisional** — two facts about NDA scope and
> evaluator conflicts remain outstanding. **They do not lead to the same place**, and an earlier
> summary of D-15 wrongly collapsed them into "either yes → `restricted_group`": an NDA
> exceeding "need to know" turns the label into `restricted_group`, while a recusal alone wants
> a per-person **deny-list** and keeps the boolean, because question 2 asks who may *not* see one
> supplier — an exclusion, not a clearance matrix. Both no keeps the boolean as built.

### Phase 0 tasks

- **T0.1** ~~Write the Postgres DDL for C1, including `audit.event` with hash-chain columns and
  privilege separation per plan Decision 9~~ → **done.** Both verify criteria are met and
  recorded live-verified in `sql/README.md`: the nine files apply cleanly (now continuously —
  `test_sql_behaviour.py`'s `schema` fixture reapplies them into a freshly dropped database on
  every CI run), and `procurement_app` cannot `UPDATE`/`DELETE`/`TRUNCATE` `audit.event`
  (`test_sql_schema.py` asserts the narrow grant; `test_truncate_is_refused` exercises the
  tripwire).
- **T0.2** ~~Add `condition` to `CanonicalField` and define the condition vocabulary per parameter
  family (D-1)~~ → **done.** `condition` is on `FieldClaim`, `CanonicalField` and the `claim`
  table, and the verify criterion is
  `test_propose_commit.py::test_the_sungrow_trio_raises_no_conflict`.
- **T0.3** ~~Define the per-field tolerance table from D-2 as data, not code~~ → **done.**
  `FIELD_TOLERANCES` in `services/conflict_hitl/tolerance.py` is a dict of `FieldTolerance` rows
  keyed on the frozen contract's own keys, and `test_values_conflict.py` is table-driven against
  it — including `test_every_tolerance_key_is_a_contract_key`. ⚠️ **One gap the criterion did not
  ask about:** the contract's 18 `list[str]` keys have **no row at all** and fall to
  `DEFAULT_TOLERANCE`, which compares lists with order-sensitive `==`. That is
  [A-53](analysis.md) and needs a D-2 amendment ([open-decisions.md #9](open-decisions.md)).
- **T0.4** ~~Decide the ACL/labelling model (C7)~~ → **written as [D-15](clarifications.md), provisionally adopted 2026-08-07.** The verify criterion is met; the model is contingent on two outstanding facts recorded in that decision.
- **T0.5** ~~Freeze the canonical workbook projection format (C6)~~ → **frozen as [D-14](clarifications.md), adopted 2026-08-07.** ⚠️ The verify criterion is **not** met: no golden JSON fixture exists yet. `tests/fixtures/` deliberately shipped none until ratification; that gate has now lifted.
- **T0.6** Publish fixture sets for every contract (see below). → **partial.** `tests/fixtures/`
  ships two claim fixtures (C2, C3) and one conflict fixture (C5), each validated three ways by
  `tests/test_fixtures.py` including a byte comparison. **No C6 projection fixture** — that is
  Track 3's deliverable now the format is frozen — and **no C4 audit-envelope fixture**, which
  waits on WP-H's library.

### The decoupling technique: frozen fixtures, not running code

Each team builds against **committed fixture files** matching the frozen schemas. WP-B ships
golden claim JSON; WP-E consumes it and ships golden conflict JSON; WP-F and WP-G consume that.
**Nobody waits on anybody's service.** The fixtures are the contract made executable, and they
double as the regression suite.

---

## Phase 1 — Parallel work packages

All nine run concurrently once Phase 0 lands.

> **Two things this list does not tell you, both added 2026-09-02.**
>
> **1. The current execution plan is
> [phase-1-execution.md](phase-1-execution.md), not this section.** Phase 0's decision half
> closed on 2026-08-07 while five of the eight contracts stayed partial, so the work was
> re-cut into six tracks with team assignments (settled 2026-08-11) rather than started as nine
> whole packages. Track 0 is done; Tracks 1a, 1b, 2, 3, 4 and 5 are unstarted. Read that
> document for what to pick up; read this one for what each package ultimately owes.
>
> **2. Nothing below carries a status marker, so landed work reads as outstanding.** These
> bullets have shipped and are covered by tests:
>
> | Bullet | Where |
> |---|---|
> | **C.7** `FORCE ROW LEVEL SECURITY`, app as non-owner non-superuser | all seven content tables in `sql/`, live-tested |
> | **C.8** no ANN index, `hnsw.iterative_scan` set anyway | `sql/01`'s `ALTER DATABASE … SET`, asserted by `test_no_ann_index_exists_anywhere` |
> | **E.1** `values_conflict()` with D-2's three kinds and the rounding floor | `services/conflict_hitl`, `tests/test_values_conflict.py` |
> | **E.2** the condition-matching gate, ahead of any tolerance check | `Condition.comparable_with`, `tests/test_condition_matching.py` |
> | **E.3** the five conflict classes | `ConflictClass` and `_classify` |
> | **E.4** D-4 identity resolution, incl. the Trina split-entity case | `services/identity`, `tests/test_identity.py` |
> | **H.1** audit DDL and privilege separation | `sql/07`, live-tested |
> | **H.6** `BEFORE TRUNCATE` statement-level tripwires | `claim`, `resolution` and `audit.event` |
>
> Partly landed: **B.7** (`confidence.fuse` exists; the cold-start rule is not tuned against a
> gold set), **B.10** (`tier_for` and `requires_review` exist; there is no `threshold_for`),
> **D.4** (the guard exists at a chokepoint, but no write path routes through it because no
> write path exists), **E.5** (`ConflictVerdict.reason` explains a *verdict*; nothing generates
> `ConflictQueueEntry.explanation`), and **E.6/E.7** (the transformer and BESS *dimensions* —
> `standards_regime`, `rte_boundary` — are in the schema and gate comparison through condition
> matching; no family-specific rules beyond that).
>
> Everything else below is untouched.

### WP-A · Ingest & storage
**Depends:** C1, C3, C7

- **A.1** Content-signature router (FR-ING-01). Route by magic bytes, never extension.
- **A.2** Spreadsheet path — openpyxl/pandas direct, bypassing document parsing (plan Decision 4).
  Preserve sheet names, headers, merged cells, numeric typing (FR-ING-02).
- **A.3** Text-layer PDF path — Docling + TableFormer ACCURATE (FR-ING-03).
- **A.4** Scanned/image path — PaddleOCR-VL-1.6 on vLLM, bounding boxes retained (FR-ING-04).
  → **Trina datasheets are image-only PDFs with no text layer.** This is a tier-1 supplier, not
  an edge case. Use one as the acceptance fixture.
- **A.5** `.docx` path (FR-ING-05).
- **A.6** Per-page audit loop — zero characters, <10% of raw text count, or zero table cells on a
  detected table region → re-run on next engine. `PARSE_FAILED` regions are recorded, never
  dropped.
- **A.7** Dual-parse reconciliation on table-critical pages; emit cell-level disagreement as a
  **confidence feature**, not just a log line.
- **A.8** Document classification into the eight types (FR-ING-06).
- **A.9** Content hashing + stable IDs; re-ingest is a no-op (FR-ING-09, NFR-05). → verify: **AC-5**.
- **A.10** ACL labelling at ingest per C7.
- **A.11** Text normalisation per D-5 — NFKD, ligature folding, `–`→`-`, `℃`→`°C`, and
  **decimal-comma handling for IEC-sourced documents**. → verify: `10,5 kV` parses as 10.5, not
  105. This is the highest-risk lexical trap in the spec.

### WP-B · Extraction & confidence
**Depends:** C2, C3, C4

- **B.1** vLLM structured outputs (xgrammar) with `logprobs` enabled. → ⚠️ **`json_schema` mode,
  never Instructor's `TOOLS` mode** — tool calls do not emit logprobs, and using them throws away
  the entire confidence signal (plan Decision 7).
- **B.2** Per-category Pydantic extraction models from
  [contracts/canonical-parameters.md](contracts/canonical-parameters.md).
- **B.3** Unit normalisation per D-5. → ⚠️ **`%/°C` ≡ `%/K` requires NO conversion.** Hard-code as
  aliases; routing through a temperature converter applies +273.15 and silently destroys the value.
- **B.4** Condition extraction (D-1) — STC vs NOCT, `@30°C` vs `@40°C`, AC vs DC side, BOL vs EOL.
- **B.5** Domain plausibility rules as both feature and hard gate: `Voc > Vmp`, `Isc > Imp`,
  `Pmax ≈ Vmp × Imp ± 0.5%`, `PTC/STC ∈ [87%, 96%]`, `|γPmax| ∈ [0.15, 0.70]`, γPmax and βVoc
  negative, αIsc positive.
- **B.6** Cross-read disagreement — two structurally asymmetric extractions (field-guided and
  document-guided), scored for agreement.
- **B.7** Rule-based cold-start confidence score (D-3). **Do not implement self-reported
  confidence** (0.692 AUC, banned) **or self-consistency N=5** (0.744 AUC at 5× cost).
- **B.8** Log every human correction as a training label.
- **B.9** ⚠️ **Build the 30–50 document labelled gold set. This is task one of week one**, ahead of
  any optimisation. No public benchmark exists for this task (D-11); every accuracy figure in the
  plan is extrapolated. Seed deliberately with poor scans and unusual layouts.
- **B.10** Define `threshold_for(field_name)` — the tiered τ that WP-G consumes (see A-11).

### WP-C · Index, retrieval & access control
**Depends:** C1, C7

- **C.1** Structure-aware chunking (D/plan Decision 6). **Tables are never token-chunked.**
- **C.2** Triple table indexing — `table_full`, `table_row` (column names inlined per row),
  `table_summary`. → verify: "what is the Voc of module X" retrieves the right row.
- **C.3** Contextual retrieval — prepend document/section context before embedding.
- **C.4** Qwen3-Embedding-4B at 1024 dims via MRL truncation + renormalisation.
- **C.5** Hybrid retrieval: dense + `tsvector` + `pg_trgm`, fused with RRF (k=60).
  → verify: `"JKM610N-66HL4M-V"` retrieves `"JKM610N 66HL4M V"`.
- **C.6** bge-reranker-v2-m3 over top-50 → top-5–8.
- **C.7** `FORCE ROW LEVEL SECURITY`; app connects as non-owner, non-superuser. → verify: **AC-8**.
- **C.8** ⚠️ **No ANN index** (plan Decision 3a). Set `hnsw.iterative_scan = relaxed_order` in
  `postgresql.conf` anyway, so a future index isn't silently wrong.
- **C.9** ⚠️ **Regression test asserting `len(results) == k`** on a filtered query. Every pgvector
  filtered-search failure mode presents as a short result set — measured, a top-10 request
  returned 5 rows with no error, and 0 rows with an ACL array. **Nothing else catches this.**

### WP-D · Web enrichment
**Depends:** C2, C3, C4

- **D.1** Gap-triggered query planning (FR-WEB-01).
- **D.2** Tag every result `web_supplement` with URL, title, timestamp; log the query (FR-WEB-02).
- **D.3** Source-authority capture and ordering (FR-WEB-05).
- **D.4** ⚠️ Route every write through `assert_no_autonomous_overwrite`. → verify: **AC-2**.
- **D.5** CEC cross-check integration (D-8) — weekly pull of the four XLSX exports, surrogate ID,
  alias seeding from the `Notes` column. → ⚠️ CEC is **not** an authority for utility-scale BESS.
  → ⚠️ Do **not** use pvlib's bundled CEC data: frozen at 2019, **zero modules ≥600 W** (D-8a).

### WP-E · Conflict detection
**Depends:** C2, C5 · *Most parallelisable — a pure function, fully fixture-testable.*

- **E.1** `values_conflict()` per the D-2 three-kind model with the rounding floor.
- **E.2** Condition-matching gate — **mismatched conditions are not a conflict, they are not a
  comparison** (D-1). This gate runs before any tolerance check.
- **E.3** The five conflict classes (FR-HITL-01).
- **E.3a** ⚠️ **If any ensemble is ever used here, aggregate by UNION, never by vote.** Stage 3's
  exit threshold is *100% of injected conflicts surfaced*. A 2-of-3 vote that suppresses a real
  conflict is a spec violation, not a false positive saved. Written down now because the verifier
  pattern is a natural thing to reach for later.
- **E.4** Identity resolution per D-4 — four stages, `(manufacturer, token)`-keyed suffix rules,
  electrical corroboration. → ⚠️ verify with the **Trina split-entity case**: bins 635–725 W under
  `Trina Solar Co.,Ltd`, bins 730/735/740 under `Trina Solar`. Looking up
  (`Trina Solar`, `TSM-700NEG21C.20`) must not return empty.
- **E.5** Generated conflict explanations (FR-HITL-03).
- **E.6** Transformer-specific gates per D-6: standards-regime detection (IEEE vs IEC) before any
  comparison of MVA, %Z or losses; `Dyn1` vs `Dyn11` treated as **incompatible, not equivalent**.
- **E.7** BESS boundary gate per D-7 — RTE and energy comparisons across differing boundaries are
  *"requires boundary normalisation"*, not a numeric conflict.

### WP-F · HITL queue service & review UI
**Depends:** C5, C8

- **F.1** Conflict table with lease-based claiming (`FOR UPDATE SKIP LOCKED`, 15-min lease).
- **F.2** The five resolution actions. `keep_sor` writes an explicit resolution — *not* a no-op, so
  "we looked and chose the contract value" stays distinguishable from "nobody looked".
- **F.3** `request_more_web_search` reopen cap at 3, then force a terminal decision.
- **F.4** Lease sweeper. **Conflicts themselves never expire** (D-12c) — they age, and age is a
  reported metric.
- **F.5** Review UI. ⚠️ **You will build this regardless** — no generic approval page serves
  provenance-carrying extracted-value review. This removes the "free UI" argument for every
  orchestration framework considered.
- **F.6** Implement D-10: Excel is read-only output; resolution happens in the application.

### WP-G · Workbook composition & determinism
**Depends:** C6 · *Fully decoupled — build against the golden projection from day one.*

- **G.1** Canonical sorted-key JSON projection; floats via `repr()`. **This is the hashed artifact
  of record**, not the xlsx — `%.16g` maps `0.1+0.2` and `0.3` to identical bytes, so a workbook
  hash cannot distinguish two genuinely different stored numbers.
- **G.2** All 13 tabs (FR-OUT-02). → verify: **AC-3**.
- **G.3** Hidden parallel state columns for provenance. → ⚠️ **no blank column between value and
  state blocks**, and `auto_filter.ref` **must span the hidden columns**. Both fail silently on
  first sort. Assert both in the generator.
- **G.4** Three orthogonal visual channels — fill=origin, font=confidence, border=conflict
  (plan Decision 8b). → verify: greyscale separation and WCAG AA contrast.
- **G.5** Deterministic render — `ExcelWriter` direct (bypassing `save_workbook`, which re-stamps
  `modified = now()` *after* you set it), zip normalisation at epoch 1980-01-01 **12:00**.
  → ⚠️ `ZipFile(compresslevel=)` is **silently ignored** with a hand-built `ZipInfo`; set
  `zi._compresslevel`. → verify: **AC-7**, with `sleep(1.1)` between the two runs.
- **G.6** ⚠️ **GATING: open the generated workbook in real desktop Excel and LibreOffice.** The
  determinism recipe was validated only by openpyxl round-trip and OPC structural checks. Test
  `[Content_Types].xml`-first ordering and the 1980 timestamps before this ships. A verified
  fallback exists (post-save `core.xml` rewrite) — see [analysis.md A-9](analysis.md).
- **G.7** Conflicts and Sources tab layouts with bidirectional `MATCH`-based navigation.
- **G.8** Completeness manifest listing every unresolved conflict.

### WP-H · Audit log
**Depends:** C1, C4 · *Ships a library the other packages call. Must land first.*

- **H.1** DDL + privilege separation (`NOLOGIN` owner role, app gets `INSERT, SELECT` only).
- **H.2** RFC 8785 canonicalisation **in Python, not SQL** — `jsonb` normalises key order but
  preserves numeric formatting, so `1.0` and `1.00` stay textually distinct.
- **H.3** Per-document hash chaining (`stream = 'doc:1234'`).
- **H.4** ⚠️ **Advisory lock as its own statement before the INSERT** — a lock *inside* the trigger
  does not work, because the statement snapshot is taken before the trigger acquires it. Measured:
  8 concurrent writers produced **42 silent forks** without this. Add `UNIQUE(stream, prev_hash)`
  so any remaining fork is loud.
- **H.5** Chain verification CLI.
- **H.6** `BEFORE TRUNCATE` statement-level trigger as a secondary tripwire — **not** the boundary.
  Document that `session_replication_role='replica'` bypasses triggers entirely and leaves no DDL
  trace.

### WP-I · Runner & stage state machine
**Depends:** C8

- **I.1** Job table + `FOR UPDATE SKIP LOCKED` worker loop (plan Decision 1).
- **I.2** Per-stage retry with backoff; **every stage must be independently idempotent** — retries
  are at-least-once and do not undo side effects.
- **I.3** Compose-time gate: query for unresolved conflicts above severity, overridable with a
  recorded `--accept-incomplete` decision (plan Decision 2). **No blocking interrupt.**
- **I.4** Poison-message handling and quarantine.
- **I.5** Observability; verify NFR-06 and NFR-07 against a real corpus.

---

## Genuine sequential dependencies

These cannot be parallelised away. Plan for them rather than discovering them.

1. **Phase 0 precedes all implementation.** The only true serialisation point.
2. **C7 (ACL model) blocks both WP-A and WP-C** — opposite ends of the pipeline, one decision.
3. **WP-H ships its library before any stage emits events.** Changing the hashed field set later
   invalidates every existing chain.
4. **Real extraction output is needed to *tune* conflict detection, not to *build* it.** WP-E
   builds against fixtures on day one; only its thresholds wait on WP-B. **Sequence the tuning,
   not the build.**
5. **Real conflicts are needed to *validate* the review UI**, same shape. WP-F builds against
   synthetic conflicts; usability review waits on WP-E.
6. **The determinism golden hash can only be locked once the workbook's shape settles.** WP-G's
   normalisation layer is buildable immediately; G.6 is the gate.

---

## Acceptance criteria ownership

**Status words are [requirements-traceability.md](../../docs/requirements-traceability.md)'s
closed vocabulary**, not a third set. This table used `passing` / `partial` / `☐` and disagreed
with both status documents on four of eight rows — AC-2 read `passing` where the guard is
unit-level and nothing drives a contradiction to a queue entry, and AC-5, AC-7 and AC-8 read `☐`
where a live-tested store defence exists. A third vocabulary is how that hides: a reader
comparing two documents sees a disagreement, a reader comparing three assumes a mapping.

| AC | Owner | Status | Where it stands |
|---|---|---|---|
| AC-1 scanned spec sheet → fields with provenance, low confidence to review | WP-A + WP-B | open | needs the corpus and an extractor; nothing reaches one |
| AC-2 web contradiction raises conflict, record unchanged | WP-D + WP-E | partial | `assert_no_autonomous_overwrite` and `test_a_web_claim_contradicting_the_record_is_queued`; no test drives it on to a queue entry, because nothing builds one |
| AC-3 all 13 tabs with conditional formatting | WP-G | partial | `expected_tabs()` and `flags_for()`; no workbook, so no formatting |
| AC-4 every cell resolves to a source | WP-G | enforced | the `SourceRef` validator, at model level |
| AC-5 re-ingest creates no duplicates | WP-A | partial | `UNIQUE (content_hash)` live-tested by `test_a_duplicate_content_hash_is_refused`; the ingest caller does not exist |
| AC-6 TRD against correct voltage-class limit; tax status per supplier | WP-B + WP-G | open | no home in the code yet |
| AC-7 byte-identical regeneration | WP-G | partial | `normalize_archive()` at archive level; gated on G.6, and there is no writer to regenerate |
| AC-8 unclear user cannot influence retrieved results | WP-C | partial | RLS on seven tables, eight live assertions led by `test_claims_do_not_leak_a_restricted_documents_values`; no retrieval path exists to filter |

---

## Suggested team allocation

| Team | Packages | Rationale |
|---|---|---|
| 1 | Phase 0, then WP-H, WP-I | Owns the contracts, so owns the substrate everyone builds on |
| 2 | WP-A | Largest surface; parser router is core IP |
| 3 | WP-B | Deepest domain work; owns the gold set |
| 4 | WP-C | Self-contained; owns the pgvector findings |
| 5 | WP-D + WP-E | Both pure-ish functions over claims; share the tolerance table |
| 6 | WP-F + WP-G | Both consume the canonical projection; share the reviewer's mental model |
