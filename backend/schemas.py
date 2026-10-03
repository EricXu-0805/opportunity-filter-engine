from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from backend.lib.email_claims import unsupported_action_claims
from backend.lib.email_contact_context import contains_context_work_claim
from backend.lib.resume_input import MAX_RESUME_TEXT_CHARACTERS

# Where an imported skill came from. Absence is the student's own choice; an
# unrecognised value is normalised to "unknown" and treated as an import.
_SKILL_SOURCES = frozenset({"resume", "github", "shared"})


class SkillItem(BaseModel):
    """One student skill, and whether its LEVEL is the student's own word.

    Both fields must be declared here or they never arrive: the routes hand
    ``profile.model_dump()`` to the email and tailor builders, and pydantic
    drops undeclared keys silently — the claim gate downstream would then read
    every import as student-chosen and be a no-op in production while its unit
    tests passed.
    """

    name: str
    level: str = "beginner"
    source: str | None = None
    confirmed: bool = False


class ProfilePreferences(BaseModel):
    min_match_threshold: float = 25
    show_reach_opportunities: bool = True
    prioritize_paid: bool = True
    exclude_citizenship_restricted: bool = True


# Unicode codepoints. Complete admitted profile data is never prefix-clipped.
PROFILE_MAX_CHARACTERS = 160_000
PROFILE_TEXT_LIMITS = {
    "name": 256, "school": 1000, "home_school": 50, "year": 100,
    "major": 1000, "college": 1000, "experience_level": 100,
    "research_interests_text": 60_000,
    "linkedin_url": 2048, "github_url": 2048, "scholar_url": 2048,
}
PROFILE_LIST_LIMITS = {
    "seeking_type": (20, 100), "desired_fields": (512, 60_000),
    "secondary_interests": (512, 1000), "coursework": (512, 1000),
}
PROFILE_SKILL_LIMIT = 512
PROFILE_SKILL_TEXT_LIMIT = 1000


def _profile_error(field: str, *, actual: int | None = None,
                   limit: int | None = None, unit: str = "characters") -> None:
    if actual is not None and limit is not None:
        raise PydanticCustomError("profile_input_limit_exceeded", "Profile input exceeds the supported limit.",
                                  {"field": field, "actual": actual, "limit": limit, "unit": unit})
    raise PydanticCustomError("profile_input_invalid", "Profile input is invalid.", {"field": field})


def _profile_text(value: object, field: str, limit: int) -> None:
    if not isinstance(value, str) or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        _profile_error(field)
    if len(value) > limit:
        _profile_error(field, actual=len(value), limit=limit)


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

    @model_validator(mode="before")
    @classmethod
    def complete_profile_input(cls, value):
        if not isinstance(value, dict):
            _profile_error("profile")
        for field, limit in PROFILE_TEXT_LIMITS.items():
            if field in value:
                _profile_text(value[field], f"profile.{field}", limit)
        for field, (count_limit, text_limit) in PROFILE_LIST_LIMITS.items():
            if field not in value:
                continue
            items = value[field]
            if not isinstance(items, list):
                _profile_error(f"profile.{field}")
            if len(items) > count_limit:
                _profile_error(f"profile.{field}", actual=len(items), limit=count_limit, unit="items")
            for item in items:
                _profile_text(item, f"profile.{field}", text_limit)
        if "hard_skills" in value:
            items = value["hard_skills"]
            if not isinstance(items, list):
                _profile_error("profile.hard_skills")
            if len(items) > PROFILE_SKILL_LIMIT:
                _profile_error("profile.hard_skills", actual=len(items), limit=PROFILE_SKILL_LIMIT, unit="items")
            for item in items:
                if isinstance(item, SkillItem):
                    item = item.model_dump()
                if isinstance(item, str):
                    _profile_text(item, "profile.hard_skills.name", PROFILE_SKILL_TEXT_LIMIT)
                elif isinstance(item, dict):
                    _profile_text(item.get("name", ""), "profile.hard_skills.name", PROFILE_SKILL_TEXT_LIMIT)
                    _profile_text(item.get("level", "beginner"), "profile.hard_skills.level", PROFILE_SKILL_TEXT_LIMIT)
                    if isinstance(item.get("source"), str) and any(0xD800 <= ord(c) <= 0xDFFF for c in item["source"]):
                        _profile_error("profile.hard_skills.source")
                else:
                    _profile_error("profile.hard_skills")
        return value

    @field_validator("home_school")
    @classmethod
    def normalize_home_school(cls, value: str) -> str:
        return value.strip().lower() or "uiuc"

    @field_validator("hard_skills", mode="before")
    @classmethod
    def normalize_skills(cls, values) -> list:
        result = []
        for item in values:
            if isinstance(item, SkillItem):
                item = item.model_dump()
            if isinstance(item, str):
                result.append(SkillItem(name=item, level="beginner"))
            else:
                # Do not mutate the caller's dictionary. Unknown provenance is
                # still imported/unconfirmed, never promoted to student-chosen.
                normalized = dict(item)
                source = normalized.get("source")
                normalized["source"] = source if source is None or (isinstance(source, str) and source in _SKILL_SOURCES) else "unknown"
                normalized["confirmed"] = normalized.get("confirmed") is True
                result.append(SkillItem(**normalized))
        return result

    @model_validator(mode="after")
    def complete_profile_budget(self):
        actual = len(json.dumps(self.model_dump(), ensure_ascii=False, separators=(",", ":")))
        if actual > PROFILE_MAX_CHARACTERS:
            _profile_error("profile", actual=actual, limit=PROFILE_MAX_CHARACTERS)
        return self

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


class ExperienceManualSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["manual"]


class ExperienceResumeSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["resume"]
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    quote: str = Field(min_length=1, max_length=6000)
    start: int = Field(ge=0, le=60000)
    end: int = Field(gt=0, le=60000)

    @field_validator("quote")
    @classmethod
    def valid_unicode(cls, value: str) -> str:
        value.encode("utf-8")
        return value

    @model_validator(mode="after")
    def valid_range(self):
        if not self.quote.strip() or self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("source range must match the quote's Unicode codepoint length")
        return self


class ExperienceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=80)
    revision: int = Field(gt=0, le=9007199254740991)
    status: Literal["candidate", "confirmed", "rejected", "withdrawn"]
    text: str = Field(min_length=1, max_length=6000)
    source: Union[ExperienceManualSource, ExperienceResumeSource] = Field(discriminator="kind")

    @field_validator("id", "text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value.encode("utf-8")
        if not value.strip():
            raise ValueError("experience fields must not be blank")
        return value


class ExperienceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1, 2]
    resume_text: str = Field(max_length=MAX_RESUME_TEXT_CHARACTERS)
    entries: list[ExperienceEntry] = Field(max_length=100)
    resume_master: dict | None = None

    @field_validator("resume_text")
    @classmethod
    def valid_unicode(cls, value: str) -> str:
        value.encode("utf-8")
        return value

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("experience version must be integer 1 or 2")
        return value

    @model_validator(mode="after")
    def valid_collection(self):
        if self.version == 2 and "resume_master" not in self.model_fields_set:
            raise ValueError("experience version 2 requires current resume_master or null")
        if self.version == 1 and "resume_master" in self.model_fields_set:
            raise ValueError("resume_master requires experience version 2")
        if self.resume_master is not None:
            from backend.lib.target_resume_ai_validation import validate_master
            validate_master(self.resume_master)
        if len({entry.id for entry in self.entries}) != len(self.entries):
            raise ValueError("duplicate experience entry id")
        # The attribution check runs on the event loop and its cost relies on this total.
        if sum(len(entry.text) for entry in self.entries) > 60000:
            raise ValueError("experience text exceeds 60000 characters")
        if sum(len(entry.source.quote) for entry in self.entries
               if isinstance(entry.source, ExperienceResumeSource)) > 60000:
            raise ValueError("experience quotes exceed 60000 characters")
        return self


# Match ECMAScript String.trim exactly; Python strip differs for FEFF/0085.
_CONTACT_TRIM = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


class _ContactFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def exact_user_text(cls, value):
        if isinstance(value, str):
            value.encode("utf-8")
            if not value or value != value.strip(_CONTACT_TRIM) or "\x00" in value:
                raise ValueError("contact text must be nonblank, trimmed and valid Unicode")
        return value


class EmailReferralContext(_ContactFields):
    referrer_name: str = Field(max_length=120)
    referral_note: str = Field(max_length=1500)
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit confirmation required")
        return value

    @field_validator("referrer_name")
    @classmethod
    def single_line_name(cls, value):
        if any(character in value for character in "\r\n\u2028\u2029"):
            raise ValueError("referrer name must be a single line")
        if contains_context_work_claim(value) or unsupported_action_claims(value):
            raise ValueError("referrer name cannot contain a student work or unsupported action claim")
        return value


class EmailFollowUpContext(_ContactFields):
    sent_confirmed: Literal[True]
    previous_message: str = Field(max_length=4000)
    sent_on: str | None = None
    reply_status: Literal["unknown", "no_reply", "received"]
    reply_text: str | None = Field(default=None, max_length=2000)

    @field_validator("sent_confirmed", mode="before")
    @classmethod
    def explicit_sent_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit sent confirmation required")
        return value

    @field_validator("sent_on")
    @classmethod
    def calendar_date(cls, value):
        if value is not None:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("sent date must be YYYY-MM-DD")
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def corresponding_reply(self):
        if (self.reply_status == "received") != (self.reply_text is not None):
            raise ValueError("reply text is required only for a received reply")
        return self


class EmailAvailabilityContext(_ContactFields):
    text: str = Field(max_length=500)
    confirmed: Literal[True]

    @field_validator("text")
    @classmethod
    def availability_not_work_claim(cls, value):
        if contains_context_work_claim(value) or unsupported_action_claims(value):
            raise ValueError("availability cannot contain a student work or unsupported action claim")
        return value

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit confirmation required")
        return value


class EmailPaperReadingContext(_ContactFields):
    title: str = Field(max_length=1000)
    work_id: str | None = None
    snapshot_version: str | None = None
    year: int | None = Field(default=None, ge=1000, le=2100)
    level: Literal["title_only", "abstract", "full_text"]
    confirmed: Literal[True]

    @model_validator(mode="after")
    def bound_snapshot(self):
        if (self.work_id is None) != (self.snapshot_version is None):
            raise ValueError("work ID and snapshot version must be provided together")
        if self.work_id is not None and (
            not re.fullmatch(r"https://openalex\.org/W[1-9][0-9]*", self.work_id)
            or not re.fullmatch(r"rs1:[0-9a-f]{64}", self.snapshot_version or "")
        ):
            raise ValueError("invalid research snapshot binding")
        return self

    @field_validator("title")
    @classmethod
    def single_line_title(cls, value):
        if any(character in value for character in "\r\n\u2028\u2029"):
            raise ValueError("paper title must be a single line")
        return value

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit reading confirmation required")
        return value


class EmailContactContext(_ContactFields):
    version: Literal[1]
    purpose: Literal["first_contact", "referral", "follow_up"]
    referral: EmailReferralContext | None = None
    follow_up: EmailFollowUpContext | None = None
    availability: EmailAvailabilityContext | None = None
    paper_reading: EmailPaperReadingContext | None = None

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("contact version must be integer 1")
        return value

    @model_validator(mode="after")
    def corresponding_context(self):
        if (self.purpose == "referral") != (self.referral is not None):
            raise ValueError("referral context must match the purpose")
        if (self.purpose == "follow_up") != (self.follow_up is not None):
            raise ValueError("follow-up context must match the purpose")
        compact = json.dumps(self.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(compact) > 9000:
            raise ValueError("contact context exceeds its total character budget")
        return self


class EmailContactReceipt(BaseModel):
    version: Literal[1] = 1
    purpose: Literal["first_contact", "referral", "follow_up"]
    context_sig: str = Field(pattern=r"^[0-9a-f]{64}$")


class ColdEmailRequest(BaseModel):
    contact_context: EmailContactContext | None = None
    expected_target_version: str | None = Field(
        default=None, strict=True, min_length=68, max_length=68,
        pattern=r"^wt1:[0-9a-f]{64}$",
    )
    profile: ProfileRequest
    opportunity_id: str
    engine: str = "template"
    # Voice overlay for the AI engine. None = no overlay (lab-type default).
    style: str | None = None
    # Legacy strings remain parseable but cannot authenticate experience.
    # Only explicitly confirmed, current structured evidence is consumed.
    resume_bullets: list[str] = Field(default_factory=list)
    experience_evidence: ExperienceEvidence | None = None

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
        # Deprecated wire compatibility only; these strings never enter the fact corpus.
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


class ExperienceResumeReference(BaseModel):
    kind: Literal["resume"]
    signature: str
    start: int
    end: int


class SelectedExperience(BaseModel):
    id: str
    revision: int
    excerpt: str = Field(min_length=1, max_length=4000)
    source: Union[ExperienceManualSource, ExperienceResumeReference] = Field(discriminator="kind")


class SelectedExperienceWithContext(SelectedExperience):
    # This is a projection of validated current facts, not the entire master.
    context: dict | None


class ExcludedExperience(BaseModel):
    id: str
    revision: int
    reason: Literal["candidate", "rejected", "withdrawn", "source_signature_mismatch", "source_quote_mismatch", "activity_reference_mismatch", "activity_ambiguous"]


class ExperienceUsage(BaseModel):
    version: Literal[1] = 1
    eligible_count: int = 0
    selected: list[Union[SelectedExperienceWithContext, SelectedExperience]] = Field(default_factory=list, max_length=8)
    excluded: list[ExcludedExperience] = Field(default_factory=list, max_length=100)
    needs_review: bool = False
    notices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounded_receipt(self):
        if sum(len(entry.excerpt) for entry in self.selected) > 4000:
            raise ValueError("experience receipt exceeds 4000 characters")
        return self


class ColdEmailResponse(BaseModel):
    target_conditions: dict | None = None
    contact_context_receipt: EmailContactReceipt | None = None
    target_version: str | None = None
    opportunity_id: str | None = None
    experience_usage: ExperienceUsage = Field(default_factory=ExperienceUsage)
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


class EmailDraftValidationRequest(ColdEmailRequest):
    """Provider-free checks of the exact manually edited draft and current target."""
    model_config = ConfigDict(extra="forbid")
    expected_target_version: str = Field(strict=True, min_length=68, max_length=68,
                                          pattern=r"^wt1:[0-9a-f]{64}$")
    subject: str = Field(strict=True)
    body: str = Field(strict=True)

    @field_validator("subject", "body")
    @classmethod
    def bounded_draft_text(cls, value, info):
        if "\0" in value:
            raise ValueError("Email text contains unsupported characters")
        try:
            size = len(value.encode("utf-16-le")) // 2
        except UnicodeEncodeError:
            raise ValueError("Email text contains invalid Unicode") from None
        limit = 2000 if info.field_name == "subject" else 5000
        if size > limit:
            raise PydanticCustomError("email_refine_text_too_long",
                                      "{field} must be at most {max_utf16} UTF-16 code units.",
                                      {"field": info.field_name, "max_utf16": limit})
        return value


EmailDraftIssue = Literal[
    "unsupported_eligibility_claim", "unsupported_deadline_claim",
    "unsupported_material_claim", "unsupported_attachment_claim", "empty_draft",
]


class EmailDraftValidationResponse(BaseModel):
    opportunity_id: str
    target_version: str
    pipeline_version: str
    contact_context_receipt: EmailContactReceipt
    target_conditions: dict
    outcome: Literal["ready", "review_required"]
    issues: list[EmailDraftIssue]


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


# A /tailor request's lists are bounded before their items are validated: pydantic
# checks a list's length first and reports one error, where 524,287 wrongly typed
# items in a 1 MiB body made 524,287 errors and a 36 MB 422 on the event loop (4-7 s).
# The bound sits far above what the route accepts, which still refuses by name
# (renovation bounds its raw sections and bullets in reject_oversized_payload).
MAX_REQUEST_BULLETS = 200


class TailorRequest(BaseModel):
    profile: ProfileRequest
    opportunity_id: str
    # Blank layout lines are dropped below; past 12 bullets the route refuses by name.
    original_bullets: list[str] = Field(default_factory=list, max_length=MAX_REQUEST_BULLETS)
    # Optional for older clients. A supplied code version is an exact pre-work
    # condition, not a claim that user-provided bullets are confirmed evidence.
    expected_pipeline_version: str | None = Field(
        default=None, strict=True, min_length=1, max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    # Optional for older clients; new writing actions bind to an anonymous
    # full-detail snapshot checked before provider work.
    expected_target_version: str | None = Field(
        default=None, strict=True, min_length=68, max_length=68,
        pattern=r"^wt1:[0-9a-f]{64}$",
    )
    # R71-D: the caller's UI language. Defaults to "en" so existing
    # clients (R71-B/C) keep their current behavior. The route uses this
    # only to pick between the EN and ZH system prompts (w14.1: each
    # rewrite stays in its own bullet's language); everything else (the
    # anti-fabrication validator, the evidence corpus, the bullet
    # limits) is locale-agnostic by design — the ASCII hard-claim
    # regex still catches Python / PyTorch / Kubernetes regardless of
    # whether the LLM output is English or Chinese, which is the
    # high-priority fabrication risk we care about.
    locale: str = "en"
    # Optional. When present, source_bullets[i] is the only evidence for bullet
    # i and original_bullets[i] is just its current wording. The modal sends it
    # after "Use kept as new originals", so accepted AI text never becomes
    # the next request's evidence.
    source_bullets: list[str] | None = Field(default=None, max_length=MAX_REQUEST_BULLETS)

    @field_validator("source_bullets")
    @classmethod
    def stringify_sources(cls, v: list | None) -> list[str] | None:
        return None if v is None else [str(source) for source in v]

    @field_validator("original_bullets")
    @classmethod
    def drop_blank_bullets(cls, v: list) -> list:
        # Blank lines are layout, not input. The 12 × 500 limit is enforced by
        # the /tailor route as a refusal that names it: slicing here used to
        # rewrite the first 500 characters of the first 12 bullets and say
        # nothing about the rest.
        lines = [str(b) for b in v]
        # A row's source_index counts the lines kept here, and the client pairs each row
        # with its own submitted line by that index. str.strip() empties a line of
        # U+001C-U+001F or U+0085 that String.prototype.trim() keeps, so dropping such a
        # line would pair every later card with the line above it: it is refused instead.
        if any(not line.strip() and any(character in "\x1c\x1d\x1e\x1f\x85" for character in line)
               for line in lines):
            raise ValueError("a bullet holds only separator control characters (U+001C-U+001F, U+0085)")
        return [line for line in lines if line.strip()]

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, v: str) -> str:
        # Accept ``"en"``, ``"zh"``, ``"en-US"``, ``"zh-CN"`` etc. — we
        # only key off the primary subtag. Unknown locales fall back to
        # "en" rather than raising so a forward-compatible client adding
        # ``"fr"`` doesn't 422 here.
        primary = (v or "").lower().split("-")[0].split("_")[0]
        return "zh" if primary == "zh" else "en"


class EvidenceLink(BaseModel):
    """A résumé phrase tied to a literal target quote, both with server offsets.

    ``entailed`` is true only when the faithfulness review confirmed that the
    phrase names the quoted thing; otherwise the quote is related text only.
    """
    id: str
    relation: Literal["same", "broader"]
    entailed: bool = False
    target_evidence: dict[str, Any]
    source_evidence: dict[str, Any]
    written_as: str | None = None


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
    # w14.0: every submitted bullet comes back once, in order. "rewritten" is a
    # reviewed rewrite; "kept" is the bullet as written with reason_code.
    status: Literal["rewritten", "kept"] = "kept"
    reason_code: str | None = None
    ops: list[str] = Field(default_factory=list)
    links: list[EvidenceLink] = Field(default_factory=list)
    # The rewrite with the posting's terms taken back out, when that passes too.
    alternative: str | None = None


class TailorStatusResponse(BaseModel):
    ai_available: bool
    pipeline_version: str


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
    target_version: str | None = None


class ResumeProcessingChunk(BaseModel):
    # Offsets are Unicode code points into the accepted, unchanged raw text.
    start: int
    end: int
    method: str
    reason: str | None = None


class ResumeProcessingCoverage(BaseModel):
    input_characters: int
    chunks: list[ResumeProcessingChunk] = Field(default_factory=list)
    ai_chunks: int = 0
    heuristic_chunks: int = 0


class ExtractBulletsRequest(BaseModel):
    # Store/accept the complete supported document. Model inputs have their
    # own smaller bound and total time/concurrency budget in the route.
    resume_text: str = Field(default="", max_length=MAX_RESUME_TEXT_CHARACTERS)
    expected_pipeline_version: str | None = Field(
        default=None, strict=True, min_length=1, max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class ExtractBulletsResponse(BaseModel):
    bullets: list[str]
    method: str = "heuristic"  # "ai" | "heuristic" | "mixed"
    warnings: list[str] = Field(default_factory=list)
    processing: ResumeProcessingCoverage | None = None
    generated_at: str | None = None
    pipeline_version: str | None = None


# --- Résumé renovation (staged: structure → macro renovate → per-bullet) -----
# The standard résumé is structured once (sections + bullets), then renovated
# toward one opportunity/professor. Every prose output routes through the same
# STUDENT-ONLY anti-fabrication corpus as /tailor; the structural stages emit
# only IDs so they cannot fabricate at all.


class ResumeBullet(BaseModel):
    id: str
    # Uncut: this is the student's own wording and the renovation rollback
    # floor. Structure text is verbatim résumé text; the rewrite stage skips
    # (and names) a bullet too long for its prompt instead of clipping it.
    text: str = ""

    @field_validator("id")
    @classmethod
    def cap_id(cls, v: str) -> str:
        # IDs are structural tokens (s1b2). Strip ALL whitespace so an id can
        # never smuggle newlines into the renovation-plan prompt, and cap the
        # length — unbounded ids were an unbounded-prompt cost vector even
        # under the 100-bullet cap.
        return re.sub(r"\s+", "", str(v))[:64]


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
    resume_text: str = Field(default="", max_length=MAX_RESUME_TEXT_CHARACTERS)
    locale: str = "en"

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, v: str) -> str:
        primary = (v or "").lower().split("-")[0].split("_")[0]
        return "zh" if primary == "zh" else "en"


class StructureResumeResponse(BaseModel):
    sections: list[ResumeSection]
    method: str = "heuristic"  # "ai" | "heuristic" | "mixed"
    warnings: list[str] = Field(default_factory=list)
    processing: ResumeProcessingCoverage | None = None


class RenovateRequest(BaseModel):
    expected_target_version: str | None = Field(
        default=None, strict=True, min_length=68, max_length=68,
        pattern=r"^wt1:[0-9a-f]{64}$",
    )
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
                raise ValueError("duplicate section id")
            seen_sections.add(s.id)
            for b in s.bullets:
                if b.id in seen_bullets:
                    raise ValueError("duplicate bullet id")
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
    ops: list[str] = Field(default_factory=list)
    links: list[EvidenceLink] = Field(default_factory=list)
    alternative: str | None = None


class RenovatedBullet(BaseModel):
    id: str
    base_text: str                                 # rollback floor — the student's own words
    variants: list[RenovatedVariant] = Field(default_factory=list)
    # Index into ``variants``; -1 == show base_text. Rollback moves this back.
    current: int = -1
    action: str = "keep"                           # "foreground" | "keep" | "demote"
    # Why a foregrounded bullet stayed as written (a TailoredBullet reason_code).
    note: str | None = None


class RenovatedSection(BaseModel):
    id: str
    heading: str = ""
    kind: str = "experience"
    bullets: list[RenovatedBullet] = Field(default_factory=list)


class RenovateResponse(BaseModel):
    target_version: str | None = None
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
    expected_target_version: str | None = Field(
        default=None, strict=True, min_length=68, max_length=68,
        pattern=r"^wt1:[0-9a-f]{64}$",
    )
    profile: ProfileRequest
    opportunity_id: str
    # Bounded by the résumé itself so an over-limit bullet reaches the route,
    # which refuses it by name instead of a generic validation error.
    current_text: str = Field(default="", max_length=MAX_RESUME_TEXT_CHARACTERS)
    base_text: str = Field(default="", max_length=MAX_RESUME_TEXT_CHARACTERS)
    instruction: str | None = Field(default=None, max_length=300)
    locale: str = "en"

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, v: str) -> str:
        primary = (v or "").lower().split("-")[0].split("_")[0]
        return "zh" if primary == "zh" else "en"


class BulletOptimizeResponse(BaseModel):
    target_version: str | None = None
    text: str
    source_evidence: str = ""
    changed: bool = False
    warnings: list[str] = Field(default_factory=list)
    status: Literal["rewritten", "kept"] = "kept"
    reason_code: str | None = None
    ops: list[str] = Field(default_factory=list)
    links: list[EvidenceLink] = Field(default_factory=list)
    alternative: str | None = None
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
