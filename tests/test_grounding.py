"""Unit tests for the shared anti-fabrication grounding check (R72-A).

The logic moved out of ``backend/routes/tailor.py`` into
``backend/lib/grounding.py`` so both the resume tailor and cold-email
generator enforce the same guarantee. These tests pin the shared contract
directly (the route-level tests cover integration).
"""

from __future__ import annotations

from backend.lib.grounding import hard_claims, validate_no_fabrication


def test_hard_claims_extracts_5plus_char_tokens():
    claims = hard_claims("Built Python pipelines for ML in CS")
    assert "python" in claims
    assert "pipelines" in claims
    assert "ml" not in claims  # too short
    assert "cs" not in claims


def test_flags_unlisted_skill():
    passed, fab = validate_no_fabrication(
        "Built pipelines with Python and PyTorch.",
        evidence_corpus="java sensors thermodynamics mechanical engineering",
    )
    assert not passed
    assert "python" in fab
    assert "pytorch" in fab


def test_accepts_when_evidence_present():
    passed, fab = validate_no_fabrication(
        "Built Python projects using PyTorch frameworks.",
        evidence_corpus="python pytorch projects machine learning",
    )
    assert passed
    assert fab == []


def test_extra_allow_permits_caller_scaffolding():
    """A token absent from the corpus + filler still passes when the caller
    allow-lists it (cold-email salutation/closing vocabulary)."""
    corpus = "python machine learning research"
    # 'sincerely' isn't in the corpus or the generic filler set.
    passed_without, fab = validate_no_fabrication(
        "Sincerely", evidence_corpus=corpus,
    )
    assert not passed_without
    assert "sincerely" in fab

    passed_with, _ = validate_no_fabrication(
        "Sincerely",
        evidence_corpus=corpus,
        extra_allow=frozenset({"sincerely"}),
    )
    assert passed_with


def test_warm_email_prose_is_not_flagged_as_fabrication():
    """R72-A-6: warm cover-letter register (tone adjectives, intensifiers,
    abstract nouns) must not be mistaken for fabricated skills. These words
    tripped the validator on 'make it warmer' edits before the filler grew."""
    draft = (
        "I am genuinely delighted and absolutely thrilled about this. I bring "
        "solid, hands-on experience and a heartfelt enthusiasm for your "
        "groundbreaking, inspiring research. I would be grateful for the chance "
        "to contribute my dedication and collaborative spirit."
    )
    passed, fab = validate_no_fabrication(draft, evidence_corpus="research")
    assert passed, f"warm prose wrongly flagged: {fab}"


def test_filler_expansion_still_catches_technical_fabrication():
    """Guard against over-relaxing: a real technology claim absent from the
    corpus is still rejected even amid heavy warm prose."""
    draft = (
        "I am truly delighted and genuinely passionate about contributing. I am "
        "also an expert in PyTorch, Kubernetes, and TensorFlow."
    )
    passed, fab = validate_no_fabrication(draft, evidence_corpus="python research")
    assert not passed
    assert "pytorch" in fab
    assert "kubernetes" in fab
    assert "tensorflow" in fab
