"""
Semantic similarity via OpenAI embeddings with TF-IDF fallback.

OpenAI path: text-embedding-3-small (1536 dims, $0.02/1M tokens)
Fallback: scikit-learn TfidfVectorizer + cosine_similarity
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

_cache: dict[str, list[float]] = {}
_cache_loaded = False


def _load_cache() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    if EMBEDDING_CACHE_FILE.exists():
        try:
            with open(EMBEDDING_CACHE_FILE, "r") as f:
                _cache = json.load(f)
            logger.info(f"Loaded {len(_cache)} cached embeddings")
        except Exception:
            _cache = {}
    _cache_loaded = True


def _save_cache() -> None:
    try:
        with open(EMBEDDING_CACHE_FILE, "w") as f:
            json.dump(_cache, f)
    except Exception as e:
        logger.warning(f"Failed to save embedding cache: {e}")


def _text_hash(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()[:16]


def _get_openai_embeddings(texts: list[str], api_key: str) -> Optional[list[list[float]]]:
    try:
        import openai
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
        resp = client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in resp.data]
    except Exception as e:
        logger.warning(f"Embedding API failed: {e}")
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a)
    vb = np.array(b)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def embed_text(text: str, api_key: str = None) -> Optional[list[float]]:
    """Get embedding for a single text, using cache when available."""
    _load_cache()
    key = _text_hash(text)
    if key in _cache:
        return _cache[key]

    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    result = _get_openai_embeddings([text], api_key)
    if result:
        _cache[key] = result[0]
        _save_cache()
        return result[0]
    return None


def embed_batch(texts: list[str], api_key: str = None) -> list[Optional[list[float]]]:
    """Embed multiple texts in one API call, respecting cache."""
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
                    results[idx] = emb
                    _cache[_text_hash(texts[idx])] = emb
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


def _tfidf_similarity(text_a: str, text_b: str) -> float:
    """TF-IDF cosine similarity fallback using scikit-learn."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine

        if not text_a.strip() or not text_b.strip():
            return 0.0

        vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=5000,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        tfidf_matrix = vectorizer.fit_transform([text_a, text_b])
        sim = sklearn_cosine(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        return float(max(0.0, sim))
    except ImportError:
        from .ranker import _text_similarity
        return _text_similarity(text_a, text_b)


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
