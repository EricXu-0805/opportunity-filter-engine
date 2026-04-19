from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

_opp_cache: list[dict] = []
_opp_cache_by_id: dict[str, dict] = {}
_opp_cache_mtime: float = 0
_tfidf_fitted_mtime: float = -1

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


def _opportunity_corpus_text(opp: dict) -> str:
    parts = [
        opp.get("title", ""),
        opp.get("lab_or_program", ""),
        " ".join(opp.get("keywords", []) or []),
        opp.get("description_clean") or opp.get("description_raw") or "",
    ]
    return " ".join(p for p in parts if p)


def _maybe_fit_tfidf(opportunities: list[dict], mtime: float) -> None:
    global _tfidf_fitted_mtime
    if mtime == _tfidf_fitted_mtime or not opportunities:
        return
    try:
        from src.matcher.embeddings import fit_tfidf_corpus
        fit_tfidf_corpus([_opportunity_corpus_text(o) for o in opportunities])
        _tfidf_fitted_mtime = mtime
    except Exception as e:
        logger.warning("TF-IDF corpus fit failed: %s", e)


def load_opportunities() -> list[dict]:
    global _opp_cache, _opp_cache_by_id, _opp_cache_mtime

    processed = DATA_DIR / "opportunities.json"
    if processed.exists():
        mtime = processed.stat().st_mtime
        if mtime != _opp_cache_mtime or not _opp_cache:
            with open(processed, encoding="utf-8") as f:
                raw = json.load(f)
            _opp_cache = [_sanitize_opportunity(o) for o in raw]
            _opp_cache_by_id = {o["id"]: o for o in _opp_cache if o.get("id")}
            _opp_cache_mtime = mtime
        _maybe_fit_tfidf(_opp_cache, mtime)
        return _opp_cache

    examples = EXAMPLES_DIR / "sample_opportunities.json"
    if examples.exists():
        with open(examples, encoding="utf-8") as f:
            data = json.load(f)
        _maybe_fit_tfidf(data, 0.0)
        return data

    return []


def load_opportunities_by_id() -> dict[str, dict]:
    load_opportunities()
    return _opp_cache_by_id
