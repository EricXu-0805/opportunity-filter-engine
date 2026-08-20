from __future__ import annotations

import re
from typing import Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError


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
    can_cold_email: bool = True
    research_interests_text: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    # The student's own public Google Scholar profile URL. Like linkedin_url it
    # does not inform matching — it's surfaced in the cold-email signature.
    scholar_url: str = ""
    search_weight: int = 50
    # "I'm still exploring" — widens matching (lifts cross-domain major floors,
    # suppresses the topic-alignment penalty, de-emphasizes readiness, and
    # diversity-samples the top buckets) for students without a settled direction.
    exploring: bool = False
    # Cross-school opt-in: other schools' resources are hidden by default
    # (home school first); national records and summer programs always show.
    include_cross_school: bool = False
    preferences: ProfilePreferences | None = None

    @field_validator("research_interests_text")
    @classmethod
    def cap_research_text(cls, v: str) -> str:
        return v[:2000]

    @field_validator("name")
    @classmethod
    def cap_name(cls, v: str) -> str:
        return v[:100]

    # These four are interpolated verbatim into the chat system prompt —
    # uncapped they let a 100k-char field balloon the prompt past the LLM
    # context budget.
    @field_validator("year", "major", "college", "experience_level")
    @classmethod
    def cap_short_text(cls, v: str) -> str:
        return v[:100]

    @field_validator("home_school")
    @classmethod
    def normalize_home_school(cls, v: str) -> str:
        return v.strip().lower()[:50] or "uiuc"

    @field_validator("linkedin_url", "github_url", "scholar_url")
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
                item["level"] = str(item.get("level", "beginner"))[:50]
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


class MatchViewState(BaseModel):
    """Exact server-side view of the canonical Match universe.

    The browser previously computed these predicates from one giant response.
    Keeping them explicit lets a bounded page retain exact search/filter/tab
    counts instead of treating the first 50 rows as the whole universe.
    """

    tab: Literal["all", "high_priority", "good_match", "reach", "starred"] = "all"
    search_query: str = Field(default="", max_length=200)
    paid: Literal["", "yes", "no"] = ""
    intl: Literal["", "yes", "no"] = ""
    source: str = Field(default="", max_length=100)
    on_campus: Literal["", "yes", "no"] = ""
    # Keep in lockstep with lib/types.DeadlineFilterValue on the client and
    # with src/saved_searches/filter.py in the digest cron: a value the client
    # can send but this Literal rejects is a 422 on the whole match view, not a
    # degraded filter.
    deadline: Literal["", "rolling", "7", "14", "30", "passed"] = ""
    min_score: int = Field(default=0, ge=0, le=100)
    scope: Literal["", "campus", "open"] = ""
    sort_by: Literal["score", "deadline", "newest"] = "score"
    show_dismissed: bool = False
    favorite_ids: list[str] = Field(default_factory=list)
    dismissed_ids: list[str] = Field(default_factory=list)
    # Browser-local calendar date. Deadline filters use calendar-day
    # differences, matching the former client implementation independent of
    # the Render instance's timezone.
    today: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("favorite_ids", "dismissed_ids")
    @classmethod
    def cap_view_ids(cls, values: list) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in values[:5000]:
            value = str(raw)[:100]
            if value and value not in seen:
                seen.add(value)
                out.append(value)
        return out

    @field_validator("today")
    @classmethod
    def valid_calendar_date(cls, value: str) -> str:
        from datetime import date

        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("today must be a valid ISO calendar date") from exc
        return value


class MatchViewRequest(BaseModel):
    profile: ProfileRequest
    view: MatchViewState
    page_size: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=768)


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
    # One concrete, student-specific sentence from the LLM rerank pass — the
    # card's lead line for top-K results; None outside the reranked window.
    ai_reason: str | None = None
    # Canonical unknown-semantics trace: dotted "profile.*" / "opportunity.*"
    # names of inputs whose missing/unknown state made this decision less
    # certain. Each was scored with its documented neutral policy — surfaces
    # may render "verify" hints from these but must not reinterpret them.
    unknowns: list[str] = Field(default_factory=list)
    opportunity: dict


class MatchesResponse(BaseModel):
    # The pageable universe: unique visible (non-low_fit) results. Invariant:
    # total == high_priority + good_match + reach == the number of items a
    # full offset traversal returns. low_fit is counted below but never served.
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
    # Version of the matching logic + tunables that produced this response
    # (src.matcher.config.MATCHER_VERSION). Clients key their caches on it so
    # results from two matcher generations can never silently coexist.
    matcher_version: str = ""
    # Server attestation of the EFFECTIVE match mode: true only when the paid
    # refine actually produced judgements for this result set. The client asks
    # for a mode with ?llm=; this reports the one it got. They differ whenever
    # the provider is unconfigured, the day budget degraded the request, or a
    # batch came back unusable — and a badge that reads the request instead of
    # this one claims work that never happened.
    ai_refined: bool = False
    # Bounded paging contract. ``total`` remains the complete visible
    # universe; these fields describe only this response window.
    returned_count: int = 0
    has_more: bool = False
    next_cursor: str | None = None
    result_set_id: str = ""
    contract_version: str = ""
    # Announces that every row in this response carries a complete
    # `target_truth` and that historical records have already been filtered out.
    # Separate from `contract_version` so it can ship while the wire version
    # stays put through a split frontend/backend deploy, and present even on an
    # empty page — which has no rows to inspect and would otherwise be
    # indistinguishable from an old backend's empty page.
    #
    # Required, with no default. An omitted marker is a page every client
    # correctly refuses, so a default would turn a forgotten argument at a new
    # construction site into a silent production outage instead of an error
    # here. (An OLD backend still sends no such field at all; that is the
    # client's absent case, and unrelated to this server's own obligation.)
    target_truth_contract: str
    view_start: int = 0
    # Exact server-side view metadata. Optional/defaulted so the canonical
    # /matches paging endpoint and older clients remain compatible.
    filtered_total: int | None = None
    view_counts: dict[str, int] = Field(default_factory=dict)
    source_facets: list[dict[str, Union[str, int]]] = Field(default_factory=list)
    scope_available: bool = False
    # How many records each deadline chip would return, keyed "7"/"14"/"30"/
    # "passed". Empty from an older backend, which the rail reads as "no
    # evidence" and hides the chips — the same fail-closed direction as
    # RELEASE_SCOPE, and the safe one: a hidden live chip is a smaller lie than
    # a shown dead one.
    deadline_facets: dict[str, int] = Field(default_factory=dict)
    view_id: str = ""


class ColdEmailRequest(BaseModel):
    profile: ProfileRequest
    opportunity_id: str
    engine: str = "template"
    # Voice overlay for the AI engine. None = no overlay (lab-type default).
    style: str | None = None
    # The student's real resume experience bullets (from /tailor/extract-
    # bullets). Optional + defaulted so existing clients that omit it are
    # unaffected. Only the AI engine uses them; they are added to the
    # anti-fabrication corpus so a draft may cite the student's own experience.
    resume_bullets: list[str] = Field(default_factory=list)

    @field_validator("profile")
    @classmethod
    def require_student_name(cls, v: ProfileRequest) -> ProfileRequest:
        """Cold-email generation must have the sender's explicit identity.

        ``ProfileRequest.name`` stays optional for matching and browsing, but
        every cold-email entry point shares this request model.  Validating
        here rejects template, AI, streaming, and variant requests before any
        generation or provider work can begin — no more emails signed
        "Student".
        """
        name = v.name.strip()
        if not name:
            raise PydanticCustomError(
                "student_name_required",
                "student_name_required",
            )
        return v.model_copy(update={"name": name})

    @field_validator("resume_bullets")
    @classmethod
    def cap_bullets(cls, v: list) -> list:
        # Mirror TailorRequest.cap_bullets: 12 × 500 chars caps the LLM budget.
        return [str(b)[:500] for b in v[:12] if str(b).strip()]

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
    # W10b contact bar: "revealed" | "sign_in_required" | "unavailable".
    # recipient_email is non-empty only when "revealed" (verified-provenance
    # address + signed-in session); the UI keys its send affordance off this.
    recipient_status: str = "unavailable"
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
    # Evidence honesty: "specific" when the posting carries real research
    # signal (keywords / stated areas / verified works) the draft could be
    # tailored with; "no_target_data" when it carries none, so the draft is
    # NECESSARILY generic and the UI must not present it as tailored. The
    # majority of scraped faculty records are research-blind — silence here
    # showed students a "personalized" email nothing personalizes.
    grounding: str = "specific"
    # W12 draft provenance: when/what produced this draft and how current the
    # source record was. source_freshness: "fresh" | "stale" | "inactive" |
    # "unknown" — never optimistically "fresh" when last_verified is absent.
    generated_at: str | None = None
    corpus_version: str | None = None
    pipeline_version: str | None = None
    source_freshness: str | None = None


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
    # Course codes currently come only from the verified UIUC mapping. None
    # means the roadmap is generic self-study guidance, not a campus catalog.
    course_catalog: Literal["uiuc"] | None = None


class RoadmapResponse(BaseModel):
    skills: list[RoadmapSkill]
    # ``total_labs`` is the deployed frontend's field name and means targets
    # actually resolved against the current corpus. The additive counters
    # below keep stale favorite ids from masquerading as an all-set skill
    # profile; they default to 0 so callers constructing minimal responses
    # keep working.
    total_labs: int = Field(ge=0)
    requested_targets: int = Field(default=0, ge=0)
    resolved_targets: int = Field(default=0, ge=0)
    unresolved_targets: int = Field(default=0, ge=0)
    # Existing records can resolve by id without being safe current targets.
    # Explicitly retired and not-yet-verified records are counted separately
    # and never contribute skills to the learning path.
    inactive_targets: int = Field(default=0, ge=0)
    unverified_targets: int = Field(default=0, ge=0)
    # A resolved target is analyzable only when its record lists at least one
    # usable required/preferred skill. Empty or malformed skill fields remain
    # explicitly unknown and must never be interpreted as profile coverage.
    targets_with_skill_evidence: int = Field(default=0, ge=0)
    targets_without_skill_evidence: int = Field(default=0, ge=0)


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
    # W13 target binding + provenance (mirrors the W12 cold-email stamps):
    # which target this suggestion set was generated for, when, and by what
    # pipeline — the client pairs suggestions to targets by the echo instead
    # of trusting its own bookkeeping.
    opportunity_id: str | None = None
    generated_at: str | None = None
    pipeline_version: str | None = None


class ExtractBulletsRequest(BaseModel):
    # R71-G: raw resume text the modal extracts bullet-shaped lines from.
    # Capped at 20k chars (well above a one-page resume) so an oversized
    # paste can't blow the LLM context budget; the route caps again before
    # the prompt.
    resume_text: str = Field(default="", max_length=20000)


class ExtractBulletsResponse(BaseModel):
    bullets: list[str]
    method: str = "heuristic"  # "ai" | "heuristic"


# --- Résumé renovation (staged: structure → macro renovate → per-bullet) -----
# The standard résumé is structured once (sections + bullets), then renovated
# toward one opportunity/professor. Every prose output routes through the same
# STUDENT-ONLY anti-fabrication corpus as /tailor; the structural stages emit
# only IDs so they cannot fabricate at all.


class ResumeBullet(BaseModel):
    id: str
    text: str = ""

    @field_validator("id")
    @classmethod
    def cap_id(cls, v: str) -> str:
        # IDs are structural tokens (s1b2). Strip ALL whitespace so an id can
        # never smuggle newlines into the renovation-plan prompt, and cap the
        # length — unbounded ids were an unbounded-prompt cost vector even
        # under the 100-bullet cap.
        return re.sub(r"\s+", "", str(v))[:64]

    @field_validator("text")
    @classmethod
    def cap_text(cls, v: str) -> str:
        return str(v)[:600]


class ResumeSection(BaseModel):
    id: str
    heading: str = ""
    # "experience" | "projects" | "research" | "education" | "skills" | "other".
    # Free-form but capped; only used to label the section, never a claim.
    kind: str = "experience"
    bullets: list[ResumeBullet] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def cap_id(cls, v: str) -> str:
        # Same rules as ResumeBullet.id (prompt-safety + cost bound).
        return re.sub(r"\s+", "", str(v))[:64]

    @field_validator("heading")
    @classmethod
    def cap_heading(cls, v: str) -> str:
        return str(v)[:120]

    @field_validator("kind")
    @classmethod
    def cap_kind(cls, v: str) -> str:
        # Interpolated into the plan prompt as a bare label — flatten
        # whitespace and cap so it can't carry payloads or bloat the prompt.
        return re.sub(r"\s+", " ", str(v)).strip()[:24]

    @field_validator("bullets")
    @classmethod
    def cap_bullets(cls, v: list) -> list:
        return v[:40]


class StructureResumeRequest(BaseModel):
    resume_text: str = Field(default="", max_length=20000)
    locale: str = "en"

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, v: str) -> str:
        primary = (v or "").lower().split("-")[0].split("_")[0]
        return "zh" if primary == "zh" else "en"


class StructureResumeResponse(BaseModel):
    sections: list[ResumeSection]
    method: str = "heuristic"  # "ai" | "heuristic"
    warnings: list[str] = Field(default_factory=list)


class RenovateRequest(BaseModel):
    profile: ProfileRequest
    opportunity_id: str
    sections: list[ResumeSection] = Field(default_factory=list)
    locale: str = "en"

    @field_validator("sections")
    @classmethod
    def cap_sections(cls, v: list) -> list:
        return v[:15]

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, v: str) -> str:
        primary = (v or "").lower().split("-")[0].split("_")[0]
        return "zh" if primary == "zh" else "en"

    @model_validator(mode="before")
    @classmethod
    def reject_oversized_payload(cls, data):
        # Runs on the RAW payload, before the silent per-section/section-count
        # truncations (cap_bullets 40, cap_sections 15). Without this, a
        # 2×61-bullet résumé would be quietly cut to 80 and renovated with 42
        # bullets missing — silent data loss on the user's résumé. A renovation
        # must see the WHOLE document or refuse loudly; oversize is a client
        # bug or abuse, so 422 with a clear message.
        if isinstance(data, dict) and isinstance(data.get("sections"), list):
            sections = data["sections"]
            if len(sections) > 15:
                raise ValueError("too many sections: max 15")
            total = 0
            for s in sections:
                if isinstance(s, dict) and isinstance(s.get("bullets"), list):
                    n = len(s["bullets"])
                    if n > 40:
                        raise ValueError("a section exceeds 40 bullets")
                    total += n
            if total > 100:
                raise ValueError("too many bullets: max 100 across all sections")
        return data

    @model_validator(mode="after")
    def validate_section_tree(self) -> RenovateRequest:
        # Global bullet cap + ID uniqueness. The per-section caps (15×40) still
        # admit 600 bullets ≈ a ~47K-token plan prompt — an abuse-sized cost
        # hole; real résumés run 15-60 bullets, so 100 is generous. Duplicate
        # IDs would attach one rewrite to two places and break the rollback
        # chain's identity, so reject outright rather than guess.
        total = 0
        seen_sections: set[str] = set()
        seen_bullets: set[str] = set()
        for s in self.sections:
            if s.id in seen_sections:
                raise ValueError(f"duplicate section id: {s.id}")
            seen_sections.add(s.id)
            for b in s.bullets:
                if b.id in seen_bullets:
                    raise ValueError(f"duplicate bullet id: {b.id}")
                seen_bullets.add(b.id)
                total += 1
        if total > 100:
            raise ValueError("too many bullets: max 100 across all sections")
        return self


class RenovatedVariant(BaseModel):
    # "base" is never stored in the chain (base_text is the floor); a variant is
    # one of the appended reframings.
    source: str  # "macro" | "ai" | "user"
    text: str
    source_evidence: str = ""


class RenovatedBullet(BaseModel):
    id: str
    base_text: str                                 # rollback floor — the student's own words
    variants: list[RenovatedVariant] = Field(default_factory=list)
    # Index into ``variants``; -1 == show base_text. Rollback moves this back.
    current: int = -1
    action: str = "keep"                           # "foreground" | "keep" | "demote"


class RenovatedSection(BaseModel):
    id: str
    heading: str = ""
    kind: str = "experience"
    bullets: list[RenovatedBullet] = Field(default_factory=list)


class RenovateResponse(BaseModel):
    sections: list[RenovatedSection]
    method: str = "fallback"  # "ai" | "fallback"
    warnings: list[str] = Field(default_factory=list)
    # W13 target binding + provenance (mirrors the W12 cold-email stamps):
    # which target this suggestion set was generated for, when, and by what
    # pipeline — the client pairs suggestions to targets by the echo instead
    # of trusting its own bookkeeping.
    opportunity_id: str | None = None
    generated_at: str | None = None
    pipeline_version: str | None = None


class BulletOptimizeRequest(BaseModel):
    profile: ProfileRequest
    opportunity_id: str
    current_text: str = Field(default="", max_length=600)
    base_text: str = Field(default="", max_length=600)
    instruction: str | None = Field(default=None, max_length=300)
    locale: str = "en"

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, v: str) -> str:
        primary = (v or "").lower().split("-")[0].split("_")[0]
        return "zh" if primary == "zh" else "en"


class BulletOptimizeResponse(BaseModel):
    text: str
    source_evidence: str = ""
    changed: bool = False
    warnings: list[str] = Field(default_factory=list)
    # W13 target binding + provenance (mirrors the W12 cold-email stamps):
    # which target this suggestion set was generated for, when, and by what
    # pipeline — the client pairs suggestions to targets by the echo instead
    # of trusting its own bookkeeping.
    opportunity_id: str | None = None
    generated_at: str | None = None
    pipeline_version: str | None = None


class OpportunityListResponse(BaseModel):
    total: int
    opportunities: list[dict]
    sources: dict[str, int]
