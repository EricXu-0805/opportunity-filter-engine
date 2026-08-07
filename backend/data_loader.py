from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

_opp_cache: list[dict] = []
_opp_cache_by_id: dict[str, dict] = {}
_opp_cache_mtime: float = 0
_opp_cache_generation: int = 0
_tfidf_fitted_mtime: float = -1
_loader_lock = threading.RLock()

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
    # Pipeline-only payloads no serving path reads: drop them from the in-memory
    # copy. The on-disk corpus keeps them — the collectors' own passes
    # (llm_tagger reads eligibility_text_raw, enrichment audits read notes)
    # open the file directly, never through this loader.
    # NB: research_areas_raw is NOT dropped — it has real serving consumers
    # (matches.llm_rerank candidate text, cold_email professor brief +
    # anti-fabrication allowlist, and the ranker similarity corpus). An earlier
    # comment mislabeled it "zero consumers" and this pop silently blanked the
    # richest topical signal for every faculty record that carries it.
    elig = opp.get("eligibility")
    if isinstance(elig, dict):
        elig.pop("eligibility_text_raw", None)
    meta = opp.get("metadata")
    if isinstance(meta, dict):
        meta.pop("notes", None)
        # Harvest bookkeeping with zero serving consumers (last_verified IS
        # served on cards and stays).
        meta.pop("first_seen_at", None)
        meta.pop("last_seen_at", None)
    _dedupe_strings(opp)
    return opp


def _canonicalize_corpus(raw: list[dict]) -> list[dict]:
    """One canonical corpus shape at the earliest layer: sanitized, unique by
    id (first occurrence wins — so the ranked list and the by-id map are the
    SAME records; the map's old last-wins built from a non-deduped list let a
    duplicate id render twice in /matches while /opportunities/{id} showed
    one), and id-sorted so /opportunities offset paging is deterministic and
    survives shard-refresh reorderings instead of inheriting shard-file order."""
    seen: set[str] = set()
    out: list[dict] = []
    dropped = 0
    for o in raw:
        oid = o.get("id")
        if oid:
            if oid in seen:
                dropped += 1
                continue
            seen.add(oid)
        out.append(_sanitize_opportunity(o))
    if dropped:
        logger.warning("corpus: dropped %d duplicate-id records at load", dropped)
    out.sort(key=lambda o: o.get("id") or "")
    return out


def _opportunity_corpus_text(opp: dict) -> str:
    # Must include the same fields the ranker's _similarity_corpus scores, so
    # every term that can appear in a scored record is in the fitted TF-IDF
    # vocabulary (max_features caps it; OOV terms are dropped at transform).
    # research_areas_raw carries the professor's stated areas verbatim — the
    # only topical signal for faculty whose keywords stayed generic.
    parts = [
        opp.get("title", ""),
        opp.get("lab_or_program", ""),
        " ".join(opp.get("keywords", []) or []),
        (opp.get("metadata") or {}).get("research_areas_raw", ""),
        opp.get("description_clean") or opp.get("description_raw") or "",
    ]
    return " ".join(p for p in parts if p)


def _maybe_fit_tfidf(opportunities: list[dict], mtime: float) -> None:
    global _tfidf_fitted_mtime
    if mtime == _tfidf_fitted_mtime:
        return
    if not opportunities:
        raise ValueError("cannot fit an empty opportunity corpus")
    from src.matcher.embeddings import fit_tfidf_corpus

    # Generator, not a list: the joined corpus texts are ~90 MiB for 32k
    # records and the fit only needs one pass — materializing them spikes
    # startup RSS for nothing on a 2 GB instance.
    fitted = fit_tfidf_corpus(
        _opportunity_corpus_text(o) for o in opportunities
    )
    if not fitted:
        raise RuntimeError("TF-IDF corpus fit did not produce a usable model")
    _tfidf_fitted_mtime = mtime


def _prepare_ranker_corpus(opportunities: list[dict], mtime: float) -> None:
    """Atomically fit and register one ranker corpus generation.

    A scorer may still be reading the previous global vectorizer/matrix in its
    dedicated worker. The shared lock makes a hot data refresh wait for that
    traversal instead of replacing those globals halfway through one result
    set.
    """
    global _tfidf_fitted_mtime

    from src.matcher import embeddings, ranker

    with ranker.corpus_generation_lock:
        old_vectorizer = embeddings._tfidf_vectorizer
        old_fitted = embeddings._tfidf_fitted
        old_fitted_mtime = _tfidf_fitted_mtime
        old_ranker_state = (
            ranker._corpus_ref,
            ranker._corpus_rows,
            ranker._static_cache,
            ranker._sim_matrix,
            dict(ranker._kw_word_res),
        )
        try:
            _maybe_fit_tfidf(opportunities, mtime)
            ranker.register_corpus(opportunities)
            if (
                ranker._corpus_ref is not opportunities
                or ranker._sim_matrix is None
            ):
                raise RuntimeError(
                    "ranker did not publish a complete corpus matrix"
                )
        except Exception:
            embeddings._tfidf_vectorizer = old_vectorizer
            embeddings._tfidf_fitted = old_fitted
            _tfidf_fitted_mtime = old_fitted_mtime
            (
                ranker._corpus_ref,
                ranker._corpus_rows,
                ranker._static_cache,
                ranker._sim_matrix,
                old_keyword_res,
            ) = old_ranker_state
            ranker._kw_word_res.clear()
            ranker._kw_word_res.update(old_keyword_res)
            raise


def _try_publish_corpus(raw: list[dict], mtime: float, source: str) -> bool:
    """Prepare a candidate fully, then atomically publish loader globals."""
    global _opp_cache, _opp_cache_by_id, _opp_cache_generation, _opp_cache_mtime

    try:
        candidate = _canonicalize_corpus(raw)
        if not candidate:
            raise ValueError("candidate corpus is empty")
        candidate_by_id = {
            opportunity["id"]: opportunity
            for opportunity in candidate
            if opportunity.get("id")
        }
        _prepare_ranker_corpus(candidate, mtime)
    except Exception as exc:
        _STR_POOL.clear()
        logger.error(
            "Corpus refresh from %s failed; keeping generation %d: %s",
            source,
            _opp_cache_generation,
            exc,
        )
        return False

    _opp_cache = candidate
    _opp_cache_by_id = candidate_by_id
    _opp_cache_mtime = mtime
    _opp_cache_generation += 1
    _STR_POOL.clear()
    return True


def load_opportunities() -> list[dict]:
    """Return one process-wide immutable corpus generation.

    Match routes call this from a worker thread. The lock turns concurrent cold
    starts/hot reloads into one load+canonicalize+fit/register operation; every
    waiter then observes the same list identity instead of briefly building
    multiple hundred-megabyte generations in parallel.
    """
    return load_opportunities_generation()[0]


def load_opportunities_generation() -> tuple[list[dict], str]:
    """Atomically return the corpus and its process-local generation token."""
    with _loader_lock:
        opportunities = _load_opportunities_unlocked()
        token = f"{_opp_cache_generation}:{_opp_cache_mtime:.6f}"
        return opportunities, token


def _load_opportunities_unlocked() -> list[dict]:
    global _opp_cache, _opp_cache_by_id, _opp_cache_generation, _opp_cache_mtime

    processed = DATA_DIR / "opportunities.json"
    if processed.exists():
        mtime = processed.stat().st_mtime
        if mtime != _opp_cache_mtime or not _opp_cache:
            try:
                with open(processed, encoding="utf-8") as f:
                    raw = json.load(f)
                _try_publish_corpus(raw, mtime, str(processed))
            except Exception as exc:
                logger.error(
                    "Corpus read from %s failed; keeping generation %d: %s",
                    processed,
                    _opp_cache_generation,
                    exc,
                )
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
                try:
                    raw = []
                    for p in shards:
                        with open(p, encoding="utf-8") as f:
                            raw.extend(json.load(f))
                    _try_publish_corpus(raw, mtime, str(shards_dir))
                except Exception as exc:
                    logger.error(
                        "Corpus read from %s failed; keeping generation %d: %s",
                        shards_dir,
                        _opp_cache_generation,
                        exc,
                    )
            return _opp_cache

    examples = EXAMPLES_DIR / "sample_opportunities.json"
    if examples.exists():
        # Same canonical path as the real corpus: previously this branch
        # skipped _opp_cache/_opp_cache_by_id entirely, so /matches returned
        # results whose detail lookups 404'd (`opportunity: {}` cards) — two
        # endpoints disagreeing about the same id on the fallback corpus.
        mtime = examples.stat().st_mtime
        if mtime != _opp_cache_mtime or not _opp_cache:
            try:
                with open(examples, encoding="utf-8") as f:
                    raw = json.load(f)
                _try_publish_corpus(raw, mtime, str(examples))
            except Exception as exc:
                logger.error(
                    "Corpus read from %s failed; keeping generation %d: %s",
                    examples,
                    _opp_cache_generation,
                    exc,
                )
        return _opp_cache

    return []


def load_opportunities_by_id() -> dict[str, dict]:
    load_opportunities()
    return _opp_cache_by_id


def corpus_version() -> str:
    """Opaque version of the currently-loaded corpus. Participates in every
    match cache/snapshot key so results computed against different corpus
    generations can never be served together. mtime-based, same invalidation
    signal load_opportunities itself uses."""
    return f"{_opp_cache_mtime:.6f}"
