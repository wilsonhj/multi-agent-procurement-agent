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
-- Three roles, not two, because Decision 9 specifically wants the audit
-- boundary isolated from the core-table boundary:
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
--   procurement_app      LOGIN. The only identity the running application ever
--                       connects as. Non-owner of every table it touches and
--                       explicitly stripped of every attribute that could make
--                       it into one -- this is Decision 3c's "the application
--                       connects as a non-owner, non-superuser role."
--
-- Idempotent: CREATE ROLE has no IF NOT EXISTS in PostgreSQL, and this file must
-- be safe to re-run against a database where these roles already exist (T0.1
-- requires migrations to "apply cleanly"). Table creation later in this file set
-- is deliberately NOT idempotent the same way -- see sql/README.md.

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
    'The running application''s only connection identity. Non-owner of every '
    'table it queries: Decision 3c''s FORCE ROW LEVEL SECURITY only restricts '
    'non-owner, non-superuser roles, so this role owning its own tables would '
    'silently stop RLS from applying to it. No password is set by this file -- '
    'configure authentication out of band (ALTER ROLE ... WITH PASSWORD, or '
    'certificate/IAM auth) so no credential is ever committed alongside this DDL.';
