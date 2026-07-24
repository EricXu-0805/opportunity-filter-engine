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

# json.load interns object KEYS but never values, so the parsed corpus holds
# hundreds of thousands of duplicate value strings (every "freshman", every
# shared majors vocabulary entry, department-boilerplate application/work-auth
# text repeated across a school's postings). Pooling them collapses equal
# strings to one object — worth hundreds of MB at 126k records on the 2GB
# instance. The pool itself is an index and is dropped after each full load;
# the cap keeps unique long descriptions from churning it.
_STR_POOL: dict[str, str] = {}
_POOL_MAX_LEN = 512


def _dedupe_strings(obj) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if len(v) <= _POOL_MAX_LEN:
                    obj[k] = _STR_POOL.setdefault(v, v)
            else:
                _dedupe_strings(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                if len(v) <= _POOL_MAX_LEN:
                    obj[i] = _STR_POOL.setdefault(v, v)
            else:
                _dedupe_strings(v)


def _strip_html(text: str) -> str:
    if not text or "<" not in text:
        return text
    return _HTML_TAG_RE.sub("", text).strip()


def _sanitize_opportunity(opp: dict) -> dict:
    for field in ("description_raw", "description_clean", "title"):
        if field in opp and isinstance(opp[field], str):
            opp[field] = _strip_html(opp[field])
    # Pipeline-only payloads no serving path reads (verified: zero consumers in
    # backend/, src/matcher/ and frontend/src): drop them from the in-memory
    # copy. The on-disk corpus keeps them — the collectors' own passes
    # (llm_tagger reads eligibility_text_raw, enrichment audits read notes)
    # open the file directly, never through this loader.
    elig = opp.get("eligibility")
    if isinstance(elig, dict):
        elig.pop("eligibility_text_raw", None)
    meta = opp.get("metadata")
    if isinstance(meta, dict):
        meta.pop("notes", None)
        meta.pop("research_areas_raw", None)
        # Harvest bookkeeping with zero serving consumers (last_verified IS
        # served on cards and stays).
        meta.pop("first_seen_at", None)
        meta.pop("last_seen_at", None)
    _dedupe_strings(opp)
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
        # Generator, not a list: the joined corpus texts are ~90 MiB for 32k
        # records and the fit only needs one pass — materializing them spikes
        # startup RSS for nothing on a 2 GB instance.
        fit_tfidf_corpus(_opportunity_corpus_text(o) for o in opportunities)
        _tfidf_fitted_mtime = mtime
    except Exception as e:
        logger.warning("TF-IDF corpus fit failed: %s", e)


def _maybe_register_ranker_corpus(opportunities: list[dict]) -> None:
    """Bind the ranker's per-record precompute to the freshly-cached corpus
    list. Idempotent per list object (register_corpus no-ops on the same
    list), so calling on every request only re-registers after a reload.
    Must run AFTER _maybe_fit_tfidf — the precomputed similarity matrix
    needs the fitted vectorizer."""
    try:
        from src.matcher.ranker import register_corpus
        register_corpus(opportunities)
    except Exception as e:
        logger.warning("Ranker corpus precompute failed: %s", e)


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
            _STR_POOL.clear()
        _maybe_fit_tfidf(_opp_cache, mtime)
        _maybe_register_ranker_corpus(_opp_cache)
        return _opp_cache

    # Deployed checkouts carry the corpus as per-school shards (the committed
    # form under GitHub's 100 MB blob limit; see scripts/shard_corpus.py) with
    # no assembled work file — concatenate the shard directory directly.
    shards_dir = DATA_DIR / "shards"
    if shards_dir.is_dir():
        shards = sorted(shards_dir.glob("*.json"))
        if shards:
            mtime = max(p.stat().st_mtime for p in shards)
            if mtime != _opp_cache_mtime or not _opp_cache:
                raw = []
                for p in shards:
                    with open(p, encoding="utf-8") as f:
                        raw.extend(json.load(f))
                _opp_cache = [_sanitize_opportunity(o) for o in raw]
                _opp_cache_by_id = {o["id"]: o for o in _opp_cache if o.get("id")}
                _opp_cache_mtime = mtime
                _STR_POOL.clear()
            _maybe_fit_tfidf(_opp_cache, mtime)
            _maybe_register_ranker_corpus(_opp_cache)
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
