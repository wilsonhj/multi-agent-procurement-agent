"""FR-HITL-06's two invariants, over every route that reaches a `CanonicalField`.

`tests/test_schema_invariants.py` covers the constructor and plain assignment.
This file covers the routes that skip validation entirely, and the one a
validator structurally cannot see.

**Why a separate file.** Review enumerated six ways to reach the forbidden
RESOLVED-with-no-`Resolution` state and one way to silently overwrite a recorded
decision, all of which passed against the version that claimed "two routes
remain open". Each needs a named test rather than a line inside an existing one,
because the useful failure message is *which route reopened*, and because two of
the seven are deliberately not closed and have to say so out loud rather than
being absent.

The invariants:

  1. `conflict_status is RESOLVED` implies `resolution is not None` - a decision
     with no record of who made it.
  2. A recorded `Resolution` is never replaced or cleared. Every validator passes
     a swap, because the resulting state is perfectly legal; only a check that
     can see the *transition* catches it. FR-HITL-06: "logged immutably".
"""

from __future__ import annotations

import copy
import pickle
from datetime import UTC, datetime
from typing import Any

import pytest

from procurement_agent.schema import (
    CanonicalField,
    ConflictStatus,
    Resolution,
    ResolutionAction,
    SourceRef,
    SourceTier,
)


def _resolution(resolved_by: str = "procurement.lead", value_after: object = 650) -> Resolution:
    return Resolution(
        action=ResolutionAction.SELECT_VALUE,
        resolved_by=resolved_by,
        resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
        rationale="datasheet revision C supersedes the PO",
        value_after=value_after,
    )


def _field(**overrides: object) -> CanonicalField:
    base: dict[str, object] = {
        "value": 650,
        "source_tier": SourceTier.SYSTEM_OF_RECORD,
        "source_ref": SourceRef(document_id="doc-1"),
        "confidence": 0.9,
    }
    base.update(overrides)
    return CanonicalField(**base)  # type: ignore[arg-type]


def _resolved() -> CanonicalField:
    return _field().evolve(conflict_status=ConflictStatus.RESOLVED, resolution=_resolution())


def _poisoned() -> CanonicalField:
    """A field in the forbidden state, reached the only way that still works.

    Used as the *input* to the propagation tests below. Writing the instance
    `__dict__` is not a route this type can close (see
    `test_the_dict_write_route_is_documented_as_open`), so it is the honest way
    to manufacture a corrupt object for the boundary tests without pretending the
    supported API produced it.
    """
    field = _field()
    field.__dict__["conflict_status"] = ConflictStatus.RESOLVED
    return field


# --- invariant 1: routes that skip validation ----------------------------------


def test_model_construct_still_runs_the_class_invariant() -> None:
    """`model_construct` skips *field* parsing, which is its point, and skipped
    model validators too, which is not. It produced a RESOLVED field with no
    Resolution that then serialised into the audit trail with no complaint:

        CanonicalField.model_construct(
            ..., conflict_status=RESOLVED, resolution=None
        ).model_dump()["conflict_status"]   # 'resolved'
    """
    with pytest.raises(ValueError, match="must carry its Resolution"):
        CanonicalField.model_construct(
            value=650,
            source_tier=SourceTier.SYSTEM_OF_RECORD,
            source_ref=SourceRef(document_id="doc-1"),
            confidence=0.9,
            conflict_status=ConflictStatus.RESOLVED,
            resolution=None,
        )


def test_model_construct_still_works_for_a_valid_field() -> None:
    """The check must not cost `model_construct` its purpose: a well-formed
    field still builds, and still without re-parsing its fields."""
    field = CanonicalField.model_construct(
        value=650,
        source_tier=SourceTier.SYSTEM_OF_RECORD,
        source_ref=SourceRef(document_id="doc-1"),
        confidence=0.9,
        conflict_status=ConflictStatus.RESOLVED,
        resolution=_resolution(),
    )
    assert field.resolution is not None


def test_unpickling_a_corrupt_field_raises_rather_than_restoring_it() -> None:
    """Pickle is a deserialisation boundary - a cache, a task queue, another
    process - and stock pydantic restores `__dict__` wholesale with no validator
    run, so a corrupt object crossed it and arrived looking freshly constructed.

    This does not make the `__dict__` route defensible; it stops one component's
    bug becoming another component's audit record."""
    payload = pickle.dumps(_poisoned())
    with pytest.raises(ValueError, match="must carry its Resolution"):
        pickle.loads(payload)


def test_a_valid_field_still_survives_a_pickle_round_trip() -> None:
    field = _resolved()
    restored = pickle.loads(pickle.dumps(field))
    assert restored.resolution == field.resolution
    assert restored.conflict_status is ConflictStatus.RESOLVED


def test_deepcopying_a_corrupt_field_raises_rather_than_duplicating_it() -> None:
    """`copy.deepcopy` is the in-process twin of a pickle round trip, and the
    ordinary way a corrupt object gets duplicated into a collection that is then
    serialised."""
    with pytest.raises(ValueError, match="must carry its Resolution"):
        copy.deepcopy(_poisoned())


def test_a_valid_field_still_survives_a_deepcopy() -> None:
    field = _resolved()
    assert copy.deepcopy(field).resolution == field.resolution


def test_model_copy_deep_also_revalidates() -> None:
    """`model_copy(deep=True)` routes through `__deepcopy__`, so the guard has to
    hold there too - otherwise the one `model_copy` form this class still allows
    becomes the replacement for the `update=` form it refuses."""
    with pytest.raises(ValueError, match="must carry its Resolution"):
        _poisoned().model_copy(deep=True)


# --- invariant 2: a recorded decision is never overwritten ---------------------


def test_assignment_cannot_replace_a_recorded_resolution() -> None:
    """Every validator passes this: the resulting state is legal. Only a check
    that sees the transition catches it, which is why it lives in `__setattr__`
    and not in `_resolution_matches_status`."""
    field = _resolved()
    with pytest.raises(ValueError, match="cannot be replaced or cleared"):
        field.resolution = _resolution(resolved_by="someone.else", value_after=999)
    assert field.resolution is not None
    assert field.resolution.resolved_by == "procurement.lead"


def test_evolve_cannot_replace_a_recorded_resolution() -> None:
    """`evolve` merges into a snapshot and revalidates, so it too passes every
    validator while swapping one reviewer's decision for another's."""
    field = _resolved()
    with pytest.raises(ValueError, match="cannot be replaced or cleared"):
        field.evolve(resolution=_resolution(resolved_by="someone.else", value_after=999))
    assert field.resolution is not None
    assert field.resolution.resolved_by == "procurement.lead"


def test_evolve_cannot_clear_a_recorded_resolution() -> None:
    field = _resolved()
    with pytest.raises(ValueError):
        field.evolve(resolution=None)
    assert field.resolution is not None


def test_attaching_a_first_resolution_is_still_allowed() -> None:
    """The rule is append-only, not read-only. The legitimate transition - a
    field that has no resolution gaining one - must still work, or the guard has
    broken the pipeline it was meant to protect."""
    field = _field()
    field.resolution = _resolution()
    field.conflict_status = ConflictStatus.RESOLVED
    assert field.conflict_status is ConflictStatus.RESOLVED

    both_at_once = _field().evolve(
        conflict_status=ConflictStatus.RESOLVED, resolution=_resolution()
    )
    assert both_at_once.resolution is not None


def test_reassigning_an_equal_resolution_is_not_an_error() -> None:
    """An idempotent replay - the same decision written twice by a retried
    worker - is not tampering, and making it raise would push callers into
    checking-before-writing, which races."""
    field = _resolved()
    field.resolution = _resolution()
    assert field.evolve(resolution=_resolution()).resolution == _resolution()


# --- what is deliberately NOT closed --------------------------------------------


def test_the_dict_write_route_is_documented_as_open() -> None:
    """The one remaining route, asserted as open on purpose.

    Writing the instance `__dict__` - directly, or via `object.__setattr__`,
    which is the same write in a different spelling - reaches the forbidden state
    and cannot be defended against by any Python object: it is the same primitive
    the language uses to build the object in the first place.

    This test exists so the gap is a recorded fact rather than an oversight, and
    so that if a future pydantic release *does* close it, this goes red and the
    claim in `CanonicalField`'s docstring and in
    docs/requirements-traceability.md gets updated rather than quietly becoming
    over-cautious."""
    by_dict = _field()
    by_dict.__dict__["conflict_status"] = ConflictStatus.RESOLVED
    assert by_dict.conflict_status is ConflictStatus.RESOLVED
    assert by_dict.resolution is None

    by_object_setattr = _field()
    object.__setattr__(by_object_setattr, "conflict_status", ConflictStatus.RESOLVED)
    assert by_object_setattr.conflict_status is ConflictStatus.RESOLVED
    assert by_object_setattr.resolution is None

    # And the same route clears a recorded resolution.
    cleared = _resolved()
    cleared.__dict__["resolution"] = None
    assert cleared.resolution is None


def test_replaying_an_equal_resolution_from_its_serialised_form_is_not_an_error() -> None:
    """The same promise as the test above, at the boundary the class is built for.

    A worker replaying a decision read back from the store holds a `dict`, not a
    `Resolution`. Both routes compared the incoming value *before* pydantic
    coerced it, so `dict != Resolution` was true for two spellings of one
    decision and the immutability error fired on an idempotent replay - the exact
    case `__setstate__` and `__deepcopy__` exist to make safe.
    """
    field = _resolved()
    field.resolution = _resolution()
    # `Any`: a store row arrives untyped, which is the whole point of the case.
    serialised: Any = _resolution().model_dump()

    field.resolution = serialised
    assert field.resolution == _resolution()
    assert field.evolve(resolution=serialised).resolution == _resolution()


def test_a_different_resolution_in_dict_form_is_still_refused() -> None:
    """Coercing before comparing must widen *equality*, not the rule. A second
    reviewer's decision arriving as a dict is still an overwrite."""
    field = _resolved()
    field.resolution = _resolution()
    someone_else: Any = _resolution(resolved_by="someone.else").model_dump()

    with pytest.raises(ValueError, match="cannot be replaced"):
        field.resolution = someone_else
    with pytest.raises(ValueError, match="cannot be replaced"):
        field.evolve(resolution=someone_else)


def test_an_uncoercible_resolution_is_still_refused() -> None:
    """A value that is not a Resolution at all must not slip through the coercion
    attempt as 'equal'. It compares unequal and raises, as before."""
    field = _resolved()
    field.resolution = _resolution()
    not_a_resolution: Any = {"action": "not-an-action"}

    with pytest.raises(ValueError, match="cannot be replaced"):
        field.resolution = not_a_resolution


def test_shallow_copying_a_corrupt_field_raises_rather_than_duplicating_it() -> None:
    """A-56. `copy.copy` was the route the inventory missed: pydantic implements
    it by copying `__dict__` exactly as `__deepcopy__` does, so a poisoned field
    shallow-copied into a collection carried the forbidden state across while
    the deep copy of the same object refused it."""
    with pytest.raises(ValueError, match="must carry its Resolution"):
        copy.copy(_poisoned())


def test_a_valid_field_still_survives_a_shallow_copy() -> None:
    field = _resolved()
    assert copy.copy(field) == field
