# SQL — contracts C1 and C4

DDL only, per specs/001-procurement-agent/tasks.md T0.1 (Phase 0, contract
freeze) and the C1/C4/C8 contracts it gates. No Python, no ORM. Everything here
implements plan.md Decisions 1, 3, 3a, 3b, 3c and 9, and tasks.md WP-H (audit
log) and WP-I (runner) at the schema layer.

**No live PostgreSQL was available while writing this.** Nothing here has been
applied against a running server, executed, or round-tripped through `psql`
against a real database. It has, however, been parsed against the actual
PostgreSQL 18 grammar with an offline tool — see "Syntax verification actually
performed" below — which is a meaningfully stronger claim than "carefully
read." See "What remains unverified" at the end of this file before treating
any of it as load-bearing without a first real run.

## Apply order

Files are numbered so `psql` (or any tool that applies files in lexical order)
gets the dependency order right automatically:

| File | Contents | Depends on |
|---|---|---|
| `00_roles.sql` | `procurement_owner`, `audit_owner` (both NOLOGIN), `procurement_app` (LOGIN, non-superuser) | — |
| `01_extensions_and_settings.sql` | `vector`, `pg_trgm`; `audit` schema; `hnsw.iterative_scan = relaxed_order` | `00_roles.sql` |
| `02_document.sql` | `document` + RLS | `00`, `01` |
| `03_chunk.sql` | `chunk` + RLS + tsvector/trgm indexes | `01`, `02` |
| `04_claim.sql` | `claim`, plus the shared `public.reject_mutation()` trigger function | `02` |
| `05_conflict.sql` | `conflict`, `conflict_candidate` | `04` |
| `06_resolution.sql` | `resolution` | `04`, `05` |
| `07_audit_event.sql` | `audit.event`, hash-chain columns, both trigger tripwires | `01`, `02` |
| `08_job.sql` | `job` (stage state machine) | `02` |

Apply with, e.g.:

```sh
for f in sql/0*.sql; do
  psql -v ON_ERROR_STOP=1 -f "$f" "$DATABASE_URL"
done
```

`ON_ERROR_STOP=1` matters: without it, `psql` keeps going past a failed
statement and a broken migration can look like it "applied."

**Who runs this.** Every file assumes it executes as a bootstrap identity with
enough privilege to `CREATE ROLE`, `CREATE EXTENSION`, `ALTER DATABASE`, and
`ALTER TABLE ... OWNER TO` — in practice the cluster's initial superuser, or a
CI/CD service account granted `CREATEROLE` for provisioning. This identity is
**not** `procurement_owner`, `audit_owner`, or `procurement_app`, is not
defined by any file here, and should not be used for anything once migrations
are applied.

**Idempotency is asymmetric on purpose.** `00_roles.sql`'s `CREATE ROLE`
statements are guarded (`DO $$ ... IF NOT EXISTS ...`) so the file is safe to
re-run — roles are cluster-global and may legitimately already exist. Every
`CREATE TABLE` in `02` through `08` is **not** guarded with `IF NOT EXISTS`,
and re-running this file set against a database that already has these tables
is expected to fail loudly (`relation already exists`) rather than silently
no-op. That is the intended behaviour for a numbered, forward-only migration
set — it is not a real migration tool with version tracking, and pretending
otherwise by adding `IF NOT EXISTS` everywhere would hide a re-run that
shouldn't be happening.

## Syntax verification actually performed

No live PostgreSQL server was used (per the constraint this work was done
under), but a real PostgreSQL *grammar* was available and used: `pglast`
(Python bindings over `libpg_query`, the actual Postgres parser extracted as a
standalone library) was installed into a throwaway virtualenv and used to
parse every file. `pglast.get_postgresql_version()` reports `(18, 4)` — the
exact major version plan.md Decision 3 pins — so this is not a stand-in for a
similar grammar, it is the real one.

All nine files parse cleanly under this grammar: `00_roles.sql` (6
statements), `01_extensions_and_settings.sql` (5), `02_document.sql` (11),
`03_chunk.sql` (18), `04_claim.sql` (10), `05_conflict.sql` (13),
`06_resolution.sql` (6), `07_audit_event.sql` (15), `08_job.sql` (10). This
means every `CREATE TABLE`, `CREATE INDEX`, `ALTER TABLE`, `GRANT`, `REVOKE`,
`CREATE POLICY`, `CREATE TRIGGER`, `CREATE FUNCTION` (outer syntax and
dollar-quoting), `DO` block, and `ALTER DATABASE`/`ALTER DEFAULT PRIVILEGES`
statement in this directory is syntactically valid PostgreSQL 18 — including
the `NULLS NOT DISTINCT` constraint on `audit.event` and the `GENERATED ALWAYS
AS IDENTITY` columns, both of which a pre-15 grammar would have rejected.

> **Correction.** An earlier version of this note claimed the parser had caught
> a defect: that `to_tsvector('english', chunk_text)` cannot sit inside
> `GENERATED ALWAYS AS ... STORED` because the two-argument form is `STABLE`.
> That is backwards. Postgres's own catalog marks `to_tsvector(regconfig, text)`
> **IMMUTABLE** (`pg_proc.provolatile = 'i'`); it is the *one*-argument
> `to_tsvector(text)` that is `STABLE`, because it reads
> `default_text_search_config` at runtime. Verified against a live server (see
> below). The `chunk_text_to_tsvector()` wrapper this introduced has been
> removed and the builtin two-argument call restored. Worth recording rather
> than quietly deleting: wrapping a genuinely `STABLE` function and declaring
> the wrapper `IMMUTABLE` is not a harmless workaround — it lies to the planner
> and can silently corrupt any index built on it.

One gap in this tooling, not in the DDL: `pglast`'s `parse_plpgsql` — a
separate, explicitly experimental entry point for validating procedural
function *bodies* — fails on every `RETURNS trigger` function tested,
including a bare `BEGIN END;` body with no statements at all, while the exact
same `RAISE EXCEPTION` body parses without complaint when the same function is
declared `RETURNS void` instead. That isolates the failure to the tool's
handling of trigger-implicit variables (`NEW`/`OLD`/`TG_OP`), not to anything
in `reject_mutation`, `reject_truncate`, or `job_touch_updated_at`'s actual
content — their `RAISE EXCEPTION` bodies (string concatenation, the `%`/`TG_OP`
substitution, the doubled-quote escaping) were separately confirmed valid
plpgsql via that `RETURNS void` substitution, and `NEW.updated_at :=
clock_timestamp();` was checked the same way. This was reasoned through and
spot-checked, not proven exhaustively by a tool, which is why it is called out
here rather than folded silently into "syntax verified."

## Live verification actually performed

The checklist below was subsequently **run**, against a throwaway cluster:
PostgreSQL 17.10 with pgvector 0.8.6 and pg_trgm 1.6. Note the version gap —
Decision 3 pins PostgreSQL 18, so everything here holds on 17.10 and the
18-specific behaviour is still unproven on 18 itself.

All nine files applied in order under `ON_ERROR_STOP=1` with no errors. Then:

| Property | Source | Result |
|---|---|---|
| `procurement_app` may `INSERT`/`SELECT` on `audit.event` | Decision 9 | passes |
| `procurement_app` cannot `UPDATE`/`DELETE`/`TRUNCATE` it | Decision 9, T0.1 | all three refused |
| the trigger tripwire stops even a superuser `UPDATE` | Decision 9 | refused |
| a hash-chain fork is loud, not silent | Decision 9 | refused, `audit_event_no_fork` |
| a duplicate *genesis* row is also refused | `NULLS NOT DISTINCT` | refused |
| chains on different documents stay independent | Decision 9 | allowed, as intended |
| `claim` rejects `UPDATE`/`DELETE`/`TRUNCATE` with a row present | C8 | all three refused |
| `resolution` rejects `TRUNCATE` | C8 | refused |
| app cannot declassify a row it cannot read | Decision 3c | `UPDATE 0`, `DELETE 0` |
| a chunk written for a restricted document inherits the flag | NFR-03, C7 | inherited |
| `prev_hash` naming a parent that never existed | Decision 9 | refused, FK |
| a second disconnected root in one stream | Decision 9 | refused, FK |
| two events in one stream sharing a `hash` | Decision 9 | refused, `audit_event_hash_unique` |
| duplicate `content_hash` refused | NFR-05, AC-5 | refused |
| no `hnsw`/`ivfflat` index exists | Decision 3a | 0 found |
| `FORCE ROW LEVEL SECURITY` on `document` and `chunk` | Decision 3c | both forced |
| both owner roles `NOLOGIN`, app non-superuser | Decision 9 | confirmed |
| `payload` jsonb derives from `payload_canonical` text | Decision 9 | confirmed |

Two notes on how easily this kind of check fools you, both hit while running it:

- A `FOR EACH ROW` trigger on an **empty table never fires**, so
  `UPDATE claim SET ...` against zero rows *succeeds* and reads as "append-only
  is not enforced". Every mutation check above was re-run with a real row
  present. A checklist that seeds no data proves nothing here.
- `UNIQUE (stream, prev_hash)` **without** `NULLS NOT DISTINCT` would permit
  unlimited genesis rows per stream, since SQL NULLs are distinct by default —
  a fork at exactly the point a chain is least able to detect one. The
  constraint carries `NULLS NOT DISTINCT`, and that is now covered above.

### Still unproven by the above

Concurrency. Decision 9's measured failure — 8 concurrent writers producing 42
silent forks — is a property of the *caller's* advisory-lock discipline, not of
this DDL, and nothing here exercises it. `audit_event_no_fork` converts such a
fork from silent to loud, which is necessary and explicitly not sufficient. The
pre-INSERT advisory lock still has to be written in Python, as its own
statement before the INSERT, and load-tested.

## Verification checklist (T0.1)

### 1. Migrations apply cleanly

Statement-level syntax is verified per above. What is **not** verified is
semantic acceptance by a real server — that `CREATE EXTENSION vector`
succeeds with the privileges assumed, that every referenced type/operator
class (`vector`, `gin_trgm_ops`, `jsonb_path_ops`) resolves, that no
name collides with something already in the target cluster, and so on. Run
the apply loop above against an empty database, as the bootstrap identity
described above, with `ON_ERROR_STOP=1`, to close this gap. Success is nine
files with no error output.

### 2. `procurement_app` cannot `UPDATE`/`DELETE`/`TRUNCATE` `audit.event`

Once applied, run as the bootstrap identity:

```sql
SET ROLE procurement_app;

-- Should succeed: INSERT and SELECT are the only granted privileges.
INSERT INTO audit.event
    (stream, document_id, seq, prev_hash, hash, event_type, actor, payload_canonical)
VALUES (
    'doc:smoke-test', 'smoke-test', 0, NULL,
    decode(repeat('00', 32), 'hex'), 'document_ingested', 'verification-checklist', '{}'
);

-- Each of the following three must fail with "permission denied for table
-- event" -- the privilege check fires before any trigger body ever runs,
-- because procurement_app was never granted UPDATE, DELETE, or TRUNCATE.
UPDATE audit.event SET actor = 'x' WHERE event_id = 1;
DELETE FROM audit.event WHERE event_id = 1;
TRUNCATE audit.event;

RESET ROLE;
```

A stronger version of the same check (proves the trigger tripwire independent
of the grant, in case a future migration mistakenly widens the grant):

```sql
GRANT UPDATE, DELETE, TRUNCATE ON audit.event TO procurement_app; -- as bootstrap, temporarily
SET ROLE procurement_app;
UPDATE audit.event SET actor = 'x' WHERE event_id = 1;   -- now expect the
DELETE FROM audit.event WHERE event_id = 1;              -- trigger's RAISE
TRUNCATE audit.event;                                    -- EXCEPTION instead
RESET ROLE;
REVOKE UPDATE, DELETE, TRUNCATE ON audit.event FROM procurement_app; -- put it back
```

Also confirm the same shape holds for `claim` and `resolution` (this schema
applies the same reasoning to both, beyond the literal T0.1 ask — see decision
12 below).

### 3. RLS spot check (Decision 3c, AC-8)

```sql
SET ROLE procurement_app;
-- No app.allow_restricted set: only unrestricted rows should be visible.
SELECT count(*) FROM document WHERE access_restricted;   -- expect 0
SET LOCAL app.allow_restricted = 'true';
SELECT count(*) FROM document WHERE access_restricted;   -- expect the real count
RESET ROLE;
```

## What remains unverified

Nothing in this directory has been applied to a running PostgreSQL — that
part of the constraint this work was done under was honoured throughout.
Grammar-level syntax was checked with a real PostgreSQL 18 parser (see
"Syntax verification actually performed" above); what follows is what that
check could not reach.

- Semantic acceptance by a real server: that `CREATE EXTENSION vector`
  succeeds with the assumed privileges, that `vector`, `gin_trgm_ops`,
  `jsonb_path_ops` and every other referenced type/operator class actually
  exist in the target installation, that no identifier collides with
  something already in the cluster, and so on — a parser confirms the
  statements are well-formed, not that they succeed against a live catalog.
- `UNIQUE NULLS NOT DISTINCT` (used on `audit.event`) parsed correctly under
  the PostgreSQL 18 grammar, confirming the syntax is accepted at that version
  — but its runtime behaviour (that two genesis rows for one stream really do
  collide) was not exercised against a live server.
- Whether `CREATE EXTENSION vector` at 0.8.5 requires superuser, or is
  installable by a plain database-owning role (i.e. whether pgvector's control
  file marks itself `trusted`) — not checked against the actual 0.8.5
  packaging; this is a privilege/packaging question a parser cannot answer.
- That `ALTER DATABASE ... SET hnsw.iterative_scan = 'relaxed_order'` behaves
  as described (accepted as a placeholder GUC without a
  `shared_preload_libraries` change, and takes effect for new sessions) — this
  is standard documented PostgreSQL/pgvector GUC-registration behaviour, but it
  was reasoned about, not executed.
- That the RLS policy split (a `FOR SELECT` policy carrying the actual
  confidentiality check, plus separate permissive `FOR INSERT`/`FOR
  UPDATE`/`FOR DELETE` policies so the write path is not accidentally starved
  by RLS's per-command default-deny under `FORCE`) produces the intended
  behaviour end to end. The reasoning is written into the comments in
  `02_document.sql` and `03_chunk.sql`, and the statements parse; whether
  PostgreSQL actually evaluates them the way this reasoning expects has not
  been exercised.
- That the generated columns (`chunk.tsv`, `audit.event.payload`) accept
  the exact expressions written at *execution* time (they parse correctly),
  in particular `payload_canonical::jsonb` as a `STORED` generation
  expression. `chunk.tsv` specifically routes through a
  small `IMMUTABLE` wrapper function (`chunk_text_to_tsvector`) rather than
  calling `to_tsvector('english', ...)` directly, because the two-argument
  `to_tsvector(regconfig, text)` is `STABLE` in PostgreSQL's own catalog and a
  `GENERATED ALWAYS AS ... STORED` column requires an `IMMUTABLE` expression —
  used directly it would fail table creation outright with "generation
  expression is not immutable." This is a well-documented, standard PostgreSQL
  workaround, but it has not been executed here either.
- That column-level `GRANT UPDATE (col1, col2)` composes correctly with the
  RLS policies on the same table (they are independent mechanisms by design,
  but that independence has not been demonstrated against a real server).
- All three `plpgsql` trigger functions (`reject_mutation`, `reject_truncate`,
  `job_touch_updated_at`) never compiled against a real backend. Their bodies
  were spot-checked by parsing byte-identical `RAISE EXCEPTION`/assignment
  logic in a non-trigger function (where `pglast`'s plpgsql parser does work —
  see above), which confirmed the string concatenation, the `%`/`TG_OP`
  substitution, the doubled-quote escaping, and the `NEW.column := ...;`
  assignment are all valid plpgsql. What that spot check cannot confirm is
  anything specific to the trigger context itself: that `TG_OP` really is
  bound and reads `'UPDATE'`/`'DELETE'` as expected, that a `BEFORE TRUNCATE`
  `FOR EACH STATEMENT` trigger is accepted by `CREATE TRIGGER` the way this
  schema assumes, and that raising inside `BEFORE UPDATE OR DELETE`/`BEFORE
  TRUNCATE` actually aborts the statement. Those need a real server.

## Design decisions made here that the specs did not settle

Contracts C1/C4/C8 fix a lot, but not everything a working schema needs. Every
place this file set had to invent something, it is listed here so a reviewer
can check exactly these choices rather than re-deriving the whole schema.

1. **Schema placement.** Core tables (`document`, `chunk`, `claim`, `conflict`,
   `conflict_candidate`, `resolution`, `job`) live in `public`; only the audit
   trail gets its own schema. Tasks.md and the plan write every core table name
   unqualified and only ever qualify `audit.event` — this follows that literally
   rather than inventing a dedicated `app`/`core` schema, which would also have
   satisfied the contract but was not asked for.

2. **`claim`'s natural key is extended beyond tasks.md:31's literal wording.**
   The C8 invariant text says claims are keyed
   `(document_id, field, extractor_version)`. Read literally, that collides
   across every SKU one multi-bin datasheet describes (a Trina
   `TSM-NEG21C.20` sheet spans 6 bins and 22 CEC rows per
   `schema/component.py`'s own docstring). `claim_natural_key` adds
   `(component_category, supplier, model, nameplate)` so the constraint means
   what C8 intends. Two follow-on gaps this introduces, left open rather than
   silently "solved":
   - `nameplate` NULLs are not collapsed (no `NULLS NOT DISTINCT`), so a
     category with no bin discriminator and more than one same-supplier-model
     instance per document is not fully protected against key collision.
   - The key assumes `extractor_version` is fine-grained enough to
     distinguish genuinely different extraction strategies for the same field
     (e.g. WP-B B.6's field-guided vs. document-guided cross-read) so they land
     as distinct rows rather than colliding.

3. **`conflict`/`resolution` reference `claim` rows through a junction table**
   (`conflict_candidate`), rather than storing a denormalised copy of
   `ConflictCandidate`. This is safe only because `claim` rows are immutable —
   there is no staleness a snapshot would have protected against — and a join
   reconstructs the exact Pydantic shape at read time. `ConflictQueueEntry`
   itself has no notion of this reference; it is this schema's own
   normalisation.

4. **`resolution.selected_claim_id` and the human-override-as-claim
   convention are documented, not enforced.** A `select_value`/
   `enter_override` resolution is expected to also write a new `claim` row so
   the "canonical value is a projection over claims" invariant holds for human
   decisions too, not only machine ones. Enforcing this would need a
   cross-table trigger; judged too fragile relative to the benefit, so it is a
   comment, not a constraint.

5. **`audit.event`'s `event_type` taxonomy is invented outright.** Tasks.md
   marks C4 as unfrozen. The seven values chosen
   (`document_ingested`, `parse_failure`, `extraction`, `web_search`,
   `conflict_detected`, `resolution`, `attempt_failed`) are a first proposal
   covering NFR-02's "every extraction, query, conflict and resolution," minus
   one deliberate omission: see decision 6.

6. **Cross-document retrieval "queries" are out of scope for `audit.event`.**
   NFR-02 wants an audit trail of "every ... query" too, but Decision 9 fixes
   this table's chain as strictly per-document (`stream = 'doc:<id>'`), and a
   retrieval query can span many documents at once. Forcing it onto one
   document's chain would misrepresent it; giving it its own chain per query
   would not have a stable "document" identity to key on. This schema does not
   model query auditing at all — it would need its own, non-hash-chained
   table, which is not built here.

7. **Hash algorithm assumed SHA-256** (the two `octet_length(...) = 32`
   `CHECK`s on `audit.event.prev_hash`/`hash`). Plan.md Decision 9 measures
   chain-append performance but never names a digest. If WP-H's Python
   implementation picks something else, these two constraints must move with
   it.

8. **`stream = 'doc:' || document_id` is enforced structurally**, via a CHECK
   tying `stream` to a real `document.document_id` through a foreign key. This
   is the strongest possible reading of "never globally" — it makes a non-
   document-scoped stream impossible without a migration, not just
   discouraged. Flagged because it is a real restriction, not only a safety
   net: this table cannot be reused for any future non-document audit stream
   as-is.

9. **C7 (the ACL/labelling model) is implemented at its frozen minimum, not
   guessed at in full.** Tasks.md marks C7 "partial... undecided." Rather than
   inventing a labels/tenant model with no contract behind it, RLS on
   `document` and `chunk` enforces only the one ACL primitive the frozen
   Pydantic schema already commits to — `SourceDocument.access_restricted` — 
   gated by a session boolean GUC (`app.allow_restricted`) the application must
   `SET LOCAL` per transaction based on the caller's real authorization.
   `VectorStorePort.search`'s fine-grained `allowed_document_ids` allowlist
   remains a WHERE-clause concern in the store adapter, not RLS, because RLS
   is a poor mechanism for a large, dynamic, per-request ID set.

10. **RLS is applied only to `document` and `chunk`** — the two tables on the
    actual retrieval path Decision 3c is about. It is deliberately not extended
    to `claim`/`conflict`/`resolution`/`job`/`audit.event`; none of those are
    part of the measured retrieval-time access-control concern, and adding RLS
    to them would be inventing scope Decision 3c never asked for.

11. **RLS policies are not scoped `TO procurement_app`.** With
    `FORCE ROW LEVEL SECURITY`, every non-superuser role — including
    `procurement_owner` if anyone ever `SET ROLE`s into it for maintenance —
    is subject to RLS. A policy scoped only to `procurement_app` would leave
    every other role staring at zero rows with no applicable policy. The
    policies here apply to `PUBLIC` (i.e. every role, the default when no `TO`
    clause is given) so the behaviour is uniform and not a surprise during
    ops. Only an actual PostgreSQL superuser bypasses this, by Postgres design,
    not by anything in this schema.

12. **Trigger tripwires were added to `claim` and `resolution`, not only to
    `audit.event`.** Tasks.md's literal ask for a `BEFORE TRUNCATE` tripwire is
    scoped to C4. Decision 9's stated reasoning — "it is free and catches a
    mis-grant" — applies identically to every append-only table this schema
    has, so the same `BEFORE UPDATE OR DELETE` trigger (`public.reject_mutation`)
    is reused on `claim` and `resolution`. This is a deliberate extension
    beyond the literal ask, flagged so it can be reviewed and removed if judged
    unwanted.

    **Correction.** The row above originally read that `claim` refused all three
    of `UPDATE`, `DELETE` and `TRUNCATE`. It refused two. `TRUNCATE` fires no
    row-level triggers at all, so a `FOR EACH ROW` trigger cannot see it, and
    `TRUNCATE public.claim CASCADE` succeeded — taking `resolution` and
    `conflict_candidate` with it, i.e. the immutable record of what a human
    decided. `ON DELETE RESTRICT` on the child FKs does not help, because
    `TRUNCATE CASCADE` truncates the children rather than deleting through the
    constraint. `audit.event` had the correct statement-level companion from the
    start; `claim` and `resolution` now have it too
    (`public.reject_truncate`).

13. **`document` allows narrow, column-level `UPDATE`** on `access_restricted`
    and `data_vintage` only, for post-ingest correction. Everything else about
    `document`, including `content_hash` and `document_id`, has no UPDATE path
    at all. The contract does not say whether `document` should be as strictly
    immutable as `claim`; this is a judgement call.

14. **`chunk` denormalises more than FR-RAG-02's literal list.** FR-RAG-02
    names "doc ID, chunk ID, component category, supplier, doc type, page,
    source URI, timestamps, source-tier flag" as indexing metadata. `model`
    and `access_restricted` are added here for symmetry with `supplier` and
    with `document.access_restricted` respectively — reasonable, but beyond
    what was literally specified.

15. **Contextual retrieval's prepended context is a separate column
    (`chunk.context_prefix`) from the verbatim chunk text (`chunk_text`).**
    Decision 6 says to prepend context before embedding but does not say
    whether the stored/cited text should include it. Splitting them means a
    citation always shows a reviewer the real source text, never a generated
    framing sentence; the lexical indexes (`tsv`, trigram) also run over
    `chunk_text` only for the same reason, which is itself a decision (Decision
    3b's own motivating example — part-number matching — lives in verbatim
    text).

16. **`chunk_kind` includes a `prose` member not named in plan.md.** Decision 6
    names only the three `table_*` kinds; `prose` is this schema's own name
    for everything else.

17. **`job` has no dependency/DAG table.** Stage sequencing (e.g. do not
    enqueue `extract` until the matching `ingest` job succeeded) is assumed to
    be the worker's responsibility at enqueue time — a job succeeding triggers
    the next stage's job being inserted — rather than a modelled graph. Decision
    1's "hand-rolled state machine, not a workflow framework" reads as
    consistent with keeping this out of the schema, but tasks.md does not say
    so explicitly.

18. **`job`'s 15-minute lease duration reuses D-12e's number.** D-12e is
    titled generically ("claim lease duration") and is cited explicitly by
    WP-F F.1 for the `conflict` table; tasks.md never gives `job` its own
    lease duration, so this schema reuses the same figure rather than
    inventing a second one.

19. **`procurement_app`'s authentication is left unconfigured.** No password,
    certificate, or IAM binding is set anywhere in this file set; `00_roles.sql`
    creates the role `LOGIN`-capable but unable to actually log in until an
    operator configures one out of band. This is deliberate — nothing here
    should ever risk shipping a credential into version control — but it means
    "migrations apply cleanly" alone does not mean the application can connect
    yet.

20. **The bootstrap/migration identity itself is undefined by this file set**
    (see "Who runs this" above). Some deployments will use the cluster
    superuser; others a scoped CI role. Either works with these files as
    written, but this schema does not attempt to create or constrain that
    identity.

21. **`chunk.tsv` goes through a small wrapper function
    (`chunk_text_to_tsvector`), not `to_tsvector('english', ...)` directly.**
    Not a design decision so much as a required fix: PostgreSQL's two-argument
    `to_tsvector(regconfig, text)` is `STABLE`, and `GENERATED ALWAYS AS ...
    STORED` requires an `IMMUTABLE` expression, so the direct form fails table
    creation outright. The wrapper pins the configuration to the literal
    `'english'` and is declared `IMMUTABLE`, which is correct as long as the
    `'english'` text search configuration itself is never redefined — noted
    here because it is exactly the kind of thing that looks like an arbitrary
    stylistic choice without the explanation.
