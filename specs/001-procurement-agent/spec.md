# Feature Specification: Procurement Agent

**Feature branch:** `001-procurement-agent`
**Created:** 2026-07-28
**Status:** Draft — ready for implementation
**Sources:** Procurement Agent FRD v2.0 (2026-06-01), Procurement Agent TRS v2.0 (2026-06-01)

---

## Overview

A decision-support tool for procuring components for a 500 MW solar-plus-storage plant
interconnecting to ERCOT in Texas.

It ingests supplier documentation in whatever format it arrives, extracts comparison-relevant
facts into a consistent structure, fills gaps from public sources, flags every place the
sources disagree, and produces a single 13-tab Excel workbook in which every value traces
back to where it came from.

**It supports the procurement decision. It does not make it.**

---

## Guiding constraints

These are not features. They are properties every feature must preserve, and any change that
weakens one is a defect regardless of what else it improves.

| # | Constraint | Consequence if violated |
|---|---|---|
| C-1 | Ingested contracts and spec sheets are the system of record. Public web data is supplementary only. | A supplier's contractual commitment gets silently replaced by a marketing figure. |
| C-2 | Web data may fill an empty field. It may never overwrite a system-of-record value. | Same as above, plus the audit trail lies about what the supplier committed to. |
| C-3 | When sources disagree, the tool surfaces all values with their sources and routes to a human. It never picks a winner. | The tool makes a procurement decision it has no authority to make. |
| C-4 | Every value in the output traces to a source document with page, or a URL. No unsourced values. | A number appears in a purchasing decision with no way to defend it. |
| C-5 | The tool takes no autonomous procurement action and commits no spend. | Out of scope entirely; also a governance breach. |
| C-6 | Contract and pricing documents are confidential. Access control is enforced when content is retrieved, not merely when it is displayed. | Confidential commercial terms leak into a context the reader is not cleared for. |

---

## User scenarios

### Primary: assemble a supplier comparison

**Actor:** Procurement lead

1. The team receives documentation from eight PV module suppliers — some as clean PDF
   datasheets, some as scans, one as a photograph of a printed spec sheet, two as Excel
   price lists, and three as executed contracts.
2. They upload the whole set.
3. The tool identifies each file by its actual content, reads it, classifies what kind of
   document it is, and pulls out the parameters that matter for comparison.
4. Where a supplier did not state a value the tool needs, it looks for it publicly and
   marks anything it finds as supplementary.
5. Where two sources disagree, it does not choose. It records both and raises an open item.
6. The lead opens the workbook, sees which cells are flagged, and works the Conflicts tab.
7. For each conflict they select a value, override it, keep the contract value, ask for
   another search, or defer.
8. They regenerate the workbook. Their decisions and reasons are recorded permanently.

**Done when:** the lead can compare all eight suppliers side by side, and can point at any
number in the workbook and see the document and page it came from.

### Secondary: a datasheet is revised mid-evaluation

A supplier issues a revised datasheet with a different degradation figure. On re-ingest the
tool detects that this is the same product with a newer vintage, raises a temporal conflict
against the previously extracted value, and leaves both visible with their dates until a
human decides which governs.

### Secondary: a scan is too poor to read

A supplier submits a low-quality scan. Rather than guessing, the tool marks the affected
fields as low-confidence or insufficient-evidence, routes them for review, and flags them in
the workbook. Nothing silently becomes a number.

### Secondary: checking eligibility for incentives

Finance needs to know which suppliers support the domestic-content bonus. The Tax Incentives
tab reports each supplier's status across three separate frameworks, sourced, with anything
unconfirmed visibly marked as such.

---

## Functional requirements

Requirement IDs are carried over from the TRS unchanged so that spec, code and tests can be
cross-referenced against the source documents.

### Ingestion and extraction

| ID | Requirement |
|---|---|
| FR-ING-01 | Accept `.xlsx`, `.csv`, `.pdf`, `.docx`, and images `.jpg/.jpeg`, `.png`, `.tif/.tiff`, `.bmp`, `.webp`, `.heic`. Route by content signature, never by file extension. |
| FR-ING-02 | Spreadsheets and CSV: preserve sheet names, headers, merged cells and numeric typing. Each table is extracted as a structured object. |
| FR-ING-03 | Text-layer PDFs: layout-aware parsing distinguishing headings, body, tables and figures, recording the page number of every element. |
| FR-ING-04 | Scanned PDFs and images: detect absent or low text coverage automatically and apply OCR. Handle skew, rotation, multi-column layout and tables. Retain bounding-box metadata. |
| FR-ING-05 | Word documents: paragraphs, headings, tables, headers/footers and footnotes. Tables serialised structure-preserving with source, page and caption. |
| FR-ING-06 | Classify every document as one of: contract/TOS, purchase order, environmental regulation, terms and conditions, warranty, technical documentation, pricing, spec sheet. Store as metadata. |
| FR-ING-07 | Extract canonical fields using schema-constrained output with validation. Every field carries a confidence score and a source pointer (document, page, table or section). |
| FR-ING-08 | Normalise units to canonical form while retaining the verbatim original exactly as written. |
| FR-ING-09 | Assign stable document and chunk identifiers with timestamps and source URI, enabling deterministic update and delete, and content-hash deduplication. |
| FR-ING-10 | Fields extracted below the confidence threshold are flagged for human review rather than committed silently. |

### Indexing and retrieval

| ID | Requirement |
|---|---|
| FR-RAG-01 | Structure-aware chunking that preserves section boundaries. Tables are kept whole where feasible. |
| FR-RAG-02 | Every chunk **shall** be embedded and stored in an **ANN vector index (HNSW/IVF, cosine)** with metadata: document ID, chunk ID, component category, supplier, document type, page, source URI, timestamps, source tier. ⚠️ **Reversed by plan Decision 3a — exact search, no ANN index.** Recorded as [A-23](analysis.md); the requirement is stated here as the TRS expresses it. |
| FR-RAG-03 | Hybrid retrieval (**vector + BM25**), with reranking and metadata filtering. System-of-record content must remain distinguishable from web-supplemented content at every point. ⚠️ **Reversed by plan Decision 3b — lexical matching via Postgres `tsvector`/GIN full-text and `pg_trgm` trigram, not BM25.** The three legs are unioned and deduped by `chunk_id`, then ranked by the cross-encoder; there is no rank-fusion stage. Recorded as [A-24](analysis.md), corrected as [A-40](analysis.md), and the fusion stage dropped by [A-43](analysis.md). |
| FR-RAG-04 | Extraction uses retrieved context only, cites document and page, and returns an explicit *insufficient evidence* result rather than fabricating a value. |
| FR-RAG-05 | Incremental add, update and delete by stable identifier, without full re-indexing. |

### Web supplement

| ID | Requirement |
|---|---|
| FR-WEB-01 | Search public sources only when a required field has no system-of-record value, or on explicit user request. |
| FR-WEB-02 | Tag every web-derived value as supplementary, with URL, page title and retrieval timestamp. Log the query itself for reproducibility. |
| FR-WEB-03 | Fill empty fields only. Never overwrite or silently replace a system-of-record value. |
| FR-WEB-04 | When a web value and a record value differ beyond tolerance, raise a conflict. Do not choose. |
| FR-WEB-05 | Prefer authoritative sources and record source authority as metadata. |

### Conflict detection and human resolution

| ID | Requirement |
|---|---|
| FR-HITL-01 | Detect field-level conflicts in five classes: record versus web; between documents; within a single document; temporal (across revisions); and unit/normalisation. |
| FR-HITL-02 | Never auto-arbitrate between web data and an ingested contract or spec sheet. |
| FR-HITL-03 | Each conflict is queued with the canonical field, component and supplier, every candidate value with its verbatim source text, source tier, source authority, document/page/URL, timestamps, and a generated explanation. |
| FR-HITL-04 | Resolution actions are exactly: select a value, enter an override, keep the system-of-record value, request further web search, or defer. Resolution and rationale persist to the field's provenance. |
| FR-HITL-05 | Unresolved conflicts, low-confidence values and insufficient-evidence fields all route to the same queue and are flagged in the output. Never silently resolved, never omitted. |
| FR-HITL-06 | Every human decision is logged immutably with user, timestamp, before and after values, and rationale. |

### Output

| ID | Requirement |
|---|---|
| FR-OUT-01 | One workbook, one tab per component category, suppliers as rows or columns (configurable), compared against that category's canonical parameters. |
| FR-OUT-02 | Exactly 13 tabs: eight category tabs (PV Modules, Inverters/PCS, Trackers & Mounting, Transformers, Cabling & Wiring, Combiner Boxes, BESS, EMS/SCADA & Controls) plus Executive Summary, Conflicts & Open Items, Sources & Provenance, Compliance Matrix, Tax Incentives. |
| FR-OUT-03 | Every comparison cell traces to its source. |
| FR-OUT-04 | Conditional formatting distinguishes four states: unresolved conflict, web-supplemented, low-confidence, missing. States can co-occur on one cell and must remain distinguishable when they do. |
| FR-OUT-05 | Each category tab includes certification and standards columns appropriate to that category. |
| FR-OUT-06 | Units display canonically with the verbatim original available. The workbook is deterministically regenerable from the canonical store, and carries a generated-on timestamp plus the vintage of every source. ⚠️ **The generated-on timestamp is store-derived, never `now()`** — the high-water mark of the store rows composition reads (`document.ingested_at`, `claim.extracted_at`, `resolution.resolved_at`). A wall-clock stamp would make two generations of an unchanged store differ by construction and so violate AC-7 while satisfying this sentence. Recorded as [A-46](analysis.md); it is an input to contract C6. |

---

## Non-functional requirements

| ID | Requirement | How it is judged |
|---|---|---|
| NFR-01 | Traceability: no unsourced values | Every field in the store has a resolvable source reference |
| NFR-02 | Auditability: web queries, extractions, conflicts and resolutions logged immutably | Log entries cannot be altered or deleted after write |
| NFR-03 | Security: access control **must** be enforced at retrieval time **via metadata filtering**; confidential documents processed on self-hosted or enterprise endpoints with no third-party training. ⚠️ **Mechanism substituted by plan Decision 3c — `FORCE ROW LEVEL SECURITY`.** Recorded as [A-25](analysis.md). | A user without clearance cannot cause restricted content to influence a result |
| NFR-04 | Modularity: parsers, OCR, embedders, vector store, reranker and LLM swappable behind stable interfaces | Any one can be replaced without touching another |
| NFR-05 | Idempotency: re-ingesting an unchanged document creates no duplicates | Content hash prevents re-processing |
| NFR-06 | Scale: hundreds of datasheets and contracts, large multi-tab workbooks | Not thousands. Do not over-engineer for volume. |
| NFR-07 | Latency: ingestion is batch/offline; conflict resolution and regeneration complete in seconds to minutes | Interactive operations are not gated on ingestion |
| NFR-08 | Human authority: no autonomous procurement commitment | No code path commits spend or places an order |

---

## Key entities

**Component instance** — one supplier's offering in one category. Identified by supplier,
model and category. Holds a set of canonical fields.

**Canonical field** — one extracted parameter. Carries its value, canonical unit, the
verbatim original text, its source tier, its source reference, a confidence score, its
conflict status, and the resolution if one was made. This object is the unit of provenance;
the workbook is regenerated entirely from these.

**Source document** — an ingested file. Content-addressed so that re-ingestion is a no-op.
Carries its type, source URI, ingestion timestamp, data vintage and access restriction.

**Conflict queue entry** — a disagreement awaiting a human. Holds every candidate value with
full provenance, the conflict class, and a generated explanation.

**Audit log entry** — an immutable record of an extraction, a web query, a detected conflict
or a human resolution.

---

## Acceptance criteria

| ID | Criterion |
|---|---|
| AC-1 | A scanned PDF spec sheet yields the defined canonical fields with per-field provenance, and low-confidence fields route to human review. |
| AC-2 | A web value contradicting an ingested spec value raises a conflict, and the system-of-record value is unchanged. |
| AC-3 | The workbook contains all 13 tabs with conditional formatting for conflicts, web-supplemented values, low-confidence values and missing data. |
| AC-4 | Every output spec cell resolves to a source. No unsourced values. |
| AC-5 | Re-ingesting an unchanged document creates no duplicates. |
| AC-6 | The inverter tab reports **TRD** against the correct **IEEE 2800** voltage-class limit with a harmonic spectrum, and the tax tab reports each supplier's status across the three incentive frameworks. **TRD, not TDD** — the TRS calls this "the key correction from v1", and getting it wrong produces a compliance matrix that passes suppliers it should fail. |
| AC-7 | Generating the workbook twice from an unchanged canonical store produces **(a)** a byte-identical **canonical projection** — sorted-key JSON with floats via `repr()` — which is the hashed artifact of record and the criterion itself; and **(b)** a byte-identical rendered `.xlsx`, whose hash is pinned in CI as a **renderer-regression check** rather than as this criterion, and whose golden value may be refreshed by a deliberate, recorded decision (a recorded openpyxl upgrade, say). A projection-hash change against an unchanged store is always a defect; a workbook-hash change is a defect **unless** a refresh is recorded — **recorded as a numbered entry in [analysis.md](analysis.md)**, which is this repository's deviation register and the only place a relaxation of an acceptance criterion counts as recorded. Layer (b)'s **run-to-run** byte identity within one environment is *not* refreshable and is not covered by that escape hatch: only the cross-version golden value is. |
| AC-8 | A user without clearance for a confidential document cannot cause its content to influence any retrieved result. |

AC-7 and AC-8 are additions to the TRS's six. They are implied by FR-OUT-06 and NFR-03
respectively but were not stated as testable criteria, and both are the kind of property
that silently rots without a test.

⚠️ **AC-7 was amended on 2026-08-04** to name the artifact it is asserted against. It previously
read "produces byte-identical files", universally read as the `.xlsx`, while plan Decision 8c had
already demoted the workbook hash internally — `%.16g` maps `0.1+0.2` and `0.3` to identical
bytes, so a workbook hash cannot distinguish two genuinely different stored numbers. The
amendment does **not** weaken determinism, but the reason takes two halves rather than one. Layer
(a) is *stricter* than the text it replaces at distinguishing **store states**, because it catches
exactly the float collision the xlsx hash cannot. It is strictly **weaker** at catching renderer
nondeterminism — a projection hash cannot see any of `normalize_archive`'s five sources (wall clock,
library version, compression level, ZIP member order, platform), because it never touches the
archive. So the guarantee is preserved only because layer (b) is **retained as a run-to-run
byte-identity assertion**, not despite it. Stating just the first half would be the argument for
dropping (b), which would be a real weakening. What the amendment buys is that a
routine renderer change — an openpyxl security patch, or the alternative entry ordering that
task G.6 may force — becomes a recorded refresh of (b)'s *golden* value rather than an
acceptance-criterion crisis.
Registered as [A-46](analysis.md); this is a deliberate amendment to a rank-2 normative artifact,
not a silent edit.

---

## Out of scope

Placing orders, signing contracts or committing spend. Automatically choosing between
conflicting data or recommending a winner. ERP posting. Price negotiation. Engineering or
yield modelling. Legal review. The tool informs these activities; it does not perform them.

---

## Assumptions

- Suppliers provide reasonably legible documentation. Very poor scans may require
  re-submission rather than best-effort guessing.
- Datasheet and pricing values change with product revisions. Every source carries its date
  or version.
- Outputs reflect the data provided plus public sources as of the generation date.
- Tax, environmental and grid rules are evolving through 2026. The tool reports status; it
  does not replace professional advice, and its regulatory content requires confirmation by
  tax and legal counsel before being relied on for filings.

---

## Dependent decisions

Ambiguities in the source documents are resolved in [clarifications.md](clarifications.md),
each with a researched default and its rationale. Technical approach is in
[plan.md](plan.md). Work breakdown for parallel teams is in [tasks.md](tasks.md).
