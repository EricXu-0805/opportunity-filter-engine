"""Pydantic models for API request/response validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProfileRequest(BaseModel):
    """Student profile submitted from frontend."""

    name: str = ""
    school: str = "UIUC"
    year: str = "freshman"
    major: str = "ECE"
    college: str = ""
    secondary_interests: list[str] = Field(default_factory=list)
    international_student: bool = True
    seeking_type: list[str] = Field(default_factory=lambda: ["research", "summer_program"])
    desired_fields: list[str] = Field(default_factory=list)
    hard_skills: list[str] = Field(default_factory=list)
    coursework: list[str] = Field(default_factory=list)
    experience_level: str = "beginner"
    resume_ready: bool = False
    linkedin_ready: bool = False
    can_cold_email: bool = True
    preferred_location: str = "on-campus"
    time_availability: str = "summer"
    research_interests_text: str = ""
    preferences: ProfilePreferences = None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Eric",
                "year": "freshman",
                "major": "ECE",
                "college": "Grainger College of Engineering",
                "international_student": True,
                "hard_skills": ["Python", "Java", "C++"],
                "seeking_type": ["research", "summer_program"],
            }
        }


class ProfilePreferences(BaseModel):
    min_match_threshold: float = 25
    show_reach_opportunities: bool = True
    prioritize_paid: bool = True
    exclude_citizenship_restricted: bool = True


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


class ColdEmailRequest(BaseModel):
    profile: ProfileRequest
    opportunity_id: str


class ColdEmailResponse(BaseModel):
    subject: str
    body: str
    recipient_email: str
    mailto_link: str


class GapAnalysisResponse(BaseModel):
    missing_skills: list[str]
    suggested_coursework: list[str]
    resume_tips: list[str]
    preparation_timeline: list[dict]


class ResumeParseResponse(BaseModel):
    extracted_skills: list[str]
    extracted_coursework: list[str]
    experience_level: str
    raw_text: str
    success: bool
    message: str = ""


class OpportunityListResponse(BaseModel):
    total: int
    opportunities: list[dict]
    sources: dict[str, int]


ProfileRequest.model_rebuild()
