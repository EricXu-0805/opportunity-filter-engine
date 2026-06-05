"""
Skill-gap roadmap — aggregates per-opportunity gap analysis across a target set
of labs into a single, dependency-ordered learning path: which skills to learn,
how many of the target labs need each, suggested UIUC courses, and a rough time
estimate. Reuses analyze_gaps + the skill taxonomy; no new knowledge base.
"""

from src.matcher.ranker import SKILL_IMPLIES, _canonicalize_skill
from src.recommender.resume_advisor import SKILL_COURSES, SKILL_TIMELINE, analyze_gaps


def _order_by_prereqs(entries: list[dict]) -> list[dict]:
    """Order skills so prerequisites come first (PyTorch after Python), then by how
    many labs need them, then required-before-preferred. Stable, cycle-safe."""
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
    learning path. Each skill carries: needed_by (count of target labs),
    priority (high if required by any lab, else medium), estimated_time, courses.
    """
    # canonical skill -> aggregate
    agg: dict[str, dict] = {}
    for opp in opportunities:
        gaps = analyze_gaps(profile, opp)
        required = {
            s.lower() for s in (opp.get("eligibility", {}).get("skills_required", []) or [])
        }
        for skill in gaps["missing_skills"]:
            key = _canonicalize_skill(skill)
            entry = agg.setdefault(key, {"skill": skill, "needed_by": 0, "required": False})
            entry["needed_by"] += 1
            if skill.lower() in required:
                entry["required"] = True

    skills = [
        {
            "skill": e["skill"],
            "needed_by": e["needed_by"],
            "priority": "high" if e["required"] else "medium",
            "estimated_time": SKILL_TIMELINE.get(e["skill"], "2-4 weeks self-study"),
            "courses": SKILL_COURSES.get(e["skill"], []),
        }
        for e in agg.values()
    ]
    return {
        "skills": _order_by_prereqs(skills),
        "total_labs": len(opportunities),
    }
