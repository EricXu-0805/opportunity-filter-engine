"""Three-layer matching engine. Scores opportunities against a student profile.

Tunable scoring knobs live in `src/matcher/config.py` (importable as
constants here). Hardcoded taxonomies (MAJOR_GROUPS, RELATED_MAJORS,
SKILL_SYNONYMS, SKILL_IMPLIES) still live in this file because they're
data, not policy — moving them to YAML is a separate refactor.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from .config import (
    BUCKET_THRESHOLDS,
    COURSEWORK_MAX_FROM_COUNT,
    COURSEWORK_PER_COURSE,
    COURSEWORK_RELEVANCE_BONUS,
    DEADLINE_PASSED_PENALTY,
    GRAD_LEVEL_PENALTY,
    HIGH_PRIORITY_TARGET_COUNT,
    INTEREST_BONUS_CAP,
    INTEREST_BONUS_PER_HIT,
    INTL_UNKNOWN_SCORE,
    PROFICIENCY_WEIGHTS,
    SEMANTIC_RERANK_FALLBACK_CAP,
    SIMILARITY_SCALE_TFIDF,
    STRETCH_BLEND,
    STRETCH_MIDPOINT,
    STRETCH_SIGMOID_K,
    TOPIC_MISMATCH_PENALTY,
    TOPIC_UNKNOWN_PENALTY,
    WEIGHTS_DEFAULT,
)


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
    "BIO": ["CHEM", "BIOE", "PSYCH", "AGE"],
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


def _normalize_major(major: str) -> str:
    major_upper = major.upper().strip()
    for group, aliases in MAJOR_GROUPS.items():
        if major_upper in {a.upper() for a in aliases}:
            return group
    return major_upper


_STEM_MAJORS = frozenset({
    "CS", "ECE", "STAT", "IS", "MATH", "PHYS", "CHEME", "BIOE", "MECHSE",
    "CEE", "MSE", "AE", "IE", "NPRE", "CHEM", "BIO", "ATMS", "AGE",
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


def _major_match_score(student_majors: list[str], required_majors: list[str]) -> float:
    if not required_majors:
        return 30.0  # No requirement = open, but no signal of good fit

    s_normalized = {_normalize_major(m) for m in student_majors}
    r_normalized = {_normalize_major(m) for m in required_majors}

    if s_normalized & r_normalized:
        return 100.0

    for sm in s_normalized:
        related = RELATED_MAJORS.get(sm, [])
        if any(r in r_normalized for r in related):
            return 70.0

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
    return " ".join(filter(None, [
        opportunity.get("title", ""),
        opportunity.get("lab_or_program", ""),
        " ".join(specific_kw),
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

    signal_text = " ".join(filter(None, [
        opportunity.get("title", ""),
        " ".join(opportunity.get("keywords", []) or []),
        opportunity.get("lab_or_program", "") or "",
    ])).lower()
    if not signal_text:
        return 0.0

    tokens = [t for t in _tokenize(interests) if t not in _GENERIC_INTEREST_WORDS]
    if not tokens:
        return 0.0

    hits = sum(1 for t in set(tokens) if t in signal_text)
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


def _coursework_score(student_courses: set[str], opportunity: dict) -> float:
    """Score coursework on count + relevance to the opportunity.

    Count alone caps at COURSEWORK_MAX_FROM_COUNT (70) so a student who
    listed 7 generic courses doesn't get a perfect score; relevant courses
    (course code prefix matches an opportunity keyword/skill, e.g. CS473
    → 'cs' tag, or BIOL420 → biology lab) earn an additional bonus on top.
    """
    if not student_courses:
        return 30.0

    count_score = min(COURSEWORK_MAX_FROM_COUNT, len(student_courses) * COURSEWORK_PER_COURSE)

    keywords = [k.lower() for k in opportunity.get("keywords", []) or [] if isinstance(k, str)]
    skills = [s.lower() for s in opportunity.get("eligibility", {}).get("skills_required", []) or [] if isinstance(s, str)]
    signals = set(keywords) | set(skills)
    if not signals:
        return count_score

    course_tokens: set[str] = set()
    for c in student_courses:
        cl = c.lower()
        course_tokens.add(cl)
        prefix = "".join(ch for ch in cl if ch.isalpha())
        if prefix:
            course_tokens.add(prefix)

    overlap = sum(1 for sig in signals if any(sig in tok or tok in sig for tok in course_tokens if len(tok) >= 2))
    if overlap == 0:
        return count_score

    relevance = min(COURSEWORK_RELEVANCE_BONUS, overlap * 10.0)
    return min(100.0, count_score + relevance)


def _year_match_score(student_year: str, preferred_years: list[str]) -> float:
    if not preferred_years or "unknown" in preferred_years:
        return 40.0  # Unknown year pref = can't tell if it fits

    year_order = ["freshman", "sophomore", "junior", "senior"]
    student_year_lower = student_year.lower().strip()

    if student_year_lower in [y.lower() for y in preferred_years]:
        return 100.0

    # One year off
    try:
        s_idx = year_order.index(student_year_lower)
        for py in preferred_years:
            p_idx = year_order.index(py.lower().strip())
            if abs(s_idx - p_idx) == 1:
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
    elig = opportunity.get("eligibility", {})
    reasons_fit = []
    reasons_gap = []

    # Year match (30% weight)
    year_score = _year_match_score(
        profile.get("year", ""),
        elig.get("preferred_year", [])
    )
    if year_score >= 80:
        reasons_fit.append(f"Accepts {profile['year']} students")
    elif year_score < 50:
        reasons_gap.append(f"Typically targets {', '.join(elig.get('preferred_year', []))}")

    # Major match (20% weight)
    student_majors = [profile.get("major", "")] + profile.get("secondary_interests", [])
    major_score = _major_match_score(student_majors, elig.get("majors", []))
    if major_score >= 100:
        reasons_fit.append(f"Your major ({profile.get('major', '')}) is a direct match")
    elif major_score >= 70:
        reasons_fit.append(f"Your major ({profile.get('major', '')}) is closely related to requirements")
    elif major_score < 50:
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
            intl_score = INTL_UNKNOWN_SCORE
            # DQ-6: "unknown" covers 37% of the corpus (mostly internships whose
            # source sponsorship field was blank). For internships specifically,
            # a flat deterrent over-discourages the primary audience — most allow
            # CPT/OPT — so frame it as verify-don't-rule-out.
            if opportunity.get("opportunity_type") == "internship":
                reasons_gap.append(
                    "International eligibility unclear — many internships qualify "
                    "for CPT/OPT; confirm with the employer"
                )
            else:
                reasons_gap.append("International eligibility unclear — verify before applying")
        else:
            reasons_fit.append("Open to international students")

    # Skill overlap (15% weight). Rolling-basis postings (faculty labs,
    # SRO entries) typically don't list fixed skill requirements because
    # they adapt to whoever applies. Treat their empty skills as neutral
    # (60) rather than penalized (35) so research-curious students don't
    # get marked down for lab postings that explicitly don't screen on skills.
    required_skills_list = elig.get("skills_required", []) or []
    if not required_skills_list and opportunity.get("is_rolling"):
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
        reasons_fit.append(f"{label}: {', '.join(skill_detail_parts)} — {len(matched_skills)}/{len(required_raw)} required")
    if missing_skills:
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

    total = 0.30 * year_score + 0.20 * major_score + 0.20 * intl_score + 0.15 * skill_score + 0.15 * type_score
    return total, reasons_fit, reasons_gap


def score_readiness(profile: dict, opportunity: dict) -> tuple[float, list[str], list[str]]:
    """Score readiness (0-100)."""
    app = opportunity.get("application", {})
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
        reasons_fit.append("Your experience level is competitive")
    elif exp_score <= 30:
        reasons_gap.append("Limited prior experience — position may be competitive")

    student_courses = set(c.upper().strip() for c in profile.get("coursework", []))
    course_score = _coursework_score(student_courses, opportunity)

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


def score_upside(
    profile: dict,
    opportunity: dict,
    precomputed_sim: float | None = None,
) -> tuple[float, list[str], list[str]]:
    """Score upside (0-100). ``precomputed_sim`` lets rank_all supply a batched
    research-interest similarity (identical to the per-pair value) instead of
    recomputing it here per opportunity."""
    reasons_fit = []
    reasons_gap = []

    # Paid (20%)
    paid_map = {"yes": 100, "stipend": 80, "unknown": 40, "no": 25}
    paid_score = paid_map.get(opportunity.get("paid", "unknown"), 50)
    if paid_score >= 70:
        reasons_fit.append("Paid opportunity" if paid_score == 100 else "Includes stipend")

    # First-experience friendly (25%)
    elig = opportunity.get("eligibility", {})
    first_exp_score = 40.0  # Default: no signal of freshman-friendliness
    if "freshman" in [y.lower() for y in elig.get("preferred_year", [])]:
        first_exp_score = 100.0
        reasons_fit.append("Explicitly welcomes first-time researchers")

    # On-campus convenience (10%)
    campus_score = 80.0 if opportunity.get("on_campus") else 50.0
    if opportunity.get("on_campus") and profile.get("international_student"):
        # The F-1 "no work-authorization concerns" advantage only holds on the
        # student's OWN campus. Withhold it only when we KNOW the campus is a
        # different school (a foreign campus stamped on_campus=True — a future
        # multi-school data error). Missing home_school or national/legacy
        # (school=None) records keep the original behavior — an F-1 can't work on
        # another school's campus, but we never penalize on incomplete data.
        opp_school = opportunity.get("school")
        home_school = profile.get("home_school")
        if opp_school is None or not home_school or opp_school == home_school:
            campus_score = 90.0
            reasons_fit.append("On-campus — no work authorization concerns")

    # Brand/prestige (15%)
    # Simple heuristic for V1 — can be refined
    brand_score = 60.0
    org = (opportunity.get("organization") or "").lower()
    prestigious = ["caltech", "mit", "stanford", "cmu", "berkeley", "nasa", "doe"]
    if any(p in org for p in prestigious):
        brand_score = 95.0
        reasons_fit.append("Prestigious institution — strong resume builder")
    elif "uiuc" in org or "illinois" in org:
        brand_score = 70.0

    desc = (opportunity.get("description_raw") or "").lower()
    mentor_keywords = ["mentor", "training", "learn", "guided", "supervision", "teach", "onboard"]
    mentor_hits = sum(1 for k in mentor_keywords if k in desc)
    mentor_score = 35.0 + min(55.0, mentor_hits * 20.0)

    pathway_keywords = ["publication", "paper", "co-author", "return", "continue", "conference", "thesis"]
    pathway_hits = sum(1 for k in pathway_keywords if k in desc)
    pathway_score = 40.0 + min(55.0, pathway_hits * 18.0)
    if pathway_hits >= 2:
        reasons_fit.append("Potential for publication or long-term involvement")

    keyword_score = 25.0
    opp_kw_list = [k.lower() for k in opportunity.get("keywords", [])]
    opp_keywords = set(opp_kw_list)
    desired = set(f.lower() for f in profile.get("desired_fields", []))
    interest_reason = ""
    interest_overlap: set[str] = set()
    if opp_keywords and desired:
        interest_overlap = opp_keywords & desired
        if interest_overlap:
            keyword_score = min(100.0, 50.0 + len(interest_overlap) * 25)
            interest_reason = f"Matches your interests: {', '.join(interest_overlap)}"
            reasons_fit.append(interest_reason)

    research_text = profile.get("research_interests_text", "").lower()
    lab = opportunity.get("lab_or_program", "")
    pi_name = opportunity.get("pi_name", "")
    opp_desc = (opportunity.get("description_raw") or opportunity.get("description_clean") or "").lower()

    specific_kw = list(dict.fromkeys(
        kw for kw in opp_kw_list if kw not in _GENERIC_KEYWORDS
    ))
    clean_pi = pi_name if pi_name and pi_name.lower().strip() not in _BAD_PI_NAMES else ""
    lab_label = clean_pi and f"Prof. {clean_pi}" or lab or opportunity.get("department", "")

    if research_text and (opp_desc or specific_kw):
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
            display_kw = _topical_keywords(specific_kw)
            work = ", ".join(display_kw[:3])
            # Name the interest terms that actually overlap the lab's areas rather
            # than echoing a mid-word slice of the student's free-text interests.
            overlap = [kw for kw in display_kw if kw in research_text]
            interest_phrase = ", ".join(overlap[:3])
            if display_kw and lab_label:
                reasons_fit.append(
                    f"Your interest in {interest_phrase} closely matches {lab_label}'s work on {work}"
                    if interest_phrase
                    else f"Your research interests align closely with {lab_label}'s work on {work}"
                )
            elif display_kw:
                reasons_fit.append(
                    f"Your interest in {interest_phrase} closely matches their work on {work}"
                    if interest_phrase
                    else f"Your research interests align closely with their work on {work}"
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

    has_skill_signal = bool(opportunity.get("eligibility", {}).get("skills_required"))
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


def _compute_weights(search_weight: int) -> dict[str, float]:
    """Blend scoring weights based on the search_weight slider (0-100).

    0   = pure research interests  → boost upside (keyword/interest matching)
    50  = balanced (default)
    100 = pure resume/experience   → boost readiness (skills, resume, coursework)
    """
    sw = max(0, min(100, search_weight))
    t = sw / 100.0

    elig = WEIGHTS_DEFAULT.eligibility - 0.05 * abs(t - 0.5) * 2
    readiness = (WEIGHTS_DEFAULT.readiness - 0.10) + 0.20 * t
    upside = 1.0 - elig - readiness
    return {"eligibility": elig, "readiness": readiness, "upside": max(0.05, upside)}


_GENERIC_KEYWORDS = frozenset({
    "undergraduate", "research", "summer", "program", "internship",
    "opportunity", "assistant", "student", "uiuc", "illinois",
    "computer science", "artificial intelligence", "machine learning",
    "engineering", "science", "technology", "department",
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
        return s[:100]
    return ""


_BAD_PI_NAMES = frozenset({"learn more", "none", "n/a", "and robotics", "unknown", ""})


def _summarize_research(opportunity: dict) -> str:
    pi = opportunity.get("pi_name") or ""
    if pi.lower().strip() in _BAD_PI_NAMES:
        pi = ""
    lab = opportunity.get("lab_or_program", "")
    dept = opportunity.get("department", "")
    desc = opportunity.get("description_raw") or opportunity.get("description_clean") or ""

    specific_kw = _topical_keywords(_extract_specific_keywords(opportunity))
    desc_focus = _extract_research_focus_from_desc(desc)

    lab_has_pi = pi and pi.split()[-1].lower() in lab.lower()

    if pi and lab and specific_kw:
        prefix = lab if lab_has_pi else f"Prof. {pi}'s {lab}"
        return f"{prefix} — {', '.join(specific_kw[:3])}"
    if pi and specific_kw:
        return f"Prof. {pi} ({dept or 'UIUC'}) — {', '.join(specific_kw[:3])}"
    if pi and lab:
        prefix = lab if lab_has_pi else f"Prof. {pi}'s {lab}"
        if desc_focus:
            return f"{prefix}: {desc_focus}"
        return f"{prefix} ({dept})" if dept and dept not in prefix else prefix
    if pi and desc_focus:
        return f"Prof. {pi}: {desc_focus}"
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

    interest = (profile.get("research_interests_text") or "").strip().lower()
    interest_tokens = {t for t in _tokenize(interest) if t not in _GENERIC_INTEREST_WORDS}
    if len(interest_tokens) < 2:
        return 1.0

    # Canonicalize the interest tokens too (not just the keyword) so a student
    # who types an acronym ("ml", "nlp", "cv") aligns with a posting keyword
    # stored as the full phrase, and vice-versa — without this the student's
    # best topical match got the MISMATCH penalty (RANK-2).
    interest_canon = {_canonicalize_skill(t) for t in interest_tokens}

    specific = [
        k.lower() for k in _extract_specific_keywords(opportunity)
        if k.lower() not in _BROAD_FIELDS
    ]
    if not specific:
        return TOPIC_UNKNOWN_PENALTY

    for kw in specific:
        canon = _canonicalize_skill(kw)
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
        # Token overlap: a multi-word curated keyword aligns when it shares any
        # specific (non-generic) word with the student's interests. The prior
        # checks only fired when the WHOLE keyword phrase appeared verbatim in
        # the interest text, so "computer vision" interest missed a "computer
        # vision and pattern recognition" keyword, and "machine learning" missed
        # "machine learning and ai" — burying 38% of faculty incl. the best
        # topical fits (RANK-7). Stopword/generic filtering keeps this from
        # aligning on filler ("and", "research"); a genuinely off-topic lab
        # (zero shared specific token) still gets the mismatch penalty.
        keyword_tokens = {
            t for t in _tokenize(kw) if t not in _GENERIC_INTEREST_WORDS
        }
        token_overlap = bool(keyword_tokens & interest_tokens)
        if exact or substring or token_overlap:
            return 1.0
    return TOPIC_MISMATCH_PENALTY


def rank_opportunity(
    profile: dict,
    opportunity: dict,
    weights: dict[str, float] | None = None,
    precomputed_eligibility: tuple[float, list[str], list[str]] | None = None,
    precomputed_sim: float | None = None,
) -> MatchResult:
    if precomputed_eligibility is not None:
        elig_score, elig_fit, elig_gap = precomputed_eligibility
    else:
        elig_score, elig_fit, elig_gap = score_eligibility(profile, opportunity)
    ready_score, ready_fit, ready_gap = score_readiness(profile, opportunity)
    up_score, up_fit, up_gap = score_upside(profile, opportunity, precomputed_sim=precomputed_sim)

    w = weights or {
        "eligibility": WEIGHTS_DEFAULT.eligibility,
        "readiness": WEIGHTS_DEFAULT.readiness,
        "upside": WEIGHTS_DEFAULT.upside,
    }
    raw = (
        w["eligibility"] * elig_score +
        w["readiness"] * ready_score +
        w["upside"] * up_score
    )

    interest_bonus = _interest_bonus(profile, opportunity)
    raw = min(100.0, raw + interest_bonus)

    # RANK-3: major fit is already weighted inside score_eligibility (0.20 of the
    # eligibility layer). A separate raw multiplier here double-counted the same
    # signal, deflating mismatches far below the documented weight. Dogfooding
    # confirmed the eligibility term alone keeps a cross-domain mismatch (e.g. a
    # Spanish major vs a CS-only lab) firmly in low_fit, so the multiplier is
    # removed and major fit lives in exactly one place.
    topic_penalty = _topic_alignment_penalty(profile, opportunity)
    if topic_penalty < 1.0:
        raw *= topic_penalty
        if topic_penalty <= TOPIC_MISMATCH_PENALTY:
            elig_gap.append("Research area looks different from your stated interests")

    final = _stretch_score(raw)

    deadline = opportunity.get("deadline", "")
    if deadline and len(deadline) >= 8 and deadline[4] == "-":
        try:
            from datetime import date
            dl = date.fromisoformat(deadline)
            days_left = (dl - date.today()).days
            if days_left < 0:
                final *= DEADLINE_PASSED_PENALTY
                elig_gap.append("Deadline has passed — verify if still accepting applications")
            elif days_left <= 7:
                elig_fit.append(f"Deadline in {days_left} days — apply soon")
        except ValueError:
            pass

    if _is_undergrad(profile) and _requires_graduate_standing(opportunity):
        final *= GRAD_LEVEL_PENALTY
        elig_gap.append("Targets graduate / PhD students — a reach for undergraduates")

    bucket = "low_fit"
    for threshold, label in BUCKET_THRESHOLDS:
        if final >= float(threshold):
            bucket = label
            break

    all_fit = elig_fit + ready_fit + up_fit
    all_gap = elig_gap + ready_gap + up_gap

    research_summary = _summarize_research(opportunity)
    if research_summary:
        pi = opportunity.get("pi_name", "")
        if pi and pi in research_summary:
            all_fit.insert(0, research_summary)
        elif opportunity.get("opportunity_type") == "research":
            all_fit.insert(0, f"This lab focuses on {research_summary}")
        # Non-research postings (internships, summer programs) have no "lab" —
        # the "This lab focuses on …" framing is a category error there, and the
        # keyword/interest reasons already convey relevance, so skip it.

    next_steps = _generate_next_steps(profile, opportunity, all_gap)

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
    )


def _generate_next_steps(profile: dict, opportunity: dict, gaps: list[str]) -> list[str]:
    """Generate actionable next steps based on gaps."""
    steps = []
    app = opportunity.get("application", {})

    # Deadline urgency
    deadline = opportunity.get("deadline")
    if deadline:
        steps.append(f"Apply before deadline: {deadline}")

    # Resume
    if not profile.get("resume_ready") and app.get("requires_resume") == "yes":
        steps.append("Prepare a research-focused resume")

    # Cold email
    if app.get("contact_method") == "email" and profile.get("can_cold_email"):
        steps.append("Send a brief cold email to the PI expressing interest")

    # Default
    if not steps:
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


def _assign_buckets(results: list[MatchResult]) -> None:
    """Assign each result's bucket from its current final_score. Expects results
    sorted by final_score desc. For >=10 results uses the RANK-6 top-N count cap
    + percentile banding; smaller sets fall back to the flat BUCKET_THRESHOLDS
    floors. Mutates in place. Shared by rank_all and semantic_rerank so a
    re-blended score never keeps a stale bucket label."""
    floor_high = float(BUCKET_THRESHOLDS[0][0])
    floor_good = float(BUCKET_THRESHOLDS[1][0])
    floor_reach = float(BUCKET_THRESHOLDS[2][0])
    if len(results) >= 10:
        scores = [r.final_score for r in results]
        p70 = scores[max(0, (len(scores) * 3) // 10)]
        p40 = scores[max(0, (len(scores) * 6) // 10)]
        k = min(HIGH_PRIORITY_TARGET_COUNT, len(scores) - 1)
        hp_threshold = max(floor_high, scores[k])
        gm_threshold = max(floor_good, p70)
        reach_threshold = max(floor_reach, p40)
    else:
        hp_threshold, gm_threshold, reach_threshold = floor_high, floor_good, floor_reach

    for r in results:
        if r.final_score >= hp_threshold:
            r.bucket = "high_priority"
        elif r.final_score >= gm_threshold:
            r.bucket = "good_match"
        elif r.final_score >= reach_threshold:
            r.bucket = "reach"
        else:
            r.bucket = "low_fit"


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

    results.sort(key=lambda r: r.final_score, reverse=True)
    # Buckets were assigned on the pre-blend scores; recompute them so the labels
    # and per-bucket counts match the re-ranked order (semantic=true used to
    # return stale buckets).
    _assign_buckets(results)
    return results


def rank_all(profile: dict, opportunities: list[dict]) -> list[MatchResult]:
    """Rank all opportunities for a profile. Returns sorted by final_score desc."""
    search_weight = profile.get("search_weight", 50)
    weights = _compute_weights(search_weight)

    home_school = str(profile.get("home_school") or "uiuc").strip().lower()
    seeking = set(profile.get("seeking_type", []))
    student_majors_norm = {_normalize_major(m) for m in [profile.get("major", "")] + profile.get("secondary_interests", [])}
    related_majors_norm: set[str] = set()
    for sm in student_majors_norm:
        related_majors_norm.update(RELATED_MAJORS.get(sm, []))

    # Parse the profile's skills once — it is identical for every opportunity, so
    # parsing it per opp (inside score_eligibility) was ~12% of rank_all's time.
    profile_skill_map = _parse_skills(profile.get("hard_skills", []))

    # Batch the upside research-interest similarity once for the whole corpus.
    # This pass is TF-IDF only (allow_embeddings=False): embedding the full ~4.4k
    # corpus per request would fan out into dozens of provider calls and is
    # reserved for the bounded semantic_rerank slice. The batch is score-identical
    # to score_upside's per-pair path only when the corpus vectorizer is fitted
    # (same deterministic transform); when it is not (offline/unfitted), leave
    # sims empty so score_upside keeps its per-pair behavior unchanged.
    sims_by_id: dict[str, float] = {}
    research_text = (profile.get("research_interests_text") or "").lower()
    if research_text:
        try:
            import src.matcher.embeddings as _emb
            if _emb._tfidf_fitted:
                corpora = [_similarity_corpus(o) for o in opportunities]
                sims = _emb.semantic_similarity_batch(
                    research_text, corpora, allow_embeddings=False
                )
                sims_by_id = {
                    o["id"]: s for o, s in zip(opportunities, sims, strict=False) if o.get("id")
                }
        except Exception:
            sims_by_id = {}

    results = []
    for opp in opportunities:
        if opp.get("metadata", {}).get("is_active") is False:
            continue

        # Multi-university scope (PR #187 Phase 1): another school's
        # campus-only posting is not actionable for this user. 'open' and
        # 'unknown' always pass — hiding 'unknown' would regress e.g. the
        # UCB faculty cold-email targets UIUC users see today.
        opp_school = opp.get("school")
        if (
            opp_school is not None
            and opp_school != home_school
            and opp.get("audience") == "campus"
        ):
            continue

        if profile.get("international_student"):
            elig = opp.get("eligibility", {})
            if elig.get("international_friendly") == "no" or elig.get("citizenship_required") is True:
                if profile.get("preferences", {}).get("exclude_citizenship_restricted", True):
                    continue

        opp_type = opp.get("opportunity_type", "")
        if seeking and opp_type and opp_type not in seeking:
            opp_majors = opp.get("eligibility", {}).get("majors", [])
            if opp_majors:
                opp_majors_norm = {_normalize_major(m) for m in opp_majors}
                if not (student_majors_norm & opp_majors_norm):
                    if not (related_majors_norm & opp_majors_norm):
                        continue

        elig_triple = score_eligibility(profile, opp, skill_map=profile_skill_map)
        min_threshold = profile.get("preferences", {}).get("min_match_threshold", 0)
        if min_threshold > 0:
            max_possible = (
                weights["eligibility"] * elig_triple[0]
                + (weights["readiness"] + weights["upside"]) * 100
            )
            if max_possible < min_threshold:
                continue

        result = rank_opportunity(
            profile, opp, weights,
            precomputed_eligibility=elig_triple,
            precomputed_sim=sims_by_id.get(opp.get("id")),
        )
        if result.final_score >= min_threshold:
            results.append(result)

    results.sort(key=lambda r: r.final_score, reverse=True)
    _assign_buckets(results)

    return results
