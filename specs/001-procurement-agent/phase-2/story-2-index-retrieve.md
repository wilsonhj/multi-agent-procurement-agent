# Story 2 — Index and retrieve (WP-C)

**Track:** 2 · **Team:** 4 · **Needs:** Track 0 (P2-C1, P2-C2, P2-C3), Track 4a (connection +
`PrincipalContext`) · **Status:** proposed 2026-09-03

**Story.** Every parsed element becomes chunks that preserve structure — tables whole, rows
inlined with their column names, a generated table summary — embedded and stored in the one
PostgreSQL, so that "what is the Voc of module X" retrieves the right row, `JKM610N-66HL4M-V`
matches `JKM610N 66HL4M V`, and a user without clearance cannot cause a restricted chunk to
influence any result.

**Done means.** `index_document()` and `retrieve()` run against a live PostgreSQL through the
pgvector and lexical adapters; the C.9 `len(results) == k` regression test and the AC-8 RLS test
pass on the `sql` CI job; the TEI embedder and reranker adapters pass the conformance suite with
recorded responses and have run once against real services (recorded in `docs/current-state.md`).

---

## Controlling decisions

| ID | Rule |
|---|---|
| Decision 3 / 3a / 3b / 3c | One PostgreSQL; **exact search, no ANN index**; hybrid = dense + `tsvector` + `pg_trgm`, RRF k=60, then rerank; `FORCE ROW LEVEL SECURITY` with a non-owner app role |
| Decision 5 | Qwen3-Embedding-4B at **1024** dims via MRL truncation + renormalisation; bge-reranker-v2-m3 top-50 → top-5–8 |
| Decision 6 | Tables never token-chunked; triple indexing `table_full` / `table_row` / `table_summary` all on one `table_id`; prose 512 tokens split on structure first; 0–10 % overlap; contextual prefix before embedding |
| Decision 10 | Sync ports; batch parallelism lives inside the payload |
| D-15 | `allowed_document_ids` is scoping within an entitlement; RLS is the boundary; AC-8's test is the RLS path |
| C.9 | Regression test asserting `len(results) == k` on a filtered query — nothing else catches under-return |
| FR-RAG-04 | Extraction uses retrieved context only and returns insufficient-evidence rather than fabricating |
| FR-RAG-05 | Incremental add/update/delete by stable identifier |

## Code surface today

- `services/indexing`: `chunk(elements, *, size_tokens, overlap_ratio) -> list[str]` and `index_document(document, elements, *, embedder, store) -> None` — both raise. **`list[str]` cannot carry `chunk_kind`, `table_id`, `page`, `context_prefix`** that `sql/03_chunk.sql` stores (P2-A-2).
- `services/retrieval.retrieve(query, *, embedder, store, reranker, limit=10, category, supplier, source_tier, allowed_document_ids) -> list[RetrievedChunk]` — raises; already threads `allowed_document_ids`.
- `ports`: `EmbedderPort.dimensions / embed(texts)`; `VectorStorePort.upsert(chunk_ids, vectors, metadata) / delete / search(vector, *, limit, category, supplier, source_tier, allowed_document_ids)`; `RerankerPort.rerank(query, chunks, *, limit)`; `RetrievedChunk(chunk_id, document_id, text, page, source_tier, score)`. **No lexical method on any port** (P2-A-3).
- `adapters/vector_store/memory.py`: filter-then-score, cosine, tie-break `chunk_id`; `ChunkMetadata` TypedDict `{document_id, text, page, source_tier, category, supplier}`.
- `sql/03_chunk.sql`: `chunk_kind ∈ prose|table_full|table_row|table_summary`, `table_id`, `embedding vector(1024)`, `tsv` generated `to_tsvector('english', chunk_text)`, GIN on `tsv`, GIN trigram on `chunk_text`, **no embedding index**; trigger inherits `access_restricted` from the parent document; RLS via `document_is_restricted()`.
- `sql/01`: `vector`, `pg_trgm`; `hnsw.iterative_scan = relaxed_order` set conditionally (belt for a future index).
- Conformance: `VectorStore` capabilities `DETERMINISTIC_OUTPUT, METADATA_FILTERING, ACCESS_FILTERING, INCREMENTAL_UPDATE, EXHAUSTIVE_RECALL`; `ACCESS_FILTERING` may not be xfailed; the suite already probes omit/`None`/`set()` → `[]` and filtered `limit=1` under-return.
- `Settings`: `embedding_endpoint/model`, `vector_store_url`, `chunk_size_tokens=512`, `chunk_overlap_ratio=0.05 (≤0.10)`; **no reranker endpoint** (P2-A-15).

---

## 1 · P2-C2 — `ChunkRecord` (Track 0 writes; this story consumes)

```python
@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str  # deterministic: sha256(document_id, kind, table_id or None, ordinal)[:32]
    document_id: str
    kind: Literal["prose", "table_full", "table_row", "table_summary"]
    text: str  # what is embedded, AFTER the context prefix is prepended
    body: str  # the chunk text without prefix (stored as chunk_text)
    context_prefix: str
    page: int | None
    section: str | None
    table_id: str | None
    ordinal: int
```

`chunk()` returns `list[ChunkRecord]`; `ChunkMetadata` gains `chunk_kind`, `table_id`, `section`.
`chunk_id` is a function of stored data only — A-50's question (*could this change without the
data changing?*) is answered by construction: no clock, no embedding, no model name.

## 2 · Chunking (Decision 6, C.1–C.3) — `services/indexing/chunking.py`

- **Tables:** one `table_full` per `ParsedElement(kind="table")`; one `table_row` per data row
  serialised `"Col1: v1 | Col2: v2 | …"` with header names inlined; one `table_summary` generated
  by `LLMPort.extract` with a small schema (`{"summary": str, "covered_models": list[str]}`) —
  when no LLM is configured, the summary is the caption plus header names, deterministic. A table
  wider than the embedder window is split by **row groups with the header repeated**, never by
  tokens. All three carry the same `table_id`.
- **Prose:** split on heading boundaries first (`role`/`kind == "heading"`), then pack to
  `Settings.chunk_size_tokens` using the embedder's tokenizer when available, else a
  whitespace-token proxy; overlap `chunk_overlap_ratio` **only inside** a section, zero at
  boundaries.
- **Contextual prefix:** `"{document title} › {section path}. "` prepended to `text` before
  embedding; `body` is stored without it so the workbook's Sources tab shows what the document
  said.
- Furniture (`role="furniture"`) is indexed as prose with `section="furniture"` and never joins a
  table's `table_id`.

## 3 · P2-C3 — `LexicalSearchPort` (D-25)

A seventh Protocol beside the six that exist today, not a method on `VectorStorePort`, so the
existing adapters stay conformant and the in-memory reference is trivial. Track 0 also adds
`WebSearchPort` (P2-C4) in the same freeze; Decision 10's count becomes **eight**.

```python
class LexicalSearchPort(Protocol):
    def search_lexical(
        self,
        query: str,
        *,
        limit: int,
        category: ComponentCategory | None = None,
        supplier: str | None = None,
        source_tier: SourceTier | None = None,
        allowed_document_ids: set[str] | None = None,
    ) -> list[RetrievedChunk]: ...
```

Same `allowed_document_ids` rule as the vector port: `None` returns nothing. Capabilities:
`DETERMINISTIC_OUTPUT, METADATA_FILTERING, ACCESS_FILTERING, TRIGRAM_TOLERANCE`.
`adapters/lexical_store/memory.py` does token overlap plus a trigram Jaccard so the part-number
test is expressible against the reference.

## 4 · Adapters

**`adapters/vector_store/pgvector.py`.** Exact cosine `ORDER BY embedding <=> %s LIMIT %s` over
`public.chunk` with `WHERE` on the metadata filters **and** `document_id = ANY(%s)` for the
allow-list, inside the same statement — filters inside top-k, never after. Opens its connection
through the Story 4 `PrincipalContext`, which sets `SET LOCAL app.allow_restricted`; the adapter
never sets the GUC itself. `upsert` is `INSERT … ON CONFLICT (chunk_id) DO UPDATE` on the
embedding and text columns (FR-RAG-05); `delete` by `chunk_id`. Declares `EXHAUSTIVE_RECALL`
because there is no index. Asserts `len(vector) == 1024` on every upsert.

**`adapters/lexical_store/postgres.py`.** One statement fusing `ts_rank_cd(tsv, plainto_tsquery(
'english', %s))` and `similarity(chunk_text, %s)` (pg_trgm) as two candidate lists, RRF k=60
within the lexical leg, same filters and allow-list.

**`adapters/embedder/tei.py`.** POST `/embed` with the Qwen3 instruction prefix for queries and
none for passages; **truncate to 1024 and L2-renormalise in the adapter**; `dimensions` returns
1024; asserts unit norm ± 1e-6. Batches of `Settings.embedding_batch_size` (new, default 32).

**`adapters/reranker/tei.py`.** POST `/rerank` with `{"query", "texts"}`; rebuilds
`RetrievedChunk` with the reranker score, preserving `source_tier`. New settings
`reranker_endpoint`, `reranker_model`.

Each vendor adapter ships three tests: the conformance suite via the memory reference, a
recorded-response wire-shape test, and an env-gated live test (`PROCUREMENT_TEI_URL`,
`PROCUREMENT_TEST_DSN`) that skips locally and is required on the self-hosted runner.

## 5 · `index_document()` and `retrieve()`

```python
def index_document(document, elements, *, embedder, store, lexical, writer, llm=None) -> IndexResult
```

Chunk → embed (batched) → `store.upsert` → `writer.write_chunks` (Story 4 repository writes the
`chunk` rows the adapter searches; the trigger inherits `access_restricted`). Idempotent by
`chunk_id`; re-indexing an unchanged document produces zero row changes (asserted with a row-count
query, not a green run).

```python
def retrieve(query, *, embedder, store, lexical, reranker, principal, limit=10, category=None,
             supplier=None, source_tier=None, allowed_document_ids: set[str] | None) -> list[RetrievedChunk]
```

Dense top-50 and lexical top-50 → RRF k=60 → rerank → `limit`. **`allowed_document_ids` is
required at the service.** `None` (and omitting it) returns `[]` — the port rule, unchanged.
Callers that want the principal's entitlement pass `DocumentRepository.visible_ids(principal)`
explicitly. There is no default-to-visible: that would make a forgotten argument return
restricted-and-cleared documents and break AC-8's "omit nothing" reading.

## 6 · Access control (Decision 3c, D-15, AC-8) — the live tests

- `test_app_role_without_guc_sees_no_restricted_chunks` — `procurement_app`, no `SET LOCAL`,
  restricted chunk present, dense and lexical both return zero restricted rows.
- `test_allowlist_cannot_widen_rls` — allow-list naming a restricted document, GUC unset, still
  zero rows. This is AC-8: the allow-list is scoping, RLS is the boundary.
- `test_filtered_topk_returns_exactly_k` (C.9) — 200 chunks, 1 % selective filter, `limit=10`,
  assert `len(results) == 10`. Belongs in the `sql` job so a future index cannot land silently
  wrong.
- `hnsw.iterative_scan` remains set; a test asserts **no index exists on `chunk.embedding`**
  (`pg_indexes` query) so Decision 3a is enforced, not remembered.

## Verify

Minimum new tests: 45. Named above plus:

- `test_tables_are_never_token_chunked` · `test_wide_table_splits_by_row_group_with_header_repeated`
- `test_triple_indexing_shares_table_id` · `test_row_chunk_inlines_column_names`
- `test_voc_of_model_retrieves_table_row` (memory adapters, synthetic fixture)
- `test_part_number_hyphen_variants_match` — `JKM610N-66HL4M-V` ↔ `JKM610N 66HL4M V` (lexical reference, then live)
- `test_chunk_id_is_a_function_of_stored_data_only`
- `test_reindex_unchanged_document_changes_zero_rows` (live)
- `test_embedder_adapter_truncates_and_renormalises` · `test_reranker_preserves_source_tier`
- `test_overlap_is_zero_at_section_boundaries`
- Conformance: `vector_store:pgvector`, `lexical_store:memory`, `lexical_store:postgres`, `embedder:tei`, `reranker:tei` registered with complete accounting.

**Gates at merge:** four local gates; `sql` job green with passed count raised by the live tests
above; recorded live run of TEI adapters noted in `docs/current-state.md`.

## Traps

- pgvector filtered search **post-filters by default with an ANN index** (measured 5 of 10). There is no index here; the C.9 test is what keeps it that way.
- `to_tsvector('english', …)` is pinned in the generated column; the query side must use the same configuration or recall silently drops.
- TEI may start honouring a `dimensions` parameter; the adapter truncates regardless and asserts the length, so a server change cannot double-truncate.
- RRF over two legs that share no candidate is legal and common for part-number queries; do not "fix" it by requiring overlap.

## Out of scope

Any ANN index (Decision 3a's migration trigger is ~5 M chunks); sparse/ColBERT vectors (Decision 5's bge-m3 contingency); async ports.

---

*Clarifications Q-5 – Q-16 cited by this story were ratified on 2026-09-03 as D-19 – D-30 in [clarifications.md](../clarifications.md); the D-entries are the authority.*
