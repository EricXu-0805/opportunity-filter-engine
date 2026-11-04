"""The 5,000-term cutoff must not reshuffle equal-frequency research terms."""

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.matcher import config, embeddings


@pytest.fixture(autouse=True)
def isolated_model(monkeypatch):
    monkeypatch.setattr(embeddings, "_tfidf_fitted", False)
    monkeypatch.setattr(embeddings, "_tfidf_vectorizer", None)


def test_unrelated_edit_cannot_reshuffle_a_split_cutoff_tie():
    common = [f"subject{i:04}" for i in range(4988)]
    tied = [f"topic{i:03}" for i in range(48)]
    rare = [f"rare{i:03}" for i in range(13)]
    docs = common * 3 + tied * 2 + rare

    for source in (iter(docs), reversed(docs), iter([*docs[:-1], docs[-1] + " zzzrare"])):
        assert embeddings.fit_tfidf_corpus(source)
        model = embeddings._tfidf_vectorizer
        # 48 terms tie for the last 12 places, so none of them is kept.
        assert model.get_feature_names_out().tolist() == sorted(common)
        # An in-scope query keeps both the included match and the excluded zero.
        assert embeddings.semantic_similarity_batch(
            "subject0000 topic000", ["subject0000", "topic000"], allow_embeddings=False
        ) == [1.0, 0.0]

    # A real change in frequency still moves a term across the boundary.
    assert embeddings.fit_tfidf_corpus(iter([*docs, tied[-1]]))
    assert set(embeddings._tfidf_vectorizer.vocabulary_) == set(common + [tied[-1]])


# Two terms above the cutoff, then seven tied at count 2: unigrams and bigrams of
# different lengths, with document frequency 2 or 1.
MIXED_TIE_DOCS = [
    *["alpha"] * 3,
    *["bravo"] * 3,
    *["kilo lima"] * 2,
    "mike mike",
    "oscarpapa quebec oscarpapa quebec",
]
MIXED_TIE = ["kilo", "kilo lima", "lima", "mike", "oscarpapa", "oscarpapa quebec", "quebec"]


def test_a_tie_that_does_not_fit_is_left_out_whatever_its_lengths_or_document_frequencies(monkeypatch):
    monkeypatch.setattr(embeddings, "TFIDF_MAX_FEATURES", 5)
    assert embeddings.fit_tfidf_corpus(iter(MIXED_TIE_DOCS))
    assert embeddings._tfidf_vectorizer.get_feature_names_out().tolist() == ["alpha", "bravo"]


def test_a_tie_that_fits_is_kept_whole(monkeypatch):
    monkeypatch.setattr(embeddings, "TFIDF_MAX_FEATURES", 2 + len(MIXED_TIE))
    assert embeddings.fit_tfidf_corpus(iter(MIXED_TIE_DOCS))
    assert embeddings._tfidf_vectorizer.get_feature_names_out().tolist() == ["alpha", "bravo", *MIXED_TIE]


def test_without_a_tie_at_the_cutoff_the_cap_is_filled_exactly(monkeypatch):
    monkeypatch.setattr(embeddings, "TFIDF_MAX_FEATURES", 2)
    assert embeddings.fit_tfidf_corpus(iter(["alpha"] * 3 + ["bravo"] * 2 + ["charlie"]))
    assert embeddings._tfidf_vectorizer.get_feature_names_out().tolist() == ["alpha", "bravo"]


def test_sklearn_weights_and_transforms_are_preserved_for_the_selected_terms(monkeypatch):
    monkeypatch.setattr(embeddings, "TFIDF_MAX_FEATURES", 4)
    # "piano" is repeated in one document, while "chamber" occurs in two.
    # The term-frequency cutoff and document-frequency weights have different jobs.
    docs = ["piano piano piano piano", "chamber music", "music chamber", "the and"]
    selected = ["chamber", "music", "piano", "piano piano"]
    reference = TfidfVectorizer(vocabulary=selected, stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    reference.fit(docs)
    # Blank texts are not documents, so they do not dilute the IDF.
    assert embeddings.fit_tfidf_corpus(iter([*docs, "", " "]))
    actual = embeddings._tfidf_vectorizer
    assert actual.get_feature_names_out().tolist() == selected
    np.testing.assert_array_equal(actual.idf_, reference.idf_)
    sample = ["Piano piano and chamber music", "unknown", "the"]
    np.testing.assert_array_equal(actual.transform(sample).toarray(), reference.transform(sample).toarray())
    assert not embeddings.fit_tfidf_corpus(["", " ", "the and"])
    assert not embeddings.fit_tfidf_corpus(["one usable topic"])
    assert embeddings._tfidf_vectorizer is actual


def test_stop_words_never_enter_the_vocabulary():
    assert not embeddings.fit_tfidf_corpus(["the and of", "of the"])
    assert embeddings._tfidf_vectorizer is None
    assert embeddings.semantic_similarity_batch("the of", ["of the"], allow_embeddings=False) == [0.0]
    assert embeddings.fit_tfidf_corpus(["the theory of music", "music of the theory"])
    assert sorted(embeddings._tfidf_vectorizer.vocabulary_) == ["music", "music theory", "theory", "theory music"]


def test_uncached_similarity_uses_the_same_tie_rule_without_publishing_a_model():
    common = [f"subject{i:04}" for i in range(4988)]
    tied = [f"topic{i:03}" for i in range(48)]
    rare = [f"rare{i:03}" for i in range(13)]
    # Each tied term occurs once in the query and once as a candidate, so the per-call
    # fit sees 48 terms tied for the last 12 places and keeps only the query's subject term.
    query = " ".join(["subject0000", *tied])
    candidates = common * 3 + tied + rare
    uncached = embeddings.semantic_similarity_batch(query, candidates, allow_embeddings=False)
    assert embeddings._tfidf_vectorizer is None
    assert uncached == [1.0 if text == "subject0000" else 0.0 for text in candidates]
    assert embeddings.fit_tfidf_corpus(iter([query, *candidates]))
    assert embeddings.semantic_similarity_batch(query, candidates, allow_embeddings=False) == uncached


def test_uncached_similarity_scores_blank_and_missing_candidates_as_empty_documents():
    query = "neural coding of memory"
    candidates = ["neural coding", "", None, "   ", "memory of neural circuits"]
    scores = embeddings.semantic_similarity_batch(query, candidates, allow_embeddings=False)
    # They still count as documents for the IDF, as in sklearn's own fit of the same texts.
    reference = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    vectors = reference.fit_transform([query, "neural coding", " ", " ", " ", "memory of neural circuits"])
    expected = cosine_similarity(vectors[0:1], vectors[1:])[0].tolist()
    assert scores[1:4] == [0.0, 0.0, 0.0]
    assert scores == pytest.approx(expected, rel=1e-12)


def test_the_cutoff_size_is_hashed_into_the_matcher_version(monkeypatch):
    before = config._matcher_fingerprint()
    monkeypatch.setattr(config, "TFIDF_MAX_FEATURES", config.TFIDF_MAX_FEATURES + 1)
    assert config._matcher_fingerprint() != before


def test_the_matcher_version_moved_for_the_tie_rule():
    assert int(config.MATCHER_VERSION.split(".")[0]) >= 34
