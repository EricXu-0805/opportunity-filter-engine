"""Round-3 re-verification (3d) for acceptance criterion (3) of fix/tailor-review.

Provider-free: the generation and review calls are stubbed at
``chat_completion``. Each test probes a regression the re-verification of a6979522 reported, or a
guard it found no test for, and fails on a6979522; a test that pins a boundary a6979522 already
holds says so.

Round 4 moved extraction back to origin/main's and removed this file's extraction
probes; their résumés are cases of tests/fixtures/extraction_differential_cases.json,
which tests/test_extraction_matches_main.py runs against main.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths_r6.py -q
"""
from __future__ import annotations

import pytest

from backend.lib import evidence_map as em
from tests.test_rewrite_display_paths import (
    ALL_PATHS,
    opportunity,  # noqa: F401  (pytest fixture)
    run,
)
from tests.test_rewrite_display_paths_r5 import _relabel_row

EN = ["Ran 40 overnight EEG sessions with 20 participants", "Designed a sensor rig for the team",
      "Wrote a data logger in C for the club"]
ZH = ["搭建了校园农场的土壤湿度传感器网络", "为社团设计了一套传感器测试台", "用 C 语言为社团编写了数据记录程序"]


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
