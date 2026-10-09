"""Round-3 re-verification (3c) for acceptance criteria (1) to (3) of fix/tailor-review.

Provider-free: the extraction, structure, generation and review calls are stubbed at
``chat_completion``. Each test probes a regression the re-verification of db09a88 reported,
or one found while fixing it, and fails on db09a88; a test that pins a boundary db09a88
already holds says so.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r5.py -q
"""
from __future__ import annotations

import pytest

from backend.lib import evidence_map as em
from backend.routes import tailor
from tests.test_rewrite_display_paths import (
    ACCEPT_ALL,
    ALL_PATHS,
    _rewrite,
    opportunity,  # noqa: F401  (pytest fixture)
    post_full_target,
    post_tailor,
    run,
)
from tests.test_rewrite_display_paths_r4 import EXTRACT_PATHS, _extracted

# ------------------------------------------------------------------ extraction: headings that hold a lock word
# 64df166 read a row under a glyph bullet that holds a word of the locks' status, team, share or
# negation families as the rest of that bullet before asking whether it is a heading. The bullet
# above such a heading could then be extracted only together with the heading: both routes refused
# the model's line for it and lost it, and the no-model fallback glued the heading onto it. Main
# keeps all of these bullets.
HEADINGS = ["Campus Involvement", "Leadership & Involvement", "Team Projects", "Team Experience", "Collaborations",
            "Collaborative Projects", "Ongoing Projects", "Research in Progress", "Works in Progress",
            "Manuscripts in Preparation", "Planned Research", "Accepted Papers", "Submitted Papers",
            "Forthcoming Publications", "论文发表", "发表论文", "在投论文", "合作项目", "合作研究", "参与项目", "团队项目"]
BULLETS = {"en": ("EXPERIENCE", ["Built a Python parser for the lab", "Designed a sensor rig for the team",
                                 "Wrote a data logger in C for the club"]),
           "zh": ("项目经历", ["搭建了校园农场的土壤湿度传感器网络", "为社团设计了一套传感器测试台",
                           "用 C 语言为社团编写了数据记录程序"])}


def _headed(heading):
    top, bullets = BULLETS["en" if heading.isascii() else "zh"]
    return f"{top}\n• {bullets[0]}\n• {bullets[1]}\n{heading}\n• {bullets[2]}\n", bullets


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("heading", HEADINGS)
def test_the_bullet_above_a_heading_with_a_lock_word_is_kept(monkeypatch, path, heading):
    resume, bullets = _headed(heading)
    assert _extracted(monkeypatch, path, resume, bullets) == bullets


@pytest.mark.parametrize("heading", HEADINGS)
def test_the_local_extraction_glues_no_heading_with_a_lock_word_to_a_bullet(heading):
    resume, bullets = _headed(heading)
    assert tailor._heuristic_bullets(resume) == bullets


# The boundary, which db09a88 already holds: a heading-shaped row whose words before its first
# joining word are all status or negation words names nothing of its own, and stays the status
# of the bullet above it (as "Under Review" and 尚未投稿 do in _r4.py).
STATUS_ROWS = {"Submitted to Nature": "en", "Under Review at ICRA": "en", "Not Yet Submitted": "en", "已投稿": "zh"}


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("row", list(STATUS_ROWS))
def test_a_heading_shaped_status_row_stays_with_its_bullet(monkeypatch, path, row):
    top, bullets = BULLETS[STATUS_ROWS[row]]
    resume = f"{top}\n• {bullets[0]}\n{row}\n• {bullets[2]}\n"
    assert bullets[0] not in _extracted(monkeypatch, path, resume, [bullets[0], bullets[2]])


# ------------------------------------------------------------------ criterion (2): an English relabel of an accented word
# 4bbdcb6 kept every relabel that leaves an accented word out of "to", so the relabel of an English
# line's loanword or name ("café inventory" -> "coffee shop inventory", "Müller group" -> "Mueller
# group") was kept before the review; a3f0424 reviewed and showed it, and main shows it. (A bare
# "Müller" -> "Mueller" shares no word, so its link is "broader" and every version keeps it.)
ENGLISH_RELABELS = {
    "loanword": ("Tracked café inventory in Excel for 12 weeks.", "Tracked coffee shop inventory in Excel for 12 weeks.",
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
