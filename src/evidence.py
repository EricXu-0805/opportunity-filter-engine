"""Shared evidence & provenance vocabulary for corpus facts (truthfulness W11).

One tiny authority for three questions every pipeline stage and serving path
keeps re-answering ad hoc:

1. **Was this value observed or synthesized?** Collectors stamp
   ``metadata.email_source`` (W7a); anything synthesized from a naming
   convention rather than observed on a page must never be treated as a real
   address anywhere. ``is_synthesized_email_source`` is the one predicate for
   that question. It is a necessary but not sufficient condition for "may
   this address be sent to or revealed" — that stronger authority is
   ``backend.lib.contact_visibility.verified_send_target`` (non-synthesized
   source AND identity-bound evidence AND format AND source-URL safety AND
   freshness), which ``src.matcher.ranker._is_actionable`` imports and calls
   directly rather than keeping a second, looser approximation here.

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

The provenance helpers remain fail-open for unstamped legacy data (the W7a
contract).  The faculty-directory helper below is one explicit, narrow
exception: it removes a known collector template whose positive claims were
never supported by the source, while preserving explicit restrictions and
reviewed records.
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
    """The record's contact email when its provenance passes the OBSERVED
    (non-synthesized) bar — this is a provenance-labeling helper only, NOT
    the send/reveal/actionability bar. It does not check identity-binding,
    address format, source-URL safety, or evidence freshness; see
    ``backend.lib.contact_visibility.verified_send_target`` for the
    authoritative "may this be sent to or revealed" predicate, which both
    the reveal endpoint and the Match ranker's actionability tie-break use.

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
# Recipient truth (shared by the collector hygiene pass and the serve-time
# reveal bar so the two cannot drift — W12 cold-email boundary)
# ---------------------------------------------------------------------------

# Generic department/unit/role mailbox local-parts that scrape in place of a
# professor's personal address (english@, mainoffice@physics, poultry@). A
# "Dear Prof. X" cold email to a unit inbox misfires. Exact-match only, never
# substring, so a personal username is never clipped.
UNIT_MAILBOX_LOCALPARTS = frozenset({
    "office", "mainoffice", "frontoffice", "dean", "meddean", "info", "contact",
    "admin", "administration", "advising", "gradoffice", "undergrad",
    "undergraduate", "hr", "reception", "frontdesk", "ischool", "poultry",
    "anthro", "dept", "department", "generalinquiries", "mailbox", "webmaster",
    "help", "support",
})


def dept_name_stems(department: str) -> set[str]:
    """Significant lowercased words of a department name (drops structural
    words), so an email local-part equal to one ("english", "linguistics")
    reads as a unit inbox, not a person."""
    return {
        w for w in re.split(r"[^a-z]+", (department or "").lower())
        if len(w) >= 4 and w not in {"department", "school", "college", "and", "the", "of"}
    }


def is_unit_mailbox_email(email: str, department: str = "") -> bool:
    """True when the address's local-part is a department/unit/role mailbox
    rather than a personal address."""
    if not email or "@" not in email:
        return False
    local = re.sub(r"[^a-z]", "", email.split("@")[0].lower())
    return bool(local) and (local in UNIT_MAILBOX_LOCALPARTS
                            or local in dept_name_stems(department))


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
# Faculty-directory claim boundary
# ---------------------------------------------------------------------------

def faculty_contact_claims_unverified(record: dict) -> bool:
    """Whether a row is a faculty contact profile rather than a job posting.

    Faculty collectors start from directory/profile pages. Those pages support
    identity and research-topic facts, but not blanket claims about current
    openings, eligible class years, application effort, or work authorization.
    A real, source-backed opening must be represented with a listing source
    type; neither a generic review flag nor one metadata bit may promote every
    legacy template field on a faculty profile at once.
    """
    return record.get("source_type") == "faculty_research"


_FACULTY_CITIZENSHIP_EVIDENCE_RE = re.compile(
    r"(?:"
    r"\b(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?required\b|"
    r"\bmust\s+be\s+(?:an?\s+)?(?:u\.?s\.?|united states)\s+citizens?\b|"
    r"\b(?:only|limited|restricted)\s+to\s+(?:u\.?s\.?|united states)\s+"
    r"(?:citizens?|permanent residents?)\b|"
    r"\b(?:u\.?s\.?|united states)\s+citizens?\s+only\b"
    r")",
    re.IGNORECASE,
)
_FACULTY_RESTRICTION_MARKER = "faculty_citizenship_restriction_stated"
_FACULTY_NOT_ACCEPTING_MARKER = "faculty_not_accepting_undergraduates_stated"
_FACULTY_RESEARCH_INACTIVE_MARKER = "faculty_research_inactive_stated"
_FACULTY_AVAILABILITY_STATUS_MARKER = "faculty_availability_status"
_FACULTY_AVAILABILITY_SCAN_VERSION_MARKER = "faculty_availability_scan_version"
_FACULTY_AVAILABILITY_SCAN_VERSION = 1
# The verb set is corpus-derived, not speculative.  Keep the object bounded so
# an unrelated later mention of students cannot turn a general negation into
# an outreach block. Object semantics are checked separately below: explicit
# undergraduate language, generic students, or applications count; a
# graduate-only object does not.
_FACULTY_NOT_ACCEPTING_RE = re.compile(
    r"\b(?:"
    r"(?:not|no\s+longer)\s+(?:(?:currently|now)\s+)?"
    r"(?:accept(?:ing)?|tak(?:e|ing)(?:\s+on)?|recruit(?:ing)?|admit(?:ting)?)"
    r"|does(?:\s+not|n['’]t)\s+(?:(?:currently|now)\s+)?"
    r"(?:accept|take(?:\s+on)?|recruit|admit)"
    r")\b(?P<object>[^).;:\n]{0,160})",
    re.IGNORECASE,
)
_FACULTY_UNDERGRAD_OBJECT_RE = re.compile(
    r"\b(?:undergrads?|undergraduates?|undergraduate\s+"
    r"(?:students?|researchers?|applicants?|applications?))\b",
    re.IGNORECASE,
)
_FACULTY_STUDENT_OBJECT_RE = re.compile(r"\bstudents?\b", re.IGNORECASE)
_FACULTY_APPLICATION_OBJECT_RE = re.compile(r"\bapplications?\b", re.IGNORECASE)
_FACULTY_GRAD_ONLY_STUDENT_RE = re.compile(
    r"\b(?:(?:new|additional|prospective|doctoral)\s+)*"
    r"(?:grad|graduate|doctoral|ph\.?d\.?|masters?|master['’]s)"
    r"(?:(?:\s+|-)(?:degree|research))?(?:\s+|-)"
    r"(?:students?|researchers?|applicants?)\b",
    re.IGNORECASE,
)
_FACULTY_GRAD_TERM_RE = re.compile(
    r"\b(?:grad|graduate|doctoral|ph\.?d\.?|masters?|master['’]s)\b",
    re.IGNORECASE,
)
_FACULTY_RESEARCH_INACTIVE_RE = re.compile(
    r"\b(?:not|no\s+longer)\s+(?:(?:currently|now)\s+)?"
    r"(?:research\s+active|conducting\s+research)\b",
    re.IGNORECASE,
)


def faculty_restriction_is_source_stated(record: dict) -> bool:
    """Whether source excerpt text directly states a citizenship restriction."""
    eligibility = record.get("eligibility") or {}
    excerpt = eligibility.get("eligibility_text_raw")
    excerpt_matches = (
        isinstance(excerpt, str)
        and _FACULTY_CITIZENSHIP_EVIDENCE_RE.search(excerpt) is not None
    )
    metadata = record.get("metadata") or {}
    canonical_marker = (
        metadata.get(_FACULTY_RESTRICTION_MARKER) is True
        and eligibility.get("international_friendly") == "no"
        and eligibility.get("citizenship_required") is True
    )
    return excerpt_matches or canonical_marker


def faculty_availability_status(record: dict) -> str:
    """Return the precise, source-backed faculty availability constraint.

    The pattern is intentionally narrow. In particular, a statement about not
    accepting *graduate* students alone must not suppress undergraduate
    outreach. Research inactivity is kept distinct from an explicit refusal of
    undergraduate students: both make this matching record non-actionable, but
    the product must never rewrite one claim as the other. Compact markers
    survive removal of raw scrape excerpts and make the decision idempotent.
    """
    if not faculty_contact_claims_unverified(record):
        return "unknown"
    metadata = record.get("metadata") or {}
    canonical_status = metadata.get(_FACULTY_AVAILABILITY_STATUS_MARKER)
    if canonical_status in {
        "not_accepting_undergraduates",
        "research_inactive",
    }:
        return canonical_status
    if (
        canonical_status == "unknown"
        and metadata.get(_FACULTY_AVAILABILITY_SCAN_VERSION_MARKER)
        == _FACULTY_AVAILABILITY_SCAN_VERSION
    ):
        # The current neutralizer already scanned the bounded raw candidates.
        # This matters on the 127k-row faculty hot path: public projection may
        # call the helper again, and a versioned negative result is safe to
        # reuse in O(1). Legacy/stale `unknown` markers have no current version
        # and deliberately fall through to a fresh scan below.
        return "unknown"
    if metadata.get(_FACULTY_NOT_ACCEPTING_MARKER) is True:
        return "not_accepting_undergraduates"
    if metadata.get(_FACULTY_RESEARCH_INACTIVE_MARKER) is True:
        return "research_inactive"
    eligibility = record.get("eligibility") or {}
    candidates = [
        record.get("description_raw"),
        record.get("description_clean"),
        metadata.get("research_areas_raw"),
        eligibility.get("eligibility_text_raw"),
    ]
    # Some legacy faculty collectors preserved a short, source-quoted status
    # only as a keyword (for example UCR's "Not taking students at this time")
    # while replacing the display description with constructed prose. Keep the
    # same narrow regex and a bounded list; do not treat arbitrary student
    # keywords as availability evidence.
    keywords = record.get("keywords")
    if isinstance(keywords, list):
        candidates.extend(keywords[:20])
    if any(
        isinstance(value, str)
        and _faculty_not_accepting_undergraduates(value)
        for value in candidates
    ):
        return "not_accepting_undergraduates"
    if any(
        isinstance(value, str)
        and _FACULTY_RESEARCH_INACTIVE_RE.search(value) is not None
        for value in candidates
    ):
        return "research_inactive"
    return "unknown"


def _faculty_not_accepting_undergraduates(text: str) -> bool:
    """Classify a bounded source excerpt without blocking graduate-only text.

    Faculty pages use several equivalent formulations: ``no longer
    recruiting``, ``does not accept``, ``not taking on``, and ``not accepting
    applications``.  The negative action alone is insufficient; it must govern
    an undergraduate/generic-student/application object.  Removing explicit
    graduate-only noun phrases before looking for a generic ``student`` keeps
    graduate admissions notices from suppressing undergraduate contact.
    """
    for match in _FACULTY_NOT_ACCEPTING_RE.finditer(text):
        target = match.group("object") or ""
        # A later contrast belongs to a different claim: "not accepting
        # graduate students, but welcoming undergraduates" is graduate-only
        # negative evidence and must not be inverted into an undergrad block.
        target = re.split(r"\b(?:but|however|although|while)\b", target, maxsplit=1)[0]
        if _FACULTY_UNDERGRAD_OBJECT_RE.search(target):
            return True

        without_grad_students = _FACULTY_GRAD_ONLY_STUDENT_RE.sub("", target)
        if _FACULTY_STUDENT_OBJECT_RE.search(without_grad_students):
            return True

        if _FACULTY_APPLICATION_OBJECT_RE.search(target):
            # "Not accepting applications this semester" is an attested
            # faculty-profile status.  But an explicitly graduate/PhD/master's
            # applications notice says nothing about undergraduate outreach.
            if _FACULTY_GRAD_TERM_RE.search(target):
                continue
            return True
    return False


def faculty_availability_is_source_negative(record: dict) -> bool:
    """Whether a precise source-backed status blocks opportunity outreach."""
    return faculty_availability_status(record) != "unknown"


def faculty_safe_eligibility(record: dict) -> dict:
    """Return eligibility facts safe for ranking/display at any call boundary.

    The loader normally neutralizes faculty rows once, but route tests, stale
    snapshots and future callers can pass a raw record directly. This pure
    projection is the second belt: research-directory metadata never becomes
    opening eligibility, while a directly quoted citizenship restriction is
    still preserved.
    """
    eligibility = record.get("eligibility") or {}
    if not isinstance(eligibility, dict):
        eligibility = {}
    if not faculty_contact_claims_unverified(record):
        return eligibility

    restriction_is_stated = faculty_restriction_is_source_stated(record)
    restriction_excerpt = eligibility.get("eligibility_text_raw")
    # The loader canonicalizes the restriction into a metadata marker and then
    # drops the raw excerpt, so a second projection of the same record has no
    # excerpt to read. Fall back to the note this branch already preserved
    # instead of stringifying None over the one fact it exists to keep.
    restriction_note = (
        restriction_excerpt
        if isinstance(restriction_excerpt, str) and restriction_excerpt.strip()
        else eligibility.get("work_auth_notes")
    )
    safe = {
        "preferred_year": ["unknown"],
        "min_gpa": None,
        "majors": [],
        "skills_required": [],
        "skills_preferred": [],
        "first_time_researchers": None,
        "international_friendly": "no" if restriction_is_stated else "unknown",
        "citizenship_required": True if restriction_is_stated else None,
        "work_auth_notes": (
            str(restriction_note).strip()[:500]
            if restriction_is_stated and isinstance(restriction_note, str)
            else ""
        ),
    }
    # Keep a present source excerpt available for idempotent re-evaluation;
    # do not add a null schema key to records that never carried one.
    if restriction_excerpt is not None:
        safe["eligibility_text_raw"] = restriction_excerpt
    return safe


def faculty_safe_lab_or_program(record: dict) -> str:
    """Return the lab label unless it is the known constructed template."""
    lab_name = str(record.get("lab_or_program") or "").strip()
    if (
        faculty_contact_claims_unverified(record)
        and re.fullmatch(
            r"Prof\.?\s+.+['’]s Research Group",
            lab_name,
            re.IGNORECASE,
        )
    ):
        return ""
    return lab_name


def _faculty_profile_summary(record: dict) -> str:
    """Build availability-neutral display prose from identity/research facts."""
    name = str(record.get("pi_name") or "this faculty member").strip()
    department = str(record.get("department") or "").strip()
    organization = str(record.get("organization") or "").strip()
    affiliation = ""
    if department and organization:
        affiliation = f" in {department} at {organization}"
    elif department:
        affiliation = f" in {department}"
    elif organization:
        affiliation = f" at {organization}"

    metadata = record.get("metadata") or {}
    research_areas = metadata.get("research_areas_raw")
    if not isinstance(research_areas, str) or not research_areas.strip():
        research_areas = ", ".join(
            value.strip()
            for value in (record.get("keywords") or [])[:6]
            if isinstance(value, str) and value.strip()
        )

    parts = [f"Faculty research profile for {name}{affiliation}."]
    if research_areas:
        parts.append(f"Research areas: {research_areas.strip()[:300]}")
    availability_status = faculty_availability_status(record)
    if availability_status == "not_accepting_undergraduates":
        parts.append(
            "The source profile states that this faculty contact is not currently "
            "accepting undergraduate students or researchers."
        )
    elif availability_status == "research_inactive":
        parts.append(
            "The source profile reports that this faculty member is not currently "
            "conducting active research."
        )
    else:
        parts.append(
            "Contact this faculty member to ask whether undergraduate research "
            "opportunities are currently available."
        )
    return " ".join(parts)


def neutralize_unverified_faculty_claims(record: dict) -> dict:
    """Downgrade known faculty-directory templates in place and return record.

    Source-stated restrictive evidence (international ``no`` or citizenship
    ``True``) is preserved. Every ``faculty_research`` row remains a contact
    profile regardless of generic review flags; a genuinely verified opening
    must use a listing source type instead. Positive opening attributes are
    removed because a directory profile cannot establish availability, pay,
    timing, application ease, or work location.
    The function runs on the freshly parsed in-memory corpus, so legacy shards
    become honest immediately without rewriting the committed 100+ MB dataset
    or waiting for a successful refresh.
    """
    if not faculty_contact_claims_unverified(record):
        return record

    availability_status = faculty_availability_status(record)

    eligibility = record.get("eligibility")
    if isinstance(eligibility, dict):
        restriction_is_stated = faculty_restriction_is_source_stated(record)
        eligibility.update(faculty_safe_eligibility(record))
        metadata = record.setdefault("metadata", {})
        if isinstance(metadata, dict):
            if restriction_is_stated:
                metadata[_FACULTY_RESTRICTION_MARKER] = True
            else:
                metadata.pop(_FACULTY_RESTRICTION_MARKER, None)

    metadata = record.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata[_FACULTY_AVAILABILITY_STATUS_MARKER] = availability_status
        metadata[_FACULTY_AVAILABILITY_SCAN_VERSION_MARKER] = (
            _FACULTY_AVAILABILITY_SCAN_VERSION
        )
        if availability_status == "not_accepting_undergraduates":
            metadata[_FACULTY_NOT_ACCEPTING_MARKER] = True
        else:
            metadata.pop(_FACULTY_NOT_ACCEPTING_MARKER, None)
        if availability_status == "research_inactive":
            metadata[_FACULTY_RESEARCH_INACTIVE_MARKER] = True
        else:
            metadata.pop(_FACULTY_RESEARCH_INACTIVE_MARKER, None)

    # Explicit top-level API contract used by cards/details. This is a status,
    # not a reconstructed opening claim, and is always present on faculty
    # records so stale/partial clients can fail closed without reading metadata.
    record["faculty_availability_status"] = availability_status

    application = record.get("application")
    if isinstance(application, dict):
        # A directory profile may suggest outreach, but it does not establish
        # an application method.  The verified-send-target boundary decides
        # later whether a real email address can be used.
        application["contact_method"] = "unknown"
        application["application_effort"] = "unknown"
        for requirement in (
            "requires_resume",
            "requires_cover_letter",
            "requires_transcript",
            "requires_recommendation",
        ):
            application[requirement] = "unknown"
        # The collector stores the faculty biography page here for historical
        # schema compatibility. It is not an application portal; the top-level
        # profile URL remains available to the UI.
        application["application_url"] = None

    # A faculty affiliation/profile identifies a person and research area. It
    # does not establish a currently available role's location, schedule,
    # compensation, or rolling application status.
    record["on_campus"] = None
    record["remote_option"] = "unknown"
    record["paid"] = "unknown"
    record["compensation_details"] = ""
    record["is_rolling"] = False
    record["duration"] = None
    record["deadline"] = None
    record["deadline_is_estimate"] = None
    record["start_date"] = None
    record["posted_date"] = None
    record["audience"] = "unknown"

    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("deadline_note", None)

    lab_name = faculty_safe_lab_or_program(record)
    if not lab_name and record.get("lab_or_program"):
        record["lab_or_program"] = ""

    summary = _faculty_profile_summary(record)
    pi_name = str(record.get("pi_name") or "").strip()
    if pi_name:
        record["title"] = pi_name
    record["description_raw"] = summary
    record["description_clean"] = summary
    return record


def faculty_safe_public_record(record: dict) -> dict:
    """Copy-on-write faculty projection for routes and stale cached payloads."""
    if not faculty_contact_claims_unverified(record):
        return record
    safe = dict(record)
    for key in ("eligibility", "application", "metadata"):
        value = record.get(key)
        if isinstance(value, dict):
            safe[key] = dict(value)
    neutralize_unverified_faculty_claims(safe)
    # The source excerpt is useful only while canonicalizing a restriction.
    # Public payloads expose the compact provenance marker, never arbitrary
    # scraped eligibility prose that can contain stale opening claims.
    eligibility = safe.get("eligibility")
    if isinstance(eligibility, dict):
        eligibility.pop("eligibility_text_raw", None)
    return safe


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
