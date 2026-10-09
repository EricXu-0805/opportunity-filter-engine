"""Criterion (E) of fix/tailor-review: /api/tailor/extract-bullets, /api/tailor/structure, their
no-model fallback and the browser's reading of a résumé return what origin/main returns.

Runs scripts/extraction_differential.py on tests/fixtures/extraction_differential_cases.json: origin/main's
backend/routes/tailor.py, loaded from ``git show``, and this tree's, on the same résumés with the same
stubbed model replies. A checkout without origin/main (a shallow pull-request checkout) skips; run
``git fetch origin main`` first.

Run from the repository root:
    python -m pytest tests/test_extraction_matches_main.py -q
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REF = "origin/main"


def _harness():
    spec = importlib.util.spec_from_file_location("extraction_differential", ROOT / "scripts" / "extraction_differential.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extraction_returns_what_main_returns():
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{REF}^{{commit}}"], cwd=ROOT,
                      capture_output=True).returncode:
        pytest.skip(f"{REF} is not in this checkout")
    result = _harness().run(REF)
    assert result["counts"]["differences"] == 0, "\n".join(result["differences"][:20])
    assert result["dependencies"] == []
    assert result["frontend"] == []
    # Every case ran: a fixture that stopped loading would compare nothing and pass.
    assert result["counts"]["cases"] >= 1_300 and result["counts"]["comparisons returning lines"] >= 30_000
