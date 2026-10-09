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
    _rewrite,
    opportunity,  # noqa: F401  (pytest fixture)
    run,
)
from tests.test_rewrite_display_paths_r5 import _relabel_row

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


# ------------------------------------------------------------------ criterion (3), round 4: the default keep
# The owner made criterion (3) default-keep: a rewrite of a Latin-script line is shown only when the line
# carries positive English evidence that nominal German, French, Dutch, Scandinavian, Italian, Spanish or
# Indonesian lines do not supply: two English function words of three letters or more outside the renamed
# phrase (_english_line). a27e84d6 read a line as English when it led with a word English résumés use as
# a verb ("Test", "Support") or held one beside a function word of any length, and asked nothing of a
# rewrite with no relabel: a reorder that joins a line's clauses with English "and" reached the review on
# every route and was shown. Each case below reaches the review on a27e84d6 (its review accepts) and is
# kept now, before the review.
def _lead_row(rewrite, phrase):
    return _rewrite(rewrite, [{"op": "lead_with", "link": "L1"}],
                    [{"id": "L1", "anchor": "t1", "term": phrase, "source": phrase, "relation": "same"}])


NOMINAL_LINES = {  # name: (original, rewrite, row, anchor)
    "german relabel": ("Test eines Python Skripts fuer 40 Sensoren im Labor.",
                       "Test eines Python scripts fuer 40 Sensoren im Labor.", ("Python Skripts", "Python scripts"),
                       "Write Python scripts for sensor data."),
    "german reorder": ("Aufbau einer Messdatenbank in Python, Auswertung der Daten fuer 40 Sensoren.",
                       "Auswertung der Daten fuer 40 Sensoren and Aufbau einer Messdatenbank in Python.",
                       "Auswertung der Daten", "Auswertung der Daten"),
    "french relabel": ("Support technique du pipeline de mesures pour 40 parcelles.",
                       "Support technique du measurement pipeline pour 40 parcelles.",
                       ("pipeline de mesures", "measurement pipeline"), "Maintain the measurement pipeline for field plots."),
    "french reorder": ("Conception d'un pipeline de mesures en Python, analyse des données de 40 capteurs.",
                       "Analyse des données de 40 capteurs and conception d'un pipeline de mesures en Python.",
                       "analyse des données", "analyse des données"),
    "dutch relabel": ("Test van een Python programma voor 40 sensoren.", "Test van een Python code voor 40 sensoren.",
                      ("Python programma", "Python code"), "Write Python code for sensor data."),
    "dutch reorder": ("Opbouw van een database in Python, analyse van meetgegevens voor 40 sensoren.",
                      "Analyse van meetgegevens voor 40 sensoren and opbouw van een database in Python.",
                      "analyse van meetgegevens", "analyse van meetgegevens"),
    "swedish relabel": ("Test av ett Python skript för 40 jordprover.", "Test av ett Python script för 40 jordprover.",
                        ("Python skript", "Python script"), "Write a Python script for sensor data."),
    "swedish reorder": ("Uppbyggnad av en databas i Python, analys av sensordata för 40 jordprover.",
                        "Analys av sensordata för 40 jordprover and uppbyggnad av en databas i Python.",
                        "analys av sensordata", "analys av sensordata"),
    "norwegian relabel": ("Test av et Python skript for 40 jordprøver.", "Test av et Python script for 40 jordprøver.",
                          ("Python skript", "Python script"), "Write a Python script for sensor data."),
    "norwegian reorder": ("Oppbygging av en database i Python, analyse av sensordata for 40 jordprøver.",
                          "Analyse av sensordata for 40 jordprøver and oppbygging av en database i Python.",
                          "analyse av sensordata", "analyse av sensordata"),
    "italian relabel": ("Test della pipeline di dati in Python per 40 sensori.",
                        "Test della data pipeline in Python per 40 sensori.", ("pipeline di dati", "data pipeline"),
                        "Build a data pipeline in Python."),
    "italian reorder": ("Sviluppo di una pipeline di dati in Python, analisi dei campioni per 40 sensori.",
                        "Analisi dei campioni per 40 sensori and sviluppo di una pipeline di dati in Python.",
                        "analisi dei campioni", "analisi dei campioni"),
    "spanish relabel": ("Test del sistema de control para 40 sensores.", "Test del control system para 40 sensores.",
                        ("sistema de control", "control system"), "Build a control system for lab sensors."),
    "spanish reorder": ("Analisis de datos en Python, sistema de control para 40 sensores.",
                        "Sistema de control para 40 sensores and analisis de datos en Python.",
                        "sistema de control", "sistema de control"),
    "indonesian relabel": ("Test model regresi untuk data sensor dari 40 lahan.",
                           "Test regression model untuk data sensor dari 40 lahan.", ("model regresi", "regression model"),
                           "Fit a regression model to sensor data."),
    "indonesian reorder": ("Pembuatan model regresi dalam Python, analisis data sensor untuk 40 lahan.",
                           "Analisis data sensor untuk 40 lahan and pembuatan model regresi dalam Python.",
                           "analisis data sensor", "analisis data sensor"),
}


def _nominal_row(name):
    original, rewrite, move, anchor = NOMINAL_LINES[name]
    row = _relabel_row(rewrite, *move) if isinstance(move, tuple) else _lead_row(rewrite, move)
    return original, rewrite, row, anchor


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(NOMINAL_LINES))
def test_a_nominal_line_in_another_latin_script_language_is_kept_as_written(
        opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite, row, anchor = _nominal_row(name)
    shown, seen = run(opportunity, monkeypatch, path, original, row, anchor)
    assert (shown, seen) == ([], set())


@pytest.mark.parametrize("name", list(NOMINAL_LINES))
def test_the_contract_keeps_a_nominal_line_as_english_unproven(name):
    original, rewrite, row, anchor = _nominal_row(name)
    anchors = {"t1": em.Anchor("t1", {"field": "description", "requirement_index": None, "start": 0,
                                      "end": len(anchor), "quote": anchor})}
    outcome = em.check_rewrite(em.Unit("b1", original, original), {"unit_id": "b1", **row}, anchors,
                               output_language=em.language(original))
    assert (outcome.status, outcome.code, outcome.detail) == ("kept", "beyond_allowed_edit", "english_unproven")


# An English line with the evidence still reaches the review on every route; one without it is kept as
# written, a lost suggestion (scripts/english_evidence_keeps.py counts them over the repository's samples).
ENGLISH_LINES = {
    "lead verb": ("Built a data pipeline in Python for the lab's 40 sensors.",
                  "Built an ETL pipeline in Python for the lab's 40 sensors.",
                  "data pipeline", "ETL pipeline", "Maintain the ETL pipeline in Python."),
    "role noun first": ("Responsible for writing Python scripts for data cleaning in the lab.",
                        "Responsible for writing Python code for data cleaning in the lab.", "Python scripts",
                        "Python code", "Experience writing Python code is required."),
    "verb outside the list": ("Pipetted 96-well plates for the lab's ELISA assay.",
                              "Pipetted 96-well plates for the lab's ELISA test.", "ELISA assay", "ELISA test",
                              "Run the ELISA test on plates."),
}
ENGLISH_KEEPS = {
    "one function word of three letters": ("Built a data pipeline in Python for 40 sensors.",
                                           "Built an ETL pipeline in Python for 40 sensors.", "data pipeline",
                                           "ETL pipeline", "Maintain the ETL pipeline in Python."),
    "the same word twice": ("Responsible for writing Python scripts for data cleaning.",
                            "Responsible for writing Python code for data cleaning.", "Python scripts", "Python code",
                            "Experience writing Python code is required."),
    "the evidence inside the renamed phrase": ("Ran sims for the lab.", "Ran simulations for the lab.",
                                               "sims for the lab", "simulations for the lab",
                                               "Run simulations for the lab."),
}


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(ENGLISH_LINES))
def test_an_english_lines_relabel_still_reaches_the_review(opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite, source, term, anchor = ENGLISH_LINES[name]
    shown, seen = run(opportunity, monkeypatch, path, original, _relabel_row(rewrite, source, term), anchor)
    assert rewrite in seen and rewrite in shown, (shown, seen)


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("name", list(ENGLISH_KEEPS))
def test_an_english_line_without_the_evidence_is_kept_as_written(opportunity, monkeypatch, path, name):  # noqa: F811
    original, rewrite, source, term, anchor = ENGLISH_KEEPS[name]
    shown, seen = run(opportunity, monkeypatch, path, original, _relabel_row(rewrite, source, term), anchor)
    assert (shown, seen) == ([], set())


@pytest.mark.parametrize(("line", "renamed", "english"), [
    ("Independently built a data pipeline for the lab.", ["data pipeline"], True),
    ("Wired the sensors for the senior project.", ["senior project"], True),
    ("Core contributor to the library and the lab wiki.", ["lab wiki"], True),
    ("Cleaned the survey data and made the figures.", [], True),                    # a reorder renames nothing
    ("Built the data pipeline and the lab wiki.", ["data pipeline", "lab wiki"], True),
    ("THE PARSER AND THE TESTS", [], True),                                          # read in any case
    # Without two such words, whatever the verbs: verb forms are no evidence (round 4).
    ("Built a data pipeline in Python.", ["data pipeline"], False),                   # "in", "a": two letters
    ("Wiring 3 soil sensors to an Arduino logger.", ["Arduino logger"], False),
    ("Responsible for writing Python scripts for data cleaning.", ["Python scripts"], False),  # "for" twice
    ("Ran EEG simulations overnight.", ["EEG simulations"], False),
    ("Programmed a drone to follow a GPS route in the robotics club.", ["Programmed a drone"], False),
    ("Wrote the code for the lab.", ["the code for the lab"], False),               # inside the renamed phrase
    ("Built the data pipeline.", ["data pipeline", "lab wiki"], False),             # a phrase not in the line
    ("", ["data pipeline"], False),
    # Nominal lines in other Latin-script languages, with and without accents.
    ("Disene un sistema de control para 40 sensores.", ["sistema de control"], False),
    ("Control de calidad para 40 sensores.", ["Control de calidad"], False),
    ("Il a construit un pipeline de mesures on the side.", ["pipeline de mesures"], False),  # "the" only
    ("Entwickelte ein Python Skript fuer 40 Sensoren im Labor.", ["Python Skript"], False),
    ("Membangun model regresi untuk data sensor dari 40 lahan.", ["regresi"], False),
    ("Test der Sensoren in Python fuer das Labor.", ["Sensoren"], False),            # a27e84d6's residual
    ("Plan de control para el laboratorio de suelos.", ["laboratorio de suelos"], False),  # a27e84d6's residual
    ("Insamling av data för 40 sensorer via appen.", [], False),                    # "för" is not "for"
    ("Opbouw van een database, het meten van 40 sensoren.", [], False),
    # Residual: a line in another language that holds two of these words supplies the evidence.
    pytest.param("Datainnsamling via sensorer for jordfuktighet i 40 felt.", [], False,
                 marks=pytest.mark.xfail(strict=True, reason='Norwegian "for" and "via" are English function words')),
    pytest.param("Was ist ein Datenbankschema, also die Struktur der Messwerte.", [], False,
                 marks=pytest.mark.xfail(strict=True, reason='German "was" and "also" are English function words')),
])
def test_a_line_shows_itself_english_only_with_two_function_words_outside_the_renamed_phrases(line, renamed, english):
    assert em._english_line(line, renamed) is english


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
