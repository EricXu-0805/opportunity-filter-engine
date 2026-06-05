from __future__ import annotations

import asyncio

from fastapi import APIRouter

from backend.data_loader import load_opportunities_by_id
from backend.schemas import RoadmapRequest, RoadmapResponse
from src.recommender.roadmap import prepare_roadmap

router = APIRouter()

# Bound the aggregation cost / payload — far more target labs than anyone curates.
MAX_ROADMAP_OPPS = 100


@router.post("/roadmap", response_model=RoadmapResponse)
async def get_roadmap(req: RoadmapRequest):
    """Aggregate the skill gaps across a target set of opportunities (e.g. the
    user's favorites) into one dependency-ordered learning path."""
    lookup = load_opportunities_by_id()
    opps = [lookup[i] for i in req.opportunity_ids[:MAX_ROADMAP_OPPS] if i in lookup]
    if not opps:
        return RoadmapResponse(skills=[], total_labs=0)
    result = await asyncio.to_thread(prepare_roadmap, req.profile.model_dump(), opps)
    return RoadmapResponse(**result)
