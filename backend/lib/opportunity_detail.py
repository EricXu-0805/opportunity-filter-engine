"""Per-field detail truth for one opportunity (M03).

The detail page answers ten questions about a record — school, department,
professor or lab, research content, eligibility, required skills, timing,
funding, location and application method. Before this module each answer was
whatever value happened to sit in the flat record, and the flat record cannot
tell three very different states apart:

* **source** — a collector read the value off the page it links to;
* **inferred** — we produced it: a keyword scan, a model, a program policy, an
  estimate, or a constant the collector writes on every record it emits;
* **unknown** — nobody said.

The third state is the one the flat record loses most often. A collector that
writes ``citizenship_required: False`` on every row turns "the page said
nothing" into "no citizenship requirement", and a UI then tells an
international student they may apply. So this module does not trust a value
because it is present. Every facet is classified by an explicit rule — an
inference stamp (``src.evidence.stamp_inferred``), or a collector template
registered below — and anything no rule vouches for is ``unknown``.

Two invariants the tests hold this module to:

1. **Values are read from the public projection, never from the canonical
   record.** ``project_public_opportunity_payload`` has already stripped offer
   terms from unverified kinds, neutralized faculty-directory templates and
   cleared the application URL on historical targets. Reading the canonical
   record here would quietly re-publish all of it. The canonical record is
   consulted only for *how* a value was produced (stamps, collector name).
2. **Nothing collapses.** unknown is never rendered as false, unpaid, not
   eligible, or "no deadline". An absent deadline is ``unknown``; an unknown
   pay value is ``unknown``; ``citizenship_required: False`` counts as a
   stated "not required" only when the same record states that international
   students are welcome.

The wire shape is deliberately boring so a client cannot misread it::

    "detail_fields": {
      "version": "m03-v1",
      "fields": {
        "<field>": {
          "state": "source" | "inferred" | "unknown",
          "explicit": {"<facet>": <value>, ...},
          "inferred": {"<facet>": {"value": <value>, "basis": "<basis>"}, ...},
          "unknown": ["<facet>", ...],
          "provenance": {"source_url": str | null, "observed_at": str | null}
        }
      }
    }

``explicit`` / ``inferred`` are the ``<field>_explicit`` / ``<field>_inferred``
split the M03 brief asks for (``eligibility.explicit`` is eligibility_explicit,
``research_content.inferred.research_areas`` is research_areas_inferred). A
facet may sit in ``explicit`` and ``inferred`` at once (a professor's stated
research text beside topic tags we derived); it is in ``unknown`` only when it
is in neither.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

# Module import, not a name import: the public projector imports this module
# for `paid_basis`/`location_basis`, and a name import would fail on whichever
# side of that cycle loads second.
from backend.lib import public_projection
from src.evidence import CAMPUS_PROGRAM_SUFFIXES, inferred_method, is_configured_program, record_kind

DETAIL_FIELDS_VERSION = "m03-v1"

DETAIL_FIELD_NAMES = (
    "school",
    "department",
    "professor_or_lab",
    "research_content",
    "eligibility",
    "required_skills",
    "timing",
    "funding",
    "location",
    "application_method",
)

# Every facet each field can report, in display order. A facet missing from a
# record is reported under `unknown` — the list is what makes "not provided"
# a statement rather than an absence the UI has to notice.
FIELD_FACETS: dict[str, tuple[str, ...]] = {
    "school": ("institution",),
    "department": ("department",),
    "professor_or_lab": ("principal_investigator", "faculty_rank", "lab_or_program"),
    "research_content": ("research_areas",),
    "eligibility": (
        "class_year",
        "majors",
        "min_gpa",
        "international_students",
        "citizenship",
        "work_authorization_notes",
    ),
    # `required` is only ever a source-backed facet. An inferred skill list is
    # reported as `mentioned`, never as `required`: a skill our tagger read out
    # of prose is not a hard requirement of the program, and naming the facet
    # `required` would make it one for every consumer of the wire.
    "required_skills": ("required", "preferred", "mentioned"),
    "timing": ("deadline", "rolling", "application_window", "start_date", "duration", "posted_date"),
    "funding": ("paid", "compensation"),
    "location": ("location", "remote_option"),
    "application_method": ("application_url", "contact_method", "requirements", "effort"),
}

# Public names for how an inferred value was produced. Collector method names
# ("rule:federal_org", "llm:bio_extraction") stay server-side, exactly as the
# target-truth evidence keys do: a client that branched on them would be
# coupled to one collector's implementation.
BASIS_TEXT_SCAN = "text_scan"             # keyword/regex read of page prose
BASIS_MODEL = "model_extraction"          # LLM read of page prose
BASIS_ENRICHMENT = "external_enrichment"  # matched third-party record (OpenAlex)
BASIS_ESTIMATE = "estimate"               # computed from another date/value
BASIS_PROGRAM_POLICY = "program_policy"   # a published rule of the funding program
BASIS_COLLECTOR_DEFAULT = "collector_default"  # a constant the collector writes on every row
BASIS_DERIVED = "derived_from_source"     # restated from a different source fact

_STAMP_PREFIX_BASIS = {
    "rule": BASIS_TEXT_SCAN,
    "llm": BASIS_MODEL,
    "derived": BASIS_ENRICHMENT,
    "estimate": BASIS_ESTIMATE,
    "policy": BASIS_PROGRAM_POLICY,
    "default": BASIS_COLLECTOR_DEFAULT,
}

STATE_SOURCE = "source"
STATE_INFERRED = "inferred"
STATE_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Collector template registry
# ---------------------------------------------------------------------------
# Values a collector writes as a constant rather than reading them off the
# page. Each entry was read out of the collector's own record builder; the
# comment names the line of reasoning, not just the file. Registered here so a
# legacy record degrades at serve time without a re-scrape, and so the
# backfill report can count what still carries one.

# Sources whose `location` is read off the posting itself. Every other
# collector writes its host school's city — `faculty_graph`, `campus_graph`,
# `ucb_common`, `ucb_campus`, `ucsb_urca_projects`, `uiuc_faculty` — which is
# where the institution is, not where the work happens. A remote internship
# posted by a Berkeley lab is not in Berkeley.
_LOCATION_FROM_POSTING = frozenset({"simplify_internships", "handshake", "manual", "uiuc_sro"})
# Collectors that parse a location when the page has one and fall back to the
# campus otherwise. Only the fallback value is the template.
_LOCATION_CAMPUS_FALLBACK = {
    "ucb_urap_projects": "Berkeley, CA",
    "uiuc_our_rss": "Champaign, IL",
}
# NSF REU records carry the awardee institution's city. REU Sites do run at the
# awardee, so this is a reasonable reading, but it is a reading of the award
# record, not a statement on a posting.
_LOCATION_FROM_AWARD = frozenset({"nsf_reu"})
# Remote/on-site status parsed from the posting.
_REMOTE_FROM_POSTING = frozenset({"simplify_internships", "handshake", "manual"})

# Class-year lists written as defaults. The four-year list is what every
# program collector writes when the page names no year ("open to
# undergraduates" is not a class-year restriction, and it is not a statement
# that all four are welcome either). The three-year lists are the Simplify /
# Handshake / UCB-campus template and the NSF REU template.
_TEMPLATE_CLASS_YEARS = frozenset({
    ("freshman", "junior", "senior", "sophomore"),
    ("junior", "senior", "sophomore"),
    ("freshman", "junior", "sophomore"),
})

# Paid values a collector hard-codes. Simplify writes "stipend" on every
# corporate internship because its source feed has no compensation field (the
# DQ-3 comment in the collector says as much); NSF REU writes "yes" because the
# REU solicitation mandates a stipend. Both are reasonable expectations and
# both are ours, not the posting's.
_PAID_TEMPLATES = {
    "simplify_internships": ("stipend", BASIS_COLLECTOR_DEFAULT),
    "nsf_reu": ("yes", BASIS_PROGRAM_POLICY),
}
# Compensation prose a collector writes as a constant.
_COMPENSATION_TEMPLATES = {
    "nsf_reu": BASIS_PROGRAM_POLICY,  # "NSF-funded stipend (typically $6,000-$7,000 …)"
}
# Timing constants. NSF records carry the AWARD start date (not the program's
# start) and a fixed "Summer (8-10 weeks)" duration.
_START_DATE_TEMPLATES = {"nsf_reu": BASIS_ESTIMATE}
_DURATION_TEMPLATES = {"nsf_reu": BASIS_PROGRAM_POLICY}
_REMOTE_TEMPLATES = {"nsf_reu": BASIS_PROGRAM_POLICY}  # "no": REU Sites are residential

# International-student answers restated from a different source fact.
# Simplify states a SPONSORSHIP status; "Does Not Offer Sponsorship" became
# international_friendly="no" even though CPT/OPT still apply to internships.
# NSF REU writes "no" from the solicitation's citizenship rule.
_INTL_TEMPLATES = {
    "simplify_internships": BASIS_DERIVED,
    "nsf_reu": BASIS_PROGRAM_POLICY,
    # Restated from the SRO page's own "Citizenship Requirement" field.
    "uiuc_sro": BASIS_DERIVED,
}
_CITIZENSHIP_TEMPLATES = {"nsf_reu": BASIS_PROGRAM_POLICY}
# Collectors that read citizenship off a labelled field, so a False is the
# page's "No Citizenship Requirements" rather than a template.
_CITIZENSHIP_FROM_FIELD = frozenset({"uiuc_sro"})
# SRO work-authorization notes written before the collector read that field
# were ±50-character keyword windows joined by " | ", or windows that start
# mid-word and run the field's label into its value. Neither is a statement.
_SRO_NOTE_WINDOW_RE = re.compile(r" \| |Citizenship Requirement (?:US|No)\b")

# The SRO database states each record on its own detail page; the record's
# `source_url` is the paginated list it was found on, which moves as rows are
# added and states none of the eligibility, pay or timing fields.
_DETAIL_PAGE_SOURCES = frozenset({"uiuc_sro"})
# Keywords that are the source's own topic list: the SRO "Research Area".
_KEYWORDS_FROM_SOURCE = frozenset({"uiuc_sro"})

# Sources whose eligibility lists (majors, skills) a person typed in from one
# posting: manual rows. Every other collector fills them from a keyword bank
# or a category map. Campus program specs (campus_graph, ucb_campus) were
# treated as curated until a 2026-10-09 check of 31 live program pages found
# none of 12 configured major lists on the page: they are configuration
# (`is_configured_program`), reported as a collector default.
_CURATED_SOURCES = frozenset({"manual"})

# Application requirement flags are only ever typed by a person for manual
# rows. Simplify and NSF write requires_resume="yes" on every record.
_REQUIREMENT_EXPLICIT_SOURCES = frozenset({"manual"})
_REQUIREMENT_FIELDS = (
    ("requires_resume", "resume"),
    ("requires_cover_letter", "cover_letter"),
    ("requires_transcript", "transcript"),
    ("requires_recommendation", "recommendation"),
)

# NSF records put the NSF program element ("REU Sites") in `department`. It is
# the funding program, not an academic department.
_DEPARTMENT_NOT_A_DEPARTMENT = frozenset({"nsf_reu"})

_ROLLING_NOTE_RE = re.compile(r"\brolling\b", re.IGNORECASE)
_ISO_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_MAX_TEXT = 600
_MAX_LIST = 20


def _is_curated_source(source: str) -> bool:
    return source in _CURATED_SOURCES


def _configured_basis(canonical: dict) -> str | None:
    """The basis for a value a campus program spec wrote, or None."""
    return BASIS_COLLECTOR_DEFAULT if is_configured_program(canonical) else None


def _collector_constant_keywords(canonical: dict) -> set[str]:
    """Keywords the campus collectors append to every row they emit.

    Each appends its own source type ("program", "lab", "announcement"), and a
    discovered row carries only that plus "undergraduate research". Neither is
    a research topic.
    """
    constants = {
        value.casefold() for value in (canonical.get("campus_source_type"), canonical.get("ucb_source_type"))
        if isinstance(value, str) and value
    }
    if constants and _dict(canonical.get("metadata")).get("discovered"):
        constants.add("undergraduate research")
    return constants


def class_years_are_template(years: object) -> bool:
    """Whether a class-year list is one of the defaults collectors write."""
    values = [y.lower() for y in _str_list(years)]
    return tuple(sorted(y for y in values if y != "unknown")) in _TEMPLATE_CLASS_YEARS


def pi_name_basis(canonical: dict) -> str | None:
    """Why a record's pi_name is not a name read off its page, or None.

    Shared with the public projector, which removes any pi_name that has one.
    """
    stamped = _basis_for(canonical, "pi_name")
    if stamped is not None:
        return stamped
    # campus_graph and ucb_campus write pi_name None on every row, configured
    # or discovered; a name there was scraped later by pi_enricher's page
    # scan — 19 of 19 on the 2026-10-09 corpus are headings or navigation
    # ("Team ProjectsGroup Conference Travel").
    if str(canonical.get("source") or "").endswith(CAMPUS_PROGRAM_SUFFIXES) and canonical.get("pi_name"):
        return BASIS_TEXT_SCAN
    return None


# ---------------------------------------------------------------------------
# Value hygiene
# ---------------------------------------------------------------------------

def _text(value: object) -> str | None:
    """A trimmed, capped string, or None for anything empty or non-string.

    ``"unknown"`` is the corpus's own spelling of unknown and is treated as
    absent: it must land in the unknown bucket, not be displayed as a value.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.lower() in {"unknown", "n/a", "none", "null"}:
        return None
    return text[:_MAX_TEXT]


def _str_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text is None:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:120])
        if len(out) >= _MAX_LIST:
            break
    return out


def _date(value: object) -> str | None:
    text = _text(value)
    if text is None or not _ISO_PREFIX_RE.match(text):
        return None
    return text[:32]


def _basis_for(canonical: dict, path: str) -> str | None:
    """The public basis of an inference stamp on ``path``, or None if unstamped."""
    method = inferred_method(canonical, path)
    if method is None:
        return None
    prefix = method.split(":", 1)[0]
    # An unrecognised prefix is still an inference: it must never read as
    # source-backed just because this table has not heard of it yet.
    return _STAMP_PREFIX_BASIS.get(prefix, BASIS_TEXT_SCAN)


# ---------------------------------------------------------------------------
# Field builder
# ---------------------------------------------------------------------------

class _Field:
    """Accumulates one field's facets into the source / inferred buckets."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.explicit: dict[str, object] = {}
        self.inferred: dict[str, dict] = {}

    def source(self, facet: str, value: object) -> None:
        if value in (None, "", [], {}):
            return
        self.explicit[facet] = value

    def infer(self, facet: str, value: object, basis: str) -> None:
        if value in (None, "", [], {}):
            return
        self.inferred[facet] = {"value": value, "basis": basis}

    def put(self, facet: str, value: object, basis: str | None) -> None:
        """Source when no basis vouches for an inference, inferred otherwise."""
        if basis is None:
            self.source(facet, value)
        else:
            self.infer(facet, value, basis)

    def build(self, provenance: dict) -> dict:
        facets = FIELD_FACETS[self.name]
        explicit = {f: self.explicit[f] for f in facets if f in self.explicit}
        # A facet may carry both: the page's research text AND topic tags we
        # derived from a matched publication record are two different claims,
        # and keeping both is the point of the split. Unknown means neither.
        inferred = {f: self.inferred[f] for f in facets if f in self.inferred}
        unknown = [f for f in facets if f not in explicit and f not in inferred]
        if explicit:
            state = STATE_SOURCE
        elif inferred:
            state = STATE_INFERRED
        else:
            state = STATE_UNKNOWN
        return {
            "state": state,
            "explicit": explicit,
            "inferred": inferred,
            "unknown": unknown,
            "provenance": provenance,
        }


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _school(payload: dict) -> _Field:
    field = _Field("school")
    field.source("institution", _text(payload.get("organization")))
    return field


def _department(payload: dict, canonical: dict, source: str) -> _Field:
    field = _Field("department")
    if source in _DEPARTMENT_NOT_A_DEPARTMENT:
        return field
    department = _text(payload.get("department"))
    if canonical.get("ucb_source_type") and _dict(canonical.get("metadata")).get("discovered"):
        # ucb_campus gives a discovered page its source's first program's
        # department: an astronomy jobs page reads "Chemistry".
        field.infer("department", department, BASIS_COLLECTOR_DEFAULT)
    else:
        field.source("department", department)
    return field


def _professor_or_lab(payload: dict, canonical: dict) -> _Field:
    field = _Field("professor_or_lab")
    # The projector removes a derived pi_name outright (every derived name on
    # the corpus is an institution or a noun), so a pi_name that survives the
    # projection is one a collector read as a person.
    if pi_name_basis(canonical) is None:
        field.source("principal_investigator", _text(payload.get("pi_name")))
    field.source("faculty_rank", _text(_dict(payload.get("metadata")).get("faculty_title")))
    lab = _text(payload.get("lab_or_program"))
    # Simplify and Handshake copy the employer into lab_or_program. A company
    # is not a lab, and repeating the organization here says nothing new.
    if lab and lab.casefold() != (_text(payload.get("organization")) or "").casefold():
        field.source("lab_or_program", lab)
    return field


def _research_content(payload: dict, canonical: dict, kind: str, source: str) -> _Field:
    field = _Field("research_content")
    metadata = _dict(payload.get("metadata"))
    stated = _text(metadata.get("research_areas_raw"))
    if stated is None:
        areas = payload.get("research_areas")
        stated = _text(areas) if isinstance(areas, str) else (", ".join(_str_list(areas)) or None)
    constants = _collector_constant_keywords(canonical)
    keywords = [k for k in _str_list(payload.get("keywords")) if k.casefold() not in constants]
    keyword_basis = _basis_for(canonical, "keywords")
    if keyword_basis is None and kind != "faculty_contact" and source not in _KEYWORDS_FROM_SOURCE:
        # Listing keywords are ours on every other collector: Simplify expands
        # its category through a map, NSF and the normalizer run a keyword
        # bank, campus program specs carry tags a person typed. Only the SRO's
        # "Research Area" field is a topic list the source published.
        keyword_basis = BASIS_TEXT_SCAN
    if stated:
        field.source("research_areas", stated)
    elif keywords and keyword_basis is None:
        # Faculty keywords are curated off the profile or split from the
        # scraped research text — the page's own words.
        field.source("research_areas", keywords)
    if keywords and keyword_basis is not None:
        field.infer("research_areas", keywords, keyword_basis)
    return field


def _eligibility(payload: dict, canonical: dict, source: str) -> _Field:
    field = _Field("eligibility")
    elig = _dict(payload.get("eligibility"))
    curated = _is_curated_source(source)
    configured = _configured_basis(canonical)

    years = [y.lower() for y in _str_list(elig.get("preferred_year"))]
    years = [y for y in years if y != "unknown"]
    if years:
        basis = _basis_for(canonical, "eligibility.preferred_year")
        if basis is None and tuple(sorted(years)) in _TEMPLATE_CLASS_YEARS:
            pass  # a default list: no class-year statement was read. Unknown.
        else:
            field.put("class_year", years, basis or configured)

    majors = _str_list(elig.get("majors"))
    if majors:
        basis = _basis_for(canonical, "eligibility.majors") or configured
        if basis is None and not curated:
            basis = BASIS_TEXT_SCAN
        field.put("majors", majors, basis)

    gpa = elig.get("min_gpa")
    if isinstance(gpa, int | float) and not isinstance(gpa, bool) and 0 < gpa <= 5:
        field.source("min_gpa", float(gpa))

    intl = _text(elig.get("international_friendly"))
    intl_explicit = False
    if intl in {"yes", "no"}:
        basis = (_basis_for(canonical, "eligibility.international_friendly")
                 or _INTL_TEMPLATES.get(source) or configured)
        field.put("international_students", intl, basis)
        intl_explicit = basis is None

    citizenship = elig.get("citizenship_required")
    citizenship_basis = _basis_for(canonical, "eligibility.citizenship_required")
    if citizenship is True:
        basis = citizenship_basis or _CITIZENSHIP_TEMPLATES.get(source) or configured
        field.put("citizenship", "required", basis)
    elif citizenship is False and citizenship_basis is None and (
        (intl_explicit and intl == "yes") or source in _CITIZENSHIP_FROM_FIELD
    ):
        # "Not required" is a positive claim. The evidence for it is a stated
        # welcome to international students or a citizenship field that says
        # so; a bare False is the template most collectors write when the
        # page is silent.
        field.source("citizenship", "not_required")

    notes = _text(elig.get("work_auth_notes"))
    if not (source == "uiuc_sro" and notes and _SRO_NOTE_WINDOW_RE.search(notes)):
        field.source("work_authorization_notes", notes)
    return field


def _required_skills(payload: dict, canonical: dict, source: str) -> _Field:
    field = _Field("required_skills")
    elig = _dict(payload.get("eligibility"))
    required = _str_list(elig.get("skills_required"))
    preferred = _str_list(elig.get("skills_preferred"))
    required_basis = _basis_for(canonical, "eligibility.skills_required")
    preferred_basis = _basis_for(canonical, "eligibility.skills_preferred")
    if not _is_curated_source(source):
        # Outside hand-curated rows every skill list is a keyword-bank or
        # tagger read of prose, stamped or not (the tagger's pre-stamp runs
        # left ~2,400 unstamped lists on the internship corpus alone).
        required_basis = required_basis or BASIS_TEXT_SCAN
        preferred_basis = preferred_basis or BASIS_TEXT_SCAN
    if required and required_basis is None:
        field.source("required", required)
    if preferred and preferred_basis is None:
        field.source("preferred", preferred)
    mentioned: list[str] = []
    basis: str | None = None
    for skills, skill_basis in ((required, required_basis), (preferred, preferred_basis)):
        if skills and skill_basis is not None:
            basis = basis or skill_basis
            for skill in skills:
                if skill.casefold() not in {m.casefold() for m in mentioned}:
                    mentioned.append(skill)
    if mentioned and basis is not None:
        field.infer("mentioned", mentioned[:_MAX_LIST], basis)
    return field


def _timing(payload: dict, canonical: dict, source: str) -> _Field:
    field = _Field("timing")
    deadline = _date(payload.get("deadline"))
    if deadline:
        basis = _basis_for(canonical, "deadline")
        if basis is None and payload.get("deadline_is_estimate") is True:
            basis = BASIS_ESTIMATE
        field.put("deadline", deadline, basis)
    note = _text(_dict(payload.get("metadata")).get("deadline_note"))
    if note:
        configured = _configured_basis(canonical)
        field.put("application_window", note, configured)
        # Rolling is claimed only on a source note that says so. `is_rolling`
        # is a collector default (True on every Simplify and campus-graph row,
        # False on every faculty row) and decides nothing either way.
        if _ROLLING_NOTE_RE.search(note):
            field.put("rolling", True, configured)
    start = _date(payload.get("start_date"))
    if start:
        field.put("start_date", start, _START_DATE_TEMPLATES.get(source))
    duration = _text(payload.get("duration"))
    if duration:
        field.put("duration", duration, _DURATION_TEMPLATES.get(source))
    field.source("posted_date", _date(payload.get("posted_date")))
    return field


def _funding(payload: dict, canonical: dict, source: str) -> _Field:
    field = _Field("funding")
    paid = _text(payload.get("paid"))
    if paid in {"yes", "stipend", "no"}:
        field.put("paid", paid, paid_basis(canonical, paid))
    compensation = _text(payload.get("compensation_details"))
    if compensation:
        field.put("compensation", compensation,
                  _COMPENSATION_TEMPLATES.get(source) or _configured_basis(canonical))
    return field


def paid_basis(canonical: dict, paid: object) -> str | None:
    """Why ``paid`` is not source-backed, or None when it is.

    Shared with the public projector so the header badge and the detail facts
    cannot disagree about whether a pay value is the posting's or ours.
    """
    stamped = _basis_for(canonical, "paid")
    if stamped is not None:
        return stamped
    template = _PAID_TEMPLATES.get(str(canonical.get("source") or ""))
    if template is not None and paid == template[0]:
        return template[1]
    return _configured_basis(canonical)


def location_basis(canonical: dict, location: object) -> str | None:
    """How a non-empty ``location`` was produced, or None when the posting stated it.

    ``"institution"`` means the collector wrote its host school's city. The
    detail model reports that as unknown — the school's location is not the
    opportunity's — and the projector publishes it as ``location_attribution``
    so the header and cards stop printing it as where the work happens.
    """
    source = str(canonical.get("source") or "")
    if source in _LOCATION_FROM_POSTING:
        return None
    fallback = _LOCATION_CAMPUS_FALLBACK.get(source)
    if fallback is not None:
        return "institution" if location == fallback else None
    if source in _LOCATION_FROM_AWARD:
        return BASIS_DERIVED
    return "institution"


def _location(payload: dict, canonical: dict, source: str) -> _Field:
    field = _Field("location")
    location = _text(payload.get("location"))
    if location:
        basis = location_basis(canonical, location)
        if basis != "institution":
            field.put("location", location, basis)
    remote = _text(payload.get("remote_option"))
    if remote in {"remote", "hybrid", "no"}:
        if source in _REMOTE_FROM_POSTING:
            field.source("remote_option", remote)
        elif source in _REMOTE_TEMPLATES:
            field.infer("remote_option", remote, _REMOTE_TEMPLATES[source])
    return field


def _application_method(payload: dict, source: str) -> _Field:
    field = _Field("application_method")
    app = _dict(payload.get("application"))
    # Already cleared by the projector on anything non-actionable, and run
    # through the public URL boundary.
    field.source("application_url", public_projection.safe_public_http_url(app.get("application_url")))
    contact = _text(app.get("contact_method"))
    if contact:
        # No collector reads a contact method off the page; each writes its
        # own constant ("online", "website") describing where its URL points.
        field.infer("contact_method", contact, BASIS_COLLECTOR_DEFAULT)
    requirements: list[str] = []
    for key, label in _REQUIREMENT_FIELDS:
        if _text(app.get(key)) == "yes":
            requirements.append(label)
    if requirements and source in _REQUIREMENT_EXPLICIT_SOURCES:
        field.source("requirements", requirements)
    effort = _text(app.get("application_effort"))
    # "medium" is the default every collector and the normalizer write. Any
    # other value was computed from the requirement flags above.
    if effort in {"low", "high"}:
        field.infer("effort", effort, BASIS_ESTIMATE)
    return field


def _provenance(payload: dict, source: str, *, observed_key: str | None = None) -> dict:
    """Where a field's value was read, and when we last saw it there.

    ``observed_at`` prefers a field-specific stamp, then the truth envelope's
    ``verified_at`` — the last time the collector loaded the page and checked
    it. Not ``last_seen_at``: that is the last run that listed the record,
    whether or not its page loaded (the loader drops it from the served corpus
    anyway). Never synthesized: absent everywhere means null.
    """
    metadata = _dict(payload.get("metadata"))
    truth = _dict(payload.get("target_truth"))
    observed = None
    if observed_key:
        observed = _date(metadata.get(observed_key))
    observed = observed or _date(truth.get("verified_at"))
    first, second = ("url", "source_url") if source in _DETAIL_PAGE_SOURCES else ("source_url", "url")
    return {
        "source_url": public_projection.safe_public_http_url(payload.get(first))
        or public_projection.safe_public_http_url(payload.get(second)),
        "observed_at": observed,
    }


# Bases no reading of the page produced: a value the collector writes itself,
# or one a funding program's rules fix. A field holding only these was not
# observed anywhere, whenever its page was last loaded.
_UNOBSERVED_BASES = frozenset({BASIS_COLLECTOR_DEFAULT, BASIS_PROGRAM_POLICY})


def _field_provenance(built: dict, provenance: dict) -> dict:
    inferred = built["inferred"]
    if not built["explicit"] and inferred and all(v["basis"] in _UNOBSERVED_BASES for v in inferred.values()):
        return {**provenance, "observed_at": None}
    return provenance


def build_detail_fields(payload: dict, canonical: dict) -> dict:
    """The M03 detail envelope for one public payload.

    ``payload`` must already have passed ``project_public_opportunity_payload``
    (values are read from it); ``canonical`` is the corpus record it was
    projected from (consulted only for stamps and the collector name). Pure and
    copy-safe: neither argument is mutated.
    """
    if not isinstance(payload, dict) or not isinstance(canonical, dict):
        raise TypeError("detail fields need a payload dict and its canonical record")
    source = str(canonical.get("source") or "")
    kind = record_kind(canonical)
    base = _provenance(payload, source)
    research_provenance = _provenance(payload, source, observed_key="research_areas_verified_at")
    fields = (
        _school(payload),
        _department(payload, canonical, source),
        _professor_or_lab(payload, canonical),
        _research_content(payload, canonical, kind, source),
        _eligibility(payload, canonical, source),
        _required_skills(payload, canonical, source),
        _timing(payload, canonical, source),
        _funding(payload, canonical, source),
        _location(payload, canonical, source),
        _application_method(payload, source),
    )
    built = {f.name: f.build(research_provenance if f.name == "research_content" else base) for f in fields}
    for field in built.values():
        field["provenance"] = _field_provenance(field, field["provenance"])
    return {"version": DETAIL_FIELDS_VERSION, "fields": built}


def unknown_facets(detail_fields: dict) -> Iterable[str]:
    """Dotted ``field.facet`` names reported unknown — for audits and backfill counts."""
    for name, field in (detail_fields.get("fields") or {}).items():
        for facet in field.get("unknown") or ():
            yield f"{name}.{facet}"
