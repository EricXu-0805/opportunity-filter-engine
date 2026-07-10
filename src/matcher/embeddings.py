"""
Semantic similarity via embeddings with TF-IDF fallback.

Provider chain (mirrors backend/lib/llm.py so one key lights up both):
  1. OPENAI_API_KEY     → text-embedding-3-small (1536 dims)
  2. GEMINI_API_KEY     → gemini-embedding-001 via Google's OpenAI-compatible
                          endpoint, reduced to EMBED_DIMENSIONS dims
  3. OPENROUTER_API_KEY → openai/text-embedding-3-small
Fallback (no key): scikit-learn TfidfVectorizer fit on the opportunity corpus,
          so student ↔ opportunity similarity uses real IDF weights.
"""

import hashlib
import json
import logging
import os
from collections import OrderedDict
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "processed"
EMBEDDING_CACHE_FILE = CACHE_DIR / "embedding_cache.json"

# Embedding dimensionality requested from providers that support it (Gemini's
# native 3072 is reduced via Matryoshka to keep the cache and cosine lean;
# OpenAI's text-embedding-3-small is natively 1536). Cosine normalizes, so the
# unnormalized reduced-dim vectors Gemini returns are fine.
EMBED_DIMENSIONS = 1536

GEMINI_EMBED_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_EMBED_MODEL = "gemini-embedding-001"

MAX_CACHE_SIZE = 5000
_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_cache_loaded = False
_cache_dirty = False


def _load_cache() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    if EMBEDDING_CACHE_FILE.exists():
        try:
            with open(EMBEDDING_CACHE_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and "__version__" in raw:
                if raw.get("__version__") == _cache_version():
                    _cache = OrderedDict(
                        (k, v) for k, v in raw.items() if not k.startswith("__")
                    )
                else:
                    stale_count = len([k for k in raw if not k.startswith("__")])
                    logger.info(
                        "Embedding cache version changed %s → %s; discarding %d stale entries",
                        raw.get("__version__"), _cache_version(), stale_count,
                    )
                    _cache = OrderedDict()
            elif isinstance(raw, dict):
                _cache = OrderedDict(raw)
            else:
                logger.warning("Embedding cache had unexpected type %s; ignoring", type(raw))
                _cache = OrderedDict()
            logger.info("Loaded %d cached embeddings", len(_cache))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to load embedding cache: %s — starting empty", e)
            _cache = OrderedDict()
    _cache_loaded = True


def _save_cache() -> None:
    """Persist cache atomically. Call sparingly — batched at end of embed_batch."""
    global _cache_dirty
    try:
        payload = {"__version__": _cache_version(), **_cache}
        tmp = EMBEDDING_CACHE_FILE.with_suffix(".json.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        tmp.replace(EMBEDDING_CACHE_FILE)
        _cache_dirty = False
    except OSError as e:
        logger.warning("Failed to save embedding cache: %s", e)


def _text_hash(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()[:16]


def _resolve_embedding_provider(explicit_key: str | None) -> tuple[str, str, str] | None:
    """Pick an embedding provider, in order (mirrors backend/lib/llm.py):
       1. explicit_key argument (treated as OpenAI direct)
       2. OPENAI_API_KEY env var
       3. GEMINI_API_KEY env var (OpenAI-compatible endpoint)
       4. OPENROUTER_API_KEY env var (gives broader model choice)
    Returns (api_key, base_url, model) or None if no key is configured.
    """
    if explicit_key:
        return explicit_key, "", "text-embedding-3-small"
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        return openai_key, "", "text-embedding-3-small"
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        return gemini_key, GEMINI_EMBED_BASE_URL, GEMINI_EMBED_MODEL
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        return openrouter_key, "https://openrouter.ai/api/v1", "openai/text-embedding-3-small"
    return None


def _has_embedding_provider(explicit_key: str | None = None) -> bool:
    """True iff an embedding provider is configured. Single source of truth for
    the embedding-vs-TF-IDF decision across this module and the ranker."""
    return _resolve_embedding_provider(explicit_key) is not None


def _cache_version() -> str:
    """Cache tag derived from the active model so vectors from one provider are
    never cosine-compared against another's (different dims/geometry). Switching
    providers invalidates the on-disk cache."""
    provider = _resolve_embedding_provider(None)
    return f"v2-{provider[2]}-{EMBED_DIMENSIONS}" if provider else "v2-none"


def _get_openai_embeddings(texts: list[str], api_key: str | None) -> list[list[float]] | None:
    try:
        import openai
    except ImportError:
        logger.warning("openai package not installed; embeddings disabled")
        return None

    provider = _resolve_embedding_provider(api_key)
    if provider is None:
        return None
    key, base_url, model = provider
    client = openai.OpenAI(api_key=key, base_url=base_url) if base_url else openai.OpenAI(api_key=key)

    # text-embedding-3-small is natively 1536; only the Gemini model needs an
    # explicit Matryoshka reduction to match.
    create_kwargs: dict = {"model": model, "input": texts}
    if model == GEMINI_EMBED_MODEL:
        create_kwargs["dimensions"] = EMBED_DIMENSIONS

    try:
        resp = client.embeddings.create(**create_kwargs)
        return [item.embedding for item in resp.data]
    except (openai.APIError, openai.APIConnectionError, openai.RateLimitError,
            openai.AuthenticationError, openai.APITimeoutError) as e:
        logger.warning("Embedding API failed: %s", e)
        return None
    except Exception as e:
        logger.warning("Unexpected embedding error (%s): %s", type(e).__name__, e)
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a)
    vb = np.array(b)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _evict_if_needed() -> None:
    while len(_cache) >= MAX_CACHE_SIZE:
        _cache.popitem(last=False)


def embed_batch(texts: list[str], api_key: str = None) -> list[list[float] | None]:
    """Embed multiple texts in one API call, respecting cache."""
    global _cache_dirty
    _load_cache()
    has_provider = _has_embedding_provider(api_key)

    results: list[list[float] | None] = [None] * len(texts)
    uncached_indices = []
    uncached_texts = []

    for i, text in enumerate(texts):
        key = _text_hash(text)
        if key in _cache:
            _cache.move_to_end(key)
            results[i] = _cache[key]
        else:
            uncached_indices.append(i)
            uncached_texts.append(text)

    if uncached_texts and has_provider:
        BATCH_SIZE = 100
        for batch_start in range(0, len(uncached_texts), BATCH_SIZE):
            batch = uncached_texts[batch_start:batch_start + BATCH_SIZE]
            batch_indices = uncached_indices[batch_start:batch_start + BATCH_SIZE]
            embeddings = _get_openai_embeddings(batch, api_key)
            if embeddings:
                for idx, emb in zip(batch_indices, embeddings, strict=False):
                    _evict_if_needed()
                    results[idx] = emb
                    _cache[_text_hash(texts[idx])] = emb
                    _cache_dirty = True
        if _cache_dirty:
            _save_cache()

    return results


def semantic_similarity_batch(
    query_text: str,
    candidate_texts: list[str],
    api_key: str = None,
    allow_embeddings: bool = True,
) -> list[float]:
    """Compute similarity of one query against many candidates.

    Uses embeddings (batched) when a provider is configured and
    ``allow_embeddings`` is True; otherwise falls back to the TF-IDF
    vectorizer (fit on the corpus via fit_tfidf_corpus). Returns scores
    in [0, 1] aligned with candidate_texts.

    ``allow_embeddings=False`` forces TF-IDF — used by rank_all so the
    whole-corpus upside pass never fans out into thousands of embedding
    calls per request (embeddings are reserved for the bounded
    semantic_rerank slice).
    """
    if not query_text or not candidate_texts:
        return [0.0] * len(candidate_texts)

    if allow_embeddings and _has_embedding_provider(api_key):
        embeddings = embed_batch([query_text, *candidate_texts], api_key)
        q_emb = embeddings[0]
        if q_emb is not None:
            return [
                max(0.0, _cosine_similarity(q_emb, c_emb)) if c_emb is not None else 0.0
                for c_emb in embeddings[1:]
            ]

    return _tfidf_similarity_batch(query_text, candidate_texts)


def _tfidf_similarity_batch(query_text: str, candidate_texts: list[str]) -> list[float]:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine
    except ImportError:
        return [0.0] * len(candidate_texts)

    if not query_text.strip():
        return [0.0] * len(candidate_texts)

    global _tfidf_vectorizer, _tfidf_fitted
    if _tfidf_fitted and _tfidf_vectorizer is not None:
        vectors = _tfidf_vectorizer.transform([query_text, *candidate_texts])
        sims = sklearn_cosine(vectors[0:1], vectors[1:])[0]
        return [float(max(0.0, s)) for s in sims]

    valid = [c if c and c.strip() else " " for c in candidate_texts]
    try:
        tv = TfidfVectorizer(
            stop_words="english",
            max_features=5000,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        vectors = tv.fit_transform([query_text, *valid])
        sims = sklearn_cosine(vectors[0:1], vectors[1:])[0]
        return [float(max(0.0, s)) for s in sims]
    except ValueError:
        return [0.0] * len(candidate_texts)


_tfidf_vectorizer = None
_tfidf_fitted = False


def fit_tfidf_corpus(corpus_texts) -> None:
    """Fit the TF-IDF vectorizer on the opportunity corpus.

    Call this once at startup (or when data reloads) so similarity
    queries use real IDF weights learned from the full corpus.
    _tfidf_similarity_batch without a fitted corpus falls back to a
    fresh per-call fit which degrades to token overlap.

    Accepts any iterable of texts (a generator, from data_loader) — the
    fit makes one pass and never retains the documents, so the caller
    doesn't have to materialize a ~90 MiB list to fit the corpus.
    """
    global _tfidf_vectorizer, _tfidf_fitted
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        return
    n_docs = 0

    def _valid_docs():
        nonlocal n_docs
        for t in corpus_texts:
            if t and t.strip():
                n_docs += 1
                yield t

    tv = TfidfVectorizer(
        stop_words="english",
        max_features=5000,
        ngram_range=(1, 2),
        sublinear_tf=True,
    )
    try:
        tv.fit(_valid_docs())
    except ValueError:  # empty / all-stopword corpus
        return
    if n_docs < 2:  # degenerate corpus, same guard as before
        return
    _tfidf_vectorizer = tv
    _tfidf_fitted = True
    logger.info("Fitted TF-IDF vectorizer on %d corpus docs", n_docs)


def precompute_opportunity_embeddings(opportunities: list[dict],
                                       api_key: str = None) -> int:
    """Pre-compute embeddings for all opportunity descriptions. Returns count of new embeddings."""
    texts = []
    for opp in opportunities:
        desc = (opp.get("description_raw") or opp.get("description_clean") or "")
        keywords = ", ".join(opp.get("keywords", []))
        lab = opp.get("lab_or_program", "")
        combined = f"{opp.get('title', '')}. {lab}. {keywords}. {desc[:300]}"
        texts.append(combined)

    _load_cache()
    already_cached = sum(1 for t in texts if _text_hash(t) in _cache)
    logger.info(f"Embedding {len(texts)} opportunities ({already_cached} already cached)")

    results = embed_batch(texts, api_key)
    new_count = sum(1 for r in results if r is not None) - already_cached
    return max(0, new_count)
