"""A textual rendering of a field value that respects equality.

`schema` sits below `services` and cannot import it, which is why this lives
here rather than beside either caller: `services.claims` and
`services.conflict_hitl` both need it, and `services.claims` already imports
`services.conflict_hitl`, so a helper in either one would be a cycle or a second
copy. It was a second copy - `claims._render` canonicalised containers while
`conflict_hitl._ordering_key` still called `repr` on the same values.

**This is the equality rendering, not D-14's hash encoding.** `encode_value()`
(Track 1a, `schema/encoding.py`) is a different function with a different
contract: it must be *injective* over the candidate value domain, so it keeps
`Decimal("650")`, `650` and `650.0` apart and tags `Decimal` and `date`. This
one only has to agree with `==`. The two belong side by side once Track 1a
lands; neither can be written in terms of the other, and this module makes no
attempt to anticipate D-14's rules.
"""

from __future__ import annotations

__all__ = ["render_value"]


def render_value(value: object, _containers: tuple[int, ...] = ()) -> str:
    """A textual rendering of a value that respects equality.

    `repr` does not, and that is not a nicety: a dict reprs in *insertion* order,
    so two extractions that read one cooling table's rows in different orders
    give values that are `==` and reprs that are not. The contract has three
    dict-valued parameters - `rating_mva_by_cooling`, `harmonic_spectrum`,
    `ercot_compliance_items` - and under `repr` such a pair counted as a
    disagreement: an OPEN conflict between two identical values, a
    `ProposalError` losing the whole field when the two shared a claim key, or -
    in `_ordering_key` - a pair orientation that changed with no data change,
    which is the A-50 class the projection hash exists to keep out.

    Containers are walked rather than repr'd whole, so the canonicalisation
    reaches a nested dict. The cycle guard is not tidiness: `repr` already
    handles a self-referential value, and a hand-rolled walk that did not would
    trade a false conflict for a `RecursionError`.
    """
    if id(value) in _containers:
        return "..."
    nested = (*_containers, id(value))
    if isinstance(value, dict):
        entries = sorted(
            (render_value(k, nested), render_value(v, nested)) for k, v in value.items()
        )
        return "{" + ", ".join(f"{key}: {item}" for key, item in entries) + "}"
    if isinstance(value, list | tuple):
        return f"{type(value).__name__}[" + ", ".join(render_value(v, nested) for v in value) + "]"
    if isinstance(value, set | frozenset):
        return (
            f"{type(value).__name__}["
            + ", ".join(sorted(render_value(v, nested) for v in value))
            + "]"
        )
    return repr(value)
