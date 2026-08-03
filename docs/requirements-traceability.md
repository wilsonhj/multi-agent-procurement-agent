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

---

## Functional requirements — FRD

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-1 | Multi-format intake | `services/ingestion.detect_content_signature` | declared |
| FR-2 | Document understanding | `schema.DocumentType`, `services/ingestion.classify_document` | declared |
| FR-3 | Fact extraction into a consistent structure | `schema.CanonicalField` (+ `schema.Condition`, see [D-1](../specs/001-procurement-agent/clarifications.md)) enforced; `schema.ComponentInstance` ordering enforced, `unresolved_conflicts()` untested | partial |
| FR-4 | Web supplement, never silent overwrite | `services/conflict_hitl.assert_no_autonomous_overwrite` | enforced |
| FR-5 | Conflict surfacing, no auto-resolution | guard, `comparison_pairs` and `values_conflict` enforced; nothing constructs a `ConflictQueueEntry` in production yet | partial |
| FR-6 | One workbook, tab per category, flagged | `services/output.write_workbook`, `schema.WorkbookTab` | declared |
| FR-7 | Source traceability, no unsourced values | `schema.SourceRef` validator | enforced |
| FR-8 | Decision authority stays human | `orchestrator.compose_gate_blocks` / `blocking_conflicts`, `schema.Severity` | enforced |

## Functional requirements — TRS

### Ingestion & extraction

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-ING-01 | Accept 10 formats, route by content signature | `services/ingestion.detect_content_signature`, `ports.ParserPort.supports` | declared |
| FR-ING-02 | Spreadsheets: sheets, headers, merged cells, typing | `ports.ParserPort` | open |
| FR-ING-03 | Text-layer PDFs: layout-aware, page numbers | `ports.ParsedElement` | declared |
| FR-ING-04 | Scanned PDFs/images: OCR, bounding boxes | `ports.OCRPort`, `schema.SourceRef.bounding_box` | declared |
| FR-ING-05 | Word: paragraphs, tables, footnotes | `ports.ParserPort` | open |
| FR-ING-06 | Classify into eight document types | `schema.DocumentType`; `classify_document` raises NotImplementedError | declared |
| FR-ING-07 | Schema-constrained extraction with confidence + source pointer | `ports.LLMPort.extract`, `schema.CanonicalField` | declared |
| FR-ING-08 | Normalize units, retain verbatim | `schema.CanonicalField.verbatim_value`, `services/ingestion.normalize_unit` | declared |
| FR-ING-09 | Stable IDs, content hash, dedup | `schema.SourceDocument.content_hash` | declared |
| FR-ING-10 | Sub-threshold confidence routes to HITL | `services/confidence.fuse` produces the score and `requires_review` routes it; Tier A is a gate that no score can pass. The threshold itself is still uncalibrated — D-3 reads it off a risk-coverage curve on a labelled set that does not exist yet | partial |

### Indexing, retrieval & RAG

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-RAG-01 | Structure-aware chunking, 512 tokens, 0–10% overlap (revised from the TRS by plan Decision 6) | `config.chunk_size_tokens` bound enforced and tested (`tests/test_settings_bounds.py`); `services/indexing.chunk` still raises `NotImplementedError` | partial |
| FR-RAG-02 | ANN index, cosine, full metadata set | `ports.VectorStorePort` | declared |
| FR-RAG-03 | Hybrid retrieval, rerank, tier stays distinguishable | `ports.RetrievedChunk.source_tier` | declared |
| FR-RAG-04 | Retrieved context only, cite source, "insufficient evidence" | `INSUFFICIENT_EVIDENCE` enforced; `ports.LLMPort.extract` returning `None` untested (no test imports `ports`) | partial |
| FR-RAG-05 | Incremental add/update/delete by stable ID | `ports.VectorStorePort.upsert` / `.delete` | declared |

### Web search

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-WEB-01 | Search only on gap or user request | `services/web_search.search_for_gap` | declared |
| FR-WEB-02 | Tag `web_supplement` + URL, title, timestamp; log queries | tier tagging enforced; `SourceRef.retrieved_at` optional and never asserted, query logging has no code | partial |
| FR-WEB-03 | Fill empty fields only, never overwrite | `assert_no_autonomous_overwrite` | enforced |
| FR-WEB-04 | Divergence beyond tolerance raises a conflict | `services/conflict_hitl.values_conflict` implemented against `conflict_hitl/tolerance.FIELD_TOLERANCES`, the [D-2](../specs/001-procurement-agent/clarifications.md) table transcribed | enforced |
| FR-WEB-05 | Prefer and record source authority | `services/web_search.SOURCE_AUTHORITY_ORDER` | declared |

### Conflict detection & HITL

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-HITL-01 | Five conflict classes | `schema.ConflictClass` — no test asserts the count | declared |
| FR-HITL-02 | Never auto-arbitrate web vs record | `assert_no_autonomous_overwrite` | enforced |
| FR-HITL-03 | Queue entry payload | `schema.ConflictQueueEntry` shape enforced (severity required, candidates carry `condition`, `component_category` is the closed vocabulary); no production path builds one | partial |
| FR-HITL-04 | Five resolution actions | `schema.ResolutionAction` — no test asserts the count | declared |
| FR-HITL-05 | Unresolved and low-confidence flagged, never dropped | `services/output.flags_for` computes all four states and is tested; `write_workbook` still raises `NotImplementedError`, so nothing puts a flag in front of a human | partial |
| FR-HITL-06 | Immutable decision log | `CanonicalField`'s validator enforced at construction *and* assignment, in both directions (`test_resolution_invariant_survives_assignment`, `test_a_resolved_field_cannot_have_its_resolution_cleared`); `ConflictQueueEntry` frozen, so a recorded resolution cannot be replaced (`test_a_recorded_resolution_cannot_be_replaced`). **Three routes remain open:** `CanonicalField.model_copy(update=...)` re-runs no validators and still reaches the forbidden state; the freeze is shallow, so `ConflictQueueEntry.candidates` is mutable in place; and `Resolution`'s own field-level frozen-ness is untested. Persisted, tamper-evident storage is NFR-02, still `declared` | partial |

### Output

| ID | Requirement | Where | Status |
|---|---|---|---|
| FR-OUT-01 | Tab per category, suppliers rows or columns | `config.suppliers_as_rows` | declared |
| FR-OUT-02 | Exactly 13 tabs | `schema.WorkbookTab` | enforced |
| FR-OUT-03 | Per-cell provenance | `services/output.write_workbook` | declared |
| FR-OUT-04 | Four conditional-formatting states | `services/output.flags_for` enforced; no test exercises the formatting itself, and the writer that would apply it is unimplemented | partial |
| FR-OUT-05 | Certification/standards columns per category | [contracts/canonical-parameters.md](../specs/001-procurement-agent/contracts/canonical-parameters.md) | declared |
| FR-OUT-06 | Canonical units, deterministic regeneration | `services/output.write_workbook` | declared |

---

## Non-functional requirements

| ID | Requirement | Where | Status |
|---|---|---|---|
| NFR-01 | Traceability, no unsourced values | `schema.SourceRef` validator | enforced |
| NFR-02 | Immutable audit log | `schema.Resolution` frozen; store not yet built | declared |
| NFR-03 | Access control at retrieval time; confidential path self-hosted | `VectorStorePort.search(allowed_document_ids=...)`, `.env.example` | declared |
| NFR-04 | Six swap points behind stable interfaces | `ports/` — all six Protocols; **no test imports `ports` at all** | declared |
| NFR-05 | Idempotent re-ingest | `schema.SourceDocument.content_hash` | declared |
| NFR-06 | Hundreds of documents | — | open |
| NFR-07 | Batch ingestion; interactive ops in seconds-to-minutes | `orchestrator` docstring | open |
| NFR-08 | Human retains final authority | `orchestrator.compose_gate_blocks` / `blocking_conflicts`, `schema.Severity` | enforced |

---

## Acceptance criteria

| ID | Criterion | Test | Status |
|---|---|---|---|
| AC-1 | Scanned spec sheet extracts fields with provenance, low confidence to HITL | — | open |
| AC-2 | Web contradiction raises conflict; record value unchanged | `tests/test_source_of_record_rule.py` calls `assert_no_autonomous_overwrite` directly; no test drives a web contradiction through detection to a queue entry | partial |
| AC-3 | All 13 tabs with conditional formatting | `tests/test_schema_invariants.py`, `tests/test_output_flags.py` | partial |
| AC-4 | Every cell resolves to a source | `tests/test_schema_invariants.py::test_source_ref_requires_a_source` | enforced |
| AC-5 | Re-ingest creates no duplicates | — | open |
| AC-6 | Inverter tab reports TRD against correct IEEE 2800 limit; tab 13 reports BABA/ITC/FEOC | — | open |

AC-3 is partial: tab identity and cell-state logic are tested, workbook generation is not.
AC-1, AC-5 and AC-6 need the ingestion path and a labelled corpus, which is Stage 1 work.
