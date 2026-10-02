"""Full-target suggestions: no persistence, whole-unit batches and exact receipts."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from backend.data_loader import load_opportunities_by_id
from backend.lib import target_resume_plan
from backend.lib.blocking import BlockingWorkOverloaded, BlockingWorkTimeout, run_blocking
from backend.lib.evidence_map import (
    CHECK_TIMEOUT_SECONDS,
    GENERATION_DEADLINE_SECONDS,
    review_rewrites,
    review_window,
    target_anchors,
)
from backend.lib.llm import is_configured
from backend.lib.release_scope import release_visible_opportunity_by_id
from backend.lib.target_actionability import assert_target_actionable
from backend.lib.target_resume_ai import (
    REVIEW_UNCHECKED,
    batch_preflight,
    dispatch,
    finalize,
    parse_output,
    prepare_batch,
    receipt,
    response_envelope,
    review_pairs,
    unit_too_large,
)
from backend.lib.target_resume_ai_schema import FullTargetRequest
from backend.lib.target_resume_ai_validation import InvalidTargetResume, canonical, fingerprint, validate_document
from backend.lib.target_resume_context import InvalidTargetContext, public_target_context
from backend.lib.target_resume_plan_schema import FullTargetPlanRequest
from backend.routes.opportunities import _redact

PRIVATE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}


class PrivateValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                response = await original(request)
            except RequestValidationError:
                return JSONResponse({"detail": {"code": "invalid_request"}}, status_code=422, headers=PRIVATE)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers={**(exc.headers or {}), **PRIVATE})
            for key, value in PRIVATE.items():
                response.headers[key] = value
            return response
        return handler


router = APIRouter(route_class=PrivateValidationRoute)


def authoritative_target(opp):
    return public_target_context(_redact(opp))


@router.post("/tailor/full-target/suggestions")
async def full_target_suggestions(request: FullTargetRequest):
    started = time.monotonic()
    try:
        doc = validate_document(request.draft)
        if doc["target_snapshot"].get("context_version") != 4:
            raise HTTPException(409, detail={"code": "legacy_target_context"})
        units, protected, selected, processable = prepare_batch(request, doc)
    except (InvalidTargetResume, TypeError, KeyError, ValueError, RecursionError):
        raise HTTPException(422, detail={"code": "invalid_full_target_request"}) from None
    opp = release_visible_opportunity_by_id(load_opportunities_by_id(), doc["opportunity_id"])
    if opp is None:
        raise HTTPException(404, detail={"code": "target_not_found"})
    assert_target_actionable(opp)
    try:
        current = authoritative_target(opp)
        if fingerprint(current) != doc["base"]["target_signature"] or canonical(current) != canonical(doc["target_snapshot"]):
            raise HTTPException(409, detail={"code": "target_changed"})
    except (InvalidTargetResume, InvalidTargetContext, TypeError, KeyError, ValueError):
        raise HTTPException(409, detail={"code": "target_changed"}) from None
    # A faculty description's "Research areas:" counts only as the authoritative
    # record's own words; the v4 snapshot cannot tell them from keywords.
    areas = (opp.get("metadata") or {}).get("research_areas_raw")
    anchors = target_anchors(doc["target_snapshot"], research_areas=areas if isinstance(areas, str) else None)
    messages, reason = batch_preflight(doc, processable, request.locale, anchors)
    calls = 0
    if not reason and not is_configured():
        reason = "model_unavailable"
    results = []
    if reason:
        results = [receipt(unit, reason[unit["unit_id"]] if isinstance(reason, dict) else reason) for unit in processable]
    elif processable:
        deadline = started + GENERATION_DEADLINE_SECONDS
        experiences = sum(unit["evidence"]["kind"] == "experience" for unit in processable)
        try:
            raw, reason, calls = await run_blocking(dispatch, messages, experiences, len(processable) - experiences,
                                                    deadline, timeout_seconds=max(0.001, deadline - time.monotonic()))
        except BlockingWorkOverloaded:
            reason, calls, raw = "timeout", 0, None
        except BlockingWorkTimeout:
            reason, calls = "timeout", 1  # dispatch may have started; honest upper bound, not billed count
            raw = None
        except Exception:  # No provider or payload text is returned or logged.
            reason, calls, raw = "invalid_model_response", 1, None
        if raw:
            # The contract and the claim locks run on a worker; past their deadline every
            # unit stays as written, retryable.
            try:
                results, pending = await run_blocking(parse_output, raw, processable, anchors, request.locale,
                                                      timeout_seconds=CHECK_TIMEOUT_SECONDS)
            except BlockingWorkTimeout:
                results, pending = [receipt(unit, REVIEW_UNCHECKED) for unit in processable], []
            if pending:
                # The review is a second logical call when there is still time to make it.
                calls += review_window(started) is not None
                verdicts = await review_rewrites(review_pairs(pending), started)
                try:
                    results += await run_blocking(finalize, pending, verdicts, request.locale,
                                                  timeout_seconds=CHECK_TIMEOUT_SECONDS)
                except BlockingWorkTimeout:
                    results += [receipt(item.unit, REVIEW_UNCHECKED) for item in pending]
        else:
            results = [receipt(unit, reason or "model_unavailable") for unit in processable]
    by_id = {row["unit_id"]: row for row in results}
    receipts = [receipt(unit, "unit_too_large") if unit_too_large(unit) else by_id[unit["unit_id"]] for unit in selected]
    return response_envelope(request, doc, units, protected, receipts, calls)


@router.post("/tailor/full-target/selection-plan")
async def full_target_selection_plan(request: FullTargetPlanRequest):
    try:
        doc = validate_document(request.draft)
        if doc["target_snapshot"].get("context_version") != 4:
            raise HTTPException(409, detail={"code": "legacy_target_context"})
        blocks, manifest, scope = target_resume_plan.prepare_plan(request, doc)
    except (InvalidTargetResume, TypeError, KeyError, ValueError, RecursionError):
        raise HTTPException(422, detail={"code": "invalid_full_target_plan_request"}) from None
    opp = release_visible_opportunity_by_id(load_opportunities_by_id(), doc["opportunity_id"])
    if opp is None:
        raise HTTPException(404, detail={"code": "target_not_found"})
    assert_target_actionable(opp)
    try:
        current = authoritative_target(opp)
        if fingerprint(current) != doc["base"]["target_signature"] or canonical(current) != canonical(doc["target_snapshot"]):
            raise HTTPException(409, detail={"code": "target_changed"})
    except (InvalidTargetResume, InvalidTargetContext, TypeError, KeyError, ValueError):
        raise HTTPException(409, detail={"code": "target_changed"}) from None
    messages, reason = target_resume_plan.plan_preflight(doc, blocks, scope, request.options.model_dump(), request.locale)
    calls, items = 0, []
    if not reason and not is_configured():
        reason = "model_unavailable"
    if not reason:
        try:
            raw, reason, calls = await run_blocking(target_resume_plan.dispatch, messages)
        except BlockingWorkOverloaded:
            raw, reason, calls = None, "timeout", 0
        except BlockingWorkTimeout:
            raw, reason, calls = None, "timeout", 1
        except Exception:  # Provider/payload text must not enter responses/logs.
            raw, reason, calls = None, "invalid_model_response", 1
        if raw:
            items, reason = target_resume_plan.parse_plan_output(raw, blocks, doc["target_snapshot"], request.locale)
        elif not reason:
            reason = "model_unavailable"
    return target_resume_plan.plan_response(request, doc, manifest, scope, items, reason, calls)
