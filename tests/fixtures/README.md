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

The two claim fixtures are deliberately a matched pair. A fixture set containing
only the no-conflict case would let a change that suppresses *every* conflict pass
green, and FR-5 is about surfacing disagreement, not hiding it.

## What is deliberately absent

**No C6 workbook projection fixture.** The canonical projection format is unfrozen
— that is T0.5, and `tasks.md` calls C6 the contract that blocks WP-G entirely.
Publishing a golden projection now would freeze by accident the one decision that
is supposed to be made deliberately.

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
