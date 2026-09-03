-- public.resolution -- contract C1, C5 (Resolution, schema/field.py).
--
-- Append-only per FR-HITL-06 ("logged immutably"): a reopened conflict
-- (REQUEST_MORE_WEB_SEARCH) gets a new resolution row, never an update to a
-- previous one, so the full decision history for one conflict is always
-- reconstructable.
--
-- Depends on: 04_claim.sql (public.reject_mutation()), 05_conflict.sql.

CREATE TABLE public.resolution (
    resolution_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_id           text NOT NULL REFERENCES public.conflict (entry_id) ON DELETE RESTRICT,

    action             text NOT NULL CHECK (action IN (
                           'select_value', 'enter_override', 'keep_system_of_record',
                           'request_more_web_search', 'defer'
                       )),
    resolved_by        text NOT NULL,
    resolved_at        timestamptz NOT NULL DEFAULT now(),
    rationale          text NOT NULL,
    value_before       jsonb,
    value_after        jsonb,

    -- When action = select_value, the specific candidate claim that was chosen.
    -- Nullable: enter_override asserts a value that matches no existing claim,
    -- and defer / request_more_web_search select nothing at all.
    --
    -- Not enforced here, but worth stating for whoever implements WP-F: a
    -- select_value or enter_override resolution is expected to also INSERT a
    -- new claim row for the human's asserted value (an extractor_version
    -- convention such as human:<resolved_by> is one option), so the projection
    -- reducer sees a human decision as just another, highest-priority claim
    -- rather than needing a special case that reads resolution.value_after
    -- directly. This keeps "the canonical value is a projection over claims,
    -- never an in-place update" (tasks.md C8) true for human overrides too,
    -- not only for machine extractions. See sql/README.md's decisions list --
    -- this is a convention this file recommends, not one it can enforce
    -- without a cross-table trigger, which was judged too fragile for the
    -- gain.
    selected_claim_id  bigint REFERENCES public.claim (claim_id) ON DELETE RESTRICT
);

COMMENT ON TABLE public.resolution IS
    'C1 core table, append-only. No UPDATE/DELETE is granted below; the trigger '
    'reused from 04_claim.sql applies the same secondary-tripwire reasoning as '
    'claim and audit.event.';

CREATE INDEX resolution_entry_id_idx ON public.resolution (entry_id);

ALTER TABLE public.resolution OWNER TO procurement_owner;

-- Confidentiality (NFR-03, AC-8). `value_before` and `value_after` are the
-- disputed values themselves, and `rationale` is a human's prose about them, so
-- a resolution is exactly as confidential as the conflict it settles. Measured
-- as procurement_app against a document that role could not see:
--
--     SELECT entry_id, value_before, value_after FROM public.resolution;
--      cf-1 | 0.35 | 0.19
--
-- Keyed on `conflict_is_restricted(entry_id)` (05_conflict.sql) rather than on a
-- document_id this table does not have -- and correctly so, since the conflict
-- being resolved may span several documents.
ALTER TABLE public.resolution ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resolution FORCE ROW LEVEL SECURITY;

CREATE POLICY resolution_confidentiality_select ON public.resolution
    FOR SELECT
    USING (
        NOT public.conflict_is_restricted(entry_id)
        OR current_setting('app.allow_restricted', true) = 'true'
    );

CREATE POLICY resolution_write_insert ON public.resolution
    FOR INSERT
    WITH CHECK (true);

-- Permissive UPDATE/DELETE policies on an append-only table, for the reason
-- given at length in 04_claim.sql: RLS removes rows before a FOR EACH ROW
-- trigger runs, so omitting these turns the append-only tripwire from a raised
-- exception into a silent `UPDATE 0`. Neither verb is granted to any role below;
-- these policies exist only so the mis-grant case is audible.
CREATE POLICY resolution_tripwire_update ON public.resolution FOR UPDATE USING (true);
CREATE POLICY resolution_tripwire_delete ON public.resolution FOR DELETE USING (true);

-- procurement_app cannot switch its own confidentiality off. See the equivalent
-- policy in 02_document.sql for the measured attack matrix, why this is a new
-- RESTRICTIVE policy rather than an edit to the permissive ones, and why
-- `WITH CHECK (true)` is spelled out.
--
-- Keyed on conflict_is_restricted(entry_id), matching
-- resolution_confidentiality_select above: `rationale` is a human's prose about
-- the disputed values and `value_before`/`value_after` are those values
-- themselves.
--
-- The two tripwire policies above are permissive `USING (true)` for UPDATE and
-- DELETE, so that a mis-grant of either verb reaches the append-only trigger and
-- raises instead of returning a silent zero. Being AND'd rather than OR'd, the
-- policy below does not undo that for the rows this role may see: an unentitled
-- UPDATE on an *open* resolution still reaches the trigger and still raises
-- loudly. It only removes restricted rows from that role's reach, which is the
-- one case where a silent zero is the correct answer anyway -- the role is not
-- supposed to know the row exists.
CREATE POLICY resolution_app_never_restricted ON public.resolution
    AS RESTRICTIVE FOR ALL TO procurement_app
    USING (NOT public.conflict_is_restricted(entry_id))
    WITH CHECK (true);

CREATE POLICY resolution_ingest_select ON public.resolution
    FOR SELECT TO procurement_ingest USING (true);

GRANT SELECT, INSERT ON public.resolution TO procurement_app;
GRANT SELECT, INSERT ON public.resolution TO procurement_ingest;

CREATE TRIGGER resolution_no_mutation
    BEFORE UPDATE OR DELETE ON public.resolution
    FOR EACH ROW
    EXECUTE FUNCTION public.reject_mutation();

-- See 04_claim.sql for why this is separate from the row-level trigger above.
-- This table is the record of what a human decided, so losing it to a TRUNCATE
-- CASCADE from `claim` is the worst of the three -- FR-HITL-04 has no other
-- copy of a reviewer's rationale.
CREATE TRIGGER resolution_no_truncate
    BEFORE TRUNCATE ON public.resolution
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.reject_truncate();
