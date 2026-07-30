"""The publication-trust boundary: fail-closed attribution gating.

A publication may be used for professor-specific matching or personalization
ONLY when its attribution to that professor is explicitly verified —
``metadata.publication_attribution_status == "verified_author_id"``, stamped
by ``src/collectors/openalex_enrich.apply_works`` when the works were fetched
through a resolved OpenAlex author id (the gated ``_match_author``
institution + surname + field resolution).

Everything else fails closed: ``name_match`` (works whose only person linkage
is a name-derived key), records enriched before the stamp existed (field
absent), and unknown/junk values are all treated as UNVERIFIED. Unverified
works may stay in the corpus as internal attribution *candidates* for the
recollection/verification effort, but no serving or generation path may use
them as professor-specific signal: not match scoring or match reasons, not
Ask-AI context, not resume personalization, not cold-email personalization,
and not API/frontend exposure as the professor's publications.

The allowed condition is equality with the verified literal — never a
"not rejected" / "not unverified" complement, which would fail OPEN on new or
malformed statuses.

This module is dependency-free so both the pipeline (``src/``) and serving
(``backend/``) sides import the SAME predicate instead of drifting copies.
``backend/lib/publication_attribution.py`` re-exports it for backend callers.
"""
from __future__ import annotations

VERIFIED_AUTHOR_ID = "verified_author_id"
NAME_MATCH = "name_match"
_KNOWN_STATUSES = frozenset({VERIFIED_AUTHOR_ID, NAME_MATCH})


def attribution_status(opp: dict) -> str | None:
    """The record's stamped status, or ``None`` for legacy/unexpected values."""
    status = (opp.get("metadata") or {}).get("publication_attribution_status")
    return status if status in _KNOWN_STATUSES else None


def works_are_verified(opp: dict) -> bool:
    """True ONLY for explicitly verified attribution (fail closed)."""
    return attribution_status(opp) == VERIFIED_AUTHOR_ID


# The questions every consumer actually asks, answered in one place so no
# feature re-implements a slightly different (and drift-prone) check.

def can_use_publications_for_personalization(opp: dict) -> bool:
    """May this record's publications drive professor-specific output?"""
    return works_are_verified(opp)


def verified_recent_works(opp: dict) -> list[dict]:
    """``metadata.recent_works`` when attribution is explicitly verified,
    else ``[]``. The ONLY sanctioned way for a serving/generation path to read
    a record's publications."""
    if not works_are_verified(opp):
        return []
    return (opp.get("metadata") or {}).get("recent_works") or []
