-- public.claim -- contract C1, the C8 invariant (tasks.md:31-46).
--
-- One immutable row per proposed field value: "workers propose, they do not
-- commit." The canonical value for a field is a projection over these rows,
-- computed by a reducer outside this schema. There is no UPDATE path here by
-- design, not merely by omission -- see the GRANT and trigger at the foot of
-- this file.
--
-- Depends on: 02_document.sql.

CREATE TABLE public.claim (
    claim_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- The document this claim is *about* -- i.e. which ingested document's
    -- component instance the field value describes. This is independent of
    -- where the evidence came from: a web-search-derived claim still names the
    -- document/component whose gap it fills, even though its own source_ref
    -- (below) may carry a URL rather than a document page. Do not conflate the
    -- two: source_ref->>'document_id' (the evidentiary reference, may be null)
    -- is a different value from this column (the claim's subject, never null).
    document_id        text NOT NULL REFERENCES public.document (document_id) ON DELETE RESTRICT,

    component_category text NOT NULL CHECK (component_category IN (
                           'pv_modules', 'inverters_pcs', 'trackers_mounting',
                           'transformers', 'cabling_wiring', 'combiner_boxes',
                           'bess', 'ems_scada'
                       )),
    supplier           text NOT NULL,
    model              text NOT NULL,
    -- Bin discriminator (component.py, ComponentInstance.nameplate: "one
    -- datasheet routinely covers several SKUs"). Nullable because not every
    -- category has one; see the note on the natural-key constraint below for
    -- what that means for collision-freedom on non-PV categories.
    nameplate          double precision,

    -- The frozen contract's own `key` column
    -- (contracts/canonical-parameters.md), e.g. `nameplate_power`. Not
    -- validated against the contract's field list at the DDL layer -- that
    -- check belongs with the application/test suite, the same way
    -- services/conflict_hitl/tolerance.py tests its own table against the
    -- contract rather than this schema re-deriving the list.
    field              text NOT NULL,
    extractor_version  text NOT NULL,

    -- CanonicalField's remaining six keys (schema/field.py): value, unit,
    -- verbatim_value, condition, source_tier, source_ref, confidence.
    -- conflict_status and resolution are deliberately absent here -- those
    -- belong to the canonical projection and the conflict queue, never to a
    -- raw claim.
    value              jsonb NOT NULL,
    unit               text,
    verbatim_value     text,
    -- schema.field.Condition, serialised whole, because Condition already
    -- treats its own field set generically (ConditionDimensions.model_fields)
    -- rather than one column per dimension -- mirroring that here means a new
    -- condition dimension needs no migration to this table.
    condition          jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_tier        text NOT NULL CHECK (source_tier IN ('system_of_record', 'web_supplement')),
    -- schema.field.SourceRef, serialised whole. May itself carry a document_id
    -- different from, or absent alongside, the outer document_id column above
    -- -- see the comment on that column.
    source_ref         jsonb NOT NULL,
    confidence         double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),

    extracted_at       timestamptz NOT NULL DEFAULT now(),

    -- A claim records that something WAS found; a field genuinely absent from a
    -- document produces no row at all (CellFlag.MISSING_DATA is a property of
    -- the canonical projection, not of an individual claim). This CHECK is the
    -- backstop for that design choice: a JSON null here would silently mean
    -- both things at once.
    CONSTRAINT claim_value_is_not_json_null CHECK (value <> 'null'::jsonb),

    -- The C8 key, extended. tasks.md:31 writes it literally as
    -- (document_id, field, extractor_version); taken that literally it
    -- collides across every SKU one multi-bin datasheet describes --
    -- component.py's own docstring: "a Trina TSM-NEG21C.20 sheet spans 6 bins
    -- and 22 CEC rows." The component-instance identity (category, supplier,
    -- model, nameplate) is added so this constraint means what C8 intends
    -- rather than what it literally says -- flagged in sql/README.md as an
    -- interpretation, not a literal reading, of a frozen contract.
    --
    -- NULLs in `nameplate` are NOT collapsed (no NULLS NOT DISTINCT): a
    -- category without a bin discriminator would otherwise need every claim
    -- for one supplier+model in one document to be the sole instance, which is
    -- not guaranteed. This is a known, narrow gap, not a solved one -- see
    -- sql/README.md.
    --
    -- This also assumes extractor_version is fine-grained enough to
    -- distinguish genuinely different extraction strategies for the same
    -- field (e.g. WP-B B.6's field-guided vs document-guided cross-read), so
    -- that the two produce distinct claim rows rather than colliding under
    -- this key -- also flagged in sql/README.md.
    CONSTRAINT claim_natural_key UNIQUE (
        document_id, component_category, supplier, model, nameplate, field, extractor_version
    )
);

COMMENT ON TABLE public.claim IS
    'C1 core table, append-only per the C8 invariant (tasks.md:31). No '
    'UPDATE/DELETE is granted below; the trigger at the foot of this file is a '
    'secondary tripwire only, mirroring plan.md Decision 9''s reasoning for '
    'audit.event -- privilege separation is the actual boundary.';

CREATE INDEX claim_document_field_idx ON public.claim (document_id, field);
CREATE INDEX claim_supplier_model_idx ON public.claim (supplier, model);
CREATE INDEX claim_condition_gin_idx ON public.claim USING gin (condition jsonb_path_ops);

ALTER TABLE public.claim OWNER TO procurement_owner;

-- No UPDATE/DELETE below: this is the actual "no UPDATE path" tasks.md's C8
-- invariant asks for. The trigger further down is free extra insurance, not
-- the boundary -- a superuser or the table owner can still bypass it, exactly
-- as Decision 9 documents for audit.event.
GRANT SELECT, INSERT ON public.claim TO procurement_app;

-- Shared immutability tripwire, reused by resolution (06_resolution.sql) for
-- the same reasoning. Owned by procurement_owner, the owner of every table
-- that uses it; audit.event gets its own copy in the audit schema
-- (07_audit_event.sql) so that function ownership never crosses the
-- audit/core privilege boundary either.
CREATE FUNCTION public.reject_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION
        'this table is append-only: % is rejected by trigger (secondary tripwire '
        'only; privilege separation above is the actual boundary -- plan.md '
        'Decision 9). ALTER TABLE ... DISABLE TRIGGER and '
        'session_replication_role=replica both bypass this trigger with no DDL '
        'trace at all.', TG_OP;
END;
$$;

ALTER FUNCTION public.reject_mutation() OWNER TO procurement_owner;

CREATE TRIGGER claim_no_mutation
    BEFORE UPDATE OR DELETE ON public.claim
    FOR EACH ROW
    EXECUTE FUNCTION public.reject_mutation();
