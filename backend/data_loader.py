from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

_opp_cache: list[dict] = []
_opp_cache_mtime: float = 0

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    if not text or "<" not in text:
        return text
    return _HTML_TAG_RE.sub("", text).strip()


def _sanitize_opportunity(opp: dict) -> dict:
    for field in ("description_raw", "description_clean", "title"):
        if field in opp and isinstance(opp[field], str):
            opp[field] = _strip_html(opp[field])
    return opp


def load_opportunities() -> list[dict]:
    global _opp_cache, _opp_cache_mtime

    processed = DATA_DIR / "opportunities.json"
    if processed.exists():
        mtime = processed.stat().st_mtime
        if mtime != _opp_cache_mtime or not _opp_cache:
            with open(processed, encoding="utf-8") as f:
                raw = json.load(f)
            _opp_cache = [_sanitize_opportunity(o) for o in raw]
            _opp_cache_mtime = mtime
        return _opp_cache

    examples = EXAMPLES_DIR / "sample_opportunities.json"
    if examples.exists():
        with open(examples, encoding="utf-8") as f:
            return json.load(f)

    return []
