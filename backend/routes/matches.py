"""Match opportunities against a student profile."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.schemas import (
    MatchesResponse,
    MatchResultResponse,
    ProfileRequest,
)
from src.matcher.ranker import rank_all
from src.recommender.resume_advisor import analyze_gaps

router = APIRouter()

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


def _load_opportunities() -> list[dict]:
    processed = DATA_DIR / "opportunities.json"
    if processed.exists():
        with open(processed, encoding="utf-8") as f:
            data = json.load(f)
            if data:
                return data

    examples = EXAMPLES_DIR / "sample_opportunities.json"
    if examples.exists():
        with open(examples, encoding="utf-8") as f:
            return json.load(f)

    return []


@router.post("/matches", response_model=MatchesResponse)
async def get_matches(profile: ProfileRequest):
    """Score and rank all opportunities for the given profile."""
    opportunities = _load_opportunities()
    if not opportunities:
        raise HTTPException(status_code=503, detail="No opportunity data available")

    profile_dict = profile.model_dump()

    # Set defaults for preferences
    if profile_dict.get("preferences") is None:
        profile_dict["preferences"] = {
            "min_match_threshold": 25,
            "show_reach_opportunities": True,
            "prioritize_paid": True,
            "exclude_citizenship_restricted": profile_dict.get("international_student", True),
        }

    results = rank_all(profile_dict, opportunities)

    # Build opp lookup
    opp_lookup = {o["id"]: o for o in opportunities}

    response_results = []
    for r in results:
        opp = opp_lookup.get(r.opportunity_id, {})
        response_results.append(
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
                opportunity=opp,
            )
        )

    buckets = {"high_priority": 0, "good_match": 0, "reach": 0, "low_fit": 0}
    for r in response_results:
        buckets[r.bucket] = buckets.get(r.bucket, 0) + 1

    return MatchesResponse(
        total=len(response_results),
        high_priority=buckets["high_priority"],
        good_match=buckets["good_match"],
        reach=buckets["reach"],
        low_fit=buckets["low_fit"],
        results=response_results,
    )


@router.post("/matches/{opportunity_id}/gaps")
async def get_gap_analysis(opportunity_id: str, profile: ProfileRequest):
    """Get detailed gap analysis for a specific opportunity."""
    opportunities = _load_opportunities()
    opp = next((o for o in opportunities if o["id"] == opportunity_id), None)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    gaps = analyze_gaps(profile.model_dump(), opp)
    return gaps
