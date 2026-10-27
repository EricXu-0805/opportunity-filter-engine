"""Tests for the Illinois Experts enricher. Network is injected via ``fetch``;
the value is in slug/name handling, the same-person safeguard, clean concept
extraction, and enriching only broad-field-only UIUC records."""
from __future__ import annotations

import base64

from bs4 import BeautifulSoup

import src.collectors.uiuc_experts as e
from src.evidence import inferred_method, keywords_are_source_topics


def _page(name: str, concepts: list[str], emails: tuple[str, ...] = (),
          units: tuple[str, ...] = ()) -> BeautifulSoup:
    """A person page in Pure's markup: positions, contact addresses (base64
    "mailto:" in ``data-md5``), fingerprint badges."""
    badges = "".join(
        f'<button class="concept-badge-large"><span class="concept-wrapper">'
        f'<span class="concept">{c}</span><span class="thesauri">Agriculture</span>'
        f'<span class="value sr-only">90%</span></span></button>'
        for c in concepts
    )
    positions = "".join(
        f'<li><span class="job-title">Professor</span>'
        f'<a rel="Organisation" class="link department" href="#">{u}</a></li>'
        for u in units
    )
    mails = "".join(
        f'<li class="emails"><a class="email" href="#" '
        f'data-md5="{base64.b64encode(f"mailto:{m}".encode()).decode()}">x</a></li>'
        for m in emails
    )
    return BeautifulSoup(
        f"<html><body><h1>{name}</h1>"
        f'<div class="rendering_personorganisationlistrendererportal"><ul>{positions}</ul></div>'
        f'<div class="rendering_personorganisationcontactrendererportal"><ul>{mails}</ul></div>'
        f"{badges}</body></html>",
        "html.parser",
    )


def _row(name: str, email: str = "", department: str = "Department of Animal Sciences",
         **fields) -> dict:
    return {"id": name, "pi_name": name, "department": department, "source": "uiuc_faculty",
            "school": "uiuc", "contact_email": email, "keywords": ["animal sciences"],
            "metadata": {"is_active": True}, **fields}


def test_name_parts_strips_title_noise_and_middle():
    assert e._name_parts("Andrea Aguiar Research Associate Professor") == ("Andrea", "Aguiar")
    assert e._name_parts("Ryan N. Dilger") == ("Ryan", "Dilger")
    assert e._name_parts("José Andino Martinez") == ("Jose", "Martinez")  # deaccented


def test_concepts_extracts_clean_names_only():
    soup = _page("Robert Knox", ["Estrus", "Gilts", "Sows"])
    assert e._concepts(soup) == ["Estrus", "Gilts", "Sows"]  # no "Agriculture"/"90%"


def test_concepts_keep_one_case_of_a_name_and_drop_what_the_corpus_gate_rejects():
    # Pure lists a concept once per thesaurus; the corpus gate rejects a
    # keyword list with a case-only repeat, junk such as a dangling "A", a bare
    # generic word and a "such as" lead-in. A comma would split the name in
    # every comma-joined keyword list.
    soup = _page("Robert Knox", ["Direct Numerical Simulation", "Direct numerical Simulation",
                                 "Bisphenol A", "4,4'-isopropylidenediphenol", "Research",
                                 "Such as Speech", "Turbulence"])
    assert e._concepts(soup) == ["Direct Numerical Simulation", "Turbulence"]


def test_page_emails_read_the_encoded_attribute_and_skip_anything_else():
    soup = _page("Robert Knox", [], emails=("RKnox@Illinois.edu",))
    contact = soup.select_one("li.emails")
    for value in ("not base64!", base64.b64encode(b"tel:2175550100").decode(),
                  base64.b64encode(b"mailto:rknox@illinois.edu").decode() + " "):
        contact.append(soup.new_tag("a", attrs={"class": "email", "data-md5": value}))
    assert e._page_emails(soup) == {"rknox@illinois.edu"}


def test_lookups_use_the_canonical_url(monkeypatch):
    asked: list[str] = []

    class Gone:
        status_code = 404

    monkeypatch.setattr(e.requests, "get", lambda url, **kw: asked.append(url) or Gone())
    assert e._fetch("robert-knox") is None
    assert asked == ["https://experts.illinois.edu/en/persons/robert-knox/"]


def test_lookups_keep_the_sites_crawl_delay(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(e, "_fetch", lambda slug: None)
    monkeypatch.setattr(e.time, "sleep", slept.append)
    e.enrich([_broad("Ada Lovelace"), _broad("Alan Turing")], {"Department of Physics"})
    assert slept == [5.0]


def test_unit_names_compare_as_pure_writes_them():
    assert e._unit_key("Department of Animal Sciences") == e._unit_key("Animal Sciences")
    assert e._unit_key("Food Science & Human Nutrition") == e._unit_key("Food Science and Human Nutrition")
    assert e._unit_key("Department of Physics") != e._unit_key("Department of Astronomy")


def test_the_same_address_is_the_same_person():
    soup = _page("Robert V. Knox", [], emails=("rknox@illinois.edu",), units=("Animal Sciences",))
    assert e._same_person(soup, _row("Robert Knox", email="RKnox@illinois.edu"))


def test_another_address_is_another_person_whatever_the_name_and_unit():
    # M161: a bare slug redirected a NRES professor's lookup to a namesake in
    # business; the name matched, the address did not.
    soup = _page("Robert Knox", [], emails=("rknox2@illinois.edu",), units=("Animal Sciences",))
    assert not e._same_person(soup, _row("Robert Knox", email="rknox@illinois.edu"))
    other_domain = _page("Robert Knox", [], emails=("rknox@gmail.com",), units=("Animal Sciences",))
    assert not e._same_person(other_domain, _row("Robert Knox", email="rknox@illinois.edu"))


def test_a_row_with_an_address_needs_it_on_the_page():
    # A page that states no address cannot confirm a row that has one, however
    # well the name and unit agree: a namesake in the same unit would pass.
    page = _page("Robert V. Knox", [], units=("Animal Sciences",))
    assert not e._same_person(page, _row("Robert Knox", email="rknox@illinois.edu"))


def test_without_an_address_the_unit_and_the_full_name_decide():
    units = ("Animal Sciences", "Carl R. Woese Institute for Genomic Biology")
    for page in (_page("Robert V. Knox", [], units=units),
                 _page("Robert V. Knox", [], emails=("rknox@illinois.edu",), units=units)):
        assert e._same_person(page, _row("Robert Knox"))
        assert not e._same_person(page, _row("Robert Knox", department="Department of Physics"))
        assert not e._same_person(page, _row("Rachel Knox"))  # same initial, another first name
        assert not e._same_person(page, _row("Robert Fox"))   # same first name, another last
    assert not e._same_person(_page("Robert V. Knox", []), _row("Robert Knox"))  # no positions
    assert e._same_person(_page("José Andino Martínez", [], units=units), _row("Jose Martinez"))


def test_experts_concepts_verified_person_returns_concepts():
    assert e.experts_concepts(
        _row("Robert V. Knox", email="rknox@illinois.edu"),
        fetch=lambda slug: _page("Robert Knox", ["Estrus", "Ovulation"], emails=("rknox@illinois.edu",)),
    ) == ["Estrus", "Ovulation"]


def test_experts_concepts_wrong_person_returns_empty():
    assert e.experts_concepts(
        _row("Robert Knox", email="rknox@illinois.edu"),
        fetch=lambda slug: _page("Robert Knox", ["Estrus"], emails=("someone.else@illinois.edu",)),
    ) == []


def test_experts_concepts_404_returns_empty():
    assert e.experts_concepts(_row("Robert Knox"), fetch=lambda slug: None) == []


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


def _knox_page(slug):
    return _page("Robert Knox", ["Estrus", "Gilts", "Sows"], emails=("rknox@illinois.edu",))


def test_enrich_only_touches_broad_only_in_target_depts():
    asked: list[str] = []
    records = [
        _row("Robert Knox", email="rknox@illinois.edu"),                   # broad-only, in-dept -> enrich
        _row("Anna Dilger", keywords=["Pork Quality", "Meat Science"]),     # already specific -> skip
        _row("Jane Doe", department="Department of Physics", keywords=["physics"]),  # out of target depts
    ]
    out = e.enrich(records, {"Department of Animal Sciences"},
                   fetch=lambda slug: asked.append(slug) or _knox_page(slug))
    assert asked == ["robert-knox"]
    assert len(out) == 1
    assert out[0]["pi_name"] == "Robert Knox"
    assert out[0]["keywords"] == ["Estrus", "Gilts", "Sows"]


def test_enriched_concepts_are_stamped_and_never_research_text():
    # M161: they are Elsevier's reading of the person's papers; unstamped, the
    # detail page and the email called them the professor's own research.
    # 284 stored rows carry this exact method.
    assert e.CONCEPTS_METHOD == "derived:illinois_experts_concepts"
    row = _row("Robert Knox", email="rknox@illinois.edu",
               metadata={"is_active": True, "inferred_fields": {"paid": "rule:federal_org"}})
    [out] = e.enrich([row], {"Department of Animal Sciences"}, fetch=_knox_page)
    assert inferred_method(out, "keywords") == e.CONCEPTS_METHOD
    assert not keywords_are_source_topics(out)
    assert "research_areas" not in out
    assert out["metadata"].get("research_areas_raw") is None
    # the stored row is not stamped in passing
    assert row["metadata"] == {"is_active": True, "inferred_fields": {"paid": "rule:federal_org"}}
    assert row["keywords"] == ["animal sciences"]


def test_enrich_never_looks_up_another_schools_row():
    # Two University of Chicago physics rows got UIUC people's concepts: the
    # target list matched department names, which every school shares.
    asked: list[str] = []
    other = {**_row("Robert Knox", email="rknox@uchicago.edu", department="Department of Physics"),
             "source": "faculty_graph", "school": "uchicago", "keywords": ["physics"]}
    out = e.enrich([other], {"Department of Physics"},
                   fetch=lambda slug: asked.append(slug) or _knox_page(slug))
    assert out == []
    assert asked == []


def test_enrich_skips_rows_no_longer_listed():
    asked: list[str] = []
    gone = _row("Robert Knox", email="rknox@illinois.edu", metadata={"is_active": False})
    assert e.enrich([gone], {"Department of Animal Sciences"},
                    fetch=lambda slug: asked.append(slug) or _knox_page(slug)) == []
    assert asked == []


def test_the_stamp_survives_the_merge_and_the_next_directory_rescrape(tmp_path):
    """The concepts and their stamp land on the stored row; the weekly scrape
    then brings the same person back with only the broad field, and the merge
    keeps the concepts with the stamp, not as stated topics."""
    import copy
    import json

    from src.collectors.uiuc_faculty import DEPARTMENTS, merge_into_processed, normalize_faculty

    def scrape():
        return normalize_faculty(
            {"name": "Ada Example", "title": "Professor", "email": "aexample@illinois.edu",
             "url": "https://physics.illinois.edu/people/directory/profile/aexample"},
            DEPARTMENTS["physics"],
        )

    stored = {**scrape(), "school": "uiuc"}
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps([stored]), encoding="utf-8")
    page = _page("Ada Example", ["Ultracold Atoms", "Optical Lattices"], emails=("aexample@illinois.edu",))

    enriched = e.enrich([copy.deepcopy(stored)], {"Department of Physics"}, fetch=lambda slug: page)
    merge_into_processed(enriched, filepath=str(path))
    [saved] = json.loads(path.read_text(encoding="utf-8"))
    assert saved["keywords"] == ["Ultracold Atoms", "Optical Lattices"]
    assert inferred_method(saved, "keywords") == e.CONCEPTS_METHOD
    assert "research_areas" not in saved

    merge_into_processed([scrape()], filepath=str(path))
    [saved] = json.loads(path.read_text(encoding="utf-8"))
    assert saved["keywords"] == ["Ultracold Atoms", "Optical Lattices"]
    assert inferred_method(saved, "keywords") == e.CONCEPTS_METHOD
    # The stored title and description built from the keywords do not say them.
    assert "Ultracold" not in saved["title"] + saved["description_clean"] + saved["description_raw"]


def _broad(name: str) -> dict:
    return {"id": name, "pi_name": name, "department": "Department of Physics",
            "source": "uiuc_faculty", "keywords": ["physics"]}


def test_enrich_stops_at_the_deadline():
    """268 UIUC targets on 2026-10-27 at 5 s each fill most of the 30-minute
    budget; a pass that cannot finish stops at its budget."""
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
