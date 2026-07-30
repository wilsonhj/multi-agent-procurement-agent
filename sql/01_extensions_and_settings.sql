-- Extensions, schemas, and cluster-visible settings.
--
-- Depends on: 00_roles.sql (the audit schema below is authorized to audit_owner,
-- which must already exist).

-- Decision 3 / Decision 5: single Postgres datastore; Qwen3-Embedding-4B stored
-- at 1024 dims via Matryoshka truncation. pgvector 0.8.5 is pinned at the
-- application dependency layer (pyproject.toml); this file only requires some
-- pgvector new enough to provide `vector(1024)` and the hnsw.iterative_scan GUC
-- (0.5.0+), whatever exact version the target cluster has installed.
CREATE EXTENSION IF NOT EXISTS vector;

-- Decision 3b: the licence gate (plan.md) rules out every permissively licensed
-- true-BM25 implementation for Postgres in 2026 -- both credible extensions are
-- AGPL. pg_trgm is what actually fixes the retrieval failure that matters at
-- this scale ("JKM610N-66HL4M-V" not matching "JKM610N 66HL4M V"), and it ships
-- under the same licence as core Postgres.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Decision 9: audit.* is owned by a NOLOGIN role distinct from the core
-- schema's owner, so a mis-grant on one side can never widen into the other.
-- Schema-level ownership also controls who may CREATE new objects inside
-- `audit` in a future migration.
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION audit_owner;

COMMENT ON SCHEMA audit IS
    'Append-only audit trail (contract C4). Owned by audit_owner (NOLOGIN); the '
    'application role holds INSERT, SELECT only on audit.event -- see '
    '07_audit_event.sql.';

-- Decision 3a: no ANN index is created anywhere in this schema (see the comment
-- on chunk.embedding in 03_chunk.sql for the measured reasons). This setting is
-- required regardless, so that if a future migration ever adds one anyway, the
-- default is not silently wrong: hnsw.iterative_scan defaults to `off`, and
-- `off` was measured returning 5 rows for a top-10 filtered request with no
-- error and no warning, or 0 rows against an ACL-array filter on a GIN index.
--
-- Scoped to this database rather than editing postgresql.conf directly, via
-- ALTER DATABASE, so the setting travels with this application's schema
-- regardless of what else shares the cluster. `current_database()` is
-- substituted dynamically so this file does not need to hardcode a database
-- name.
--
-- This takes effect for sessions that connect after it is set; it does not
-- retroactively change the session running this script. It also requires no
-- shared_preload_libraries change: pgvector's custom GUCs are ordinary
-- per-backend placeholders that PostgreSQL accepts and holds as text until the
-- `vector` extension's library actually loads into a given backend (the first
-- time that backend touches a vector value or operator), at which point the
-- placeholder is validated against the real enum definition.
DO $$
BEGIN
    EXECUTE format(
        'ALTER DATABASE %I SET hnsw.iterative_scan = %L',
        current_database(),
        'relaxed_order'
    );
END
$$;
