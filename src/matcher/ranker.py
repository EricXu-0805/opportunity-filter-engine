"""Three-layer matching engine. Scores opportunities against a student profile.

Tunable scoring knobs live in `src/matcher/config.py` (importable as
constants here). Hardcoded taxonomies (MAJOR_GROUPS, RELATED_MAJORS,
SKILL_SYNONYMS, SKILL_IMPLIES) still live in this file because they're
data, not policy — moving them to YAML is a separate refactor.
"""

import math
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from backend.lib.contact_visibility import send_target_strength, verified_send_target

from ..evidence import (
    faculty_availability_status,
    faculty_contact_claims_unverified,
    faculty_positive_major_labels,
    faculty_safe_eligibility,
    faculty_safe_lab_or_program,
    is_inferred,
    is_professor_rank,
    is_read_off_the_page,
    target_truth,
)
from ..normalizers.school_audience import SOURCE_DEFAULTS
from .config import (
    BUCKET_THRESHOLDS,
    COLLEGE_AFFINITY_MAX,
    COURSEWORK_FOCUS_BONUS,
    COURSEWORK_MAX_FROM_COUNT,
    COURSEWORK_PER_COURSE,
    COURSEWORK_RELEVANCE_BONUS,
    COURSEWORK_UNKNOWN,
    DEADLINE_PASSED_PENALTY,
    ELIG_MAJOR_WEIGHT,
    EMPTY_INTEREST_MAJOR_BONUS,
    EXPLORE_MAJOR_MISMATCH_FLOOR,
    EXPLORE_READINESS_DROP,
    GRAD_LEVEL_PENALTY,
    HIGH_PRIORITY_TARGET_COUNT,
    HOME_SCHOOL_AFFINITY_MAX,
    IMPLICIT_MAJOR_KEYWORD_CEILING,
    IMPLICIT_MAJOR_PER_HIT,
    INTEREST_BONUS_CAP,
    INTEREST_BONUS_PER_HIT,
    INTL_UNKNOWN_INTERNSHIP_SCORE,
    INTL_UNKNOWN_SCORE,
    PROFICIENCY_WEIGHTS,
    RESPONSIVENESS_BONUS,
    RESPONSIVENESS_MIN_N,
    SEASONAL_BOOST_ENABLED,
    SEASONAL_BOOST_FACTOR,
    SEASONAL_BOOST_MONTHS,
    SEMANTIC_RERANK_FALLBACK_CAP,
    SIMILARITY_SCALE_TFIDF,
    STRETCH_BLEND,
    STRETCH_MIDPOINT,
    STRETCH_SIGMOID_K,
    TOPIC_MISMATCH_PENALTY,
    TOPIC_UNKNOWN_PENALTY,
    WEIGHTS_DEFAULT,
)

# Every school slug the platform collects for. All are R1s, so records hosted
# at any of them share one brand score — ranking registered schools against
# each other (the old caltech/mit/... list) is not the product's job.
REGISTERED_SCHOOLS = frozenset(s for s, _ in SOURCE_DEFAULTS.values() if s)

# External prestige brands (labs/agencies/schools we don't collect for),
# word-bounded so "mit" can't match Smithsonian/Smiths/Smith+Nephew.
_PRESTIGE_ORG_RE = re.compile(r"\b(?:caltech|mit|stanford|cmu|berkeley|nasa|doe)\b")


def _is_actionable(opportunity: dict) -> bool:
    """The student can act on this result. An email-outreach posting
    (contact_method='email' — every faculty record) is actionable only with an
    actual address: faculty collectors stamp the PROFILE url into
    application_url, so that field proves nothing for them. For real
    application flows (website/form) the URL is the action.

    The email bar is the SAME authoritative predicate the reveal/send flow
    uses (backend.lib.contact_visibility.verified_send_target): non-
    synthesized source AND exact identity-bound evidence AND exact verified
    email AND a safe, matching source URL AND a fresh timestamp. A record the
    product would refuse to reveal must never win a ranking tie as
    "actionable" — imported directly rather than re-approximated here, so the
    two bars can never drift apart again."""
    if verified_send_target(opportunity):
        return True
    app = opportunity.get("application") or {}
    if app.get("contact_method") == "email":
        return False
    return bool(app.get("application_url"))


def _evidence_rank(opportunity: dict) -> int:
    """Tie-break ladder: 2 fully-bound email > 1 legacy email or a real
    application URL > 0 dead end. Fully-proven evidence outranks the W7a
    legacy pass-through in a tie (the truthfulness contract), while a
    legacy address still outranks a record the student cannot act on at
    all."""
    strength = send_target_strength(opportunity)
    if strength:
        return strength
    app = opportunity.get("application") or {}
    if app.get("contact_method") == "email":
        return 0
    return 1 if app.get("application_url") else 0


@dataclass
class MatchResult:
    opportunity_id: str
    eligibility_score: float
    readiness_score: float
    upside_score: float
    final_score: float
    bucket: str  # "high_priority" | "good_match" | "reach" | "low_fit"
    reasons_fit: list[str]
    reasons_gap: list[str]
    next_steps: list[str]
    # True when the opportunity's keywords topically match the student's stated
    # interests OR their major-derived field — used for the "N strong matches in
    # your field" count so a thin field isn't padded by generic high-quality opps.
    field_relevant: bool = False
    # The student can act on this result (a direct email or an application URL).
    # Scores round to 0.1 and keyword-thin schools produce 8-way tie walls, so
    # within a tie the actionable result must outrank the dead-end one — the
    # audit found #1 matches with no email while equal-scored peers had one.
    actionable: bool = True
    # Tie-break evidence ladder (see _evidence_rank): 2 bound email, 1 legacy
    # email / application URL, 0 dead end.
    evidence_rank: int = 1
    # One concrete, student-specific sentence from the LLM rerank pass (the
    # card's lead line for top-K results). None outside the reranked window or
    # when the rerank is unavailable — the rule reasons are always the floor.
    ai_reason: str | None = None
    # Canonical unknown semantics: the inputs whose missing/unknown state left
    # this decision less certain (dotted "profile.*" / "opportunity.*" names).
    # Unknown NEVER silently becomes eligible/ineligible — each listed field was
    # scored with its documented neutral policy (see docs/matching_logic.md),
    # and this list is the machine-readable trace of that.
    unknowns: list[str] = field(default_factory=list)


def canonical_sort_key(r: "MatchResult"):
    """THE result ordering: score desc, then actionable-first, then id — a
    total order (ids are unique), so equal-score bands can never reorder
    between requests or paginate inconsistently. Every consumer that sorts
    MatchResults (rank_all, semantic_rerank, the route-level LLM rerank) must
    use this key; a bare `final_score` sort silently drops the tie-break
    contract."""
    return (-r.final_score, -r.evidence_rank, r.opportunity_id)


# --- Field matching utilities ---

MAJOR_GROUPS = {
    "ECE": {"ECE", "Electrical Engineering", "Computer Engineering", "Electrical & Computer Engineering",
            "Electrical and Computer Engineering", "Neural Engineering"},
    "CS": {"CS", "Computer Science", "Mathematics & Computer Science",
           "Statistics & Computer Science",
           "Computer Science + Advertising", "Computer Science + Animal Sciences",
           "Computer Science + Anthropology", "Computer Science + Astronomy",
           "Computer Science + Bioengineering", "Computer Science + Chemistry",
           "Computer Science + Crop Sciences", "Computer Science + Economics",
           "Computer Science + Education", "Computer Science + Geography & GIS",
           "Computer Science + Linguistics", "Computer Science + Music",
           "Computer Science + Philosophy", "Computer Science + Physics"},
    "STAT": {"STAT", "Statistics", "Data Science", "Statistics & Computer Science", "Actuarial Science",
             "Econometrics & Quantitative Economics"},
    "IS": {"IS", "Information Sciences", "iSchool", "Information Sciences + Data Science", "Information Systems"},
    "MATH": {"MATH", "Mathematics", "Applied Math", "Applied Mathematics", "Mathematics & Computer Science"},
    "PHYS": {"Physics", "PHYS", "Applied Physics", "Engineering Physics", "Astrophysics", "Astronomy"},
    "CHEME": {"Chemical Engineering", "Chemical & Biomolecular Engineering", "Biochemistry"},
    "BIOE": {"Bioengineering", "BioE", "Biomedical Engineering"},
    "MECHSE": {"MechSE", "Mechanical Engineering", "Engineering Mechanics"},
    "CEE": {"CEE", "Civil Engineering", "Civil & Environmental Engineering", "Environmental Engineering"},
    "MSE": {"MatSE", "Materials Science", "Materials Science & Engineering"},
    "AE": {"Aerospace Engineering", "AE"},
    "IE": {"Industrial Engineering", "Industrial & Enterprise Systems Engineering", "ISE", "Operations Management"},
    "NPRE": {"NPRE", "Nuclear Engineering", "Nuclear, Plasma & Radiological Engineering"},
    "CHEM": {"Chemistry", "CHEM"},
    "BIO": {"Biology", "Integrative Biology", "Molecular & Cellular Biology", "MCB", "Plant Biotechnology",
            "Animal Sciences", "Neuroscience", "Brain & Cognitive Science"},
    "VET": {"Veterinary Medicine", "VET", "Pre-Veterinary Medicine", "Veterinary Sciences"},
    "ECON": {"Economics", "ECON", "Agricultural & Consumer Economics", "Finance"},
    "PSYCH": {"Psychology", "PSYCH"},
    "ACCY": {"Accountancy", "ACCY", "Accountancy + Data Science"},
    "ATMS": {"Atmospheric Sciences", "ATMS", "Earth, Society & Environmental Sustainability", "Geology"},
    "ANTH": {"Anthropology", "ANTH"},
    "SOC": {"Sociology", "SOC", "Social Work"},
    "POLS": {"Political Science", "POLS", "Global Studies", "Latin American Studies"},
    "COMM": {"Communication", "COMM", "Journalism", "Advertising", "Media & Cinema Studies", "Sports Media"},
    "LING": {"Linguistics", "LING", "Applied Linguistics", "TESOL",
             "Second Language Acquisition & Teacher Education", "SLATE"},
    "AGE": {"Agricultural & Biological Engineering", "ABE", "Agronomy", "Crop Sciences",
            "Natural Resources & Environmental Sciences"},
    "SPAN": {"Spanish", "SPAN", "Spanish, Italian & Portuguese", "SIP",
             "Hispanic Studies", "Latin American & Caribbean Studies"},
    "FREN": {"French", "FREN", "French & Francophone Studies"},
    "GERM": {"German", "GERM", "Germanic Languages & Literatures"},
    "EALC": {"East Asian Languages & Cultures", "EALC", "Japanese", "Chinese", "Korean"},
    "SLAV": {"Slavic Languages & Literatures", "SLAV", "Russian"},
    "CWL": {"Comparative & World Literature", "CWL", "Comparative Literature"},
    "ENGL": {"English", "ENGL", "English Literature", "Creative Writing", "Rhetoric & Composition"},
    "HIST": {"History", "HIST", "Medieval Studies"},
    "PHIL": {"Philosophy", "PHIL"},
    "REL": {"Religion", "REL", "Religious Studies"},
    "CLASS": {"Classics", "CLASS", "Classical Civilization"},
    "ART": {"Art", "Studio Art", "Fine Arts"},
    "ARTH": {"Art History", "ARTH"},
    "MUS": {"Music", "MUS", "Music Composition", "Music Education"},
    "JOUR": {"Journalism", "JOUR"},
    "ADV": {"Advertising", "ADV"},
    "GEOG": {"Geography", "GEOG", "Geography & GIS"},
    "GWS": {"Gender & Women's Studies", "GWS"},
    "AFRO": {"African American Studies", "AFRO"},
    "AAS": {"Asian American Studies", "AAS"},
    "LAS": {"Latina/Latino Studies", "LAS"},
    "URB": {"Urban & Regional Planning", "URB"},
}

RELATED_MAJORS = {
    "CS": ["ECE", "IS", "STAT", "MATH", "BIOE"],
    "ECE": ["CS", "PHYS", "MATH", "MECHSE", "MSE"],
    "STAT": ["CS", "IS", "MATH", "ECON"],
    "IS": ["CS", "STAT", "COMM"],
    "MATH": ["CS", "STAT", "PHYS", "ECON"],
    "PHYS": ["ECE", "MATH", "CHEME", "AE", "NPRE", "ATMS"],
    "CHEME": ["CHEM", "BIOE", "MSE", "PHYS"],
    "BIOE": ["CS", "CHEME", "BIO", "ECE"],
    "MECHSE": ["AE", "CEE", "MSE", "ECE"],
    "CEE": ["MECHSE", "ATMS", "AGE"],
    "MSE": ["CHEME", "MECHSE", "PHYS"],
    "AE": ["MECHSE", "PHYS", "ECE"],
    "IE": ["STAT", "CS", "ECON"],
    "CHEM": ["CHEME", "BIO", "PHYS"],
    "BIO": ["CHEM", "BIOE", "PSYCH", "AGE", "VET"],
    "VET": ["BIO", "AGE", "CHEM"],
    "ECON": ["STAT", "MATH", "ACCY", "IE"],
    "PSYCH": ["BIO", "SOC", "LING"],
    "ACCY": ["ECON", "IS"],
    "AGE": ["CEE", "BIO", "CHEM"],
    "COMM": ["IS", "SOC", "POLS", "JOUR", "ADV"],
    "SPAN": ["LING", "FREN", "CWL", "LAS", "ANTH", "HIST"],
    "FREN": ["LING", "SPAN", "CWL", "HIST"],
    "GERM": ["LING", "CWL", "HIST", "PHIL"],
    "EALC": ["LING", "CWL", "HIST", "ANTH"],
    "SLAV": ["LING", "CWL", "HIST"],
    "CWL": ["ENGL", "LING", "SPAN", "FREN", "GERM", "EALC", "SLAV", "PHIL"],
    "ENGL": ["CWL", "LING", "JOUR", "COMM", "PHIL", "HIST"],
    "HIST": ["POLS", "ANTH", "SOC", "CLASS", "PHIL", "REL"],
    "PHIL": ["ENGL", "HIST", "REL", "CLASS", "POLS", "CWL"],
    "REL": ["PHIL", "HIST", "CLASS", "ANTH"],
    "CLASS": ["HIST", "LING", "PHIL", "ARTH"],
    "LING": ["CS", "PSYCH", "SPAN", "FREN", "GERM", "EALC", "SLAV", "CWL", "ENGL"],
    "ART": ["ARTH", "CINE", "COMM"],
    "ARTH": ["ART", "HIST", "CLASS"],
    "MUS": ["ART", "COMM"],
    "JOUR": ["COMM", "ENGL", "POLS", "ADV"],
    "ADV": ["COMM", "JOUR", "PSYCH"],
    "GEOG": ["ATMS", "URB", "CEE", "ANTH"],
    "GWS": ["SOC", "PSYCH", "ANTH", "HIST"],
    "AFRO": ["HIST", "ANTH", "SOC", "POLS"],
    "AAS": ["HIST", "ANTH", "SOC", "EALC"],
    "LAS": ["HIST", "ANTH", "SPAN", "POLS"],
    "URB": ["CEE", "GEOG", "SOC", "POLS"],
    "POLS": ["ECON", "HIST", "SOC", "COMM"],
    "SOC": ["PSYCH", "ANTH", "POLS", "COMM", "GWS"],
    "ANTH": ["SOC", "HIST", "LING", "PSYCH"],
}


# Flattened alias→group lookup (first group wins, matching the original
# iteration order over MAJOR_GROUPS) — rebuilding the upper-cased alias sets on
# every call was ~16% of a warm rank_all.
_MAJOR_ALIAS_LOOKUP: dict[str, str] = {}
for _group, _aliases in MAJOR_GROUPS.items():
    for _alias in _aliases:
        _MAJOR_ALIAS_LOOKUP.setdefault(_alias.upper(), _group)


# Spellings that mean the same field. The taxonomy writes "Materials Science &
# Engineering"; 25 school catalogs offer "Materials Science and Engineering"
# and 433 faculty records carry that spelling, and an exact uppercase lookup
# missed every one. It matters more than a cosmetic miss, because
# MAJOR_TOPIC_KEYWORDS and RELATED_MAJORS are BOTH keyed on the result — so an
# unrecognized major gets no topic steer AND no related-field fallback, which
# is the one case the fallback exists for. 52.8% of the 5,024 entries the
# product's own dropdowns offer resolved to nothing.
_MAJOR_LEAD_IN_RE = re.compile(
    r"^(?:the\s+)?(?:department|school|division|college)\s+of\s+", re.IGNORECASE
)


def _major_lookup_keys(major_upper: str) -> list[str]:
    """The spellings of ``major_upper`` worth trying, most literal first."""
    keys = [major_upper]
    stripped = _MAJOR_LEAD_IN_RE.sub("", major_upper).strip()
    for base in ([stripped] if stripped != major_upper else []) + [major_upper]:
        for swapped in (base.replace(" AND ", " & "), base.replace(" & ", " AND ")):
            keys.append(swapped)
            words = swapped.split()
            # A trailing plural on the LAST word only, in both directions: the
            # taxonomy says "Animal Sciences" and the catalogs offer "Animal
            # Science". Never folded mid-phrase, so "Sciences and Engineering"
            # keeps its first word.
            if words and len(words[-1]) > 3:
                last = words[-1]
                folded = last[:-1] if last.endswith("S") else last + "S"
                keys.append(" ".join(words[:-1] + [folded]))
    return keys


def _normalize_major(major: str) -> str:
    major_upper = major.upper().strip()
    for key in _major_lookup_keys(major_upper):
        group = _MAJOR_ALIAS_LOOKUP.get(key)
        if group is not None:
            return group
    return major_upper


_STEM_MAJORS = frozenset({
    "CS", "ECE", "STAT", "IS", "MATH", "PHYS", "CHEME", "BIOE", "MECHSE",
    "CEE", "MSE", "AE", "IE", "NPRE", "CHEM", "BIO", "VET", "ATMS", "AGE",
})
_HUMANITIES_MAJORS = frozenset({
    "SPAN", "ENGL", "LING", "HIST", "PHIL", "REL", "CLASS", "FREN", "GERM",
    "EALC", "SLAV", "SAME", "CWL", "TESOL", "ART", "ARTH", "MUS", "DANC",
    "THEA", "CINE", "COMM", "JOUR", "ADV",
})
_SOCIAL_SCIENCE_MAJORS = frozenset({
    "PSYCH", "SOC", "ANTH", "POLS", "ECON", "GEOG", "GWS", "AFRO", "AAS",
    "LAS", "URB",
})

# Major → field-typical research keywords. Keyed by the normalized major group
# (`_normalize_major` output). Every token here is verified to exist in the
# corpus keyword vocabulary so the bridge actually has inventory to surface — a
# token with zero corpus presence would be dead weight. Groups with no corpus
# inventory (most humanities) are intentionally omitted: they fall back through
# RELATED_MAJORS, and if that is also empty the student simply gets no implicit
# steer (pure generic quality, unchanged). This is data, not policy.
MAJOR_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "CS": ["machine learning", "artificial intelligence", "software engineering", "data science",
           "computer vision", "natural language processing", "algorithms", "robotics", "deep learning",
           "distributed systems", "cybersecurity", "human-computer interaction"],
    "ECE": ["embedded systems", "hardware", "signal processing", "circuits", "integrated circuits",
            "control systems", "photonics", "power systems", "semiconductor", "networks", "robotics"],
    "STAT": ["statistics", "data science", "machine learning", "optimization", "quantitative finance",
             "causal inference"],
    "IS": ["information science", "data science", "machine learning", "human-computer interaction"],
    "MATH": ["mathematics", "optimization", "statistics", "machine learning", "algorithms"],
    "PHYS": ["physics", "condensed matter physics", "quantum", "photonics", "nanotechnology",
             "astrophysics", "applied physics", "astronomy"],
    "CHEME": ["chemistry", "materials science", "catalysis", "polymer", "drug discovery"],
    "BIOE": ["bioengineering", "computational biology", "neuroscience", "bioinformatics", "biomedical"],
    "MECHSE": ["robotics", "materials science", "control systems"],
    "CEE": ["civil engineering", "environmental sciences", "transportation", "structural engineering",
            "sustainability", "renewable energy"],
    "MSE": ["materials science", "nanotechnology", "condensed matter physics", "polymer", "semiconductor"],
    "AE": ["autonomous systems", "robotics", "control systems"],
    "IE": ["optimization", "operations research", "statistics"],
    "NPRE": ["renewable energy", "materials science", "physics"],
    "CHEM": ["chemistry", "organic chemistry", "physical chemistry", "materials science", "catalysis",
             "spectroscopy", "drug discovery"],
    "BIO": ["integrative biology", "molecular biology", "computational biology", "neuroscience",
            "genomics", "ecology", "bioinformatics", "animal sciences"],
    "VET": ["animal sciences", "integrative biology", "molecular biology", "neuroscience", "genomics",
            "ecology"],
    "ECON": ["economics", "quantitative finance", "statistics", "optimization"],
    "ACCY": ["quantitative finance", "economics", "statistics"],
    "PSYCH": ["psychology", "neuroscience"],
    "ATMS": ["climate", "atmospheric sciences", "remote sensing", "environmental sciences", "geology"],
    "AGE": ["crop sciences", "food science", "animal sciences", "ecology", "sustainability"],
    "LING": ["linguistics", "natural language processing"],
    "POLS": ["political science"],
    "ANTH": ["anthropology"],
    "COMM": ["communication", "communications"],
    "HIST": ["history"],
}

# College → opportunity-`department` substring stems. Opportunities carry no
# usable `college` field (only 26 records), but ~54% carry a free-text
# `department`, so the student's college becomes a signal via stem matching.
# Stems are lowercase and chosen to match the real corpus department strings
# (e.g. "engineering" matches both "Electrical & Computer Engineering" and UCB's
# "Electrical Engineering and Computer Sciences" — sidestepping wording drift).
# Keyed by the frontend college display string (frontend/src/lib/colleges.ts).
COLLEGE_DEPARTMENT_SIGNALS: dict[str, list[str]] = {
    "Grainger College of Engineering": [
        "engineering", "computer scien", "computing", "siebel", "electrical",
        "mechanical", "aerospace", "bioengineering", "materials", "nuclear", "civil",
    ],
    "Liberal Arts & Sciences (LAS)": [
        "physics", "chemistr", "statistic", "mathematic", "molecular & cellular",
        "integrative biology", "psycholog", "econom", "linguistic", "english",
        "histor", "philosoph", "political science", "anthropolog", "sociolog",
        "astronom", "atmospheric", "earth science", "communication",
    ],
    "College of ACES": [
        "crop science", "animal science", "food science", "natural resources",
        "agricultur", "nutrition",
    ],
    "College of Veterinary Medicine": [
        "animal science", "molecular & cellular", "integrative biology",
        "pathobiolog", "comparative", "veterinary",
    ],
    "School of Information Sciences (iSchool)": ["information science"],
    "Gies College of Business": ["econom", "business", "finance", "accountan"],
    "College of Fine & Applied Arts": [
        "music", "art", "architecture", "theatre", "dance", "landscape", "urban",
    ],
    "College of Media": ["journalism", "advertising", "media"],
    "College of Education": ["education", "curriculum"],
    "College of Applied Health Sciences": [
        "kinesiology", "health", "speech", "recreation",
    ],
    "School of Social Work": ["social work"],
}


def _profile_implicit_keywords(profile: dict) -> set[str]:
    """Field-typical keywords derived from the student's major (+ secondary
    interests) — the implicit steer for students who haven't written explicit
    research interests. Reuses `_normalize_major` and falls back through
    `RELATED_MAJORS` so an unmapped major still gets *some* field signal."""
    majors = [profile.get("major", "")] + list(profile.get("secondary_interests", []) or [])
    out: set[str] = set()
    for m in majors:
        if not m:
            continue
        group = _normalize_major(m)
        direct = MAJOR_TOPIC_KEYWORDS.get(group)
        if direct:
            out.update(direct)
        else:
            for rel in RELATED_MAJORS.get(group, []):
                out.update(MAJOR_TOPIC_KEYWORDS.get(rel, []))
    return {k.lower() for k in out}


def _implicit_steer(profile: dict) -> set[str]:
    """The major-derived steer exactly as rank_all gates it: applied ONLY when
    the student gave no explicit interests — with a stated interest, the
    implicit major keywords would compete with and dilute it (e.g. a vet major
    + "computer vision" interest must still surface CV work, not biology). So
    "explicit interests LEAD, major DRIVES the rest" holds by construction.
    Shared by rank_all and rank_opportunity's default path so a single-record
    caller (the explain endpoint) scores identically to the list."""
    has_explicit_interest = (
        len((profile.get("research_interests_text") or "").strip()) >= 4
        or bool(profile.get("desired_fields"))
    )
    return set() if has_explicit_interest else _profile_implicit_keywords(profile)


def _coursework_focus_bonus(profile: dict, opportunity: dict) -> float:
    """Additive lift (0..COURSEWORK_FOCUS_BONUS) for coursework that names this
    professor's field, growing across the right half of the search-focus slider.

    The slider's right-hand label says "Coursework". It used to deliver that by
    raising the readiness layer's weight — but coursework is one fifth of that
    layer, and for a faculty record the other four fifths (resume, experience,
    willingness to cold-email, application effort) are properties of the student
    and identical against every professor in the list. Measured over three
    personas the layer's spread was 0.23-0.88 points against 5.3-15.2 for
    eligibility and upside, and dropping it outright left 21 to 25 of the visible
    top 25 unmoved. So the old right-hand end took ordering power away from
    interest matching and handed it to a constant.

    Zero at and below the midpoint, so the default and interests-led halves of
    the slider score exactly as before.
    """
    sw = max(0, min(100, profile.get("search_weight", 50) or 0))
    if sw <= 50:
        return 0.0
    courses = profile.get("coursework") or []
    if not courses:
        return 0.0
    _, tokens = _course_sets(tuple(courses))
    relevance = _coursework_relevance(opportunity, tokens)
    if relevance <= 0.0:
        return 0.0
    return COURSEWORK_FOCUS_BONUS * ((sw - 50) / 50.0) * (relevance / COURSEWORK_RELEVANCE_BONUS)


def _college_affinity(profile: dict, opportunity: dict) -> float:
    """Additive bonus (0..COLLEGE_AFFINITY_MAX) when the opportunity's department
    matches the student's college. Missing department → 0.0 (never a penalty),
    so the ~46% of records without a department degrade gracefully."""
    college = (profile.get("college") or "").strip()
    stems = COLLEGE_DEPARTMENT_SIGNALS.get(college)
    if not stems:
        return 0.0
    st = _opp_static(opportunity)
    if not st.dept_lower:
        return 0.0
    # A one-word stem has to name a word of the department, not merely appear
    # inside one. "art" is inside "department": matching it as a substring gave
    # a Fine & Applied Arts student the affinity bonus on 86,425 of the 129,328
    # faculty records - two thirds of the corpus, headed by mathematics, English
    # and psychology. Multi-word stems ("political science") are specific enough
    # that plain containment cannot collide.
    return COLLEGE_AFFINITY_MAX if any(
        (stem in st.dept_lower) if " " in stem else _names_a_field(stem, st.dept_words)
        for stem in stems
    ) else 0.0


def _home_school_affinity(profile: dict, opportunity: dict) -> float:
    """Additive bonus (0..HOME_SCHOOL_AFFINITY_MAX) for the student's own
    school when cross-school discovery is on — the home school wins ties
    without outranking a clearly better topical match elsewhere. 0.0 when the
    toggle is off (the visible pool is already home-heavy) or the profile has
    no home school."""
    if not profile.get("include_cross_school"):
        return 0.0
    home = str(profile.get("home_school") or "").strip().lower()
    if not home:
        return 0.0
    return HOME_SCHOOL_AFFINITY_MAX if opportunity.get("school") == home else 0.0


def _responsiveness_bonus(
    opportunity: dict, responsiveness: dict[str, dict] | None
) -> float:
    """Additive bonus (0..3) when aggregated internal signals show students
    recently got replies here: >= RESPONSIVENESS_MIN_N distinct devices made
    contact and >= 1 reached got-reply/interviewing. Tunable via
    OFE_RESPONSIVENESS_BONUS (0 disables); clamped so it can only break ties."""
    if not responsiveness or RESPONSIVENESS_BONUS <= 0:
        return 0.0
    sig = responsiveness.get(opportunity.get("id", ""))
    if not sig:
        return 0.0
    if sig.get("contacted_n", 0) < RESPONSIVENESS_MIN_N or sig.get("replied_n", 0) < 1:
        return 0.0
    return min(RESPONSIVENESS_BONUS, 3.0)


NO_MAJOR_REQUIREMENT = 30.0


def _major_match_score(
    student_majors: list[str],
    required_majors: list[str],
    exploring: bool = False,
    label_only: bool = False,
) -> float:
    """Score the student's major against the opportunity's.

    ``label_only`` says the ``majors`` list NAMES something rather than
    REQUIRING it — see the caller. A match still earns credit either way; a
    mismatch cannot cost anything, because there is nothing to have missed.
    """
    if not required_majors:
        return NO_MAJOR_REQUIREMENT  # No requirement = open, but no signal of good fit

    s_normalized = {_normalize_major(m) for m in student_majors}
    r_normalized = {_normalize_major(m) for m in required_majors}

    if s_normalized & r_normalized:
        return 100.0

    for sm in s_normalized:
        related = RELATED_MAJORS.get(sm, [])
        if any(r in r_normalized for r in related):
            return 70.0

    # A department label the student does not share is not a failed
    # requirement. Score it exactly like a posting that names no major at all —
    # which is what a directory scrape in fact does.
    if label_only:
        return NO_MAJOR_REQUIREMENT

    # An explorer hasn't picked a field, so a "wrong" major is breadth, not a
    # poor fit — lift both mismatch tiers to a single floor so other-domain
    # opportunities aren't buried below same-domain ones.
    if exploring:
        return EXPLORE_MAJOR_MISMATCH_FLOOR

    # Cross-domain mismatch (humanities student ↔ STEM-only opp) is worse
    # than same-domain mismatch (CS ↔ ECE w/o related edge). Penalize harder
    # so a Spanish major doesn't get the same 15 points for a CS-only lab
    # as a CS major gets for a MechSE-only lab.
    def _domain(m: str) -> str:
        if m in _STEM_MAJORS: return "stem"
        if m in _HUMANITIES_MAJORS: return "hum"
        if m in _SOCIAL_SCIENCE_MAJORS: return "soc"
        return "other"

    s_domains = {_domain(m) for m in s_normalized}
    r_domains = {_domain(m) for m in r_normalized}
    # An unrecognised name is UNKNOWN, not a conflict. The three lists name 53
    # majors between them; the corpus carries 1,305 distinct strings in this
    # field across 186,044 records, so "other" is the ordinary case rather than
    # the edge. Reading it as a clash charged every student the cross-domain
    # penalty for Immunology, Cell Biology, Epidemiology, Physiology,
    # Biostatistics — and told a Bioengineering student they conflict with Cell
    # Biology. Unknown falls back to the same-domain tier.
    if "other" in s_domains or "other" in r_domains:
        return 15.0
    if s_domains and r_domains and not (s_domains & r_domains):
        return 8.0

    return 15.0


_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall", "this",
    "that", "these", "those", "it", "its", "they", "their", "them", "we",
    "our", "you", "your", "i", "me", "my", "he", "she", "his", "her",
    "not", "no", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "than", "too", "very", "also", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "over", "out", "up", "down", "off", "then",
    "so", "if", "when", "where", "how", "what", "which", "who", "whom",
    "while", "just", "only", "even", "here", "there", "much", "many",
    "well", "use", "used", "using", "work", "working", "new",
    "including", "include", "includes", "provide", "provides",
    "students", "student", "program", "research", "university",
    "opportunity", "opportunities", "experience", "summer",
})


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{2,}", text.lower()) if w not in _STOP_WORDS]


def _text_similarity(text_a: str, text_b: str) -> float:
    """Corpus-fitted TF-IDF similarity for the upside base layer. Deliberately
    TF-IDF (not embeddings) so the per-pair path is identical to rank_all's
    batched pass and to the list view — embeddings are reserved for the bounded
    semantic_rerank slice, never the always-on whole-corpus base score."""
    try:
        from .embeddings import semantic_similarity_batch
        return semantic_similarity_batch(text_a, [text_b], allow_embeddings=False)[0]
    except ImportError:
        return _token_cosine_similarity(text_a, text_b)
    except (ValueError, RuntimeError):
        return _token_cosine_similarity(text_a, text_b)


def _similarity_corpus(opportunity: dict) -> str:
    """The opportunity-side text the upside layer compares against the student's
    research interests. Shared by score_upside (per-pair) and rank_all (batched)
    so both feed byte-identical input to the similarity backend — and therefore
    produce identical scores."""
    opp_kw_list = [k.lower() for k in opportunity.get("keywords", [])]
    specific_kw = list(dict.fromkeys(kw for kw in opp_kw_list if kw not in _GENERIC_KEYWORDS))
    opp_desc = (opportunity.get("description_raw") or opportunity.get("description_clean") or "").lower()
    # The professor's own stated research areas — often the only topical signal
    # for faculty whose keywords never got past the generic department template.
    # Kept resident by the loader (backend/data_loader._sanitize_opportunity)
    # and included in the TF-IDF fit corpus so these terms aren't dropped OOV.
    research_areas_raw = ((opportunity.get("metadata") or {}).get("research_areas_raw") or "").lower()
    return " ".join(filter(None, [
        opportunity.get("title", ""),
        opportunity.get("lab_or_program", ""),
        " ".join(specific_kw),
        research_areas_raw,
        opp_desc,
    ]))


def _token_cosine_similarity(text_a: str, text_b: str) -> float:
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0

    all_tokens = set(tokens_a) | set(tokens_b)
    count_a = Counter(tokens_a)
    count_b = Counter(tokens_b)

    dot = sum(count_a.get(t, 0) * count_b.get(t, 0) for t in all_tokens)
    mag_a = math.sqrt(sum(v * v for v in count_a.values()))
    mag_b = math.sqrt(sum(v * v for v in count_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _empty_interest_major_bonus(profile: dict, opportunity: dict) -> float:
    """With no stated interests, the major is the only topical signal — yet
    major-DIRECT matches trailed off-field national programs (a CogSci
    freshman's own CogSci faculty sat at #12-15 under a radio-astronomy REU,
    2026-07 audit). Additive lift for opportunities that explicitly want the
    student's major, gated to the empty-interest case: once interests exist,
    the interest bonus takes over and this stays out of the way."""
    if faculty_contact_claims_unverified(opportunity):
        return 0.0
    if len(str(profile.get("research_interests_text") or "").strip()) >= 4:
        return 0.0
    student_majors = [profile.get("major", "")] + (profile.get("secondary_interests") or [])
    student_majors = [m for m in student_majors if m]
    if not student_majors:
        return 0.0
    majors = (opportunity.get("eligibility") or {}).get("majors") or []
    if _major_match_score(student_majors, majors) >= 100.0:
        return EMPTY_INTEREST_MAJOR_BONUS
    return 0.0


def _interest_bonus(profile: dict, opportunity: dict) -> float:
    """Bonus up to +8 points when stated research_interests_text
    tokens show strong literal overlap with opportunity title+keywords.

    Rewards users who write specific interests (e.g. "language study")
    by surfacing postings whose title/keywords contain those tokens,
    even when the eligibility/major score is weak. Capped at +8 so it
    refines ordering without overriding hard eligibility signals.
    """
    interests = str(profile.get("research_interests_text") or "").strip()
    if len(interests) < 4:
        return 0.0

    signal_text = _opp_static(opportunity).signal_text
    if not signal_text:
        return 0.0

    tokens = _interest_bonus_tokens(interests)
    if not tokens:
        return 0.0

    # signal_text is space-padded normalized words; requiring the space before
    # each token = word-boundary at the hit's start. Prefix matches stay
    # ("gene" still hits "genetics"), mid-word ones don't ("gene" no longer
    # hits "eugene" — name-luck put a political scientist in a premed's top-8).
    hits = sum(1 for t in tokens if f" {t}" in signal_text)
    if hits == 0:
        return 0.0
    return min(INTEREST_BONUS_CAP, hits * INTEREST_BONUS_PER_HIT)


_GENERIC_INTEREST_WORDS = frozenset({
    "research", "study", "studies", "interested", "interest", "learning",
    "field", "work", "general", "related", "area", "topic", "stuff",
    "things", "various", "different", "many", "some",
})


SKILL_SYNONYMS: dict[str, set[str]] = {
    "machine learning":  {"ml", "machine learning", "machine-learning"},
    "deep learning":     {"dl", "deep learning", "deep-learning", "neural networks", "neural network", "nn"},
    "natural language processing": {"nlp", "natural language processing", "text mining"},
    "large language models": {"llm", "llms", "large language model", "large language models"},
    "computer vision":   {"cv", "computer vision", "image processing", "image recognition"},
    "data science":      {"data science", "data analysis", "data analytics"},
    "python":            {"python", "python3"},
    "javascript":        {"javascript", "js"},
    "typescript":        {"typescript", "ts"},
    "c++":               {"c++", "cpp"},
    "c#":                {"c#", "csharp", "c sharp"},
    "pytorch":           {"pytorch", "torch"},
    "tensorflow":        {"tensorflow", "tf"},
    "scikit-learn":      {"scikit-learn", "sklearn", "scikit learn"},
    "react":             {"react", "reactjs", "react.js"},
    "next.js":           {"next.js", "nextjs", "next"},
    "node.js":           {"node.js", "nodejs", "node"},
    "sql":               {"sql", "mysql", "postgresql", "postgres", "sqlite"},
    "nosql":             {"nosql", "mongodb", "mongo", "dynamodb", "redis"},
    "aws":               {"aws", "amazon web services"},
    "gcp":               {"gcp", "google cloud", "google cloud platform"},
    "docker":            {"docker", "containerization"},
    "kubernetes":        {"kubernetes", "k8s"},
    "linux":             {"linux", "unix", "bash", "shell"},
    "r":                 {"r", "r language", "rstudio"},
    "matlab":            {"matlab"},
    "statistics":        {"statistics", "statistical analysis", "stat", "stats"},
}

SKILL_IMPLIES: dict[str, list[str]] = {
    "pytorch":       ["deep learning", "machine learning", "python"],
    "tensorflow":    ["deep learning", "machine learning", "python"],
    "scikit-learn":  ["machine learning", "python"],
    "opencv":        ["computer vision", "python"],
    "keras":         ["deep learning", "python"],
    "huggingface":   ["natural language processing", "deep learning", "python"],
    "pandas":        ["data science", "python"],
    "numpy":         ["python"],
    "react":         ["javascript"],
    "next.js":       ["react", "javascript"],
    "flask":         ["python"],
    "django":        ["python"],
    "fastapi":       ["python"],
    "express":       ["javascript", "node.js"],
}


def _build_synonym_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in SKILL_SYNONYMS.items():
        for alias in aliases:
            lookup[alias] = canonical
    return lookup

_SYNONYM_LOOKUP = _build_synonym_lookup()


def _canonicalize_skill(name: str) -> str:
    return _SYNONYM_LOOKUP.get(name.lower().strip(), name.lower().strip())


def _parse_skills(student_skills: list) -> dict[str, float]:
    result: dict[str, float] = {}
    for s in student_skills:
        if isinstance(s, dict):
            name = s.get("name", "").lower().strip()
            level = s.get("level", "experienced")
            weight = PROFICIENCY_WEIGHTS.get(level, 0.75)
        elif isinstance(s, str):
            name = s.lower().strip()
            weight = 1.0
        else:
            name = getattr(s, "name", "").lower().strip()
            level = getattr(s, "level", "experienced")
            weight = PROFICIENCY_WEIGHTS.get(level, 0.75)

        canonical = _canonicalize_skill(name)
        result[canonical] = max(result.get(canonical, 0), weight)
        result[name] = max(result.get(name, 0), weight)

        for implied in SKILL_IMPLIES.get(canonical, []):
            impl_canon = _canonicalize_skill(implied)
            result[impl_canon] = max(result.get(impl_canon, 0), weight * 0.6)

    return result


def _skill_overlap_score(
    student_skills: list,
    required_skills: list[str],
    skill_map: dict[str, float] | None = None,
) -> float:
    if not required_skills:
        return 35.0

    # skill_map is the caller-precomputed _parse_skills(student_skills); rank_all
    # passes it so the (identical) profile skills are parsed once, not per opp.
    skill_weights = skill_map if skill_map is not None else _parse_skills(student_skills)

    total_weight = 0.0
    for r in required_skills:
        canon = _canonicalize_skill(r)
        w = skill_weights.get(canon, 0.0)
        if w == 0.0:
            w = skill_weights.get(r.lower().strip(), 0.0)
        total_weight += w

    max_possible = len(required_skills) * 1.0
    ratio = total_weight / max_possible if max_possible > 0 else 0.0
    if ratio <= 0.0:
        return 10.0
    return min(100.0, ratio * 100)


_COURSE_WORD_RE = re.compile(r"[a-z0-9]+")
# Connectives carry no field information, and a student who types a course as a
# sentence ("Introduction to Biology") would otherwise match every keyword that
# happens to contain "to".
_COURSE_STOPWORDS = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is", "it",
    "its", "of", "on", "or", "the", "to", "with",
})
# Below this a token is an initialism, not a morpheme.
_FIELD_STEM_MIN = 4


def _names_a_field(token: str, words: frozenset[str]) -> bool:
    """True when ``token`` names the field that ``words`` describe.

    Substring matching over raw strings let a short token count wherever its
    letters turned up: "CS" sits inside economics, genomics, statistics and
    American politics, and "art" sits inside "department". A token means
    something as a word, or as the stem inside a longer one when it is long
    enough to be a morpheme ("chemistr" -> biochemistry, "physics" ->
    astrophysics). It means nothing as a run of letters through the middle of
    an unrelated word.
    """
    if token in words:
        return True
    return len(token) >= _FIELD_STEM_MIN and any(token in w for w in words)


def _course_touches(course_tokens: frozenset[str], signal_words: frozenset[str]) -> bool:
    """True when a student's coursework plausibly names the field of a keyword.

    18,765 faculty records - 14.5% of the corpus - scored as coursework-relevant
    for a student whose courses were CS 3500 and MATH 2270, and the ones the old
    substring rule ranked highest were the wrong ones.
    """
    return any(_names_a_field(word, signal_words) for word in course_tokens)


def _coursework_score(
    student_courses: set[str] | frozenset[str],
    opportunity: dict,
    course_tokens: frozenset[str] | None = None,
) -> float:
    """Score coursework on count + relevance to the opportunity.

    Count alone caps at COURSEWORK_MAX_FROM_COUNT (70) so a student who
    listed 7 generic courses doesn't get a perfect score; relevant courses
    (course code prefix matches an opportunity keyword/skill, e.g. CS473
    → 'cs' tag, or BIOL420 → biology lab) earn an additional bonus on top.

    ``course_tokens`` is the caller-precomputed token set for
    ``student_courses`` (score_readiness derives both from one cached pass);
    None means build it here.
    """
    if not student_courses:
        return COURSEWORK_UNKNOWN

    # Floored at the unknown value, because that value is a neutral prior for a
    # student who told us nothing — not a score they earned. Without the floor a
    # student who typed one course scored 12 and one who typed two scored 24,
    # both below the 30 handed to a student who left the field blank: answering
    # the question honestly cost you up to 18 points of readiness. Information
    # may move a student up from the prior or leave them level. Never down.
    count_score = min(
        COURSEWORK_MAX_FROM_COUNT,
        max(COURSEWORK_UNKNOWN, len(student_courses) * COURSEWORK_PER_COURSE),
    )

    if course_tokens is None:
        course_tokens = _course_tokens(set(student_courses))

    return min(100.0, count_score + _coursework_relevance(opportunity, course_tokens))


def _coursework_relevance(opportunity: dict, course_tokens: frozenset[str]) -> float:
    """The part of the coursework score that is about THIS opportunity (0..bonus).

    The count component is a property of the student — the same number against
    every professor in a list — so anything that wants coursework to order a
    list has to read this half on its own.
    """
    signals = _opp_static(opportunity).course_signals
    if not signals or not course_tokens:
        return 0.0
    overlap = sum(1 for sig_words in signals if _course_touches(course_tokens, sig_words))
    return min(COURSEWORK_RELEVANCE_BONUS, overlap * 10.0)


_UNDERGRAD_ORDER = ["freshman", "sophomore", "junior", "senior"]


def _is_grad_year(y: str) -> bool:
    """True for a graduate-level year term — the student's own year or a program's
    audience. Guards the "undergraduate" substring trap (it contains "graduate")."""
    y = y.lower().strip()
    if "undergrad" in y:
        return False
    return any(t in y for t in ("phd", "ph.d", "doctoral", "doctorate", "master", "graduate")) \
        or y in {"grad", "ms", "msc"}


def _year_match_score(student_year: str, preferred_years: list[str]) -> float:
    if not preferred_years or "unknown" in [p.lower() for p in preferred_years]:
        return 40.0  # Unknown year pref = can't tell if it fits

    sy = student_year.lower().strip()
    if not sy or sy == "unknown":
        # Unknown STUDENT year gets the same neutral treatment as an unknown
        # opportunity-side preference. It previously fell through to the hard
        # 0.0 — since ~96% of the corpus lists all four undergrad years, a
        # profile with no year was silently scored near-ineligible against
        # essentially everything (unknown → ineligible is exactly the silent
        # conversion the canonical policy forbids).
        return 40.0
    prefs = [p.lower().strip() for p in preferred_years]

    if sy in prefs:
        return 100.0

    # A grad student fits any grad-level opening; an undergraduate-only program is
    # a hard mismatch (a PhD can't take an REU), not "one year off".
    if _is_grad_year(sy):
        return 100.0 if any(_is_grad_year(p) for p in prefs) else 0.0

    # Undergraduate student. A program open generically to "undergraduates" fits
    # any class year; a grad-only program does not; otherwise reward one year off.
    if any("undergrad" in p for p in prefs):
        return 100.0
    if all(_is_grad_year(p) for p in prefs):
        return 0.0
    try:
        s_idx = _UNDERGRAD_ORDER.index(sy)
        for p in prefs:
            if p in _UNDERGRAD_ORDER and abs(s_idx - _UNDERGRAD_ORDER.index(p)) == 1:
                return 50.0
    except ValueError:
        pass

    return 0.0


def _normalize_type_key(value: str) -> str:
    """Canonicalise an opportunity-type string to the form used in the
    affinity dict below: lowercase + spaces collapsed to underscores.

    R69-D: callers that don't come through the home form (share URLs,
    admin debug injection, future API integrations, prefill drift from
    a different vocabulary) can pass values like 'Research' or
    'Summer program'. The affinity dict only has 'research' /
    'summer_program' keys, so any case/format drift previously made
    the function silently return the 30.0 fallback and the matcher
    appended a false 'not your primary target type' concern. Normalising
    on entry keeps the function robust to any caller without forcing
    every upstream to remember the wire format.
    """
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _type_preference_score(seeking_types: list[str], opp_type: str) -> float:
    """Score how well the opportunity type matches user preferences.

    Inputs are normalised via ``_normalize_type_key`` so callers don't
    need to know the canonical form (see R69-D commit for the audit
    trail). Returns 60.0 (neutral) when no preference is stated, 100.0
    on exact match, an affinity score (50-70) for related types, and
    30.0 for unrelated types.
    """
    if not seeking_types:
        return 60.0  # No preference stated
    normalised_seeking = [_normalize_type_key(s) for s in seeking_types if s]
    normalised_opp = _normalize_type_key(opp_type)
    if not normalised_seeking:
        return 60.0
    if normalised_opp in normalised_seeking:
        return 100.0
    type_affinity = {
        ("research", "summer_program"): 70.0,
        ("summer_program", "research"): 70.0,
        ("internship", "summer_program"): 60.0,
        ("summer_program", "internship"): 60.0,
        ("research", "internship"): 50.0,
        ("internship", "research"): 50.0,
    }
    for st in normalised_seeking:
        score = type_affinity.get((st, normalised_opp))
        if score:
            return score
    return 30.0  # Completely different type


# --- Scoring layers ---

def score_eligibility(
    profile: dict,
    opportunity: dict,
    skill_map: dict[str, float] | None = None,
) -> tuple[float, list[str], list[str]]:
    """Score eligibility (0-100). Returns (score, fit_reasons, gap_reasons).

    ``skill_map`` is the precomputed _parse_skills(profile hard_skills); rank_all
    passes it so the profile's skills are parsed once per request, not per opp.
    """
    is_faculty_contact = faculty_contact_claims_unverified(opportunity)
    elig = faculty_safe_eligibility(opportunity)
    reasons_fit = []
    reasons_gap = []

    # Year match (30% weight)
    student_year = (profile.get("year") or "").strip()
    # A class-year list the tagger derived is not a targeting claim, and this
    # layer is 30% of the eligibility score. The tagger read "graduating HIGH
    # SCHOOL seniors" out of one program's own sentence and wrote ['senior'];
    # the majors layer sixty lines below already refuses to grade against a
    # derived list (#862), and preferred_year is stamped by the same tagger in
    # the same call. Passing [] falls through to the neutral 40 that
    # _year_match_score already returns for an unknown year.
    stated_years = (
        [] if is_inferred(opportunity, "eligibility.preferred_year")
        else (elig.get("preferred_year") or [])
    )
    year_score = _year_match_score(student_year, stated_years)
    pref_years = stated_years
    if year_score >= 80:
        reasons_fit.append(f"Accepts {student_year} students")
    elif not student_year or student_year.lower() == "unknown":
        # Neutral 40 (see _year_match_score) — the gap names the actual
        # problem (missing profile data) instead of fabricating a targeting
        # mismatch from a list the student may perfectly fit.
        reasons_gap.append("Add your class year to confirm year eligibility")
    elif year_score < 50:
        if _is_grad_year(student_year) and pref_years and not any(
            _is_grad_year(p) for p in pref_years
        ):
            reasons_gap.append("For undergraduates — not a graduate-level opening")
        else:
            named_years = [p for p in pref_years if p and p.lower() != "unknown"]
            if named_years:
                reasons_gap.append(f"Typically targets {', '.join(named_years)}")

    # Major match (20% weight)
    #
    # On a faculty record `majors` is the DEPARTMENT the professor sits in,
    # copied straight from config (faculty_graph writes
    # `"majors": dept.get("majors", [])`) — a label, never a requirement anyone
    # stated. Grading a mismatch against it invented a constraint the source
    # does not carry, and an expensive one: 80-85% of the 128,449 faculty
    # records missed any given student's major, each losing 20.4 eligibility
    # points, which is 9.2 of final score against a top-100 spread of about 14.
    # Working in another department is the ordinary shape of undergraduate
    # research, not a disqualification.
    #
    # This is the same call `enrich_opportunity` already makes one field over,
    # for the same reason: it refuses to infer skills_required for faculty
    # because a cold-email research contact must not be "routing a
    # research-curious student's match through a skills mismatch they never
    # should have been graded on."
    major_is_label = opportunity.get("source_type") == "faculty_research"
    major_labels = (
        faculty_positive_major_labels(opportunity)
        if major_is_label
        else (elig.get("majors") or [])
    )
    student_majors = [profile.get("major", "")] + (profile.get("secondary_interests") or [])
    major_score = _major_match_score(
        student_majors,
        major_labels,
        exploring=bool(profile.get("exploring")),
        label_only=major_is_label,
    )
    if major_is_label and major_score >= 100:
        reasons_fit.append("This faculty member's department aligns with your major")
    elif major_is_label and major_score >= 70:
        reasons_fit.append("This faculty member's department is related to your major")
    elif major_score >= 100:
        reasons_fit.append(f"Your major ({profile.get('major', '')}) is a direct match")
    elif major_score >= 70:
        reasons_fit.append(f"Your major ({profile.get('major', '')}) is closely related to requirements")
    elif (
        major_score < 50
        and elig.get("majors")
        and not major_is_label
        and not is_inferred(opportunity, "eligibility.majors")
    ):
        # Only a REAL preference list earns a gap: an open posting (majors=[])
        # scores 30 too, and previously emitted the nonsensical gap "Prefers ".
        # A department label earns none either — "Prefers Bioengineering" put a
        # preference in a professor's mouth that no page of theirs states.
        #
        # Nor does a list we derived. uiuc_sro maps a coarse research-area
        # label to a fixed bank of majors — _research_area_to_majors, whose own
        # docstring says "approximate" — so a UW-Madison biology program filed
        # under "Medicine & Health" came out preferring ECE, Physics and CS,
        # and told a biology student so.
        reasons_gap.append(f"Prefers {', '.join(elig.get('majors', []))}")

    intl_score = 100.0
    if profile.get("international_student"):
        friendly = elig.get("international_friendly", "unknown")
        # Honor an explicit citizenship_required flag even when the tagger never
        # reconciled international_friendly (it can stay 'unknown') — otherwise a
        # US-only posting shows an F-1 student a clean ~60 "verify" match instead
        # of a restricted one. Same restriction the 'no' branch applies; matters
        # as domestic / US-only sources enter the corpus.
        if friendly == "no" or elig.get("citizenship_required") is True:
            intl_score = 0.0
            reasons_gap.append("Requires US citizenship or permanent residency")
        elif friendly == "unknown":
            # DQ-6: "unknown" covers 37% of the corpus (mostly internships whose
            # source sponsorship field was blank). For internships specifically,
            # a flat deterrent over-discourages the primary audience — most allow
            # CPT/OPT — so both the score and the message stay verify-don't-rule-out.
            if opportunity.get("opportunity_type") == "internship":
                intl_score = INTL_UNKNOWN_INTERNSHIP_SCORE
                reasons_gap.append(
                    "International eligibility unclear — many internships qualify "
                    "for CPT/OPT; confirm with the employer"
                )
            else:
                intl_score = INTL_UNKNOWN_SCORE
                reasons_gap.append(
                    "International eligibility is not stated — confirm when "
                    "contacting the faculty member"
                    if is_faculty_contact
                    else "International eligibility unclear — verify before applying"
                )
        else:
            reasons_fit.append("Open to international students")

    # Skill overlap (15% weight). Evidence-backed rolling postings such as SRO
    # entries may omit fixed requirements because they adapt to the applicant.
    # A faculty directory contact is not a rolling posting and cannot earn this
    # boost merely because an old collector stamped is_rolling=True.
    required_skills_list = elig.get("skills_required", []) or []
    if (
        not required_skills_list
        and opportunity.get("is_rolling")
        and not faculty_contact_claims_unverified(opportunity)
    ):
        skill_score = 60.0
    else:
        skill_score = _skill_overlap_score(
            profile.get("hard_skills", []),
            required_skills_list,
            skill_map=skill_map,
        )
    student_skill_map = skill_map if skill_map is not None else _parse_skills(profile.get("hard_skills", []))
    required_raw = elig.get("skills_required", [])
    matched_skills = []
    missing_skills = []
    for r in required_raw:
        canon = _canonicalize_skill(r)
        if canon in student_skill_map or r.lower().strip() in student_skill_map:
            matched_skills.append(r)
        else:
            missing_skills.append(r)

    # Whether the requirement list is the program's or ours. 2,767 of the 6,349
    # records carrying required skills — 43.6% — were written by the LLM tagger
    # from page prose that never listed any: a wet-lab biology REU "requires"
    # Python, an undergraduate research consortium "requires" Git. The stamp
    # has been in the data since #826 and nothing in the matcher has ever read
    # it, so those inventions came back to the student as fact, and as a
    # shortfall: "Missing skills: Stata" on a program whose own page lists only
    # timing and a deadline.
    #
    # The score still uses them — they carry a weak topic signal — but no
    # SENTENCE may claim the program requires something nobody said it does.
    requirements_are_ours = is_inferred(opportunity, "eligibility.skills_required")

    if matched_skills:
        skill_detail_parts = []
        raw_skills = profile.get("hard_skills", [])
        level_map = {}
        for s in raw_skills:
            if isinstance(s, dict):
                level_map[s.get("name", "").lower()] = s.get("level", "beginner")
            elif hasattr(s, "name"):
                level_map[getattr(s, "name", "").lower()] = getattr(s, "level", "beginner")

        for r in matched_skills:
            lvl = level_map.get(r.lower(), level_map.get(_canonicalize_skill(r), ""))
            if lvl == "expert":
                skill_detail_parts.append(f"{r} (expert)")
            elif lvl == "experienced":
                skill_detail_parts.append(f"{r} (experienced)")
            else:
                skill_detail_parts.append(r)

        expert_count = sum(1 for r in matched_skills if level_map.get(r.lower(), level_map.get(_canonicalize_skill(r), "")) in ("expert", "experienced"))
        if expert_count >= 2 and skill_score >= 70:
            label = "Strong tech stack fit"
        elif skill_score >= 70:
            label = "Tech stack overlap"
        else:
            label = "Partial skill match"
        if requirements_are_ours:
            reasons_fit.append(f"{label}: {', '.join(skill_detail_parts)}")
        else:
            reasons_fit.append(f"{label}: {', '.join(skill_detail_parts)} — {len(matched_skills)}/{len(required_raw)} required")
    if missing_skills and not requirements_are_ours:
        reasons_gap.append(f"Missing skills: {', '.join(missing_skills)}")

    # Type preference match (15% weight)
    type_score = _type_preference_score(
        profile.get("seeking_type", []),
        opportunity.get("opportunity_type", "")
    )
    _otype_label = opportunity.get("opportunity_type", "").replace("_", " ")
    if type_score >= 80:
        reasons_fit.append(f"Matches your interest in {_otype_label}")
    elif type_score < 50:
        reasons_gap.append(f"This is a {_otype_label} — not your primary target type")

    # Major is the product's core differentiator, so it carries more of the
    # eligibility layer than the original 0.20 (which was too weak to reorder — an
    # exact major match moved final score only ~9%). ELIG_MAJOR_WEIGHT (default
    # 0.24) is moderate on purpose: strong enough to steer, not so strong it
    # OVERRIDES an explicit stated interest. The remaining weight keeps the
    # original year:intl:skill:type = 30:20:15:15 proportion so the layer sums to
    # 1.0. Deliberately NOT a second raw multiplier (the RANK-3 regression) —
    # major fit still lives in exactly one place.
    mw = ELIG_MAJOR_WEIGHT
    rem = 1.0 - mw
    total = (
        rem * 0.375 * year_score
        + mw * major_score
        + rem * 0.25 * intl_score
        + rem * 0.1875 * skill_score
        + rem * 0.1875 * type_score
    )
    return total, reasons_fit, reasons_gap


def score_readiness(profile: dict, opportunity: dict) -> tuple[float, list[str], list[str]]:
    """Score readiness (0-100)."""
    is_faculty_contact = faculty_contact_claims_unverified(opportunity)
    app = {} if is_faculty_contact else (opportunity.get("application") or {})
    reasons_fit = []
    reasons_gap = []

    # Resume (25%)
    resume_score = 100.0 if profile.get("resume_ready") else 30.0
    if not profile.get("resume_ready"):
        if app.get("requires_resume") == "yes":
            reasons_gap.append("Resume required — prepare one before applying")
        else:
            resume_score = 60.0

    # Experience (20%)
    exp_map = {"strong": 100, "some": 70, "beginner": 40, "none": 20}
    exp_score = exp_map.get(profile.get("experience_level", "none"), 20)
    if exp_score >= 70:
        reasons_fit.append(
            "Your experience can support a thoughtful faculty outreach"
            if is_faculty_contact
            else "Your experience level is competitive"
        )
    elif exp_score <= 30:
        reasons_gap.append(
            "Your experience signal is limited — ask what preparation would help"
            if is_faculty_contact
            else "Limited prior experience — position may be competitive"
        )

    student_courses, course_tokens = _course_sets(tuple(profile.get("coursework", []) or []))
    course_score = _coursework_score(student_courses, opportunity, course_tokens=course_tokens)

    # Cold email (15%)
    email_score = 100.0 if profile.get("can_cold_email") else 40.0
    if profile.get("can_cold_email"):
        reasons_fit.append("You're comfortable with direct outreach")

    # Application effort vs readiness (20%)
    effort = app.get("application_effort", "medium")
    effort_map = {"low": 90, "medium": 60, "high": 30}
    effort_score = effort_map.get(effort, 60)
    if effort == "low":
        reasons_fit.append("Low application effort — quick to apply")
    elif effort == "high":
        reasons_gap.append("High application effort — plan time for materials")

    total = 0.25 * resume_score + 0.20 * exp_score + 0.20 * course_score + \
            0.15 * email_score + 0.20 * effort_score
    return total, reasons_fit, reasons_gap


_MENTOR_KEYWORDS = ("mentor", "training", "learn", "guided", "supervision", "teach", "onboard")
_PATHWAY_KEYWORDS = ("publication", "paper", "co-author", "return", "continue", "conference", "thesis")


def score_upside(
    profile: dict,
    opportunity: dict,
    precomputed_sim: float | None = None,
    implicit_keywords: set[str] | None = None,
    desired_overlap: set[str] | None = None,
) -> tuple[float, list[str], list[str]]:
    """Score upside (0-100). ``precomputed_sim`` lets rank_all supply a batched
    research-interest similarity (identical to the per-pair value) instead of
    recomputing it here per opportunity. ``implicit_keywords`` is the student's
    major-derived field steer (see ``_profile_implicit_keywords``).
    ``desired_overlap`` is the caller-precomputed ``_desired_field_overlap``
    result (rank_opportunity computes it once for both this layer and
    field_relevant); None means compute it here."""
    st = _opp_static(opportunity)
    is_faculty_contact = faculty_contact_claims_unverified(opportunity)
    reasons_fit = []
    reasons_gap = []

    # Paid (20%)
    # Canonical unknown policy: null, empty, missing key, and unrecognized
    # enum all collapse to "unknown" → 40. (Previously an explicit null scored
    # 50 while a missing key scored 40 — the same unknown fact, two scores.)
    paid_map = {"yes": 100, "stipend": 80, "unknown": 40, "no": 25}
    paid_value = "unknown" if is_faculty_contact else (opportunity.get("paid") or "unknown")
    paid_score = paid_map.get(paid_value, 40)
    # The score is the record's pay value either way; the SENTENCE is a claim
    # about the program's terms, and 220 records carry a value _detect_paid_
    # from_text read off prose — one of them says only "in many cases, funding
    # or a stipend". An NSF Site keeps the sentence: `policy:` names a
    # published requirement of the funding program, not a reading of its page.
    if paid_score >= 70 and not is_read_off_the_page(opportunity, "paid"):
        reasons_fit.append("Paid opportunity" if paid_score == 100 else "Includes stipend")

    # First-experience friendly (25%). Class-year eligibility is not evidence
    # that a posting welcomes applicants without prior research experience;
    # only the dedicated explicit field may earn this claim.
    first_exp_score = 40.0  # Default: no signal of freshman-friendliness
    if st.first_exp:
        first_exp_score = 100.0
        reasons_fit.append("Explicitly welcomes first-time researchers")

    # On-campus convenience (10%). This is a location signal, never a work-
    # authorization conclusion: employment/funding rules depend on the actual
    # arrangement and cannot be inferred from the campus alone.
    on_campus = None if is_faculty_contact else opportunity.get("on_campus")
    campus_score = 80.0 if on_campus else 50.0
    if on_campus is True:
        opp_school = opportunity.get("school")
        home_school = profile.get("home_school")
        if opp_school and home_school and opp_school == home_school:
            campus_score = 90.0
            reasons_fit.append("At your university")

    # Brand/prestige (15%)
    brand_score = st.brand_score
    if st.brand_reason:
        reasons_fit.append(st.brand_reason)

    mentor_score = st.mentor_score
    pathway_score = st.pathway_score
    if st.pathway_reason and not faculty_contact_claims_unverified(opportunity):
        reasons_fit.append("Potential for publication or long-term involvement")

    keyword_score = 25.0
    opp_keywords = st.kw_set
    desired = set(f.lower() for f in profile.get("desired_fields", []))
    interest_reason = ""
    interest_overlap: set[str] = set()
    if opp_keywords and desired:
        interest_overlap = (
            desired_overlap if desired_overlap is not None
            else _desired_field_overlap(desired, list(st.kw_lower), static=st)
        )
        if interest_overlap:
            keyword_score = min(100.0, 50.0 + len(interest_overlap) * 25)
            interest_reason = f"Matches your interests: {', '.join(sorted(interest_overlap))}"
            reasons_fit.append(interest_reason)

    # Implicit major→topic steer: lifts the 25.0 baseline tier for a student who
    # gave no explicit interests, so changing major actually reorders results.
    # CAPPED at IMPLICIT_MAJOR_KEYWORD_CEILING (below the good_match bucket floor)
    # and max()-folded, so it never raises an opportunity above a real explicit
    # interest match. Silent — explicit/structural signals carry the headline.
    if implicit_keywords and opp_keywords:
        imp_hits = len(opp_keywords & implicit_keywords)
        if imp_hits:
            keyword_score = max(
                keyword_score,
                min(IMPLICIT_MAJOR_KEYWORD_CEILING, 25.0 + imp_hits * IMPLICIT_MAJOR_PER_HIT),
            )

    research_text = (profile.get("research_interests_text") or "").lower()

    specific_kw = st.specific_kw
    lab_label = st.lab_label

    if research_text and (st.has_desc or specific_kw):
        # Both the batched (rank_all) and per-pair sims are corpus-fitted TF-IDF,
        # so the same scale applies either way and the two paths score identically.
        sim = (
            precomputed_sim if precomputed_sim is not None
            else _text_similarity(research_text, _similarity_corpus(opportunity))
        )
        keyword_score = max(keyword_score, min(100.0, 15.0 + sim * SIMILARITY_SCALE_TFIDF))
        if sim > 0.15:
            pre_sim_len = len(reasons_fit)
            # Display only genuine research areas — drop role/format tokens so a
            # job title never reads as a topic ("...work on CV, research assistant").
            display_kw = st.display_kw
            work = ", ".join(display_kw[:3])
            # Name the interest terms that actually overlap the lab's areas rather
            # than echoing a mid-word slice of the student's free-text interests.
            overlap = [kw for kw in display_kw if kw in research_text]
            interest_phrase = ", ".join(overlap[:3])
            if display_kw and lab_label:
                reasons_fit.append(
                    f"Your interest in {interest_phrase} closely matches {lab_label}'s work on {work}"
                    if interest_phrase
                    # No literal overlap: the similarity is between the student's
                    # prose and the lab's description, and the words in `work`
                    # are the lab's, not the student's. A tester whose profile
                    # said "machine learning, artificial intelligence" was told
                    # their interests "align closely with Prof. Tong's work on
                    # security" — the one area they had not mentioned. State
                    # what the lab works on; do not put the alignment in the
                    # student's mouth.
                    else f"{lab_label} also works on {work}"
                )
            elif display_kw:
                reasons_fit.append(
                    f"Your interest in {interest_phrase} closely matches their work on {work}"
                    if interest_phrase
                    else f"They also work on {work}"
                )
            elif lab_label:
                reasons_fit.append(
                    f"Your research background aligns with {lab_label}'s focus area"
                )
            # If the similarity reason re-mentions every keyword from the bare
            # "Matches your interests" reason, that earlier reason is pure
            # repetition — drop it. Partial or disjoint coverage keeps both,
            # since the bare reason still names keywords the similarity reason
            # doesn't.
            if interest_reason and len(reasons_fit) > pre_sim_len:
                if all(kw in reasons_fit[-1] for kw in interest_overlap):
                    reasons_fit.remove(interest_reason)

    has_skill_signal = st.has_skill_signal
    if opportunity.get("source_type") == "faculty_research":
        # Faculty postings (uiuc_faculty + ucb_*_faculty — source_type
        # 'faculty_research' is carried by exactly the faculty collectors) have
        # template-generated descriptions, so the mentor / pathway keyword scans
        # are a flat constant across ~all of them and don't differentiate labs
        # (C4). Redirect their combined weight into keyword_score
        # (research-interest similarity) so faculty are ranked by topical fit
        # instead of a shared constant. Other layers (paid/first-exp/
        # campus/brand) keep their weights.
        if has_skill_signal:
            total = 0.15 * paid_score + 0.15 * first_exp_score + 0.10 * campus_score + \
                    0.10 * brand_score + 0.50 * keyword_score
        else:
            total = 0.10 * paid_score + 0.10 * first_exp_score + 0.10 * campus_score + \
                    0.10 * brand_score + 0.60 * keyword_score
    elif has_skill_signal:
        total = 0.15 * paid_score + 0.15 * first_exp_score + 0.10 * campus_score + \
                0.10 * brand_score + 0.15 * mentor_score + 0.15 * pathway_score + 0.20 * keyword_score
    else:
        total = 0.10 * paid_score + 0.10 * first_exp_score + 0.10 * campus_score + \
                0.10 * brand_score + 0.15 * mentor_score + 0.10 * pathway_score + 0.35 * keyword_score
    return total, reasons_fit, reasons_gap


def _stretch_score(raw: float) -> float:
    """Widen the score distribution so matches spread out visibly.

    The weighted-sum raw score tends to cluster in 45-75 because every
    sub-score has a ~40 default floor for unknowns. We mostly preserve
    raw, but apply a gentle sigmoid pull (strong at the extremes, weak
    in the middle) plus a subtract-midpoint amplification so signal
    differences in the 70-90 zone aren't compressed. Knobs in config.py.
    """
    x = max(0.0, min(100.0, raw))
    sig = 1.0 / (1.0 + math.exp(-STRETCH_SIGMOID_K * (x - STRETCH_MIDPOINT)))
    stretched = sig * 100.0
    blended = (1.0 - STRETCH_BLEND) * x + STRETCH_BLEND * stretched
    return max(0.0, min(100.0, blended))


def _compute_weights(search_weight: int, exploring: bool = False) -> dict[str, float]:
    """Blend scoring weights based on the search_weight slider (0-100).

    0   = pure research interests  → boost upside (keyword/interest matching)
    50  = balanced (default)
    100 = pure resume/experience   → boost readiness (skills, resume, coursework)
    """
    sw = max(0, min(100, search_weight))
    t = sw / 100.0

    # The layer weights are deliberately left alone. Readiness barely varies
    # BETWEEN two faculty records (spread 0.23-0.88 against 5.3-15.2 for the
    # other two layers), which is why the slider needed a coursework term of its
    # own — but it does separate faculty records from programs, because a
    # program states an application effort and a professor does not. Moving its
    # weight to eligibility on the right half was measured and reverted: it sent
    # the first professor a UIUC ECE student sees from rank 42 to rank 256, and
    # left zero faculty in the top 100. Programs carry filled-in eligibility;
    # professors do not, so eligibility weight buys programs.
    elig = WEIGHTS_DEFAULT.eligibility - 0.05 * abs(t - 0.5) * 2
    readiness = (WEIGHTS_DEFAULT.readiness - 0.10) + 0.20 * t
    upside = 1.0 - elig - readiness
    weights = {"eligibility": elig, "readiness": readiness, "upside": max(0.05, upside)}

    if exploring:
        # De-emphasize readiness (resume/skills): an explorer is early-stage and
        # shouldn't rank primarily on application-readiness. Move the freed weight
        # to eligibility + upside (fit + intrinsic appeal). Bounded so readiness
        # never drops below 0.05.
        drop = min(EXPLORE_READINESS_DROP, weights["readiness"] - 0.05)
        if drop > 0:
            weights["readiness"] -= drop
            weights["eligibility"] += drop * 0.5
            weights["upside"] += drop * 0.5

    return weights


_GENERIC_KEYWORDS = frozenset({
    "undergraduate", "research", "summer", "program", "internship",
    "opportunity", "assistant", "student", "uiuc", "illinois",
    "computer science", "artificial intelligence", "machine learning",
    "engineering", "science", "technology", "department",
})

# Tokens too broad to carry topic alignment ON THEIR OWN. A single shared
# "science"/"computer"/"data" token between a CompE/ML student and a
# "computational social science" lab is corpus noise, not a topical match — it
# floated humanities/soc-sci labs into good_match (RANK-9 false promote). A
# multi-word real area still aligns on its distinctive token ("computer VISION",
# "MACHINE learning"); only the lone broad token is suppressed. Deliberately
# curated (NOT derived from _GENERIC_KEYWORDS, which contains the real areas
# "machine learning"/"artificial intelligence" that MUST stay alignable).
_LOW_SIGNAL_ALIGN_TOKENS: frozenset[str] = frozenset({
    "science", "sciences", "scientific", "computer", "computers",
    "computational", "data", "social", "technology", "technologies",
    "engineering", "information", "systems", "system", "studies", "applied",
    "general", "theory", "analysis", "methods", "design", "development",
    "advanced", "modern", "interdisciplinary", "quantitative",
})


# Role / format / process tokens that describe the POSTING, not the lab's
# research area. They are multi-word (so they slip past the single-token
# _GENERIC_KEYWORDS) and would otherwise surface as a fake topical area in
# headlines/reasons (e.g. "...work on computer vision, research assistant, deep
# learning"). Filtered in the DISPLAY paths ONLY — never in
# _extract_specific_keywords, which also feeds _topic_alignment_penalty;
# stripping there would flip a role-only admin row's deserved mismatch penalty
# (0.80) to a neutral 1.0 "unknown" and promote it.
_ROLE_PROCESS_TOKENS = frozenset({
    "undergraduate research", "research assistant", "summer research",
    "research experience", "research opportunity", "reu", "fellowship",
    "paid", "our", "portal",
})


def _topical_keywords(keywords: list[str]) -> list[str]:
    """Drop role/format tokens for display — keep only genuine research areas."""
    return [kw for kw in keywords if kw.lower() not in _ROLE_PROCESS_TOKENS]


def _desired_field_overlap(
    desired: set[str], opp_keywords: list[str], static: "_OppStatic | None" = None
) -> set[str]:
    """Which of the student's desired-field chips align with an opportunity's
    keywords. Exact set intersection (the prior logic) is 100% blind to the
    OpenAlex enrichment: a 'machine learning' chip never matched an enriched
    keyword 'multimodal machine learning', so every enriched faculty was denied
    the strong interest bonus and the 'Matches your interests' reason. This
    mirrors _topic_alignment_penalty's containment matching so credit and
    demotion are symmetric: exact/canonical equality always counts, and bounded
    (len>=4, word-boundary) bidirectional containment adds the long-phrase
    matches. A low-signal single-token chip ('data', 'systems') only counts on
    exact equality, so it can't blanket-match via containment. Returns the CHIP
    labels (what the student asked for) for the reason text."""
    if not desired or not opp_keywords:
        return set()
    if static is not None:
        kws: list[str] | tuple[str, ...] = static.ov_kws
        kw_set: set[str] | frozenset[str] = static.ov_set
        kw_canon: set[str] | frozenset[str] = static.ov_canon
        containment_res: list[re.Pattern[str]] | tuple[re.Pattern[str], ...] = static.containment_res
    else:
        kws = [k.lower().strip() for k in opp_keywords if k and k.strip()]
        kw_set = set(kws)
        kw_canon = {_canonicalize_skill(k) for k in kws}
        containment_res = [
            _word_re(k) for k in kws
            if len(k) >= 4 and not (" " not in k and k in _LOW_SIGNAL_ALIGN_TOKENS)
        ]
    matched: set[str] = set()
    for d in desired:
        dl = d.lower().strip()
        if not dl:
            continue
        dc = _canonicalize_skill(dl)
        if dl in kw_set or dc in kw_canon or dc in kw_set:
            matched.add(d)
            continue
        # A bare low-signal token ("data", "systems") matches only exactly
        # (handled above) — never by containment, which would float it in on
        # any "data visualization"/"distributed systems" keyword.
        if " " not in dl and dl in _LOW_SIGNAL_ALIGN_TOKENS:
            continue
        if len(dl) >= 4:
            dl_re = _word_re(dl)
            if any(dl_re.search(k) for k in kws):
                matched.add(d)
                continue
        # Reverse containment (opp keyword inside the chip) needs the SAME
        # low-signal guard as the chip side above: without it a faculty whose
        # only keyword is a broad department token ("engineering", "science",
        # "systems") word-matches inside a specific chip ("chemical engineering",
        # "computer science") and blanket-credits it into the strong-interest
        # tier. A distinctive keyword ("physics" ⊂ "quantum physics") still
        # counts — only lone broad tokens are suppressed.
        if any(p.search(dl) for p in containment_res):
            matched.add(d)
    return matched


def _extract_specific_keywords(opportunity: dict) -> list[str]:
    keywords = opportunity.get("keywords", [])
    return [kw for kw in keywords if kw.lower() not in _GENERIC_KEYWORDS]


def _extract_research_focus_from_desc(desc: str) -> str:
    if not desc or len(desc) < 30:
        return ""
    noise_prefixes = (
        "research opportunity with",
        "seeking undergraduate",
        "looking for",
        "we are",
        "this position",
        "contact the professor",
        "the program",
        "this program",
        "apply",
    )
    noise_content = ("$", "stipend", "housing", "travel", "compensation", "salary")
    for sentence in desc.split("."):
        s = sentence.strip()
        if len(s) < 15:
            continue
        s_lower = s.lower()
        if any(s_lower.startswith(p) for p in noise_prefixes):
            continue
        if any(n in s_lower for n in noise_content):
            continue
        if len(s) <= 100:
            return s
        # Trim to the last space inside the budget: a hard slice handed the
        # card half a word ("...at Northwestern Uni").
        cut = s[:100].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return cut or s[:100]
    return ""


_BAD_PI_NAMES = frozenset({"learn more", "none", "n/a", "and robotics", "unknown", ""})


def _summarize_research(opportunity: dict) -> str:
    pi = opportunity.get("pi_name") or ""
    if pi.lower().strip() in _BAD_PI_NAMES:
        pi = ""
    metadata = opportunity.get("metadata") or {}
    stated_rank = metadata.get("faculty_title") or opportunity.get("faculty_title") or ""
    # "Prof." is an academic-rank claim, not a generic synonym for anyone in
    # a faculty directory. Keep the person's name useful in the explanation,
    # but earn the honorific from a source-stated professor rank.
    pi_label = f"Prof. {pi}" if pi and is_professor_rank(stated_rank) else pi
    lab = faculty_safe_lab_or_program(opportunity)
    dept = opportunity.get("department", "")
    # NOT for a faculty record: neutralize_unverified_faculty_claims overwrites
    # both description fields on every one of them with prose this product
    # generates, so mining it quotes our own filler back to the student under
    # the professor's name. 67,083 records led "Why it fits" with exactly that.
    desc = (
        ""
        if faculty_contact_claims_unverified(opportunity)
        else (opportunity.get("description_raw") or opportunity.get("description_clean") or "")
    )

    # Areas we matched from an OpenAlex author record (surname + institution)
    # are evidence of a topic, not a statement by this person about their own
    # work — and this sentence puts them right after their name. The sibling
    # consumers already refuse the same data: cold_email._stated_keywords
    # returns [] for a stamped record, and public_projection publishes
    # keywords_attribution so the detail page can caveat the chips. Fall
    # through to the lab and description branches, which are read off the
    # professor's own page.
    specific_kw = (
        [] if is_inferred(opportunity, "keywords")
        else _topical_keywords(_extract_specific_keywords(opportunity))
    )
    desc_focus = _extract_research_focus_from_desc(desc)

    lab_has_pi = pi and pi.split()[-1].lower() in lab.lower()

    if pi and lab and specific_kw:
        prefix = lab if lab_has_pi else f"{pi_label}'s {lab}"
        return f"{prefix} — {', '.join(specific_kw[:3])}"
    if pi and specific_kw:
        return f"{pi_label} ({dept or 'UIUC'}) — {', '.join(specific_kw[:3])}"
    if pi and lab:
        prefix = lab if lab_has_pi else f"{pi_label}'s {lab}"
        if desc_focus:
            return f"{prefix}: {desc_focus}"
        return f"{prefix} ({dept})" if dept and dept not in prefix else prefix
    if pi and desc_focus:
        return f"{pi_label}: {desc_focus}"
    if lab and specific_kw:
        return f"{lab} — {', '.join(specific_kw[:3])}"
    if lab:
        return lab
    if specific_kw:
        return ", ".join(specific_kw[:3])
    if desc_focus:
        return desc_focus
    return ""


# Graduate-level role markers. \bgraduate\b cannot match inside
# "undergraduate" (no word boundary before the 'g'), and \bph\.?\s?d\b cannot
# match inside "UR2PhD" (preceded by a digit), so undergrad-facing listings are
# not falsely flagged. Title markers are unambiguous role names; description
# markers require an explicit standing phrase so an undergrad-prep course that
# merely mentions "PhD applications" is not penalized.
_GRAD_TITLE_RE = re.compile(
    r"\bph\.?\s?d\b|\bdoctoral\b|\bdoctorate\b|\bpost-?doc|"
    r"\bgraduate\s+(?:students?|research\s+assistants?|researchers?|interns?)\b|"
    r"\bgrad\s+students?\b|"
    # DQ-5: master's / MBA role titles are grad-level for an undergrad audience.
    # Require the possessive/plural ("master's", "masters") so a trade title like
    # "Master Electrician" is not flagged; \bmba\b is unambiguous. We deliberately
    # do NOT flag bare "graduate <engineer/developer/...>" — those are often
    # entry-level "graduate scheme" titles for new bachelor's grads.
    r"\bmaster'?s\b|\bmba\b",
    re.IGNORECASE,
)
_GRAD_DESC_RE = re.compile(
    r"\b(?:ph\.?\s?d|doctoral|doctorate)\s+(?:student|candidate|program)\b|"
    r"\bpursuing\s+(?:a\s+|an\s+|their\s+)?(?:ph\.?\s?d|doctoral|doctorate|master)|"
    r"\bgraduate\s+students?\s+only\b|"
    r"\bmust\s+be\s+(?:a\s+|currently\s+)?(?:ph\.?\s?d|doctoral|graduate)\s+"
    r"(?:student|candidate)\b|"
    r"\b(?:ms|m\.s\.)\s*/\s*ph\.?\s?d\b",
    re.IGNORECASE,
)
_GRADUATE_YEARS = frozenset({
    "graduate", "grad", "masters", "master", "phd", "ph.d", "doctoral", "postdoc",
})


def _requires_graduate_standing(opportunity: dict) -> bool:
    if faculty_contact_claims_unverified(opportunity):
        return False
    title = str(opportunity.get("title", ""))
    if _GRAD_TITLE_RE.search(title):
        return True
    desc = str(opportunity.get("description_clean") or opportunity.get("description_raw") or "")
    return bool(_GRAD_DESC_RE.search(desc))


def _is_undergrad(profile: dict) -> bool:
    return str(profile.get("year", "")).strip().lower() not in _GRADUATE_YEARS


# Broad department fields (a faculty row's keyword[0] after the keyword-pollution
# fix). They name a department, not an individual's research area, so they are
# treated as "no specific area" rather than a topic to align against — otherwise
# a cleaned "physics" row would read as a topic mismatch instead of unknown.
_BROAD_FIELDS = frozenset({
    "computer science", "physics", "chemistry", "mathematics", "biology",
    "molecular biology", "integrative biology", "psychology", "economics",
    "statistics", "information science", "linguistics", "communication",
    "english", "political science", "anthropology", "sociology", "history",
    "philosophy", "geology", "astronomy", "atmospheric sciences",
    "civil engineering", "mechanical engineering", "electrical engineering",
    "chemical engineering", "aerospace", "nuclear engineering",
    "industrial engineering", "bioengineering", "materials science",
    "animal sciences", "crop sciences", "food science", "environmental sciences",
    "natural resources",
})


def _stem_align_token(t: str) -> str:
    """Fold trivial plurals for alignment comparisons so "robotics" meets
    "robotic manipulation" (2026-07 audit: morphology mismatches re-inverted
    the topic penalty — the only robotics-keyworded ME prof was demoted while
    keywordless REUs escaped)."""
    if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _topic_alignment_penalty(profile: dict, opportunity: dict) -> float:
    """Demote research postings whose area contradicts a student's stated
    interests. Returns a multiplier in (0, 1].

    Only research postings are judged, and only when the student named at least
    two specific interest tokens (otherwise there is nothing to align against,
    so the multiplier is a no-op 1.0). A posting's curated keywords, minus broad
    department fields, are the topic signal:

      - a keyword aligns with the interest               -> aligned (1.0)
      - the posting has specific keywords, none align    -> mismatch penalty
      - the posting has no specific keywords (unknown)   -> TOPIC_UNKNOWN_PENALTY
        (defaults to 1.0: an unenriched lab is a data gap, not a poor fit)

    Alignment matches on exact token equality, canonical-form equality (so the
    acronym "nlp"/"ml"/"cv" the student typed lines up with a full-phrase
    keyword and vice-versa), or a len>=4 substring containment (which avoids the
    "computer" / "computers and education" false positive per-token matching had).
    """
    if opportunity.get("opportunity_type", "") != "research":
        return 1.0

    # An explorer should see other research areas, not be steered off them — a
    # topic "mismatch" is exactly the breadth they're looking for, so no penalty.
    if profile.get("exploring"):
        return 1.0

    interest = (profile.get("research_interests_text") or "").strip().lower()
    interest_tokens, interest_canon = _topic_interest_sets(interest)
    if len(interest_tokens) < 2:
        return 1.0

    st = _opp_static(opportunity)
    if not st.topic_has_specific:
        return TOPIC_UNKNOWN_PENALTY

    # Align over the FULL keyword list (minus broad department fields), not just
    # `specific`: a curated keyword like "machine learning"/"artificial
    # intelligence" is dropped from `specific` as a corpus-broad area, but when
    # it IS the student's stated interest it is a true alignment, not a data gap.
    # Without this, an ML/NLP/LLM lab whose only "specific" keyword was "natural
    # language processing" got the mismatch penalty for an ML student whose best
    # signal ("machine learning") had been stripped (RANK-9 false demote). The
    # `specific` gate above still decides whether the lab has ANY topic signal at
    # all, so this does not start penalizing broad-field-only labs.
    interest_meaningful = interest_tokens - _LOW_SIGNAL_ALIGN_TOKENS
    # Stemmed comparison folds singular/plural topic variants (#443); the
    # keyword side is pre-stemmed into topic_candidates at corpus load.
    interest_stems = frozenset(_stem_align_token(t) for t in interest_meaningful)
    for kw, canon, keyword_stems in st.topic_candidates:
        # Whole-token / canonical equality aligns regardless of length, so a
        # short acronym keyword ("nlp") or a short canonicalized interest still
        # matches. The len>=4 gate is kept only for loose substring containment,
        # which guards "computer" from matching inside "computers and education".
        exact = (
            kw in interest_tokens
            or canon in interest_canon
            or canon in interest_tokens
        )
        substring = (len(kw) >= 4 and kw in interest) or (
            canon != kw and len(canon) >= 4 and canon in interest
        )
        # Token overlap must share a MEANINGFUL (non-broad, non-filler) token.
        # The prior check fired on any shared non-stopword token, so a lone
        # "science"/"computer"/"data" floated a "computational social science"
        # lab in for a CompE/ML profile (RANK-9 false promote). A genuinely
        # off-topic lab (zero shared meaningful token) still gets the mismatch
        # penalty, and a student who typed the exact broad phrase still aligns
        # via the `substring` check above.
        if exact or substring or (keyword_stems & interest_stems):
            return 1.0
    return TOPIC_MISMATCH_PENALTY


def _seasonal_multiplier(opportunity: dict, today=None) -> float:
    """Return a >=1.0 lift for summer-research postings during the apply-for-
    summer window (Feb-Jul by default). Gated to opportunity_type
    'summer_program' so a non-seasonal posting's score is never perturbed.

    ``today`` is injectable for deterministic tests; defaults to the wall clock.
    """
    if not SEASONAL_BOOST_ENABLED:
        return 1.0
    if opportunity.get("opportunity_type") != "summer_program":
        return 1.0
    from datetime import date
    if today is None:
        today = date.today()
    # Only a verifiably-open application window earns the lift. 279 dateless
    # summer records (closed 2026 cycles that can never expire) monopolized
    # July top-15s through this multiplier — a record with no future deadline
    # gets a neutral 1.0, not a boost (2026-07 audit).
    try:
        dl = date.fromisoformat((opportunity.get("deadline") or "")[:10])
    except ValueError:
        return 1.0
    if dl < today:
        return 1.0
    if today.month in SEASONAL_BOOST_MONTHS:
        return SEASONAL_BOOST_FACTOR
    return 1.0


# --- Corpus precompute ---
#
# Everything below hoists per-record work that is PROFILE-INDEPENDENT (keyword
# normalization, description keyword scans, static regex results, parsed
# deadlines) out of the per-request scoring loop. `register_corpus` is called
# by the backend data loader whenever the corpus (re)loads; invalidation is
# by list identity — a reload builds a new list, so stale statics can never
# be served. Records are treated as immutable between reloads (they are:
# nothing mutates them after _sanitize_opportunity). Unregistered dicts
# (unit tests, ad-hoc callers) are computed fresh per call and never cached,
# so behavior — including mutation between calls — is unchanged for them.

@dataclass(slots=True)
class _OppStatic:
    kw_lower: tuple[str, ...]
    kw_set: frozenset[str]
    specific_kw: tuple[str, ...]
    display_kw: tuple[str, ...]
    ov_kws: tuple[str, ...]
    ov_set: frozenset[str]
    ov_canon: frozenset[str]
    containment_res: "tuple[re.Pattern[str], ...]"
    course_signals: tuple[frozenset[str], ...]
    first_exp: bool
    brand_score: float
    brand_reason: str | None
    mentor_score: float
    pathway_score: float
    pathway_reason: bool
    has_desc: bool
    has_skill_signal: bool
    lab_label: str
    signal_text: str
    dept_lower: str
    dept_words: frozenset[str]
    topic_candidates: tuple[tuple[str, str, frozenset[str]], ...]
    topic_has_specific: bool
    requires_grad: bool
    research_summary: str
    deadline_date: date | None


def _build_opp_static(opp: dict) -> _OppStatic:
    is_faculty_contact = faculty_contact_claims_unverified(opp)
    keywords = opp.get("keywords", []) or []
    kw_lower = tuple(k.lower() for k in keywords)
    kw_set = frozenset(kw_lower)
    specific_kw = tuple(dict.fromkeys(kw for kw in kw_lower if kw not in _GENERIC_KEYWORDS))
    # display_kw is prose only ("...'s work on X", "They also work on X"), so
    # emptying it for guessed areas drops the authorship claim while leaving
    # specific_kw — which gates and feeds the similarity score — untouched.
    display_kw = (
        () if is_inferred(opp, "keywords")
        else tuple(kw for kw in specific_kw if kw not in _ROLE_PROCESS_TOKENS)
    )

    # _desired_field_overlap's view of the keywords (stripped, non-empty).
    ov_kws = tuple(k.lower().strip() for k in keywords if k and k.strip())
    ov_canon = frozenset(_canonicalize_skill(k) for k in ov_kws)
    # Patterns pre-compiled through the corpus-scoped intern dict: keyword
    # vocabulary cycles far past any per-request LRU, so a bounded cache
    # thrashed to 100% miss and re-compiling was the top warm-path cost.
    containment_res = tuple(
        _kw_word_re(k) for k in ov_kws
        if len(k) >= 4 and not (" " not in k and k in _LOW_SIGNAL_ALIGN_TOKENS)
    )

    dept_lower = (opp.get("department") or "").lower()
    elig = faculty_safe_eligibility(opp)
    # One word-set per keyword / required skill: the count of distinct signals a
    # student touches is what earns the relevance bonus, so they stay separate.
    course_signals = tuple(dict.fromkeys(
        ws for ws in (
            frozenset(_COURSE_WORD_RE.findall(sig.lower()))
            for sig in list(keywords) + list(elig.get("skills_required", []) or [])
            if isinstance(sig, str)
        ) if ws
    ))

    brand_score, brand_reason = 60.0, None
    org = (opp.get("organization") or "").lower()
    if opp.get("school") in REGISTERED_SCHOOLS:
        brand_score = 90.0
        brand_reason = (
            "Faculty profile from a major research university"
            if is_faculty_contact
            else "Major research university — strong resume builder"
        )
    elif _PRESTIGE_ORG_RE.search(org):
        brand_score = 95.0
        brand_reason = (
            "Faculty profile from a recognized research institution"
            if is_faculty_contact
            else "Prestigious institution — strong resume builder"
        )

    # description_clean too: 7,537 of 8,361 listing records (90.1%) keep their
    # prose there, and every other description reader in this file already
    # falls back. Without it mentor and pathway — a quarter to a third of the
    # upside layer for a listing — were the constants 35.0 and 40.0, and the
    # "publication or long-term involvement" reason could never be produced.
    desc = (opp.get("description_raw") or opp.get("description_clean") or "").lower()
    mentor_hits = sum(1 for k in _MENTOR_KEYWORDS if k in desc)
    pathway_hits = sum(1 for k in _PATHWAY_KEYWORDS if k in desc)

    lab = faculty_safe_lab_or_program(opp)
    pi_name = opp.get("pi_name", "")
    clean_pi = pi_name if pi_name and pi_name.lower().strip() not in _BAD_PI_NAMES else ""
    stated_rank = (
        (opp.get("metadata") or {}).get("faculty_title")
        or opp.get("faculty_title")
        or ""
    )
    lab_label = lab or opp.get("department", "")
    if clean_pi:
        lab_label = (
            f"Prof. {clean_pi}"
            if not is_faculty_contact or is_professor_rank(stated_rank)
            else clean_pi
        )

    # Interest-bonus haystack. Two guards against name-luck ranking (a
    # cancer-immunology student's "gene/genomics" tokens put Gene Fridman and
    # THREE Eugenes in her top-15): the professor's name is cut out of the
    # title/lab text, and the text is normalized to space-padded words so the
    # bonus can require a word boundary at the start of each hit.
    signal_parts = [opp.get("title", ""), " ".join(keywords), lab or ""]
    if pi_name:
        signal_parts = [
            re.sub(re.escape(pi_name), " ", part, flags=re.IGNORECASE)
            for part in signal_parts
        ]
    signal_joined = re.sub(r"[^a-z0-9]+", " ", " ".join(signal_parts).lower()).strip()

    deadline = "" if is_faculty_contact else opp.get("deadline", "")
    deadline_date = None
    if deadline and len(deadline) >= 8 and deadline[4] == "-":
        try:
            # [:10] matches _seasonal_multiplier's parse: a timestamped deadline
            # ("2026-05-01T00:00:00") must hit the passed-deadline penalty and
            # the seasonal boost identically, not one but not the other.
            deadline_date = date.fromisoformat(deadline[:10])
        except ValueError:
            pass

    return _OppStatic(
        kw_lower=kw_lower,
        kw_set=kw_set,
        specific_kw=specific_kw,
        display_kw=display_kw,
        ov_kws=ov_kws,
        ov_set=frozenset(ov_kws),
        ov_canon=ov_canon,
        containment_res=containment_res,
        course_signals=course_signals,
        first_exp=(
            not is_faculty_contact
            and elig.get("first_time_researchers") is True
        ),
        brand_score=brand_score,
        brand_reason=brand_reason,
        mentor_score=35.0 + min(55.0, mentor_hits * 20.0),
        pathway_score=40.0 + min(55.0, pathway_hits * 18.0),
        pathway_reason=not is_faculty_contact and pathway_hits >= 2,
        has_desc=bool(opp.get("description_raw") or opp.get("description_clean") or ""),
        has_skill_signal=not is_faculty_contact and bool(elig.get("skills_required")),
        lab_label=lab_label,
        signal_text=f" {signal_joined} " if signal_joined else "",
        dept_lower=dept_lower,
        dept_words=frozenset(_COURSE_WORD_RE.findall(dept_lower)),
        topic_candidates=tuple(
            (
                kw,
                _canonicalize_skill(kw),
                frozenset(
                    _stem_align_token(t) for t in _tokenize(kw)
                    if t not in _GENERIC_INTEREST_WORDS and t not in _LOW_SIGNAL_ALIGN_TOKENS
                ),
            )
            for kw in kw_lower if kw not in _BROAD_FIELDS
        ),
        topic_has_specific=any(
            k.lower() not in _BROAD_FIELDS for k in _extract_specific_keywords(opp)
        ),
        requires_grad=False if is_faculty_contact else _requires_graduate_standing(opp),
        research_summary=_summarize_research(opp),
        deadline_date=deadline_date,
    )


_STATIC_CACHE_MAX = 8192
_SIMILARITY_CHUNK_SIZE = 1024

_corpus_ref: list[dict] | None = None
# Object identity -> row in the registered TF-IDF matrix.  Release/profile
# filters return new lists containing the SAME opportunity dicts, so an
# identity map lets those exact survivors reuse the full-corpus matrix without
# rebuilding 130k corpus strings on every request.
_corpus_rows: dict[int, int] = {}
_static_cache: "OrderedDict[int, _OppStatic]" = OrderedDict()
_sim_matrix = None
# A hot corpus reload must never swap the TF-IDF vectorizer/matrix or static
# identity map halfway through one score traversal. data_loader acquires this
# same re-entrant lock around fit+register; public single-record scoring and
# the full iterator acquire it while reading the generation.
corpus_generation_lock = threading.RLock()


def _opp_static(opp: dict) -> _OppStatic:
    object_id = id(opp)
    st = _static_cache.get(object_id)
    if st is not None:
        _static_cache.move_to_end(object_id)
        return st
    st = _build_opp_static(opp)
    if object_id in _corpus_rows and _STATIC_CACHE_MAX > 0:
        _static_cache[object_id] = st
        _static_cache.move_to_end(object_id)
        while len(_static_cache) > _STATIC_CACHE_MAX:
            _static_cache.popitem(last=False)
    return st


def register_corpus(opportunities: list[dict]) -> None:
    """Bind the ranker's per-record precompute to a loaded corpus. Idempotent
    per list object; call again with the freshly-loaded list on reload. The
    per-record statics build lazily on first use (no reload-time transient);
    the TF-IDF row matrix builds eagerly in bounded chunks."""
    with corpus_generation_lock:
        _register_corpus_unlocked(opportunities)


def registered_corpus_identity() -> int | None:
    """Identity of the corpus backing the current TF-IDF/static generation."""
    with corpus_generation_lock:
        return id(_corpus_ref) if _corpus_ref is not None else None


def registered_corpus_identity_nowait() -> int | None:
    """Best-effort identity probe that never waits behind an active scorer.

    ``_corpus_ref`` is published only after the replacement matrix/maps are
    complete. A mismatch is therefore a reason to enter the locked register
    path; a match lets cache-hit requests avoid blocking the async event loop.
    The worker still performs the authoritative locked generation check.
    """
    return id(_corpus_ref) if _corpus_ref is not None else None


def _register_corpus_unlocked(opportunities: list[dict]) -> None:
    global _corpus_ref, _corpus_rows, _static_cache, _sim_matrix
    if opportunities is _corpus_ref:
        return
    # Build every potentially failing replacement before publishing any
    # generation global. A matrix allocation/transform failure must leave the
    # previous corpus rows, matrix and caches usable.
    replacement_rows = {id(o): i for i, o in enumerate(opportunities)}
    replacement_matrix = _build_sim_matrix(opportunities)
    _corpus_rows = replacement_rows
    _static_cache = OrderedDict()
    _sim_matrix = replacement_matrix
    _corpus_ref = opportunities
    _kw_word_res.clear()


def _build_sim_matrix(opportunities: list[dict]):
    try:
        from scipy.sparse import vstack

        from . import embeddings as _emb
    except ImportError:
        return None
    if not _emb._tfidf_fitted or _emb._tfidf_vectorizer is None or not opportunities:
        return None
    chunk = 4096
    blocks = [
        _emb._tfidf_vectorizer.transform(
            [_similarity_corpus(o) for o in opportunities[i:i + chunk]]
        )
        for i in range(0, len(opportunities), chunk)
    ]
    return vstack(blocks, format="csr")


def _corpus_sims_precomputed(research_text: str, opportunities: list[dict]) -> list[float] | None:
    if _sim_matrix is None:
        return None
    rows: list[int] = []
    for opportunity in opportunities:
        row = _corpus_rows.get(id(opportunity))
        if row is None:
            return None
        rows.append(row)
    from sklearn.metrics.pairwise import cosine_similarity

    from . import embeddings as _emb
    q = _emb._tfidf_vectorizer.transform([research_text])
    sims = cosine_similarity(q, _sim_matrix[rows])[0]
    return [float(max(0.0, s)) for s in sims]


@lru_cache(maxsize=4096)
def _word_re(term: str) -> "re.Pattern[str]":
    """Whole-term containment pattern for user-supplied terms (interest chips,
    search queries). Bounded LRU because the terms are user input.

    NOT `\b...\b`. `\b` is a boundary between a word character and a non-word
    one, so `\bc\\+\\+\b` can never match: the character after the `+` would
    have to be a word character for the trailing `\b` to fire, and then the
    `+` would not be the term's end. Every term whose first or last character
    is punctuation matched nothing — c++, c#, f#, .net — including on text
    reading "C++ Developer Intern".

    Asserting "not adjacent to a word character" only at the ends that ARE
    word characters is exactly equivalent to `\b...\b` for an alphanumeric
    term, and correct for the rest.
    """
    escaped = re.escape(term)
    left = r"(?<!\w)" if term[:1].isalnum() or term[:1] == "_" else ""
    right = r"(?!\w)" if term[-1:].isalnum() or term[-1:] == "_" else ""
    return re.compile(rf"{left}{escaped}{right}")


# Corpus-side intern table for keyword containment patterns — bounded by the
# corpus keyword vocabulary, reset on corpus registration so it can't grow
# across reloads.
_kw_word_res: dict[str, "re.Pattern[str]"] = {}


def _kw_word_re(term: str) -> "re.Pattern[str]":
    pat = _kw_word_res.get(term)
    if pat is None:
        pat = re.compile(rf"\b{re.escape(term)}\b")
        _kw_word_res[term] = pat
    return pat


@lru_cache(maxsize=512)
def _interest_bonus_tokens(interests: str) -> frozenset[str]:
    """Tokens from the free-text interests that may earn the literal-overlap
    bonus. Filters the low-signal align set as well as generic words: a lone
    "systems"/"data"/"computational" token ("AI systems" → "systems") otherwise
    prefix-hits half the corpus ("type systems", "data and information
    systems") and inflated topically-unrelated faculty into an ML student's
    top-10 (2026-07 dogfood: a data-systems-only professor at 96.9). The
    canonical desired-field path still credits real multi-word areas.

    Fallback (adversarial-review HIGH): when EVERY token is low-signal
    ("data science", "information theory"), the broad tokens ARE that
    student's topic — wiping the bonus dropped all on-topic results out of a
    data-science persona's top-25 on the real corpus, below the LLM-rerank
    window. The filter applies only when a distinctive token survives to
    carry the signal."""
    tokens = frozenset(
        t for t in _tokenize(interests) if t not in _GENERIC_INTEREST_WORDS
    )
    specific = frozenset(t for t in tokens if t not in _LOW_SIGNAL_ALIGN_TOKENS)
    return specific or tokens


@lru_cache(maxsize=512)
def _topic_interest_sets(interest: str) -> tuple[frozenset[str], frozenset[str]]:
    """(tokens, canonicalized tokens) for _topic_alignment_penalty. Canonicalize
    the interest tokens too (not just the keyword) so a student who types an
    acronym ("ml", "nlp", "cv") aligns with a posting keyword stored as the
    full phrase, and vice-versa — without this the student's best topical
    match got the MISMATCH penalty (RANK-2)."""
    tokens = frozenset(t for t in _tokenize(interest) if t not in _GENERIC_INTEREST_WORDS)
    return tokens, frozenset(_canonicalize_skill(t) for t in tokens)


@lru_cache(maxsize=512)
def _course_sets(courses: tuple[str, ...]) -> tuple[frozenset[str], frozenset[str]]:
    upper = frozenset(c.upper().strip() for c in courses)
    return upper, _course_tokens(upper)


def _course_tokens(courses: frozenset[str] | set[str]) -> frozenset[str]:
    """The words a student's course list contributes to relevance matching.

    Both the words of the course title and the letters of its code ("CS 225"
    -> {"cs", "225"}), because a code prefix is how a course names its field.
    """
    tokens: set[str] = set()
    for c in courses:
        for word in _COURSE_WORD_RE.findall(c.lower()):
            if len(word) >= 2 and word not in _COURSE_STOPWORDS:
                tokens.add(word)
    return frozenset(tokens)


# Fixed phrasings all come from this module, so prefix matching is stable; an
# unrecognized reason lands mid-pack (tier 4) rather than misfiling.
_REASON_TIERS: tuple[tuple[int, tuple[str, ...]], ...] = (
    # 0 — student-specific topical tie: the reason that answers "why THIS one".
    (0, ("Your interest in ", "Your research interests align",
         "Your research background aligns", "Matches your interests:")),
    # 2 — concrete skill fit.
    (2, ("Strong tech stack fit", "Tech stack overlap", "Partial skill match")),
    # 3 — genuine differentiators of the posting itself.
    (3, ("Explicitly welcomes first-time researchers",
         "Potential for publication", "Deadline in ", "Summer research — in season")),
    # 5 — nice-to-know attributes.
    (5, ("Paid opportunity", "Includes stipend", "At your university")),
    # 6 — boilerplate that is true of half the results page. The brand lines
    # are school-constant (every registered-school result gets one), so they
    # must not occupy a top-3 card slot when specific reasons are scarce.
    (6, ("Accepts ", "Your major (", "Open to international students",
         "Your experience level is competitive",
         "You're comfortable with direct outreach", "Low application effort",
         "Matches your interest in ", "Major research university",
         "Prestigious institution")),
)


def _reason_priority(reason: str) -> int:
    """Display tier for a fit reason — lower shows first. See _REASON_TIERS;
    tier 1 is reserved for the research-summary headline rank_opportunity
    inserts positionally."""
    for tier, prefixes in _REASON_TIERS:
        if reason.startswith(prefixes):
            return tier
    return 4


def _rank_opportunity_unlocked(
    profile: dict,
    opportunity: dict,
    weights: dict[str, float] | None = None,
    precomputed_eligibility: tuple[float, list[str], list[str]] | None = None,
    precomputed_sim: float | None = None,
    today=None,
    implicit_keywords: set[str] | None = None,
    responsiveness: dict[str, dict] | None = None,
) -> MatchResult:
    st = _opp_static(opportunity)

    # Defaults derive from the profile exactly as rank_all does, so a
    # single-opportunity caller (the explain endpoint) scores identically to
    # the list path: same slider/exploring weights, same major-derived
    # implicit steer. rank_all still passes both explicitly (hoisted once per
    # request), so the list path is unchanged.
    if weights is None:
        weights = _compute_weights(
            profile.get("search_weight", 50), exploring=bool(profile.get("exploring"))
        )
    if implicit_keywords is None:
        implicit_keywords = _implicit_steer(profile)

    desired_lc = {f.lower() for f in profile.get("desired_fields", [])}
    desired_overlap = _desired_field_overlap(
        desired_lc, opportunity.get("keywords", []), static=st
    )

    if precomputed_eligibility is not None:
        elig_score, elig_fit, elig_gap = precomputed_eligibility
    else:
        elig_score, elig_fit, elig_gap = score_eligibility(profile, opportunity)
    ready_score, ready_fit, ready_gap = score_readiness(profile, opportunity)
    up_score, up_fit, up_gap = score_upside(
        profile, opportunity,
        precomputed_sim=precomputed_sim,
        implicit_keywords=implicit_keywords,
        desired_overlap=desired_overlap,
    )

    w = weights
    raw = (
        w["eligibility"] * elig_score +
        w["readiness"] * ready_score +
        w["upside"] * up_score
    )

    interest_bonus = _interest_bonus(profile, opportunity)
    major_bonus = _empty_interest_major_bonus(profile, opportunity)
    college_bonus = _college_affinity(profile, opportunity)
    home_bonus = _home_school_affinity(profile, opportunity)
    resp_bonus = _responsiveness_bonus(opportunity, responsiveness)
    course_bonus = _coursework_focus_bonus(profile, opportunity)
    raw = min(100.0, raw + interest_bonus + major_bonus + college_bonus + home_bonus
              + resp_bonus + course_bonus)

    # RANK-3: major fit is already weighted inside score_eligibility (0.20 of the
    # eligibility layer). A separate raw multiplier here double-counted the same
    # signal, deflating mismatches far below the documented weight. Dogfooding
    # confirmed the eligibility term alone keeps a cross-domain mismatch (e.g. a
    # Spanish major vs a CS-only lab) firmly in low_fit, so the multiplier is
    # removed and major fit lives in exactly one place.
    # All confidence-reducing penalties (topic mismatch, passed deadline,
    # grad-level reach) are applied AFTER the stretch transform so each is a
    # clean multiplicative haircut on the final score. Previously the topic
    # penalty multiplied the pre-stretch `raw` while deadline/grad multiplied
    # the post-stretch score — an asymmetry that made the topic penalty's
    # effective magnitude depend non-linearly on where a posting sat on the
    # sigmoid. Now the order is uniform.
    final = _stretch_score(raw)

    topic_penalty = _topic_alignment_penalty(profile, opportunity)
    if topic_penalty < 1.0:
        final *= topic_penalty
        if topic_penalty <= TOPIC_MISMATCH_PENALTY:
            elig_gap.append("Research area looks different from your stated interests")

    if st.deadline_date is not None:
        days_left = (st.deadline_date - date.today()).days
        if days_left < 0:
            final *= DEADLINE_PASSED_PENALTY
            elig_gap.append("Deadline has passed — verify if still accepting applications")
        elif days_left <= 7:
            elig_fit.append(f"Deadline in {days_left} days — apply soon")

    if _is_undergrad(profile) and st.requires_grad:
        final *= GRAD_LEVEL_PENALTY
        elig_gap.append("Targets graduate / PhD students — a reach for undergraduates")

    # Seasonal boost: a summer-research posting is most actionable in the
    # spring-into-summer apply window. Multiplicative lift, capped at 100, so it
    # nudges ordering without overriding hard eligibility signals.
    seasonal = _seasonal_multiplier(opportunity, today=today)
    if seasonal > 1.0:
        final = min(100.0, final * seasonal)
        elig_fit.append("Summer research — in season; applications are typically active now")

    bucket = "low_fit"
    for threshold, label in BUCKET_THRESHOLDS:
        if final >= float(threshold):
            bucket = label
            break

    # Specific-first ordering: the old elig+ready+up concatenation buried the
    # reasons that actually differentiate THIS opportunity (topical ties, skill
    # fit — generated last, in the upside layer) beneath boilerplate every card
    # shares ("Accepts sophomore students", "major is a direct match"), so the
    # visible top-3 were near-identical across the whole results page
    # (2026-07 dogfood). Stable sort: within a tier, original order holds.
    all_fit = sorted(elig_fit + ready_fit + up_fit, key=_reason_priority)
    all_gap = elig_gap + ready_gap + up_gap
    if faculty_contact_claims_unverified(opportunity):
        all_gap.append(
            "Faculty availability and eligibility are not confirmed — verify when you contact them"
        )

    research_summary = st.research_summary
    if research_summary:
        pi = opportunity.get("pi_name", "")
        # The lab's focus-areas headline reads as context, not personal fit —
        # it slots AFTER a student-specific topical tie when one exists.
        at = 1 if all_fit and _reason_priority(all_fit[0]) == 0 else 0
        if pi and pi in research_summary:
            all_fit.insert(at, research_summary)
        elif opportunity.get("opportunity_type") == "research":
            all_fit.insert(at, f"This lab focuses on {research_summary}")
        # Non-research postings (internships, summer programs) have no "lab" —
        # the "This lab focuses on …" framing is a category error there, and the
        # keyword/interest reasons already convey relevance, so skip it.

    next_steps = _generate_next_steps(profile, opportunity, all_gap)

    # Field-relevant = the opportunity topically matches the student's stated
    # interests OR their major-derived field. Drives the "N strong matches in
    # your field" count so a thin field isn't padded with generic high-quality opps.
    field_relevant = bool(desired_overlap)
    if not field_relevant and implicit_keywords:
        field_relevant = bool(st.kw_set & implicit_keywords)
    if not field_relevant and precomputed_sim is not None and precomputed_sim > 0.15:
        field_relevant = True

    return MatchResult(
        opportunity_id=opportunity.get("id", ""),
        eligibility_score=round(elig_score, 1),
        readiness_score=round(ready_score, 1),
        upside_score=round(up_score, 1),
        final_score=round(final, 1),
        bucket=bucket,
        reasons_fit=all_fit,
        reasons_gap=all_gap,
        next_steps=next_steps,
        field_relevant=field_relevant,
        actionable=_is_actionable(opportunity),
        evidence_rank=_evidence_rank(opportunity),
        unknowns=_decision_unknowns(profile, opportunity),
    )


def rank_opportunity(
    profile: dict,
    opportunity: dict,
    weights: dict[str, float] | None = None,
    precomputed_eligibility: tuple[float, list[str], list[str]] | None = None,
    precomputed_sim: float | None = None,
    today=None,
    implicit_keywords: set[str] | None = None,
    responsiveness: dict[str, dict] | None = None,
) -> MatchResult:
    """Score one record against one immutable registered corpus generation."""
    with corpus_generation_lock:
        return _rank_opportunity_unlocked(
            profile,
            opportunity,
            weights,
            precomputed_eligibility,
            precomputed_sim,
            today,
            implicit_keywords,
            responsiveness,
        )


def _decision_unknowns(profile: dict, opportunity: dict) -> list[str]:
    """The decision-relevant inputs whose missing/unknown state made this
    result less certain — the machine-readable trace of the canonical unknown
    policy. Each listed field was scored with its documented NEUTRAL value
    (never silently converted to eligible/ineligible); surfaces may render
    these as "verify"-style hints but must not reinterpret them."""
    unknowns: list[str] = []
    is_faculty_contact = faculty_contact_claims_unverified(opportunity)
    elig = faculty_safe_eligibility(opportunity)

    student_year = (profile.get("year") or "").strip().lower()
    if not student_year or student_year == "unknown":
        unknowns.append("profile.year")  # scored neutral 40, see _year_match_score
    if not (profile.get("major") or "").strip():
        unknowns.append("profile.major")

    pref_years = elig.get("preferred_year") or []
    if not pref_years or any((p or "").lower() == "unknown" for p in pref_years):
        unknowns.append("opportunity.preferred_year")  # scored neutral 40
    if not (elig.get("majors") or []):
        unknowns.append("opportunity.majors")  # open posting: 30, no gap reason
    if profile.get("international_student") and (
        elig.get("international_friendly", "unknown") or "unknown"
    ) == "unknown" and elig.get("citizenship_required") is not True:
        # verify-don't-rule-out: INTL_UNKNOWN_*_SCORE, never a hard exclusion
        unknowns.append("opportunity.international_friendly")
    paid = "unknown" if is_faculty_contact else (opportunity.get("paid") or "unknown")
    if paid not in ("yes", "stipend", "no"):
        unknowns.append("opportunity.paid")  # scored 40
    effort = (
        None
        if is_faculty_contact
        else (opportunity.get("application") or {}).get("application_effort")
    )
    if effort not in {"low", "medium", "high"}:
        unknowns.append("opportunity.application_effort")
    on_campus = None if is_faculty_contact else opportunity.get("on_campus")
    if on_campus is not True and on_campus is not False:
        unknowns.append("opportunity.on_campus")
    if is_faculty_contact or not opportunity.get("deadline"):
        unknowns.append("opportunity.deadline")  # no penalty, no seasonal boost
    if elig.get("min_gpa") is not None and str(elig.get("min_gpa")).strip():
        # The corpus records GPA floors but the product never collects the
        # student's GPA, so it is NOT evaluated (documented policy) — surfaced
        # here so a GPA requirement is never mistaken for "checked and passed".
        unknowns.append("profile.gpa")
    return unknowns


def _generate_next_steps(profile: dict, opportunity: dict, gaps: list[str]) -> list[str]:
    """Generate actionable next steps based on gaps."""
    steps = []
    is_faculty_contact = opportunity.get("source_type") == "faculty_research"
    raw_app = opportunity.get("application") or {}
    app = {} if is_faculty_contact else raw_app

    # Deadline urgency
    deadline = None if is_faculty_contact else opportunity.get("deadline")
    if deadline:
        steps.append(f"Apply before deadline: {deadline}")

    # Resume
    if not profile.get("resume_ready") and app.get("requires_resume") == "yes":
        steps.append("Prepare a research-focused resume")

    # Cold email. Faculty outreach is a distinct action from an application
    # method: a directory record's application.contact_method is deliberately
    # neutralized. A verified target can still produce a send-ready next step;
    # otherwise the honest action is to verify a channel on the profile.
    if is_faculty_contact and profile.get("can_cold_email"):
        if verified_send_target(opportunity):
            steps.append("Send a brief cold email to the PI expressing interest")
        else:
            steps.append("Open the faculty profile and verify a contact channel")
    elif raw_app.get("contact_method") == "email" and profile.get("can_cold_email"):
        steps.append("Send a brief cold email to the PI expressing interest")

    # Default
    if not steps:
        if is_faculty_contact:
            steps.append(
                "Review the faculty profile and ask whether current research "
                "opportunities are available"
            )
        else:
            steps.append("Review the posting and prepare your application materials")

    return steps


def _profile_query_text(profile: dict) -> str:
    parts: list[str] = []
    interests = profile.get("research_interests_text") or profile.get("research_interests", "")
    if interests:
        parts.append(str(interests))
    major = profile.get("major", "")
    if major:
        parts.append(f"major: {major}")
    for s in profile.get("hard_skills", []) or []:
        if isinstance(s, dict) and s.get("name"):
            parts.append(s["name"])
        elif isinstance(s, str):
            parts.append(s)
    for kw in profile.get("secondary_interests", []) or []:
        parts.append(str(kw))
    return " ".join(parts).strip()


def _opportunity_query_text(opp: dict) -> str:
    parts = [
        opp.get("title", ""),
        opp.get("lab_or_program", "") or "",
        " ".join(opp.get("keywords", []) or []),
        opp.get("description_clean") or opp.get("description_raw") or "",
    ]
    return " ".join(p for p in parts if p)


def _bucket_thresholds(
    result_count: int,
    score_at_descending_index,
) -> tuple[float, float, float]:
    """Return the exact high/good/reach cutoffs for a ranked score universe.

    ``score_at_descending_index`` deliberately abstracts the backing storage:
    the legacy list path reads a sorted ``MatchResult`` list, while the
    low-memory route path reads a score histogram.  Keeping the percentile and
    top-N formula here prevents those two exact representations from drifting.
    """
    floor_high = float(BUCKET_THRESHOLDS[0][0])
    floor_good = float(BUCKET_THRESHOLDS[1][0])
    floor_reach = float(BUCKET_THRESHOLDS[2][0])
    if result_count >= 10:
        p70 = score_at_descending_index(max(0, (result_count * 3) // 10))
        p40 = score_at_descending_index(max(0, (result_count * 6) // 10))
        k = min(HIGH_PRIORITY_TARGET_COUNT, result_count - 1)
        return (
            max(floor_high, score_at_descending_index(k)),
            max(floor_good, p70),
            max(floor_reach, p40),
        )
    return floor_high, floor_good, floor_reach


def _assign_bucket(
    result: MatchResult,
    thresholds: tuple[float, float, float],
) -> None:
    hp_threshold, gm_threshold, reach_threshold = thresholds
    if result.final_score >= hp_threshold:
        result.bucket = "high_priority"
    elif result.final_score >= gm_threshold:
        result.bucket = "good_match"
    elif result.final_score >= reach_threshold:
        result.bucket = "reach"
    else:
        result.bucket = "low_fit"


def _assign_buckets(results: list[MatchResult]) -> None:
    """Assign each result's bucket from its current final_score. Expects results
    sorted by final_score desc. For >=10 results uses the RANK-6 top-N count cap
    + percentile banding; smaller sets fall back to the flat BUCKET_THRESHOLDS
    floors. Mutates in place. Shared by rank_all and semantic_rerank so a
    re-blended score never keeps a stale bucket label."""
    thresholds = _bucket_thresholds(
        len(results),
        lambda index: results[index].final_score,
    )
    for r in results:
        _assign_bucket(r, thresholds)


def semantic_rerank(
    profile: dict,
    results: list[MatchResult],
    opportunities_by_id: dict[str, dict],
    top_k: int = 200,
    semantic_weight: float = 0.5,
) -> list[MatchResult]:
    """Re-rank the top ``top_k`` results using semantic similarity.

    Blend: ``final = (1 - w) * rule_score + w * semantic_score * 100``
    where w = semantic_weight (default 0.5). Only the top slice is
    re-scored to bound embedding cost; the tail keeps its rule score.

    Falls back gracefully to TF-IDF (corpus-fitted) when no OpenAI key
    is available, so this function never raises on missing deps.

    Mutates ``results`` in place AND returns the re-sorted list.
    """
    if not results or top_k <= 0 or semantic_weight <= 0:
        return results

    try:
        from .embeddings import _has_embedding_provider, semantic_similarity_batch
    except ImportError:
        return results

    query = _profile_query_text(profile)
    if not query:
        return results

    slice_end = min(top_k, len(results))
    top_slice = results[:slice_end]

    candidate_texts: list[str] = []
    for r in top_slice:
        opp = opportunities_by_id.get(r.opportunity_id)
        candidate_texts.append(_opportunity_query_text(opp) if opp else "")

    sims = semantic_similarity_batch(query, candidate_texts)

    # When falling back to TF-IDF (no embedding provider), the similarity
    # signal is noisier — it matches generic corpus keywords like "REU" or
    # "undergraduate" and can demote truly relevant labs. Cap the blend weight
    # so rule-based signal dominates. With a provider (OpenAI/Gemini/OpenRouter)
    # the rerank uses real embeddings → full weight applies.
    has_api = _has_embedding_provider()
    effective_weight = semantic_weight if has_api else min(semantic_weight, SEMANTIC_RERANK_FALLBACK_CAP)

    w = max(0.0, min(1.0, effective_weight))
    for r, sim in zip(top_slice, sims, strict=False):
        rule = r.final_score
        blended = (1.0 - w) * rule + w * float(sim) * 100.0
        r.final_score = round(max(0.0, min(100.0, blended)), 1)

    # Deterministic tie-break: scores round to 0.1, so equal-score bands
    # (17-way ties were observed) otherwise reorder whenever corpus file
    # order shifts between refreshes. Within a tie, results the student can
    # act on (email / application URL) come first — the audit found dead-end
    # #1 matches while equal-scored contactable peers sat below them.
    results.sort(key=canonical_sort_key)
    # Buckets were assigned on the pre-blend scores; recompute them so the labels
    # and per-bucket counts match the re-ranked order (semantic=true used to
    # return stale buckets).
    _assign_buckets(results)
    return results


def _diversity_group(opp: dict) -> tuple[str, str]:
    """Coarse (type, area) key for explore-mode de-clustering. The area is the
    posting's first distinctive keyword, falling back to its department, so two
    NLP labs share a group but an NLP lab and a robotics lab do not."""
    otype = opp.get("opportunity_type") or "other"
    area = ""
    for kw in _extract_specific_keywords(opp):
        kl = kw.lower()
        if kl not in _BROAD_FIELDS:
            area = kl
            break
    if not area:
        area = (opp.get("department") or "").lower().strip()
    return (otype, area)


def _round_robin_by_group(
    items: list[MatchResult], key_of: dict[str, tuple[str, str]]
) -> list[MatchResult]:
    """Interleave items across diversity groups, preserving each group's internal
    (score) order. Groups lead in order of their best member, so the strongest
    cluster still comes first but no single cluster monopolizes the top rows."""
    groups: dict[tuple[str, str], list[MatchResult]] = {}
    order: list[tuple[str, str]] = []
    for it in items:
        k = key_of.get(it.opportunity_id, ("other", ""))
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(it)

    if len(order) < 2:
        return items

    out: list[MatchResult] = []
    while len(out) < len(items):
        for k in order:
            bucket = groups[k]
            if bucket:
                out.append(bucket.pop(0))
    return out


def _diversify_explore(
    results: list[MatchResult],
    opportunities_by_id: dict[str, dict],
    *,
    universe_count: int | None = None,
) -> list[MatchResult]:
    """Reorder WITHIN each actionable band (high_priority / good_match / reach)
    so an explorer sees breadth across research areas / opportunity types instead
    of one cluster. Within-bucket only: bucket membership (hence the quality
    floor) is untouched, and the low_fit tail keeps pure score order."""
    # The compact public-universe path drops low-fit objects before calling
    # this helper. Its enable/disable guard must still see the complete scored
    # universe or a 4-total/3-visible edge would diverge from rank_all.
    if (len(results) if universe_count is None else universe_count) < 4:
        return results

    key_of = {
        r.opportunity_id: _diversity_group(opportunities_by_id[r.opportunity_id])
        for r in results
        if r.opportunity_id in opportunities_by_id
    }

    by_bucket: dict[str, list[MatchResult]] = {}
    order: list[str] = []
    for r in results:
        if r.bucket not in by_bucket:
            by_bucket[r.bucket] = []
            order.append(r.bucket)
        by_bucket[r.bucket].append(r)

    for b in ("high_priority", "good_match", "reach"):
        if len(by_bucket.get(b, [])) > 2:
            by_bucket[b] = _round_robin_by_group(by_bucket[b], key_of)

    out: list[MatchResult] = []
    for b in order:
        out.extend(by_bucket[b])
    return out


@dataclass(slots=True)
class _FilterCtx:
    """Per-request context for the hard eligibility filters — hoisted once so
    rank_all and the single-record path (explain) apply IDENTICAL rules."""
    home_school: str
    hide_cross_school: bool
    exclude_citizenship_restricted: bool
    international_student: bool
    seeking: set[str]
    student_majors_norm: set[str]
    related_majors_norm: set[str]


def _filter_context(profile: dict) -> _FilterCtx:
    home_school_raw = str(profile.get("home_school") or "").strip().lower()
    # Cross-school resources are opt-in (Eric, 2026-07: 正常肯定还是会优先本学校的科研).
    # Without a home_school there is no "cross-school" to hide, so such
    # profiles keep the pre-toggle behavior.
    student_majors_norm = {
        _normalize_major(m)
        for m in [profile.get("major", "")] + (profile.get("secondary_interests") or [])
    }
    related_majors_norm: set[str] = set()
    for sm in student_majors_norm:
        related_majors_norm.update(RELATED_MAJORS.get(sm, []))
    return _FilterCtx(
        home_school=home_school_raw or "uiuc",
        hide_cross_school=not profile.get("include_cross_school") and bool(home_school_raw),
        exclude_citizenship_restricted=(profile.get("preferences") or {}).get(
            "exclude_citizenship_restricted", True
        ),
        international_student=bool(profile.get("international_student")),
        seeking=set(profile.get("seeking_type") or []),
        student_majors_norm=student_majors_norm,
        related_majors_norm=related_majors_norm,
    )


def hard_exclusion(opp: dict, ctx: _FilterCtx) -> str | None:
    """THE hard eligibility filter: the single reason-coded implementation of
    every rule that drops a record from a profile's result universe. rank_all
    and the explain endpoint both consume this, so "in your results" can never
    mean different things on different surfaces. Returns a stable reason code,
    or None when the record stays."""
    # Target truth stays the FIRST branch, where the bare is_active check used
    # to live. Order is load-bearing: placed after the school-scope rules below,
    # a closed Berkeley listing would be reported to a non-Berkeley student as
    # "another school's campus posting" — true, but not the reason it is dead.
    # `target_truth` still answers "inactive" for a plain deactivated record, so
    # no existing exclusion changes its code.
    target = target_truth(opp)
    if not target.actionable:
        return target.reason_code
    faculty_status = faculty_availability_status(opp)
    if faculty_status == "not_accepting_undergraduates":
        return "faculty_not_accepting"

    # Multi-university scope (PR #187 Phase 1): another school's campus-only
    # posting is not actionable for this user, so it always drops. The rest of
    # another school's records ('open'/'unknown') are opt-in via
    # include_cross_school — except summer programs, which recruit nationally
    # regardless of host (Eric: 暑期科研肯定是无所谓的). National records
    # (school=None) never enter this branch.
    is_faculty_contact = faculty_contact_claims_unverified(opp)
    opp_school = opp.get("school")
    if opp_school is not None and opp_school != ctx.home_school:
        if not is_faculty_contact and opp.get("audience") == "campus":
            return "other_school_campus"
        if ctx.hide_cross_school and opp.get("opportunity_type") != "summer_program":
            return "cross_school_hidden"

    if ctx.international_student:
        elig = faculty_safe_eligibility(opp)
        if elig.get("international_friendly") == "no" or elig.get("citizenship_required") is True:
            if ctx.exclude_citizenship_restricted:
                return "citizenship_restricted"

    opp_type = opp.get("opportunity_type", "")
    if ctx.seeking and opp_type and opp_type not in ctx.seeking:
        opp_majors = faculty_safe_eligibility(opp).get("majors") or []
        if opp_majors:
            opp_majors_norm = {_normalize_major(m) for m in opp_majors}
            if not (ctx.student_majors_norm & opp_majors_norm):
                if not (ctx.related_majors_norm & opp_majors_norm):
                    return "seeking_type_mismatch"

    return None


def _chunk_similarities(
    research_text: str,
    opportunities: list[dict],
) -> list[float | None]:
    """Exact corpus-fitted TF-IDF similarities for one bounded candidate chunk.

    The fitted vectorizer still represents the complete corpus.  Filtering only
    chooses which already-fitted rows to compare with the query; it never
    refits IDF on a profile-specific subset.  If the corpus precompute is not
    registered (unit/ad-hoc callers), the same vectorizer transforms this
    bounded set directly.  ``None`` preserves rank_opportunity's existing
    per-pair fallback when TF-IDF is unavailable or a batch fails.
    """
    if not research_text or not opportunities:
        return [None] * len(opportunities)
    try:
        import src.matcher.embeddings as _emb

        if not _emb._tfidf_fitted:
            return [None] * len(opportunities)
        sims = _corpus_sims_precomputed(research_text, opportunities)
        if sims is None:
            sims = _emb.semantic_similarity_batch(
                research_text,
                [_similarity_corpus(o) for o in opportunities],
                allow_embeddings=False,
            )
        return [float(s) for s in sims]
    except Exception:
        return [None] * len(opportunities)


def _iter_scored_results_unlocked(
    profile: dict,
    opportunities: list[dict],
    responsiveness: dict[str, dict] | None = None,
):
    """Yield every canonical result while bounding per-request transients.

    Hard exclusions run before TF-IDF. Survivors are scored in small chunks,
    so a 130k corpus never materializes 130k similarity strings, floats, or a
    second full lookup map for one request. We deliberately do not pre-prune
    from a partial layer score: interest, school, responsiveness and seasonal
    bonuses are applied later, so only the fully-computed final score may be
    compared with the profile's minimum threshold.
    """
    search_weight = profile.get("search_weight", 50)
    exploring = bool(profile.get("exploring"))
    weights = _compute_weights(search_weight, exploring=exploring)
    ctx = _filter_context(profile)
    profile_skill_map = _parse_skills(profile.get("hard_skills", []))
    implicit_kw = _implicit_steer(profile)
    research_text = (profile.get("research_interests_text") or "").lower()
    min_threshold = (profile.get("preferences") or {}).get("min_match_threshold", 0)
    pending: list[tuple[dict, tuple[float, list[str], list[str]]]] = []

    def flush_pending():
        chunk_opportunities = [opp for opp, _ in pending]
        sims = _chunk_similarities(research_text, chunk_opportunities)
        for (opp, elig_triple), sim in zip(pending, sims, strict=True):
            # The public wrapper acquires ``corpus_generation_lock`` for
            # standalone callers. This complete traversal already holds that
            # re-entrant lock, so call the implementation directly instead of
            # reacquiring it once per corpus row.
            result = _rank_opportunity_unlocked(
                profile,
                opp,
                weights,
                precomputed_eligibility=elig_triple,
                precomputed_sim=sim,
                implicit_keywords=implicit_kw,
                responsiveness=responsiveness,
            )
            if result.final_score >= min_threshold:
                yield result

    for opp in opportunities:
        if hard_exclusion(opp, ctx) is not None:
            continue

        elig_triple = score_eligibility(profile, opp, skill_map=profile_skill_map)
        pending.append((opp, elig_triple))
        if len(pending) >= _SIMILARITY_CHUNK_SIZE:
            yield from flush_pending()
            pending.clear()
    if pending:
        yield from flush_pending()


def _iter_scored_results(
    profile: dict,
    opportunities: list[dict],
    responsiveness: dict[str, dict] | None = None,
):
    """Yield one complete score traversal from a single corpus generation."""
    with corpus_generation_lock:
        yield from _iter_scored_results_unlocked(
            profile,
            opportunities,
            responsiveness,
        )


def _opportunity_lookup_for_results(
    opportunities: list[dict],
    results: list[MatchResult],
) -> dict[str, dict]:
    result_ids = {result.opportunity_id for result in results}
    return {
        opportunity["id"]: opportunity
        for opportunity in opportunities
        if opportunity.get("id") in result_ids
    }


def rank_all(
    profile: dict,
    opportunities: list[dict],
    responsiveness: dict[str, dict] | None = None,
) -> list[MatchResult]:
    """Rank all opportunities for a profile. Returns sorted by final_score desc."""
    results = list(_iter_scored_results(profile, opportunities, responsiveness))

    # Deterministic tie-break: scores round to 0.1, so equal-score bands
    # (17-way ties were observed) otherwise reorder whenever corpus file
    # order shifts between refreshes. Within a tie, results the student can
    # act on (email / application URL) come first — the audit found dead-end
    # #1 matches while equal-scored contactable peers sat below them.
    results.sort(key=canonical_sort_key)
    _assign_buckets(results)

    if profile.get("exploring"):
        opportunities_by_id = _opportunity_lookup_for_results(opportunities, results)
        results = _diversify_explore(results, opportunities_by_id)

    return results


@dataclass(slots=True)
class RankedMatchUniverse:
    """Exact public Match universe without retaining low-fit result objects."""

    visible: list[MatchResult]
    buckets: dict[str, int]
    field_relevant_count: int


def rank_visible_universe(
    profile: dict,
    opportunities: list[dict],
    responsiveness: dict[str, dict] | None = None,
) -> RankedMatchUniverse:
    """Return the exact non-low-fit universe with bounded result retention.

    Every survivor of the canonical hard/minimum filters is still scored.  A
    compact histogram retains the complete score distribution needed by the
    percentile bucket policy, while full ``MatchResult`` objects below the
    absolute Reach floor are released immediately.  Because the effective
    Reach threshold is always at least that floor, no discarded object could
    become visible.
    """
    floor_reach = float(BUCKET_THRESHOLDS[2][0])
    score_counts: Counter[float] = Counter()
    retained: list[MatchResult] = []

    for result in _iter_scored_results(profile, opportunities, responsiveness):
        score_counts[result.final_score] += 1
        if result.final_score >= floor_reach:
            retained.append(result)

    result_count = sum(score_counts.values())
    descending_bands = sorted(score_counts.items(), reverse=True)

    def score_at(index: int) -> float:
        seen = 0
        for score, count in descending_bands:
            seen += count
            if index < seen:
                return score
        raise IndexError(index)

    thresholds = _bucket_thresholds(result_count, score_at)
    buckets = {"high_priority": 0, "good_match": 0, "reach": 0, "low_fit": 0}
    visible: list[MatchResult] = []
    for result in retained:
        _assign_bucket(result, thresholds)
        buckets[result.bucket] += 1
        if result.bucket != "low_fit":
            visible.append(result)

    # Everything not retained was strictly below the absolute Reach floor and
    # therefore low_fit under every percentile distribution.
    buckets["low_fit"] += result_count - len(retained)
    visible.sort(key=canonical_sort_key)

    if profile.get("exploring"):
        opportunity_lookup = _opportunity_lookup_for_results(opportunities, visible)
        visible = _diversify_explore(
            visible,
            opportunity_lookup,
            universe_count=result_count,
        )

    return RankedMatchUniverse(
        visible=visible,
        buckets=buckets,
        field_relevant_count=sum(1 for result in visible if result.field_relevant),
    )
