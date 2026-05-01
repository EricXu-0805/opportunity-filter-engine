from __future__ import annotations

import asyncio
import os
import time
from collections import Counter
from datetime import UTC, date, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.data_loader import load_opportunities, load_opportunities_by_id
from backend.schemas import ProfileRequest

router = APIRouter()

REDACTED_FIELDS = {"contact_email", "pi_email"}

_stats_cache: dict | None = None
_stats_cache_time: float = 0
_STATS_TTL = 300


def _redact(opp: dict) -> dict:
    return {k: v for k, v in opp.items() if k not in REDACTED_FIELDS}


@router.get("/opportunities")
async def list_opportunities(
    opportunity_type: str | None = None,
    paid: str | None = None,
    international_friendly: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
):
    opportunities = load_opportunities()

    if opportunity_type:
        opportunities = [o for o in opportunities if o.get("opportunity_type") == opportunity_type]
    if paid:
        opportunities = [o for o in opportunities if o.get("paid") == paid]
    if international_friendly:
        opportunities = [
            o for o in opportunities
            if o.get("eligibility", {}).get("international_friendly") == international_friendly
        ]

    total = len(opportunities)
    page = opportunities[offset:offset + limit]

    return {
        "total": total,
        "opportunities": [_redact(o) for o in page],
        "limit": limit,
        "offset": offset,
    }


@router.post("/opportunities/batch")
async def get_opportunities_batch(request: dict):
    """Return multiple opportunities by ID in a single request.

    Body: {"ids": ["id1", "id2", ...]} — capped at 200 to bound work.
    Missing IDs are silently skipped so the caller can always iterate
    the response alongside its own list.
    """
    ids = request.get("ids") if isinstance(request, dict) else None
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="Body must be {ids: string[]}")
    if len(ids) > 200:
        raise HTTPException(status_code=400, detail="At most 200 IDs per request")

    lookup = load_opportunities_by_id()
    results = []
    for oid in ids:
        if not isinstance(oid, str) or len(oid) > 100:
            continue
        opp = lookup.get(oid)
        if opp is not None:
            results.append(_redact(opp))
    return {"opportunities": results, "requested": len(ids), "found": len(results)}


@router.get("/opportunities/upcoming")
async def get_upcoming_deadlines(days: int = Query(default=30, ge=1, le=365)):
    """Opportunities with deadlines within the next ``days`` days, sorted ascending.

    Useful for building a calendar / "what's due soon" widget without
    re-ranking the full corpus per request.
    """
    opportunities = load_opportunities()
    today = date.today()
    cutoff = today + timedelta(days=days)
    upcoming = []
    for o in opportunities:
        deadline = o.get("deadline", "")
        if not deadline or len(deadline) < 10 or deadline[4] != "-":
            continue
        try:
            dl = date.fromisoformat(deadline[:10])
        except ValueError:
            continue
        if today <= dl <= cutoff:
            upcoming.append({
                "id": o.get("id"),
                "title": o.get("title"),
                "organization": o.get("organization"),
                "deadline": deadline,
                "days_left": (dl - today).days,
                "opportunity_type": o.get("opportunity_type"),
                "paid": o.get("paid"),
                "url": o.get("url"),
                "source": o.get("source"),
            })
    upcoming.sort(key=lambda o: o["deadline"])
    return {"total": len(upcoming), "opportunities": upcoming, "days": days}


@router.get("/opportunities/{opportunity_id}/similar")
async def get_similar_opportunities(
    opportunity_id: str,
    limit: int = Query(default=5, ge=1, le=20),
):
    """Return opportunities similar to the given one.

    Similarity is the weighted sum of:
      * shared keyword count  (primary signal)
      * same opportunity_type (small bonus)
      * shared majors         (small bonus)
      * same organization     (small bonus for "more from this lab")
    The source opportunity is always excluded.
    """
    if len(opportunity_id) > 100:
        raise HTTPException(status_code=400, detail="Invalid opportunity ID")

    lookup = load_opportunities_by_id()
    source = lookup.get(opportunity_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    source_keywords = {k.lower() for k in (source.get("keywords") or []) if isinstance(k, str)}
    source_majors = {m.lower() for m in (source.get("eligibility") or {}).get("majors", []) if isinstance(m, str)}
    source_type = source.get("opportunity_type")
    source_org = (source.get("organization") or "").lower()

    scored: list[tuple[float, dict]] = []
    for opp in load_opportunities():
        if opp.get("id") == opportunity_id:
            continue
        if not opp.get("metadata", {}).get("is_active", True):
            continue

        kws = {k.lower() for k in (opp.get("keywords") or []) if isinstance(k, str)}
        majors = {m.lower() for m in (opp.get("eligibility") or {}).get("majors", []) if isinstance(m, str)}

        shared_keywords = len(source_keywords & kws)
        shared_majors = len(source_majors & majors)

        score = 0.0
        if source_keywords:
            score += shared_keywords * 3.0
        if source_type and opp.get("opportunity_type") == source_type:
            score += 1.0
        if source_majors:
            score += shared_majors * 0.5
        if source_org and (opp.get("organization") or "").lower() == source_org:
            score += 0.5

        if score <= 0:
            continue
        scored.append((score, opp))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    return {
        "source_id": opportunity_id,
        "total": len(top),
        "opportunities": [
            {**_redact(o), "_similarity": round(s, 2)}
            for s, o in top
        ],
    }


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: str):
    if len(opportunity_id) > 100:
        raise HTTPException(status_code=400, detail="Invalid opportunity ID")

    opp = load_opportunities_by_id().get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return _redact(opp)


@router.get("/opportunities/stats/summary")
async def get_stats():
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache and now - _stats_cache_time < _STATS_TTL:
        return _stats_cache

    opportunities = load_opportunities()

    type_counts = dict(Counter(o.get("opportunity_type", "unknown") for o in opportunities))
    source_counts = dict(Counter(o.get("source", "unknown") for o in opportunities))
    paid_counts = dict(Counter(o.get("paid", "unknown") for o in opportunities))
    intl_counts = dict(Counter(
        o.get("eligibility", {}).get("international_friendly", "unknown")
        for o in opportunities
    ))

    active = sum(1 for o in opportunities if o.get("metadata", {}).get("is_active", True))
    paid_total = sum(1 for o in opportunities if o.get("paid") in ("yes", "stipend"))
    intl_total = sum(1 for o in opportunities if o.get("eligibility", {}).get("international_friendly") == "yes")

    from datetime import datetime
    from pathlib import Path
    data_path = Path(__file__).resolve().parents[2] / "data" / "processed" / "opportunities.json"
    last_updated_at = None
    if data_path.exists():
        last_updated_at = datetime.fromtimestamp(
            data_path.stat().st_mtime, tz=UTC
        ).isoformat()

    result = {
        "total": len(opportunities),
        "active": active,
        "paid_total": paid_total,
        "international_friendly_total": intl_total,
        "by_type": type_counts,
        "by_source": source_counts,
        "by_paid": paid_counts,
        "by_international": intl_counts,
        "last_updated_at": last_updated_at,
    }
    _stats_cache = result
    _stats_cache_time = now
    return result


class ChatMessage(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        return v

    @field_validator("content")
    @classmethod
    def cap_content(cls, v: str) -> str:
        return v[:4000]


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)
    profile: ProfileRequest | None = None


def _format_skill_list(skills: list) -> str:
    if not skills:
        return "(none listed)"
    out = []
    for s in skills:
        if isinstance(s, dict):
            out.append(s.get("name", ""))
        elif hasattr(s, "name"):
            out.append(s.name)
        else:
            out.append(str(s))
    return ", ".join(filter(None, out)) or "(none listed)"


def _build_chat_system_prompt(opp: dict, profile: ProfileRequest | None) -> str:
    elig = opp.get("eligibility") or {}
    app = opp.get("application") or {}
    desc = (opp.get("description_clean") or opp.get("description_raw") or "")[:1500]

    lines: list[str] = [
        "You are a focused assistant helping a UIUC undergraduate evaluate ONE specific research/internship opportunity.",
        "Use ONLY the structured information provided below. Do not invent or guess details.",
        "If a question cannot be answered from the data, say so plainly and suggest checking the source URL or emailing the contact.",
        "Keep replies under 150 words unless the user asks for more. Use plain prose, no markdown headings. Bullets OK for lists.",
        "",
        "OPPORTUNITY DATA:",
        f"- Title: {opp.get('title', '')}",
        f"- Organization: {opp.get('organization', '')} {('(' + opp.get('department', '') + ')') if opp.get('department') else ''}".strip(),
        f"- Type: {opp.get('opportunity_type', 'unknown')}",
        f"- PI / Lab: {opp.get('pi_name') or '—'} / {opp.get('lab_or_program') or '—'}",
        f"- Location: {opp.get('location', 'unspecified')} (on-campus: {opp.get('on_campus')})",
        f"- Remote: {opp.get('remote_option', 'unknown')}",
        f"- Paid: {opp.get('paid', 'unknown')}; compensation: {opp.get('compensation_details') or '—'}",
        f"- Deadline: {opp.get('deadline') or '—'} (rolling: {bool(opp.get('is_rolling'))})",
        f"- Start date: {opp.get('start_date') or '—'}; duration: {opp.get('duration') or '—'}",
        f"- Eligible majors: {', '.join(elig.get('majors') or []) or '(unspecified)'}",
        f"- Preferred years: {', '.join(elig.get('preferred_year') or []) or '(unspecified)'}",
        f"- Required skills: {', '.join(elig.get('skills_required') or []) or '(none specified)'}",
        f"- International friendly: {elig.get('international_friendly', 'unknown')}",
        f"- Citizenship required: {bool(elig.get('citizenship_required'))}",
        f"- Application: requires_resume={app.get('requires_resume', 'unknown')}, cover_letter={app.get('requires_cover_letter', 'unknown')}, recommendation={app.get('requires_recommendation', 'unknown')}, effort={app.get('application_effort', 'unknown')}",
        f"- Apply URL: {app.get('application_url') or opp.get('url') or opp.get('source_url') or '—'}",
        f"- Keywords: {', '.join(opp.get('keywords') or []) or '(none)'}",
    ]
    if desc:
        lines.append(f"- Description: {desc}")

    if profile is not None:
        p = profile
        lines.extend([
            "",
            "STUDENT PROFILE (the user has opted to share this):",
            f"- Year / college / major: {p.year or '—'} / {p.college or '—'} / {p.major or '—'}",
            f"- International student: {p.international_student}",
            f"- Skills: {_format_skill_list(p.hard_skills)}",
            f"- Coursework: {', '.join(p.coursework) or '(none listed)'}",
            f"- Experience level: {p.experience_level or '—'}",
            f"- Research interests: {(p.research_interests_text or '')[:300] or '(none stated)'}",
            "",
            "Personalize answers when the user asks fit-style questions (e.g., 'am I eligible', 'what gaps do I have').",
        ])
    else:
        lines.extend([
            "",
            "(Student profile NOT shared — answer generically; suggest the user enable profile-sharing if they ask 'is this a fit for me'.)",
        ])

    return "\n".join(lines)


def _llm_chat_call(messages: list[dict]) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = ""
    model = "gpt-4o-mini"
    if not api_key:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
        model = "google/gemini-2.0-flash-lite-001"
    if not api_key:
        return None

    try:
        import openai
    except ImportError:
        return None

    try:
        client = openai.OpenAI(api_key=api_key, base_url=base_url) if base_url else openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.4,
            max_tokens=400,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        return None


def _local_chat_fallback(opp: dict, message: str) -> str:
    elig = opp.get("eligibility") or {}
    app = opp.get("application") or {}
    bits: list[str] = [
        f"AI chat is not configured on this server, so here are the structured facts for this opportunity:",
        f"- {opp.get('title', '')}",
        f"- Type: {opp.get('opportunity_type', 'unknown')}; paid: {opp.get('paid', 'unknown')}; deadline: {opp.get('deadline') or 'not specified'}.",
        f"- Eligible majors: {', '.join(elig.get('majors') or []) or 'unspecified'}.",
        f"- Required skills: {', '.join(elig.get('skills_required') or []) or 'none listed'}.",
        f"- International-friendly: {elig.get('international_friendly', 'unknown')}; citizenship required: {bool(elig.get('citizenship_required'))}.",
        f"- Apply at: {app.get('application_url') or opp.get('url') or 'see source'}.",
        "Set OPENROUTER_API_KEY or OPENAI_API_KEY on the backend to enable AI chat.",
    ]
    return "\n".join(bits)


@router.post("/opportunities/{opportunity_id}/chat")
async def chat_with_opportunity(opportunity_id: str, body: ChatRequest):
    if len(opportunity_id) > 100:
        raise HTTPException(status_code=400, detail="Invalid opportunity ID")
    opp = load_opportunities_by_id().get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    system_prompt = _build_chat_system_prompt(opp, body.profile)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in body.history[-10:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": body.message})

    reply = await asyncio.to_thread(_llm_chat_call, messages)
    if reply:
        return {"reply": reply, "method": "llm"}
    return {"reply": _local_chat_fallback(opp, body.message), "method": "local"}
