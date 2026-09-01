"""The publication-trust boundary: fail-closed attribution gating.

A publication may be used for professor-specific matching or personalization
ONLY when its attribution to that professor is explicitly verified —
``metadata.publication_attribution_status == "verified_author_id"``, stamped
by ``src/collectors/openalex_enrich.apply_works`` when the works were fetched
through a resolved OpenAlex author id (the gated ``_match_author``
institution + surname + field resolution).

Everything else fails closed: ``name_match`` (works whose only person linkage
is a name-derived key), ``pending_remediation`` (works a superseded gate chose,
withdrawn from trust until the current gate has re-judged them), records
enriched before the stamp existed (field absent), and unknown/junk values are
all treated as UNVERIFIED. Unverified works may stay in the corpus as internal
attribution *candidates* for the recollection/verification effort, but no
serving or generation path may use them as professor-specific signal: not match
scoring or match reasons, not Ask-AI context, not resume personalization, not
cold-email personalization, and not API/frontend exposure as the professor's
publications.

The allowed condition is equality with the verified literal — never a
"not rejected" / "not unverified" complement, which would fail OPEN on new or
malformed statuses.

This module is dependency-free so both the pipeline (``src/``) and serving
(``backend/``) sides import the SAME predicate instead of drifting copies.
``backend/lib/publication_attribution.py`` re-exports it for backend callers.

WHY THE GATE VERSION LIVES HERE TOO. "Verified" is a claim made by a specific
version of the attribution rule, and that rule has been wrong before: gate 1
judged a paper by the nine-field family the professor's *department* could
plausibly touch, which let a conflated OpenAlex entity's search-agent and
geochemistry papers through to a UIUC MRI professor. So trust is really two
questions — "is it stamped verified" and "by which gate" — and a consumer that
can only ask the first keeps citing whatever a superseded rule allowed. Both
answers belong to the one authority rather than to the collector that happens
to write them.
"""
from __future__ import annotations

VERIFIED_AUTHOR_ID = "verified_author_id"
NAME_MATCH = "name_match"
# Trust withdrawn pending re-judgement by the current gate. Written by the
# historical remediation (scripts/remediate_publications.py) over records a
# superseded gate had stamped verified: the papers stay on the record as
# candidates for the re-harvest, the trust does not. Deliberately a real status
# rather than a deleted stamp, because "we took this back on purpose and it is
# queued" and "nobody ever looked at this" are different facts, and the ledger,
# the operator queue and the next harvest all need to tell them apart.
PENDING_REMEDIATION = "pending_remediation"
_KNOWN_STATUSES = frozenset({VERIFIED_AUTHOR_ID, NAME_MATCH, PENDING_REMEDIATION})

# Which per-work gate produced a record's stored papers.
#   1  the department's OpenAlex field family alone. A proxy for the author and
#      a poor one in both directions: Electrical & Computer Engineering spans
#      nine fields including Computer Science and Environmental Science, so a
#      conflated entity's papers all passed, while the professor's own imaging
#      work, filed under Medicine, did not.
#   2  the author's own published fields, falling back to the family only when
#      we don't have them (#846), with the roster's direct name evidence
#      allowed to reclaim a record the field gate discarded (#853).
#
# Bump this when the rule deciding "could this paper be theirs" changes. Every
# record an older gate stamped then re-enters the remediation population by
# construction — no migration, no hand-maintained list of affected ids.
CURRENT_WORKS_GATE = 2


def attribution_status(opp: dict) -> str | None:
    """The record's stamped status, or ``None`` for legacy/unexpected values."""
    status = (opp.get("metadata") or {}).get("publication_attribution_status")
    return status if status in _KNOWN_STATUSES else None


def works_are_verified(opp: dict) -> bool:
    """True ONLY for explicitly verified attribution (fail closed).

    Positive equality with the verified literal, never a complement: a status
    this module has not heard of — a new pipeline stage, a typo, a half-applied
    migration — has to read as untrusted, and ``!= rejected`` would read it as
    trusted.
    """
    return attribution_status(opp) == VERIFIED_AUTHOR_ID


def record_works_gate(opp: dict) -> int:
    """The gate that chose this record's stored works.

    Absent means gate 1: every write since the field existed sets it, so the
    only records without one are those written before it did.
    """
    gate = (opp.get("metadata") or {}).get("works_gate")
    return gate if isinstance(gate, int) else 1


def works_are_current_gate(opp: dict) -> bool:
    """Whether this record's papers were chosen by the gate in force today."""
    return record_works_gate(opp) >= CURRENT_WORKS_GATE


def is_pending_remediation(opp: dict) -> bool:
    """Whether trust in these papers has been withdrawn pending re-judgement."""
    return attribution_status(opp) == PENDING_REMEDIATION


def needs_publication_remediation(opp: dict) -> bool:
    """Whether this record's papers are trusted on a superseded gate's word.

    The authoritative membership test for the historical remediation
    population, defined once here. A record qualifies when it is *currently
    trusted* and that trust was granted by a gate older than the one in force —
    exactly the set whose citations no living rule has ever approved.

    Records already withdrawn (``pending_remediation``) are NOT in this set:
    the invalidation step has dealt with them and the ledger tracks them from
    there. Ask ``is_pending_remediation`` for those.
    """
    return works_are_verified(opp) and not works_are_current_gate(opp)


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
