"""POST /api/import-url — user pastes a URL, server returns a structured
opportunity draft for the frontend's "Add by URL" review form.

Wraps src.collectors.url_parser.parse_url_llm. The route only validates
the URL and shapes the response; all extraction + LLM fallback lives in
the collector module so manual-import CLI (src.collectors.manual_importer)
gets the same code path for free.

The returned draft is NOT persisted — the client is expected to let the
user edit before saving. Rate-limited tightly (5/min/IP) in backend/main.py
because every successful call makes both an outbound HTTP fetch AND an
LLM completion (costs $ + can be abused for SSRF probes).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.lib.blocking import (
    SINGLE_LLM_TIMEOUT_SECONDS,
    BlockingWorkOverloaded,
    BlockingWorkTimeout,
    run_blocking,
)
from src.collectors.import_document import ImportDocumentError
from src.collectors.url_parser import UrlImportSourceError, is_safe_url, parse_url_llm

logger = logging.getLogger(__name__)
router = APIRouter()

_SOURCE_ERRORS = {
    "invalid_html": "The page could not be read as HTML. Paste the complete opportunity text.",
    "unsupported_content_type": "This link does not contain a supported page. Paste the complete opportunity text.",
    "empty_page": "No readable page text was found. Paste the complete opportunity text.",
    "metadata_only": "Only a page summary was available. Paste the complete opportunity text.",
    "access_page": "The page blocked access to its content. Paste the complete opportunity text.",
    "javascript_required": "The page text requires JavaScript. Paste the complete opportunity text.",
    "too_large": "The page is too large to import in full. Use a page for one opportunity.",
}


def _source_error(reason: object) -> HTTPException:
    # Fixed codes/messages only: source URLs can contain private query tokens.
    safe_reason = reason if isinstance(reason, str) and reason in _SOURCE_ERRORS else "invalid_html"
    too_large = safe_reason == "too_large"
    return HTTPException(status_code=413 if too_large else 422, detail={
        "code": "import_input_too_large" if too_large else "import_source_unreadable",
        "reason": safe_reason,
        "message": _SOURCE_ERRORS[safe_reason],
        "retryable": False,
    })


class ImportUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class ImportUrlResponse(BaseModel):
    ok: bool
    opportunity: Optional[dict] = None
    error: Optional[str] = None
    llm_enriched: bool = False


@router.post("/import-url", response_model=ImportUrlResponse)
async def import_url(req: ImportUrlRequest) -> ImportUrlResponse:
    ok, reason = is_safe_url(req.url)
    if not ok:
        raise HTTPException(status_code=400, detail=f"unsafe url: {reason}")

    # DNS, HTTP, HTML parsing, and the optional LLM client are synchronous.
    # Keep them off the ASGI event loop so one slow import cannot stall every
    # request handled by the worker.
    try:
        result = await run_blocking(
            parse_url_llm,
            req.url,
            timeout_seconds=SINGLE_LLM_TIMEOUT_SECONDS,
        )
    except ImportDocumentError as exc:
        raise _source_error(exc.reason) from exc
    except UrlImportSourceError as exc:
        # Fixed text only: signed or personal URLs must not be echoed in errors.
        message = (
            "The link opened a different page. Open the intended page and import its address."
            if exc.reason == "redirect_mismatch"
            else "The page address could not be verified. Try importing the page again."
        )
        return ImportUrlResponse(ok=False, error=message)
    except BlockingWorkOverloaded as exc:
        logger.warning("import_url_work_rejected reason=overloaded")
        raise HTTPException(
            status_code=503,
            detail="URL import is busy. Try again shortly.",
            headers={"Retry-After": "5"},
        ) from exc
    except BlockingWorkTimeout as exc:
        logger.warning("import_url_work_rejected reason=timeout")
        raise HTTPException(
            status_code=503,
            detail="URL import timed out. Try again shortly.",
            headers={"Retry-After": "5"},
        ) from exc
    if result is None:
        return ImportUrlResponse(
            ok=False,
            error="failed to fetch or parse the URL",
        )

    return ImportUrlResponse(
        ok=True,
        opportunity=asdict(result),
        llm_enriched=bool(result.extra_fields.get("llm_enriched")),
    )
