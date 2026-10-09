"""Round-3 re-verification (3b) for acceptance criterion (3) of fix/tailor-review.

Provider-free: the generation and review calls are stubbed at
``chat_completion``. Each test was written as a probe of a gap or a regression the
re-verification of a3f0424 reported, failed there, and now pins the fix.

Round 4 moved extraction back to origin/main's and removed this file's extraction
probes; their résumés are cases of tests/fixtures/extraction_differential_cases.json,
which tests/test_extraction_matches_main.py runs against main.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r4.py -q
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from tests.test_rewrite_display_paths import (
    ALL_PATHS,
    _rewrite,
    opportunity,  # noqa: F401  (pytest fixture)
    run,
)

# ------------------------------------------------------------------ criterion (3): an accented phrase relabeled
# 3a6f715 stopped counting accented Latin letters as a script of their own, so the relabel same-script
# check no longer saw "pipeline de données" -> "data pipeline": a French line's phrase written in
# English reached the review and was shown.
LATIN_RELABELS = {
    "french": ("Développé un pipeline de données en Python pour 40 capteurs.",
               "Développé un data pipeline en Python pour 40 capteurs.", "pipeline de données", "data pipeline",
               "Build a data pipeline in Python."),
}


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(LATIN_RELABELS))
def test_an_accented_phrase_relabeled_into_english_is_kept(opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite, source, term, anchor = LATIN_RELABELS[name]
    row = _rewrite(rewrite, [{"op": "relabel", "link": "L1", "from": source, "to": term}],
                   [{"id": "L1", "anchor": "t1", "term": term, "source": source, "relation": "same"}])
    shown, seen = run(opportunity, monkeypatch, path, original, row, anchor)
    assert rewrite not in seen and rewrite not in shown, (shown, seen)


@pytest.mark.parametrize(("source", "target", "kept"), [
    ("pipeline de données", "data pipeline", True),        # French written in English
    ("data pipeline", "pipeline de données", True),        # English written in French
    ("résumé parser", "resume parser", False),             # the same word without its accents
    ("Café Lab survey", "Café Lab questionnaire", False),  # the accented word stays
])
def test_a_relabel_keeps_each_accented_word_accents_aside(source, target, kept):
    from backend.lib import evidence_map as em
    assert em._accents_kept(source, target) is not kept


# ------------------------------------------------------------------ the full-target routes' parse errors
# d378ee4 parsed the full-target body on the request lane and caught every ValueError as invalid
# JSON, so a body that is not UTF-8 got 422 where FastAPI answers 400.
@pytest.mark.parametrize("path", ["/api/tailor/full-target/suggestions", "/api/tailor/full-target/selection-plan"])
def test_a_body_that_is_not_utf8_gets_fastapis_400(monkeypatch, path):
    monkeypatch.setenv("OFE_DISABLE_RATE_LIMIT", "1")
    response = TestClient(app).post(path, content=b'{"version":"\xff"}', headers={"content-type": "application/json"})
    assert (response.status_code, response.json()) == (400, {"detail": "There was an error parsing the body"})
    assert response.headers["cache-control"].startswith("private, no-store")
