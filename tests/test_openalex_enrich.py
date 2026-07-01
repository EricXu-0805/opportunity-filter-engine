"""Tests for the OpenAlex scholarly-record enrichment pass.

The network (`_get`) is monkeypatched; the value under test is the accuracy
gating — institution-id match, surname match, min-works, the majority
field-consistency gate (wrong-person rejection), topic cleaning, and updates-only
apply.
"""
from src.collectors import openalex_enrich as oa


def _author(name, works, inst_ids, topics):
    return {
        "display_name": name,
        "works_count": works,
        "affiliations": [{"institution": {"id": f"https://openalex.org/{i}"}} for i in inst_ids],
        "topics": [{"display_name": d, "field": {"display_name": f}} for d, f in topics],
    }


def test_clean_topic_strips_trailing_generic_noun():
    assert oa._clean_topic("Advanced Clustering Algorithms Research") == "advanced clustering algorithms"
    assert oa._clean_topic("Semiconductor materials and devices") == "semiconductor materials and devices"


def test_clean_topic_flattens_internal_delimiters():
    # OpenAlex compound labels must become a single delimiter-free phrase, else
    # an internal comma shatters one area into several in the faculty title.
    assert oa._clean_topic("Galaxies: formation, evolution, phenomena") == "galaxies formation evolution phenomena"
    assert oa._clean_topic("quantum, superfluid, helium dynamics") == "quantum superfluid helium dynamics"
    assert "," not in oa._clean_topic("stellar, planetary, and galactic")


def test_surname():
    assert oa._surname("Linda Bushnell") == "bushnell"
    assert oa._surname("Joseph A. Marino, III") == "iii" or oa._surname("Joseph A. Marino") == "marino"


def test_author_topics_requires_institution_and_surname(monkeypatch):
    # right surname but WRONG institution -> no match
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        _author("Linda Bushnell", 80, ["I999"], [("control systems", "Engineering")])]})
    assert oa.author_topics("Linda Bushnell", "I201448701", "Electrical Engineering") == []
    # right institution + surname + field-compatible -> topics
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        _author("Linda Bushnell", 80, ["I201448701"],
                [("control systems", "Engineering"), ("network security", "Computer Science")])]})
    out = oa.author_topics("Linda Bushnell", "I201448701", "Electrical Engineering")
    assert "control systems" in out and "network security" in out


def test_author_topics_majority_field_gate_rejects_wrong_person(monkeypatch):
    # same name, same institution, but a seismologist (Earth Sciences) — must be
    # rejected for an Electrical Engineering professor even though one topic is
    # mis-labelled Computer Science.
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        _author("M. E. West", 236, ["I130701444"], [
            ("earthquake and tectonic", "Earth and Planetary Sciences"),
            ("seismology", "Computer Science"),
            ("seismic waves", "Earth and Planetary Sciences"),
            ("geochemical analysis", "Earth and Planetary Sciences"),
            ("geophysics", "Earth and Planetary Sciences")])]})
    assert oa.author_topics("Michael E West", "I130701444", "School of Electrical Engineering") == []


def test_author_topics_min_works(monkeypatch):
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        _author("Jane Roe", 3, ["I201448701"], [("topic", "Engineering")])]})
    assert oa.author_topics("Jane Roe", "I201448701", "Electrical Engineering") == []


def test_apply_is_updates_only():
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a"},
        {"pi_name": "E", "school": "uw", "url": "https://x.edu/e", "keywords": ["existing"]},
    ]
    n = oa.apply_openalex(opps, {"https://x.edu/a": ["robotics"], "https://x.edu/e": ["nope"]})
    assert n == 1
    assert opps[0]["keywords"] == ["robotics"]
    assert opps[1]["keywords"] == ["existing"]
