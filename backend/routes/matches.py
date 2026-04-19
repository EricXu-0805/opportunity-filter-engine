from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.data_loader import load_opportunities, load_opportunities_by_id
from backend.schemas import (
    MatchesResponse,
    MatchResultResponse,
    ProfileRequest,
)
from src.matcher.ranker import rank_all, semantic_rerank
from src.recommender.resume_advisor import analyze_gaps

router = APIRouter()

_REDACTED_FIELDS = frozenset({"contact_email", "pi_email"})
MAX_RESULTS_PER_REQUEST = 500


@router.post("/matches", response_model=MatchesResponse)
async def get_matches(
    profile: ProfileRequest,
    limit: int = Query(default=MAX_RESULTS_PER_REQUEST, ge=1, le=MAX_RESULTS_PER_REQUEST),
    offset: int = Query(default=0, ge=0),
    semantic: bool = Query(default=False),
):
    """Score and rank opportunities for the given profile.

    The full bucket counts are always returned so the client knows
    the total picture. Only the slice [offset, offset+limit) of visible
    (non-low_fit) results is returned in ``results``.

    Set ``semantic=true`` to blend LLM/TF-IDF semantic similarity into
    the top 50 results (30% weight). Adds ~200-800ms latency when
    OpenAI key is configured; free when falling back to TF-IDF.
    """
    opportunities = load_opportunities()
    if not opportunities:
        raise HTTPException(status_code=503, detail="No opportunity data available")

    profile_dict = profile.model_dump()

    if profile_dict.get("preferences") is None:
        profile_dict["preferences"] = {
            "min_match_threshold": 25,
            "show_reach_opportunities": True,
            "prioritize_paid": True,
            "exclude_citizenship_restricted": profile_dict.get("international_student", True),
        }

    results = rank_all(profile_dict, opportunities)

    opp_lookup = load_opportunities_by_id()

    if semantic:
        results = semantic_rerank(profile_dict, results, opp_lookup, top_k=50)

    buckets = {"high_priority": 0, "good_match": 0, "reach": 0, "low_fit": 0}
    visible_results = []
    for r in results:
        buckets[r.bucket] = buckets.get(r.bucket, 0) + 1
        if r.bucket != "low_fit":
            visible_results.append(r)

    page = visible_results[offset:offset + limit]
    page_response = [
        MatchResultResponse(
            opportunity_id=r.opportunity_id,
            eligibility_score=r.eligibility_score,
            readiness_score=r.readiness_score,
            upside_score=r.upside_score,
            final_score=r.final_score,
            bucket=r.bucket,
            reasons_fit=r.reasons_fit,
            reasons_gap=r.reasons_gap,
            next_steps=r.next_steps,
            opportunity={k: v for k, v in opp_lookup.get(r.opportunity_id, {}).items()
                         if k not in _REDACTED_FIELDS},
        )
        for r in page
    ]

    return MatchesResponse(
        total=len(results),
        high_priority=buckets["high_priority"],
        good_match=buckets["good_match"],
        reach=buckets["reach"],
        low_fit=buckets["low_fit"],
        results=page_response,
    )


@router.post("/matches/{opportunity_id}/gaps")
async def get_gap_analysis(opportunity_id: str, profile: ProfileRequest):
    if len(opportunity_id) > 100:
        raise HTTPException(status_code=400, detail="Invalid opportunity ID")
    opp = load_opportunities_by_id().get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    gaps = analyze_gaps(profile.model_dump(), opp)
    return gaps
