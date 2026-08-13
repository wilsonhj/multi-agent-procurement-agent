# Committed fixture sets (T0.6)

These are the contract made executable. `tasks.md` states the technique they serve:

> Each team builds against **committed fixture files** matching the frozen schemas.
> WP-B ships golden claim JSON; WP-E consumes it and ships golden conflict JSON;
> WP-F and WP-G consume that. **Nobody waits on anybody's service.**

Every file here is validated by [`../test_fixtures.py`](../test_fixtures.py) three
ways — it validates against its model, its **canonical bytes** are compared against
what is on disk, and it still produces the behaviour it was written to encode. The
third check is the one that matters most: schema-valid JSON encoding the wrong
worked example is a failure the first two cannot see.

**The canonical serialisation is part of the contract:**

```python
json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
```

`ensure_ascii=False` is not a preference. The Sungrow fixture contains `°`, and
`json.dumps`' default (`ensure_ascii=True`) rewrites it to `°` — different
bytes, identical structure. An earlier version of the test compared parsed
structures and passed over exactly that mutation, so the check now compares bytes.

## What is here

| Path | Contract | What it encodes |
|---|---|---|
| `claims/sungrow-sg350hx-rated-ac-power.json` | C2, C3 | D-1's worked example — one datasheet, one field, three ambients. **Zero conflicts.** Three legitimate conditioned values, not a contradiction. |
| `claims/trina-tsm-neg21c-nameplate.json` | C2, C3 | A record value and a web value that genuinely disagree under the same unstated condition. **One conflict.** |
| `conflicts/trina-tsm-neg21c-nameplate.json` | C5, C3 | The `ConflictQueueEntry` the pair above projects to, at the severity `assign_severity` computes today (`MEDIUM`). |
| `workbooks/two-supplier-pv-store.json` | C6 | T0.5's golden projection — a synthetic two-supplier PV store (a Sungrow inverter carrying D-1's trio, a Trina module carrying the disagreement), under a pinned policy. **All four `CellFlag` states occur.** |
| `workbooks/two-supplier-pv-store.canonical-bytes.sha256` | C6 | `sha256(projection)` — the artifact of record. See *Two serialisations* below. |

The two claim fixtures are deliberately a matched pair. A fixture set containing
only the no-conflict case would let a change that suppresses *every* conflict pass
green, and FR-5 is about surfacing disagreement, not hiding it.

## Two serialisations, one artifact (C6 only)

The C6 fixture is the one file here whose committed bytes are **not** the bytes its
hash covers, so the two are named apart rather than left to be discovered:

| | Serialisation | Why |
|---|---|---|
| `two-supplier-pv-store.json` | the indented form above, like every other fixture | A 21 kB single-line artifact is one unreviewable diff line. The byte check above still applies to it unchanged. |
| `…canonical-bytes.sha256` | `sha256` of **D-14's** bytes — `separators=(",", ":")`, no indent | That compact form is the artifact of record. `sha256(normalized xlsx)`, when WP-G's writer lands, is a renderer-regression check only and never the integrity claim. |

So `sha256sum two-supplier-pv-store.json` does **not** reproduce the sidecar, by
design — the filename says `canonical-bytes` for that reason. Round-tripping the
committed JSON through `json.loads` and re-dumping compactly does, and
`test_the_fixture_hash_covers_the_committed_file_and_not_just_the_code` asserts
exactly that, so a hand-edit to the JSON cannot leave a self-consistently wrong hash.

**Its behavioural assertion lives in `../test_workbook_projection.py`**, not in
`test_fixtures.py`. The check that earns C6's place is regenerating the artifact
from the synthetic store it was built from, and that store is code, not JSON. The
loader here still does real work: it revalidates the top-level shape and recomputes
`generated_on` from the payload alone.

**Pin the policy in a C6 fixture, always.** The projection is a function of
*(store, policy)* and D-14 puts the policy and the computed `CellFlag`s inside the
hash, so a fixture reading a production threshold would re-baseline itself the first
time τ moved. `tasks.md` sequences τ tuning after WP-B, which is precisely when that
churn would be worst.

## What is deliberately absent

**No document fixtures** (PDF, DOCX, XLSX). Two reasons, and the second is binding:

1. Nothing consumes them yet — every ingestion entry point raises
   `NotImplementedError`, so a document fixture could not be exercised.
2. `.gitignore` blanket-excludes `*.docx` and `*.doc` **with no negation**, so a
   Word fixture cannot be committed at all. `*.xlsx` *is* negated for
   `tests/fixtures/**/*.xlsx`, so a spreadsheet fixture is permitted here when one
   is needed — it is the only document format that is.

## Rules for adding one

- **Synthetic or public data only.** Product identifiers and datasheet figures from
  published specifications are fine; contract terms and pricing are not, per NFR-03
  and the confidentiality note at the top of `.gitignore`. The web-sourced fixture
  deliberately uses an `example.invalid` URL rather than a live listing.
- **Add a loader to `FIXTURE_LOADERS`** in `test_fixtures.py` — not just a label.
  A fixture in an unmapped directory fails
  `test_every_fixture_lives_in_a_known_directory`, and because the map dispatches to
  a validator rather than merely naming known kinds, a new kind cannot fall through
  to the wrong model and report coverage it does not have.
- **Add a behavioural assertion**, not just a shape check. What is this fixture
  *for*? If the answer is only "it parses", it is not earning its place.
- **No `resolution` on any conflict fixture.** FR-HITL-06 makes a resolution a human
  decision; a committed one is a decision with nobody behind it, and anything
  seeding a store from these would import it as though a reviewer had made it.
  Enforced by `test_no_fixture_carries_a_resolution`.
- **Deterministic values only** — fixed timestamps, no `now()`. These files are
  compared byte-for-byte.
- **`.json` is what gets swept.** `_fixture_files()` globs `*.json`, so the two
  automatic checks — the known-directory test and the byte compare — do not see a
  sidecar of any other extension. The `.sha256` above is covered because a named
  test asserts it, which is the only thing keeping it honest. Give any future
  non-JSON companion the same treatment rather than assuming this directory is
  swept wholesale.

## Regenerating

There is no generator script on purpose — the byte check makes one unnecessary. Load
the file, revalidate it through its model, and re-dump with **exactly** the canonical
options:

```python
json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
```

Omitting `ensure_ascii=False` produces a file that parses identically and fails the
byte check — which is the intended behaviour, not a nuisance. If a schema change
makes a fixture fail, regenerate it **and re-check the behavioural assertions**: the
point of a fixture is what it means, not that it parses.
