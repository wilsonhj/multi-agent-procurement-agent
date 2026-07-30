-- public.chunk -- contract C1.
--
-- The retrieval unit produced by WP-C indexing (FR-RAG-01/02/05, plan.md
-- Decisions 3a/3b/5/6).
--
-- Depends on: 01_extensions_and_settings.sql (vector, pg_trgm), 02_document.sql.

-- `tsv` is generated with the TWO-argument to_tsvector(regconfig, text), which
-- PostgreSQL's own catalog marks IMMUTABLE (pg_proc.provolatile = 'i'), so it is
-- legal directly inside GENERATED ALWAYS AS ... STORED. Verified against a live
-- PostgreSQL 17.10: the two-argument form creates the table, and the ONE-argument
-- to_tsvector(text) is the STABLE one that fails with "generation expression is
-- not immutable" -- because it reads default_text_search_config at runtime.
--
-- Pinning the configuration in the call is therefore the whole fix; no IMMUTABLE
-- wrapper function is needed. An earlier draft of this file added one, on the
-- mistaken belief that the two-argument form was STABLE. Worth naming, because
-- wrapping a genuinely STABLE function and declaring the wrapper IMMUTABLE is
-- not a harmless workaround -- it lies to the planner and can silently corrupt
-- any index built on it. The same immutability is why the standard
-- `CREATE INDEX ... USING gin(to_tsvector('english', col))` idiom works at all.

CREATE TABLE public.chunk (
    chunk_id           text PRIMARY KEY,
    document_id        text NOT NULL REFERENCES public.document (document_id) ON DELETE RESTRICT,

    -- Decision 6: a table is indexed three times, all three rows pointing at
    -- one table_id. `prose` is this schema's own name for the non-table case;
    -- plan.md only names the three table_* kinds.
    chunk_kind         text NOT NULL CHECK (chunk_kind IN (
                           'prose', 'table_full', 'table_row', 'table_summary'
                       )),
    table_id           text,

    -- Denormalized onto the chunk row per FR-RAG-02's own list of what indexing
    -- must write: "doc ID, chunk ID, component category, supplier, doc type,
    -- page, source URI, timestamps, source-tier flag" (see
    -- services/indexing/__init__.py). `model` and `access_restricted` are added
    -- here beyond that literal list, for symmetry with supplier and with
    -- document.access_restricted respectively -- flagged in sql/README.md.
    -- Denormalized rather than joined so VectorStorePort.search's category and
    -- supplier filters (ports/__init__.py) never need a join against claim on
    -- the hot retrieval path.
    component_category text CHECK (component_category IN (
                           'pv_modules', 'inverters_pcs', 'trackers_mounting',
                           'transformers', 'cabling_wiring', 'combiner_boxes',
                           'bess', 'ems_scada'
                       )),
    supplier           text,
    model              text,
    document_type      text CHECK (document_type IN (
                           'contract_tos',
                           'purchase_order',
                           'environmental_regulation',
                           'terms_and_conditions',
                           'warranty',
                           'technical_documentation',
                           'pricing',
                           'spec_sheet'
                       )),
    page               integer,
    section            text,
    source_uri         text,

    -- FR-RAG-03: system-of-record chunks must remain distinguishable from web
    -- supplements at all times, so this travels with every retrieved row rather
    -- than being looked up later (see ports.RetrievedChunk).
    source_tier        text NOT NULL CHECK (source_tier IN ('system_of_record', 'web_supplement')),
    access_restricted  boolean NOT NULL DEFAULT false,

    -- The verbatim chunk text: what a citation shows a reviewer, and what the
    -- lexical indexes below run over. Decision 3b's motivating failure
    -- ("JKM610N-66HL4M-V" not matching "JKM610N 66HL4M V") lives in source
    -- text, not in a generated context sentence, which is why the indexes
    -- target this column and not context_prefix.
    chunk_text         text NOT NULL,

    -- Decision 6, "contextual retrieval": 1-2 sentences of document/section
    -- context, prepended only to the text that gets embedded. Kept in its own
    -- column, separate from chunk_text, so a citation never presents
    -- LLM-generated framing to a reviewer as if it were the source. This split
    -- is this file's own resolution of an ambiguity Decision 6 leaves open --
    -- see sql/README.md. NULL where no prefix was generated.
    context_prefix     text,

    -- Decision 5: Qwen3-Embedding-4B, Matryoshka-truncated and renormalised to
    -- 1024 dims. The truncation is load-bearing, not an optimisation: pgvector
    -- caps HNSW indexable dimensions at 2000, so the native 2560 could never be
    -- indexed even if Decision 3a is later revisited.
    embedding          vector(1024) NOT NULL,

    -- Decision 3b's lexical leg. Generated, not written by application code, so
    -- there is no code path that could forget to keep it in sync with
    -- chunk_text, with the configuration pinned in the call -- see the note above
    -- on why the two-argument form is the one that belongs here.
    tsv                tsvector GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED NOT NULL,

    created_at         timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.chunk IS
    'C1 core table. FR-RAG-05: incremental add/update/delete by stable chunk_id, '
    'never a full re-index -- see ports.VectorStorePort.upsert and .delete.';

COMMENT ON COLUMN public.chunk.embedding IS
    'Decision 3a: no ANN index is built on this column anywhere in this schema. '
    'Measured at 50,000 chunks with a 1 percent selective filter and LIMIT 10: '
    'HNSW with hnsw.iterative_scan=off silently returned 5 rows, no error, no '
    'warning; HNSW against an ACL-array GIN filter returned 0. Exact search '
    'combined with a metadata filter measured 3.5 to 5.5 ms with guaranteed '
    'top-k; the unfiltered worst case was 130 to 180 ms, trivial beside the LLM '
    'call it feeds. Do not add a hnsw or ivfflat index here on the strength of '
    'FR-RAG-02''s ANN wording alone -- plan.md Decision 3a supersedes it. If a '
    'future migration adds one anyway, hnsw.iterative_scan is already set to '
    'relaxed_order (01_extensions_and_settings.sql), and pgvector enforces '
    'ef_construction >= 2 * m as a hard error at index build time, not merely '
    'README guidance.';

-- Lookup and filter indexes. No index is created on `embedding` -- see the
-- comment on that column above.
CREATE INDEX chunk_document_id_idx ON public.chunk (document_id);
CREATE INDEX chunk_tsv_idx ON public.chunk USING gin (tsv);
CREATE INDEX chunk_text_trgm_idx ON public.chunk USING gin (chunk_text gin_trgm_ops);
CREATE INDEX chunk_category_supplier_idx ON public.chunk (component_category, supplier);
CREATE INDEX chunk_table_id_idx ON public.chunk (table_id) WHERE table_id IS NOT NULL;

ALTER TABLE public.chunk OWNER TO procurement_owner;

-- See the equivalent comment in 02_document.sql: FORCE applies RLS uniformly,
-- including to procurement_owner, so the policies below are deliberately not
-- scoped `TO procurement_app`.
ALTER TABLE public.chunk ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chunk FORCE ROW LEVEL SECURITY;

CREATE POLICY chunk_confidentiality_select ON public.chunk
    FOR SELECT
    USING (
        NOT access_restricted
        OR current_setting('app.allow_restricted', true) = 'true'
    );

-- Same reasoning as document.sql's write-path policies: RLS's default-deny is
-- per command, so INSERT/UPDATE/DELETE each need their own permissive policy or
-- the SELECT-only policy above would leave them at zero rows despite the GRANT
-- below allowing them.
CREATE POLICY chunk_write_insert ON public.chunk
    FOR INSERT
    WITH CHECK (true);

CREATE POLICY chunk_write_update ON public.chunk
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

CREATE POLICY chunk_write_delete ON public.chunk
    FOR DELETE
    USING (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.chunk TO procurement_app;
