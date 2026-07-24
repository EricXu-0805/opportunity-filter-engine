"""
Skill-gap roadmap — aggregates per-opportunity gap analysis across a target set
into a single, dependency-ordered learning path: which skills to learn, how
many targets need each, school-scoped course suggestions when verified, and a
rough time estimate. Reuses analyze_gaps + the skill taxonomy; no new
knowledge base.
"""

from src.matcher.ranker import SKILL_IMPLIES, _canonicalize_skill
from src.recommender.resume_advisor import SKILL_COURSES, SKILL_TIMELINE, analyze_gaps


def _listed_skills(opportunity: dict, field: str) -> list[str]:
    """Return normalized, usable skill strings from one evidence field."""
    eligibility = opportunity.get("eligibility")
    if not isinstance(eligibility, dict):
        return []
    skills = eligibility.get(field)
    if not isinstance(skills, list):
        return []
    return [skill.strip() for skill in skills if isinstance(skill, str) and skill.strip()]


def _has_listed_skill_evidence(opportunity: dict) -> bool:
    """Return whether a target carries at least one usable listed skill.

    An absent, malformed, or empty skills payload is unknown evidence, not a
    signal that the student satisfies the target.  Keep this check strict so
    the roadmap cannot turn parser/schema drift into an "all set" claim.
    """
    return bool(
        _listed_skills(opportunity, "skills_required")
        or _listed_skills(opportunity, "skills_preferred")
    )


def _order_by_prereqs(entries: list[dict]) -> list[dict]:
    """Order skills so prerequisites come first (PyTorch after Python), then by how
    many targets need them, then required-before-preferred. Stable, cycle-safe."""
    by_canon = {_canonicalize_skill(e["skill"]): e for e in entries}
    canons = set(by_canon)
    prereqs = {
        c: ({_canonicalize_skill(p) for p in SKILL_IMPLIES.get(c, [])} & canons) - {c}
        for c in canons
    }

    def sort_key(c: str):
        e = by_canon[c]
        return (-e["needed_by"], 0 if e["priority"] == "high" else 1, e["skill"].lower())

    ordered: list[dict] = []
    emitted: set[str] = set()
    remaining = set(canons)
    while remaining:
        ready = sorted((c for c in remaining if prereqs[c] <= emitted), key=sort_key)
        if not ready:  # dependency cycle — emit the rest deterministically
            ready = sorted(remaining, key=sort_key)
        for c in ready:
            ordered.append(by_canon[c])
            emitted.add(c)
        remaining -= set(ready)
    return ordered


def prepare_roadmap(profile: dict, opportunities: list[dict]) -> dict:
    """Aggregate missing-skill gaps across ``opportunities`` into an ordered
    learning path. Each skill carries: needed_by (count of saved targets),
    priority (high if required by any target, else medium), estimated_time,
    courses. Targets without any listed skill evidence are counted separately
    instead of silently passing as "covered".
    """
    # SKILL_COURSES is explicitly a UIUC catalog mapping. Fail closed unless
    # the profile's canonical home-school slug is UIUC; a display-name match or
    # a missing legacy field is not enough to authorize those course codes.
    is_uiuc = str(profile.get("home_school") or "").strip().casefold() == "uiuc"

    # canonical skill -> aggregate
    agg: dict[str, dict] = {}
    targets_with_skill_evidence = 0
    for opp in opportunities:
        if not _has_listed_skill_evidence(opp):
            continue
        targets_with_skill_evidence += 1
        required_skills = _listed_skills(opp, "skills_required")
        preferred_skills = _listed_skills(opp, "skills_preferred")
        # Analyze only sanitized evidence.  Mixed-type upstream lists keep
        # their valid strings without letting malformed members crash or count.
        evidence_opp = {
            **opp,
            "eligibility": {
                **(opp.get("eligibility") or {}),
                "skills_required": required_skills,
                "skills_preferred": preferred_skills,
            },
        }
        gaps = analyze_gaps(profile, evidence_opp)
        required = {_canonicalize_skill(skill) for skill in required_skills}
        counted_for_target: set[str] = set()
        for skill in gaps["missing_skills"]:
            key = _canonicalize_skill(skill)
            if key in counted_for_target:
                continue
            counted_for_target.add(key)
            entry = agg.setdefault(key, {"skill": skill, "needed_by": 0, "required": False})
            entry["needed_by"] += 1
            if key in required:
                entry["required"] = True

    skills = [
        {
            "skill": e["skill"],
            "needed_by": e["needed_by"],
            "priority": "high" if e["required"] else "medium",
            "estimated_time": SKILL_TIMELINE.get(e["skill"], "2-4 weeks self-study"),
            "courses": SKILL_COURSES.get(e["skill"], []) if is_uiuc else [],
            "course_catalog": "uiuc" if is_uiuc else None,
        }
        for e in agg.values()
    ]
    return {
        "skills": _order_by_prereqs(skills),
        "total_labs": len(opportunities),
        "targets_with_skill_evidence": targets_with_skill_evidence,
        "targets_without_skill_evidence": (
            len(opportunities) - targets_with_skill_evidence
        ),
    }
