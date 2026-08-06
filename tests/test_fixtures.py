"""The committed fixture sets, and the assertions that stop them rotting (T0.6).

`tasks.md` specifies the decoupling technique these exist for: "Each team builds
against **committed fixture files** matching the frozen schemas. WP-B ships golden
claim JSON; WP-E consumes it and ships golden conflict JSON; WP-F and WP-G consume
that. Nobody waits on anybody's service."

That only works if the fixtures are *known* to still match the schemas. A fixture
nothing asserts against is worse than no fixture, because a downstream package
builds on it and discovers the drift at integration time - which is precisely the
coupling the technique exists to remove. So every file here is checked three ways:

1. **It validates** against its model. Catches a schema change that the fixture
   was never updated for.
2. **It round-trips byte-for-byte.** Catches drift in the *other* direction - a
   field added to the model, or a serialisation alias changed, would leave the
   committed JSON a valid-but-incomplete instance, which `model_validate` alone
   accepts silently because every added field so far has had a default.
3. **It still means what it was written to mean.** Schema-valid JSON encoding the
   wrong worked example is the failure mode neither check above can see.

Only contracts that are actually frozen get fixtures. C2/C3 (claims) and C5
(conflicts) are covered. **C6 deliberately is not**: the canonical workbook
projection is unfrozen (T0.5), and publishing a golden projection now would freeze
by accident the one decision `tasks.md` says must be made deliberately.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from procurement_agent.schema import ConflictClass, ConflictQueueEntry, Severity
from procurement_agent.services.claims import FieldClaim
from procurement_agent.services.conflict_hitl import assign_severity, comparison_pairs

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

#: Subdirectory -> the contract it carries. A directory absent from this map is a
#: fixture nothing validates, so `test_every_fixture_lives_in_a_known_directory`
#: fails rather than letting it sit there unchecked.
FIXTURE_KINDS: dict[str, str] = {
    "claims": "C2/C3 - a list of FieldClaim",
    "conflicts": "C5 - a single ConflictQueueEntry",
}


def _fixture_files() -> list[Path]:
    return sorted(FIXTURE_ROOT.rglob("*.json"))


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(FIXTURE_ROOT)) for p in paths]


def test_the_fixture_root_is_not_empty() -> None:
    """T0.6 asks for fixture sets to exist at all.

    Without this, every parametrised test below would collect zero cases and the
    suite would pass green over a deleted directory - the vacuous-pass shape that
    `sql/README.md` already records twice.
    """
    assert FIXTURE_ROOT.is_dir()
    assert _fixture_files(), "no fixtures found; the parametrised tests would be vacuous"


def test_every_fixture_lives_in_a_known_directory() -> None:
    """A new fixture directory must be wired into `FIXTURE_KINDS` to be validated.

    Adding `tests/fixtures/workbooks/` and committing a golden projection would
    otherwise be checked by nothing at all, while *looking* covered because this
    module exists.
    """
    unknown = {
        str(p.relative_to(FIXTURE_ROOT))
        for p in _fixture_files()
        if p.relative_to(FIXTURE_ROOT).parts[0] not in FIXTURE_KINDS
    }
    assert not unknown, f"fixtures in unmapped directories: {sorted(unknown)}"


@pytest.mark.parametrize("path", _fixture_files(), ids=_ids(_fixture_files()))
def test_a_fixture_round_trips_through_its_model(path: Path) -> None:
    """Validate, re-dump, and compare against what is on disk.

    `model_validate` alone is a weak check: every field added to these models so
    far has carried a default, so a fixture written before the addition still
    validates and silently encodes the default rather than a considered value.
    Comparing the re-dump against the committed bytes catches that.
    """
    raw = _load(path)
    kind = path.relative_to(FIXTURE_ROOT).parts[0]

    if kind == "claims":
        assert isinstance(raw, list), "a claims fixture is a list of FieldClaim"
        dumped: Any = [FieldClaim.model_validate(c).model_dump(mode="json") for c in raw]
    else:
        dumped = ConflictQueueEntry.model_validate(raw).model_dump(mode="json")

    assert dumped == raw, (
        f"{path.name} no longer round-trips; the model and the committed JSON have "
        "diverged. Regenerate the fixture and re-check the behavioural assertions "
        "below - do not just overwrite it."
    )


def test_the_sungrow_trio_still_raises_no_conflict() -> None:
    """D-1's worked example, loaded from disk rather than built in code.

    One datasheet stating one parameter at three ambients is three legitimate
    values, not "four apparent conflicts and zero real ones". `comparison_pairs`
    returning anything non-empty here means the condition gate has been defeated
    again - the defect `test_the_sungrow_trio_raises_no_conflict` in
    `test_propose_commit.py` was written for, now also pinned against the
    committed artifact every other work package builds on.
    """
    path = FIXTURE_ROOT / "claims" / "sungrow-sg350hx-rated-ac-power.json"
    claims = [FieldClaim.model_validate(c) for c in _load(path)]
    assert len(claims) == 3
    candidates = [c.as_candidate() for c in claims]
    assert not any(c.condition.is_unstated() for c in candidates)
    assert comparison_pairs(candidates) == []


def test_the_trina_pair_still_raises_exactly_one_conflict() -> None:
    """The other direction: a record value and a web value that genuinely disagree.

    A fixture set that only contains the no-conflict case would let a change
    suppressing *all* conflicts pass green, which is the more dangerous failure -
    FR-5 is about surfacing disagreement, not hiding it.
    """
    path = FIXTURE_ROOT / "claims" / "trina-tsm-neg21c-nameplate.json"
    claims = [FieldClaim.model_validate(c) for c in _load(path)]
    assert len(claims) == 2

    pairs = comparison_pairs([c.as_candidate() for c in claims])
    assert len(pairs) == 1
    left, right = pairs[0]
    # The pair is specifically record-against-web, which is what makes it a
    # RECORD_VS_WEB conflict rather than two record values disagreeing.
    assert {left.source_tier, right.source_tier} == {
        claims[0].source_tier,
        claims[1].source_tier,
    }
    assert {left.value, right.value} == {650.0, 655.0}


def test_the_conflict_fixture_matches_the_claims_it_was_derived_from() -> None:
    """The queue entry is the projection of the claim pair, so the two must agree.

    WP-E consumes the claim fixture and produces the conflict fixture. If they
    drift apart, a downstream package building on the conflict fixture is building
    on something the upstream one no longer produces - the exact integration
    failure committed fixtures exist to prevent.
    """
    claims = [
        FieldClaim.model_validate(c)
        for c in _load(FIXTURE_ROOT / "claims" / "trina-tsm-neg21c-nameplate.json")
    ]
    entry = ConflictQueueEntry.model_validate(
        _load(FIXTURE_ROOT / "conflicts" / "trina-tsm-neg21c-nameplate.json")
    )
    assert entry.field_name == claims[0].field_name
    assert [c.value for c in entry.candidates] == [c.value for c in claims]
    assert [c.source_tier for c in entry.candidates] == [c.source_tier for c in claims]


def test_the_conflict_fixtures_severity_is_what_the_policy_computes_today() -> None:
    """Pins the *semantics*, not just the shape.

    `assign_severity` is a pure function of four arguments; this asserts the
    committed severity is still the one it returns. A deliberate policy change
    turns this red, which is correct - the fixture is what WP-F and WP-G triage
    against, so a severity change is a change to their input and should require
    someone to look at it rather than propagating silently.
    """
    entry = ConflictQueueEntry.model_validate(
        _load(FIXTURE_ROOT / "conflicts" / "trina-tsm-neg21c-nameplate.json")
    )
    candidates = list(entry.candidates)
    recomputed = assign_severity(
        entry.field_name, ConflictClass.RECORD_VS_WEB, candidates, candidates
    )
    assert entry.severity is recomputed
    assert entry.severity is Severity.MEDIUM


def test_no_fixture_carries_a_resolution() -> None:
    """FR-HITL-06: a resolution is a human decision, and no fixture may ship one.

    A committed `resolution` would be a decision with no human behind it, and any
    package seeding a store from these fixtures would import it as though a
    reviewer had made it.
    """
    for path in (FIXTURE_ROOT / "conflicts").glob("*.json"):
        entry = ConflictQueueEntry.model_validate(_load(path))
        assert entry.resolution is None, f"{path.name} ships a fabricated resolution"
