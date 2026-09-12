"""The caller a store connection is opened through (P2-C5)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PrincipalContext"]


@dataclass(frozen=True)
class PrincipalContext:
    """Identity and entitlement for one request.

    Story 4a's `open_transaction` reads this type; it does not define a second
    class. `denied_suppliers` is the Story 7 outcome-C recusal hook and stays
    empty until that story populates it.
    """

    subject: str
    cleared_for_restricted: bool
    denied_suppliers: frozenset[str] = frozenset()
