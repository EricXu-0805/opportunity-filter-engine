"""Unit tests for the shared anti-fabrication grounding check (R72-A).

The logic moved out of ``backend/routes/tailor.py`` into
``backend/lib/grounding.py`` so both the resume tailor and cold-email
generator enforce the same guarantee. These tests pin the shared contract
directly (the route-level tests cover integration).
"""

from __future__ import annotations

from backend.lib.grounding import (
    _TECH_TERMS,
    LENIENT_PROSE,
    hard_claims,
    validate_no_fabrication,
)


def _lenient(text, evidence_corpus, **kw):
    return validate_no_fabrication(text, evidence_corpus, policy=LENIENT_PROSE, **kw)


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


# --- LENIENT_PROSE policy (cold-email): hybrid concreteness-signal detection ---


def test_lenient_passes_warm_prose_without_filler_reliance():
    """The mechanism, not the allowlist, must carry warm prose: ordinary
    register words are not claim candidates at all under LENIENT_PROSE."""
    draft = (
        "I am genuinely delighted and absolutely thrilled to reach out. I bring "
        "a heartfelt, solid, hands-on enthusiasm for your groundbreaking, "
        "inspiring research and would be grateful for the chance to contribute."
    )
    passed, fab = _lenient(draft, "research")
    assert passed, f"warm prose wrongly flagged: {fab}"


def test_lenient_catches_lowercase_tech_via_taxonomy():
    """The headline fix's headline risk: a lowercase real-tech claim
    ('expert in pytorch') must still be caught even with no capital signal."""
    passed, fab = _lenient(
        "I am an expert in pytorch and have used numpy and pandas extensively.",
        evidence_corpus="python machine learning",
    )
    assert not passed
    assert {"pytorch", "numpy", "pandas"} <= set(fab)


def test_lenient_catches_camelcase_and_digit_shapes():
    passed, fab = _lenient(
        "I built models with TensorFlow and fine-tuned GPT-4 on our cluster.",
        evidence_corpus="python research",
    )
    assert not passed
    assert "tensorflow" in fab
    assert "gpt-4" in fab


def test_lenient_catches_short_acronyms_missed_by_regex():
    """ROS/CUDA/AWS/C++/K8s are <5 chars and invisible to the strict regex;
    the taxonomy + word-boundary matching catch them under LENIENT_PROSE."""
    passed, fab = _lenient(
        "Experienced with ROS, CUDA, AWS, C++, and K8s deployments.",
        evidence_corpus="python robotics",
    )
    assert not passed
    assert {"ros", "cuda", "aws", "c++", "k8s"} <= set(fab)


def test_lenient_short_token_not_swallowed_by_substring_collision():
    """The make-or-break guard: fabricated 'ros' must NOT be absorbed by the
    corpus word 'across' (word-boundary matching for short tokens)."""
    passed, fab = _lenient(
        "I have used ROS on several robots.",
        evidence_corpus="i worked across many teams on robotics",
    )
    assert not passed
    assert "ros" in fab


def test_lenient_long_token_substring_still_matches():
    """Don't over-tighten: 'python' is grounded by a corpus 'python3'."""
    passed, fab = _lenient(
        "I used Python for the project.", evidence_corpus="built with python3"
    )
    assert passed, f"unexpected flags: {fab}"


def test_lenient_sentence_initial_capital_is_not_a_claim():
    passed, fab = _lenient(
        "Delighted to apply. Genuinely excited about this lab.",
        evidence_corpus="research",
    )
    assert passed, f"sentence-initial words wrongly flagged: {fab}"


def test_lenient_allcaps_shouting_not_flagged_but_listed_acronym_is():
    passed, fab = _lenient(
        "I AM VERY EXCITED TO JOIN YOUR AWS RESEARCH GROUP.",
        evidence_corpus="research group",
    )
    assert not passed
    assert "aws" in fab
    assert "excited" not in fab and "research" not in fab


def test_lenient_multilingual_lowercase_tech_flagged():
    """Module contract: ASCII tech proper nouns must be caught amid non-Latin
    prose; the taxonomy is the primary defense when case signal is absent."""
    passed, fab = _lenient(
        "我熟悉 pytorch 和 kubernetes，希望加入您的实验室。",
        evidence_corpus="python 机器学习 research",
    )
    assert not passed
    assert {"pytorch", "kubernetes"} <= set(fab)


def test_lenient_grounded_tech_passes():
    passed, fab = _lenient(
        "I have hands-on Python and PyTorch experience from my coursework.",
        evidence_corpus="python pytorch machine learning cs 124",
    )
    assert passed, f"grounded tech wrongly flagged: {fab}"


def test_policy_divergence_same_draft_strict_rejects_lenient_passes():
    """The per-touchpoint split must not silently collapse: a plain ordinary
    word is fabrication under STRICT but fine under LENIENT_PROSE."""
    # 'kayaking' is non-filler ordinary English with no concreteness signal:
    # STRICT flags it (unknown 5+ token), LENIENT_PROSE does not (not a claim).
    draft = "On weekends I enjoy kayaking."
    strict_passed, strict_fab = validate_no_fabrication(draft, evidence_corpus="research")
    lenient_passed, _ = _lenient(draft, "research")
    assert not strict_passed and "kayaking" in strict_fab
    assert lenient_passed


def test_tech_terms_cover_security_critical():
    """Pin the high-value taxonomy members so a future trim cannot quietly
    reopen a fabrication hole."""
    critical = {
        "pytorch", "tensorflow", "kubernetes", "aws", "cuda", "ros",
        "scikit-learn", "numpy", "pandas", "cpp",
    }
    assert critical <= _TECH_TERMS
