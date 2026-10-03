"""Round-3 re-verification (3b) for acceptance criterion (1) of fix/tailor-review.

Provider-free: the extraction, structure, generation and review calls are stubbed at
``chat_completion``. Each test was written as a probe of a gap or a regression the
re-verification of a3f0424 reported, failed there, and now pins the fix.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r4.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import tailor

EXTRACT_PATHS = ["/api/tailor/extract-bullets", "/api/tailor/structure"]


def _extracted(monkeypatch, path, resume, answer):
    """The lines a route returns when the model answers ``answer`` for ``resume``."""
    def model(messages, **kwargs):
        if "Structure it now" in messages[1]["content"]:
            return json.dumps({"sections": [{"heading": "Experience", "kind": "experience", "bullets": answer}]})
        return json.dumps({"bullets": answer})
    monkeypatch.setattr(tailor, "chat_completion", model)
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    body = TestClient(app).post(path, json={"resume_text": resume, "locale": "en"}).json()
    return body["bullets"] if path.endswith("extract-bullets") else [
        bullet["text"] for section in body["sections"] for bullet in section["bullets"]]


# ------------------------------------------------------------------ criterion (1) regression: rows of their own
# a2e3c4e read a row that opens with a capital, a digit or a CJK character under a glyph bullet as the
# rest of that bullet, unless it was in capitals or a short title-case heading. A mixed-case role row,
# a Chinese heading or a "Label: ..." row under the last bullet of a group then made that bullet
# extractable only together with the row: the model's correct answer was refused, the line was lost
# from the renovation doc and "Copy renovated résumé", and the no-model fallback glued the row to it.
OWN_ROWS = {
    "role rows": ("EXPERIENCE\nResearch Assistant, Sleep Lab, Jan 2025 - Present\n"
                  "• Ran 40 overnight EEG sessions with 20 participants\n• Cleaned 212 survey responses in R\n"
                  "Teaching Assistant, PSYC 100, Aug 2024 - Dec 2024\n• Graded 60 lab reports every week\n",
                  ["Ran 40 overnight EEG sessions with 20 participants", "Cleaned 212 survey responses in R",
                   "Graded 60 lab reports every week"]),
    "role row naming a team": ("EXPERIENCE\n• Cleaned 212 survey responses in R\nTeam Lead, Robotics Club, 2023 - 2024\n"
                               "• Wired the battery pack for the robot\n",
                               ["Cleaned 212 survey responses in R", "Wired the battery pack for the robot"]),
    "project title rows": ("PROJECTS\nSoil Sensor Network, Fall 2023\n• Built a soil sensor network for the farm\n"
                           "Campus Food Pantry Dashboard, Spring 2024\n• Built a survey dashboard in R\n",
                           ["Built a soil sensor network for the farm", "Built a survey dashboard in R"]),
    "chinese headings": ("项目经历\n• 搭建了校园农场的土壤湿度传感器网络\n• 清洗并分析了 200 份问卷数据\n实习经历\n"
                         "• 为推广办公室撰写了实地调研报告\n",
                         ["搭建了校园农场的土壤湿度传感器网络", "清洗并分析了 200 份问卷数据", "为推广办公室撰写了实地调研报告"]),
    "chinese role row": ("科研经历\n• 用 R 清洗 212 份问卷数据\n研究助理 2025年1月至今\n• 完成 40 次夜间脑电记录\n",
                         ["用 R 清洗 212 份问卷数据", "完成 40 次夜间脑电记录"]),
    "label row": ("PROJECTS\n• Built a survey dashboard in R\n• Cleaned 200 survey responses for the lab\n"
                  "Technical Skills: Python, R, SQL\n",
                  ["Built a survey dashboard in R", "Cleaned 200 survey responses for the lab"]),
}


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("name", list(OWN_ROWS))
def test_a_bullet_above_a_row_of_its_own_is_kept(monkeypatch, path, name):
    resume, answer = OWN_ROWS[name]
    assert _extracted(monkeypatch, path, resume, answer) == answer


@pytest.mark.parametrize("name", list(OWN_ROWS))
def test_the_local_extraction_glues_no_row_of_its_own_to_a_bullet(name):
    resume, answer = OWN_ROWS[name]
    assert tailor._heuristic_bullets(resume) == answer


# ------------------------------------------------------------------ criterion (1) gap 3: a tab after the glyph
# _resume_rows read every tab as a column gap, so the row under "•\t..." (Word's plain-text list,
# pdf-parser.ts's wide gap) always opened an item: the first physical row of a wrapped bullet was
# accepted whatever opened the row below, and the bullet's status on it was lost.
TAB_WRAPS = {
    "capital": ("•\tCo-authored a paper on soil moisture sensing for the campus farm\n"
                "Under review at the ICRA 2026 workshop\n•\tCleaned 200 survey responses for the lab\n",
                "Co-authored a paper on soil moisture sensing for the campus farm"),
    "lowercase": ("•\tCo-authored a paper on soil moisture sensing for the\ncampus farm, under review at ICRA\n"
                  "•\tCleaned 200 survey responses for the lab\n",
                  "Co-authored a paper on soil moisture sensing for the"),
    "cjk": ("•\t搭建了校园农场的土壤湿度传感器网络\n计划于 2026 年投稿\n•\tCleaned 200 survey responses for the lab\n",
            "搭建了校园农场的土壤湿度传感器网络"),
    "digit": ("•\tBuilt a soil sensor network for the farm\n2026 deployment planned\n"
              "•\tCleaned 200 survey responses for the lab\n", "Built a soil sensor network for the farm"),
}


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("name", list(TAB_WRAPS))
def test_the_first_row_of_a_wrapped_bullet_after_a_tab_is_not_returned(monkeypatch, path, name):
    resume, cut = TAB_WRAPS[name]
    lines = _extracted(monkeypatch, path, resume, [cut, "Cleaned 200 survey responses for the lab"])
    assert cut not in lines, lines


# ------------------------------------------------------------------ criterion (1) gap 3: a status in a row's shape
# A row under a glyph bullet that carries a status, a share of the work or a negation is the rest of
# that bullet whatever its shape: a title-case status (005e618 read "Under Review" as a heading), a
# label, a date range, or a row after one that cannot end an item ("at the").
SHAPED_WRAPS = {
    "title-case status": ("• Co-authored a paper on soil moisture sensing for the farm\nUnder Review\n",
                          "Co-authored a paper on soil moisture sensing for the farm"),
    "title-case unfinished": ("• Co-authored a paper on soil moisture sensing for the farm\nIn Preparation\n",
                              "Co-authored a paper on soil moisture sensing for the farm"),
    "labelled status": ("• Co-authored a paper on soil moisture sensing for the farm\nStatus: under review\n",
                        "Co-authored a paper on soil moisture sensing for the farm"),
    "status with dates": ("• Built a soil sensor network for the campus farm\nIn progress, Jan 2025 - Present\n",
                          "Built a soil sensor network for the campus farm"),
    "title-case collaborators": ("• Built a soil sensor network for the campus farm\nWith Two Graduate Students\n",
                                 "Built a soil sensor network for the campus farm"),
    "after a determiner": ("• Presented a poster on soil moisture sensing at the\nUndergraduate Research Symposium\n",
                           "Presented a poster on soil moisture sensing at the"),
    "chinese status": ("• 搭建了校园农场的土壤湿度传感器网络\n尚未投稿\n", "搭建了校园农场的土壤湿度传感器网络"),
}


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("name", list(SHAPED_WRAPS))
def test_a_status_row_in_any_shape_stays_with_its_bullet(monkeypatch, path, name):
    resume, cut = SHAPED_WRAPS[name]
    assert cut not in _extracted(monkeypatch, path, "EXPERIENCE\n" + resume + "• Cleaned 200 survey responses\n",
                                 [cut, "Cleaned 200 survey responses"])


# ------------------------------------------------------------------ criterion (4): the local extraction off the loop
# Both routes ran the local extraction of every chunk the model did not answer on the event loop, and
# grounded each model line against a layout built again for that line. a2e3c4e's row reading made both
# dearer: on a3f0424 ten 60,000-character requests at once held the loop 640 ms with no model and
# 2,283 ms with a model answering 60 lines (scripts/extract_route_lag.py --concurrent 10 [--model]).
@pytest.mark.parametrize(("path", "local"), [("/api/tailor/extract-bullets", "_heuristic_bullets"),
                                             ("/api/tailor/structure", "_heuristic_structure")])
def test_the_local_extraction_runs_on_the_request_lane(monkeypatch, path, local):
    import threading
    threads = []
    original = getattr(tailor, local)

    def recorded(*args, **kwargs):
        threads.append(threading.current_thread().name)
        return original(*args, **kwargs)
    monkeypatch.setattr(tailor, local, recorded)
    monkeypatch.setattr(tailor, "is_configured", lambda: False)
    body = {"resume_text": "EXPERIENCE\n• Cleaned 212 survey responses in R\n", "locale": "en"}
    if path.endswith("extract-bullets"):
        body["expected_pipeline_version"] = tailor.TAILOR_PIPELINE_VERSION
    assert TestClient(app).post(path, json=body).status_code == 200
    assert threads and all(name.startswith("ofe-request-work") for name in threads), threads


def test_the_model_lines_of_a_chunk_are_grounded_against_one_layout(monkeypatch):
    calls = []
    original = tailor._extraction_layout
    monkeypatch.setattr(tailor, "_extraction_layout", lambda text: calls.append(1) or original(text))
    lines = [f"Cleaned {count} survey responses in R" for count in range(100, 110)]
    monkeypatch.setattr(tailor, "chat_completion", lambda *a, **k: json.dumps({"bullets": lines}))
    resume = "EXPERIENCE\n" + "".join(f"• {line}\n" for line in lines)
    assert tailor._ai_extract_bullets(resume) == lines
    assert len(calls) == 1
