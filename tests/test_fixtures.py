"""The committed fixture sets, and the assertions that stop them rotting (T0.6).

`tasks.md` specifies the decoupling technique these exist for: "Each team builds
against **committed fixture files** matching the frozen schemas. WP-B ships golden
claim JSON; WP-E consumes it and ships golden conflict JSON; WP-F and WP-G consume
that. Nobody waits on anybody's service."

That only works if the fixtures are *known* to still match the schemas, so every
file here is checked three ways, and the rationale lives here rather than being
repeated on each test:

1. **It validates** against its model — catches a schema change the fixture was
   never updated for.
2. **Its canonical bytes are unchanged.** Not a structural compare: an earlier
   version of this module asserted `model_dump() == json.loads(file)`, which is
   blind to serialisation drift. Regenerating with `json.dumps`' default
   `ensure_ascii=True` rewrites the Sungrow fixture's `°` to `\\u00b0` — different
   bytes, identical structure, and the structural check passed. Comparing bytes
   subsumes the structural check and closes that hole.
3. **It still means what it was written to mean.** Schema-valid, byte-canonical
   JSON encoding the wrong worked example is the failure neither check above sees.

Only frozen contracts get fixtures. C2/C3 (claims), C5 (conflicts) and **C6 (the
workbook projection)** are covered. C6 was deliberately absent while its format
was unfrozen - publishing a golden projection then would have frozen by accident
the one decision `tasks.md` says must be made deliberately - and it ships now
that D-14 is adopted and T0.5 is closed.

The C6 fixture is the one kind whose *behavioural* assertions live elsewhere, in
`test_workbook_projection.py`: the check that earns its place is regenerating the
artifact from the synthetic store it was built from, and that store is code, not
JSON. What is checked here is the same three ways as everything else - the loader
below revalidates the shape and recomputes the vintage stamp from the payload
alone, which is a real check and not a pass-through.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from procurement_agent.schema import (
    ConflictClass,
    ConflictQueueEntry,
    Severity,
    SourceTier,
)
from procurement_agent.services.claims import FieldClaim
from procurement_agent.services.conflict_hitl import (
    assign_severity,
    comparison_pairs,
    tolerance_for,
    values_conflict,
)
from procurement_agent.services.output.projection import (
    PROJECTION_VERSION,
    fold_generated_on,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

#: The one serialisation these files are written in. `ensure_ascii=False` is part
#: of the contract, not a preference - see the module docstring.
CANONICAL_JSON: dict[str, Any] = {"indent": 2, "sort_keys": True, "ensure_ascii": False}


def _load_claims(raw: Any) -> Any:
    assert isinstance(raw, list), "a claims fixture is a list of FieldClaim"
    return [FieldClaim.model_validate(c).model_dump(mode="json") for c in raw]


def _load_conflict(raw: Any) -> Any:
    return ConflictQueueEntry.model_validate(raw).model_dump(mode="json")


def _load_workbook_projection(raw: Any) -> Any:
    """Revalidate a C6 projection (D-14) without rebuilding it from a store.

    There is no model to round-trip through: a projection is deliberately plain
    encoded JSON, so `value` can hold a `$decimal` tag on one row and a bare
    float on the next. What can be checked from the payload alone is the shape
    D-14 fixes, and - the useful one - that `generated_on` is still the fold over
    the write timestamps *inside* the file. That is the property decision 2 is
    about, and it is checkable by anyone holding only the bytes.
    """
    assert set(raw) == {
        "projection_version",
        "policy",
        "components",
        "conflicts",
        "sources",
        "generated_on",
    }, "not a D-14 projection"
    assert raw["projection_version"] == PROJECTION_VERSION
    assert raw["generated_on"] == fold_generated_on(raw), (
        "generated_on is not the fold over this file's own store write timestamps - "
        "the stamp was edited, or it was produced by a parallel query rather than "
        "from inside the projection (D-14 decision 2)"
    )
    return raw


#: Subdirectory -> the loader that validates it. A directory absent from this map
#: is a fixture nothing validates. It is a *dispatch* table rather than a set of
#: labels because the previous version fell through to `ConflictQueueEntry` for
#: any unrecognised kind: adding `workbooks/` here would have validated a golden
#: projection as a queue entry and reported coverage it did not have.
FIXTURE_LOADERS: dict[str, Callable[[Any], Any]] = {
    "claims": _load_claims,
    "conflicts": _load_conflict,
    "workbooks": _load_workbook_projection,
}


def _fixture_files() -> list[Path]:
    return sorted(FIXTURE_ROOT.rglob("*.json"))


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(FIXTURE_ROOT)) for p in paths]


def _claims(name: str) -> list[FieldClaim]:
    path = FIXTURE_ROOT / "claims" / name
    return [FieldClaim.model_validate(c) for c in json.loads(path.read_text())]


def _conflict(name: str) -> ConflictQueueEntry:
    path = FIXTURE_ROOT / "conflicts" / name
    return ConflictQueueEntry.model_validate(json.loads(path.read_text()))


TRINA = "trina-tsm-neg21c-nameplate.json"
SUNGROW = "sungrow-sg350hx-rated-ac-power.json"


def test_the_fixture_root_is_not_empty() -> None:
    """Without this, the parametrised test below collects zero cases and the suite
    passes green over a deleted directory - the vacuous-pass shape `sql/README.md`
    already records twice."""
    assert FIXTURE_ROOT.is_dir()
    assert _fixture_files(), "no fixtures found; the parametrised tests would be vacuous"


def test_every_fixture_lives_in_a_known_directory() -> None:
    """A new fixture directory must be given a loader to be validated at all."""
    unknown = {
        str(p.relative_to(FIXTURE_ROOT))
        for p in _fixture_files()
        if p.relative_to(FIXTURE_ROOT).parts[0] not in FIXTURE_LOADERS
    }
    assert not unknown, f"fixtures in unmapped directories: {sorted(unknown)}"


@pytest.mark.parametrize("path", _fixture_files(), ids=_ids(_fixture_files()))
def test_a_fixture_is_byte_identical_to_its_canonical_form(path: Path) -> None:
    """Validate, re-dump canonically, and compare the actual bytes on disk.

    See the module docstring for why this is a byte compare and not a structural
    one. The practical consequence: a fixture regenerated with different
    `json.dumps` options fails here rather than sitting on disk in a second,
    undeclared serialisation.
    """
    raw_text = path.read_text()
    kind = path.relative_to(FIXTURE_ROOT).parts[0]
    dumped = FIXTURE_LOADERS[kind](json.loads(raw_text))

    assert json.dumps(dumped, **CANONICAL_JSON) + "\n" == raw_text, (
        f"{path.name} is not byte-identical to its canonical form. Either the model "
        "and the committed JSON have diverged, or it was regenerated with different "
        f"json.dumps options - the contract is {CANONICAL_JSON}. Regenerate and "
        "re-check the behavioural assertions; do not just overwrite it."
    )


def test_the_sungrow_trio_still_raises_no_conflict() -> None:
    """D-1's worked example, loaded from disk rather than built in code.

    One datasheet stating one parameter at three ambients is three legitimate
    values, not "four apparent conflicts and zero real ones". The values and
    temperatures are pinned so the fixture cannot drift into a different example
    while still parsing - parity with `_sungrow()` in `test_propose_commit.py`.
    """
    claims = _claims(SUNGROW)
    assert [(c.value, c.condition.temperature_c) for c in claims] == [
        (352.0, 30.0),
        (320.0, 40.0),
        (295.0, 50.0),
    ]
    candidates = [c.as_candidate() for c in claims]
    assert not any(c.condition.is_unstated() for c in candidates)
    assert comparison_pairs(candidates, field_name="rated_ac_power") == []


def test_the_trina_pair_still_disagrees_beyond_tolerance() -> None:
    """The other direction: a record value and a web value that genuinely disagree.

    Asserting only "one comparison pair" would be too weak. `comparison_pairs`
    reports *comparability*, not disagreement - widening `nameplate_power`'s
    tolerance from 1 Wp to 10 would leave the pair intact while the conflict
    silently vanished. So this asserts the verdict, and that the two candidates
    sit on opposite source tiers, which is what makes it RECORD_VS_WEB rather
    than two record values disagreeing.
    """
    claims = _claims(TRINA)
    assert {c.source_tier for c in claims} == {
        SourceTier.SYSTEM_OF_RECORD,
        SourceTier.WEB_SUPPLEMENT,
    }

    candidates = [c.as_candidate() for c in claims]
    pairs = comparison_pairs(candidates, field_name="nameplate_power")
    assert len(pairs) == 1

    left, right = pairs[0]
    verdict = values_conflict(
        left, right, tolerance=tolerance_for("nameplate_power"), field_name="nameplate_power"
    )
    assert verdict.conflicts
    assert verdict.conflict_class is ConflictClass.RECORD_VS_WEB
    assert {left.value, right.value} == {650.0, 655.0}


def test_the_conflict_fixture_matches_the_claims_it_was_derived_from() -> None:
    """WP-E consumes the claim fixture and produces the conflict fixture, so if the
    two drift apart a downstream package is building on something upstream no
    longer produces."""
    claims = _claims(TRINA)
    entry = _conflict(TRINA)
    assert entry.field_name == claims[0].field_name
    assert [c.value for c in entry.candidates] == [c.value for c in claims]
    assert [c.source_tier for c in entry.candidates] == [c.source_tier for c in claims]


def test_the_conflict_fixtures_severity_is_what_the_policy_computes_today() -> None:
    """Pins the *semantics*, not just the shape.

    `conflict_class` is read off the fixture rather than hardcoded: passing a
    literal would let the committed class drift while severity still recomputed
    green, which is the same shape of blind spot as asserting a pair instead of a
    verdict above. The expected class is then asserted separately.
    """
    entry = _conflict(TRINA)
    assert entry.conflict_class is ConflictClass.RECORD_VS_WEB

    candidates = list(entry.candidates)
    recomputed = assign_severity(entry.field_name, entry.conflict_class, candidates, candidates)
    assert entry.severity is recomputed
    assert entry.severity is Severity.MEDIUM


def test_no_fixture_carries_a_resolution() -> None:
    """FR-HITL-06: a resolution is a human decision. A committed one is a decision
    with nobody behind it, and anything seeding a store from these fixtures would
    import it as though a reviewer had made it."""
    for path in (FIXTURE_ROOT / "conflicts").glob("*.json"):
        entry = _conflict(path.name)
        assert entry.resolution is None, f"{path.name} ships a fabricated resolution"
