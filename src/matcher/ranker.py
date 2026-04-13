"""
Three-layer matching engine.
Scores opportunities against a student profile.
"""

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
    "CS": {"CS", "Computer Science"},
    "ECE": {"ECE", "Electrical Engineering", "Computer Engineering", "Electrical and Computer Engineering"},
    "STAT": {"STAT", "Statistics", "Data Science"},
    "IS": {"IS", "Information Sciences", "iSchool"},
    "MATH": {"MATH", "Mathematics", "Applied Math"},
    "PHYS": {"Physics", "PHYS", "Applied Physics"},
}

RELATED_MAJORS = {
    "CS": ["ECE", "IS", "STAT", "MATH"],
    "ECE": ["CS", "PHYS", "MATH"],
    "STAT": ["CS", "IS", "MATH"],
    "IS": ["CS", "STAT"],
}


def _normalize_major(major: str) -> str:
    major_upper = major.upper().strip()
    for group, aliases in MAJOR_GROUPS.items():
        if major_upper in {a.upper() for a in aliases}:
            return group
    return major_upper


def _major_match_score(student_majors: list[str], required_majors: list[str]) -> float:
    if not required_majors:
        return 40.0  # No requirement = open, but no signal of good fit

    s_normalized = {_normalize_major(m) for m in student_majors}
    r_normalized = {_normalize_major(m) for m in required_majors}

    # Exact match
    if s_normalized & r_normalized:
        return 100.0

    # Related match
    for sm in s_normalized:
        related = RELATED_MAJORS.get(sm, [])
        if any(r in r_normalized for r in related):
            return 70.0

    return 15.0


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
            level = s.get("level", "beginner")
            weight = PROFICIENCY_WEIGHTS.get(level, 0.5)
        elif isinstance(s, str):
            name = s.lower().strip()
            weight = 0.5
        else:
            name = getattr(s, "name", "").lower().strip()
            level = getattr(s, "level", "beginner")
            weight = PROFICIENCY_WEIGHTS.get(level, 0.5)

        canonical = _canonicalize_skill(name)
        result[canonical] = max(result.get(canonical, 0), weight)
        result[name] = max(result.get(name, 0), weight)

        for implied in SKILL_IMPLIES.get(canonical, []):
            impl_canon = _canonicalize_skill(implied)
            result[impl_canon] = max(result.get(impl_canon, 0), weight * 0.6)

    return result


def _skill_overlap_score(student_skills: list, required_skills: list[str]) -> float:
    if not required_skills:
        return 40.0

    skill_weights = _parse_skills(student_skills)

    total_weight = 0.0
    for r in required_skills:
        canon = _canonicalize_skill(r)
        w = skill_weights.get(canon, 0.0)
        if w == 0.0:
            w = skill_weights.get(r.lower().strip(), 0.0)
        total_weight += w

    max_possible = len(required_skills) * 1.0
    return min(100.0, (total_weight / max_possible) * 100)


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

    # Year match (30%)
    year_score = _year_match_score(
        profile.get("year", ""),
        elig.get("preferred_year", [])
    )
    if year_score >= 80:
        reasons_fit.append(f"Accepts {profile['year']} students")
    elif year_score < 50:
        reasons_gap.append(f"Typically targets {', '.join(elig.get('preferred_year', []))}")

    # Major match (25%)
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

    # Skill overlap (15%)
    skill_score = _skill_overlap_score(
        profile.get("hard_skills", []),
        elig.get("skills_required", [])
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

    if skill_score >= 70 and matched_skills:
        reasons_fit.append(f"Tech stack overlap: {', '.join(matched_skills)} ({len(matched_skills)}/{len(required_raw)} required)")
    elif skill_score >= 40 and matched_skills:
        reasons_fit.append(f"Partial skill match: {', '.join(matched_skills)}")
    if missing_skills:
        reasons_gap.append(f"Missing skills: {', '.join(missing_skills)}")

    # Type preference match (10%)
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

    # Mentorship signal (15%)
    desc = (opportunity.get("description_raw") or "").lower()
    mentor_keywords = ["mentor", "training", "learn", "guided", "supervision"]
    mentor_score = 80.0 if any(k in desc for k in mentor_keywords) else 50.0

    # Future pathway (15%)
    pathway_score = 60.0
    pathway_keywords = ["publication", "paper", "co-author", "return", "continue"]
    if any(k in desc for k in pathway_keywords):
        pathway_score = 90.0
        reasons_fit.append("Potential for publication or long-term involvement")

    keyword_score = 40.0
    opp_keywords = set(k.lower() for k in opportunity.get("keywords", []))
    desired = set(f.lower() for f in profile.get("desired_fields", []))
    if opp_keywords and desired:
        overlap = opp_keywords & desired
        if overlap:
            keyword_score = min(100.0, 50.0 + len(overlap) * 25)
            reasons_fit.append(f"Matches your interests: {', '.join(overlap)}")

    research_text = profile.get("research_interests_text", "").lower()
    if research_text and opp_keywords:
        text_overlap = [kw for kw in opp_keywords if kw in research_text]
        if text_overlap and keyword_score < 80:
            keyword_score = min(100.0, keyword_score + len(text_overlap) * 15)
            reasons_fit.append(f"Research interest alignment: {', '.join(text_overlap)}")

    opp_desc = (opportunity.get("description_clean") or opportunity.get("description_raw") or "").lower()
    if research_text and opp_desc and keyword_score < 60:
        interest_words = [w for w in research_text.split() if len(w) > 4]
        desc_hits = [w for w in interest_words if w in opp_desc]
        if len(desc_hits) >= 3:
            keyword_score = min(100.0, keyword_score + 20)
            reasons_fit.append("Opportunity description aligns with your research interests")

    total = 0.20 * paid_score + 0.20 * first_exp_score + 0.10 * campus_score + \
            0.10 * brand_score + 0.15 * mentor_score + 0.15 * pathway_score + 0.10 * keyword_score
    return total, reasons_fit, reasons_gap


# --- Combined ranker ---

WEIGHTS = {"eligibility": 0.45, "readiness": 0.35, "upside": 0.20}

BUCKET_THRESHOLDS = [
    (80, "high_priority"),
    (65, "good_match"),
    (45, "reach"),
    (0,  "low_fit"),
]


def _summarize_research(opportunity: dict) -> str:
    lab = opportunity.get("lab_or_program", "")
    desc = opportunity.get("description_raw") or opportunity.get("description_clean") or ""
    keywords = opportunity.get("keywords", [])

    generic = {"undergraduate", "research", "summer", "program", "internship",
               "opportunity", "assistant", "student", "uiuc", "illinois"}
    specific_kw = [kw for kw in keywords if kw.lower() not in generic]

    if lab and specific_kw:
        return f"{lab} — {', '.join(specific_kw[:3])}"
    if lab:
        return lab
    if specific_kw:
        return ", ".join(specific_kw[:3])
    if desc:
        first_sentence = desc.split(".")[0].strip()
        if len(first_sentence) > 15:
            return first_sentence[:80]
    return ""


def rank_opportunity(profile: dict, opportunity: dict) -> MatchResult:
    elig_score, elig_fit, elig_gap = score_eligibility(profile, opportunity)
    ready_score, ready_fit, ready_gap = score_readiness(profile, opportunity)
    up_score, up_fit, up_gap = score_upside(profile, opportunity)

    final = (
        WEIGHTS["eligibility"] * elig_score +
        WEIGHTS["readiness"] * ready_score +
        WEIGHTS["upside"] * up_score
    )

    bucket = "low_fit"
    for threshold, label in BUCKET_THRESHOLDS:
        if final >= threshold:
            bucket = label
            break

    all_fit = elig_fit + ready_fit + up_fit
    all_gap = elig_gap + ready_gap + up_gap

    research_summary = _summarize_research(opportunity)
    if research_summary and bucket in ("high_priority", "good_match"):
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


def rank_all(profile: dict, opportunities: list[dict]) -> list[MatchResult]:
    """Rank all opportunities for a profile. Returns sorted by final_score desc."""
    results = []
    for opp in opportunities:
        # Hard filters
        if profile.get("international_student"):
            elig = opp.get("eligibility", {})
            if elig.get("international_friendly") == "no":
                if profile.get("preferences", {}).get("exclude_citizenship_restricted", True):
                    continue

        result = rank_opportunity(profile, opp)

        # Apply minimum threshold
        min_threshold = profile.get("preferences", {}).get("min_match_threshold", 0)
        if result.final_score >= min_threshold:
            results.append(result)

    results.sort(key=lambda r: r.final_score, reverse=True)
    return results
