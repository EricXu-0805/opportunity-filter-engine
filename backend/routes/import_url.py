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

from src.collectors.url_parser import is_safe_url, parse_url_llm

logger = logging.getLogger(__name__)
router = APIRouter()


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

    result = parse_url_llm(req.url)
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
