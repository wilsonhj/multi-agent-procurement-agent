"""`extractor_version` naming (P2-C8). A pin, not a writer."""

from __future__ import annotations

__all__ = ["EXTRACTOR_VERSION_PREFIXES"]


EXTRACTOR_VERSION_PREFIXES: tuple[str, str, str, str] = (
    "<pipeline>@<semver-or-hash>",
    "human:<oidc-sub>",
    "web:<provider>@<version>",
    "gold:<annotator>",
)
"""The four legal shapes of `FieldClaim.extractor_version`.

Machine pipelines use the first; a human resolution claim uses `human:` (D-16);
Story 3's fetched pages use `web:`; gold labels use `gold:` and are never
committed to a claim store (D-24). Track 0 does not write a claim.
"""
