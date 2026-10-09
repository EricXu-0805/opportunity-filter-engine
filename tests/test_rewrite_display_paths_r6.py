"""Round-3 re-verification (3d) for acceptance criteria (1) to (3) and the extraction standard of fix/tailor-review.

Provider-free: the extraction, structure, generation and review calls are stubbed at
``chat_completion``. Each test probes a regression the re-verification of a6979522 reported, or a
guard it found no test for, and fails on a6979522; a test that pins a boundary a6979522 already
holds says so.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r6.py -q
"""
from __future__ import annotations

import pytest

from backend.lib import evidence_map as em
from backend.routes import tailor
from tests.test_rewrite_display_paths import (
    ALL_PATHS,
    opportunity,  # noqa: F401  (pytest fixture)
    run,
)
from tests.test_rewrite_display_paths_r4 import EXTRACT_PATHS, _extracted
from tests.test_rewrite_display_paths_r5 import _relabel_row

EN = ["Ran 40 overnight EEG sessions with 20 participants", "Designed a sensor rig for the team",
      "Wrote a data logger in C for the club"]
ZH = ["搭建了校园农场的土壤湿度传感器网络", "为社团设计了一套传感器测试台", "用 C 语言为社团编写了数据记录程序"]

# ------------------------------------------------------------------ extraction: bullet glyphs
# a6979522 started a bullet only at a row's start or after a glyph of _LINE_GLYPH. A résumé whose
# bullets open with any other glyph had no model line accepted on either route (the glyph stood
# between the row's start and the bullet), and the fallback's _BULLET_PREFIX_RE read none of them:
# both routes returned no bullet. Main accepts every model line. The first group is the frontend's
# own BULLET_LINE set (resume-input.ts) and pdf-parser.ts's BULLET_GLYPH: U+F0B7 is Word's Symbol-font
# bullet as a PDF extracts it.
FRONTEND_GLYPHS = ["\uf0b7\t", "\uf0a7 ", "\uf076 ", "\uf0d8 ", "\uf0fc ", "‣ ", "∙ ", "■ ", "► ", "➢\t", "✓ ", "◆ ",
                   "(1) "]
OTHER_GLYPHS = ["o\t", "o ", "a. ", "-", "–", "1、", "（1）", "①", "① ", "※ ", "★ ", "√ ", "○ ", "> ", "a) ", "(1)", "1.",
                "◇ ", "❖ "]


def _glyphed(glyph, lang):
    bullets = EN if lang == "en" else ZH
    top = "EXPERIENCE\nResearch Assistant, Smith Lab" if lang == "en" else "项目经历"
    return top + "\n" + "".join(f"{glyph}{bullet}\n" for bullet in bullets), bullets


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("glyph", FRONTEND_GLYPHS + OTHER_GLYPHS)
def test_a_bullet_after_any_glyph_or_list_number_is_kept(monkeypatch, path, lang, glyph):
    resume, bullets = _glyphed(glyph, lang)
    assert _extracted(monkeypatch, path, resume, bullets) == bullets


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("glyph", FRONTEND_GLYPHS)
def test_the_local_extraction_reads_the_frontends_glyphs(lang, glyph):
    resume, bullets = _glyphed(glyph, lang)
    assert tailor._heuristic_bullets(resume) == bullets


# The boundary, which a6979522 holds: a bullet never starts past a sign that bounds or approximates its
# number, nor inside a number.
@pytest.mark.parametrize(("row", "cut"), [("~40 participants surveyed in 3 villages", "40 participants surveyed in 3 villages"),
                                          ("> 90% accuracy on held-out nights", "90% accuracy on held-out nights"),
                                          ("1.5x faster parser for the lab", "5x faster parser for the lab"),
                                          ("-20% error on the test split", "20% error on the test split")])
def test_no_bullet_starts_past_a_sign_or_inside_a_number(row, cut):
    resume = f"EXPERIENCE\n{row}\n"
    assert tailor._bullet_grounded(row, resume) and not tailor._bullet_grounded(cut, resume)


# ------------------------------------------------------------------ extraction: entry rows under a bullet
# a6979522 read a row under a glyph bullet as the rest of that bullet unless its shape made it a row
# of its own. A date row, a sentence-case title, a label with lower-case words or CJK fields read as
# the bullet's last row: both routes refused the model's line for the bullet above and lost it, and
# the fallback glued the row onto it. Main keeps every one. Now a row that only nothing shapes as a
# row of its own is soft, and a cut above it is accepted when the rows it leaves out carry no
# status, share or negation word (_item_cuts); entry title rows with such a word that name their
# item besides it are rows of their own (_entry_row).
ENTRY_ROWS = [
    # no lock word: read as soft rows
    "2023-2024", "2024.09 - 2025.06", "Machine learning for sleep staging",
    "Relevant coursework: Data Structures, Algorithms", "Sleep staging with deep learning (CS 446 final project)",
    "Joint Project with Department of Psychology",
    "北京大学 物理学院", "某某公司 软件工程实习生", "计算机工程 学士", "全国大学生数学建模竞赛 二等奖", "伊利诺伊大学厄巴纳-香槟分校",
    # a lock word in an entry's title row that names its item besides it
    "Robotics Team, UIUC", "Smith Research Group, UIUC", "iGEM Team, University of Illinois", "iGEM Team (2024)",
    "Illini Formula SAE Team, Champaign, IL", "Undergraduate Research Team, Smith Lab",
    "Liu Lab Group, Department of Psychology", "Planned Parenthood of Illinois, Champaign",
    "Collaborative Robotics Lab, UIUC", "Solar Car Team, UIUC — Electrical Lead",
    "Autonomous Rover (Ongoing) | ROS, Python", "Course Scheduler | Team of 4 | Fall 2024",
    "Campus Navigation App (In Progress)", "Senior Design Project — In Progress",
    "B.S. in Computer Engineering, Expected May 2027", "Expected Graduation: May 2027",
    "Sleep Spindles and Memory, Under Review at SLEEP",
    "Projects (Team)", "Leadership, Service & Involvement", "Research Experience — Ongoing",
    "智能机器人团队，清华大学", "智能温室项目（进行中）", "国家大学生创新训练项目（在研）", "论文发表（第一作者）",
    "团队项目：校园导航App", "某某实验室 科研助理（拟加入）",
]


def _entry(row):
    top, bullets = ("EXPERIENCE", EN) if row.isascii() else ("项目经历", ZH)
    return f"{top}\n• {bullets[0]}\n• {bullets[1]}\n{row}\n• {bullets[2]}\n", bullets


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("row", ENTRY_ROWS)
def test_the_bullet_above_an_entry_row_is_kept(monkeypatch, path, row):
    resume, bullets = _entry(row)
    assert _extracted(monkeypatch, path, resume, bullets) == bullets


@pytest.mark.parametrize("row", ENTRY_ROWS)
def test_the_local_extraction_glues_no_entry_row_to_a_bullet(row):
    resume, bullets = _entry(row)
    assert tailor._heuristic_bullets(resume) == bullets


# Found while fixing the above: an organization row that starts the next entry, under a sentence-case
# heading or directly under the last bullet of an entry (the re-verification's résumé).
ORG_RESUMES = {
    "org row under a sentence-case heading": (
        "EXPERIENCE\nResearch Assistant, Sleep Lab\n• Ran 40 overnight EEG sessions\n• Cleaned 212 survey responses in R\n"
        "Extracurricular activities\nRobotics Team, UIUC\n• Designed the battery box for the car\n",
        ["Ran 40 overnight EEG sessions", "Cleaned 212 survey responses in R", "Designed the battery box for the car"]),
    "org row then role row": (
        "RESEARCH EXPERIENCE\nSleep Lab, UIUC\nResearch Assistant, Jan 2025 - Present\n"
        "• Ran 40 overnight EEG sessions with 20 participants\n• Cleaned 212 survey responses in R\n"
        "Smith Research Group, UIUC\nUndergraduate Researcher, Aug 2024 - Dec 2024\n• Built a Python parser for lab notebooks\n",
        ["Ran 40 overnight EEG sessions with 20 participants", "Cleaned 212 survey responses in R",
         "Built a Python parser for lab notebooks"]),
    "date row under the last bullet": (
        "EXPERIENCE\nSmith Lab, Undergraduate Research Assistant\nJan 2025 - Present\n"
        "• Built a Python pipeline that cleans 200 EEG recordings\n• Ran 40 overnight sleep sessions with 20 participants\n"
        "2023-2024\nCampus Food Pantry, Volunteer Data Lead\n• Designed an inventory dashboard in React\n",
        ["Built a Python pipeline that cleans 200 EEG recordings", "Ran 40 overnight sleep sessions with 20 participants",
         "Designed an inventory dashboard in React"]),
    "chinese team org row": (
        "科研经历\n脑科学实验室，清华大学\n• 完成了40次夜间脑电实验\n• 用 R 清洗了212份问卷数据\n智能机器人团队，清华大学\n• 设计了机器人的电池仓\n",
        ["完成了40次夜间脑电实验", "用 R 清洗了212份问卷数据", "设计了机器人的电池仓"]),
}


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("name", list(ORG_RESUMES))
def test_the_bullet_above_the_next_entrys_rows_is_kept(monkeypatch, path, name):
    resume, bullets = ORG_RESUMES[name]
    assert _extracted(monkeypatch, path, resume, bullets) == bullets
    assert tailor._heuristic_bullets(resume) == bullets


# The boundary: a row that names nothing but a status, a share or a negation, in an entry row's
# shape, stays the bullet's (a6979522 holds these too), and so does a soft row with such a row below
# it, or a row that is itself such a status in a field.
STATUS_FIELDS = ["Status: Under Review", "Under Review: NeurIPS 2025", "Team of 4, Fall 2024",
                 "Under Review at ICRA, 2025", "Ongoing, Jan 2025 - Present", "In progress, Jan 2025 - Present",
                 "With Two Graduate Students, Smith Lab", "Planned Fall 2026, NSF REU", "与两名研究生合作，共同完成",
                 "计划于 2026 年投稿", "论文在投 Under Review", "论文在投 | Under Review"]


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("row", STATUS_FIELDS)
def test_a_status_in_an_entry_rows_shape_stays_with_its_bullet(monkeypatch, path, row):
    top, bullets = ("EXPERIENCE", EN) if row.isascii() else ("项目经历", ZH)
    resume = f"{top}\n• {bullets[0]}\n{row}\n• {bullets[2]}\n"
    assert bullets[0] not in _extracted(monkeypatch, path, resume, [bullets[0], bullets[2]])


SOFT_WRAPS = {
    "status below a soft row": ("• Co-wrote a soil sensing paper for the campus farm\nMachine learning for sleep staging\n"
                                "under review at SLEEP\n", "Co-wrote a soil sensing paper for the campus farm"),
    "share below a soft row": ("• Built a soil sensor network for the campus farm\n"
                               "Sleep staging with deep learning (CS 446 final project)\nTeam of 4\n",
                               "Built a soil sensor network for the campus farm"),
}


@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("name", list(SOFT_WRAPS))
def test_a_cut_above_a_soft_row_that_leaves_out_a_status_is_refused(monkeypatch, path, name):
    resume, cut = SOFT_WRAPS[name]
    assert cut not in _extracted(monkeypatch, path, "EXPERIENCE\n" + resume + "• Cleaned 200 survey responses\n",
                                 [cut, "Cleaned 200 survey responses"])


def test_a_soft_row_with_no_status_in_its_item_may_start_a_bullet():
    # As main accepts it: the model's line for the soft row alone leaves out no status.
    resume = "EXPERIENCE\n• Ran 40 overnight sleep sessions with 20 participants\nMachine learning for sleep staging\n"
    assert tailor._bullet_grounded("Machine learning for sleep staging", resume)


# A row read as a row of its own reads the rows below it apart from the bullet above: a date range, CJK
# fields apart by spaces, or a list number or circled number that opens the next item.
ROWS_BELOW = {
    "date range above a share": ("EXPERIENCE\n• Built a soil sensor network for the campus farm\n2023-2024\nTeam of 4\n",
                                 "Built a soil sensor network for the campus farm", True),
    "CJK fields above a plan": ("项目经历\n• 搭建了校园农场的土壤湿度传感器网络\n北京大学 物理学院\n计划于 2026 年毕业\n",
                                "搭建了校园农场的土壤湿度传感器网络", True),
    "circled number, status below": ("EXPERIENCE\n①Co-authored a paper on soil moisture sensing for the farm\nUnder Review\n"
                                     "②Cleaned 200 survey responses\n",
                                     "Co-authored a paper on soil moisture sensing for the farm", False),
    "list number, status below": ("EXPERIENCE\n(1)Co-authored a paper on soil moisture sensing for the farm\nUnder Review\n"
                                  "(2)Cleaned 200 survey responses\n",
                                  "Co-authored a paper on soil moisture sensing for the farm", False),
}


@pytest.mark.parametrize("name", list(ROWS_BELOW))
def test_a_row_of_its_own_reads_the_rows_below_it_apart_from_the_bullet(name):
    resume, bullet, grounded = ROWS_BELOW[name]
    assert tailor._bullet_grounded(bullet, resume) is grounded


def test_a_soft_row_with_a_status_is_not_a_bullet_of_its_own():
    # Starting a bullet at a soft row would part the status on it from the claim above it.
    resume = "EXPERIENCE\n• Built a soil sensor network for the campus farm\nPaper on sleep spindles under review\n"
    assert not tailor._bullet_grounded("Paper on sleep spindles under review", resume)
    assert tailor._bullet_grounded("Built a soil sensor network for the campus farm Paper on sleep spindles under review",
                                   resume)


# ------------------------------------------------------------------ guards with no test on a6979522
# The re-verification mutated each of these guards and no test failed. a6979522 passes these tests;
# each fails when its guard is dropped: the word limit and the 40-character bound of
# _heading_in_sentence_case, the _own_row check on a bilingual heading's English name, the last-row
# clause of the sentence-case flip, and the bilingual clause of _row_of_its_own's shape test.
@pytest.mark.parametrize("path", EXTRACT_PATHS)
@pytest.mark.parametrize("row", ["Paper on sleep spindles under review",                 # five words or more
                                 "Unpublished interdisciplinary neuroengineering manuscript",  # longer than 40
                                 "合作完成 joint work"])  # CJK letters and lower-case English: no bilingual heading
def test_a_status_row_no_heading_rule_reads_stays_with_its_bullet(monkeypatch, path, row):
    top, bullets = ("EXPERIENCE", EN) if row.isascii() else ("项目经历", ZH)
    resume = f"{top}\n• {bullets[0]}\n{row}\n• {bullets[2]}\n"
    assert bullets[0] not in _extracted(monkeypatch, path, resume, [bullets[0], bullets[2]])


@pytest.mark.parametrize("path", EXTRACT_PATHS)
def test_the_bullet_above_a_sentence_case_heading_on_the_last_row_is_kept(monkeypatch, path):
    resume = f"EXPERIENCE\n• {EN[0]}\n• {EN[1]}\nTeam projects\n"
    assert _extracted(monkeypatch, path, resume, EN[:2]) == EN[:2]
    assert tailor._heuristic_bullets(resume) == EN[:2]


@pytest.mark.parametrize("path", EXTRACT_PATHS)
def test_a_bilingual_heading_starts_a_row_of_its_own_for_the_rows_below_it(monkeypatch, path):
    # A bilingual heading whose English name opens with a joining word names nothing ahead of the
    # qualifier check, and is read by the shape test's bilingual clause. Read as a soft row, it
    # would keep the glyph item open, and "Expected May 2027" below it would go on with the
    # bullet and take it.
    resume = f"EXPERIENCE\n• {EN[0]}\n研究经历 At UIUC\nExpected May 2027\n"
    assert _extracted(monkeypatch, path, resume, EN[:1]) == EN[:1]


# ------------------------------------------------------------------ criterion (3): relabels in other Latin-script languages
# _accents_kept read a relabel as within one language as soon as its "from" had no accented word, and
# language() reads every Latin-script line as English: a Spanish, French, German, Italian or Indonesian
# phrase relabeled into English reached the review on every route and was shown. The review prompt's
# rule 5 accepts a faithful translation.
FOREIGN_LINES = {
    "spanish, accented elsewhere": ("Diseñé un sistema de control para 40 sensores del laboratorio.",
                                    "Diseñé un control system para 40 sensores del laboratorio.",
                                    "sistema de control", "control system", "Build a control system for lab sensors."),
    "spanish, no accent": ("Disene un sistema de control para 40 sensores del laboratorio.",
                           "Disene un control system para 40 sensores del laboratorio.",
                           "sistema de control", "control system", "Build a control system for lab sensors."),
    "spanish pipeline": ("Desarrollo un pipeline de datos para 40 sensores.", "Desarrollo un data pipeline para 40 sensores.",
                         "pipeline de datos", "data pipeline", "Build a data pipeline in Python."),
    "french": ("Construit un pipeline de capteurs pour 40 parcelles.", "Construit un sensor pipeline pour 40 parcelles.",
               "pipeline de capteurs", "sensor pipeline", "Maintain the sensor pipeline for field plots."),
    "french with english function words": ("Il a construit un pipeline de mesures on the side.",
                                           "Il a construit un measurement pipeline on the side.",
                                           "pipeline de mesures", "measurement pipeline",
                                           "Maintain the measurement pipeline for the lab."),
    "french accented, english function words": ("Il a construit un pipeline de données on the side.",
                                                "Il a construit un data pipeline on the side.",
                                                "pipeline de données", "data pipeline", "Build a data pipeline in Python."),
    "german": ("Entwickelte ein Python Skript fuer 40 Sensoren im Labor.",
               "Entwickelte ein Python script fuer 40 Sensoren im Labor.", "Python Skript", "Python script",
               "Write a Python script for sensor data."),
    "italian": ("Sviluppato una pipeline di dati per 40 sensori.", "Sviluppato una data pipeline per 40 sensori.",
                "pipeline di dati", "data pipeline", "Build a data pipeline in Python."),
    "indonesian": ("Membangun model regresi untuk data sensor dari 40 lahan.",
                   "Membangun regression model untuk data sensor dari 40 lahan.", "model regresi", "regression model",
                   "Fit a regression model to sensor data."),
}


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(FOREIGN_LINES))
def test_a_phrase_of_another_latin_script_language_relabeled_into_english_is_kept(
        opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite, source, term, anchor = FOREIGN_LINES[name]
    shown, seen = run(opportunity, monkeypatch, path, original, _relabel_row(rewrite, source, term), anchor)
    assert rewrite not in seen and rewrite not in shown, (shown, seen)


# The boundary, which a6979522 holds: an English line's relabel still reaches the review.
ENGLISH_LINES = {
    "lead verb": ("Built a data pipeline in Python for 40 sensors.", "Built an ETL pipeline in Python for 40 sensors.",
                  "data pipeline", "ETL pipeline", "Maintain the ETL pipeline in Python."),
    "role noun first": ("Responsible for writing Python scripts for data cleaning.",
                        "Responsible for writing Python code for data cleaning.", "Python scripts", "Python code",
                        "Experience writing Python code is required."),
    "verb outside the list": ("Pipetted 96-well plates for the lab's ELISA assay.",
                              "Pipetted 96-well plates for the lab's ELISA test.", "ELISA assay", "ELISA test",
                              "Run the ELISA test on plates."),
}


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(ENGLISH_LINES))
def test_an_english_lines_relabel_still_reaches_the_review(opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite, source, term, anchor = ENGLISH_LINES[name]
    shown, seen = run(opportunity, monkeypatch, path, original, _relabel_row(rewrite, source, term), anchor)
    assert rewrite in seen and rewrite in shown, (shown, seen)


@pytest.mark.parametrize(("line", "source", "target", "english"), [
    ("Built a data pipeline in Python.", "data pipeline", "ETL pipeline", True),
    ("Independently built a data pipeline for the lab.", "data pipeline", "ETL pipeline", True),
    ("Wiring 3 soil sensors to an Arduino logger.", "Arduino logger", "data logger", True),  # "-ing" lead
    ("Responsible for writing Python scripts for data cleaning.", "Python scripts", "Python code", True),  # verb, "for"
    ("Wired the sensors for the senior project.", "senior project", "capstone project", True),  # "-ed" lead
    ("Ran EEG simulations overnight.", "EEG simulations", "EEG models", True),  # a résumé verb leads
    ("Core contributor to the library and the lab wiki.", "lab wiki", "lab website", True),  # "the" and "and"
    # A corpus pair whose declared relabel holds the verb: "to" keeps "Programmed".
    ("Programmed a drone to follow a GPS route in the robotics club.", "Programmed a drone",
     "Programmed an unmanned aerial vehicle", True),
    ("Disene un sistema de control para 40 sensores.", "sistema de control", "control system", False),
    ("Desarrollo un sistema de control para 40 sensores.", "sistema", "system", False),  # "control" alone outside
    ("Control de calidad para 40 sensores.", "Control de calidad", "Quality control", False),  # kept verb alone
    ("Il a construit un pipeline de mesures on the side.", "pipeline de mesures", "measurement pipeline", False),
    ("Entwickelte ein Python Skript fuer 40 Sensoren im Labor.", "Python Skript", "Python script", False),
    ("Membangun model regresi untuk data sensor dari 40 lahan.", "regresi", "regression", False),  # "model" alone
    ("", "data pipeline", "ETL pipeline", False),
    # Known residual: a foreign line that leads with a word English résumés use as a verb, or holds one
    # beside an English function word, reads as English (no list may tell "Test" or "Plan" apart).
    pytest.param("Test der Sensoren in Python fuer das Labor.", "Sensoren", "sensors", False,
                 marks=pytest.mark.xfail(strict=True, reason="lead word is an English résumé verb form")),
    pytest.param("Plan de control para el laboratorio de suelos.", "laboratorio de suelos", "soil lab", False,
                 marks=pytest.mark.xfail(strict=True, reason="two English résumé verb forms outside the phrase")),
])
def test_a_line_reads_as_english_around_a_relabel_only_with_english_words_outside_it(line, source, target, english):
    assert em._english_line(line, source, target) is english


# Two cases the re-verification found no test for (a6979522 passes them): an accented word outside the
# phrase decides an otherwise English line (M9: "not accented" in _english_around), and one English
# function word is too little ("len(function) >= 2"). Each fails when its condition is dropped.
@pytest.mark.parametrize(("source", "target", "line", "kept"), [
    ("café inventory", "coffee shop inventory", "Tracked café inventory for the Montréal office.", False),
    ("café inventory", "coffee shop inventory", "Tracked café inventory for weeks.", False),
    ("café inventory", "coffee shop inventory", "Tracked café inventory for the campus office.", True),
])
def test_an_accented_relabel_needs_an_english_line_with_no_other_accented_word(source, target, line, kept):
    assert em._accents_kept(source, target, line) is kept
