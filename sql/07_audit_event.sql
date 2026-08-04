-- audit.event -- contract C4. The append-only, hash-chained audit envelope
-- (plan.md Decision 9; tasks.md WP-H).
--
-- Every extraction, conflict detection and resolution this pipeline performs is
-- expected to also write one of these rows, in the SAME transaction as the
-- business write. Rollback erasing the audit record is correct, not a bug: if
-- the extraction rolled back, it did not happen, and logging that it did would
-- be a false record. The genuine "we attempted X and it failed" case is a
-- different event class (event_type = attempt_failed below), logged from the
-- exception handler in a NEW transaction after the failure. Do not reach for
-- dblink or any other autonomous-transaction trick to make an audit row survive
-- the rollback of its own business transaction -- plan.md Decision 9 explicitly
-- rejects this, because it reintroduces exactly the failure (a logged event
-- that did not really happen) the same-transaction rule exists to prevent.
--
-- THE ADVISORY LOCK IS NOT IN THIS FILE, and that is deliberate. Decision 9's
-- measured finding: an advisory lock taken inside a trigger on this table does
-- not work, because the statement snapshot a trigger's queries run against is
-- taken before the trigger body acquires the lock -- a concurrent waiter still
-- reads a stale chain tip, and 8 concurrent writers produced 42 silent forks
-- under exactly this design. The fix that measured zero forks is a lock taken
-- as ITS OWN STATEMENT by the Python caller, before it reads the chain tip and
-- before it INSERTs. There is no way to express "take this lock first" as a
-- table constraint or a trigger without reintroducing the bug being fixed, so
-- it is not attempted here. The expected caller sequence (WP-H H.4), enforced
-- by code review and by the Python client library, NOT by this schema:
--
--   1. SELECT pg_advisory_xact_lock(hashtext(document_id));    -- own statement
--   2. SELECT hash FROM audit.event
--        WHERE document_id = $1 ORDER BY seq DESC LIMIT 1;     -- read the tip
--   3. -- in Python, per WP-H H.2: canonicalise the payload (RFC 8785, NOT
--      -- jsonb -- jsonb normalises key order but preserves whatever numeric
--      -- literal text it was given, so 1.0 and 1.00 stay textually distinct)
--      -- and compute hash := sha256(prev_hash || canonical_payload || ...).
--   4. INSERT INTO audit.event (...) VALUES (...);             -- same txn
--
-- UNIQUE(document_id, prev_hash) below turns any violation of that discipline
-- into a loud unique-violation error instead of a silent fork -- "necessary,
-- insufficient" per Decision 9: it catches a fork after the fact, it does not
-- prevent the race that causes one, which is why step 1 still matters.
--
-- THERE IS NO `stream` COLUMN, and its absence is deliberate rather than an
-- omission. Earlier versions carried `stream text NOT NULL` beside
-- `document_id`, tied to it by `CHECK (stream = 'doc:' || document_id)`, and
-- keyed all three UNIQUEs and the self-FK on it. The chain identity is
-- `document_id`, directly. Decision 9 requires the chain be per document "not
-- globally, so cross-document concurrency stays unconstrained", and
-- document-scoped uniqueness carries that requirement whole -- there was nothing
-- `stream` said that `document_id` did not already say. Its one hypothetical
-- value, a future non-document audit stream, was structurally foreclosed by the
-- very CHECK that kept it consistent; sql/README.md's decision 8 said so in as
-- many words ("this table cannot be reused for any future non-document audit
-- stream as-is"). A column whose single degree of freedom is constrained to zero
-- is redundancy, not capability, and it cost a CHECK, a wider key in three
-- indexes, and a second name for one thing in every caller.
--
-- Removed *now* because C4's Python half does not exist yet: tasks.md marks C4
-- partial -- "the bytes the `hash` column is computed over are still undefined;
-- nothing may emit an event". After the first real chain exists, the column is
-- frozen into it. tasks.md H.3 and H.4, and plan.md Decision 9, all named the
-- removed column; A-42 in specs/001-procurement-agent/analysis.md recorded them
-- as outstanding from this file and they were corrected at integration.
--
-- Depends on: 01_extensions_and_settings.sql (schema audit), 02_document.sql.

CREATE TABLE audit.event (
    event_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- **The chain identity.** Decision 9: "chain per document ... not globally,
    -- so cross-document concurrency stays unconstrained." Every UNIQUE and the
    -- self-FK below lead on this column, which is what makes "never global" a
    -- structural property of the table rather than a convention a caller could
    -- forget -- there is no value of this column that names anything but one
    -- real document, because it is a foreign key. See the header for why the
    -- separate `stream` column that used to carry this was removed.
    document_id        text NOT NULL REFERENCES public.document (document_id) ON DELETE RESTRICT,

    -- Ordering within a document's chain. A convenience for ORDER BY and for
    -- the H.5 verification CLI, which would otherwise walk the linked list one
    -- prev_hash lookup at a time; it is NOT itself the concurrency-safety
    -- mechanism -- that is the advisory-lock discipline above, plus the UNIQUE
    -- constraints below.
    seq                bigint NOT NULL CHECK (seq >= 0),

    -- Hash chain. NULL prev_hash marks the one genesis event for a document.
    -- Digest algorithm is assumed to be SHA-256 (32 bytes): plan.md Decision 9
    -- measures chain performance but never pins an algorithm, so this is one
    -- of this file's flagged decisions -- see sql/README.md. If WP-H picks a
    -- different digest, these two CHECKs need to change with it.
    prev_hash          bytea CHECK (prev_hash IS NULL OR octet_length(prev_hash) = 32),
    hash               bytea NOT NULL CHECK (octet_length(hash) = 32),

    -- C4's event_type taxonomy. A CHECK, not a native enum type, for the same
    -- extensibility reason as document.document_type: a later ALTER TABLE ...
    -- DROP/ADD CONSTRAINT is far less awkward than ALTER TYPE ... ADD VALUE,
    -- which can never be dropped from once added. This taxonomy is NOT frozen
    -- by any spec document (tasks.md marks C4's status unfrozen); the seven
    -- values below are this file's own proposal -- see sql/README.md.
    event_type         text NOT NULL CHECK (event_type IN (
                           'document_ingested',
                           'parse_failure',
                           'extraction',
                           'web_search',
                           'conflict_detected',
                           'resolution',
                           'attempt_failed'
                       )),

    -- Who or what produced the event: a worker identity, a reviewer's email, a
    -- service name. Free text deliberately -- unlike event_type this is not a
    -- closed taxonomy the pipeline reasons over.
    actor              text NOT NULL,

    -- The RFC 8785 (JCS) canonical JSON text, produced in Python per WP-H H.2,
    -- NOT in SQL. `hash` above is computed over these exact bytes; this is
    -- what the H.5 verification CLI re-hashes to check the chain, never the
    -- `payload` column below.
    payload_canonical  text NOT NULL,

    -- Query and index convenience only, generated from payload_canonical so
    -- the two can never drift -- there is no application code path that
    -- writes one without the other. Never used to reverify the hash: casting
    -- back through jsonb is exactly the round-trip H.2's own reasoning warns
    -- against trusting as a canonicalisation step.
    payload            jsonb GENERATED ALWAYS AS (payload_canonical::jsonb) STORED NOT NULL,

    recorded_at        timestamptz NOT NULL DEFAULT clock_timestamp(),

    -- A genesis event (no parent) must be seq 0, and every non-genesis event
    -- must have a parent; this ties the two redundant ordering mechanisms
    -- together so a caller bug that disagrees between them fails loudly at
    -- INSERT rather than producing a chain that looks fine until someone
    -- walks it.
    CONSTRAINT audit_event_genesis_seq_zero
        CHECK ((prev_hash IS NULL) = (seq = 0)),

    -- Fork detection, loud rather than silent (Decision 9's own phrase).
    -- NULLS NOT DISTINCT (PostgreSQL 15+, available under Decision 3's
    -- PostgreSQL 18 pin) so that two genesis events for one document (both
    -- prev_hash NULL) collide too -- an ordinary UNIQUE constraint treats two
    -- NULLs as distinct and would let one document's chain grow two unrelated
    -- roots.
    CONSTRAINT audit_event_no_fork UNIQUE NULLS NOT DISTINCT (document_id, prev_hash),
    CONSTRAINT audit_event_seq_unique UNIQUE (document_id, seq),

    -- The chain has to be walkable, not merely fork-free.
    --
    -- `audit_event_no_fork` catches one shape of tampering: two children of the
    -- same parent. Review found three it does not, all accepted as
    -- procurement_app against the first version of this file:
    --
    --   1. a row whose prev_hash names a parent that never existed
    --   2. a second, disconnected root in the same document's chain (seq 900,
    --      prev_hash pointing at a fabricated digest) -- a fork made by starting
    --      a new segment rather than by branching an existing one, which is
    --      precisely what the comment above claims to prevent
    --   3. two rows in one document's chain sharing a `hash`, i.e. a chain loop
    --
    -- Each is silent, and each produces a chain that can never be verified.
    -- Decision 9 leans on this chain as "the only mechanism that survives the
    -- superuser bypass -- a superuser can edit a row but cannot make the chain
    -- re-verify", so a chain that was never walkable in the first place gives
    -- that argument nothing to stand on.
    --
    -- UNIQUE (document_id, hash) makes a digest identify at most one event per
    -- document, which is what lets the self-reference below be a foreign key at
    -- all, and independently rules out (3).
    CONSTRAINT audit_event_hash_unique UNIQUE (document_id, hash)
);

-- The self-reference: every non-genesis event's parent must exist, in the same
-- document's chain. Added after the table rather than inline because a
-- self-referential FK cannot be declared against a unique constraint defined in
-- the same CREATE TABLE statement.
--
-- NOT VALID is deliberately NOT used: this file creates the table empty, so
-- there is nothing to validate against and the constraint is enforced from the
-- first INSERT.
--
-- MATCH SIMPLE (the default) is what makes genesis work: with prev_hash NULL
-- the constraint is satisfied without a parent, so `audit_event_genesis_seq_zero`
-- above remains the thing that ties genesis to seq 0.
--
-- ON DELETE/UPDATE RESTRICT rather than CASCADE -- a cascade here would let one
-- deletion unravel a whole chain, which is the opposite of the property this
-- table exists to provide. The append-only triggers below already reject both
-- verbs; this is the same defence stated where a reader of the constraint will
-- see it.
ALTER TABLE audit.event
    ADD CONSTRAINT audit_event_parent_exists
    FOREIGN KEY (document_id, prev_hash)
    REFERENCES audit.event (document_id, hash)
    ON DELETE RESTRICT
    ON UPDATE RESTRICT;

COMMENT ON TABLE audit.event IS
    'C4 audit event envelope. Immutable: see the triggers below and the GRANT '
    'at the foot of this file. Privilege separation (00_roles.sql) is the '
    'actual boundary per plan.md Decision 9; the triggers are a free secondary '
    'tripwire that catches a mis-grant, nothing more.';

-- A prefix-duplicate of `audit_event_seq_unique`'s index since the re-key, and
-- kept anyway: `document_id` alone is the RLS policy's filter and the H.5 chain
-- walk's filter, and a one-column index is materially smaller than the
-- (document_id, seq) unique it would otherwise share. Recorded rather than left
-- for a reader to wonder about, because "why are there two indexes led by the
-- same column" is a fair question with a boring answer.
CREATE INDEX audit_event_document_id_idx ON audit.event (document_id);
CREATE INDEX audit_event_type_idx ON audit.event (event_type);

ALTER TABLE audit.event OWNER TO audit_owner;

REVOKE ALL ON audit.event FROM PUBLIC;
GRANT USAGE ON SCHEMA audit TO procurement_app;
GRANT SELECT, INSERT ON audit.event TO procurement_app;
GRANT USAGE ON SCHEMA audit TO procurement_ingest;
GRANT SELECT, INSERT ON audit.event TO procurement_ingest;

-- ---------------------------------------------------------------------------
-- Confidentiality (NFR-03, AC-8). `payload_canonical` -- and therefore the
-- generated `payload` -- is the extraction's own content: the price that was
-- read, the certification that was found. Measured as procurement_app against a
-- document that role could not see:
--
--     SELECT document_id FROM public.document WHERE document_id = 'doc-secret';
--      (0 rows)
--     SELECT document_id, event_type, payload FROM audit.event
--       WHERE document_id = 'doc-secret';
--      doc-secret | document_ingested | {"price_per_watt_dc": 0.19}
--      doc-secret | extraction        | {"price_per_watt_dc": 0.19}
--
-- An audit log that reproduces the material it audits is a copy of that
-- material, and NFR-03 does not carve out an exception for copies. The
-- derivation is the document the event's chain belongs to -- structurally exact
-- here, because `document_id` IS the chain identity and a NOT NULL foreign key,
-- so an event's subject document is never ambiguous and never absent.
--
-- **This does not weaken Decision 9.** RLS governs SELECT visibility; it is not
-- and never was the immutability boundary -- that is the GRANT above (no UPDATE,
-- no DELETE, no TRUNCATE) plus the tripwires below. Nothing here can hide an
-- event from the H.5 verification CLI either: that runs as an operator identity
-- which sets `app.allow_restricted`, exactly as the confidentiality model
-- intends, and a chain walk that skipped rows would fail to verify rather than
-- pass quietly.
ALTER TABLE audit.event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit.event FORCE ROW LEVEL SECURITY;

CREATE POLICY audit_event_confidentiality_select ON audit.event
    FOR SELECT
    USING (
        NOT public.document_is_restricted(document_id)
        OR current_setting('app.allow_restricted', true) = 'true'
    );

-- INSERT needs its own policy or RLS's per-command default-deny starves the
-- GRANT above.
--
-- Note the consequence for the caller sequence at the top of this file: step 2
-- reads the chain tip with a SELECT, so a worker appending to a restricted
-- document's chain must connect as procurement_ingest (00_roles.sql), which the
-- policy below entitles. Under procurement_app that SELECT returns no rows and
-- the worker would compute a genesis event for a document whose chain already
-- has one -- caught loudly by audit_event_no_fork, but caught late.
CREATE POLICY audit_event_write_insert ON audit.event
    FOR INSERT
    WITH CHECK (true);

CREATE POLICY audit_event_ingest_select ON audit.event
    FOR SELECT TO procurement_ingest USING (true);

-- Permissive UPDATE/DELETE policies on the append-only table, for the reason
-- given at length in 04_claim.sql. Without them, enabling RLS above would have
-- quietly *disabled* the Decision 9 tripwire this file's whole second half is
-- about: RLS filters rows out before a FOR EACH ROW trigger runs, so
-- `UPDATE audit.event SET actor = 'x'` as audit_owner returned `UPDATE 0`
-- instead of raising. Decision 9's attack matrix lists that cell as
-- "Trigger: blocked", and a silent no-op is not blocked, it is unmeasured.
-- Neither verb is granted to any role; these policies only make a mis-grant
-- audible.
CREATE POLICY audit_event_tripwire_update ON audit.event FOR UPDATE USING (true);
CREATE POLICY audit_event_tripwire_delete ON audit.event FOR DELETE USING (true);

-- Forward-looking only: this affects audit tables that audit_owner itself
-- creates after this point (for example, via SET ROLE audit_owner in a later
-- migration), not audit.event above, which a bootstrap identity created and
-- then transferred to audit_owner via ALTER TABLE ... OWNER TO. A harmless
-- no-op until such a table exists.
ALTER DEFAULT PRIVILEGES FOR ROLE audit_owner IN SCHEMA audit
    GRANT SELECT, INSERT ON TABLES TO procurement_app;

-- ---------------------------------------------------------------------------
-- Secondary tripwires. Decision 9: "Add the trigger too -- it is free and
-- catches a mis-grant -- but do not count it as the boundary."
--
-- Both of the triggers below are bypassed by ALTER TABLE ... DISABLE TRIGGER,
-- and by session_replication_role = 'replica' -- the latter with NO DDL trace
-- at all, which is exactly the bypass Decision 9 says people forget. Both are
-- also bypassed outright by an actual PostgreSQL superuser, regardless of
-- FORCE ROW LEVEL SECURITY or any GRANT here. The only durable answer to that
-- threat model is shipping this log OUT -- logical replication to a
-- write-once sink -- which is out of scope for this DDL and is not attempted
-- here.
-- ---------------------------------------------------------------------------

CREATE FUNCTION audit.reject_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION
        'audit.event is append-only: % is rejected by trigger (secondary '
        'tripwire only; privilege separation is the actual boundary -- plan.md '
        'Decision 9). ALTER TABLE ... DISABLE TRIGGER and '
        'session_replication_role=replica both bypass this trigger with no DDL '
        'trace at all.', TG_OP;
END;
$$;

ALTER FUNCTION audit.reject_mutation() OWNER TO audit_owner;

CREATE TRIGGER audit_event_no_mutation
    BEFORE UPDATE OR DELETE ON audit.event
    FOR EACH ROW
    EXECUTE FUNCTION audit.reject_mutation();

-- BEFORE TRUNCATE must be its own trigger, declared FOR EACH STATEMENT: a
-- TRUNCATE trigger cannot be a row-level trigger, so it cannot be folded into
-- audit_event_no_mutation above even though the two share almost identical
-- wording.
CREATE FUNCTION audit.reject_truncate() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION
        'audit.event is append-only: TRUNCATE is rejected by trigger '
        '(secondary tripwire only, NOT the boundary -- plan.md Decision 9). '
        'This trigger is bypassed by ALTER TABLE ... DISABLE TRIGGER and by '
        'session_replication_role=replica, the latter leaving no DDL trace at '
        'all. It also cannot help against a superuser connection. The only '
        'durable answer to that threat model is shipping this log out '
        '(logical replication to a write-once sink), not another trigger.';
END;
$$;

ALTER FUNCTION audit.reject_truncate() OWNER TO audit_owner;

CREATE TRIGGER audit_event_no_truncate
    BEFORE TRUNCATE ON audit.event
    FOR EACH STATEMENT
    EXECUTE FUNCTION audit.reject_truncate();
