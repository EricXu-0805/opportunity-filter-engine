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

from backend.routes import tailor
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
