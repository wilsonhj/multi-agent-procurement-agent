-- public.document -- contract C1.
--
-- One row per ingested source file. Matches SourceDocument in
-- src/procurement_agent/schema/component.py field-for-field. Identity is
-- content-addressed so a re-ingest of byte-identical input is a no-op, per
-- FR-ING-09 / NFR-05 / AC-5.
--
-- Depends on: 00_roles.sql.

CREATE TABLE public.document (
    document_id       text PRIMARY KEY,
    content_hash      text NOT NULL,
    source_uri        text NOT NULL,

    -- Mirrors DocumentType (schema/enums.py) verbatim, eight members. A CHECK,
    -- not a native enum type, so the taxonomy can later be extended with an
    -- ordinary ALTER TABLE ... DROP/ADD CONSTRAINT migration rather than
    -- ALTER TYPE ... ADD VALUE, which cannot be dropped from once added and,
    -- before PostgreSQL 12, could not even run inside a transaction with other
    -- DDL.
    document_type     text NOT NULL CHECK (document_type IN (
                           'contract_tos',
                           'purchase_order',
                           'environmental_regulation',
                           'terms_and_conditions',
                           'warranty',
                           'technical_documentation',
                           'pricing',
                           'spec_sheet'
                       )),

    ingested_at       timestamptz NOT NULL DEFAULT now(),
    data_vintage      timestamptz,

    -- NFR-03: contract and pricing documents are confidential. This is the
    -- coarse flag SourceDocument.access_restricted already fixes in the
    -- Pydantic schema; see the RLS policy below for how it is enforced at
    -- retrieval time, not only at the API edge.
    access_restricted boolean NOT NULL DEFAULT false,

    -- NFR-05 / AC-5, and the exact gap docs/agent-topology.md:34 names:
    -- "content_hash is the intended dedup key ... but it is an unconstrained
    -- field today ... a retry after a partial commit can still duplicate.
    -- Transactional hash uniqueness is a prerequisite for calling retries free,
    -- not a consequence of the field existing." This UNIQUE constraint is that
    -- prerequisite: the ingest worker's retry path becomes
    -- `INSERT ... ON CONFLICT (content_hash) DO NOTHING`, safe because the
    -- database refuses the duplicate rather than application logic merely
    -- being expected to check first.
    CONSTRAINT document_content_hash_unique UNIQUE (content_hash)
);

COMMENT ON TABLE public.document IS
    'C1 core table, matching SourceDocument (schema/component.py). See the GRANT '
    'statement below for exactly which columns the application may update.';

CREATE INDEX document_document_type_idx ON public.document (document_type);

ALTER TABLE public.document OWNER TO procurement_owner;

-- Decision 3c: FORCE so this policy applies even if a session ever connects as
-- the table owner by mistake. procurement_app is a non-owner already, so it was
-- always subject to the policy regardless of FORCE; FORCE closes the gap for
-- every other role, including procurement_owner itself, which is why the
-- policies below are deliberately not scoped `TO procurement_app` -- an
-- unscoped policy (default: PUBLIC) applies the same rule uniformly rather
-- than leaving the owner role staring at zero rows with no applicable policy
-- during a maintenance query. Only an actual PostgreSQL superuser bypasses
-- FORCE ROW LEVEL SECURITY, by design (plan.md Decision 9: "a superuser
-- bypasses even FORCE RLS").
ALTER TABLE public.document ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document FORCE ROW LEVEL SECURITY;

-- The coarse confidentiality gate from NFR-03. Deliberately NOT the
-- fine-grained per-query `allowed_document_ids` allowlist that
-- VectorStorePort.search (ports/__init__.py) takes as a parameter -- that stays
-- a WHERE-clause concern inside the store adapter, because RLS is a poor fit
-- for a large, dynamic, per-request ID set (it would need a session GUC
-- re-issued on every call). RLS here is the boundary a caller cannot forget to
-- apply; allowed_document_ids is the boundary that scopes *which*
-- unrestricted-or-authorized documents one specific query may see. C7 (the
-- ACL/labelling model) is explicitly unfrozen per tasks.md, so this
-- deliberately implements no more than the field the frozen Pydantic schema
-- already commits to -- see sql/README.md's decisions list.
--
-- current_setting(..., true) returns NULL when the GUC was never set for this
-- session, and NULL is never true, so an application that forgets to set
-- app.allow_restricted fails closed (restricted documents hidden), not open.
CREATE POLICY document_confidentiality_select ON public.document
    FOR SELECT
    USING (
        NOT access_restricted
        OR current_setting('app.allow_restricted', true) = 'true'
    );

-- RLS's default-deny is per command, independently of any other policy on the
-- table: with FORCE enabled and only a SELECT policy defined, INSERT/UPDATE
-- would see zero eligible rows even though the GRANT below allows them. These
-- two policies keep the write path exactly where the GRANT puts it; only the
-- SELECT policy above is meant to restrict anything, per Decision 3c's scope
-- (RLS is for retrieval-time visibility; the immutability boundary is
-- privilege separation, Decision 9 -- not RLS).
CREATE POLICY document_write_insert ON public.document
    FOR INSERT
    WITH CHECK (true);

CREATE POLICY document_write_update ON public.document
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

-- document is append-only in spirit (document_id is content-addressed
-- identity) but not literally immutable the way claim/resolution/audit.event
-- are: no reduction logic anywhere depends on a document row never changing,
-- and access_restricted or data_vintage may legitimately need correcting after
-- a misclassification at ingest. UPDATE is therefore granted narrowly to just
-- those two columns rather than withheld entirely or opened on the whole row;
-- this is a judgement call the specs do not make either way -- see
-- sql/README.md. There is no DELETE path: nothing in the spec ever removes an
-- ingested document, and chunk/claim/audit.event all reference it by
-- document_id.
GRANT SELECT, INSERT ON public.document TO procurement_app;
GRANT UPDATE (access_restricted, data_vintage) ON public.document TO procurement_app;
