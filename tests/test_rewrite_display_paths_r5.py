"""Round-3 re-verification (3c) for acceptance criteria (1) to (3) of fix/tailor-review.

Provider-free: the generation and review calls are stubbed at
``chat_completion``. Each test probes a regression the re-verification of db09a88 reported,
or one found while fixing it, and fails on db09a88; a test that pins a boundary db09a88
already holds says so.

Round 4 moved extraction back to origin/main's and removed this file's extraction
probes; their résumés are cases of tests/fixtures/extraction_differential_cases.json,
which scripts/extraction_differential.py runs against main.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r5.py -q
"""
from __future__ import annotations

import pytest

from backend.lib import evidence_map as em
from tests.test_rewrite_display_paths import (
    ACCEPT_ALL,
    ALL_PATHS,
    _rewrite,
    opportunity,  # noqa: F401  (pytest fixture)
    post_full_target,
    post_tailor,
    run,
)

# ------------------------------------------------------------------ criterion (2): an English relabel of an accented word
# 4bbdcb6 kept every relabel that leaves an accented word out of "to", so the relabel of an English
# line's loanword or name ("café inventory" -> "coffee shop inventory", "Müller group" -> "Mueller
# group") was kept before the review; a3f0424 reviewed and showed it, and main shows it. (A bare
# "Müller" -> "Mueller" shares no word, so its link is "broader" and every version keeps it.) Each line
# holds two English function words of three letters, which the default keep asks for (round 4).
ENGLISH_RELABELS = {
    "loanword": ("Tracked café inventory in Excel for 12 weeks with the dining staff.",
                 "Tracked coffee shop inventory in Excel for 12 weeks with the dining staff.",
                 "café inventory", "coffee shop inventory", "We track coffee shop inventory for campus dining."),
    "name": ("Co-wrote a sleep study protocol with the Müller group.",
             "Co-wrote a sleep study protocol with the Mueller group.", "Müller group", "Mueller group",
             "Join the Mueller group to study sleep."),
}


def _relabel_row(rewrite, source, term):
    return _rewrite(rewrite, [{"op": "relabel", "link": "L1", "from": source, "to": term}],
                    [{"id": "L1", "anchor": "t1", "term": term, "source": source, "relation": "same"}])


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(ENGLISH_RELABELS))
def test_an_english_relabel_of_an_accented_word_goes_to_the_review(opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite, source, term, anchor = ENGLISH_RELABELS[name]
    shown, seen = run(opportunity, monkeypatch, path, original, _relabel_row(rewrite, source, term), anchor)
    assert rewrite in seen and rewrite in shown and set(shown) <= seen, (shown, seen)


# 0bacf74d read a French line whose words outside the phrase include "on" and "a" as English, so its
# phrase relabeled into English reached the review on every route.
FOREIGN_RELABELS = {
    "french with on and a": ("On a construit un pipeline de données pour 40 capteurs.",
                             "On a construit un data pipeline pour 40 capteurs.", "pipeline de données",
                             "data pipeline", "Build a data pipeline in Python."),
}


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(FOREIGN_RELABELS))
def test_a_foreign_phrase_relabeled_into_english_is_kept_beside_two_letter_english_words(
        opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite, source, term, anchor = FOREIGN_RELABELS[name]
    shown, seen = run(opportunity, monkeypatch, path, original, _relabel_row(rewrite, source, term), anchor)
    assert rewrite not in seen and rewrite not in shown, (shown, seen)


# A setting's accented word written otherwise: the setting lock reads "at the Gomez lab" letter for letter
# as a setting the line never named. On db09a88 the accent-only relabel passed the contract and every
# route refused it with a fabrication warning (setting_added); main shows it. Now the contract keeps it
# as written, with no warning, and so it keeps "Müller lab" -> "Mueller lab", which the English
# exemption above would otherwise send to the same lock (this one db09a88 already keeps).
SETTING_RELABELS = {
    "accent only": ("Surveyed 200 students at the Gómez lab in Chicago.",
                    "Surveyed 200 students at the Gomez lab in Chicago.", "Gómez lab", "Gomez lab",
                    "Join the Gomez lab to study sleep."),
    "renamed": ("Ran 40 EEG sessions for the Müller lab in Python.", "Ran 40 EEG sessions for the Mueller lab in Python.",
                "Müller lab", "Mueller lab", "Join the Mueller lab to study sleep with EEG."),
}


def _reason(opportunity_id, monkeypatch, path, original, row, anchor):
    """The kept line's reason code, and the warnings the route returned with it."""
    if path == "full-target":
        receipt, _ = post_full_target(monkeypatch, original, row, ACCEPT_ALL, description=anchor)
        return receipt["reason_code"], receipt.get("warnings") or []
    body, _ = post_tailor(opportunity_id, monkeypatch, path, [(original, row)], ACCEPT_ALL, anchors=[anchor])
    if path.endswith("/renovate"):
        return body["sections"][0]["bullets"][0]["note"], body["warnings"]
    if path.endswith("/bullet"):
        return body["reason_code"], body["warnings"]
    return body["tailored_bullets"][0]["reason_code"], body["warnings"]


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(SETTING_RELABELS))
def test_a_settings_accented_word_written_otherwise_is_kept_not_refused(opportunity, monkeypatch, path,  # noqa: F811
                                                                         name):
    original, rewrite, source, term, anchor = SETTING_RELABELS[name]
    assert _reason(opportunity, monkeypatch, path, original, _relabel_row(rewrite, source, term), anchor) == (
        "beyond_allowed_edit", [])


@pytest.mark.parametrize(("source", "target", "line", "kept"), [
    ("café inventory", "coffee shop inventory", "Tracked café inventory in Excel for 12 weeks.", True),
    ("café inventory", "coffee shop inventory", "", False),  # with no line, every accented word stays
    # Too little English around the phrase to tell; kept as on db09a88.
    ("café inventory", "coffee shop inventory", "Tracked café inventory weekly.", False),
    # Another language around the phrase: an accented word outside it, no English function word,
    # or only one that English shares with it.
    ("pipeline de données", "data pipeline", "Développé un pipeline de données en Python pour 40 capteurs.", False),
    ("pipeline de données", "data pipeline", "Construit un pipeline de données pour 40 capteurs.", False),
    ("Datenbank für Messwerte", "measurement database", "Aufbau einer Datenbank für Messwerte in Python.", False),
    # Only two-letter words English shares with French ("on", "a") or German ("an", "in"); 0bacf74d read
    # both lines as English. An English line with only such words around the phrase is kept too.
    ("pipeline de données", "data pipeline", "On a construit un pipeline de données pour 40 capteurs.", False),
    ("Datenbank für Messwerte", "measurement database", "Aufbau einer Datenbank für Messwerte an der TU in Berlin.",
     False),
    ("café inventory", "coffee shop inventory", "Ran café inventory as a volunteer.", False),
    # "to" writes an accented word "from" lacks, in any line.
    ("coffee shop inventory", "café inventory", "Tracked coffee shop inventory in Excel for 12 weeks.", False),
])
def test_an_accented_word_is_renamed_only_in_an_english_line(source, target, line, kept):
    assert em._accents_kept(source, target, line) is kept


@pytest.mark.parametrize(("line", "source", "target", "changed"), [
    ("Surveyed 200 students at the Gómez lab in Chicago.", "Gómez lab", "Gomez lab", True),
    ("Ran 40 EEG sessions for the Müller lab in Python.", "Müller lab", "Mueller lab", True),
    ("Co-wrote a sleep study protocol with the Müller group.", "Müller group", "Mueller group", False),
    ("Tracked café inventory in Excel for 12 weeks.", "café inventory", "coffee shop inventory", False),
])
def test_a_relabel_keeps_a_settings_accented_words_as_written(line, source, target, changed):
    assert em._setting_accent_changed(line, source, target) is changed
