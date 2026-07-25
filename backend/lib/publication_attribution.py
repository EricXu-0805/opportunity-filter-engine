"""Serving-side view of ``metadata.publication_attribution_status``.

The pipeline stamps the field when it writes ``metadata.recent_works``
(src/collectors/openalex_enrich.py — the value literals live there with the
writer; these mirror them). Records enriched before the stamp existed simply
lack it. Serving treats anything but a known value as unknown — an honest
label, never an error, and never a reason to hide or reorder publications.
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
    return attribution_status(opp) == VERIFIED_AUTHOR_ID
