"""
Three-layer matching engine.
Scores opportunities against a student profile.
"""

import math
import os
import re
from collections import Counter
from dataclasses import dataclass


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
    "well", "use", "used", "using", "will", "work", "working", "new",
    "including", "include", "includes", "provide", "provides",
    "students", "student", "program", "research", "university",
    "opportunity", "opportunities", "experience", "summer",
})


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{2,}", text.lower()) if w not in _STOP_WORDS]


def _text_similarity(text_a: str, text_b: str) -> float:
    try:
        from .embeddings import semantic_similarity
        return semantic_similarity(text_a, text_b)
    except ImportError:
        return _token_cosine_similarity(text_a, text_b)
    except (ValueError, RuntimeError):
        return _token_cosine_similarity(text_a, text_b)


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
    return min(8.0, hits * 3.0)


_GENERIC_INTEREST_WORDS = frozenset({
    "research", "study", "studies", "interested", "interest", "learning",
    "field", "work", "general", "related", "area", "topic", "stuff",
    "things", "various", "different", "many", "some",
})


PROFICIENCY_WEIGHTS = {"expert": 1.0, "experienced": 0.75, "beginner": 0.5}

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


def _skill_overlap_score(student_skills: list, required_skills: list[str]) -> float:
    if not required_skills:
        return 35.0

    skill_weights = _parse_skills(student_skills)

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


def _type_preference_score(seeking_types: list[str], opp_type: str) -> float:
    """Score how well the opportunity type matches user preferences."""
    if not seeking_types:
        return 60.0  # No preference stated
    if opp_type in seeking_types:
        return 100.0
    type_affinity = {
        ("research", "summer_program"): 70.0,
        ("summer_program", "research"): 70.0,
        ("internship", "summer_program"): 60.0,
        ("summer_program", "internship"): 60.0,
        ("research", "internship"): 50.0,
        ("internship", "research"): 50.0,
    }
    for st in seeking_types:
        score = type_affinity.get((st, opp_type))
        if score:
            return score
    return 30.0  # Completely different type


# --- Scoring layers ---

def score_eligibility(profile: dict, opportunity: dict) -> tuple[float, list[str], list[str]]:
    """Score eligibility (0-100). Returns (score, fit_reasons, gap_reasons)."""
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

    # International eligibility (20%)
    intl_score = 100.0
    if profile.get("international_student"):
        friendly = elig.get("international_friendly", "unknown")
        if friendly == "no":
            intl_score = 0.0
            reasons_gap.append("Requires US citizenship or permanent residency")
        elif friendly == "unknown":
            intl_score = 35.0  # Significant penalty for uncertainty
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
            required_skills_list
        )
    student_skill_map = _parse_skills(profile.get("hard_skills", []))
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
    if type_score >= 80:
        reasons_fit.append(f"Matches your interest in {opportunity.get('opportunity_type', '')}")
    elif type_score < 50:
        reasons_gap.append(f"This is a {opportunity.get('opportunity_type', '')} — not your primary target type")

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

    # Coursework (20%)
    student_courses = set(c.upper().strip() for c in profile.get("coursework", []))
    # Simple heuristic: more courses = more prepared
    course_score = min(100.0, len(student_courses) * 15)

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


def score_upside(profile: dict, opportunity: dict) -> tuple[float, list[str], list[str]]:
    """Score upside (0-100)."""
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
    opp_keywords = set(k.lower() for k in opportunity.get("keywords", []))
    desired = set(f.lower() for f in profile.get("desired_fields", []))
    if opp_keywords and desired:
        overlap = opp_keywords & desired
        if overlap:
            keyword_score = min(100.0, 50.0 + len(overlap) * 25)
            reasons_fit.append(f"Matches your interests: {', '.join(overlap)}")

    research_text = profile.get("research_interests_text", "").lower()
    lab = opportunity.get("lab_or_program", "")
    pi_name = opportunity.get("pi_name", "")
    opp_desc = (opportunity.get("description_raw") or opportunity.get("description_clean") or "").lower()

    specific_kw = [kw for kw in opp_keywords if kw not in _GENERIC_KEYWORDS]
    clean_pi = pi_name if pi_name and pi_name.lower().strip() not in _BAD_PI_NAMES else ""
    lab_label = clean_pi and f"Prof. {clean_pi}" or lab or opportunity.get("department", "")

    if research_text and (opp_desc or specific_kw):
        opp_corpus = " ".join(filter(None, [
            opportunity.get("title", ""),
            lab,
            " ".join(specific_kw),
            opp_desc,
        ]))
        sim = _text_similarity(research_text, opp_corpus)
        keyword_score = max(keyword_score, min(100.0, 15.0 + sim * 400))
        if sim > 0.15:
            if specific_kw and lab_label:
                reasons_fit.append(
                    f"Your interest in {research_text[:50].rstrip('.')} closely matches {lab_label}'s work on {', '.join(specific_kw[:3])}"
                )
            elif specific_kw:
                reasons_fit.append(
                    f"Your interest in {research_text[:50].rstrip('.')} closely matches their work on {', '.join(specific_kw[:3])}"
                )
            elif lab_label:
                reasons_fit.append(
                    f"Your research background aligns with {lab_label}'s focus area"
                )
    elif research_text and specific_kw:
        text_overlap = [kw for kw in specific_kw if kw in research_text]
        if text_overlap:
            keyword_score = min(100.0, keyword_score + len(text_overlap) * 15)
            if lab_label:
                reasons_fit.append(
                    f"Your interest in {', '.join(text_overlap)} connects to {lab_label}'s research"
                )
            else:
                reasons_fit.append(
                    f"Your interest in {', '.join(text_overlap)} connects to this position"
                )

    has_skill_signal = bool(opportunity.get("eligibility", {}).get("skills_required"))
    if has_skill_signal:
        total = 0.15 * paid_score + 0.15 * first_exp_score + 0.10 * campus_score + \
                0.10 * brand_score + 0.15 * mentor_score + 0.15 * pathway_score + 0.20 * keyword_score
    else:
        total = 0.10 * paid_score + 0.10 * first_exp_score + 0.10 * campus_score + \
                0.10 * brand_score + 0.15 * mentor_score + 0.10 * pathway_score + 0.35 * keyword_score
    return total, reasons_fit, reasons_gap


# --- Combined ranker ---

WEIGHTS_DEFAULT = {"eligibility": 0.45, "readiness": 0.35, "upside": 0.20}

BUCKET_THRESHOLDS = [
    (78, "high_priority"),
    (62, "good_match"),
    (42, "reach"),
    (0,  "low_fit"),
]


def _stretch_score(raw: float) -> float:
    """Widen the score distribution so matches spread out visibly.

    The weighted-sum raw score tends to cluster in 45-75 because every
    sub-score has a ~40 default floor for unknowns. We mostly preserve
    raw, but apply a gentle sigmoid pull (strong at the extremes, weak
    in the middle) plus a subtract-midpoint amplification so signal
    differences in the 70-90 zone aren't compressed.
    """
    x = max(0.0, min(100.0, raw))
    k = 0.07
    midpoint = 55.0
    sig = 1.0 / (1.0 + math.exp(-k * (x - midpoint)))
    stretched = sig * 100.0
    blended = 0.55 * x + 0.45 * stretched
    return max(0.0, min(100.0, blended))


def _compute_weights(search_weight: int) -> dict[str, float]:
    """Blend scoring weights based on the search_weight slider (0-100).

    0   = pure research interests  → boost upside (keyword/interest matching)
    50  = balanced (default)
    100 = pure resume/experience   → boost readiness (skills, resume, coursework)
    """
    sw = max(0, min(100, search_weight))
    t = sw / 100.0  # 0.0 → 1.0

    elig = 0.45 - 0.05 * abs(t - 0.5) * 2
    readiness = 0.25 + 0.20 * t
    upside = 1.0 - elig - readiness
    return {"eligibility": elig, "readiness": readiness, "upside": max(0.05, upside)}


_GENERIC_KEYWORDS = frozenset({
    "undergraduate", "research", "summer", "program", "internship",
    "opportunity", "assistant", "student", "uiuc", "illinois",
    "computer science", "artificial intelligence", "machine learning",
    "engineering", "science", "technology", "department",
})


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

    specific_kw = _extract_specific_keywords(opportunity)
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


def rank_opportunity(
    profile: dict,
    opportunity: dict,
    weights: dict[str, float] | None = None,
    precomputed_eligibility: tuple[float, list[str], list[str]] | None = None,
) -> MatchResult:
    if precomputed_eligibility is not None:
        elig_score, elig_fit, elig_gap = precomputed_eligibility
    else:
        elig_score, elig_fit, elig_gap = score_eligibility(profile, opportunity)
    ready_score, ready_fit, ready_gap = score_readiness(profile, opportunity)
    up_score, up_fit, up_gap = score_upside(profile, opportunity)

    w = weights or WEIGHTS_DEFAULT
    raw = (
        w["eligibility"] * elig_score +
        w["readiness"] * ready_score +
        w["upside"] * up_score
    )

    interest_bonus = _interest_bonus(profile, opportunity)
    raw = min(100.0, raw + interest_bonus)

    elig = opportunity.get("eligibility", {})
    required_majors = elig.get("majors", [])
    if required_majors:
        student_majors = [profile.get("major", "")] + profile.get("secondary_interests", [])
        mm_score = _major_match_score(student_majors, required_majors)
        if mm_score <= 10.0:
            raw *= 0.75
        elif mm_score <= 20.0:
            raw *= 0.88

    final = _stretch_score(raw)

    deadline = opportunity.get("deadline", "")
    if deadline and len(deadline) >= 8 and deadline[4] == "-":
        try:
            from datetime import date
            dl = date.fromisoformat(deadline)
            days_left = (dl - date.today()).days
            if days_left < 0:
                final *= 0.7
                elig_gap.append("Deadline has passed — verify if still accepting applications")
            elif days_left <= 7:
                elig_fit.append(f"Deadline in {days_left} days — apply soon")
        except ValueError:
            pass

    bucket = "low_fit"
    for threshold, label in BUCKET_THRESHOLDS:
        if final >= threshold:
            bucket = label
            break

    all_fit = elig_fit + ready_fit + up_fit
    all_gap = elig_gap + ready_gap + up_gap

    research_summary = _summarize_research(opportunity)
    if research_summary:
        pi = opportunity.get("pi_name", "")
        if pi and pi in research_summary:
            all_fit.insert(0, research_summary)
        else:
            all_fit.insert(0, f"This lab focuses on {research_summary}")

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
        from .embeddings import semantic_similarity_batch
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

    # When falling back to TF-IDF (no OpenAI/OpenRouter key), similarity
    # signal is noisier — it matches generic corpus keywords like "REU" or
    # "undergraduate" and can demote truly relevant labs. Detect fallback
    # by probing the env, and cap the blend weight so rule-based signal
    # dominates. Production has OPENAI_API_KEY set → full weight applies.
    has_api = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
    effective_weight = semantic_weight if has_api else min(semantic_weight, 0.2)

    w = max(0.0, min(1.0, effective_weight))
    for r, sim in zip(top_slice, sims):
        rule = r.final_score
        blended = (1.0 - w) * rule + w * float(sim) * 100.0
        r.final_score = round(max(0.0, min(100.0, blended)), 2)

    results.sort(key=lambda r: r.final_score, reverse=True)
    return results


def rank_all(profile: dict, opportunities: list[dict]) -> list[MatchResult]:
    """Rank all opportunities for a profile. Returns sorted by final_score desc."""
    search_weight = profile.get("search_weight", 50)
    weights = _compute_weights(search_weight)

    seeking = set(profile.get("seeking_type", []))
    student_majors_norm = {_normalize_major(m) for m in [profile.get("major", "")] + profile.get("secondary_interests", [])}

    results = []
    for opp in opportunities:
        if opp.get("metadata", {}).get("is_active") is False:
            continue

        if profile.get("international_student"):
            elig = opp.get("eligibility", {})
            if elig.get("international_friendly") == "no":
                if profile.get("preferences", {}).get("exclude_citizenship_restricted", True):
                    continue

        opp_type = opp.get("opportunity_type", "")
        if seeking and opp_type and opp_type not in seeking:
            opp_majors = opp.get("eligibility", {}).get("majors", [])
            if opp_majors:
                opp_majors_norm = {_normalize_major(m) for m in opp_majors}
                if not (student_majors_norm & opp_majors_norm):
                    all_related = set()
                    for sm in student_majors_norm:
                        all_related.update(RELATED_MAJORS.get(sm, []))
                    if not (all_related & opp_majors_norm):
                        continue

        elig_triple = score_eligibility(profile, opp)
        min_threshold = profile.get("preferences", {}).get("min_match_threshold", 0)
        if min_threshold > 0:
            max_possible = (
                weights["eligibility"] * elig_triple[0]
                + (weights["readiness"] + weights["upside"]) * 100
            )
            if max_possible < min_threshold:
                continue

        result = rank_opportunity(profile, opp, weights, precomputed_eligibility=elig_triple)
        if result.final_score >= min_threshold:
            results.append(result)

    results.sort(key=lambda r: r.final_score, reverse=True)

    if len(results) >= 10:
        scores = [r.final_score for r in results]
        p90 = scores[max(0, len(scores) // 10)]
        p70 = scores[max(0, (len(scores) * 3) // 10)]
        p40 = scores[max(0, (len(scores) * 6) // 10)]

        hp_threshold = max(78, p90)
        gm_threshold = max(62, p70)
        reach_threshold = max(42, p40)

        for r in results:
            if r.final_score >= hp_threshold:
                r.bucket = "high_priority"
            elif r.final_score >= gm_threshold:
                r.bucket = "good_match"
            elif r.final_score >= reach_threshold:
                r.bucket = "reach"
            else:
                r.bucket = "low_fit"

    return results
