"""Serving-side face of the publication-trust boundary (fail closed).

Re-exports the canonical predicates from ``src.publication_trust`` — the one
authority both the pipeline and serving share. A publication may influence
professor-specific output (match reasons/scoring, Ask AI context, resume
personalization, cold email, API exposure) ONLY when
``metadata.publication_attribution_status == "verified_author_id"``.
``name_match``, absent, pending, or unrecognized statuses are all UNVERIFIED
and must be excluded, never merely labeled.
"""
from __future__ import annotations

from src.publication_trust import (
    NAME_MATCH,
    VERIFIED_AUTHOR_ID,
    attribution_status,
    can_use_publications_for_personalization,
    verified_recent_works,
    works_are_verified,
)

__all__ = [
    "NAME_MATCH",
    "VERIFIED_AUTHOR_ID",
    "attribution_status",
    "can_use_publications_for_personalization",
    "verified_recent_works",
    "works_are_verified",
]
