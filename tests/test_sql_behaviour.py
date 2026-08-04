"""What the DDL actually *does*, measured against a running PostgreSQL.

`test_sql_schema.py` next door asserts the DDL's text. That catches a fix being
reverted, and it cannot catch a fix that was never right: every security defect
this schema shipped was one where the SQL read correctly and the server behaved
otherwise. `USING (true)` on a write policy looks like "the write path is
unrestricted", not like "the application role can declassify every confidential
row in one statement" - but that is what it did, and only a live server said so.

So each test here descends from a defect that was *measured* against a cluster:
the attack is run, and the assertion is that it now fails. The docstring on each
one names what it used to do.

**Skipped unless `PROCUREMENT_TEST_DSN` points at a disposable database.** CI
supplies one from a `pgvector/pgvector` service container. Locally, over TCP
with password authentication, which is what CI does:

    echo postgres > /tmp/pg/pw
    initdb -D /tmp/pg/data -U postgres --auth-host=scram-sha-256 --pwfile=/tmp/pg/pw
    pg_ctl -D /tmp/pg/data -o '-p 5433 -h 127.0.0.1' start
    PGPASSWORD=postgres psql -h 127.0.0.1 -p 5433 -U postgres -c 'create database procurement'
    PROCUREMENT_TEST_DSN='postgresql://postgres:postgres@127.0.0.1:5433/procurement' \
        uv run pytest tests/test_sql_behaviour.py

**Use TCP and a password, not a Unix socket with `trust`.** The first version of
this docstring recommended the socket, and the socket never exercises
authentication: the suite passed locally and failed 8 of 23 in CI, because the
DDL creates its roles without passwords and the container's `pg_hba.conf`
requires `scram-sha-256`. A local setup that cannot reproduce a CI failure is
worse than no local setup, because it is trusted. See `TEST_ROLE_PASSWORD`.

The database is **dropped and recreated per session**. Never point this at
anything you care about; the fixture says so again at the point of use.

One trap is load-bearing enough to state here rather than in a comment. A
`FOR EACH ROW` trigger never fires on an empty table, so an append-only check
against zero rows passes vacuously - it was the first thing that fooled the
original hand-run checklist. `seeded` below therefore inserts real rows, and
every mutation test depends on it.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    # mypy needs the real module to resolve `psycopg.Connection` and the
    # `psycopg.errors.*` classes. `importorskip` returns an untyped module
    # object, so the annotations below would be unresolvable names without this.
    import psycopg
    import psycopg.sql
else:
    psycopg = pytest.importorskip("psycopg", reason="the `store` extra is not installed")
    # Importing the parent does not bind the submodule, and the fixture below
    # uses psycopg.sql for safe identifier quoting on ALTER ROLE.
    import psycopg.sql  # noqa: F401,F811

DSN = os.environ.get("PROCUREMENT_TEST_DSN")

pytestmark = pytest.mark.skipif(
    not DSN, reason="PROCUREMENT_TEST_DSN is unset; live-database checks skipped"
)

SQL_DIR = pathlib.Path(__file__).parent.parent / "sql"

#: 32-byte digests, written out rather than generated, so a chain in a failure
#: message is readable and the same run twice produces the same bytes.
GENESIS_HASH = bytes.fromhex("aa" * 32)
CHILD_HASH = bytes.fromhex("bb" * 32)
FABRICATED = bytes.fromhex("ff" * 32)


#: Password given to the two LOGIN roles for the duration of the test run.
#:
#: `00_roles.sql` deliberately creates them **without** one — credentials are a
#: deployment concern and belong nowhere near version control. That is correct,
#: and it means a harness connecting over TCP has to supply them: the pgvector
#: image's `pg_hba.conf` ends in `host all all all scram-sha-256`, so a
#: passwordless role gets `FATAL: password authentication failed ... has no
#: password assigned`.
#:
#: This was not hypothetical. A first version of this file passed locally
#: against a Unix socket with `trust` auth and failed 8 of 23 in CI for exactly
#: that reason — the local run never exercised authentication at all.
#:
#: A literal rather than a generated secret, because this only ever reaches a
#: database the fixture drops and rebuilds, and a reader should be able to
#: connect by hand while debugging a failure.
TEST_ROLE_PASSWORD = "procurement-test-only"

#: The roles the DDL creates with LOGIN. The two owner roles are NOLOGIN by
#: design (Decision 9) and must stay that way — `test_owner_roles_cannot_log_in`
#: asserts it — so they are deliberately absent.
LOGIN_ROLES = ("procurement_app", "procurement_ingest")


def _connect(*, user: str = "postgres", autocommit: bool = True) -> psycopg.Connection:
    assert DSN is not None
    if user == "postgres":
        return psycopg.connect(DSN, autocommit=autocommit)
    return psycopg.connect(DSN, user=user, password=TEST_ROLE_PASSWORD, autocommit=autocommit)


@pytest.fixture(scope="session")
def schema() -> None:
    """Apply the nine files in order into a **freshly dropped** database.

    In order, and from the same files a deployment would use — not from a dump.
    A schema test that runs against a hand-built approximation of the schema
    tests the approximation.
    """
    with _connect() as conn:
        conn.execute("DROP SCHEMA IF EXISTS audit CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        # Restore the ACL a stock database ships with. From PostgreSQL 15 a
        # freshly CREATE'd `public` grants nothing to PUBLIC, so without this
        # every role below loses USAGE and the whole suite fails with
        # "permission denied for schema public" — a fixture artefact that looks
        # exactly like a privilege defect in the DDL.
        #
        # Worth noting rather than only working around: no file in `sql/` grants
        # USAGE on `public` (only on `audit`, in 07). The DDL therefore relies on
        # the ambient schema ACL. That is ordinary practice, but it means a
        # cluster hardened with `REVOKE ALL ON SCHEMA public FROM PUBLIC` would
        # break the application with nothing in these files to explain why.
        conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO PUBLIC")
        for path in sorted(SQL_DIR.glob("0*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))

        # Credentials, supplied by the harness rather than by the DDL — see
        # TEST_ROLE_PASSWORD. Done after the files are applied so the roles
        # exist, and only for the two LOGIN roles: setting a password on a
        # NOLOGIN owner would not grant it a login, but writing that line would
        # suggest otherwise to the next reader.
        for role in LOGIN_ROLES:
            conn.execute(
                psycopg.sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                    psycopg.sql.Identifier(role),
                    psycopg.sql.Literal(TEST_ROLE_PASSWORD),
                )
            )


@pytest.fixture
def seeded(schema: None) -> Iterator[None]:
    """One open document and one restricted one, each with a chunk and a claim.

    **Rows, not an empty table.** A `FOR EACH ROW` trigger cannot fire without
    them, so every append-only assertion below would pass against nothing.
    """
    with _connect() as conn:
        conn.execute("SET app.allow_restricted = 'true'")
        conn.execute(
            """
            INSERT INTO public.document
                (document_id, content_hash, source_uri, document_type,
                 ingested_at, access_restricted)
            VALUES ('open-1',  'hash-open',   'file:///open.pdf',   'spec_sheet', now(), false),
                   ('secret-1','hash-secret', 'file:///secret.pdf', 'pricing',    now(), true)
            ON CONFLICT (content_hash) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO public.chunk
                (chunk_id, document_id, chunk_kind, source_tier, chunk_text, embedding)
            VALUES ('chunk-open',   'open-1',  'prose', 'system_of_record',
                    'JKM610N-66HL4M-V', array_fill(0.1, array[1024])::vector),
                   ('chunk-secret', 'secret-1','prose', 'system_of_record',
                    'CONFIDENTIAL 0.19 per watt', array_fill(0.2, array[1024])::vector)
            ON CONFLICT (chunk_id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO public.claim
                (document_id, component_category, supplier, model, field,
                 extractor_version, value, condition, source_tier, source_ref,
                 confidence, extracted_at)
            VALUES ('open-1',  'pv_modules','Trina','TSM-700','nameplate_power','v1',
                    '700'::jsonb,'{}'::jsonb,'system_of_record',
                    '{"document_id":"open-1"}'::jsonb, 0.9, now()),
                   ('secret-1','pv_modules','Trina','TSM-700','price_per_watt_dc','v1',
                    '0.19'::jsonb,'{}'::jsonb,'system_of_record',
                    '{"document_id":"secret-1"}'::jsonb, 0.9, now())
            """
        )
    yield
    with _connect() as conn:
        conn.execute("SET app.allow_restricted = 'true'")
        conn.execute("ALTER TABLE public.claim DISABLE TRIGGER claim_no_mutation")
        conn.execute("ALTER TABLE public.chunk DISABLE TRIGGER chunk_inherit_access_restricted")
        conn.execute("DELETE FROM public.claim")
        conn.execute("DELETE FROM public.chunk")
        conn.execute("DELETE FROM public.document")
        conn.execute("ALTER TABLE public.claim ENABLE TRIGGER claim_no_mutation")
        conn.execute("ALTER TABLE public.chunk ENABLE TRIGGER chunk_inherit_access_restricted")


# --- confidentiality: the two defects that made RLS decorative -------------------


def test_the_app_role_cannot_declassify_rows_it_cannot_read(seeded: None) -> None:
    """Was: `UPDATE public.chunk SET access_restricted = false` returned
    `UPDATE 2` as `procurement_app` and declassified a row that role could not
    SELECT one statement earlier. The write policies were `USING (true)`, which
    is permissive and OR's with the confidentiality policy, and a WHERE-less
    UPDATE needs no SELECT."""
    with _connect(user="procurement_app") as app:
        app.execute("UPDATE public.chunk SET access_restricted = false")
        visible = app.execute("SELECT chunk_id FROM public.chunk").fetchall()
    assert [row[0] for row in visible] == ["chunk-open"]

    with _connect() as owner:
        owner.execute("SET app.allow_restricted = 'true'")
        still = owner.execute(
            "SELECT count(*) FROM public.chunk WHERE access_restricted"
        ).fetchone()
    assert still is not None and still[0] == 1


def test_the_write_policy_alone_protects_an_unreadable_row(seeded: None) -> None:
    """Isolates the RLS policy from the inheritance trigger.

    The test above asserts an *outcome* that two independent mechanisms both
    provide: the write policy refuses the row, and the inheritance trigger would
    re-derive `access_restricted` even if it did not. Reverting the policy to
    `USING (true)` therefore left it green — the trigger silently covered for it.
    A defence-in-depth arrangement is good; a test that cannot tell which layer
    is holding is not, because the day someone removes the other layer nothing
    goes red.

    So this writes `section`, which no trigger touches and which the app role is
    granted. Only the policy can refuse it.
    """
    with _connect(user="procurement_app") as app:
        app.execute("UPDATE public.chunk SET section = 'tampered'")
    with _connect() as owner:
        owner.execute("SET app.allow_restricted = 'true'")
        rows = owner.execute(
            "SELECT chunk_id, section FROM public.chunk ORDER BY chunk_id"
        ).fetchall()
    by_id: dict[str, str | None] = dict(rows)
    assert by_id["chunk-secret"] is None, "an unreadable row was modified"
    assert by_id["chunk-open"] == "tampered", "a readable row must still be writable"


def test_the_document_write_policy_alone_protects_an_unreadable_row(seeded: None) -> None:
    """Same isolation for `document`, whose UPDATE grant is column-level.
    `data_vintage` is in that grant and no trigger derives it."""
    with _connect(user="procurement_app") as app:
        app.execute("UPDATE public.document SET data_vintage = now()")
    with _connect() as owner:
        owner.execute("SET app.allow_restricted = 'true'")
        rows = owner.execute(
            "SELECT document_id, data_vintage FROM public.document ORDER BY document_id"
        ).fetchall()
    by_id: dict[str, object] = dict(rows)
    assert by_id["secret-1"] is None, "an unreadable document was modified"
    assert by_id["open-1"] is not None, "a readable document must still be writable"


def test_the_app_role_cannot_delete_rows_it_cannot_read(seeded: None) -> None:
    """Same policy defect, the other verb: `DELETE FROM public.chunk` destroyed
    a row the role could not see."""
    with _connect(user="procurement_app") as app:
        app.execute("DELETE FROM public.chunk")
    with _connect() as owner:
        owner.execute("SET app.allow_restricted = 'true'")
        remaining = owner.execute("SELECT chunk_id FROM public.chunk").fetchall()
    assert [row[0] for row in remaining] == ["chunk-secret"]


def test_a_chunk_inherits_its_parent_documents_restriction(seeded: None) -> None:
    """Was: `chunk.access_restricted` defaulted to false with nothing tying it to
    the parent, so an indexer that forgot the flag left confidential text
    world-readable while the document itself was correctly hidden. Chunks are the
    retrieval unit, so this is where NFR-03 is actually decided."""
    with _connect() as owner:
        owner.execute("SET app.allow_restricted = 'true'")
        owner.execute(
            """
            INSERT INTO public.chunk
                (chunk_id, document_id, chunk_kind, source_tier, chunk_text, embedding)
            VALUES ('chunk-forgot', 'secret-1', 'prose', 'system_of_record',
                    'CONFIDENTIAL: price 0.19/W', array_fill(0.3, array[1024])::vector)
            """
        )
        inherited = owner.execute(
            "SELECT access_restricted FROM public.chunk WHERE chunk_id = 'chunk-forgot'"
        ).fetchone()
    assert inherited is not None and inherited[0] is True

    with _connect(user="procurement_app") as app:
        seen = app.execute(
            "SELECT count(*) FROM public.chunk WHERE chunk_id = 'chunk-forgot'"
        ).fetchone()
    assert seen is not None and seen[0] == 0


def test_restriction_can_only_increase(seeded: None) -> None:
    """The inheritance rule is OR, not assignment, so a chunk may be *more*
    restricted than its parent but never less — even for an entitled session."""
    with _connect() as owner:
        owner.execute("SET app.allow_restricted = 'true'")
        owner.execute(
            "UPDATE public.chunk SET access_restricted = false WHERE chunk_id = 'chunk-secret'"
        )
        after = owner.execute(
            "SELECT access_restricted FROM public.chunk WHERE chunk_id = 'chunk-secret'"
        ).fetchone()
    assert after is not None and after[0] is True


def test_claims_do_not_leak_a_restricted_documents_values(seeded: None) -> None:
    """Was: no RLS on `claim`, so `SELECT document_id, field, value FROM claim`
    as `procurement_app` returned `0.19` for a document that role could not
    see."""
    with _connect(user="procurement_app") as app:
        rows = app.execute("SELECT document_id FROM public.claim").fetchall()
    assert [row[0] for row in rows] == ["open-1"]


# --- append-only: the verb that fires no row triggers ----------------------------


@pytest.mark.parametrize("table", ["public.claim", "public.resolution", "audit.event"])
def test_truncate_is_refused(seeded: None, table: str) -> None:
    """Was: refused on `audit.event` only. TRUNCATE fires no row-level triggers,
    so the `FOR EACH ROW` append-only trigger could not see it, and
    `TRUNCATE public.claim CASCADE` succeeded — taking `resolution` and
    `conflict_candidate` with it, i.e. the immutable record of what a human
    decided. `ON DELETE RESTRICT` does not help: CASCADE truncates children
    rather than deleting through the constraint."""
    with _connect() as owner:
        owner.execute("SET app.allow_restricted = 'true'")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            owner.execute(f"TRUNCATE {table} CASCADE")


@pytest.mark.parametrize(
    "verb", ["UPDATE public.claim SET confidence = 0.1", "DELETE FROM public.claim"]
)
def test_the_row_level_tripwire_still_raises(seeded: None, verb: str) -> None:
    """The regression guard for the RLS work: enabling RLS on an append-only
    table filters rows *before* a `FOR EACH ROW` trigger runs, which turned this
    from a raised exception into a silent `UPDATE 0`. The data was safe either
    way; Decision 9 picks the trigger precisely because it is loud."""
    with _connect() as owner:
        owner.execute("SET app.allow_restricted = 'true'")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            owner.execute(verb)


# --- claim_natural_key must agree with FieldClaim.claim_key() -------------------

#: One claim INSERT. Every column of `claim_natural_key` is a parameter or a
#: literal here, so the tests below differ in exactly the column they are about.
_CLAIM = """
INSERT INTO public.claim
    (document_id, component_category, supplier, model, nameplate, field,
     extractor_version, value, condition, source_tier, source_ref, confidence)
VALUES ('open-1', %s, %s, %s, %s, 'nameplate_power', 'v1', %s::jsonb, %s::jsonb,
        'system_of_record', '{"document_id":"open-1"}'::jsonb, 0.9)
"""


def _claim(
    conn: psycopg.Connection,
    *,
    category: str,
    supplier: str,
    model: str,
    nameplate: float | None,
    value: str,
    condition: str,
) -> None:
    """One claim about `nameplate_power`, on the seeded open document.

    Everything the natural key covers except `condition` is pinned by the
    caller, so a test that varies only the condition is varying only the
    condition — which is the whole point of the four tests below.
    """
    conn.execute(_CLAIM, (category, supplier, model, nameplate, value, condition))


def test_two_conditions_of_one_field_both_insert(seeded: None) -> None:
    """D-1's own worked case, and the defect A-41 closed.

    `claim_natural_key` had no `condition` column, while the frozen contract's
    `FieldClaim.claim_key()` keys on
    `(document_id, field_name, extractor_version, condition.grouping_key())` and
    says why: "one datasheet stating a parameter at three ambients is three
    claims, not one extractor contradicting itself."

    Trina prints STC and NOCT nameplate power side by side. One document, one
    field, one extractor version, one bin — two conditions. Before the fix the
    second INSERT raised
    `duplicate key value violates unique constraint "claim_natural_key"`, i.e.
    the schema refused exactly the multi-condition claims the C2/D-1 layer above
    it exists to store.
    """
    with _connect() as conn:
        _claim(
            conn,
            category="pv_modules",
            supplier="Trina",
            model="TSM-NEG21C.20",
            nameplate=700.0,
            value="700",
            condition='{"basis":"stc"}',
        )
        _claim(
            conn,
            category="pv_modules",
            supplier="Trina",
            model="TSM-NEG21C.20",
            nameplate=700.0,
            value="523",
            condition='{"basis":"noct"}',
        )
        stored = conn.execute(
            """
            SELECT condition->>'basis', value FROM public.claim
            WHERE model = 'TSM-NEG21C.20' ORDER BY 1
            """
        ).fetchall()
    assert stored == [("noct", 523), ("stc", 700)]


def test_the_sungrow_trio_inserts_under_one_key(seeded: None) -> None:
    """The same property on a category with no bin discriminator.

    The SG350HX's `352 kVA @30 degC / 320 @40 / 295 @50` is the trio
    `services/claims/__init__.py` names in its module docstring. It inserted
    before the fix too — but only because `nameplate` is NULL for inverters and
    an ordinary UNIQUE treats NULLs as distinct. It passed for a reason that had
    nothing to do with the condition, which is why the PV half above failed while
    this half looked healthy.
    """
    with _connect() as conn:
        for temperature, kva in ((30, "352"), (40, "320"), (50, "295")):
            _claim(
                conn,
                category="inverters_pcs",
                supplier="Sungrow",
                model="SG350HX",
                nameplate=None,
                value=kva,
                condition=f'{{"temperature_c":{temperature}}}',
            )
        stored = conn.execute(
            """
            SELECT (condition->>'temperature_c')::int, value FROM public.claim
            WHERE model = 'SG350HX' ORDER BY 1
            """
        ).fetchall()
    assert stored == [(30, 352), (40, 320), (50, 295)]


def test_a_same_condition_duplicate_is_still_refused(seeded: None) -> None:
    """The other direction: widening the key must not stop it being a key.

    Same document, component identity, field, extractor version **and**
    condition, differing only in the value — one extractor version emitting two
    answers for one field under one condition, which is what C8 refuses.
    """
    with _connect() as conn:
        _claim(
            conn,
            category="pv_modules",
            supplier="Trina",
            model="TSM-NEG21C.20",
            nameplate=700.0,
            value="700",
            condition='{"basis":"stc"}',
        )
        with pytest.raises(psycopg.errors.UniqueViolation, match="claim_natural_key"):
            _claim(
                conn,
                category="pv_modules",
                supplier="Trina",
                model="TSM-NEG21C.20",
                nameplate=700.0,
                value="999",
                condition='{"basis":"stc"}',
            )


def test_a_same_condition_duplicate_is_refused_with_a_null_nameplate(seeded: None) -> None:
    """The `NULLS NOT DISTINCT` half, which was inert before A-41.

    `nameplate` is the only nullable column in the key, and an ordinary UNIQUE
    treats two NULLs as distinct — so on every category without a bin
    discriminator the constraint accepted a genuine duplicate. Measured before
    the change: this second INSERT succeeded, giving one document two different
    `352 kVA @30 degC` answers from one extractor version.
    """
    with _connect() as conn:
        _claim(
            conn,
            category="inverters_pcs",
            supplier="Sungrow",
            model="SG350HX",
            nameplate=None,
            value="352",
            condition='{"temperature_c":30}',
        )
        with pytest.raises(psycopg.errors.UniqueViolation, match="claim_natural_key"):
            _claim(
                conn,
                category="inverters_pcs",
                supplier="Sungrow",
                model="SG350HX",
                nameplate=None,
                value="999",
                condition='{"temperature_c":30}',
            )


# --- the hash chain has to be walkable, not merely fork-free --------------------


def _event(
    conn: psycopg.Connection,
    seq: int,
    prev: bytes | None,
    digest: bytes,
    *,
    document_id: str = "open-1",
) -> None:
    """Append one event to `document_id`'s chain.

    `document_id` **is** the chain identity; there is no `stream` column. This
    helper used to pass one as well — the literal `'doc:open-1'`, held equal to
    this column by a CHECK constraint — which is the redundancy A-42 removed.
    """
    conn.execute(
        """
        INSERT INTO audit.event
            (document_id, seq, prev_hash, hash, event_type, actor, payload_canonical)
        VALUES (%s, %s, %s, %s, 'extraction', 'test', '{}')
        """,
        (document_id, seq, prev, digest),
    )


@pytest.fixture
def chain(seeded: None) -> Iterator[None]:
    with _connect() as conn:
        _event(conn, 0, None, GENESIS_HASH)
        _event(conn, 1, GENESIS_HASH, CHILD_HASH)
    yield
    with _connect() as conn:
        conn.execute("ALTER TABLE audit.event DISABLE TRIGGER audit_event_no_mutation")
        conn.execute("DELETE FROM audit.event")
        conn.execute("ALTER TABLE audit.event ENABLE TRIGGER audit_event_no_mutation")


def test_a_valid_chain_appends(chain: None) -> None:
    with _connect() as conn:
        count = conn.execute("SELECT count(*) FROM audit.event").fetchone()
    assert count is not None and count[0] == 2


def test_a_fabricated_parent_is_refused(chain: None) -> None:
    """Was: accepted. `prev_hash` named a digest that never existed, producing a
    chain that can never be walked — while `UNIQUE (document_id, prev_hash)` saw
    nothing wrong, because it only catches *two children of one parent*."""
    with _connect() as conn, pytest.raises(psycopg.errors.ForeignKeyViolation):
        _event(conn, 7, FABRICATED, bytes.fromhex("cc" * 32))


def test_a_second_disconnected_root_is_refused(chain: None) -> None:
    """Was: accepted. A fork made by *starting a new segment* rather than by
    branching an existing one — exactly what the fork constraint's own comment
    claimed to prevent."""
    with _connect() as conn, pytest.raises(psycopg.errors.ForeignKeyViolation):
        _event(conn, 900, bytes.fromhex("ee" * 32), bytes.fromhex("dd" * 32))


def test_a_chain_loop_is_refused(chain: None) -> None:
    """Was: accepted. Two events in one document's chain sharing a `hash`;
    nothing was unique on `hash` at all."""
    with _connect() as conn, pytest.raises(psycopg.errors.UniqueViolation):
        _event(conn, 2, CHILD_HASH, GENESIS_HASH)


def test_a_fork_is_still_refused(chain: None) -> None:
    """Regression: the property that already worked must survive the two new
    constraints."""
    with _connect() as conn, pytest.raises(psycopg.errors.UniqueViolation):
        _event(conn, 5, GENESIS_HASH, bytes.fromhex("99" * 32))


def test_a_duplicate_genesis_is_still_refused(chain: None) -> None:
    """Regression on `NULLS NOT DISTINCT`: an ordinary UNIQUE treats two NULLs as
    distinct and would let one document's chain grow two unrelated roots.

    **The constraint name is asserted, not just the error class**, and that is
    the point of this version of the test. Two constraints can refuse this row:
    `audit_event_no_fork`, which is what the property is about, and
    `audit_event_seq_unique`, because `audit_event_genesis_seq_zero` forces every
    genesis to `seq = 0` and there is already one. Measured by mutation:
    deleting `NULLS NOT DISTINCT` from `audit_event_no_fork` left this test green
    on the error class alone — the seq constraint covered for it, exactly the way
    the inheritance trigger once covered for the reverted chunk write policy.
    That is the failure `test_the_write_policy_alone_protects_an_unreadable_row`
    exists to name one section up. A second genesis with a *different* seq is not
    an available discriminator here: the genesis CHECK makes it unrepresentable.
    """
    with _connect() as conn, pytest.raises(psycopg.errors.UniqueViolation) as raised:
        _event(conn, 0, None, bytes.fromhex("88" * 32))
    assert raised.value.diag.constraint_name == "audit_event_no_fork", (
        "a duplicate genesis was refused, but by "
        f"{raised.value.diag.constraint_name} rather than the fork constraint — "
        "so this test no longer measures NULLS NOT DISTINCT"
    )


def test_another_documents_chain_starts_its_own_genesis(chain: None) -> None:
    """The other half of `NULLS NOT DISTINCT (document_id, prev_hash)`, and the
    property A-42's re-key is most able to break: Decision 9 wants the chain
    scoped per document, "not globally, so cross-document concurrency stays
    unconstrained."

    `open-1` already has a genesis (`prev_hash` NULL, seq 0). A second document
    must be able to start one of its own. Keyed on `prev_hash` alone — a
    plausible over-simplification once `stream` is gone — this INSERT would be
    refused and every document after the first would be unauditable.
    """
    with _connect() as conn:
        _event(conn, 0, None, bytes.fromhex("77" * 32), document_id="secret-1")
        roots = conn.execute(
            "SELECT document_id FROM audit.event WHERE prev_hash IS NULL ORDER BY document_id"
        ).fetchall()
    assert [row[0] for row in roots] == ["open-1", "secret-1"]


# --- ingest: making a row MORE restricted must not be the failing direction ------


def test_a_restricted_document_can_be_ingested_idempotently(schema: None) -> None:
    """Was: `INSERT ... RETURNING` and `INSERT ... ON CONFLICT DO NOTHING` both
    failed for `access_restricted = true`, because a `FOR SELECT` policy applies
    to the new row whenever the statement reads it back. The direction was
    backwards for a confidentiality control — making a row *more* restricted
    failed while making it less succeeded."""
    with _connect(user="procurement_ingest") as ingest:
        returned = ingest.execute(
            """
            INSERT INTO public.document
                (document_id, content_hash, source_uri, document_type,
                 ingested_at, access_restricted)
            VALUES ('ingest-1', 'hash-ingest', 'file:///x.pdf', 'pricing', now(), true)
            RETURNING document_id
            """
        ).fetchone()
        assert returned is not None and returned[0] == "ingest-1"

        # NFR-05 / AC-5: re-ingesting an unchanged document is a no-op.
        ingest.execute(
            """
            INSERT INTO public.document
                (document_id, content_hash, source_uri, document_type,
                 ingested_at, access_restricted)
            VALUES ('ingest-1', 'hash-ingest', 'file:///x.pdf', 'pricing', now(), true)
            ON CONFLICT (content_hash) DO NOTHING
            """
        )

    with _connect(user="procurement_app") as app:
        seen = app.execute(
            "SELECT count(*) FROM public.document WHERE document_id = 'ingest-1'"
        ).fetchone()
    assert seen is not None and seen[0] == 0, "the ingest role's write must stay restricted"

    with _connect() as owner:
        owner.execute("ALTER TABLE public.document DISABLE TRIGGER USER")
        owner.execute("SET app.allow_restricted = 'true'")
        owner.execute("DELETE FROM public.document WHERE document_id = 'ingest-1'")
        owner.execute("ALTER TABLE public.document ENABLE TRIGGER USER")


def test_the_app_role_cannot_escalate_to_the_ingest_role(schema: None) -> None:
    """The ingest role is only a boundary if the application cannot become it."""
    with _connect(user="procurement_app") as app:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute("SET ROLE procurement_ingest")


# --- privilege hygiene and the standing decisions -------------------------------


def test_no_ann_index_exists_anywhere(schema: None) -> None:
    """plan.md Decision 3a: exact pgvector search. Measured at 50,000 chunks,
    HNSW with a selective filter silently returned 5 rows for a LIMIT 10."""
    with _connect() as conn:
        found = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE indexdef ~* '(hnsw|ivfflat)'"
        ).fetchall()
    assert found == []


def test_owner_roles_cannot_log_in_and_the_app_is_unprivileged(schema: None) -> None:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT rolname, rolcanlogin, rolsuper, rolbypassrls
            FROM pg_roles WHERE rolname LIKE 'procurement%' OR rolname = 'audit_owner'
            ORDER BY rolname
            """
        ).fetchall()
    by_name: dict[str, tuple[str, bool, bool, bool]] = {r[0]: r for r in rows}
    for owner in ("procurement_owner", "audit_owner"):
        assert by_name[owner][1] is False, f"{owner} must be NOLOGIN"
    for unprivileged in ("procurement_app", "procurement_ingest"):
        assert by_name[unprivileged][2] is False, f"{unprivileged} must not be superuser"
        assert by_name[unprivileged][3] is False, f"{unprivileged} must not have BYPASSRLS"


def test_a_duplicate_content_hash_is_refused(seeded: None) -> None:
    """NFR-05 / AC-5: re-ingesting an unchanged document creates no duplicate."""
    with _connect() as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            """
            INSERT INTO public.document
                (document_id, content_hash, source_uri, document_type, ingested_at)
            VALUES ('open-2', 'hash-open', 'file:///again.pdf', 'spec_sheet', now())
            """
        )


def test_no_project_role_is_a_member_of_another(schema: None) -> None:
    """Decision 9's boundary is defeated by a membership as surely as by
    `SUPERUSER`, and much more quietly.

    `00_roles.sql` re-asserts role *attributes* on every run, which closed one
    hole. A membership is not an attribute:

        GRANT procurement_ingest TO procurement_app;

    survived a clean re-run of that file with every attribute check still
    passing, and let `procurement_app` execute `SET ROLE procurement_ingest`.
    Measured before the fix; `current_user` came back `procurement_ingest`.

    `test_the_app_role_cannot_escalate_to_the_ingest_role` next door does go red
    in that state, but it names the *consequence*. This names the cause, so a
    failure points at `pg_auth_members` rather than leaving a reader to work
    backwards from a denied `SET ROLE`.
    """
    with _connect() as conn:
        memberships = conn.execute(
            """
            SELECT g.rolname, m.rolname
            FROM pg_auth_members am
            JOIN pg_roles g ON am.roleid = g.oid
            JOIN pg_roles m ON am.member = m.oid
            WHERE g.rolname LIKE 'procurement%' OR g.rolname = 'audit_owner'
            ORDER BY 1, 2
            """
        ).fetchall()
    assert memberships == [], (
        f"project roles are members of one another: {memberships}. A membership "
        "hands over every privilege of the granting role for the cost of one "
        "SET ROLE, and survives re-running 00_roles.sql."
    )
