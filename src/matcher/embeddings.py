"""
Semantic similarity via OpenAI embeddings with TF-IDF fallback.

OpenAI path: text-embedding-3-small (1536 dims, $0.02/1M tokens)
Fallback: scikit-learn TfidfVectorizer fit on the opportunity corpus,
          so student ↔ opportunity similarity uses real IDF weights.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "processed"
EMBEDDING_CACHE_FILE = CACHE_DIR / "embedding_cache.json"

EMBEDDING_MODEL_VERSION = "v1-openai-3small"

MAX_CACHE_SIZE = 5000
_cache: dict[str, list[float]] = {}
_cache_loaded = False
_cache_dirty = False


def _load_cache() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    if EMBEDDING_CACHE_FILE.exists():
        try:
            with open(EMBEDDING_CACHE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and "__version__" in raw:
                if raw.get("__version__") == EMBEDDING_MODEL_VERSION:
                    _cache = {k: v for k, v in raw.items() if not k.startswith("__")}
                else:
                    stale_count = len([k for k in raw if not k.startswith("__")])
                    logger.info(
                        "Embedding cache version changed %s → %s; discarding %d stale entries",
                        raw.get("__version__"), EMBEDDING_MODEL_VERSION, stale_count,
                    )
                    _cache = {}
            elif isinstance(raw, dict):
                _cache = raw
            else:
                logger.warning("Embedding cache had unexpected type %s; ignoring", type(raw))
                _cache = {}
            logger.info("Loaded %d cached embeddings", len(_cache))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to load embedding cache: %s — starting empty", e)
            _cache = {}
    _cache_loaded = True


def _save_cache() -> None:
    """Persist cache atomically. Call sparingly — batched at end of embed_batch."""
    global _cache_dirty
    try:
        payload = {"__version__": EMBEDDING_MODEL_VERSION, **_cache}
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


def _get_openai_embeddings(texts: list[str], api_key: str) -> Optional[list[list[float]]]:
    try:
        import openai
    except ImportError:
        logger.warning("openai package not installed; embeddings disabled")
        return None

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key and not api_key:
        client = openai.OpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
        )
        model = "openai/text-embedding-3-small"
    else:
        client = openai.OpenAI(api_key=api_key)
        model = "text-embedding-3-small"

    try:
        resp = client.embeddings.create(model=model, input=texts)
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
        oldest_key = next(iter(_cache))
        del _cache[oldest_key]


def embed_text(text: str, api_key: str = None) -> Optional[list[float]]:
    """Get embedding for a single text, using cache when available."""
    global _cache_dirty
    _load_cache()
    key = _text_hash(text)
    if key in _cache:
        return _cache[key]

    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    result = _get_openai_embeddings([text], api_key)
    if result:
        _evict_if_needed()
        _cache[key] = result[0]
        _cache_dirty = True
        _save_cache()
        return result[0]
    return None


def embed_batch(texts: list[str], api_key: str = None) -> list[Optional[list[float]]]:
    """Embed multiple texts in one API call, respecting cache."""
    global _cache_dirty
    _load_cache()
    api_key = api_key or os.environ.get("OPENAI_API_KEY")

    results: list[Optional[list[float]]] = [None] * len(texts)
    uncached_indices = []
    uncached_texts = []

    for i, text in enumerate(texts):
        key = _text_hash(text)
        if key in _cache:
            results[i] = _cache[key]
        else:
            uncached_indices.append(i)
            uncached_texts.append(text)

    if uncached_texts and api_key:
        BATCH_SIZE = 100
        for batch_start in range(0, len(uncached_texts), BATCH_SIZE):
            batch = uncached_texts[batch_start:batch_start + BATCH_SIZE]
            batch_indices = uncached_indices[batch_start:batch_start + BATCH_SIZE]
            embeddings = _get_openai_embeddings(batch, api_key)
            if embeddings:
                for idx, emb in zip(batch_indices, embeddings):
                    _evict_if_needed()
                    results[idx] = emb
                    _cache[_text_hash(texts[idx])] = emb
                    _cache_dirty = True
        if _cache_dirty:
            _save_cache()

    return results


def semantic_similarity(text_a: str, text_b: str, api_key: str = None) -> float:
    """Compute semantic similarity between two texts (0.0 - 1.0)."""
    emb_a = embed_text(text_a, api_key)
    emb_b = embed_text(text_b, api_key)

    if emb_a and emb_b:
        sim = _cosine_similarity(emb_a, emb_b)
        return max(0.0, sim)

    return _tfidf_similarity(text_a, text_b)


def semantic_similarity_batch(
    query_text: str,
    candidate_texts: list[str],
    api_key: str = None,
) -> list[float]:
    """Compute similarity of one query against many candidates.

    Uses OpenAI embeddings (batched) when an API key is available;
    otherwise falls back to the TF-IDF vectorizer (fit on the corpus
    via fit_tfidf_corpus). Returns a list of scores in [0, 1] aligned
    with candidate_texts.
    """
    if not query_text or not candidate_texts:
        return [0.0] * len(candidate_texts)

    api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if api_key:
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


def fit_tfidf_corpus(corpus_texts: list[str]) -> None:
    """Fit the TF-IDF vectorizer on the opportunity corpus.

    Call this once at startup (or when data reloads) so similarity
    queries use real IDF weights learned from the full corpus.
    Calling _tfidf_similarity without a fitted corpus falls back to
    a 2-doc fit which degrades to token overlap.
    """
    global _tfidf_vectorizer, _tfidf_fitted
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        return
    valid = [t for t in corpus_texts if t and t.strip()]
    if len(valid) < 2:
        return
    _tfidf_vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=5000,
        ngram_range=(1, 2),
        sublinear_tf=True,
    )
    _tfidf_vectorizer.fit(valid)
    _tfidf_fitted = True
    logger.info("Fitted TF-IDF vectorizer on %d corpus docs", len(valid))


def _tfidf_similarity(text_a: str, text_b: str) -> float:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine
    except ImportError:
        return 0.0

    if not text_a.strip() or not text_b.strip():
        return 0.0

    global _tfidf_vectorizer, _tfidf_fitted
    if _tfidf_fitted and _tfidf_vectorizer is not None:
        matrix = _tfidf_vectorizer.transform([text_a, text_b])
        sim = sklearn_cosine(matrix[0:1], matrix[1:2])[0][0]
        return float(max(0.0, sim))

    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=5000,
        ngram_range=(1, 2),
        sublinear_tf=True,
    )
    try:
        matrix = vectorizer.fit_transform([text_a, text_b])
    except ValueError:
        return 0.0
    sim = sklearn_cosine(matrix[0:1], matrix[1:2])[0][0]
    return float(max(0.0, sim))


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
