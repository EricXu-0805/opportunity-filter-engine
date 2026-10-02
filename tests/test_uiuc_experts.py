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


def test_refresh_targets_configured_departments(monkeypatch, tmp_path):
    import json
    p = tmp_path / "opps.json"
    p.write_text(json.dumps([{"pi_name": "X", "department": "Department of Physics",
                              "source": "uiuc_faculty", "source_type": "faculty_research",
                              "keywords": ["physics"]}]))
    seen = {}

    def fake_enrich(records, departments, fetch=None, deadline=None, order_key=""):
        seen["departments"] = departments
        return []  # nothing enriched -> no merge/write path

    monkeypatch.setattr(e, "enrich", fake_enrich)
    assert e.refresh(str(p)) == 0
    # the expanded target set folds in both the ACES cohort and the STEM departments
    assert {"Department of Animal Sciences", "Department of Physics",
            "Department of Economics"} <= seen["departments"]


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


def _broad(name: str) -> dict:
    return {"id": name, "pi_name": name, "department": "Department of Physics",
            "keywords": ["physics"]}


def test_enrich_stops_at_the_deadline():
    """7,045 broad-only faculty on 2026-10-01 at ~1s each: the pass cannot
    finish inside the refresh job, so it stops at its budget."""
    asked: list[str] = []
    out = e.enrich([_broad("Ada Lovelace"), _broad("Alan Turing")],
                   {"Department of Physics"}, deadline=0.0,
                   fetch=lambda slug: asked.append(slug) or None)
    assert out == []
    assert asked == []


def test_enrich_takes_targets_in_a_new_order_each_month():
    """A page that 404s leaves its record broad, so a fixed order would spend
    every month's budget on the same unresolvable names."""
    names = [f"{first} {last}" for first in ("Ada", "Alan", "Grace", "Edsger")
             for last in ("Lovelace", "Turing", "Hopper")]

    def order(key):
        asked: list[str] = []
        e.enrich([_broad(n) for n in names], {"Department of Physics"},
                 order_key=key, fetch=lambda slug: asked.append(slug) or None)
        return asked

    assert order("2026-10") == order("2026-10")
    assert order("2026-10") != order("2026-11")
    assert sorted(order("2026-10")) == sorted(order("2026-11"))


def test_refresh_passes_its_budget_and_the_month(monkeypatch, tmp_path):
    import json
    import time

    p = tmp_path / "opps.json"
    p.write_text(json.dumps([_broad("Ada Lovelace")]))
    seen = {}

    def fake_enrich(records, departments, fetch=None, deadline=None, order_key=""):
        seen.update(deadline=deadline, order_key=order_key)
        return []

    monkeypatch.setattr(e, "enrich", fake_enrich)
    e.refresh(str(p), time_budget_minutes=30)
    assert time.monotonic() + 29 * 60 < seen["deadline"] <= time.monotonic() + 30 * 60
    assert len(seen["order_key"]) == 7 and seen["order_key"][4] == "-"

    e.refresh(str(p))
    assert seen["deadline"] is None
