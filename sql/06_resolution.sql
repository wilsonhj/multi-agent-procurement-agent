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

GRANT SELECT, INSERT ON public.resolution TO procurement_app;

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
