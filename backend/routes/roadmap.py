from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.data_loader import load_opportunities_by_id
from backend.lib.blocking import (
    LOCAL_WORK_TIMEOUT_SECONDS,
    BlockingWorkOverloaded,
    BlockingWorkTimeout,
    run_blocking,
)
from backend.lib.release_scope import release_visible_opportunity_by_id
from backend.schemas import RoadmapRequest, RoadmapResponse
from src.recommender.roadmap import prepare_roadmap

router = APIRouter()
logger = logging.getLogger("ofe.roadmap")

# Bound the aggregation cost / payload — far more saved targets than anyone curates.
MAX_ROADMAP_OPPS = 100


def _prepare_roadmap_request(profile: dict, opportunity_ids: list[str]) -> dict:
    """Resolve targets and build the roadmap as one bounded blocking unit."""
    lookup = load_opportunities_by_id()
    # A roadmap target is a set member, not one row per repeated request id.
    # Preserve order for deterministic processing and count ids beyond the
    # bounded work window as unresolved rather than silently claiming success.
    requested_ids = list(dict.fromkeys(opportunity_ids))
    resolved_ids: list[str] = []
    inactive_targets = 0
    unverified_targets = 0
    unresolved_targets = max(0, len(requested_ids) - MAX_ROADMAP_OPPS)
    for opportunity_id in requested_ids[:MAX_ROADMAP_OPPS]:
        opportunity = release_visible_opportunity_by_id(lookup, opportunity_id)
        if opportunity is None:
            unresolved_targets += 1
            continue
        metadata = opportunity.get("metadata")
        activity = metadata.get("is_active") if isinstance(metadata, dict) else None
        if activity is True:
            resolved_ids.append(opportunity_id)
        elif activity is False:
            inactive_targets += 1
        else:
            unverified_targets += 1
    opps = [lookup[opportunity_id] for opportunity_id in resolved_ids]
    result = (
        prepare_roadmap(profile, opps)
        if opps
        else {
            "skills": [],
            "total_labs": 0,
            "targets_with_skill_evidence": 0,
            "targets_without_skill_evidence": 0,
        }
    )
    return {
        **result,
        "requested_targets": len(requested_ids),
        "resolved_targets": len(opps),
        "unresolved_targets": unresolved_targets,
        "inactive_targets": inactive_targets,
        "unverified_targets": unverified_targets,
    }


@router.post("/roadmap", response_model=RoadmapResponse)
async def get_roadmap(req: RoadmapRequest):
    """Aggregate the skill gaps across a target set of opportunities (e.g. the
    user's favorites) into one dependency-ordered learning path. Campus course
    codes are returned only for a canonical UIUC home-school profile."""
    try:
        result = await run_blocking(
            _prepare_roadmap_request,
            req.profile.model_dump(),
            req.opportunity_ids,
            timeout_seconds=LOCAL_WORK_TIMEOUT_SECONDS,
        )
    except BlockingWorkOverloaded as exc:
        logger.warning("roadmap_work_rejected reason=overloaded")
        raise HTTPException(
            status_code=503,
            detail="Roadmap service is busy. Try again shortly.",
            headers={"Retry-After": "5"},
        ) from exc
    except BlockingWorkTimeout as exc:
        logger.warning("roadmap_work_rejected reason=timeout")
        raise HTTPException(
            status_code=503,
            detail="Roadmap service timed out. Try again shortly.",
            headers={"Retry-After": "5"},
        ) from exc
    return RoadmapResponse(**result)
