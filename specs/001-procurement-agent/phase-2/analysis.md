# Phase 2 cross-artifact analysis

Consistency findings across `spec.md`, `plan.md`, `clarifications.md`, `tasks.md`,
`docs/current-state.md`, `docs/requirements-traceability.md`, `agent-topology.md`, the ports, the
services, `sql/`, CI, and the seven story specs. Numbered `P2-A-n` so they do not collide with the
Phase 1 register in [analysis.md](../analysis.md) (A-1..A-62). Same practice: **do not re-open a
Fixed row; append a new one.**

Status vocabulary: **Open** (the story that owns it is named) · **Decided** (a contract or rule in
this plan covers it) · **Ratified → D-n** (folded into `clarifications.md` on 2026-09-03) ·
**Recorded** (a fact to know, no action).

**Re-analysed 2026-09-03 after the Q-5 – Q-16 ratification.** P2-A-24 – P2-A-27 were added by that pass.

| ID | Finding | Evidence | Owner | Status |
|---|---|---|---|---|
| **P2-A-1** | `ParsedElement(kind, text, page)` cannot carry a bounding box, table structure, page quality or role, yet `OCRPort.recognize`'s docstring says "retain bounding boxes" (FR-ING-04), FR-ING-02 requires structured tables, D-3's hard gate needs "low-quality scan", FR-ING-05 needs headers/footers/footnotes. The conformance matrix pins `__annotations__ == {kind, text, page}` | `ports/__init__.py` L47–53, L83–93; `tests/port_contracts/test_conformance_matrix.py` | Track 0 | **Ratified → D-23** (P2-C1) |
| **P2-A-2** | `services.indexing.chunk()` returns `list[str]`; `sql/03_chunk.sql` stores `chunk_kind`, `table_id`, `page`, `section`, `context_prefix`. Decision 6's triple indexing is unrepresentable through the stub's return type | `services/indexing/__init__.py` L35; `sql/03_chunk.sql` | Track 0 | Decided (P2-C2; no Q needed) |
| **P2-A-3** | No port serves the lexical leg Decision 3b requires; `retrieve()`'s stub takes only `store` and `reranker` | `services/retrieval/__init__.py` L42; `ports/` (six Protocols) | Track 0 | **Ratified → D-25** (P2-C3) |
| **P2-A-4** | `search_for_gap() -> list[CanonicalField]` contradicts C8 ("workers propose … the canonical value is a projection over claims") and D-16's shape; every other producer emits `FieldClaim` | `services/web_search/__init__.py` L25 | Story 3 | Open — signature changes to `list[FieldClaim]` with Team 1 review |
| **P2-A-5** | `orchestrator.Stage` has six members and no `reduce`; agent-topology says "a single reducer commits"; `sql/08`'s CHECK pins the six | `orchestrator/__init__.py` L38–51; `sql/08_job.sql`; `agent-topology.md` L85–91 | Story 4 | Decided — the reducer is the `detect_conflicts` handler, serial per field; no seventh stage |
| **P2-A-6** | `EVENT_TYPES_V1` lists `web_search`, `audit.event`'s stream CHECK is `doc:`-only, and D-13 assigns web queries to `audit.run_event`, which does not exist. Story 3 cannot log a query without Story 4's `sql/11`–`12` | `audit/envelope.py` L113–123; `sql/07` L117–125; D-13 | Story 4 (4a) | Open — P2-C7; ordering constraint in the master merge order |
| **P2-A-7** | `.env.example` and `Settings` have no OCR endpoint, reranker endpoint, web-search provider, OIDC issuer/client, classification threshold, embedding batch size, gold corpus dir, access-review max age | `config.py`; `.env.example` | Stories 1b, 2, 3, 5, 1d, 7 | Open — each story adds its settings and the `.env.example` lines; names listed in the stories |
| **P2-A-8** | `docs/current-state.md` cites a **1000**-passing baseline; the post-#36 baseline is **1039** passed / 42 skipped / 4 xfailed. The audit text is otherwise directionally right | `docs/current-state.md` L6; pytest run 2026-09-03 | Track 0 (docs owner of record) | Open — one-line correction in the Track 0 PR |
| **P2-A-9** | FR-ING-05 promises page numbers for Word tables; Docling cannot supply them from `.docx` | research.md; Docling issues #775, #2196 | Story 1a | **Ratified → D-19** |
| **P2-A-10** | Brave API terms forbid storing results beyond transient use; FR-WEB-02 + NFR-02 require an immutable query log | research.md; Brave ToS | Story 3 + product owner | **Ratified → D-20** as engineering; commercial half with the product owner |
| **P2-A-11** | `sql/04_claim.sql` has no link from a `human:` claim to its `Resolution`; D-16 records this as "Python ahead of DDL; WP-H/WP-F own the migration" | `sql/04` L47–49; D-16 "What it costs" | Story 4a | **Ratified → D-27** (P2-C6) |
| **P2-A-12** | FR-OUT-01 says orientation is configurable; `write_workbook(suppliers_as_rows=False)` raises `NotImplementedError` | `services/output/__init__.py` L172–175 | Story 6 | Open — §6 of story-6 |
| **P2-A-13** | **`tasks.md` says AC-2 is "passing"; `docs/current-state.md` says "partial"** ("Nothing drives a contradiction from ingestion through to a queue entry"). `current-state.md` is right — the guard function is tested, the path is not. Two status documents disagreeing is the defect `current-state.md`'s 2026-08-05 correction note warns about | `tasks.md` L312; `docs/current-state.md` AC-2 row | Story 3 | Open — Story 3 delivers the end-to-end path and corrects **both** rows in one PR; until then a grep test in Story 3 pins agreement |
| **P2-A-14** | `PARSED_ELEMENT_KINDS` is four values; Docling distinguishes captions, footnotes and furniture, which FR-ING-05 names. Adding kinds would ripple through every adapter and the memory reference | `adapters/parsed_element.py`; Docling labels | Track 0 | Decided — `role` field on `ParsedElement` (P2-C1), kinds unchanged |
| **P2-A-15** | Same as P2-A-7 for the `.env.example` file specifically: it documents the removed `HITL_CONFIDENCE_THRESHOLD` but none of the Phase 2 services | `.env.example` | each story | Open — folded into P2-A-7 |
| **P2-A-16** | D-3's hard gate "the source page was a low-quality scan" has no signal in the schema: `SourceRef` carries a `bounding_box` but no quality | `schema/field.py` L68–147 | Track 0 | Decided — `ParsedElement.page_quality` (P2-C1); the claim's `confidence` features consume it; `SourceRef` unchanged |
| **P2-A-17** | `SourceRef.bounding_box` is a 4-tuple; PaddleOCR-VL-1.6 emits quads/polygons for skewed pages | `schema/field.py`; PaddleOCR docs | Story 1b | Decided — envelope on the element and `SourceRef`; polygon kept on the OCR adapter's chunk payload; no schema change |
| **P2-A-18** | `plan.md` Decision 4's per-page audit compares against "the raw PyMuPDF text count"; PyMuPDF is AGPL and was removed from `pyproject` with pypdfium2 named as the fallback | `plan.md` Decision 4; `pyproject.toml` parse extra comment | Story 1a | Decided — pypdfium2; Track 0's docs sweep corrects the plan's sentence |
| **P2-A-19** | CI runs `pgvector/pgvector:0.8.6-pg16`; `plan.md`'s technical context says PostgreSQL 18 + pgvector 0.8.5. Nothing in `sql/` needs 17+ features today | `.github/workflows/ci.yml`; `plan.md` L18 | Recorded | Recorded — the first PG18-only feature must bump the CI image in the same PR |
| **P2-A-20** | Phase 1's stub `ingest()` returns `list[ComponentInstance]`; C8 says components are projections over claims, and agent-topology's `extract` fan-out unit is document × category, not document | `services/ingestion/__init__.py` L35–52; `tasks.md` C8 invariant | Story 1a | Decided — `ingest()` returns `IngestResult(document, elements, parse_events)`; extraction is its own stage |
| **P2-A-21** | Story 7 adds `sql/13_access_denylist.sql`; the master's Track 4a row owns `sql/10`–`12`. Two tracks writing numbered files need a reservation so numbers do not collide in parallel worktrees | phase-2-execution.md tracks table | Track 0 | Decided — Track 0 reserves numbers in `sql/README.md`: `10`–`12` Story 4, `13` Story 7, `14+` unassigned; `sql/proposals/` is outside the apply order |
| **P2-A-22** | `Settings.compose_gate_threshold` is `le=HIGH` so `CRITICAL` cannot disable the gate; Story 4's compose handler must not add an env override that bypasses it, and `--accept-incomplete` is a **recorded** decision, not a threshold change | `config.py`; Decision 2 | Story 4b | Recorded — asserted by the existing `test_settings_bounds` and Story 4's `test_accept_incomplete_records_override_run_event` |
| **P2-A-23** | The verification pass of 2026-09-03 found the vertical slice's `persist_vertical_slice` appends events in a loop over `audit.append_event`, not via `write_and_append_event`. Both are correct; Story 4's repositories follow the slice's multi-event pattern, and `write_and_append_event` stays as the single-event primitive | `services/vertical_slice.py` L355–366 | Recorded | Recorded — no change |
| **P2-A-24** | **"Six ports" is stated in eleven places** — `plan.md` Decision 10 heading, ADR-001 (three times), `docs/current-state.md` (twice), `docs/requirements-traceability.md` NFR-04, `adapters/registry.py`, `adapters/__init__.py`, both `tests/port_contracts/*` module docstrings. D-25 and D-26 make it **eight**. Phase 1 Track 0's lesson: sweep for meaning, not filenames | grep `six port\|six Protocol\|Six Protocol` on 2026-09-03 | Track 0 | Open — the sweep is part of the P2-C3/P2-C4 PR; a grep test pins the count at zero afterwards |
| **P2-A-25** | D-29 amends D-14's `policy` shape. A reader of D-14's table alone would build a policy without `thresholds` and hash differently — the Track 1a "table alone" trap | D-14 vs D-29 | Done | Recorded — D-14 now carries an "Amended by D-29" callout; the golden re-baseline is Story 6's |
| **P2-A-26** | D-16's cost note still read "WP-H/WP-F own that migration" after D-27 assigned it to Story 4a | D-16 "What it costs" | Done | Recorded — cross-reference added to D-16 |
| **P2-A-27** | `.env.example` has `PROCUREMENT_LLM_MODEL=` blank; D-22 names a default. Same for every setting the ratified decisions introduce (`ocr_*`, `reranker_*`, `web_search_provider`, `oidc_*`, `classification_threshold`, `access_review_max_age_days`, `PROCUREMENT_GOLD_CORPUS_DIR`) | `.env.example`; D-19..D-30 | each story | Open — folded into P2-A-7; each story's PR adds its lines with the ratified default as the example value |

## Coverage check against the seven stories

Every FR/NFR/AC row that `docs/requirements-traceability.md` marks `open` or `declared` has a
home:

| Row | Story |
|---|---|
| FR-ING-01..10, AC-1, AC-5 (caller half) | 1 |
| FR-RAG-01..05, NFR-03 (retrieval), AC-8 | 2 |
| FR-WEB-01..05, AC-2 (end to end) | 3 |
| C8 Python half, WP-I, NFR-05 (application), NFR-06/07 (measured), audit `run_event` | 4 |
| FR-HITL-03..06 (service + UI), D-10 | 5 |
| FR-OUT-01, FR-OUT-04..06 finish, AC-3, AC-6 layout, AC-7 (LibreOffice half) | 6 |
| C7 facts, D-15 outcomes | 7 |

Not homed in Phase 2 and stated as such in the master: tabs 12–13 **content** (Phase 3 specialist
team); D-4 threshold tuning (needs the gold set); `sql/` migration tooling.

## Things the stories were checked for and do not do

- No story adds a seventh `Stage`, an ANN index, a workflow framework, an async port, a global
  tolerance, a self-reported confidence, a majority vote, an Excel import path, a `Decimal.normalize()`,
  an enum `repr()` in hashed order, a hand-rolled JCS, or pvlib's bundled CEC data.
- No story edits `tests/fixtures/workbooks/two-supplier-pv-store.json` except Story 6's single
  structural re-baseline (Q-15), which the story requires to be reviewed as "one added key".
- No story writes `app.allow_restricted` outside `services/store/principal.py`.
