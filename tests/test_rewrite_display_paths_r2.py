"""Round-2 display paths for acceptance criteria (1) and (3) of fix/tailor-review.

Provider-free: the generation call, the renovation plan and the faithfulness
review are stubbed at ``chat_completion`` through the helpers of
tests/test_rewrite_display_paths.py. Written by the round-2 review as probes;
the gaps they found are fixed, and each test now pins the fix.

Round 4 moved extraction back to origin/main's and removed this file's extraction
probes; their résumés are cases of tests/fixtures/extraction_differential_cases.json,
which tests/test_extraction_matches_main.py runs against main.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r2.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.lib import evidence_map as em
from backend.main import app
from backend.routes import tailor
from tests.test_rewrite_display_paths import (
    ACCEPT_ALL,
    ALL_PATHS,
    PROFILE,
    TAILOR_PATHS,
    _rewrite,
    offered,
    opportunity,  # noqa: F401  (pytest fixture)
    post_tailor,
    review_by,
    run,
)

# ------------------------------------------------------------------ criterion (3)
# A relabel whose "from" is written in a script that is neither ASCII nor CJK ideographs
# (Hangul, kana, Cyrillic) and whose "to" is English. language() and tokens() read neither,
# so the line's own Korean / Japanese / Russian words could be swapped for the posting's
# English: every letter they cannot read now keeps its count (scripts/other_script_probe.py).
PIPELINE_ANCHOR = "Experience building a Python data pipeline is required."
PIPELINE_LINK = [{"id": "L1", "anchor": "t1", "term": "Python data pipeline", "source": None, "relation": "same"}]

OTHER_SCRIPT_RELABELS = {
    "hangul": ("Python 데이터 파이프라인 구축 및 유지보수 담당", "Python 데이터 파이프라인"),
    "kana": ("Python データパイプライン の かいはつ を たんとう", "Python データパイプライン"),
    "cyrillic": ("Разработка: Python конвейер данных для лаборатории", "Python конвейер данных"),
}


def _relabel_row(original, source):
    rewrite = original.replace(source, "Python data pipeline")
    links = [{**PIPELINE_LINK[0], "source": source}]
    return rewrite, _rewrite(rewrite, [{"op": "relabel", "link": "L1", "from": source, "to": "Python data pipeline"}],
                             links)


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("script", list(OTHER_SCRIPT_RELABELS))
def test_a_relabel_out_of_a_non_cjk_script_is_kept_before_the_review(opportunity, monkeypatch, path, script):  # noqa: F811
    original, source = OTHER_SCRIPT_RELABELS[script]
    _, row = _relabel_row(original, source)
    shown, seen = run(opportunity, monkeypatch, path, original, row, PIPELINE_ANCHOR)
    assert (shown, seen) == ([], set())


# The same blind spot without a relabel: lead_with reorders the line and its own conjunction
# (및 / и / と) is written as the English "and", or the line keeps every letter of its own and
# gains English glue. A line written in part in a non-Latin script gains no English function word.
SQL_ANCHOR = "Experience with SQL is required."
SQL_LINK = [{"id": "L1", "anchor": "t1", "term": "SQL", "source": "SQL", "relation": "same"}]
CONJUNCTION_SWAPS = {
    "hangul": ("Python 및 SQL 데이터 정리 담당", "SQL and Python 데이터 정리 담당"),
    "cyrillic": ("Python и SQL для обработки данных", "SQL and Python для обработки данных"),
    "kana": ("Python と SQL で データ を せいり", "SQL and Python で データ を せいり"),
}
GLUE = {
    "hangul": ("데이터 분석: Python, SQL", "SQL and Python: 데이터 분석"),
    "cyrillic": ("Анализ данных: Python, SQL", "SQL and Python: Анализ данных"),
    "kana": ("データ ぶんせき: Python, SQL", "SQL and Python: データ ぶんせき"),
}


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize(("script", "shape"), [(script, shape) for shape in ("conjunction", "glue")
                                               for script in CONJUNCTION_SWAPS])
def test_a_non_cjk_line_gains_no_english_function_word(opportunity, monkeypatch, path, script, shape):  # noqa: F811
    original, rewrite = (CONJUNCTION_SWAPS if shape == "conjunction" else GLUE)[script]
    shown, seen = run(opportunity, monkeypatch, path, original,
                      _rewrite(rewrite, [{"op": "lead_with", "link": "L1"}], SQL_LINK), SQL_ANCHOR)
    assert (shown, seen) == ([], set())


@pytest.mark.parametrize("path", TAILOR_PATHS)
def test_a_reorder_that_keeps_a_non_cjk_line_in_its_own_words_still_goes_to_the_review(opportunity, monkeypatch,  # noqa: F811
                                                                                      path):
    original, rewrite = "Python 및 SQL 데이터 정리 담당", "SQL 및 Python 데이터 정리 담당"
    shown, seen = run(opportunity, monkeypatch, path, original,
                      _rewrite(rewrite, [{"op": "lead_with", "link": "L1"}], SQL_LINK), SQL_ANCHOR)
    assert (shown, seen) == ([rewrite], {rewrite})


# ------------------------------------------------------------------ criterion (1): fallbacks
# Every failure mode of the review falls back to the submitted line on every route.

# The line holds "for" and "the", the English evidence the default keep asks for (round 4).
ONE = ("Responsible for writing Python scripts for data cleaning in the lab.",
       _rewrite("Wrote Python code for data cleaning in the lab.",
                [{"op": "relabel", "link": "L1", "from": "Python scripts", "to": "Python code"}, {"op": "verb_first"}],
                [{"id": "L1", "anchor": "t1", "term": "Python code", "source": "Python scripts", "relation": "same"}]))
ONE_ANCHOR = "Experience writing Python code is required."


def _verdict(index, faithful=True, links=(("L1", True),), **extra):
    return {"index": index, "changes": "[ok]", "faithful": faithful,
            "links": [{"id": ident, "entailed": ok} for ident, ok in links], "problem": "", **extra}


FAILING_REVIEWS = {
    "no answer": None,
    "empty string": "",
    "invalid json": "{verdicts:",
    "verdicts not a list": json.dumps({"verdicts": {"1": True}}),
    "empty verdict list": json.dumps({"verdicts": []}),
    "index 0": json.dumps({"verdicts": [_verdict(0)]}),
    "index past the end": json.dumps({"verdicts": [_verdict(3)]}),
    "index as float": json.dumps({"verdicts": [_verdict(1.0)]}),
    "index as bool": json.dumps({"verdicts": [_verdict(True)]}),
    "faithful as string": json.dumps({"verdicts": [_verdict(1, faithful="true")]}),
    "links missing": json.dumps({"verdicts": [{"index": 1, "changes": "[ok]", "faithful": True, "problem": ""}]}),
    "link not entailed": json.dumps({"verdicts": [_verdict(1, links=(("L1", False),))]}),
    "link entailed as string": json.dumps({"verdicts": [{**_verdict(1), "links": [{"id": "L1", "entailed": "true"}]}]}),
    "unknown link id": json.dumps({"verdicts": [_verdict(1, links=(("L9", True),))]}),
    "extra link id": json.dumps({"verdicts": [_verdict(1, links=(("L1", True), ("L2", True)))]}),
    "duplicate link id": json.dumps({"verdicts": [_verdict(1, links=(("L1", True), ("L1", True)))]}),
    "conflicting duplicate": json.dumps({"verdicts": [_verdict(1), _verdict(1, faithful=False)]}),
    "broken rule tag": json.dumps({"verdicts": [{**_verdict(1), "changes": "dropped 'responsible' [3]"}]}),
    "top-level list": json.dumps([_verdict(1)]),
    "verdict for the alternative only": json.dumps({"verdicts": [_verdict(2, links=())]}),
    "truncated envelope": json.dumps({"verdicts": [_verdict(1)]})[:-3],
}


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(FAILING_REVIEWS))
def test_a_review_that_does_not_accept_the_rewrite_shows_nothing(opportunity, monkeypatch, path, name):  # noqa: F811
    shown, seen = run(opportunity, monkeypatch, path, ONE[0], ONE[1], ONE_ANCHOR, FAILING_REVIEWS[name])
    assert ONE[1]["text"] in seen
    assert shown == [], (name, shown)


@pytest.mark.parametrize("path", TAILOR_PATHS)
def test_a_review_that_raises_or_times_out_keeps_the_original(opportunity, monkeypatch, path):  # noqa: F811
    from backend.lib.blocking import BlockingWorkTimeout

    original_run = em.run_blocking

    async def review_times_out(func, *args, **kwargs):
        if func is em.ai_review:
            raise BlockingWorkTimeout()
        return await original_run(func, *args, **kwargs)

    monkeypatch.setattr(em, "run_blocking", review_times_out)
    body, reviews = post_tailor(opportunity, monkeypatch, path, [ONE], ACCEPT_ALL, anchors=[ONE_ANCHOR])
    assert offered(path, body) == [[]] and reviews == []


@pytest.mark.parametrize("path", TAILOR_PATHS)
def test_no_time_left_for_the_review_keeps_the_original(opportunity, monkeypatch, path):  # noqa: F811
    monkeypatch.setattr(em, "review_window", lambda started: None)
    body, reviews = post_tailor(opportunity, monkeypatch, path, [ONE], ACCEPT_ALL, anchors=[ONE_ANCHOR])
    assert offered(path, body) == [[]] and reviews == []


@pytest.mark.parametrize("path", TAILOR_PATHS)
def test_a_review_that_raises_inside_the_worker_is_a_500_not_a_display(opportunity, monkeypatch, path):  # noqa: F811
    """chat_completion swallows provider errors, but an error inside ai_review itself propagates."""
    def boom(*args, **kwargs):
        raise RuntimeError("reviewer crashed")
    monkeypatch.setattr(em, "ai_review", boom)
    anchors = [em.Anchor("t1", {"field": "description", "requirement_index": None, "start": 0,
                                "end": len(ONE_ANCHOR), "quote": ONE_ANCHOR})]
    monkeypatch.setattr(tailor, "_snapshot_anchors", lambda source, snapshot: anchors)

    def model(messages, **kwargs):
        if "REORGANIZE" in messages[0]["content"]:
            return json.dumps({"sections": [{"id": "s1", "bullets": [{"id": "b0", "action": "foreground"}]}]})
        units = json.loads(messages[1]["content"].split("DATA (JSON):\n", 1)[1])["units"]
        return json.dumps({"bullets": [{"unit_id": unit["unit_id"], **ONE[1]} for unit in units]})
    monkeypatch.setattr(tailor, "chat_completion", model)
    payload = {"profile": PROFILE, "opportunity_id": opportunity, "locale": "en"}
    if path.endswith("/renovate"):
        payload["sections"] = [{"id": "s1", "heading": "P", "kind": "projects", "bullets": [{"id": "b0", "text": ONE[0]}]}]
    elif path.endswith("/bullet"):
        payload.update(base_text=ONE[0], current_text=ONE[0])
    else:
        payload["original_bullets"] = [ONE[0]]
    response = TestClient(app, raise_server_exceptions=False).post(path, json=payload)
    assert response.status_code == 500 and ONE[1]["text"] not in response.text


@pytest.mark.parametrize("path", TAILOR_PATHS)
def test_a_second_attempt_answer_counts_only_if_complete(opportunity, monkeypatch, path):  # noqa: F811
    """A retried review returns one answer; a later corrected envelope after a broken one is not read."""
    reply = "{\"verdicts\": [" + json.dumps(_verdict(1)) + "\n" + json.dumps({"verdicts": [_verdict(1)]})
    shown, _ = run(opportunity, monkeypatch, path, ONE[0], ONE[1], ONE_ANCHOR, reply)
    assert shown == []


# ------------------------------------------------------------------ criterion (1): the generation answer

@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/renovate"])
def test_duplicate_rows_for_one_unit_keep_it_as_written(opportunity, monkeypatch, path):  # noqa: F811
    anchors = [em.Anchor("t1", {"field": "description", "requirement_index": None, "start": 0,
                                "end": len(ONE_ANCHOR), "quote": ONE_ANCHOR})]
    monkeypatch.setattr(tailor, "_snapshot_anchors", lambda source, snapshot: anchors)
    reviews: list = []

    def model(messages, **kwargs):
        system = messages[0]["content"]
        if system.startswith("FAITHFULNESS REVIEW"):
            reviews.append(json.loads(messages[1]["content"]))
            return ACCEPT_ALL(reviews[-1])
        if "REORGANIZE" in system:
            return json.dumps({"sections": [{"id": "s1", "bullets": [{"id": "b0", "action": "foreground"}]}]})
        units = json.loads(messages[1]["content"].split("DATA (JSON):\n", 1)[1])["units"]
        row = {"unit_id": units[0]["unit_id"], **ONE[1]}
        return json.dumps({"bullets": [row, row]})
    monkeypatch.setattr(tailor, "chat_completion", model)
    monkeypatch.setattr(em, "chat_completion", model)
    payload = {"profile": PROFILE, "opportunity_id": opportunity, "locale": "en"}
    if path.endswith("/renovate"):
        payload["sections"] = [{"id": "s1", "heading": "P", "kind": "projects", "bullets": [{"id": "b0", "text": ONE[0]}]}]
    else:
        payload["original_bullets"] = [ONE[0]]
    body = TestClient(app).post(path, json=payload).json()
    assert offered(path, body) == [[]] and reviews == []


@pytest.mark.parametrize("separator", ["\x1f", "\x1c", " \x85 "])
def test_a_line_of_separator_controls_is_refused_not_dropped(opportunity, monkeypatch, separator):  # noqa: F811
    """str.strip() empties a line of U+001C-U+001F / U+0085 that String.prototype.trim() keeps.

    TailorModal pairs each row with submitted[source_index] (reviewedBullets). Dropped, such a
    line made every later card show the line above it; it is refused before any model call.
    """
    calls: list = []
    monkeypatch.setattr(tailor, "chat_completion", lambda *a, **k: calls.append(a) or None)
    monkeypatch.setattr(em, "chat_completion", lambda *a, **k: calls.append(a) or None)
    submitted = ["Tutored 12 students in calculus each week.", separator, "Built a weather station with two classmates."]
    response = TestClient(app).post("/api/tailor", json={"profile": PROFILE, "opportunity_id": opportunity,
                                                        "original_bullets": submitted})
    assert (response.status_code, calls) == (422, [])
    assert submitted[2] not in response.text


def test_blank_layout_lines_are_still_dropped(opportunity, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tailor, "chat_completion", lambda *a, **k: None)
    monkeypatch.setattr(em, "chat_completion", lambda *a, **k: None)
    submitted = ["Tutored 12 students in calculus each week.", " \t　", "Built a weather station with two classmates."]
    body = TestClient(app).post("/api/tailor", json={"profile": PROFILE, "opportunity_id": opportunity,
                                                    "original_bullets": submitted}).json()
    assert [row["text"] for row in body["tailored_bullets"]] == [submitted[0], submitted[2]]


# ------------------------------------------------------------------ criterion (3): holds

@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize(("original", "rewrite", "ops"), [
    # Chinese line keeps a few Chinese words, the rest translated.
    ("在北京大学实验室用 Python 清洗了 212 份问卷数据", "Cleaned 212 份问卷 with Python at 北京大学实验室", [{"op": "verb_first"}]),
    # English line with full-width punctuation rewritten with a Chinese clause.
    ("Cleaned 212 survey responses in R；wrote the lab report.", "撰写了实验报告；Cleaned 212 survey responses in R.",
     [{"op": "verb_first"}]),
    # Numbers and symbols only, rewritten into words.
    ("2023 – 2024 | 3.9 / 4.0", "GPA 3.9 / 4.0 from 2023 to 2024", [{"op": "verb_first"}]),
    # Full-width Latin added to an ASCII line.
    ("Analyzed EEG recordings in Python.", "Analyzed EEG recordings in Ｐｙｔｈｏｎ.", [{"op": "verb_first"}]),
], ids=["zh-keeps-few-words", "en-gains-zh-clause", "numbers-only", "full-width-latin"])
def test_other_language_rewrites_are_kept_before_the_review(opportunity, monkeypatch, path, original, rewrite, ops):  # noqa: F811
    shown, seen = run(opportunity, monkeypatch, path, original, _rewrite(rewrite, ops),
                      "We analyze EEG recordings and survey responses.")
    assert (shown, seen) == ([], set())


def test_each_rewrite_needs_its_own_accepted_verdict(opportunity, monkeypatch):  # noqa: F811
    """Two rewrites, the reviewer accepts only the second: the first stays as written."""
    two = [ONE, ("Responsible for writing Python scripts for plotting the data.",
                 _rewrite("Wrote Python code for plotting the data.",
                          [{"op": "relabel", "link": "L1", "from": "Python scripts", "to": "Python code"},
                           {"op": "verb_first"}],
                          [{"id": "L1", "anchor": "t1", "term": "Python code", "source": "Python scripts",
                            "relation": "same"}]))]
    body, reviews = post_tailor(opportunity, monkeypatch, "/api/tailor", two,
                                review_by(lambda pair: pair["rewrite"] == "Wrote Python code for plotting the data."),
                                anchors=[ONE_ANCHOR])
    assert [bool(texts) for texts in offered("/api/tailor", body)] == [False, True]
