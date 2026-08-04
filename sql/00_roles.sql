-- Roles and privilege separation.
--
-- Implements plan.md Decision 9 (immutable audit log) and Decision 3c (access
-- control): the boundary that actually holds against UPDATE/DELETE/TRUNCATE from
-- the application connection is privilege separation, not a trigger, and it is
-- completely defeated the moment the application authenticates as an object
-- owner. So every owner role below is NOLOGIN -- nothing, ever, connects as one.
-- A separate, more privileged bootstrap identity creates these roles and later
-- reassigns table ownership to them with ALTER ... OWNER TO; see the "Who runs
-- this" section of sql/README.md for exactly what that identity needs.
--
-- Four roles, because Decision 9 wants the audit boundary isolated from the
-- core-table boundary, and because the pipeline's write path and its retrieval
-- path have opposite confidentiality requirements (see procurement_ingest):
--
--   procurement_owner  NOLOGIN. Owns document, chunk, claim, conflict,
--                       conflict_candidate, resolution, job -- every table in
--                       this file set except audit.event.
--   audit_owner         NOLOGIN. Owns schema audit and audit.event, and nothing
--                       else. A second, distinct owner role rather than reusing
--                       procurement_owner, so a future mis-grant on the core
--                       tables cannot widen into audit privileges: the two
--                       blast radii are structurally separate roles, not just
--                       separate GRANT statements against one role.
--   procurement_app      LOGIN. The retrieval/serving identity -- the one that
--                       answers a user's question. Non-owner of every table it
--                       touches and explicitly stripped of every attribute that
--                       could make it into one -- this is Decision 3c's "the
--                       application connects as a non-owner, non-superuser
--                       role." Subject to the confidentiality policies in full.
--   procurement_ingest   LOGIN. The pipeline's WRITE identity: ingest, indexing,
--                       extraction, conflict detection, audit append. See the
--                       block below for why this is a separate role rather than
--                       a GUC on procurement_app.
--
-- Idempotent: CREATE ROLE has no IF NOT EXISTS in PostgreSQL, and this file must
-- be safe to re-run against a database where these roles already exist (T0.1
-- requires migrations to "apply cleanly"). Table creation later in this file set
-- is deliberately NOT idempotent the same way -- see sql/README.md.
--
-- **Re-running this file re-asserts attributes; it does not merely skip.** The
-- first version guarded each role behind `IF NOT EXISTS` and stopped there, so
-- every attribute below was applied *only* at first creation. Measured against a
-- live cluster:
--
--     ALTER ROLE procurement_app SUPERUSER BYPASSRLS;   -- however this happened
--     \i 00_roles.sql                                   -- the file "applies cleanly"
--     SELECT rolsuper, rolbypassrls FROM pg_roles
--       WHERE rolname = 'procurement_app';              -- t | t   -- still
--     SET ROLE procurement_app;
--     SELECT document_id FROM public.document WHERE access_restricted;  -- 2 rows
--
-- A file whose entire purpose is "the application connects as a non-owner,
-- non-superuser role" cannot leave that property untested on the one path it
-- was designed to support. The unconditional `ALTER ROLE`s below re-assert it on
-- every run, and the assertion block at the foot of the file turns any residual
-- forbidden attribute into a loud failure rather than a clean-looking apply.
--
-- **This file therefore requires a superuser bootstrap identity.** SUPERUSER,
-- BYPASSRLS and REPLICATION can only be cleared by an actual superuser -- a
-- CREATEROLE service account is refused with "permission denied to alter role"
-- even when the attribute is already unset. That is the correct trade: an
-- identity that cannot clear BYPASSRLS cannot honestly promise it is unset. The
-- rest of the file set (02 onward) still applies under the weaker CI identity
-- sql/README.md describes.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'procurement_owner') THEN
        CREATE ROLE procurement_owner NOLOGIN;
    END IF;
END
$$;

COMMENT ON ROLE procurement_owner IS
    'Owns the core C1 tables. NOLOGIN: never assumed by the running application. '
    'See sql/README.md for the bootstrap identity that reassigns ownership here.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'audit_owner') THEN
        CREATE ROLE audit_owner NOLOGIN;
    END IF;
END
$$;

COMMENT ON ROLE audit_owner IS
    'Owns schema audit and audit.event, and nothing else. NOLOGIN, and deliberately '
    'distinct from procurement_owner so a mis-grant on the core tables cannot widen '
    'into audit privileges. See plan.md Decision 9.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'procurement_app') THEN
        CREATE ROLE procurement_app LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOREPLICATION
            NOBYPASSRLS;
    END IF;
END
$$;

COMMENT ON ROLE procurement_app IS
    'The retrieval/serving connection identity. Non-owner of every table it '
    'queries: Decision 3c''s FORCE ROW LEVEL SECURITY only restricts '
    'non-owner, non-superuser roles, so this role owning its own tables would '
    'silently stop RLS from applying to it. No password is set by this file -- '
    'configure authentication out of band (ALTER ROLE ... WITH PASSWORD, or '
    'certificate/IAM auth) so no credential is ever committed alongside this DDL.';

-- ---------------------------------------------------------------------------
-- procurement_ingest -- the pipeline's write identity.
--
-- **Why a fourth role rather than one more GUC.** RLS applies a table's `FOR
-- SELECT` policy as a WITH CHECK against the *proposed* row whenever an INSERT
-- carries `RETURNING` or `ON CONFLICT`. So with only procurement_app,
--
--     INSERT INTO public.document (..., access_restricted)
--     VALUES (..., true)
--     ON CONFLICT (content_hash) DO NOTHING;
--     -- ERROR: new row violates row-level security policy for table "document"
--
-- while the identical statement with `access_restricted = false` succeeded.
-- Writing a MORE confidential row failed and writing a LESS confidential one
-- worked -- the schema penalised the safe action, and the documented idempotent
-- ingest idiom (02_document.sql) was unusable for exactly the pricing and
-- contract documents NFR-03 exists to protect. Any `RETURNING` was equally
-- affected, including `RETURNING claim_id` on the identity column that
-- conflict_candidate needs.
--
-- Three fixes were considered and two measured:
--
--   * **`xmin = pg_current_xact_id_if_assigned()::xid` as a read-back policy** --
--     "let a session read rows it wrote itself." Measured: does NOT work. The
--     policy is evaluated as a WITH CHECK on the in-memory proposed tuple, whose
--     system columns are not yet set, so it never matches. Recorded because it
--     is the obvious first idea and it fails silently in the direction of
--     looking correct.
--   * **Reuse `app.allow_restricted` on the ingest path** -- measured, works.
--     Rejected: it makes the *writer* assert full retrieval entitlement to every
--     restricted document in the store, on the same role and the same
--     connection pool that serves user queries. `SET` (as opposed to `SET
--     LOCAL`) persists for the life of the session, and a pooled backend handed
--     to the next request carries it; one un-RESET GUC silently declassifies
--     every subsequent retrieval query. The failure is invisible and global.
--   * **A separate write role** -- chosen. The entitlement becomes a static,
--     auditable property of a principal no user request is ever served by,
--     instead of dynamic session state that a pool can leak. This is the same
--     reasoning the rest of this file already rests on: per plan.md Decision 9,
--     "the boundary that actually holds ... is privilege separation."
--
-- The split is real and not cosmetic: procurement_ingest may read restricted
-- rows, and procurement_app may not. AC-8 ("a user without clearance for a
-- confidential document cannot cause its content to influence any retrieved
-- result") is a property of the retrieval principal, and that principal is
-- procurement_app, whose policies are unchanged by this role existing.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'procurement_ingest') THEN
        CREATE ROLE procurement_ingest LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOREPLICATION
            NOBYPASSRLS;
    END IF;
END
$$;

COMMENT ON ROLE procurement_ingest IS
    'The pipeline''s write identity (ingest, indexing, extraction, conflict '
    'detection, audit append). Entitled to read restricted rows because it is '
    'the principal that writes them and RLS applies SELECT policies to '
    'RETURNING/ON CONFLICT. Must NEVER be used to serve a user query -- that is '
    'procurement_app, which stays subject to the confidentiality policies. '
    'Non-owner and non-superuser, exactly like procurement_app. No password is '
    'set by this file.';

-- ---------------------------------------------------------------------------
-- Unconditional re-assertion. These run on every apply, including a re-run
-- against a cluster where the roles already exist -- which is the case the
-- IF NOT EXISTS guards above deliberately skip, and the case where a role may
-- have acquired attributes nobody in this file set intended. See the header.
--
-- No PASSWORD clause anywhere: ALTER ROLE without one leaves the existing
-- credential untouched, so re-running this file cannot lock the application out.
ALTER ROLE procurement_owner  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE audit_owner        NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE procurement_app    LOGIN   NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE procurement_ingest LOGIN   NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- The assertion, separate from the ALTERs above on purpose: reading pg_roles
-- needs no privilege at all, so this check holds even where the ALTERs could not
-- run, and it names what is wrong instead of leaving a reader to infer it from
-- "permission denied to alter role". Without it, the failure mode this section
-- exists to close is a migration that prints no errors.
DO $$
DECLARE
    offender record;
BEGIN
    FOR offender IN
        SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication
        FROM pg_catalog.pg_roles
        WHERE rolname IN ('procurement_owner', 'audit_owner', 'procurement_app', 'procurement_ingest')
          AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)
    LOOP
        RAISE EXCEPTION
            'role % carries attributes this schema''s access control cannot survive '
            '(super=% bypassrls=% createrole=% createdb=% replication=%). FORCE ROW '
            'LEVEL SECURITY is bypassed outright by SUPERUSER and by BYPASSRLS, so '
            'every confidentiality policy in 02_document.sql and 03_chunk.sql is '
            'inert for this role. Clear them as a superuser (ALTER ROLE % NOSUPERUSER '
            'NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION) and re-run.',
            offender.rolname, offender.rolsuper, offender.rolbypassrls,
            offender.rolcreaterole, offender.rolcreatedb, offender.rolreplication,
            offender.rolname;
    END LOOP;
END
$$;
