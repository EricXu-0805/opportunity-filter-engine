"""Shared evidence & provenance vocabulary for corpus facts (truthfulness W11).

One tiny authority for three questions every pipeline stage and serving path
keeps re-answering ad hoc:

1. **Was this value observed or synthesized?** Collectors stamp
   ``metadata.email_source`` (W7a); anything synthesized from a naming
   convention rather than observed on a page must never be treated as a real
   address by ranking or reveal flows. The prefix tuple lives here so
   ``src.matcher.ranker`` and ``backend.lib.contact_visibility`` cannot drift.

2. **Was this value stated by the source or inferred by us?** Rule/LLM
   taggers historically wrote into ``eligibility``/top-level fields with no
   marker, making "the page said so" and "a heuristic guessed so"
   indistinguishable at rest (the keyword-provenance debt). ``stamp_inferred``
   records the method under ``metadata.inferred_fields`` — additive, never a
   gate on legacy records (absent stamp == legacy/unknown provenance, exactly
   like ``email_source``).

3. **May source B overwrite what source A wrote?** ``SOURCE_PRIORITY`` is the
   centralized ordering (official page > academic-identity source >
   approved aggregator > our own inference > construction). Equal rank may
   refresh (a newer scrape of the same class of source); a lower rank must
   never silently replace a higher one — it either abstains or records a
   conflict with ``record_conflict`` for review.

Fail-open by design for legacy data (same contract as W7a): these helpers
label and arbitrate NEW writes; they never destroy or gate values that
predate stamping.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# 1. Observed vs synthesized (email provenance)
# ---------------------------------------------------------------------------

# Any email_source starting with one of these was synthesized, not observed.
# Prefix match so future variants (e.g. "constructed_<campus>") stay covered.
SYNTHESIZED_EMAIL_PREFIXES = ("constructed", "inferred", "guessed", "pattern")


def is_synthesized_email_source(source: object) -> bool:
    """True when an ``metadata.email_source`` stamp marks a synthesized address."""
    return isinstance(source, str) and source.startswith(SYNTHESIZED_EMAIL_PREFIXES)


def harvested_contact_email(opp: dict) -> str:
    """The record's contact email when its provenance passes the harvested bar.

    Returns ``""`` for missing addresses and for synthesized-provenance ones.
    The legacy unstamped majority (real scrapes predating provenance stamps)
    passes — provenance never gates data that predates it.
    """
    email = opp.get("contact_email") or opp.get("pi_email") or ""
    if not isinstance(email, str) or not email.strip():
        return ""
    source = (opp.get("metadata") or {}).get("email_source") or ""
    if is_synthesized_email_source(source):
        return ""
    return email.strip()


# ---------------------------------------------------------------------------
# Position rank (shared by collectors and serving so framing cannot drift)
# ---------------------------------------------------------------------------

# "Prof." framing is earned only by a source-stated professor rank. Matches
# Professor / Assistant, Associate, Teaching, Research, Adjunct Professor /
# "Prof." / "Prof" — and NOT "Professional …" (the essor/./\b alternation
# rejects the 'essional' continuation).
_PROFESSOR_RANK_RE = re.compile(r"\bprof(?:essor|\.|\b)", re.IGNORECASE)


def is_professor_rank(title: object) -> bool:
    """True when a stated rank is a professor rank; "" / None / other ranks are not."""
    return isinstance(title, str) and bool(_PROFESSOR_RANK_RE.search(title))


# ---------------------------------------------------------------------------
# 2. Stated vs inferred (field-level inference stamps)
# ---------------------------------------------------------------------------

INFERRED_FIELDS_KEY = "inferred_fields"


def stamp_inferred(metadata: dict, field: str, method: str) -> None:
    """Record that ``field`` was written by inference ``method``, not stated.

    ``field`` is the dotted record path ("eligibility.international_friendly",
    "deadline", "keywords"); ``method`` names the producer
    ("rule:federal_org", "llm:bio_extraction", "policy:nsf_reu_solicitation",
    "estimate:award_start_date"). Idempotent; last writer wins for the same
    field, which is correct because the stamp describes the current value.
    """
    stamps = metadata.setdefault(INFERRED_FIELDS_KEY, {})
    stamps[field] = method


def inferred_method(record: dict, field: str) -> str | None:
    """The inference method stamped for ``field``, or None (stated/legacy)."""
    meta = record.get("metadata") or {}
    stamps = meta.get(INFERRED_FIELDS_KEY) or {}
    method = stamps.get(field)
    return method if isinstance(method, str) and method else None


def is_inferred(record: dict, field: str) -> bool:
    """True when the current value of ``field`` carries an inference stamp."""
    return inferred_method(record, field) is not None


# ---------------------------------------------------------------------------
# 3. Source priority + conflicts
# ---------------------------------------------------------------------------

# Lower rank = more authoritative. Ranks, not a total order of source names:
# every concrete source (a dept directory, the WP-REST API of that dept, a
# faculty member's own page) maps into one of these classes.
SOURCE_PRIORITY = {
    "official_page": 0,       # university/college/dept/program/faculty page or its official API
    "official_announcement": 0,  # official application system / announcement
    "academic_identity": 1,   # approved identity sources (OpenAlex author records)
    "approved_third_party": 2,  # aggregators used by permission (Simplify, Handshake)
    "rule_inference": 3,      # deterministic heuristics over source text
    "llm_inference": 3,       # LLM extraction/derivation from source text
    "constructed": 4,         # synthesized values; never product-verified facts
    "discovery": 5,           # search results/crawl discovery — leads, never evidence
}


def source_rank(kind: str) -> int:
    """Rank for a source class; unknown classes rank below every known one."""
    return SOURCE_PRIORITY.get(kind, max(SOURCE_PRIORITY.values()) + 1)


def can_override(new_kind: str, old_kind: str | None) -> bool:
    """May a value from ``new_kind`` replace one from ``old_kind``?

    Equal or higher authority may refresh; lower authority must abstain (and
    ``record_conflict`` when it disagrees). ``old_kind`` None means the field
    is empty/legacy-unstamped — anything may fill an empty field.
    """
    if old_kind is None:
        return True
    return source_rank(new_kind) <= source_rank(old_kind)


CONFLICTS_KEY = "conflicts"
_CONFLICTS_CAP = 10


def record_conflict(metadata: dict, field: str, *, kept: object, rejected: object,
                    kept_source: str, rejected_source: str) -> None:
    """Keep an audit trail when two sources disagree about one field.

    The KEPT value stays in the record body; the disagreement is preserved for
    review instead of being silently discarded. Deduped on (field, rejected)
    and capped so a flapping source can't grow a record without bound.
    """
    conflicts = metadata.setdefault(CONFLICTS_KEY, [])
    for c in conflicts:
        if c.get("field") == field and c.get("rejected") == rejected:
            return
    if len(conflicts) >= _CONFLICTS_CAP:
        return
    conflicts.append({
        "field": field,
        "kept": kept,
        "rejected": rejected,
        "kept_source": kept_source,
        "rejected_source": rejected_source,
        "seen_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    })
