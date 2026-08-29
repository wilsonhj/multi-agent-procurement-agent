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

> **NFR-04, 2026-08-12.** **One row moved**, `declared` → `partial`, on the first tests that import
> `ports` — Track 4 of [`phase-1-execution.md`](../specs/001-procurement-agent/phase-1-execution.md),
> implementing [ADR-001](decisions/ADR-001-cross-repo-pattern-adoption.md) decision 2.
>
> Two other rows, FR-RAG-04 and AC-8, had citations that asserted "no test imports `ports`", which
> this change falsified. Both were corrected and **neither status moved.** That is the finding
> rather than an omission: a conformance suite whose only subjects are in-memory references proves
> the Protocols are *expressible*, and both of those rows are withheld on the absence of a retrieval
> path, which is untouched. Moving them on the strength of a reference adapter would be the
> 2026-07-28 defect — counting a test that does not cover the requirement as coverage of it.
>
> **Reconciled 2026-08-29.** `docs/current-state.md` now agrees: AC-8 is partial because forced
> RLS and the in-memory access-filtering contract are tested, while the production retrieval path
> and vendor adapter remain absent.

### Live-database coverage, and what it is worth

`tests/test_sql_behaviour.py` and `tests/test_audit_live.py` run their assertions against a real
PostgreSQL. Both are `skipif` on `PROCUREMENT_TEST_DSN`, so they **skip silently in a default
local `pytest`**: 32 schema-behaviour tests and 9 audit-chain tests, accounting for all 41 skips
in the current baseline. The `sql` job in `.github/workflows/ci.yml` runs the files separately,
greps each output, and fails if either suite skipped rather than ran.

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
| FR-3 | Fact extraction into a consistent structure | The structure is covered end to end by `CanonicalField`, `Condition`, `services.claims.project`, canonical ordering, and unresolved-conflict tests. `services.vertical_slice.run_sanitized_pv_csv` now produces immutable claims and a canonical component from a trusted fixture (`test_sanitized_csv_reaches_canonical_component_and_conflict_queue`). General extraction remains absent: `services.ingestion.ingest` raises `NotImplementedError`, and no native document or model adapter produces a claim | partial |
| FR-4 | Web supplement, never silent overwrite | `services/conflict_hitl.assert_no_autonomous_overwrite` (`tests/test_source_of_record_rule.py`) | enforced |
| FR-5 | Conflict surfacing, no auto-resolution | The guard, `comparison_pairs`, and `values_conflict` are enforced; `services.claims.project` derives `ConflictStatus.OPEN` without arbitrating. The sanitized-PV slice constructs a high-severity `ConflictQueueEntry` and leaves the canonical source value unchanged until an explicit human resolution. General ingestion/web paths and a durable queue service remain absent | partial |
| FR-6 | One workbook, tab per category, flagged | `schema.WorkbookTab`, `services.output.flags_for`, and the initial `write_workbook` path are tested. The sanitized-PV slice emits all thirteen tabs with provenance, flags, and an open-item row. The advanced state-column/navigation and desktop application gates remain | partial |
| FR-7 | Source traceability, no unsourced values | `schema.SourceRef` validator (`test_source_ref_requires_a_source`) | enforced |
| FR-8 | Decision authority stays human | `orchestrator.compose_gate_blocks` / `blocking_conflicts`, `schema.Severity` (`tests/test_compose_gate.py`) | enforced |

## Functional requirements — TRS

### Ingestion & extraction

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-ING-01 | Accept 10 formats, route by content signature | `services/ingestion.detect_content_signature`, `ports.ParserPort.supports` | declared |
| FR-ING-02 | Spreadsheets: sheets, headers, merged cells, typing | `ports.ParserPort` | open |
| FR-ING-03 | Text-layer PDFs: layout-aware, page numbers | `ports.ParsedElement` | declared |
| FR-ING-04 | Scanned PDFs/images: OCR, bounding boxes | `ports.OCRPort` has a tested in-memory reference for routing, recognition, page numbers, determinism, and declared table recovery. The bounding-box half remains only a `SourceRef` field: `ParsedElement` cannot express it, and `test_fr_ing_04s_bounding_box_clause_is_not_expressible_through_parsedelement` pins that gap | partial |
| FR-ING-05 | Word: paragraphs, tables, footnotes | `ports.ParserPort` | open |
| FR-ING-06 | Classify into eight document types | `schema.DocumentType`; `classify_document` raises NotImplementedError | declared |
| FR-ING-07 | Schema-constrained extraction with confidence + source pointer | `ports.LLMPort.extract` and `schema.CanonicalField` declare the general contract. The sanitized CSV adapter enforces the closed PV field registry and carries confidence plus provenance into claims, but it is not a model-backed extractor | partial |
| FR-ING-08 | Normalize units, retain verbatim | **Retention is covered, normalisation is not.** `verbatim_value` survives the claim-to-canonical projection as provenance rather than as part of the value (`test_the_same_figure_printed_twice_may_differ_in_source_text`), and a unit mismatch is refused rather than absorbed (`test_a_unit_mismatch_is_not_agreement`, `test_a_unit_mismatch_is_never_resolved_by_tolerance`). `services/ingestion.normalize_unit` raises `NotImplementedError` | partial |
| FR-ING-09 | Stable IDs, content hash, dedup | The database dedup half is live-tested: `sql/02_document.sql`'s `UNIQUE (content_hash)` refuses a second row, and the documented upsert is exercised. The sanitized-PV slice derives deterministic source hashes under total row ordering and replays immutable claims idempotently in its in-memory store. The general ingestion/repository path remains absent | partial |
| FR-ING-10 | Sub-threshold confidence routes to HITL | `services/confidence.fuse` produces the score and `requires_review` routes it; Tier A is a gate that no score can pass (`test_tier_a_ignores_the_threshold_entirely`). The threshold itself is still uncalibrated — D-3 reads it off a risk-coverage curve on a labelled set that does not exist yet — and the route from the gate to the workbook is a recorded gap, not a wired path: `confidence.UNIMPLEMENTED_REVIEW_ROUTING` and `test_the_gap_between_the_gate_and_the_workbook_is_named` | partial |

### Indexing, retrieval & RAG

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-RAG-01 | Structure-aware chunking, 512 tokens, 0–10% overlap (revised from the TRS by plan Decision 6) | `config.chunk_size_tokens` bound enforced and tested (`tests/test_settings_bounds.py`); `services/indexing.chunk` still raises `NotImplementedError` | partial |
| FR-RAG-02 | ANN index, cosine, full metadata set | `ports.VectorStorePort`; `sql/03_chunk.sql` stores the embedding and FR-RAG-02's metadata list on the chunk row. **Left `declared` on purpose:** no test asserts that metadata set, and the one live test touching the table (`test_no_ann_index_exists_anywhere`) asserts Decision 3a's reversal of the ANN mandate — the opposite of the requirement, so it is not coverage of it | declared |
| FR-RAG-03 | Hybrid retrieval, rerank, tier stays distinguishable | `ports.RetrievedChunk.source_tier`; `sql/03_chunk.sql` carries `source_tier NOT NULL` with a two-value CHECK and the `tsvector`/`pg_trgm` indexes Decision 3b substitutes for BM25. No test asserts either, and `services/retrieval.retrieve` raises `NotImplementedError` | declared |
| FR-RAG-04 | Retrieved context only, cite source, "insufficient evidence" | `INSUFFICIENT_EVIDENCE` enforced (`test_insufficient_evidence_is_flagged_not_silently_dropped`); `ports.LLMPort.extract` returning `None` is now covered — `test_no_context_is_insufficient_evidence_rather_than_a_guess` and `test_a_field_absent_from_the_context_is_not_invented` (`tests/port_contracts/`) hold an adapter to declining rather than inventing, and the capability may not be declared absent. Still `partial`, and the reason is unchanged by that: the only adapter behind it is an in-memory reference, and `services/retrieval.retrieve` raises `NotImplementedError`, so no path retrieves context for a model to be restricted to | partial |
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
| FR-HITL-03 | Queue entry payload | `schema.ConflictQueueEntry` shape is enforced (severity required, candidates carry `condition`, category is closed); grouping and candidate provenance are tested. The sanitized-PV path now constructs and tests a complete high-severity entry. A durable queue service/API remains absent | partial |
| FR-HITL-04 | Five resolution actions | `schema.ResolutionAction` and `sql/06_resolution.sql` declare the five actions. The sanitized-PV review operation implements selection of an existing sourced candidate (including the system-of-record restriction) and refuses ambiguous or unsourced choices; the other actions and durable resolution persistence remain | partial |
| FR-HITL-05 | Unresolved and low-confidence flagged, never dropped | `services.output.flags_for` computes all four states and is tested; `ComponentInstance.unresolved_conflicts()` reads every conditioned value, and `orchestrator.blocking_conflicts` names blockers. The initial writer carries flags into the workbook and the vertical test pins the unresolved open item. The general confidence-to-review route and full visual QA remain incomplete | partial |
| FR-HITL-06 | Immutable decision log | `CanonicalField`'s validator runs at construction, at assignment in both directions, and on every update route: `model_copy(update=...)` raises, `evolve(...)` revalidates, `model_construct` runs the invariant on the finished object, and `__setstate__`/`__deepcopy__` revalidate so a corrupt object cannot cross a pickle or copy boundary silently (`test_resolution_invariant_survives_assignment`, `test_a_resolved_field_cannot_have_its_resolution_cleared`, `test_model_copy_update_is_refused_on_a_canonical_field`, `test_evolve_reruns_validation_and_still_forbids_the_state`, `tests/test_resolution_immutability.py`). Overwriting a recorded `Resolution` — which every validator passes, because the resulting state is legal — is refused by `__setattr__` and by `evolve` (`test_a_recorded_resolution_cannot_be_replaced`, `test_evolve_cannot_replace_a_recorded_resolution`); `ConflictQueueEntry` is frozen and `Resolution`'s own fields are frozen (`test_resolution_fields_are_frozen`). **Exactly one route remains open, and it cannot be closed:** writing the instance `__dict__` directly — `field.__dict__["conflict_status"] = RESOLVED`, or the same write spelled `object.__setattr__(field, ...)`, which is one route in two spellings and not two. No Python object can defend against it. The shallow-freeze gap is unchanged: `ConflictQueueEntry.candidates` is a list and is mutable in place. Persisted, tamper-evident storage is NFR-02; `sql/` implements the append-only half (no UPDATE/DELETE grant on `resolution`, plus row-level and statement-level tripwires) and it is now **live-tested rather than only hand-verified**: `test_sql_behaviour.py::test_truncate_is_refused[public.resolution]` and `test_the_row_level_tripwire_still_raises` | partial |

### Output

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-OUT-01 | Tab per category, suppliers rows or columns | The initial writer implements the suppliers-as-rows layout and vertical tests exercise it. `suppliers_as_rows=False` is explicitly unsupported rather than silently ignored; no dedicated test yet pins the orientation contract | partial |
| FR-OUT-02 | Exactly 13 tabs | `schema.WorkbookTab` (`test_workbook_has_thirteen_tabs`) | enforced |
| FR-OUT-03 | Per-cell provenance | `write_workbook` emits provenance columns and comments for comparison cells; `test_writer_emits_all_tabs_provenance_and_open_item` pins the source document in the PV value comment | enforced |
| FR-OUT-04 | Four conditional-formatting states | `services.output.flags_for` computes and tests all four states, and the writer applies deterministic fill precedence while retaining every state in the Flags column. Writer-level tests pin an unresolved flag but do not yet inspect all four rendered styles or their accessibility | partial |
| FR-OUT-05 | Certification/standards columns per category | [contracts/canonical-parameters.md](../specs/001-procurement-agent/contracts/canonical-parameters.md) | declared |
| FR-OUT-06 | Canonical units, deterministic regeneration | `services.output.normalize_archive` strips run-to-run archive variance and is independently tested. Claims projection is completion-order independent; component identity supplies total row order. D-14's canonical projection and golden fixture are implemented. The initial writer now passes a two-generation byte-identity test through the sanitized-PV slice. Still partial: general unit normalization is absent, no production store is wired, the alternate orientation is unsupported, and desktop Excel/LibreOffice validation is unrun | partial |

---

## Non-functional requirements

| ID | Requirement | Where | Status |
|---|---|---|---|
| NFR-01 | Traceability, no unsourced values | `schema.SourceRef` validator (`test_source_ref_requires_a_source`) | enforced |
| NFR-02 | Immutable audit log | The database and low-level Python library are built. `sql/07_audit_event.sql` implements the hash chain and the claim/resolution tables are append-only. `src/procurement_agent/audit/` implements D-13's RFC 8785 envelope, advisory-lock append path, verifier, and CLI. `services.transactional_audit.write_and_append_event()` binds a business callback and audit append to one caller-owned transaction; the live suite proves both disappear on rollback. The sanitized-PV slice creates all ingestion/extraction/conflict intents and `persist_vertical_slice()` writes them on that same uncommitted connection. The caller must invoke `acknowledge_persisted()` only after its commit succeeds; that acknowledgement then clears the pending intents. Still partial: the general stages and business repositories remain absent, so the guarantee covers the narrow slice rather than every required operation | partial |
| NFR-03 | Access control at retrieval time; confidential path self-hosted | **RLS is implemented on all seven tables that hold document content**, with `FORCE` so the owner is not exempt, an `app.allow_restricted` entitlement GUC, and a separate `procurement_ingest` role so making a row *more* restricted is not the failing direction. Structural: `test_every_table_holding_document_content_forces_rls`, `test_every_such_table_has_a_confidentiality_select_policy` (both ×7). Live: `test_the_app_role_cannot_declassify_rows_it_cannot_read`, `test_the_write_policy_alone_protects_an_unreadable_row`, `test_the_document_write_policy_alone_protects_an_unreadable_row`, `test_the_app_role_cannot_delete_rows_it_cannot_read`, `test_a_chunk_inherits_its_parent_documents_restriction`, `test_restriction_can_only_increase`, `test_claims_do_not_leak_a_restricted_documents_values`, `test_the_app_role_cannot_escalate_to_the_ingest_role`. `VectorStorePort.search(allowed_document_ids=...)` has a tested in-memory reference that filters inside the search, but no vendor adapter or production retrieval path; `services/retrieval.retrieve` raises `NotImplementedError`. Self-hosted endpoints remain a `.env.example` convention with no check. **D-15 (adopted 2026-08-07, provisional) ratifies this label model** as C7's answer — one document-level label, per-principal clearance from the OIDC subject, labelling at ingest failing closed. Provisional because two facts are outstanding, not two preferences. | partial |
| NFR-04 | Six swap points behind stable interfaces | **The interfaces are exercised; nothing has been swapped.** `tests/port_contracts/` is the first suite to import `ports` — 74 tests over one in-memory reference adapter per Protocol in `src/procurement_agent/adapters/`, implementing [ADR-001](decisions/ADR-001-cross-repo-pattern-adoption.md) decision 2. Each reference is checked three independent ways: `isinstance` against the Protocol (`test_every_adapter_satisfies_its_port_at_runtime`), signatures by `mypy --strict` through each module's `_conforms()`, and behaviour by the contract tests. The capability declaration is required to partition its port's set exactly (`test_every_adapter_accounts_for_every_capability_of_its_port`), so an unmet capability is declared rather than absent, and `ACCESS_FILTERING` / `INSUFFICIENT_EVIDENCE` may not be declared absent at all (`test_an_unxfailable_capability_is_never_declared_absent`). **Not `enforced`, and the gap is the requirement's own verb.** Every registered adapter is an in-memory reference written *against these tests*: they prove the six Protocols are expressible and mutually consistent, not that any real backend satisfies them. No vendor adapter exists, and no production path consumes a port — `services/ingestion.ingest` and `services/retrieval.retrieve` still raise `NotImplementedError`. `test_every_registered_adapter_is_an_in_memory_reference` goes red the day that stops being true, so this row cannot outlive its evidence quietly | partial |
| NFR-05 | Idempotent re-ingest | `schema.SourceDocument.content_hash` plus `sql/02_document.sql`'s `UNIQUE (content_hash)` are live-tested, including the documented `ON CONFLICT DO NOTHING` idiom. The sanitized-PV slice derives order-independent hashes and idempotently replays claims in its in-memory store. Not `enforced`: general `services.ingestion.ingest` and its repository path remain unimplemented | partial |
| NFR-06 | Hundreds of documents | — | open |
| NFR-07 | Batch ingestion; interactive ops in seconds-to-minutes | `orchestrator` docstring | open |
| NFR-08 | Human retains final authority | `orchestrator.compose_gate_blocks` / `blocking_conflicts`, `schema.Severity` (`tests/test_compose_gate.py`) | enforced |

---

## Acceptance criteria

| ID | Criterion | Test | Status |
|---|---|---|---|
| AC-1 | Scanned spec sheet extracts fields with provenance, low confidence to HITL | — | open |
| AC-2 | Web contradiction raises conflict; record value unchanged | `tests/test_source_of_record_rule.py` calls `assert_no_autonomous_overwrite` directly, and `test_propose_commit.py::test_a_web_claim_contradicting_the_record_is_queued` drives a web contradiction through projection to `ConflictStatus.OPEN` with the record still supplying the value. The sanitized slice builds an inter-document queue entry, but no test drives a **web** contradiction all the way into that queue path | partial |
| AC-3 | All 13 tabs with conditional formatting | Schema/flag tests plus `test_writer_emits_all_tabs_provenance_and_open_item` exercise a real generated workbook. All tabs, provenance, flag text, and the open item are pinned; every writer-level style combination and desktop Excel/LibreOffice remain unverified | partial |
| AC-4 | Every cell resolves to a source | `tests/test_schema_invariants.py::test_source_ref_requires_a_source` | enforced |
| AC-5 | Re-ingest creates no duplicates | `tests/test_sql_behaviour.py::test_a_duplicate_content_hash_is_refused` inserts a second row with an existing `content_hash` against a live server and asserts the `UniqueViolation`; `test_a_restricted_document_can_be_ingested_idempotently` runs the `ON CONFLICT DO NOTHING` idiom as the ingest role. **Verified non-vacuous:** changing the second insert to a distinct hash turns the test red, and removing the `UNIQUE` constraint takes the whole file down while `test_sql_schema.py` stays green. Not `enforced`: this covers the store, and `services/ingestion.ingest` — the thing that would re-ingest — raises `NotImplementedError` | partial |
| AC-6 | Inverter tab reports TRD against correct IEEE 2800 limit; tab 13 reports BABA/ITC/FEOC | — | open |
| AC-7 | Two generations from an unchanged store are byte-identical | `tests/test_workbook_determinism.py` covers normalization and `test_workbook_bytes_are_deterministic` generates two byte-identical complete workbooks from the same vertical-slice result. No production store is wired and the desktop Excel/LibreOffice gate (task G.6) is unrun | partial |
| AC-8 | An uncleared user cannot influence any retrieved result | See NFR-03 for the full citation. RLS on seven tables with `FORCE`, an entitlement GUC and a separate ingest role, live-tested by eight assertions in `tests/test_sql_behaviour.py` — the load-bearing one is `test_claims_do_not_leak_a_restricted_documents_values`, which fails when and only when `claim`'s confidentiality policy is widened to `USING (true)`. `ports.VectorStorePort.search(allowed_document_ids=...)` is no longer only a declared parameter: `tests/port_contracts/` holds any adapter to enforcing it *inside* the search rather than after it (`test_access_control_is_applied_inside_the_search_not_after_it` — asking for one result when the three nearest chunks are restricted, which a post-filter answers with nothing), and `ACCESS_FILTERING` is one of the two capabilities an adapter may not declare absent. That is a contract a future adapter is held to, not a retrieval path: the only implementation behind it is an in-memory reference. **Not `enforced`, and the reason has changed:** [A-28](../specs/001-procurement-agent/analysis.md) withheld it because CI did not execute the DDL, which #25 fixed. It is withheld now because there is no retrieval path at all — a user cannot influence a retrieved result today because nothing retrieves | partial |

AC-7 and AC-8 were absent from this table while `spec.md` listed eight criteria. They are the
two the spec itself flags as "the kind of property that silently rots without a test", so
omitting them from the traceability record was the specific failure they were added to prevent.

AC-3 is partial: tab identity and cell-state logic are tested, and the initial writer is generated
and inspected. Full writer-level coverage of all four visual states and desktop Excel/LibreOffice
validation remain open.
AC-1 and AC-6 need the ingestion path and a labelled corpus — Stage 1 in the
[README build plan](../README.md#build-plan). AC-5 is no longer in that group: the store-level
invariant it names is live-tested, and only the ingest path that would exercise it is missing.
[`tasks.md`](../specs/001-procurement-agent/tasks.md) assigns owners per criterion and is the
list to check before claiming one.
