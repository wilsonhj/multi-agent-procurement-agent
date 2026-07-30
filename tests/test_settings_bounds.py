"""Every numeric setting carries a bound.

`Settings` is environment-driven, so an out-of-range value arrives as a string
from a `.env` file rather than from a code path a reviewer reads. The compose
gate already learned this the hard way (issue #14): a bound checked nowhere is a
bound that does not exist, and `validate_assignment=True` above it only helps
once a constraint is actually declared.
"""

from typing import Any

import annotated_types
import pytest
from pydantic import ValidationError

from procurement_agent.config import Settings


def _isolated_settings(**overrides: Any) -> Settings:
    """`Settings` built without reading the ambient environment or a local `.env`.

    A bare `Settings()` reads both, so a bounds test would depend on whatever the
    developer's `.env` happens to hold - and this branch ships `.env.example`.
    """
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


_NUMERIC = [
    name for name, field in Settings.model_fields.items() if field.annotation in (int, float)
]


def test_the_numeric_settings_are_discovered() -> None:
    """Guards the parametrisation below: an empty list would make every case
    vanish and the suite would stay green while checking nothing."""
    assert len(_NUMERIC) >= 6


@pytest.mark.parametrize("name", _NUMERIC)
def test_every_numeric_setting_declares_a_lower_bound(name: str) -> None:
    """`chunk_size_tokens` was the one exception, sitting directly beside a
    bounded sibling.

    A zero or negative chunk size is not a degraded setting, it is a chunker that
    cannot terminate - and FR-RAG-01's size is the parameter most likely to be
    tuned from the environment by someone who never reads this file.
    """
    bounds = Settings.model_fields[name].metadata
    assert any(isinstance(bound, annotated_types.Ge | annotated_types.Gt) for bound in bounds), (
        f"{name} accepts any value the environment supplies"
    )


def test_a_non_positive_chunk_size_is_refused() -> None:
    """The bound above, exercised rather than introspected."""
    with pytest.raises(ValidationError):
        _isolated_settings(chunk_size_tokens=0)
    with pytest.raises(ValidationError):
        _isolated_settings(chunk_size_tokens=-1)


def test_a_sane_chunk_size_is_still_accepted() -> None:
    """The bound must not be so tight it rejects the documented default."""
    assert _isolated_settings(chunk_size_tokens=512).chunk_size_tokens == 512
