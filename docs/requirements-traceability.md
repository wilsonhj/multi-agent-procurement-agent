# Requirements traceability

Maps every requirement from the FRD and TRS to where it is addressed in the codebase.

Status values:
- **enforced** — implemented **and covered by a test**
- **partial** — some of the cited artifact is tested, some is not
- **declared** — the type, signature or contract exists; behaviour is not implemented
- **open** — no home in the code yet

> **Audit, 2026-07-28.** Fourteen rows changed status after review, **ten** of them demoted from
> **enforced** with no test covering the cited artifact — including NFR-04, whose entire citation
> is a module no test imports. Three cited symbols had been deleted outright
> (`orchestrator.INTERRUPTING_STAGES`, `config.hitl_confidence_threshold`). `enforced` in this
> table means a test exists, not that the author believed the code was right.
>
> The counts in an earlier version of this note ("eleven" and "eight") were both wrong; they are
> recomputed from the diff above.
>
> A closed vocabulary a reader can trust matters more here than a flattering count:
> `enforced` promises that a regression test protects the requirement, and if that is
> not true the guarantee can be lost in a refactor with nothing going red.

> **Audit, 2026-08-04. The same defect, sign reversed.** All **48 requirement rows and 8
> acceptance-criterion rows** were re-read against both the cited artifact and the cited test.
> **Ten rows changed status, all upward.** Nothing was demoted, and every file path, symbol and
> test name in the table was checked to exist — none did not.
>
> Every remaining row's citation was re-read too. **Two carried a claim that had become false** —
> FR-3 called `unresolved_conflicts()` untested, and FR-HITL-06 said `sql/`'s append-only half was
> "verified against a live PostgreSQL", which was true when written and is now weaker than the
> truth. The rest were tightened to name the test, or the `NotImplementedError`, that decides
> them. Only the ten status changes are counted here, because that is the number a reader can
> recompute from the diff — the 2026-07-28 note shipped two counts it could not.
>
> The 2026-07-28 audit and [A-16](../specs/001-procurement-agent/analysis.md) corrected rows
> claiming *more* coverage than existed. This one corrects the opposite: `sql/` and its live suite
> landed with the CI PR (#25), and `services/claims`, `services/identity`, `services/confidence`
> and `services/conflict_hitl/severity.py` landed before it, and the rows those merges answered
> were never raised. NFR-02 still said "store not yet built" beside a nine-file schema whose
> append-only tripwires are exercised against a running PostgreSQL on every pull request.
>
> An understating row is the cheaper error, but it corrodes the same vocabulary. A reader who
> finds a `declared` row with a passing regression test behind it stops trusting the column in
> both directions, and the next person to weaken a guarantee finds a table nobody reads.
>
> **Two rows were checked and deliberately left `declared` where a raise looked available**, named
> here because "no change" is the finding least likely to be believed. FR-RAG-02 and FR-RAG-03
> gained a real storage home in `sql/03_chunk.sql`, and one live test touches it — but
> `test_no_ann_index_exists_anywhere` asserts plan Decision 3a's **reversal** of FR-RAG-02, not
> FR-RAG-02. Counting a test that asserts the opposite of a requirement as coverage of that
> requirement would be the 2026-07-28 defect wearing a new hat.

### Live-database coverage, and what it is worth

`tests/test_sql_behaviour.py` runs its assertions against a real PostgreSQL. It is `skipif` on
`PROCUREMENT_TEST_DSN`, so it **skips silently in a default local `pytest`** — the 23 skips in a
clean run are this file — and executes only in the `sql` job of `.github/workflows/ci.yml`, which
greps the output and fails the job if the suite skipped rather than ran.

The rule applied uniformly below:

- A row it covers is **not `declared`**. A test that goes red on a real server when the behaviour
  is broken is a regression test, whichever host runs it.
- A row it covers is **not `enforced` on that basis alone**, because it proves the *schema*
  behaves, not that any Python path uses the schema — and every row in this position still has an
  unimplemented application half. Those rows are `partial`, and each names which half is
  live-tested and which is missing.

`tests/test_sql_schema.py` is **structural**: regex assertions over DDL text. It proves that a fix
cannot be deleted silently; it proves nothing about behaviour, and it is cited here on that
narrower basis only. The division is not theoretical. Measured on this branch by reintroducing
four closed defects one at a time and running each suite:

| defect reintroduced | `test_sql_schema.py` | `test_sql_behaviour.py` |
|---|---|---|
| `UNIQUE (content_hash)` dropped from `02_document.sql` | **green** | red |
| `claim`'s confidentiality policy widened to `USING (true)` | red | red |
| `resolution`'s statement-level TRUNCATE tripwire deleted | red | red |
| `GRANT procurement_ingest TO procurement_app` added | **green** | red |

Two of the four are invisible to the structural suite. That is why a `sql/` citation below names
the behavioural test wherever one exists, and says so explicitly where only the structural one
does.

---

## Functional requirements — FRD

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-1 | Multi-format intake | `services/ingestion.detect_content_signature` — raises `NotImplementedError`, no test | declared |
| FR-2 | Document understanding | `schema.DocumentType`, `services/ingestion.classify_document` — the latter raises `NotImplementedError` | declared |
| FR-3 | Fact extraction into a consistent structure | The *structure* is covered end to end: `schema.CanonicalField` (+ `schema.Condition`, see [D-1](../specs/001-procurement-agent/clarifications.md)), `schema.ComponentInstance.ordering_key()` (`tests/test_canonical_ordering.py`) and `unresolved_conflicts()` (`test_unresolved_conflicts_reads_every_conditioned_value`, `test_a_clean_store_has_no_unresolved_conflicts`) — the last of these was cited as untested and has been covered since the Phase 0 substrate landed. `services/claims.project` builds the structure from claims and is tested. The *extraction* is absent: `services/ingestion.ingest` raises `NotImplementedError`, so nothing produces a claim from a document | partial |
| FR-4 | Web supplement, never silent overwrite | `services/conflict_hitl.assert_no_autonomous_overwrite` (`tests/test_source_of_record_rule.py`) | enforced |
| FR-5 | Conflict surfacing, no auto-resolution | guard, `comparison_pairs` and `values_conflict` enforced; `services/claims.project` now derives `ConflictStatus.OPEN` from disagreeing claims without arbitrating them (`test_two_record_claims_that_disagree_are_not_arbitrated`, `test_a_web_claim_contradicting_the_record_is_queued`). Nothing constructs a `ConflictQueueEntry` in production yet — grep confirms the only non-test uses are type annotations in `orchestrator` | partial |
| FR-6 | One workbook, tab per category, flagged | `schema.WorkbookTab` tested (`test_workbook_has_thirteen_tabs`, `test_first_eight_tabs_are_the_category_tabs`) and `services/output.flags_for` tested; `services/output.write_workbook` raises `NotImplementedError`, so no workbook exists to carry either | partial |
| FR-7 | Source traceability, no unsourced values | `schema.SourceRef` validator (`test_source_ref_requires_a_source`) | enforced |
| FR-8 | Decision authority stays human | `orchestrator.compose_gate_blocks` / `blocking_conflicts`, `schema.Severity` (`tests/test_compose_gate.py`) | enforced |

## Functional requirements — TRS

### Ingestion & extraction

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-ING-01 | Accept 10 formats, route by content signature | `services/ingestion.detect_content_signature`, `ports.ParserPort.supports` | declared |
| FR-ING-02 | Spreadsheets: sheets, headers, merged cells, typing | `ports.ParserPort` | open |
| FR-ING-03 | Text-layer PDFs: layout-aware, page numbers | `ports.ParsedElement` | declared |
| FR-ING-04 | Scanned PDFs/images: OCR, bounding boxes | `ports.OCRPort`, `schema.SourceRef.bounding_box` — both exist, neither is exercised by any test | declared |
| FR-ING-05 | Word: paragraphs, tables, footnotes | `ports.ParserPort` | open |
| FR-ING-06 | Classify into eight document types | `schema.DocumentType`; `classify_document` raises NotImplementedError | declared |
| FR-ING-07 | Schema-constrained extraction with confidence + source pointer | `ports.LLMPort.extract`, `schema.CanonicalField` | declared |
| FR-ING-08 | Normalize units, retain verbatim | **Retention is covered, normalisation is not.** `verbatim_value` survives the claim-to-canonical projection as provenance rather than as part of the value (`test_the_same_figure_printed_twice_may_differ_in_source_text`), and a unit mismatch is refused rather than absorbed (`test_a_unit_mismatch_is_not_agreement`, `test_a_unit_mismatch_is_never_resolved_by_tolerance`). `services/ingestion.normalize_unit` raises `NotImplementedError` | partial |
| FR-ING-09 | Stable IDs, content hash, dedup | The dedup half is live-tested: `sql/02_document.sql`'s `UNIQUE (content_hash)` refuses a second row (`tests/test_sql_behaviour.py::test_a_duplicate_content_hash_is_refused`), and the structural suite is blind to its removal — see the table above. `schema.SourceDocument.content_hash` carries the key; the stable-ID and timestamp half has no test | partial |
| FR-ING-10 | Sub-threshold confidence routes to HITL | `services/confidence.fuse` produces the score and `requires_review` routes it; Tier A is a gate that no score can pass (`test_tier_a_ignores_the_threshold_entirely`). The threshold itself is still uncalibrated — D-3 reads it off a risk-coverage curve on a labelled set that does not exist yet — and the route from the gate to the workbook is a recorded gap, not a wired path: `confidence.UNIMPLEMENTED_REVIEW_ROUTING` and `test_the_gap_between_the_gate_and_the_workbook_is_named` | partial |

### Indexing, retrieval & RAG

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-RAG-01 | Structure-aware chunking, 512 tokens, 0–10% overlap (revised from the TRS by plan Decision 6) | `config.chunk_size_tokens` bound enforced and tested (`tests/test_settings_bounds.py`); `services/indexing.chunk` still raises `NotImplementedError` | partial |
| FR-RAG-02 | ANN index, cosine, full metadata set | `ports.VectorStorePort`; `sql/03_chunk.sql` stores the embedding and FR-RAG-02's metadata list on the chunk row. **Left `declared` on purpose:** no test asserts that metadata set, and the one live test touching the table (`test_no_ann_index_exists_anywhere`) asserts Decision 3a's reversal of the ANN mandate — the opposite of the requirement, so it is not coverage of it | declared |
| FR-RAG-03 | Hybrid retrieval, rerank, tier stays distinguishable | `ports.RetrievedChunk.source_tier`; `sql/03_chunk.sql` carries `source_tier NOT NULL` with a two-value CHECK and the `tsvector`/`pg_trgm` indexes Decision 3b substitutes for BM25. No test asserts either, and `services/retrieval.retrieve` raises `NotImplementedError` | declared |
| FR-RAG-04 | Retrieved context only, cite source, "insufficient evidence" | `INSUFFICIENT_EVIDENCE` enforced (`test_insufficient_evidence_is_flagged_not_silently_dropped`); `ports.LLMPort.extract` returning `None` untested (no test imports `ports`) | partial |
| FR-RAG-05 | Incremental add/update/delete by stable ID | `ports.VectorStorePort.upsert` / `.delete` | declared |

### Web search

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-WEB-01 | Search only on gap or user request | `services/web_search.search_for_gap` — raises `NotImplementedError` | declared |
| FR-WEB-02 | Tag `web_supplement` + URL, title, timestamp; log queries | tier tagging enforced; `SourceRef.retrieved_at` optional and still never asserted by any test, query logging has no code | partial |
| FR-WEB-03 | Fill empty fields only, never overwrite | `assert_no_autonomous_overwrite` (`tests/test_source_of_record_rule.py`) | enforced |
| FR-WEB-04 | Divergence beyond tolerance raises a conflict | `services/conflict_hitl.values_conflict` implemented against `conflict_hitl/tolerance.FIELD_TOLERANCES`, the [D-2](../specs/001-procurement-agent/clarifications.md) table transcribed (`tests/test_values_conflict.py`) | enforced |
| FR-WEB-05 | Prefer and record source authority | `services/web_search.SOURCE_AUTHORITY_ORDER` — no test reads it. (`SourceRef.source_authority` *is* exercised, but by `tolerance`'s CEC-list discriminator, which is a different claim) | declared |

### Conflict detection & HITL

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-HITL-01 | Five conflict classes | All five `schema.ConflictClass` members are now produced by `conflict_hitl._classify` / `values_conflict` and asserted individually — `RECORD_VS_WEB`, `INTER_DOCUMENT` and `INTRA_DOCUMENT` in `test_the_conflict_class_is_derived_from_the_candidates`, `TEMPORAL` in `test_an_edition_difference_is_temporal_not_a_string_mismatch`, `UNIT_NORMALIZATION` in `test_a_unit_mismatch_is_never_resolved_by_tolerance`. Still **no test asserts the count**, so a sixth class could be added with nothing going red | partial |
| FR-HITL-02 | Never auto-arbitrate web vs record | `assert_no_autonomous_overwrite` (`tests/test_source_of_record_rule.py`) | enforced |
| FR-HITL-03 | Queue entry payload | `schema.ConflictQueueEntry` shape enforced (severity required, candidates carry `condition`, `component_category` is the closed vocabulary); `conflict_hitl.conflict_groupings` fixes what an entry may hold and is tested (`test_a_queue_entry_never_holds_two_incomparable_candidates`, `test_the_bridging_candidate_appears_in_two_entries`), and `claims.FieldClaim.as_candidate()` builds the candidate half with its provenance stamped (`test_the_queue_entry_carries_it_too`). No production path builds an *entry* | partial |
| FR-HITL-04 | Five resolution actions | `schema.ResolutionAction` — no test asserts the count. `sql/06_resolution.sql` pins the same five strings in a CHECK constraint, but no test inserts a resolution row, so neither list is protected | declared |
| FR-HITL-05 | Unresolved and low-confidence flagged, never dropped | `services/output.flags_for` computes all four states and is tested; `ComponentInstance.unresolved_conflicts()` reads every conditioned value rather than the first (`test_unresolved_conflicts_reads_every_conditioned_value` — a mutation of the inner loop previously survived the whole suite) and `orchestrator.blocking_conflicts` names the blockers for the completeness manifest. `write_workbook` still raises `NotImplementedError`, so nothing puts a flag in front of a human | partial |
| FR-HITL-06 | Immutable decision log | `CanonicalField`'s validator runs at construction, at assignment in both directions, and on every update route: `model_copy(update=...)` raises, `evolve(...)` revalidates, `model_construct` runs the invariant on the finished object, and `__setstate__`/`__deepcopy__` revalidate so a corrupt object cannot cross a pickle or copy boundary silently (`test_resolution_invariant_survives_assignment`, `test_a_resolved_field_cannot_have_its_resolution_cleared`, `test_model_copy_update_is_refused_on_a_canonical_field`, `test_evolve_reruns_validation_and_still_forbids_the_state`, `tests/test_resolution_immutability.py`). Overwriting a recorded `Resolution` — which every validator passes, because the resulting state is legal — is refused by `__setattr__` and by `evolve` (`test_a_recorded_resolution_cannot_be_replaced`, `test_evolve_cannot_replace_a_recorded_resolution`); `ConflictQueueEntry` is frozen and `Resolution`'s own fields are frozen (`test_resolution_fields_are_frozen`). **Exactly one route remains open, and it cannot be closed:** writing the instance `__dict__` directly — `field.__dict__["conflict_status"] = RESOLVED`, or the same write spelled `object.__setattr__(field, ...)`, which is one route in two spellings and not two. No Python object can defend against it. The shallow-freeze gap is unchanged: `ConflictQueueEntry.candidates` is a list and is mutable in place. Persisted, tamper-evident storage is NFR-02; `sql/` implements the append-only half (no UPDATE/DELETE grant on `resolution`, plus row-level and statement-level tripwires) and it is now **live-tested rather than only hand-verified**: `test_sql_behaviour.py::test_truncate_is_refused[public.resolution]` and `test_the_row_level_tripwire_still_raises` | partial |

### Output

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-OUT-01 | Tab per category, suppliers rows or columns | `config.suppliers_as_rows` — a bool with no bound and no test | declared |
| FR-OUT-02 | Exactly 13 tabs | `schema.WorkbookTab` (`test_workbook_has_thirteen_tabs`) | enforced |
| FR-OUT-03 | Per-cell provenance | `services/output.write_workbook` | declared |
| FR-OUT-04 | Four conditional-formatting states | `services/output.flags_for` enforced; no test exercises the formatting itself, and the writer that would apply it is unimplemented | partial |
| FR-OUT-05 | Certification/standards columns per category | [contracts/canonical-parameters.md](../specs/001-procurement-agent/contracts/canonical-parameters.md) | declared |
| FR-OUT-06 | Canonical units, deterministic regeneration | **The determinism machinery is implemented and tested; the writer it would wrap is not.** `services/output.normalize_archive` strips all five sources of run-to-run variance and `tests/test_workbook_determinism.py` pins them (byte-identity across a second boundary, idempotence, pinned compression level, forced `create_system`). `services/claims.project` is a pure function of the claim set (`test_the_projection_does_not_depend_on_completion_order`) and `ComponentInstance.ordering_key()`, filled by `services/identity.identity_keys`, supplies the total row order AC-7 needs. **D-14 (adopted 2026-08-07) freezes the canonical projection** — the bytes, `encode_value()`, policy inside the hash, and a store-derived `generated_on` that resolves the FR-OUT-06/AC-7 tension recorded as A-48. No projection function and no golden fixture exist yet, and `write_workbook` raises `NotImplementedError`, and the canonical-units half is FR-ING-08's unimplemented `normalize_unit` | partial |

---

## Non-functional requirements

| ID | Requirement | Where | Status |
|---|---|---|---|
| NFR-01 | Traceability, no unsourced values | `schema.SourceRef` validator (`test_source_ref_requires_a_source`) | enforced |
| NFR-02 | Immutable audit log | **The store is built.** The previous "store not yet built" predated `sql/`. `sql/07_audit_event.sql` implements the hash chain and `sql/04_claim.sql` / `sql/06_resolution.sql` the append-only tables, all three with row-level and statement-level tripwires, and the chain is walked against a live server: `test_a_valid_chain_appends`, `test_a_fabricated_parent_is_refused`, `test_a_second_disconnected_root_is_refused`, `test_a_chain_loop_is_refused`, `test_truncate_is_refused` (all three tables), `test_the_row_level_tripwire_still_raises`. `schema.Resolution` is frozen and tested. **D-13 (adopted 2026-08-07) settles the canonicalisation and the preimage** — RFC 8785, one JCS object carrying `"v": 1`, SHA-256 — so the bytes the chain covers are defined and `sql/07`'s caller-sequence comment now matches. Still not `enforced`: nothing in Python writes an audit event, so no application path is protected — only the schema is | partial |
| NFR-03 | Access control at retrieval time; confidential path self-hosted | **RLS is implemented on all seven tables that hold document content**, with `FORCE` so the owner is not exempt, an `app.allow_restricted` entitlement GUC, and a separate `procurement_ingest` role so making a row *more* restricted is not the failing direction. Structural: `test_every_table_holding_document_content_forces_rls`, `test_every_such_table_has_a_confidentiality_select_policy` (both ×7). Live: `test_the_app_role_cannot_declassify_rows_it_cannot_read`, `test_the_write_policy_alone_protects_an_unreadable_row`, `test_the_document_write_policy_alone_protects_an_unreadable_row`, `test_the_app_role_cannot_delete_rows_it_cannot_read`, `test_a_chunk_inherits_its_parent_documents_restriction`, `test_restriction_can_only_increase`, `test_claims_do_not_leak_a_restricted_documents_values`, `test_the_app_role_cannot_escalate_to_the_ingest_role`. Not `enforced`: `VectorStorePort.search(allowed_document_ids=...)` has no adapter and `services/retrieval.retrieve` raises `NotImplementedError`, so the *retrieval-time* clause the TRS actually writes is unexercised. Self-hosted endpoints remain a `.env.example` convention with no check  **D-15 (adopted 2026-08-07, provisional) ratifies this label model** as C7's answer — one document-level label, per-principal clearance from the OIDC subject, labelling at ingest failing closed. Provisional because two facts are outstanding, not two preferences. | partial |
| NFR-04 | Six swap points behind stable interfaces | `ports/` — all six Protocols; **no test imports `ports` at all** (re-verified 2026-08-04) | declared |
| NFR-05 | Idempotent re-ingest | `schema.SourceDocument.content_hash` plus `sql/02_document.sql`'s `UNIQUE (content_hash)`, live-tested by `test_a_duplicate_content_hash_is_refused` and by `test_a_restricted_document_can_be_ingested_idempotently`, which runs the documented `ON CONFLICT (content_hash) DO NOTHING` idiom as the ingest role. Not `enforced`: `services/ingestion.ingest` raises `NotImplementedError`, so nothing re-ingests | partial |
| NFR-06 | Hundreds of documents | — | open |
| NFR-07 | Batch ingestion; interactive ops in seconds-to-minutes | `orchestrator` docstring | open |
| NFR-08 | Human retains final authority | `orchestrator.compose_gate_blocks` / `blocking_conflicts`, `schema.Severity` (`tests/test_compose_gate.py`) | enforced |

---

## Acceptance criteria

| ID | Criterion | Test | Status |
|---|---|---|---|
| AC-1 | Scanned spec sheet extracts fields with provenance, low confidence to HITL | — | open |
| AC-2 | Web contradiction raises conflict; record value unchanged | `tests/test_source_of_record_rule.py` calls `assert_no_autonomous_overwrite` directly, and `test_propose_commit.py::test_a_web_claim_contradicting_the_record_is_queued` now drives a web contradiction through the projection to `ConflictStatus.OPEN` with the record still supplying the value — the "record value unchanged" half. `test_the_record_supplies_the_value_even_when_the_web_looks_better` pins it where the web claim wins on confidence and filename. No test drives it on to a queue entry, because nothing builds one | partial |
| AC-3 | All 13 tabs with conditional formatting | `tests/test_schema_invariants.py`, `tests/test_output_flags.py` | partial |
| AC-4 | Every cell resolves to a source | `tests/test_schema_invariants.py::test_source_ref_requires_a_source` | enforced |
| AC-5 | Re-ingest creates no duplicates | `tests/test_sql_behaviour.py::test_a_duplicate_content_hash_is_refused` inserts a second row with an existing `content_hash` against a live server and asserts the `UniqueViolation`; `test_a_restricted_document_can_be_ingested_idempotently` runs the `ON CONFLICT DO NOTHING` idiom as the ingest role. **Verified non-vacuous:** changing the second insert to a distinct hash turns the test red, and removing the `UNIQUE` constraint takes the whole file down while `test_sql_schema.py` stays green. Not `enforced`: this covers the store, and `services/ingestion.ingest` — the thing that would re-ingest — raises `NotImplementedError` | partial |
| AC-6 | Inverter tab reports TRD against correct IEEE 2800 limit; tab 13 reports BABA/ITC/FEOC | — | open |
| AC-7 | Two generations from an unchanged store are byte-identical | `tests/test_workbook_determinism.py` covers `normalize_archive` at archive level; `write_workbook` raises `NotImplementedError`, so no complete workbook is regenerated and the desktop Excel/LibreOffice gate (task G.6) is unrun | partial |
| AC-8 | An uncleared user cannot influence any retrieved result | See NFR-03 for the full citation. RLS on seven tables with `FORCE`, an entitlement GUC and a separate ingest role, live-tested by eight assertions in `tests/test_sql_behaviour.py` — the load-bearing one is `test_claims_do_not_leak_a_restricted_documents_values`, which fails when and only when `claim`'s confidentiality policy is widened to `USING (true)`. `ports.VectorStorePort.search(allowed_document_ids=...)` still only declares the parameter, and no test imports `ports`. **Not `enforced`, and the reason has changed:** [A-28](../specs/001-procurement-agent/analysis.md) withheld it because CI did not execute the DDL, which #25 fixed. It is withheld now because there is no retrieval path at all — a user cannot influence a retrieved result today because nothing retrieves | partial |

AC-7 and AC-8 were absent from this table while `spec.md` listed eight criteria. They are the
two the spec itself flags as "the kind of property that silently rots without a test", so
omitting them from the traceability record was the specific failure they were added to prevent.

AC-3 is partial: tab identity and cell-state logic are tested (`expected_tabs()` is pinned by
`test_expected_tabs_returns_all_thirteen_in_order`), workbook generation is not.
AC-1 and AC-6 need the ingestion path and a labelled corpus — Stage 1 in the
[README build plan](../README.md#build-plan). AC-5 is no longer in that group: the store-level
invariant it names is live-tested, and only the ingest path that would exercise it is missing.
[`tasks.md`](../specs/001-procurement-agent/tasks.md) assigns owners per criterion and is the
list to check before claiming one.
