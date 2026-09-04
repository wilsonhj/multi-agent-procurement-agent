# Phase 2 research — stack re-verification, 2026-09-03

**Purpose.** [plan.md](../plan.md) fixed the stack on 2026-07-28. Before Phase 2 pins any of
it into code, every load-bearing external claim was re-checked against the vendor's own
documentation as it stood on 2026-09-03. Each row records what was checked, what was found, and
what changes for the story that depends on it. Nothing here re-opens a plan decision; where a
finding contradicts the plan, it is listed as a Phase 2 clarification in
[clarifications.md](clarifications.md), not silently patched.

Sourcing caveat carried from [open-decisions.md](../open-decisions.md): vendor documentation and
changelogs were read; no standard, regulation or supplier datasheet was read verbatim.

> **2026-09-03:** the questions this research opened (Q-5 – Q-8) were ratified the same day as
> D-19 – D-22 in [clarifications.md](../clarifications.md). The Q-numbers below are historical
> pointers; the D-entries are the authority.

---

## Findings by story

### Story 1 — ingest and extract

| Claim in plan | Checked against | Finding | Consequence |
|---|---|---|---|
| Docling 2.115.0, MIT, MSWord backend, TableFormer ACCURATE | Docling `CHANGELOG.md` | Current release **v2.124.0 (2026-08-31)**. Pin floor `docling>=2.115` still valid. v2.121 extended `PdfPageBackend` and "improved OCR input selection" — relevant to A.6's per-page audit | Keep the floor; add an upper bound `<3` because the `DoclingDocument` schema is versioned and a major would move provenance |
| Every element records its page number (FR-ING-03) | Docling `DoclingDocument` concept doc; issues #775, #2196 | Page is `item.prov[i].page_no`; bbox is `prov.bbox`; character span is `prov.charspan`. **For `.docx`, `prov` is frequently empty** — Word has no page model, so Docling cannot populate `page_no` for Word tables | FR-ING-05 promises "source, page and caption" for Word tables. This is **not achievable from `.docx` directly**. Clarification **Q-5** proposes the rule |
| PaddleOCR-VL-1.6 on vLLM, Apache-2.0 | PaddleOCR-VL usage tutorial | **PaddleOCR-VL-1.6 released 2026-05-28**; architecture identical to 1.5 ("seamless migration at zero cost"). Served by `paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --backend vllm`; client `PaddleOCRVL(pipeline_version="v1.6", vl_rec_backend="vllm-server", vl_rec_server_url=...)`. Layout boxes available as `rect`, `quad` or `poly` via `layout_shape_mode` | Plan is current. Spec the OCR adapter to request `layout_shape_mode="quad"` for skew (FR-ING-04) and to store the polygon verbatim; `SourceRef` keeps `page` + `section`, the polygon goes on the chunk |
| vLLM structured outputs via xgrammar, `json_schema` mode, `logprobs` on | vLLM structured-outputs docs; engine-args reference; PR #21398 | **`guided_json` and friends were removed in vLLM 0.12.0.** The request carries either the portable `response_format={"type":"json_schema","json_schema":{"name":..,"schema":..}}` or the vLLM envelope `extra_body={"structured_outputs":{"json":..}}`. Backend is a **server launch flag** `--structured-outputs-config.backend` (default `auto` → xgrammar for JSON), not a per-request field. Separately, `--logprobs-mode` (default `raw_logprobs`) decides whether returned logprobs are **before** or **after** logit processors, and the grammar bitmask is a logit processor | Decision 7 survives intact and gains two pins: request via `response_format`, and launch with `--logprobs-mode raw_logprobs` **explicitly**, because `processed_logprobs` would report the post-mask distribution, on which every grammar-forced token — and every value token whose alternatives were masked — saturates. That is the exact failure D-3 calls "naive logprob-mean" |
| Extraction LLM — **`plan.md` never names one**; `.env.example` has only `PROCUREMENT_LLM_MODEL=` | Qwen3 repository and model cards; QwenLM/Qwen3 issue #1700 | The whole Qwen3 open-weight line is Apache-2.0, which passes the licence gate (Llama's community licence does not). `Qwen3-30B-A3B-Instruct-2507` (MoE, 3.3 B active, 262 K native context, `vllm>=0.8.5`) is the obvious self-hostable default for schema-constrained extraction; a dense `Qwen3-32B` is the alternative where MoE serving is unwelcome. **Known trap:** the Instruct-2507 checkpoints do not terminate under `json_schema` structured output unless vLLM is launched with `--structured-outputs-config '{"disable_any_whitespace": true, "backend": "xgrammar"}'` | Clarification **Q-8** proposes the default. The launch flags become part of the extraction adapter's documented server contract, alongside `--logprobs-mode raw_logprobs` |
| Instructor in `json_schema` mode, never `TOOLS` | Instructor `modes-comparison.md`; issue #1884 | `Mode.JSON_SCHEMA` is a core mode and is accepted by `from_openai` in Instructor v2. It sends `response_format` of type `json_schema`. Instructor's `create()` returns the parsed model only; the raw completion (and therefore `logprobs`) comes from `create_with_completion()` | Spec B.1 to call `create_with_completion` and to fail the request if `choices[0].logprobs` is `None` — a silent loss of the confidence signal must be loud |

### Story 2 — index and retrieve

| Claim in plan | Checked against | Finding | Consequence |
|---|---|---|---|
| pgvector 0.8.5; `hnsw.iterative_scan = relaxed_order` as a safety default | pgvector README at v0.8.6; PostgreSQL news | **0.8.6 is current.** `iterative_scan` semantics unchanged: default `off`, `relaxed_order`/`strict_order`, bounded by `hnsw.max_scan_tuples` (20 000). Decision 3a (no ANN index) stands; the setting remains a belt for a future index | `sql/01` keeps the GUC. Story 2 adds no index. C.9's `len(results) == k` regression test is unchanged in importance |
| Qwen3-Embedding-4B at 1024 dims via MRL truncation + renormalisation | Qwen3-Embedding-4B model card; TEI README | MRL is native: "user-defined output dimensions ranging from 32 to 2560". TEI 1.7.2+ serves it; the `/embed` endpoint does **not** reliably accept a `dimensions` parameter | Truncate to 1024 and L2-renormalise **client-side in the adapter**, as the plan already says. The port conformance suite must assert `len(vector) == 1024` and unit norm, or a server that starts honouring `dimensions` would silently double-truncate |
| bge-reranker-v2-m3 on TEI, top-50 → top-5–8 | TEI README; model card | Served by TEI `/rerank` with `{"query":..,"texts":[..]}`. Latency figures remain vendor/secondary-source with unstated batch size (plan open item 4) | Unchanged. Reranker adapter is a thin HTTP client behind `RerankerPort`; benchmark before any SLA |
| `pg_trgm` for part-number tolerance, `tsvector` for lexical recall, RRF k=60 | PostgreSQL contrib docs (unchanged) | Ships with PostgreSQL under the PostgreSQL licence | Unchanged |

### Story 3 — gap-only web enrichment

| Claim in plan | Checked against | Finding | Consequence |
|---|---|---|---|
| `PROCUREMENT_WEB_SEARCH_API_KEY` exists in `.env.example`; **no provider is chosen anywhere** | Brave Search API ToS (read); Tavily and SerpAPI terms (secondary) | Brave's API terms forbid storing or caching Search Results "except for transient storage required for operation", forbid redistribution, and forbid use "to create, evaluate, train, re-train, fine-tune or otherwise improve" AI models; storage rights exist only on bespoke plans. Tavily/SerpAPI restrict competitive use and resale; SerpAPI carries a US "Legal Shield" for scraping liability on paid plans | **FR-WEB-02 requires the query, URL, page title and retrieval timestamp to be logged for reproducibility, and NFR-02 makes that log immutable.** Under Brave's general terms that log is arguably prohibited storage. This is a legal reading, not an engineering one → clarification **Q-6**. The engineering mitigation that works under any provider: persist the **fetched page** (publisher content, under the publisher's terms) and the **query string**, and treat the provider's result list as transient — never store rank, snippet or provider metadata |
| CEC equipment list as an authority tier; pvlib's bundled data frozen at 2019 | [D-8/D-8a](../clarifications.md) | Unchanged; not re-verified (CEC domain returned 403 on the original research and was not retried) | Unchanged |

### Story 4 — persistence and runner

| Claim in plan | Checked against | Finding | Consequence |
|---|---|---|---|
| psycopg 3 sync API; `FOR UPDATE SKIP LOCKED` worker loop | Decision 1 / Decision 10 | Both are PostgreSQL and psycopg core features; no version risk | Unchanged |
| DBOS Transact as the alternative if the team would rather not own durability | Decision 1 | Not re-verified; Decision 1's chosen path is the hand-rolled state machine and `sql/08_job.sql` already implements its table | Not adopted. Listed so nobody re-proposes it inside Story 4 |

### Story 5 — review service and UI

No stack decision exists in `plan.md` for the reviewer surface. WP-F.5 says only "you will
build this regardless". The recommended default is in clarification **Q-7**; it was chosen
under the licence gate (MIT/BSD/Apache only), Decision 10 (sync ports; per-process concurrency),
and D-15 (clearance derived from the OIDC subject).

### Story 6 — workbook finish

| Claim in plan | Checked against | Finding | Consequence |
|---|---|---|---|
| `openpyxl==3.1.5`, exact pin | PyPI | **3.1.5 (2024-06-28) is still the latest stable release**; 3.2.0b1 (2022) is older. No upgrade pressure | Pin stands. The renderer-regression hash keeps its meaning |
| G.6 "open in real desktop Excel and LibreOffice" is gating and unrun | LibreOffice headless docs and the community cheat-sheet | `soffice --headless --convert-to pdf --outdir <dir> <file>.xlsx` runs in CI. Two traps: the profile lock (give each run `-env:UserInstallation=file:///tmp/<unique>`), and **exit codes lie** — verify the output file exists and is non-empty | Story 6 can automate the **LibreOffice half** of G.6 in CI: convert, assert a PDF exists with page count > 0, and assert the sheet count and tab names round-trip through `openpyxl.load_workbook`. The **desktop Excel half stays a human gate** and the spec says so |
| Hidden state columns; `auto_filter.ref` must span them; no blank column | Decision 8a | Unchanged | Both assertions belong in the generator, not only in tests |

### Story 7 — access-label facts

Not a research item. Q-1 in [phase-1-execution.md](../phase-1-execution.md) is unchanged: someone
reads the NDAs and the evaluator roster. Story 7 specifies what the code must be **ready** to
do for each of the three outcomes so that the answer, when it arrives, is a configuration and
a migration rather than a redesign.

---

## Items deliberately not re-verified

- Licence *names* for the rejected components in `plan.md`'s licence gate. The rejections stand
  regardless; the names matter only for procurement paperwork, and the plan already says to read
  the `LICENSE` file before that point.
- IEEE 2800 TRD limits and the three tax-incentive frameworks (AC-6). Regulatory content; the spec
  says it requires counsel confirmation.
- Reranker latency. Plan open item 4; still secondary-source.

## What this changes in the plan

Nothing is reversed. Five pins were added (Docling `<3`; vLLM `response_format` +
`--logprobs-mode raw_logprobs` + the xgrammar/`disable_any_whitespace` launch config; Instructor
`create_with_completion`; client-side MRL truncation asserted by the conformance suite). The two
questions this research opened (**Q-5** Word page numbers, **Q-6** web-result storage rights) and
the two stack choices the plan never made (**Q-7** reviewer surface, **Q-8** extraction model)
were ratified the same day as D-19 – D-22.
