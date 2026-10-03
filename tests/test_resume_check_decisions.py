"""Recorded decisions of the résumé and email claim checks.

The original/rewrite pairs in ``resume_check_decisions.json`` are decided
exactly as recorded there, both as given and with their spacing changed
(doubled, no-break or ideographic spaces, tabs, indented lines, CRLF line ends).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.lib import email_experience_attribution as ea
from backend.lib import target_resume_ai_grounding as grounding
from backend.routes.tailor import _validate_bullet_rewrite

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "resume_check_decisions.json").read_text(encoding="utf-8"))
# Each row: original, rewrite, then the decisions _decisions returns.
ROWS = RECORDED["rows"]
SECOND_ENTRY = "Wrote unit tests for the parser."


def _decisions(original: str, rewrite: str) -> list:
    passed, findings = _validate_bullet_rewrite(rewrite, original)
    return [
        passed,
        sorted(findings),
        grounding.claim_upgrade_detected(rewrite, original),
        grounding.supported_claim_upgrade_detected(rewrite, [original, SECOND_ENTRY]),
        ea.experience_attribution_violations(rewrite, [original]),
        ea.unsupported_experience_claims(rewrite, [original], allow_subjectless_claims=True),
    ]


def _each_line(prefix: str):
    return lambda text: prefix + text.replace("\n", "\n" + prefix)


SPACINGS = {
    "as-given": lambda text: text,
    "doubled-spaces": lambda text: text.replace(" ", "  "),
    "tabs": lambda text: text.replace(" ", "\t"),
    "no-break-spaces": lambda text: text.replace(" ", "\u00a0"),
    "ideographic-spaces": lambda text: text.replace(" ", "\u3000"),
    "indented-lines": _each_line("\u00a0"),
    "indented-with-tabs": _each_line("\t"),
    "crlf": lambda text: text.replace("\n", "\r\n"),
    "expanded": lambda text: text.replace(" ", " \t  ").replace("\n", "\n\n"),
}


def test_record_holds_both_outcomes():
    assert len(ROWS) > 600
    assert RECORDED["columns"][:2] == ["original", "rewrite"] and all(len(row) == 8 for row in ROWS)
    # Both outcomes are present, so agreement below is not vacuous.
    assert {row[2] for row in ROWS} == {True, False}
    assert {row[4] for row in ROWS} == {True, False}


@pytest.mark.parametrize("spacing", SPACINGS)
def test_decisions_match_the_record(spacing):
    change = SPACINGS[spacing]
    differing = [index for index, (original, rewrite, *recorded) in enumerate(ROWS)
                 if _decisions(change(original), change(rewrite)) != recorded]
    assert differing == []


def test_collapse_whitespace_keeps_line_breaks():
    assert ea.collapse_whitespace("a   b\t\tc\u00a0\u3000d") == "a b c d"
    assert ea.collapse_whitespace("a  \r\n\n  b") == "a\nb"
    assert ea.collapse_whitespace("plain text") == "plain text"
