from __future__ import annotations

from typing import Union

from pydantic import BaseModel, Field, field_validator


class SkillItem(BaseModel):
    name: str
    level: str = "beginner"


class ProfilePreferences(BaseModel):
    min_match_threshold: float = 25
    show_reach_opportunities: bool = True
    prioritize_paid: bool = True
    exclude_citizenship_restricted: bool = True


class ProfileRequest(BaseModel):
    name: str = ""
    school: str = ""
    # Lowercase host-school slug ('uiuc', 'ucb', ...) — identity for the
    # matcher's discovery-scope filter. Distinct from `school`, which is the
    # free-text display name.
    home_school: str = "uiuc"
    year: str = ""
    major: str = ""
    college: str = ""
    secondary_interests: list[str] = Field(default_factory=list)
    international_student: bool = False
    seeking_type: list[str] = Field(default_factory=lambda: ["research", "summer_program"])
    desired_fields: list[str] = Field(default_factory=list)
    hard_skills: list[Union[SkillItem, str]] = Field(default_factory=list)
    coursework: list[str] = Field(default_factory=list)
    experience_level: str = "beginner"
    resume_ready: bool = False
    linkedin_ready: bool = False
    can_cold_email: bool = True
    preferred_location: str = "on-campus"
    time_availability: str = "summer"
    research_interests_text: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    search_weight: int = 50
    # "I'm still exploring" — widens matching (lifts cross-domain major floors,
    # suppresses the topic-alignment penalty, de-emphasizes readiness, and
    # diversity-samples the top buckets) for students without a settled direction.
    exploring: bool = False
    preferences: ProfilePreferences | None = None

    @field_validator("research_interests_text")
    @classmethod
    def cap_research_text(cls, v: str) -> str:
        return v[:2000]

    @field_validator("name")
    @classmethod
    def cap_name(cls, v: str) -> str:
        return v[:100]

    @field_validator("home_school")
    @classmethod
    def normalize_home_school(cls, v: str) -> str:
        return v.strip().lower()[:50] or "uiuc"

    @field_validator("linkedin_url", "github_url")
    @classmethod
    def cap_url(cls, v: str) -> str:
        return v[:300]

    @field_validator("coursework")
    @classmethod
    def cap_coursework(cls, v: list) -> list:
        return [str(c)[:20] for c in v[:50]]

    @field_validator("seeking_type", "desired_fields", "secondary_interests")
    @classmethod
    def cap_string_lists(cls, v: list) -> list:
        return [str(x)[:100] for x in v[:20]]

    @field_validator("hard_skills", mode="before")
    @classmethod
    def normalize_skills(cls, v) -> list:
        if not isinstance(v, list):
            return []
        result = []
        for item in v[:50]:
            if isinstance(item, str):
                result.append(SkillItem(name=item[:50], level="beginner"))
            elif isinstance(item, dict):
                item["name"] = str(item.get("name", ""))[:50]
                result.append(SkillItem(**item))
            else:
                result.append(item)
        return result

    def skill_names(self) -> list[str]:
        return [s.name if isinstance(s, SkillItem) else s for s in self.hard_skills]

    def skills_with_levels(self) -> list[SkillItem]:
        return [s if isinstance(s, SkillItem) else SkillItem(name=s) for s in self.hard_skills]

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Eric",
                "year": "freshman",
                "major": "ECE",
                "college": "Grainger College of Engineering",
                "international_student": True,
                "hard_skills": [
                    {"name": "Python", "level": "experienced"},
                    {"name": "Java", "level": "beginner"},
                    {"name": "C++", "level": "expert"},
                ],
                "seeking_type": ["research", "summer_program"],
            },
        },
    }


class MatchResultResponse(BaseModel):
    opportunity_id: str
    eligibility_score: float
    readiness_score: float
    upside_score: float
    final_score: float
    bucket: str
    reasons_fit: list[str]
    reasons_gap: list[str]
    next_steps: list[str]
    opportunity: dict


class MatchesResponse(BaseModel):
    total: int
    high_priority: int
    good_match: int
    reach: int
    low_fit: int
    results: list[MatchResultResponse]
    # Visible results that topically match the student's stated interests OR
    # major-derived field. `thin_inventory` true → the client shows "few matches
    # in your field" instead of implying the padded total is all field-relevant.
    field_relevant_count: int = 0
    thin_inventory: bool = False


class ColdEmailRequest(BaseModel):
    profile: ProfileRequest
    opportunity_id: str
    engine: str = "template"
    # Voice overlay for the AI engine. None = no overlay (lab-type default).
    style: str | None = None

    @field_validator("engine")
    @classmethod
    def valid_engine(cls, v: str) -> str:
        if v not in ("template", "ai"):
            raise ValueError("engine must be 'template' or 'ai'")
        return v

    @field_validator("style")
    @classmethod
    def valid_style(cls, v: str | None) -> str | None:
        if v is not None and v not in ("professional", "warm", "friendly", "lively"):
            raise ValueError(
                "style must be one of: professional, warm, friendly, lively"
            )
        return v


class ColdEmailResponse(BaseModel):
    subject: str
    body: str
    recipient_email: str
    mailto_link: str
    method: str = "template"
    lab_type: str | None = None
    # The voice overlay actually applied (echoes request.style; None on the
    # template path), plus the tone we suggest for this lab_type so the UI can
    # badge a default without re-deriving the mapping.
    style: str | None = None
    recommended_style: str | None = None
    # R72-A: when an AI draft was requested but we served the template,
    # this says why so the UI can show an accurate hint. None when method
    # is "ai" or the caller asked for the template engine directly.
    # Values: "not_configured" | "unavailable" | "invalid_output" |
    # "fabrication".
    fallback_reason: str | None = None


class GapAnalysisResponse(BaseModel):
    missing_skills: list[str]
    suggested_coursework: list[str]
    resume_tips: list[str]
    preparation_timeline: list[dict]


class RoadmapRequest(BaseModel):
    profile: ProfileRequest
    opportunity_ids: list[str]


class RoadmapSkill(BaseModel):
    skill: str
    needed_by: int
    priority: str
    estimated_time: str
    courses: list[str]


class RoadmapResponse(BaseModel):
    skills: list[RoadmapSkill]
    total_labs: int


class ResumeParseResponse(BaseModel):
    extracted_skills: list[str]
    extracted_coursework: list[str]
    experience_level: str
    raw_text: str
    success: bool
    message: str = ""
    # A labeled "Areas of Interest" / "Research Interests" line, used to seed the
    # research-interests box when empty — the frontend's only semantic-match lever.
    suggested_interests: str = ""


class TailorRequest(BaseModel):
    profile: ProfileRequest
    opportunity_id: str
    original_bullets: list[str] = Field(default_factory=list)
    # R71-D: caller-declared output language. Defaults to "en" so existing
    # clients (R71-B/C) keep their current behavior. The route uses this
    # to pick between the EN and ZH system prompts; everything else (the
    # anti-fabrication validator, the evidence corpus, the cap_bullets
    # field validator) is locale-agnostic by design — the ASCII hard-claim
    # regex still catches Python / PyTorch / Kubernetes regardless of
    # whether the LLM output is English or Chinese, which is the
    # high-priority fabrication risk we care about.
    locale: str = "en"

    @field_validator("original_bullets")
    @classmethod
    def cap_bullets(cls, v: list) -> list:
        # Cap at 12 bullets × 500 chars each so a malicious / oversized
        # paste cannot blow past the LLM context budget. Mirrors the
        # ``ProfileRequest`` field-validator pattern.
        return [str(b)[:500] for b in v[:12] if str(b).strip()]

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, v: str) -> str:
        # Accept ``"en"``, ``"zh"``, ``"en-US"``, ``"zh-CN"`` etc. — we
        # only key off the primary subtag. Unknown locales fall back to
        # "en" rather than raising so a forward-compatible client adding
        # ``"fr"`` doesn't 422 here.
        primary = (v or "").lower().split("-")[0].split("_")[0]
        return "zh" if primary == "zh" else "en"


class TailoredBullet(BaseModel):
    text: str
    source_evidence: str = ""
    # R71-E: zero-based index pointing back into the request's
    # ``original_bullets``. Lets the frontend pair each tailored bullet
    # with its source bullet for side-by-side display, even when some
    # bullets were dropped by the anti-fabrication validator and the
    # accepted list is shorter than the submitted list.
    #
    # Conventions:
    #   - AI path: equals the bullet's position in the LLM's response
    #     array, which by prompt contract matches its position in the
    #     original_bullets array (the prompt explicitly tells the model
    #     to keep the rewritten list in the same order).
    #   - Fallback path: equals the bullet's index in original_bullets
    #     verbatim, since fallback is positional passthrough.
    source_index: int = 0


class TailorResponse(BaseModel):
    tailored_bullets: list[TailoredBullet]
    method: str = "fallback"  # "ai" | "fallback"
    warnings: list[str] = Field(default_factory=list)


class ExtractBulletsRequest(BaseModel):
    # R71-G: raw resume text the modal extracts bullet-shaped lines from.
    # Capped at 20k chars (well above a one-page resume) so an oversized
    # paste can't blow the LLM context budget; the route caps again before
    # the prompt.
    resume_text: str = Field(default="", max_length=20000)


class ExtractBulletsResponse(BaseModel):
    bullets: list[str]
    method: str = "heuristic"  # "ai" | "heuristic"


class OpportunityListResponse(BaseModel):
    total: int
    opportunities: list[dict]
    sources: dict[str, int]


