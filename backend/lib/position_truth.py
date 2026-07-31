"""Serving-side face of position truthfulness (W11).

Legacy corpus records bake the display string "Research with Prof. <name>"
into ``title`` regardless of the scraped rank — 12% of faculty records whose
own ``metadata.faculty_title`` says Lecturer / Instructor / Director shipped
with a "Prof." claim. Collectors no longer fabricate the honorific, but the
committed shards refresh gradually; this copy-on-write rewrite makes every
serving path honest immediately.

Only a STATED non-professor rank triggers the rewrite: a legacy
``faculty_title == "Professor"`` (real or historical default) is
indistinguishable from evidence and is left as-is — that residual is
documented in docs/truthfulness_audit.md.
"""
from __future__ import annotations

from src.evidence import is_professor_rank

_PROF_PREFIX = "Research with Prof. "


def stated_rank(opp: dict) -> str:
    """The record's stated academic rank, '' when unknown."""
    rank = (opp.get("metadata") or {}).get("faculty_title")
    return rank.strip() if isinstance(rank, str) else ""


def displayed_title(opp: dict) -> str:
    """The record title, with an unsupported "Prof." honorific removed."""
    title = opp.get("title") or ""
    rank = stated_rank(opp)
    if rank and not is_professor_rank(rank) and title.startswith(_PROF_PREFIX):
        return "Research with " + title[len(_PROF_PREFIX):]
    return title
