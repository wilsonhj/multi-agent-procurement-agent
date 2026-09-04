# Story 1 — Ingest and extract (WP-A, WP-B)

**Tracks:** 1a parser router and document paths · 1b OCR · 1c extraction and confidence · 1d gold set
**Teams:** 2 (1a, 1b) · 3 (1c, 1d harness) · human (1d content)
**Needs:** Track 0 (P2-C1, P2-C8). 1c additionally needs 1a's committed parsed-elements fixture.
**Status:** proposed 2026-09-03

**Story.** A procurement lead uploads a set of supplier files — text-layer PDFs, image-only scans,
a photographed spec sheet, Excel price lists, Word contracts. Each file is identified by content,
parsed by the right engine, classified, labelled for access, and its comparison-relevant facts are
extracted as **claims** with page-level provenance, a condition, a confidence, and a routing
decision. Nothing silently becomes a number.

**Done means.** `services.ingestion.ingest()` and `services.extraction.extract()` run end to end
on the committed synthetic fixtures and on the gold corpus when present; AC-1 is demonstrated on
at least one image-only PDF from the gold set; AC-5 is demonstrated by re-ingesting an unchanged
document through the real path; every claim written carries a `P2-C8` `extractor_version` and an
on-contract key.

---

## Controlling decisions

| ID | Rule this story must build to |
|---|---|
| Decision 4 | Content-signature routing; spreadsheets bypass document parsing; text-layer PDFs never go to a VLM; three-tier fallback; `PARSE_FAILED` recorded, never dropped; **no `pdfmux` dependency** |
| Decision 7 | vLLM structured outputs; `json_schema` mode; logprobs over the **value span only**; banned: self-reported confidence, N=5 self-consistency |
| D-1 | `condition` extracted beside value/unit; unqualified PV electrical ⇒ `stc` per open-decisions §2; **never default** inverter `rated_ac_power` temperature, BESS basis/side, RTE boundary, cycle-life EOL |
| D-3 | Tier A never auto-accepted; hard gates bypass the score; ≥99 % precision target; 15–25 % review budget |
| D-4 / D-4a | Identity resolution stages; never auto-merge on manufacturer + model without electrical corroboration |
| D-5 | NFKD, ligatures, `–`→`-`, `℃`→`°C`; **decimal comma for IEC-sourced documents**; `%/°C ≡ %/K` with no conversion |
| D-6, D-7 | Transformer regime detection before comparison; Dyn1 ≠ Dyn11; BESS boundary strings evaluated multiplicatively |
| D-11 | Gold set first; no public benchmark; Trina datasheets are image-only |
| D-15 | Label at ingest from FR-ING-06 classification; **below-threshold classification labels restricted** |
| C2, C8 | Keys validated where used as keys (`ComponentInstance.fields`, `commit_claims`); claims are immutable proposals |
| ADR-001 §6 | No prompt optimisation before the gold set exists |

## Code surface today

- `services/ingestion/__init__.py`: `detect_content_signature(data) -> str`, `classify_document(elements) -> DocumentType`, `normalize_unit(raw) -> tuple[float | None, str | None]`, `ingest(data, source_uri, *, parsers, ocr, llm) -> tuple[SourceDocument, list[ComponentInstance]]` — all raise.
- `ports/`: `ParserPort.supports(content_signature) / parse(data) -> list[ParsedElement]`; `OCRPort.needs_ocr(elements) / recognize(data)`; `LLMPort.extract(*, prompt, context, json_schema) -> dict | None`. `ParsedElement(kind, text, page)` only — **no bbox, no table structure, no page quality** (P2-A-1).
- `adapters/{parser,ocr,llm}/memory.py` references; `adapters/registry.py` `AdapterEntry` with capability accounting; `UNXFAILABLE = {ACCESS_FILTERING, INSUFFICIENT_EVIDENCE}`.
- `schema/registry.py`: 125 `FieldSpec` over 124 contract keys, bidirectionally tested; `SourceRef(document_id, page, section, extractor_version, bounding_box: tuple[float,float,float,float] | None, url, page_title, retrieved_at, source_authority)`.
- `services/claims`: `FieldClaim` (frozen; `extractor_version` required; `human:` rule), `canonical_claims`, `project`, `commit_claims(field_name, claims, *, writer, category)`.
- `services/confidence/`: Tier A table derived from the registry; `fuse()` / `requires_review()` exist; **no `threshold_for()` and no extraction scorer**.
- `services/vertical_slice.py`: the CSV-only path; **stays as is** — it is the executable proof of the contracts, not the production route.
- `Settings`: `max_concurrent_parse=4`, `max_concurrent_llm=8`, `llm_endpoint/model/api_key`; **no OCR endpoint** (P2-A-15).

---

## A — Track 1a: parser router and document paths

### A.0 · P2-C1 / D-23, consumed (Track 0 writes it)

`ParsedElement` gains, all optional with `None` defaults:

- `bbox: tuple[float, float, float, float] | None` — axis-aligned envelope in page points, origin top-left. Polygons from OCR are reduced to their envelope here; the polygon itself stays on the OCR adapter's `recognize()` payload (not on `ParsedElement`, not on `ChunkRecord`, not on `SourceRef`).
- `table: TableData | None` — present iff `kind == "table"`:

```python
@dataclass(frozen=True)
class CellSpan:
    row: int  # 0-based origin of the merged region
    col: int
    rowspan: int  # >= 1
    colspan: int  # >= 1


@dataclass(frozen=True)
class TableData:
    rows: tuple[tuple[str, ...], ...]
    header_rows: int
    caption: str | None
    merged: tuple[CellSpan, ...]
```

  Both types live in `ports/__init__.py` next to `ParsedElement`.
- `page_quality: float | None` — 0–1, OCR/parser confidence for the page region; D-3's "low-quality scan" hard gate reads it.
- `role: Literal["body", "furniture", "footnote", "caption"] = "body"` — FR-ING-05 headers/footers/footnotes.

Kinds stay `heading | body | table | figure`. The conformance pin on `__annotations__` is updated in the same PR (Track 0). A `TableElement` subclass is **not** introduced — one carrier, optional fields, so every consumer's `isinstance` check stays valid.

### A.1 · Content-signature router (FR-ING-01)

`detect_content_signature(data) -> str` returns a media type from **magic bytes only**:

| Bytes | Media type |
|---|---|
| `%PDF-` | `application/pdf` |
| `PK\x03\x04` + `[Content_Types].xml` naming `xl/` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| `PK\x03\x04` + `word/` | `…wordprocessingml.document` |
| `\xff\xd8\xff`, `\x89PNG`, `II*\x00`/`MM\x00*`, `BM`, `RIFF….WEBP`, `ftypheic/heix/mif1` | the matching `image/*` |
| none of the above, valid UTF-8/Latin-1, ≥ 2 lines with a consistent delimiter | `text/csv` |
| otherwise | raise `UnsupportedContent(signature)` — **never fall back to the extension** |

Verify: a `.pdf`-named PNG routes as `image/png`; a `.csv`-named XLSX routes as spreadsheet; a zip that is neither raises.

### A.2 · Spreadsheet path (FR-ING-02) — `adapters/parser/spreadsheet.py`

openpyxl (already a core dependency) with `data_only=False` **and** a second `data_only=True`
pass so formulas keep both text and cached value; pandas is **not** required and is not added to
core. Per sheet → one `ParsedElement(kind="table")` with `TableData` preserving sheet name as
`caption`, header rows detected by type-homogeneity of row 1, merged ranges in `merged`, numbers
kept as numbers in `rows` via `repr()` — the **same float rule as D-14 / Decision 8c** (do not
import `encode_value` into the parser; the rule is "what `float.__repr__` would print"). `page`
is the 1-based sheet index; `section` on the claim is the sheet name.

CSV routes here too, via `csv.Sniffer` for the dialect. The sanitized-PV CSV fixture must parse
through this adapter to the same claims `vertical_slice` produces — that is the compatibility
test.

### A.3 · Text-layer PDF and Word path (FR-ING-03, FR-ING-05) — `adapters/parser/docling.py`

`docling>=2.115,<3`, lazy import inside the factory. `DocumentConverter` with TableFormer
`ACCURATE`, OCR **off** (the OCR adapter is a separate engine per Decision 4). Map
`DoclingDocument` items → `ParsedElement`: `SectionHeaderItem` → heading, `TextItem` → body,
`TableItem` → table with `TableData` from `table.data`, `PictureItem` → figure; `page` from
`item.prov[0].page_no`, `bbox` from `prov.bbox`, `role="furniture"` for items under
`doc.furniture`, `footnote`/`caption` from the Docling label.

**Word documents (D-19).** Docling populates no `page_no` for `.docx`. Adopted default: convert
`.docx` → PDF with LibreOffice headless (`soffice --headless -env:UserInstallation=file:///tmp/<uuid>
--convert-to pdf`) and parse the PDF, so `page` is real; keep the `.docx` bytes as the stored
document (its `content_hash` is the identity), and record `section` (heading path) on every
element regardless of format. If `soffice` is absent the adapter declares `PAGE_NUMBERS` as an
`UNIMPLEMENTED` absence for Word and elements carry `page=None` — loud in the conformance matrix,
never silent. The conversion subprocess is **isolated**: no network, CPU/memory/time caps, a
throwaway `UserInstallation`, and a pinned LibreOffice version in the Story 6 CI image. It does
not inherit the worker's DB credentials.

### A.4 · Per-page audit and the three-tier fallback (Decision 4, A.6)

`services/ingestion/audit.py`: for each page, compare the parser's character count against a raw
text probe (**pypdfium2**, BSD-3/Apache-2.0 — PyMuPDF is AGPL and was removed from `pyproject`;
P2-A-18). Flag a page when: zero characters; < 10 % of the probe count; or a layout-detected table
region yielded zero cells. Flagged pages go to the next engine (OCR, Track 1b). A page that fails
every engine becomes a `ParsedElement(kind="body", text="", page=n, page_quality=0.0)` **and** a
`parse_failure` audit intent — the taxonomy already has the event type. Never omit the page.

### A.5 · Dual-parse reconciliation on table-critical pages (A.7)

When a page holds a table and OCR is available, run both engines, align cells by row/column
index, and emit per-cell agreement as `page_quality` on the table element **and** as a feature
record for 1c (`services/extraction/features.py::ParserAgreement`). This is a confidence feature,
not a log line, and disagreement marks the cell contested — it never picks the value.

### A.6 · Classification (FR-ING-06) and the access label (A.10, D-15)

`classify_document(elements) -> DocumentType` — rules first (title/heading tokens, presence of
price columns, signature blocks, "Warranty" headings), then `LLMPort.extract` with a
`choice`-constrained schema over the eight `DocumentType` values when rules are indecisive. The
result is a `(DocumentType, confidence)`; below `Settings.classification_threshold` (new,
default 0.90) the document is **labelled restricted** and routed to review. Label map per D-15:
contract/TOS, purchase order, pricing, terms and conditions, warranty → `access_restricted=True`;
spec sheet, technical documentation, environmental regulation → `False`. The label is set once at
ingest; Story 7's register check (D-30) warns, never blocks. Track **1a** owns the check inside
`ingest()` and the test `test_stale_register_warns_and_labels_restricted_never_blocks`; Story 7
owns the register file and the setting.

### A.7 · Content hash, stable IDs, idempotent re-ingest (FR-ING-09, NFR-05, AC-5)

`content_hash = "sha256:" + hexdigest(bytes)` (the slice's convention); `document_id` is a
deterministic function of the hash so re-ingest produces the same row and
`INSERT … ON CONFLICT (content_hash) DO NOTHING` (already the DDL's design) makes the store half
a no-op. The **application half**: `ingest()` returns early with the existing `SourceDocument`
when the hash exists and emits **no** `document_ingested` event the second time. That is the
AC-5 test the traceability record still calls "open" on the caller side.

### A.8 · Text normalisation (D-5, A.11) — `services/ingestion/normalise.py`

NFKD; ligature folding; `–`/`—` → `-`; `℃` → `°C`; `μ`/`µ` unification; decimal-comma
handling keyed on **document locale evidence** (IEC standard citations, `,` as the only separator
in a numeric column, EU supplier country): `10,5 kV` → 10.5. `normalize_unit(raw)` returns
`(value, canonical_unit)` and keeps `verbatim_value` untouched on the claim. `%/°C`, `%/K`,
`%/degC` are **aliases**; there is no temperature converter in this module and a test asserts the
module has no code path that adds 273.15.

### A.9 · `ingest()` composition

```python
def ingest(data, source_uri, *, parsers, ocr, llm, principal, store) -> IngestResult
```

Router → parser → per-page audit → OCR fallback → classification → label → hash/dedup → persist
`SourceDocument` (Story 4 repository) → return `IngestResult(document, elements, parse_events)`.
`ingest()` does **not** extract: extraction is Track 1c's stage, invoked by the runner (Story 4),
because agent-topology's fan-out unit for `extract` is document × category field set, not
document. The Phase 1 stub returns `tuple[SourceDocument, list[ComponentInstance]]`; that return
is removed (components are projections over claims, never an ingest output — P2-A-20).

---

## B — Track 1b: OCR adapter

`adapters/ocr/paddleocr_vl.py`: HTTP client for the `paddleocr genai_server --backend vllm`
service (PaddleOCR-VL-1.6-0.9B), `pipeline_version="v1.6"`, `layout_shape_mode="quad"`.
`needs_ocr(elements)` is the per-page audit's verdict (A.4) — the memory reference's
"< 40 chars/page" heuristic stays as the reference behaviour. `recognize(data)` returns elements
with `bbox` = quad envelope, `page_quality` = the layout model's `score`, tables from the
recognised HTML/markdown table into `TableData`. Skew/rotation are the engine's job; the adapter
asserts orientation metadata is preserved (FR-ING-04). Degraded tier `adapters/ocr/rapidocr.py`
(RapidOCR + PP-StructureV3, CPU) registers with `TABLE_STRUCTURE` as an honest absence and every
element flagged `page_quality ≤ 0.5` so D-3's hard gate routes its output to review. GLM-OCR is
the documented hot-swap; not built.

New settings: `ocr_endpoint: str | None`, `ocr_model: str | None`. `.env.example` gains both
(P2-A-15).

---

## C — Track 1c: extraction and confidence

### C.1 · Extraction models from the registry (B.2)

`services/extraction/models.py` generates one Pydantic model **per category** from
`schema/registry.py` `FieldSpec`s at import time: each contract key becomes an optional field of
`ExtractedValue(value, unit, verbatim, condition, source: SourceRef-shaped locator, evidence_span)`.
Types come from the registry (`list[str]` keys → lists). `model_json_schema()` is what goes to
vLLM. No hand-written per-category model exists; the registry's bidirectional test is what keeps
the schema on-contract. Off-contract keys cannot be emitted because they are not in the schema.

### C.2 · LLM adapter — `adapters/llm/vllm_openai.py` (B.1)

`openai` client against the vLLM OpenAI-compatible endpoint. Request: `response_format=
{"type":"json_schema","json_schema":{"name":..,"schema":..,"strict":True}}`, `logprobs=True`,
`top_logprobs=5`, `temperature=0`. Use Instructor `Mode.JSON_SCHEMA` only through
`create_with_completion` so the raw completion is retained; **if `choices[0].logprobs` is `None`
the adapter raises** — a silent loss of the confidence signal is the failure mode Decision 7
names. `extract()` returns `None` on the model's explicit insufficient-evidence result (a
schema-level `{"insufficient_evidence": true}` alternative) — the `INSUFFICIENT_EVIDENCE`
capability that may not be xfailed.

**Documented server contract** (in the adapter docstring and `docs/development.md`):
`vllm serve <model> --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}'
--logprobs-mode raw_logprobs`. The first flag is the termination fix for Qwen3-Instruct-2507
under `json_schema`; the second keeps logprobs pre-mask. Default model per D-22.

### C.3 · Two structurally asymmetric reads (B.6)

`field_guided(document, category)` — "extract these N fields"; `document_guided(document)` —
"list every specification present with its verbatim text and location". Agreement per field is a
feature; disagreement is a feature **and** a D-3 hard gate. Both run over retrieved context when
Story 2 is present and over the full parsed document when it is not (documents are small; NFR-06).

### C.4 · Plausibility gates (B.5) — `services/extraction/plausibility.py`

As data, per category, from D-2's cross-validation rules: `Voc > Vmp`, `Isc > Imp`,
`Pmax ≈ Vmp × Imp ± 0.5 %`, `PTC/STC ∈ [0.87, 0.96]`, `|γPmax| ∈ [0.15, 0.70]`, γPmax and βVoc
negative, αIsc positive, c-Si efficiency ≤ 27 %, transformer regime detected before any MVA
comparison (D-6), BESS boundary string parsed before any RTE (D-7). A failed gate is a feature
**and** forces review; it never edits the value.

### C.5 · Claims out, with `P2-C8` versions

Every extracted value becomes a `FieldClaim` with `extractor_version =
f"{pipeline}@{version}"` where `pipeline` names the engine chain (`docling+qwen3-30b-a3b`) and
`version` is a hash of the prompt template + schema + model id — so a prompt change is a new
extractor and old claims are superseded, never edited. The string must match P2-C8's machine
regex. `source_tier=system_of_record`. `condition` resolved per open-decisions §2
(`Condition.derived` records what was filled). `confidence` from C.6. Claims go to the store
through `commit_claims` (the reducer) — never a direct table write from a worker. `gold:` is
refused on this path (D-24).

### C.6 · Cold-start confidence and `threshold_for()` (B.7, B.10, A-11)

`services/confidence/score.py`: rule-based fusion of grounding (verbatim/near-verbatim match in
the parsed source), parser agreement (A.5), cross-read agreement (C.3), value-span logprob
statistics (**not** structural tokens), plausibility, field type. Output in [0, 1]. Tier A fields
return a score but `threshold_for(field_name)` returns `1.0 + ε` for them, so nothing
auto-accepts. Tiers B/C get provisional τ (0.95 / 0.90) until the gold set fits the risk–coverage
curve; the τ table is a versioned data file and `ProjectionPolicy` embeds it **by value** (D-29).
`flags_for()` keeps its float parameter; Story 6 consumes `threshold_for`.

Banned by test: no call site reads a model-reported confidence; no N-sample voting exists.

### C.7 · Human corrections as labels (B.8)

Every `resolution` row (Story 5) is exportable as a label pair (extracted, decided) by
`services/confidence/labels.py`; the export is read-only over the audit and resolution tables.

---

## D — Track 1d: the gold set (D-11, B.9)

**Content is human work.** 30–50 supplier documents, seeded deliberately with poor scans, image-only
PDFs (Trina), photographed pages, IEC decimal-comma sources, one transformer and one BESS
datasheet. Documents are **not** committed (confidential/copyright); they live at
`PROCUREMENT_GOLD_CORPUS_DIR` and the manifest keys them by `content_hash`.

**Harness is agent work.** `tests/fixtures/gold/manifest.json`; label files as `FieldClaim` lists
with `extractor_version="gold:<annotator>"` (D-24); `tests/test_gold_set.py` skips without the
corpus dir (the DSN pattern) and, when present, reports per-field exact-match and the D-3
precision at coverage; CI on a self-hosted runner fails on silent skip the way the `sql` job does.
The metric-result contract is ADR-001 §5.

---

## Verify

Minimum new tests: 60. Named:

- `test_router_ignores_extension` (3 cases) · `test_router_raises_on_unknown_signature`
- `test_spreadsheet_adapter_reproduces_vertical_slice_claims` — same CSV, same claims
- `test_docling_adapter_every_element_has_page` — against a committed synthetic 2-page PDF (`tests/fixtures/ingestion/synthetic-pv-datasheet.pdf`, generated once by LibreOffice from a committed `.odt`, sha256 pinned; no PDF-writing dependency is added to the project)
- `test_word_path_yields_pages_via_pdf_conversion` — skips if `soffice` absent, and the conformance matrix shows the absence
- `test_page_audit_flags_zero_char_page` · `test_failed_page_is_recorded_not_dropped` (asserts a `parse_failure` intent)
- `test_classification_below_threshold_labels_restricted` (D-15 fail-closed)
- `test_stale_register_warns_and_labels_restricted_never_blocks` (D-30; 1a owns this test)
- `test_soffice_conversion_has_no_network_and_uses_throwaway_profile` (D-19 isolation; may skip
  without `soffice`, must not skip the profile/env assertions when the binary is present)
- `test_reingest_unchanged_document_is_a_noop_in_application` (AC-5 caller half; live, DSN-gated)
- `test_decimal_comma_iec_document` — `10,5 kV` → 10.5 · `test_percent_per_kelvin_is_alias` · `test_no_temperature_conversion_path_exists`
- `test_ocr_elements_carry_bbox_and_quality` (recorded response) · `test_degraded_tier_forces_review`
- `test_extraction_model_keys_equal_registry_keys` (per category) · `test_offcontract_key_cannot_be_emitted`
- `test_llm_adapter_raises_when_logprobs_missing` · `test_llm_adapter_returns_none_on_insufficient_evidence`
- `test_cross_read_disagreement_forces_review` · `test_each_plausibility_gate` (one per rule)
- `test_extractor_version_scheme` (P2-C8 regex) · `test_prompt_change_is_new_extractor`
- `test_tier_a_never_auto_accepts` · `test_threshold_table_is_embedded_by_value_in_policy`
- `test_no_self_reported_confidence_is_read` (grep-level guard over `services/extraction`)
- Conformance: `parser:spreadsheet`, `parser:docling`, `ocr:paddleocr_vl`, `ocr:rapidocr`, `llm:vllm_openai` registered with complete capability accounting; matrix test's "all references" assertion flips to the NFR-04 evidence claim.

**Gates at merge:** four local gates; `sql` job green (A.7 touches live tests); passed count on
`main` + ≥ 60.

## Traps written down so they are not rediscovered

- `ParsedElement.page` is 1-based everywhere; the OCR reference already does this.
- A Docling `TableItem` with empty `prov` is a **Word** table — do not "fix" it by guessing page 1.
- `repr()` for numbers in `TableData`, never `str()` or `%.16g` (same float rule as D-14 /
  Decision 8c; not an import of `schema.encoding.encode_value`).
- Logprob-mean over the whole JSON is exactly the metric D-3 says fails; the span mask must exclude grammar-forced tokens.
- `commit_claims` refuses dropped condition groups (`StoredValueLossError`); an extractor that stops emitting a condition it emitted before is a defect, not a cleanup.

## Out of scope

Prompt optimisation (ADR-001 §6), identity-resolution threshold tuning (D-4 Stage 4), tabs 12–13
specialist extraction (Phase 3), retrieval-augmented extraction wiring (Story 2 provides it; 1c
must work without it).

---

*Clarifications Q-5 – Q-16 cited by this story were ratified on 2026-09-03 as D-19 – D-30 in [clarifications.md](../clarifications.md); the D-entries are the authority.*
