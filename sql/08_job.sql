-- public.job -- plan.md Decision 1 / tasks.md WP-I I.1.
--
-- The stage state machine: a Postgres table plus a
-- `SELECT ... FOR UPDATE SKIP LOCKED` worker loop, not a workflow framework.
--
-- `stage` is keyed on orchestrator.Stage
-- (src/procurement_agent/orchestrator/__init__.py) verbatim -- the same
-- discipline services/conflict_hitl/tolerance.py uses for its own table,
-- keyed on the frozen field contract rather than an invented name. Six
-- values, no more, no fewer, and deliberately no await_human_resolution stage:
-- plan.md Decision 2 detaches the human gate from the pipeline entirely, and
-- orchestrator.Stage's own docstring says so explicitly.
--
-- Depends on: 02_document.sql.

CREATE TABLE public.job (
    job_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Nullable: compose_workbook is a whole-store operation with no single
    -- document subject (docs/agent-topology.md's own stage table marks it
    -- "none" for fan-out, for the same reason). Every other stage is
    -- document-scoped.
    document_id        text REFERENCES public.document (document_id) ON DELETE RESTRICT,

    stage              text NOT NULL CHECK (stage IN (
                           'ingest', 'extract', 'index', 'enrich_via_web',
                           'detect_conflicts', 'compose_workbook'
                       )),

    status             text NOT NULL DEFAULT 'pending' CHECK (status IN (
                           'pending', 'running', 'succeeded', 'failed', 'quarantined'
                       )),

    -- I.2: every stage must be independently idempotent; retries are
    -- at-least-once. This is the DB-level half of that promise, the same
    -- pattern as document.content_hash and claim's natural key: the enqueue
    -- path is `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`, so
    -- re-enqueuing the same logical unit of work is a no-op rather than a
    -- duplicate row racing the original.
    idempotency_key    text NOT NULL,
    payload            jsonb NOT NULL DEFAULT '{}'::jsonb,

    attempt            integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts       integer NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
    -- I.2 backoff: a job only becomes eligible for the worker loop's SELECT
    -- once this is reached. Defaults to now() so a freshly enqueued job is
    -- immediately eligible.
    next_attempt_at    timestamptz NOT NULL DEFAULT now(),

    -- D-12e: 15-minute lease, the same duration WP-F F.1 uses for conflict
    -- claiming -- tasks.md never gives the job table its own number, so this
    -- reuses D-12e's rather than inventing a second one; flagged in
    -- sql/README.md. Swept back to 'pending' by a periodic worker-loop query
    -- (see the comment on the supporting index below), not a DB trigger --
    -- Decision 1 keeps this logic in the runner, not in the schema.
    lease_owner        text,
    lease_expires_at   timestamptz,

    last_error         text,

    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT job_idempotency_key_unique UNIQUE (idempotency_key),
    CONSTRAINT job_lease_fields_consistent
        CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);

COMMENT ON TABLE public.job IS
    'Stage state machine for plan.md Decision 1. No corresponding Pydantic '
    'model exists in schema/ -- this table is this file''s own C8-consistent '
    'design, not a mapping of an existing frozen type.';

-- The worker loop's hot path: claim the next eligible job for a stage.
--   SELECT job_id FROM job
--     WHERE stage = $1 AND status = 'pending' AND next_attempt_at <= now()
--     ORDER BY created_at
--     FOR UPDATE SKIP LOCKED
--     LIMIT $2;
CREATE INDEX job_pending_by_stage_idx ON public.job (stage, next_attempt_at)
    WHERE status = 'pending';

-- The lease sweeper's hot path:
--   UPDATE job SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL
--     WHERE status = 'running' AND lease_expires_at < now();
CREATE INDEX job_running_lease_idx ON public.job (lease_expires_at)
    WHERE status = 'running';

CREATE INDEX job_document_id_idx ON public.job (document_id);

CREATE FUNCTION public.job_touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

-- Bookkeeping only, not a business-rule trigger of the kind Decision 9 warns
-- against: it does not enforce or hide any invariant, it only timestamps a
-- change that already happened.
CREATE TRIGGER job_set_updated_at
    BEFORE UPDATE ON public.job
    FOR EACH ROW
    EXECUTE FUNCTION public.job_touch_updated_at();

ALTER TABLE public.job OWNER TO procurement_owner;
ALTER FUNCTION public.job_touch_updated_at() OWNER TO procurement_owner;

-- job is the mutable state machine itself -- unlike claim/resolution/
-- audit.event, full UPDATE is granted rather than withheld, since state
-- transitions are the table's entire purpose. No DELETE: nothing in the spec
-- ever removes a job row -- a poison message is quarantined (status =
-- 'quarantined', I.4), never deleted.
GRANT SELECT, INSERT, UPDATE ON public.job TO procurement_app;
