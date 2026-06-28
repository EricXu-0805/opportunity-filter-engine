"""Tests for the Illinois Experts enricher. Network is injected via ``fetch``;
the value is in slug/name handling, the same-person safeguard, clean concept
extraction, and enriching only broad-field-only records."""
from __future__ import annotations

from bs4 import BeautifulSoup

import src.collectors.uiuc_experts as e


def _page(name: str, concepts: list[str]) -> BeautifulSoup:
    badges = "".join(
        f'<button class="concept-badge-large"><span class="concept-wrapper">'
        f'<span class="concept">{c}</span><span class="thesauri">Agriculture</span>'
        f'<span class="value sr-only">90%</span></span></button>'
        for c in concepts
    )
    return BeautifulSoup(f"<html><body><h1>{name}</h1>{badges}</body></html>", "html.parser")


def test_name_parts_strips_title_noise_and_middle():
    assert e._name_parts("Andrea Aguiar Research Associate Professor") == ("Andrea", "Aguiar")
    assert e._name_parts("Ryan N. Dilger") == ("Ryan", "Dilger")
    assert e._name_parts("José Andino Martinez") == ("Jose", "Martinez")  # deaccented


def test_concepts_extracts_clean_names_only():
    soup = _page("Robert Knox", ["Estrus", "Gilts", "Sows"])
    assert e._concepts(soup) == ["Estrus", "Gilts", "Sows"]  # no "Agriculture"/"90%"


def test_name_confirms_matches_same_person():
    soup = _page("Robert V. Knox", [])
    assert e._name_confirms(soup, "Robert", "Knox")


def test_name_confirms_rejects_same_last_different_person():
    soup = _page("Steven Knox", [])  # same last, different first initial
    assert not e._name_confirms(soup, "Robert", "Knox")


def test_experts_concepts_verified_person_returns_concepts():
    assert e.experts_concepts(
        "Robert V. Knox",
        fetch=lambda slug: _page("Robert Knox", ["Estrus", "Ovulation"]),
    ) == ["Estrus", "Ovulation"]


def test_experts_concepts_wrong_person_returns_empty():
    # same last name, different first initial -> not confirmed
    assert e.experts_concepts(
        "Robert Knox", fetch=lambda slug: _page("Someone Else", ["Estrus"])
    ) == []


def test_experts_concepts_404_returns_empty():
    assert e.experts_concepts("Robert Knox", fetch=lambda slug: None) == []


def test_enrich_only_touches_broad_only_in_target_depts():
    records = [
        {"pi_name": "Robert Knox", "department": "Department of Animal Sciences",
         "keywords": ["animal sciences"]},                       # broad-only, in-dept -> enrich
        {"pi_name": "Anna Dilger", "department": "Department of Animal Sciences",
         "keywords": ["Pork Quality", "Meat Science"]},          # already specific -> skip
        {"pi_name": "Jane Doe", "department": "Department of Physics",
         "keywords": ["physics"]},                               # out of target depts -> skip
    ]
    out = e.enrich(records, {"Department of Animal Sciences"},
                   fetch=lambda slug: _page("Robert Knox", ["Estrus", "Gilts", "Sows"]))
    assert len(out) == 1
    assert out[0]["pi_name"] == "Robert Knox"
    assert out[0]["keywords"] == ["Estrus", "Gilts", "Sows"]
    assert out[0]["research_areas"] == "Estrus; Gilts; Sows"
