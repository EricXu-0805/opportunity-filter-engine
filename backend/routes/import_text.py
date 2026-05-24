"""POST /api/import-text — user pastes raw text describing an opportunity,
server returns the same structured draft shape /api/import-url returns.

Used when the source URL is blocked by anti-bot (LinkedIn job posts),
behind a paywall (Indeed), or simply doesn't exist (Slack/email forwards
of a posting). The frontend's /import page offers it as a sibling "By
Text" mode alongside the URL flow.

Unlike the URL flow there is no V1 OG-meta fallback — paste-text is
meaningless without LLM extraction, so the route returns ok=false when
no LLM provider is configured or when extraction fails.

Rate-limited 5/min/IP in backend/main.py because every successful call
runs an LLM completion (costs $ + the input body can be up to ~50KB of
arbitrary text).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.collectors.url_parser import (
    PASTE_TEXT_MAX_CHARS,
    PASTE_TEXT_MIN_CHARS,
    parse_text_llm,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ImportTextRequest(BaseModel):
    text: str = Field(
        min_length=PASTE_TEXT_MIN_CHARS,
        max_length=PASTE_TEXT_MAX_CHARS,
    )


class ImportTextResponse(BaseModel):
    ok: bool
    opportunity: Optional[dict] = None
    error: Optional[str] = None
    llm_enriched: bool = False


@router.post("/import-text", response_model=ImportTextResponse)
async def import_text(req: ImportTextRequest) -> ImportTextResponse:
    trimmed = req.text.strip()
    if len(trimmed) < PASTE_TEXT_MIN_CHARS:
        return ImportTextResponse(
            ok=False,
            error="text is too short after trimming whitespace",
        )

    result = parse_text_llm(trimmed)
    if result is None:
        return ImportTextResponse(
            ok=False,
            error="AI extraction unavailable — paste-text requires an LLM and the call did not return usable JSON",
        )

    return ImportTextResponse(
        ok=True,
        opportunity=asdict(result),
        llm_enriched=bool(result.extra_fields.get("llm_enriched")),
    )
