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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

from src.contact_instructions import SOURCE_KEY as CONTACT_SOURCE_KEY
from src.contact_instructions import _source_time as contact_source_time
from src.contact_instructions import _url as contact_url

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
    meta = record.get("metadata")
    stamps = meta.get(INFERRED_FIELDS_KEY) if isinstance(meta, dict) else None
    # Malformed legacy shapes (metadata or the stamp map as a string) carry no
    # readable stamp: None, the same answer as an unstamped record.
    method = stamps.get(field) if isinstance(stamps, dict) else None
    return method if isinstance(method, str) and method else None


def is_inferred(record: dict, field: str) -> bool:
    """True when the current value of ``field`` carries an inference stamp."""
    return inferred_method(record, field) is not None


def is_read_off_the_page(record: dict, field: str) -> bool:
    """True when ``field`` was inferred by reading the source text.

    The stamp namespace separates two very different claims. ``rule:``,
    ``llm:``, ``derived:`` and ``estimate:`` all mean a scan of the page
    produced the value, so it is only as good as the sentence it came from —
    "in many cases, funding or a stipend" becomes ``paid: yes``. ``policy:``
    means a published requirement of the funding program produced it: an NSF
    REU Site must pay a stipend because the solicitation says so, which is a
    fact about the program type rather than a reading of its page. Surfaces
    that hedge a guess should hedge the first kind and not the second.
    """
    method = inferred_method(record, field)
    return method is not None and not method.startswith("policy:")


# Collector constants that read like source statements (M03). Keyed by
# collector, then stamp path, to (template value, method). Stamped at corpus
# load — the neutralizer pattern — so the committed shards become honest
# without a re-scrape, and every stamp-aware reader (ranker fit sentences,
# the public projector's attribution flags) agrees at once.
#
# Deliberately narrow. Simplify writes paid="stipend" on every internship
# because its feed has no pay field (the collector's DQ-3 comment); the ranker
# then told 6,096 students "Includes stipend". Stamping it `default:` keeps the
# pay score (the expectation is reasonable) and drops the sentence (it is not
# the posting's). Other collector templates that stamp-aware ranking reads —
# majors, skills, class years — would move scores, so they are classified for
# display only by backend.lib.opportunity_detail, not stamped here.
_COLLECTOR_TEMPLATE_STAMPS: dict[str, dict[str, tuple[object, str]]] = {
    "simplify_internships": {
        "paid": ("stipend", "default:simplify_feed_has_no_pay_field"),
    },
}

# Program specs in the campus_graph and ucb_campus configs. A person typed the
# pay, international answer and citizenship rule into the config once, and
# every refresh re-emits them without reading the page again. Checked against
# 31 live program pages on 2026-10-09, 10 of 33 configured facets were stated
# there and 5 were contradicted (a "stipend" that is a $500 expense grant;
# "international students: yes" on a program for research abroad). So a
# configured value is ours unless the page text the row carries states it
# (`configured_fact` below): stamped like the Simplify stipend when it does
# not, while majors and class years are classified for display only, by the
# rule above.
CAMPUS_PROGRAM_SUFFIXES = ("_research_programs", "_labs", "_external_research")
_CONFIGURED_PROGRAM_STAMPS = {
    "paid": ("paid", lambda value: value in {"yes", "stipend", "no"}),
    "eligibility.international_friendly": ("international_students", lambda value: value in {"yes", "no"}),
    "eligibility.citizenship_required": ("citizenship", lambda value: value is True or value is False),
}
CONFIGURED_PROGRAM_METHOD = "default:configured_program"


def is_configured_program(record: dict) -> bool:
    """A campus_graph / ucb_campus row built from a program spec in the
    collector config, rather than a page the crawl discovered."""
    source = record.get("source")
    metadata = record.get("metadata")
    return (isinstance(source, str) and source.endswith(CAMPUS_PROGRAM_SUFFIXES)
            and not (isinstance(metadata, dict) and metadata.get("discovered")))


# The owner's rule (2026-10-09): where the program page states a configured
# value, show it as the page's, in the page's own words; where it does not, it
# is our inference. The page text a configured row carries is of two kinds,
# both read off a page a crawl loaded:
#
# * the excerpt the crawl appends to its description after
#   CAPTURED_PAGE_MARKER (`_readable_excerpt`: the first 400 characters of the
#   main content of the row's own `source_url`, rewritten by each run that
#   loads the page, which also sets `last_verified`, and dropped by one that
#   does not);
# * the passages the condition capture kept from that page
#   (`metadata.contact_instruction_sources`: whole paragraphs, each with the
#   URL it was read at and when). The cold-email conditions quote the same
#   passages (`backend.lib.email_target_conditions`).
#
# `configured_fact` reads them one sentence at a time, the excerpt first:
#
# * stated: one sentence holds the value's own terms where the facet's words
#   make them a term of this program ("receive a stipend"; "international
#   students are eligible"; "open to Biology majors"; every word of a free
#   text value beside a pay or timing word). That sentence is the quote.
# * contradicted: a sentence says what the value excludes ("positions are
#   unpaid" against a stipend, "must be U.S. citizens" against an
#   international "yes", "open to all majors" against a major list, a
#   deadline on another day). It wins over a stating sentence: the page then
#   says both, and that is for a person to read
#   (`scripts/configured_facts_report.py` lists them).
# * unstated: anything else. That includes a sentence that hedges ("may",
#   "if", "subject to", "typically"), one that says nothing about this
#   program (a legend, "$$ = Stipend provided"; a pointer, "check each
#   program's website for details such as stipend amounts"; "funding for
#   unpaid internships"), and one that cannot be read whole: over 300
#   characters, which is navigation run together; the excerpt's last
#   sentence when the 400-character cut ended it, since the words cut off may
#   be the ones that qualify it; "rising juniors", which names the year after
#   the one a student is in.
#
# Exact terms only. "Scholarship" does not state "stipend", "International"
# alone does not state that international students may apply, and
# "Biochemistry" does not state "Chemistry". The one normalization is spelling
# that cannot change the meaning: "Jan" is "January", "$5,000" is "$5000",
# "&" is "and".
CAPTURED_PAGE_MARKER = "From the program page:"
# Where the campus collectors cut that text: `_readable_excerpt`'s limit, and
# their description cap (`_DESC_CAP`). An excerpt at either length was cut.
EXCERPT_LIMIT = 400
DESCRIPTION_LIMIT = 1500
FACT_STATED = "stated"
FACT_UNSTATED = "unstated"
FACT_CONTRADICTED = "contradicted"
_MAX_QUOTE = 300

# The record path of each configured facet, by its detail-fields facet name.
CONFIGURED_FACT_PATHS = {
    "paid": "paid",
    "compensation": "compensation_details",
    "international_students": "eligibility.international_friendly",
    "citizenship": "eligibility.citizenship_required",
    "majors": "eligibility.majors",
    "class_year": "eligibility.preferred_year",
    "application_window": "metadata.deadline_note",
}


@dataclass(frozen=True)
class ConfiguredFact:
    """One configured value checked against the page text its row carries.

    ``quote`` is the page's sentence: the one that states the value, or the
    one that contradicts it. None when the page text says neither.
    ``source_url`` and ``observed_at`` say where and when that sentence was
    read: the row's page and `last_verified` for the excerpt, the passage's
    own URL and `checked_at` for a captured passage.
    """

    state: str
    quote: str | None = None
    source_url: str | None = None
    observed_at: str | None = None


_UNSTATED = ConfiguredFact(FACT_UNSTATED)

# A sentence ends at a line break, a bullet or pipe, a semicolon, or a full
# stop after a lowercase letter or digit that starts a capitalised word, so
# "U.S. citizens" and "e.g. biology" stay whole. The excerpt is flattened page
# text, so a heading ("SUMMER RESEARCH GRANTS (SURG)") or a field label
# ("Deadline:") also ends one: without that, a menu run into the first
# sentence reads as part of it. A heading stops before an uppercase label,
# so "FELLOWSHIP DEADLINE: February 14" keeps the label with its date.
_SENTENCE_BREAK_RE = re.compile(r"[\n\r•·|]+|(?<=;)\s+|(?<=[a-z0-9)][.!?])\s+(?=[\"“(]?[A-Z0-9])")
_HEADING_RE = re.compile(r"\b(?:[A-Z]{2,}[\s&/-]+){2,}[A-Z]{2,}\b(?!:)(?:\s*\([A-Z]{2,}\))?")
# A capitalised word, and at most one more, before a colon: "Deadline:",
# "Application deadline:", "ELIGIBILITY:".
_LABEL_RE = re.compile(r"(?<!\S)(?:[A-Z][a-z]+(?:\s[A-Za-z]+)?|[A-Z]{2,}):(?=\s)")
# A legend or a pointer to another page describes no program.
_NOT_A_STATEMENT_RE = re.compile(
    r"=|\b(?:check|see|visit|consult|refer\s+to)\b.{0,80}?\b(?:websites?|web\s+sites?|sites?|pages?|links?|details)\b",
    re.IGNORECASE,
)
# "May" is a hedge, except in "may apply" and in a date ("May 1").
_HEDGE_RE = re.compile(
    r"\b(?:if|unless|depending|subject\s+to|might|could|possibly|typically|usually|generally|often|some"
    r"|may(?!\s+(?:also\s+)?apply\b|\s+\d))\b",
    re.IGNORECASE,
)
_TERMINATED_RE = re.compile(r"[.!?][\"”’')\]]*$")
_NOT_RE = re.compile(r"\b(?:not|no|ineligible|cannot|unable|except|excluding|excluded)\b|n't\b", re.IGNORECASE)

_PAY_WORD_RE = re.compile(
    r"\b(?:stipends?|salar(?:y|ies)|wages?|hourly"
    r"|(?:are|is|be|get|gets|getting|being|was|were)\s+paid(?!\s+for\b)"
    r"|paid\s+(?:positions?|research|internships?|opportunit(?:y|ies)|programs?|roles?|work|undergraduates?"
    r"|students?|summer|hourly|at\b|\$))",
    re.IGNORECASE,
)
_STIPEND_RE = re.compile(r"\bstipends?\b", re.IGNORECASE)
# Said of this position: "positions are unpaid", "this is an unpaid
# internship". Not "funding for unpaid internships", which pays for them.
_UNPAID_RE = re.compile(
    r"\b(?:(?:is|are|be|was|were|remains?)\s+(?:an?\s+)?(?:(?!(?:for|to|in|of|on|with|from|by|towards?)\b)[\w-]+\s+){0,2}?"
    r"unpaid|not\s+(?:be\s+)?paid"
    r"|no\s+(?:stipends?|salary|pay|payment|compensation)"
    r"|without\s+(?:a\s+)?(?:stipend|salary|pay|payment|compensation)|on\s+a\s+volunteer\s+basis)\b",
    re.IGNORECASE,
)
_PAY_DENIED_RE = re.compile(
    r"\b(?:stipends?|salary|pay|payment|compensation)\s+(?:is|are|will)\s+not\b"
    r"|\bnot\s+(?:provide|offer|include|receive)\w*\s+(?:a\s+)?(?:stipends?|salary|pay|payment|compensation)\b",
    re.IGNORECASE,
)
_PAY_CONTEXT_RE = re.compile(
    r"\$\s?\d|\b(?:stipends?|scholarships?|awards?|salar(?:y|ies)|wages?|paid|pay|payment|funding|funded|funds?"
    r"|grants?|fellowships?|compensation|compensated|hourly|earn(?:s|ings)?)\b",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"\$\s?(\d[\d,]*)")
_PAY_NOUN_RE = re.compile(r"\b(stipend|grant|award|scholarship|fellowship|salar|wage)(?:s|y|ies)?\b", re.IGNORECASE)

# Who an international student is. Not DACA recipients or undocumented
# students: a page welcoming them says nothing about a student on a visa.
_INTL_GROUP = (r"(?:international\s+(?:students?|undergraduates?|applicants?|scholars?)"
               r"|non[- ]?(?:u\.?\s?s\.?\s+)?citizens?)")
# The welcome is said of that group: "international students are eligible",
# "open to U.S. citizens and international students". Not "international
# student applicants must have an eligible F-1 visa", which sets a condition.
_INTL_WELCOME_RE = re.compile(
    rf"\b{_INTL_GROUP}\s+(?:are|is)\s+(?:also\s+|all\s+)?(?:eligible|welcomed?|encouraged\s+to\s+apply"
    rf"|invited\s+to\s+apply)\b"
    rf"|\b{_INTL_GROUP}\s+(?:may|can)\s+(?:also\s+)?apply\b"
    rf"|\b(?:open|available)\s+to\s+(?:[\w.’'-]+\s+){{0,6}}?{_INTL_GROUP}"
    rf"|\b(?:welcomes?|accepts?|considers?)\s+(?:applications\s+from\s+)?{_INTL_GROUP}"
    r"|\bregardless\s+of\s+(?:citizenship|nationality|visa\s+status)\b",
    re.IGNORECASE,
)
_WELCOME_RE = re.compile(
    r"\b(?:eligible|welcome[ds]?|encouraged|invited|may\s+apply|can\s+apply|open\s+to|regardless)\b",
    re.IGNORECASE,
)
_ONLY_RE = re.compile(r"\bonly\b", re.IGNORECASE)
_US = r"(?:u\.?\s?s\.?|united\s+states)"
_CITIZEN_ONLY_RE = re.compile(
    rf"\bmust\s+be\s+(?:an?\s+)?{_US}\s+(?:citizens?|nationals?|permanent\s+residents?)"
    rf"|\b(?:only|limited|restricted|open|available)\s+to\s+{_US}\s+(?:citizens?|nationals?|permanent\s+residents?)"
    rf"|\b{_US}\s+citizens?(?:\s+(?:and|or|and/or)\s+(?:{_US}\s+)?(?:lawful\s+)?permanent\s+residents?)?\s+only\b"
    rf"|\b{_US}\s+citizenship\s+(?:is\s+)?required"
    r"|\b(?:international\s+(?:students?|applicants?)|non[- ]?(?:u\.?\s?s\.?\s+)?citizens?)\s+(?:are\s+)?"
    r"(?:not\s+eligible|ineligible|cannot\s+apply|may\s+not\s+apply)",
    re.IGNORECASE,
)

# Words that make a field name a student's major, before the list ("Biology
# and Chemistry majors") or after it ("majoring in Biology", "students in
# Physics"). "Disciplines" and "fields" are not among them: "projects
# involving chemistry, physics and engineering disciplines" names research,
# not who may apply; and a name elsewhere in the sentence ("the Honors Program
# in Engineering Sciences") is not a major either.
_MAJOR_NOUN = r"(?:majors?|concentrators?|concentrations?|minors?)"
_MAJOR_LEAD = (r"(?:majors?\s+in|majoring\s+in|concentrat(?:ion|ions|ing|ors?)\s+in|minors?\s+in|degrees?\s+in"
               r"|students?\s+(?:in|of|from|studying)|studying)")
_LIST_SEPARATOR = r"(?:\s*,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+|\s*/\s*)"
_ANY_MAJOR_RE = re.compile(
    r"\b(?:(?:all|any|every)\s+(?:academic\s+)?(?:majors?|disciplines|fields\s+of\s+study)"
    r"|regardless\s+of\s+(?:academic\s+)?(?:major|discipline))\b",
    re.IGNORECASE,
)
# A configured list that is itself the all-majors answer.
_ALL_MAJORS_VALUES = frozenset({"all", "any", "all majors", "any major", "any majors", "any department"})


def is_all_majors_answer(majors: object) -> bool:
    """Whether a major list says "all majors" (``["all"]``) rather than naming any."""
    return (isinstance(majors, list) and bool(majors)
            and all(isinstance(m, str) and m.strip().lower() in _ALL_MAJORS_VALUES for m in majors))


_CLASS_YEAR_RES = {
    year: re.compile(
        rf"\b(?:{plural}|{singular}\s+(?:students?|standing|undergraduates?)"
        rf"|{ordinal}[- ]years|{ordinal}[- ]year\s+(?:students?|undergraduates?|standing))\b",
        re.IGNORECASE,
    )
    for year, plural, singular, ordinal in (
        ("freshman", "freshmen", "freshman", "first"),
        ("sophomore", "sophomores", "sophomore", "second"),
        ("junior", "juniors", "junior", "third"),
        ("senior", "seniors", "senior", "fourth"),
    )
}
_YEAR_CONTEXT_RE = re.compile(
    r"\b(?:eligible|eligibility|(?:open|available|offered|awarded|made|limited|restricted)\s+to|must\s+be|only"
    r"|apply|applicants?|welcome[ds]?|encouraged|(?:intended|designed)\s+(?:for|to)|serv(?:e|es|ing))\b",
    re.IGNORECASE,
)
_ALL_YEARS_RE = re.compile(
    r"\b(?:all\s+(?:class\s+)?years|all\s+undergraduates|all\s+class\s+levels|any\s+(?:class\s+)?year"
    r"|students\s+of\s+all\s+(?:class\s+)?(?:years|levels))\b",
    re.IGNORECASE,
)
_UNCERTAIN_YEAR_RE = re.compile(r"\b(?:rising|high\s+school)\b", re.IGNORECASE)

_TIMING_RE = re.compile(
    r"\b(?:deadlines?|due|apply|applications?|applicants?|open(?:s|ed)?|clos(?:e|es|ed|ing)|rolling"
    r"|cycles?|submit(?:ted)?|submissions?|accept(?:ed|ing)?)\b",
    re.IGNORECASE,
)
_DEADLINE_RE = re.compile(r"\b(?:deadlines?|due)\b", re.IGNORECASE)
_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august",
                "september", "october", "november", "december")
_MONTH_ABBREVIATIONS = {name[:3]: name for name in _MONTH_NAMES} | {"sept": "september"}
_MONTH_ABBREVIATION_RE = re.compile(r"\b(jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b\.?")
# "May" is a month only with a day after it: "students may apply" names none.
_MONTH_RE = re.compile(r"\b(january|february|march|april|june|july|august|september|october|november|december)\b"
                       r"|\b(may)\s+\d")
_DATE_RE = re.compile(rf"\b({'|'.join(_MONTH_NAMES)})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b"
                      r"|\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b")
_FILLER_WORDS = frozenset({
    "the", "and", "for", "with", "via", "per", "from", "are", "its", "their", "this", "that", "also",
    "plus", "into", "typically", "usually", "generally", "often", "about", "approximately", "around",
})


def _page_sentences(text: str, *, cut: bool) -> tuple[str, ...]:
    text = _LABEL_RE.sub(lambda m: "\n" + m.group(0), _HEADING_RE.sub(lambda m: m.group(0) + "\n", text))
    sentences = [s for s in (" ".join(part.split()) for part in _SENTENCE_BREAK_RE.split(text)) if s]
    if cut and sentences and not _TERMINATED_RE.search(sentences[-1]):
        sentences.pop()
    return tuple(s for s in sentences if len(s) <= _MAX_QUOTE
                 and not _NOT_A_STATEMENT_RE.search(s) and not _HEDGE_RE.search(s))


@lru_cache(maxsize=4096)
def _excerpt_sentences(description: str) -> tuple[str, ...]:
    """The readable sentences of the excerpt after CAPTURED_PAGE_MARKER.

    A description holding an email address gives none: the public projection
    serves it as "[email redacted]", so no part of it can be quoted.
    """
    if CAPTURED_PAGE_MARKER not in description:
        return ()
    # Imported here: the projector imports this module.
    from backend.lib.public_projection import contains_embedded_email

    if contains_embedded_email(description):
        return ()
    excerpt = description.split(CAPTURED_PAGE_MARKER, 1)[1].lstrip()
    return _page_sentences(excerpt, cut=len(excerpt) >= EXCERPT_LIMIT or len(description) >= DESCRIPTION_LIMIT)


# A passage under a heading for another audience is about another program
# ("Graduate Students > IPAC Visiting Graduate Student Research Fellowship"
# on an undergraduate program's page).
_OTHER_AUDIENCE_RE = re.compile(
    r"\b(?:graduate|grad\s+students?|masters?|doctoral|ph\.?\s?d\.?|postdocs?|postdoctoral|high\s+school|faculty)\b",
    re.IGNORECASE,
)
_MAX_PASSAGE = 4000


@lru_cache(maxsize=4096)
def _passage_sentences(sources: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...]
                       ) -> tuple[tuple[str, str, str], ...]:
    """(sentence, source_url, checked_at) for the captured passages
    ``sources`` holds as (source_url, checked_at, ((heading, text), ...))."""
    from backend.lib.public_projection import contains_embedded_email

    out = []
    for source_url, checked_at, sections in sources:
        for heading, text in sections:
            # A passage with an address in it is published as "[email
            # redacted]" wherever it is quoted, so no sentence of it can be.
            if len(text) > _MAX_PASSAGE or _OTHER_AUDIENCE_RE.search(heading) or contains_embedded_email(text):
                continue
            out.extend((sentence, source_url, checked_at) for sentence in _page_sentences(text, cut=False))
    return tuple(out)


# A program named by its acronym in a passage's heading ("CICS-Based Research
# Opportunities > Early Research Scholars Program (ERSP)").
_HEADING_ACRONYM_RE = re.compile(r"\(([A-Z][A-Z0-9+&]+)\)")


def _names_another_program(heading: str, names: str) -> bool:
    """Whether ``heading`` names a program by an acronym the row's own title
    and program name (``names``) do not carry: a page listing several
    programs, and this passage is about one of the others."""
    return any(not re.search(rf"(?<![A-Za-z0-9]){re.escape(acronym)}(?![A-Za-z0-9])", names)
               for acronym in _HEADING_ACRONYM_RE.findall(heading))


def _captured_passages(record: dict, metadata: dict) -> tuple[tuple[str, str, str], ...]:
    """The passages kept from the row's own page, as `email_target_conditions`
    binds them: to the row's URL, with a past `checked_at`. A passage under
    another program's name is left out."""
    sources = metadata.get(CONTACT_SOURCE_KEY)
    if not isinstance(sources, list):
        return ()
    bound = {contact_url(record.get(key)) for key in ("source_url", "url")} - {None}
    names = " ".join(record[key] for key in ("title", "lab_or_program") if isinstance(record.get(key), str))
    kept = []
    for source in sources:
        if not (isinstance(source, dict) and contact_url(source.get("record_source_url")) in bound
                and contact_url(source.get("source_url")) and contact_source_time(source.get("checked_at"))
                and isinstance(source.get("sections"), list)):
            continue
        sections = tuple((section["heading"], section["text"]) for section in source["sections"]
                         if isinstance(section, dict) and isinstance(section.get("heading"), str)
                         and isinstance(section.get("text"), str)
                         and not _names_another_program(section["heading"], names))
        kept.append((source["source_url"], source["checked_at"], sections))
    return _passage_sentences(tuple(kept)) if kept else ()


def _captured_text(record: dict) -> tuple[tuple[str, ...], dict[str, tuple[str | None, str | None]]]:
    """Every readable sentence of the page text a configured row carries, the
    excerpt first, and where and when each was read."""
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    description = record.get("description")
    origins: dict[str, tuple[str | None, str | None]] = {}
    if isinstance(description, str):
        source_url = record.get("source_url")
        verified = metadata.get("last_verified")
        for sentence in _excerpt_sentences(description):
            origins.setdefault(sentence, (source_url if isinstance(source_url, str) else None,
                                          verified if isinstance(verified, str) else None))
    for sentence, source_url, checked_at in _captured_passages(record, metadata):
        origins.setdefault(sentence, (source_url, checked_at))
    return tuple(origins), origins


def _words(text: str) -> list[str]:
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text.lower().replace("&", " and "))
    return [_MONTH_ABBREVIATIONS.get(word, word) for word in re.findall(r"[a-z]+|\d+", text)]


def _content_words(text: str) -> frozenset[str]:
    return frozenset(w for w in _words(text) if w.isdigit() or (len(w) >= 3 and w not in _FILLER_WORDS))


def _spell_months(text: str) -> str:
    return _MONTH_ABBREVIATION_RE.sub(lambda m: _MONTH_ABBREVIATIONS[m.group(1)], text.lower())


def _months(text: str) -> set[str]:
    return {m.group(1) or m.group(2) for m in _MONTH_RE.finditer(_spell_months(text))}


def _dates(text: str) -> set[tuple[str, int]]:
    """(month, day) for every date written out: "March 1", "Mar. 1st", "3/1/27"."""
    dates = set()
    for m in _DATE_RE.finditer(_spell_months(text)):
        if m.group(1):
            dates.add((m.group(1), int(m.group(2))))
        elif 1 <= int(m.group(3)) <= 12:
            dates.add((_MONTH_NAMES[int(m.group(3)) - 1], int(m.group(4))))
    return dates


def _first(sentences: tuple[str, ...], test) -> str | None:
    return next((s for s in sentences if test(s)), None)


def _verdict(stated: str | None, contradicted: str | None) -> ConfiguredFact:
    if contradicted is not None:
        return ConfiguredFact(FACT_CONTRADICTED, contradicted)
    if stated is not None:
        return ConfiguredFact(FACT_STATED, stated)
    return _UNSTATED


def _all_words_stated(value: str, sentences: tuple[str, ...], context_re: re.Pattern, negated) -> str | None:
    """The sentence holding every content word of a free-text value, or None."""
    wanted = _content_words(value)
    if not wanted:
        return None
    return _first(sentences, lambda s: bool(context_re.search(s)) and not negated(s) and wanted <= set(_words(s)))


def _pay_negated(sentence: str) -> bool:
    return bool(_UNPAID_RE.search(sentence) or _PAY_DENIED_RE.search(sentence))


def _pay_stated(sentence: str) -> bool:
    return bool(_PAY_WORD_RE.search(sentence)) and not _pay_negated(sentence)


def _check_paid(value: object, sentences: tuple[str, ...]) -> ConfiguredFact:
    if value == "no":
        return _verdict(_first(sentences, _UNPAID_RE.search), _first(sentences, _pay_stated))
    if value == "stipend":
        stated = _first(sentences, lambda s: bool(_STIPEND_RE.search(s)) and not _pay_negated(s))
    elif value == "yes":
        stated = _first(sentences, _pay_stated)
    else:
        return _UNSTATED
    return _verdict(stated, _first(sentences, _pay_negated))


def _check_compensation(value: object, sentences: tuple[str, ...]) -> ConfiguredFact:
    if not isinstance(value, str) or not value.strip():
        return _UNSTATED
    stated = _all_words_stated(value, sentences, _PAY_CONTEXT_RE, _pay_negated)
    contradicted = None
    amounts = {a.replace(",", "") for a in _AMOUNT_RE.findall(value)}
    nouns = _pay_nouns(value)
    if amounts and not any(amounts & {a.replace(",", "") for a in _AMOUNT_RE.findall(s)} for s in sentences):
        # The page names its pay in dollars, and never the configured amount.
        # When the value says what the money is ("$4,800 stipend"), only the
        # same kind of pay can disagree with it: "up to $400 for travel" is
        # another line of the same award, and the excerpt may have cut the
        # stipend's own sentence.
        contradicted = _first(sentences, lambda s: bool(_AMOUNT_RE.search(s) and _PAY_CONTEXT_RE.search(s))
                              and (not nouns or bool(nouns & _pay_nouns(s))))
    return _verdict(stated, contradicted)


def _pay_nouns(text: str) -> set[str]:
    return {noun.lower() for noun in _PAY_NOUN_RE.findall(text)}


def _intl_welcome(sentence: str) -> bool:
    return bool(_INTL_WELCOME_RE.search(sentence)) and not _NOT_RE.search(sentence) and not _ONLY_RE.search(sentence)


def _citizen_restriction(sentence: str) -> bool:
    return bool(_CITIZEN_ONLY_RE.search(sentence)) and not _intl_welcome(sentence)


def _check_international(value: object, sentences: tuple[str, ...]) -> ConfiguredFact:
    if value == "yes":
        return _verdict(_first(sentences, _intl_welcome), _first(sentences, _citizen_restriction))
    if value == "no":
        return _verdict(_first(sentences, _citizen_restriction), _first(sentences, _intl_welcome))
    return _UNSTATED


def _check_citizenship(value: object, sentences: tuple[str, ...]) -> ConfiguredFact:
    if value is True:
        return _check_international("no", sentences)
    if value is False:
        return _check_international("yes", sentences)
    return _UNSTATED


def _phrase_pattern(phrase: str) -> str:
    words = re.findall(r"[a-z0-9]+", phrase.lower().replace("&", " and "))
    return r"\b" + r"\W+".join(map(re.escape, words)) + r"\b" if words else ""


def _majors_named(majors: list[str], sentence: str) -> set[str]:
    """The configured majors ``sentence`` names as majors: in a list of them
    next to a major word, before it ("Biology and Chemistry majors") or after
    it ("majoring in Biology")."""
    names = {major: pattern for major in majors if (pattern := _phrase_pattern(major))}
    if not names:
        return set()
    name = "(?:" + "|".join(names.values()) + ")"
    run = rf"{name}(?:{_LIST_SEPARATOR}{name})*"
    text = sentence.lower().replace("&", " and ")
    spans = [m.group(1) for m in re.finditer(rf"({run})\s+{_MAJOR_NOUN}\b", text)]
    spans += [m.group(1) for m in re.finditer(rf"\b{_MAJOR_LEAD}\s+(?:the\s+)?({run})", text)]
    return {major for major, pattern in names.items() if any(re.search(pattern, span) for span in spans)}


def _check_majors(value: object, sentences: tuple[str, ...]) -> ConfiguredFact:
    majors = [m for m in value if isinstance(m, str) and m.strip()] if isinstance(value, list) else []
    if not majors:
        return _UNSTATED
    # Every major, said of who may apply: "open to students of all majors".
    # "Projects in all fields of study" is about the research, and "students
    # from every major study biology" about who takes the courses.
    every_major = _first(sentences, lambda s: bool(_ANY_MAJOR_RE.search(s) and _WELCOME_RE.search(s))
                         and not _NOT_RE.search(s))
    if is_all_majors_answer(majors):
        return _verdict(every_major, None)
    stated = _first(sentences, lambda s: not _NOT_RE.search(s) and not _ANY_MAJOR_RE.search(s)
                    and _majors_named(majors, s) == set(majors))
    return _verdict(stated, every_major)


def _years_named(sentence: str) -> set[str]:
    return {year for year, pattern in _CLASS_YEAR_RES.items() if pattern.search(sentence)}


def _check_class_year(value: object, sentences: tuple[str, ...]) -> ConfiguredFact:
    years = {y.lower() for y in value if isinstance(y, str)} - {"unknown"} if isinstance(value, list) else set()
    if not years or not years <= set(_CLASS_YEAR_RES):
        return _UNSTATED
    readable = tuple(s for s in sentences if _YEAR_CONTEXT_RE.search(s)
                     and not _UNCERTAIN_YEAR_RE.search(s) and not _NOT_RE.search(s))
    stated = _first(readable, lambda s: _years_named(s) == years)
    contradicted = _first(readable, lambda s: bool(_years_named(s) - years)
                          or (len(years) < len(_CLASS_YEAR_RES) and bool(_ALL_YEARS_RE.search(s))))
    return _verdict(stated, contradicted)


def _check_window(value: object, sentences: tuple[str, ...]) -> ConfiguredFact:
    if not isinstance(value, str) or not value.strip():
        return _UNSTATED
    stated = _all_words_stated(value, sentences, _TIMING_RE, lambda s: bool(_NOT_RE.search(s)))
    # The page dates its deadline, and never on a day the note gives (or,
    # when the note names only months, never in a month it names).
    dates, months = _dates(value), _months(value)
    on_page = _dates(" ".join(sentences))
    contradicted = None
    if (dates and not on_page & dates) or (not dates and months and not {m for m, _ in on_page} & months):
        contradicted = _first(sentences, lambda s: bool(_DEADLINE_RE.search(s) and _dates(s)))
    return _verdict(stated, contradicted)


# A row whose config names its page a directory or a hub ("Summer
# Undergraduate Research Opportunities directory", "Research Opportunities
# Hub"): a sentence there is about one of the programs it lists.
_HUB_RE = re.compile(r"\b(?:directory|directories|hub|database|listings?)\b", re.IGNORECASE)

_FACT_CHECKS = {
    "paid": _check_paid,
    "compensation": _check_compensation,
    "international_students": _check_international,
    "citizenship": _check_citizenship,
    "majors": _check_majors,
    "class_year": _check_class_year,
    "application_window": _check_window,
}


def configured_fact(record: dict, facet: str) -> ConfiguredFact:
    """Whether the page text a configured campus row carries states its ``facet``.

    ``facet`` is a key of CONFIGURED_FACT_PATHS. A row that is not a configured
    program, a value another producer stamped (a tagger's pay, the enricher's
    majors), a row with no page text, a row whose page the config shares
    with another program (`shared_program_page`: a sentence there may be
    about the other one) and a row the config calls a directory or hub are
    all unstated.
    """
    path = CONFIGURED_FACT_PATHS[facet]
    if not is_configured_program(record) or inferred_method(record, path) not in (None, CONFIGURED_PROGRAM_METHOD):
        return _UNSTATED
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and metadata.get("shared_program_page") is True:
        return _UNSTATED
    if any(isinstance(record.get(key), str) and _HUB_RE.search(record[key]) for key in ("title", "lab_or_program")):
        return _UNSTATED
    sentences, origins = _captured_text(record)
    if not sentences:
        return _UNSTATED
    value: object = record
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    fact = _FACT_CHECKS[facet](value, sentences)
    if fact.quote is None:
        return fact
    return ConfiguredFact(fact.state, fact.quote, *origins[fact.quote])


def configured_value_unstated(record: dict, facet: str) -> bool:
    """Whether ``facet`` holds a campus program spec's value that the page text
    the row carries does not state: our configuration, shown as inference."""
    return is_configured_program(record) and configured_fact(record, facet).state != FACT_STATED


# SRO work-authorization notes written before the collector read the
# "Citizenship Requirement" field were ±50-character keyword windows joined by
# " | ", or one window that runs the field's label into its value. A row whose
# note is one of those, or empty, got its citizenship rule and intl answer from
# that keyword scan of the whole page: on the 2026-10-09 corpus 5 of 279 such
# rows say "required" beside a field reading "No Citizenship Requirements". A
# window note also dates the row to before the collector read Compensation, so
# its pay came from the same kind of scan.
SRO_NOTE_WINDOW_RE = re.compile(r" \| |Citizenship Requirement (?:US|No)\b")
SRO_SCANNED_CITIZENSHIP_METHOD = "rule:sro_page_citizenship_keywords"
SRO_SCANNED_PAY_METHOD = "rule:sro_page_paid_keywords"
_SRO_SCANNED_CITIZENSHIP_STAMPS = {
    "eligibility.international_friendly": (lambda value: value in {"yes", "no"}, SRO_SCANNED_CITIZENSHIP_METHOD),
    "eligibility.citizenship_required": (lambda value: value is True or value is False,
                                         SRO_SCANNED_CITIZENSHIP_METHOD),
}
_SRO_SCANNED_PAY_STAMPS = {"paid": (lambda value: value in {"yes", "stipend", "no"}, SRO_SCANNED_PAY_METHOD)}


def _sro_scanned_fields(record: dict) -> dict:
    """Stamp tests for the fields of a uiuc_sro row that a keyword scan wrote."""
    if record.get("source") != "uiuc_sro":
        return {}
    eligibility = record.get("eligibility")
    notes = eligibility.get("work_auth_notes") if isinstance(eligibility, dict) else None
    notes = notes.strip() if isinstance(notes, str) else ""
    if notes and not SRO_NOTE_WINDOW_RE.search(notes):
        return {}  # the collector read the labelled fields
    return {**_SRO_SCANNED_CITIZENSHIP_STAMPS, **(_SRO_SCANNED_PAY_STAMPS if notes else {})}


def stamp_collector_templates(record: dict) -> dict:
    """Stamp registered collector constants as inferred, in place; return record.

    Idempotent, and never overrides an existing stamp: a field some other
    producer already accounted for keeps that producer's method. Only a value
    equal to the registered template (or, for a configured program or a
    scanned SRO field, any answer other than unknown) is stamped — a future
    collector that reads a real pay value off the page is left stated, and so
    is a configured value its page text states (`configured_fact`).
    """
    templates = _COLLECTOR_TEMPLATE_STAMPS.get(record.get("source") or "", {})
    matches = {path: (lambda value, template=template: value == template, method)
               for path, (template, method) in templates.items()}
    if is_configured_program(record):
        matches.update({
            path: (lambda value, facet=facet, test=test: test(value)
                   and configured_fact(record, facet).state != FACT_STATED, CONFIGURED_PROGRAM_METHOD)
            for path, (facet, test) in _CONFIGURED_PROGRAM_STAMPS.items()
        })
    matches.update(_sro_scanned_fields(record))
    for path, (matches_template, method) in matches.items():
        if inferred_method(record, path) is not None:
            continue
        value: object = record
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if matches_template(value):
            metadata = record.setdefault("metadata", {})
            if isinstance(metadata, dict):
                stamp_inferred(metadata, path, method)
    return record


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
# Internal corpus field shared by collectors, the serve-time neutralizer and
# the ranker. Public projections remove it before serialization.
FACULTY_MAJOR_LABELS_MARKER = "_faculty_major_labels"
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


def faculty_positive_major_labels(record: dict) -> list[str]:
    """Return source-backed faculty field labels for positive-only matching.

    Faculty collectors historically stored a department/field label in
    ``eligibility.majors``.  It is not an application requirement, so the
    public eligibility projection must continue to clear it.  It is still a
    useful weak fit signal when the student's field actually aligns.  Preserve
    that signal under an internal metadata marker before neutralization; fall
    back to the stated department so future collectors that correctly leave
    opening eligibility empty do not lose the label on the next refresh.
    """
    if not faculty_contact_claims_unverified(record):
        return []

    metadata = record.get("metadata")
    stored = (
        metadata.get(FACULTY_MAJOR_LABELS_MARKER)
        if isinstance(metadata, dict)
        else None
    )
    eligibility = record.get("eligibility")
    raw = eligibility.get("majors") if isinstance(eligibility, dict) else None
    candidates = stored if isinstance(stored, list) and stored else raw
    if not isinstance(candidates, list) or not candidates:
        department = record.get("department")
        candidates = [department] if isinstance(department, str) else []

    labels: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        if not isinstance(value, str):
            continue
        label = value.strip()[:120]
        key = label.casefold()
        if label and key not in seen:
            labels.append(label)
            seen.add(key)
        if len(labels) >= 12:
            break
    return labels


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


# The sentence that closes a faculty description, keyed by the availability
# the structured summary carries. frontend/src/lib/faculty-profile-copy.ts says
# each one from the code, so a new key here needs a dictionary entry there.
FACULTY_PROFILE_CLOSINGS: dict[str, str] = {
    "not_accepting_undergraduates": (
        "The source profile states that this faculty contact is not currently "
        "accepting undergraduate students or researchers."
    ),
    "research_inactive": (
        "The source profile reports that this faculty member is not currently "
        "conducting active research."
    ),
    "unknown": (
        "Contact this faculty member to ask whether undergraduate research "
        "opportunities are currently available."
    ),
}


def faculty_profile_summary_fields(record: dict) -> dict:
    """The parts a faculty description is written from, sent beside it.

    The client says the description in its UI language from these, and keeps
    the research areas as the source gave them. Before this it had to
    recognise the English sentence, so any rewording here silently left the
    Chinese page in English. Absent parts are null, never "".
    """
    name = str(record.get("pi_name") or "").strip()
    department = str(record.get("department") or "").strip()
    organization = str(record.get("organization") or "").strip()

    metadata = record.get("metadata") or {}
    research_areas = metadata.get("research_areas_raw")
    if not isinstance(research_areas, str) or not research_areas.strip():
        research_areas = ", ".join(
            value.strip()
            for value in (record.get("keywords") or [])[:6]
            if isinstance(value, str) and value.strip()
        )
    availability = faculty_availability_status(record)
    return {
        "version": 1,
        "name": name or None,
        "department": department or None,
        "organization": organization or None,
        "research_areas": research_areas.strip()[:300] or None,
        "availability": availability if availability in FACULTY_PROFILE_CLOSINGS else "unknown",
    }


def render_faculty_profile_summary(fields: dict) -> str:
    """The English description, written from the structured fields alone."""
    department = fields["department"]
    organization = fields["organization"]
    affiliation = ""
    if department and organization:
        affiliation = f" in {department} at {organization}"
    elif department:
        affiliation = f" in {department}"
    elif organization:
        affiliation = f" at {organization}"
    parts = [f"Faculty research profile for {fields['name'] or 'this faculty member'}{affiliation}."]
    if fields["research_areas"]:
        parts.append(f"Research areas: {fields['research_areas']}")
    parts.append(FACULTY_PROFILE_CLOSINGS[fields["availability"]])
    return " ".join(parts)


def _faculty_profile_summary(record: dict) -> str:
    """Build availability-neutral display prose from identity/research facts."""
    return render_faculty_profile_summary(faculty_profile_summary_fields(record))


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
    major_labels = faculty_positive_major_labels(record)

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
        if major_labels:
            metadata[FACULTY_MAJOR_LABELS_MARKER] = major_labels
        else:
            metadata.pop(FACULTY_MAJOR_LABELS_MARKER, None)
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
    # Built per response rather than kept on the corpus row: ~127k faculty
    # rows would each hold another dict for a field only the wire needs.
    safe["faculty_profile_summary"] = faculty_profile_summary_fields(safe)
    # The source excerpt is useful only while canonicalizing a restriction.
    # Public payloads expose the compact provenance marker, never arbitrary
    # scraped eligibility prose that can contain stale opening claims.
    eligibility = safe.get("eligibility")
    if isinstance(eligibility, dict):
        eligibility.pop("eligibility_text_raw", None)
    metadata = safe.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop(FACULTY_MAJOR_LABELS_MARKER, None)
    return safe


# ---------------------------------------------------------------------------
# Target truth: may a student act on this record today?
# ---------------------------------------------------------------------------

_CLOSED_LISTING_STATUSES = frozenset({"closed", "past", "archived", "expired"})
_OPEN_LISTING_STATUSES = frozenset({"open", "active", "recruiting"})

# Source-specific status keys, in the order they are consulted. A source states
# its own listing lifecycle; we read that rather than re-deriving one from prose.
_LISTING_STATUS_KEYS = ("listing_status", "urap_status")

# Every source_type the canonical collectors emit for a real listing. A
# missing, stale or unreviewed value proves nothing about whether an opening
# exists, so it resolves to "unknown" rather than defaulting to a listing.
# Mirrors frontend/src/lib/record-kind.ts — add to both or to neither.
_LISTING_SOURCE_TYPES = frozenset({
    "campus_announcement",
    "campus_career",
    "campus_department",
    "campus_lab",
    "campus_program",
    "external",
    "external_reu",
    "internship",
    "job",
    "manual",
    "rss",
    "summer_program",
    "ucb_announcement",
    "ucb_career",
    "ucb_department",
    "ucb_lab",
    "ucb_program",
    "uiuc_research",
})


def record_kind(record: dict) -> str:
    """``faculty_contact`` | ``listing`` | ``unknown`` from source_type alone."""
    source_type = record.get("source_type") if isinstance(record, dict) else None
    if source_type == "faculty_research":
        return "faculty_contact"
    if isinstance(source_type, str) and source_type in _LISTING_SOURCE_TYPES:
        return "listing"
    return "unknown"


# Sources whose closed records are published as reference material, stated by
# the collector itself ("Shown as a reference for the kind of undergraduate
# research this lab offers"). Closedness alone does not earn this: a generic
# expired posting makes no editorial promise that it is worth reading, and
# claiming otherwise invents one on the source's behalf.
_REFERENCE_CONTRACT_SOURCES = frozenset({"ucb_urap_projects"})


@dataclass(frozen=True)
class TargetTruth:
    """Whether a record supports action, and the evidence for that answer.

    ``listing_state`` and ``reference_only`` are deliberately two dimensions.
    A closed listing can still be worth reading — the URAP rows describe real
    labs — and a source may publish reference material that was never a
    listing. Collapsing them into one flag forces the product to lie about one.

    ``verified_at`` / ``expires_at`` are read off the record or left ``None``.
    A confident-looking date we invented is worse than an absent one.
    """

    listing_state: str
    reference_only: bool
    actionable: bool
    accepting_state: str
    reason_code: str | None
    evidence_source: str | None
    evidence_key: str | None
    evidence_value: str | None
    verified_at: str | None
    expires_at: str | None


def stated_listing_deadline(record: dict) -> date | None:
    """The application deadline a listing's source stated, or None.

    The evidence bar ``src.matcher.ranker._stated_deadline_date`` scores by,
    so the card that says "Deadline has passed" and the guard that refuses the
    action read one date: never an estimate, never an inference stamp, never a
    faculty profile. One step stricter than the ranker: only a record we know
    is a listing has one. On a record of unknown kind a deadline is a term of
    an application nobody showed exists, and target_truth refuses that record
    anyway (record_kind_unverified, unless an earlier reason applies).
    """
    if record_kind(record) != "listing":
        return None
    if record.get("deadline_is_estimate") or is_inferred(record, "deadline"):
        return None
    deadline = record.get("deadline")
    if not isinstance(deadline, str):
        return None
    try:
        return date.fromisoformat(deadline[:10])
    except ValueError:
        return None


def _today() -> date:
    # The UTC date, whatever the host's zone. The ranker's deadline penalty and
    # the match snapshot day key read the local date.today() instead; the two
    # agree only because Render runs on UTC.
    return datetime.now(UTC).date()


# A source writes its deadline as a date in its own time zone, and the server
# runs on UTC. Anywhere on Earth (UTC-12) date D ends at D+1 12:00 UTC, so D
# has passed for everyone only from UTC D+2. Without the extra day a student in
# Chicago drafting at 8 pm on the deadline day is refused: it is already the
# next UTC date.
_DEADLINE_GRACE = timedelta(days=1)


def _listing_status(metadata: dict) -> tuple[str | None, str | None]:
    """The source-stated listing status and the key that decided it.

    Every authoritative key is scanned, not just the first populated one. A
    record carrying both ``listing_status='unknown'`` and
    ``urap_status='closed'`` was previously decided by key order, so a vaguer
    or merely unrecognised value could mask an explicit closure and let a dead
    listing through. Any recognised closure wins; a recognised open is accepted
    only when no key says closed; anything unrecognised decides nothing.
    """
    first_open: tuple[str, str] | None = None
    for key in _LISTING_STATUS_KEYS:
        raw = metadata.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip().lower()
        if value in _CLOSED_LISTING_STATUSES:
            return value, key
        if value in _OPEN_LISTING_STATUSES and first_open is None:
            first_open = (value, key)
    return first_open if first_open is not None else (None, None)


def target_truth(record: dict) -> TargetTruth:
    """Decide, in O(1) and without touching ``record``, whether it is actionable.

    Fails closed on explicit evidence only. A record that states nothing keeps
    today's behaviour and reports ``unknown``: this contract exists to keep
    stated-closed listings out of action flows, not to retire the unstamped
    majority of the corpus.

    The one input from outside the record is today's UTC date, which a stated
    deadline is read against. The same record can turn non-actionable
    overnight, so a cached answer is only as current as the day it was
    computed on.
    """
    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not isinstance(metadata, dict):
        metadata = {}

    verified_at = metadata.get("last_verified")
    verified_at = verified_at if isinstance(verified_at, str) else None
    expires_at = metadata.get("expires_at")
    expires_at = expires_at if isinstance(expires_at, str) else None

    status, status_key = _listing_status(metadata)
    if status in _CLOSED_LISTING_STATUSES:
        listing_state = "closed"
    elif status in _OPEN_LISTING_STATUSES:
        listing_state = "open"
    else:
        listing_state = "unknown"

    source = record.get("source") if isinstance(record, dict) else None
    source_publishes_reference = (
        isinstance(source, str)
        and source.strip().lower() in _REFERENCE_CONTRACT_SOURCES
        and listing_state == "closed"
    )
    reference_marker = metadata.get("reference_only") is True
    reference_only = reference_marker or source_publishes_reference

    def _truth(
        reason: str | None,
        *,
        key: str | None = None,
        value: str | None = None,
        source: str = "metadata",
        listing: str | None = None,
        accepting: str | None = None,
    ) -> TargetTruth:
        return TargetTruth(
            listing_state=listing if listing is not None else listing_state,
            reference_only=reference_only,
            actionable=reason is None,
            # "accepting" is a claim about the target, so it needs both a
            # stated-open listing and a record we would actually act on. A
            # deactivated row carrying a stale `open` status is not evidence
            # that anyone is still taking students.
            accepting_state=(
                accepting
                if accepting is not None
                else "not_accepting"
                if listing_state == "closed"
                else "accepting"
                if listing_state == "open" and reason is None
                else "unknown"
            ),
            reason_code=reason,
            evidence_source=source if reason else None,
            evidence_key=key,
            evidence_value=value,
            verified_at=verified_at,
            expires_at=expires_at,
        )

    # Most precise reason first. The fixed collector writes `urap_status=closed`
    # AND `is_active=False` on the same past project, so letting `inactive` win
    # would silently blur every closed listing's reason on the next refresh —
    # same record, same closure, vaguer answer. `inactive` stays the fallback it
    # has always been for records that state nothing more specific.
    if listing_state == "closed":
        return _truth("listing_closed", key=status_key, value=status)
    if reference_marker:
        return _truth("reference_only", key="reference_only", value="True")
    # The person's own statement that they are not taking undergraduates. The
    # ranker has excluded these from Match for a long time, but exclusion from
    # a ranked list is not a contract: a direct opportunity id reaches the
    # action routes without ever passing through ranking, so email and tailor
    # could act on a professor who has said in writing not to ask. It belongs
    # in the truth itself, which every action path consults.
    #
    # Ranked below the listing reasons and above `inactive`: a posting's own
    # closure is the more precise statement, while `inactive` states nothing
    # about who is accepting. `listing_state` is deliberately reported as
    # unknown — nothing here says a posting closed, and a faculty row carrying
    # a stale `open` status is not a listing this contract will vouch for.
    #
    # `research_inactive` is NOT here, and must never be folded in. "I have no
    # active research right now" and "do not ask me" are different claims from
    # different people; blocking the first would silently rewrite it as the
    # second and cost students a legitimate, carefully-worded question.
    if faculty_availability_status(record) == "not_accepting_undergraduates":
        return _truth(
            "faculty_not_accepting",
            key="faculty_availability_status",
            value="not_accepting_undergraduates",
            source="faculty_availability",
            listing="unknown",
            accepting="not_accepting",
        )
    # The source dated its own application window, and the date is behind
    # us: the same closure as a stated `closed` status, read off the calendar.
    # Ahead of `inactive` for the reason a stated status is — the collector
    # deactivates a past listing on a later refresh, and that must not blur
    # "the deadline passed" into "no longer active".
    deadline = stated_listing_deadline(record)
    if deadline is not None and deadline + _DEADLINE_GRACE < _today():
        return _truth(
            "listing_closed",
            key="deadline",
            value=record["deadline"],
            source="deadline",
            listing="closed",
            accepting="not_accepting",
        )
    if metadata.get("is_active") is False:
        return _truth("inactive", key="is_active", value="False")
    # Last, and only once every more specific fact has had its say: we have
    # never confirmed what this record IS.
    #
    # `source_type` is what tells us a row is a posting rather than a directory
    # page, and an unreviewed one is not evidence of either. Every surface then
    # has to decide for itself whether to show a deadline, a pay figure, an
    # eligibility rule, an Apply button — dozens of sinks each maintaining a
    # third state, and each one edit away from treating "we don't know" as
    # "listing". Deciding it once, here, is what makes that impossible.
    #
    # Deliberately NOT `reference_only`: nobody published this as reference
    # material, and saying so would invent an editorial claim on the source's
    # behalf. Deliberately not the client's `status_unverified` either — that
    # one means a payload we could not read; this is a payload we read fine,
    # describing a record whose type nobody has reviewed.
    if record_kind(record) == "unknown":
        return _truth(
            "record_kind_unverified",
            key="source_type",
            value=str(record.get("source_type")) if isinstance(record, dict) else None,
            source="record_kind",
            listing="unknown",
            accepting="unknown",
        )
    return _truth(None)


def is_actionable_target(record: dict) -> bool:
    """Shorthand for the one question most call sites ask."""
    return target_truth(record).actionable


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
