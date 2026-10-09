"""Department-level capture and per-person profile links (backlog D23).

Two coarse spots in the faculty corpus, both fixed in the collector configs so
the data changes through the normal refresh:

* JHU School of Medicine and Northwestern's Feinberg School of Medicine landed
  every professor under the school umbrella although their committed seeds
  already carry the department; ``json_dir`` now reads it, keeping only names on
  the school's own department list and falling back to the umbrella otherwise.
* Six schools (UCR, ASU, UF, Iowa, Houston, Utah) stored the department's
  directory page as the profile link of every professor whose feed or card had
  no link. ``json_dir`` gained ``link_template`` / ``link_rewrite`` for feeds that
  carry a person id but no absolute URL, and the scrape units gained link
  selectors.

Fixtures under ``tests/fixtures/school_department_capture`` are trimmed copies
of the live pages and feeds (2026-10-09), with names and addresses replaced.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from src.collectors import faculty_graph as fg

FIXTURES = Path(__file__).parent / "fixtures" / "school_department_capture"


def _feed(monkeypatch, payload):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())


# --- engine: json_dir link_template / link_rewrite ---------------------------

class TestJsonDirLinkTemplate:
    def test_template_builds_a_per_person_url_from_record_fields(self, monkeypatch):
        _feed(monkeypatch, [{"name": "Ada Byron", "title": "Professor",
                             "ids": {"net": "ada b"}}])
        people = fg._fetch_json_dir({"short": "X", "json_dir": {
            "url": "https://feed.example.edu/api", "name_fields": ["name"],
            "link_template": "https://profiles.example.edu/p/{ids.net}"}})
        # Dotted path, and the value is quoted so it cannot add path segments.
        assert people[0]["url"] == "https://profiles.example.edu/p/ada%20b"

    def test_link_field_value_wins_over_the_template(self, monkeypatch):
        _feed(monkeypatch, [
            {"name": "Ada Byron", "id": "1", "site": "https://ada.example.org/"},
            {"name": "Bob Lee", "id": "2", "site": None},
        ])
        people = fg._fetch_json_dir({"short": "X", "json_dir": {
            "url": "https://feed.example.edu/api", "name_fields": ["name"],
            "link_field": "site",
            "link_template": "https://dir.example.edu/profile/{id}"}})
        assert [p["url"] for p in people] == [
            "https://ada.example.org/", "https://dir.example.edu/profile/2"]

    def test_missing_template_field_leaves_the_link_empty(self, monkeypatch):
        _feed(monkeypatch, [{"name": "Ada Byron", "id": ""},
                            {"name": "Bob Lee"}])
        people = fg._fetch_json_dir({"short": "X", "json_dir": {
            "url": "https://feed.example.edu/api", "name_fields": ["name"],
            "link_template": "https://dir.example.edu/profile/{id}"}})
        # "" falls back to the directory URL in _normalize — never a half-built
        # ".../profile/" that would be shared by everyone without an id.
        assert [p["url"] for p in people] == ["", ""]

    def test_rewrite_maps_a_staging_link_to_the_public_host(self, monkeypatch):
        _feed(monkeypatch, [
            {"name": "Ada Byron", "link": "http://cop-a2.sites.example.edu/blog/profile/byron-ada/"},
            {"name": "Bob Lee", "link": "http://cop-a2.sites.example.edu/profile/lee-bob-1/"},
            {"name": "Cy Dee", "link": "http://cop-a2.sites.example.edu/blog/news/2020/"},
        ])
        people = fg._fetch_json_dir({"short": "X", "json_dir": {
            "url": "https://feed.example.edu/api", "name_fields": ["name"],
            "link_field": "link",
            "link_rewrite": [r"^https?://[^/]+(?:/blog)?/profile/([^/?#]+)/?$",
                             r"https://pharmacy.example.edu/profile/\1/"]}})
        # A link that does not have the profile shape is dropped, not kept: the
        # staging host is unreachable from outside the campus network.
        assert [p["url"] for p in people] == [
            "https://pharmacy.example.edu/profile/byron-ada/",
            "https://pharmacy.example.edu/profile/lee-bob-1/",
            ""]


# --- engine: json_dir department_field / department_units --------------------

_UNITS = {
    "prefix": "School of Medicine — ",
    "strip": r"^Clinical\s+",
    "names": ["Medicine", "Pediatrics", "Radiology and Radiological Science",
              "Neurology"],
    "aliases": {"Neurology - Davee Department": "Neurology"},
    "boundary": r"\s*$|\s*[(,]|\s+(?:Additional|Find)\b",
}


class TestJsonDirDepartment:
    def _people(self, monkeypatch, raws, units=_UNITS):
        _feed(monkeypatch, [{"name": f"Person {chr(65 + i)} Example", "dept": raw}
                            for i, raw in enumerate(raws)])
        cfg = {"url": "https://feed.example.edu/api", "name_fields": ["name"],
               "department_field": "dept"}
        if units is not None:
            cfg["department_units"] = units
        return fg._fetch_json_dir({"short": "X", "json_dir": cfg})

    def test_field_without_units_passes_the_value_through(self, monkeypatch):
        people = self._people(monkeypatch, ["Physics", None], units=None)
        assert [p["department"] for p in people] == ["Physics", ""]

    def test_a_listed_department_is_kept_with_the_school_prefix(self, monkeypatch):
        people = self._people(monkeypatch, [
            "School of Medicine — Pediatrics",
            "School of Medicine — Radiology and Radiological Science",
        ])
        assert [p["department"] for p in people] == [
            "School of Medicine — Pediatrics",
            "School of Medicine — Radiology and Radiological Science"]

    def test_clinical_rank_modifier_and_page_spillover_are_cut(self, monkeypatch):
        people = self._people(monkeypatch, [
            "School of Medicine — Clinical Pediatrics",
            "School of Medicine — Medicine Find a Clinical Trial",
            "School of Medicine — Neurology Additional Academic Titles",
            "School of Medicine — Medicine (General Internal Medicine) , Medica",
        ])
        assert [p["department"] for p in people] == [
            "School of Medicine — Pediatrics", "School of Medicine — Medicine",
            "School of Medicine — Neurology", "School of Medicine — Medicine"]

    def test_alias_maps_to_its_department(self, monkeypatch):
        people = self._people(monkeypatch, [
            "School of Medicine — Neurology - Davee Department"])
        assert people[0]["department"] == "School of Medicine — Neurology"

    def test_anything_else_falls_back_to_the_umbrella(self, monkeypatch):
        people = self._people(monkeypatch, [
            # Another institution's appointment, read off a biography.
            "School of Medicine — Medicine at Georgetown University",
            "School of Medicine — Radiology and Surgery at the",
            "School of Medicine — Medicine/Cardiology. He was the past",
            # Not on the list at all, and not this school.
            "School of Medicine — Strategy and Entrepreneurship",
            "Bloomberg School of Public Health",
        ])
        assert [p["department"] for p in people] == [""] * 5

    def test_a_value_without_the_school_prefix_is_not_trusted(self, monkeypatch):
        # Another school's row, or a seed regenerated in a different shape.
        # "School of Pharmacy — " is as long as the prefix, so cutting it off
        # unchecked would leave a listed name behind.
        people = self._people(monkeypatch, [
            "Pediatrics", "Medicine (Cardiology)", "School of Pharmacy — Pediatrics"])
        assert [p["department"] for p in people] == ["", "", ""]

    def test_the_longest_listed_name_wins(self, monkeypatch):
        units = {"prefix": "", "names": ["Radiology", "Radiology and Radiological Science"],
                 "boundary": r"\s*$|\s+\S"}
        people = self._people(monkeypatch, ["Radiology and Radiological Science Find"],
                              units=units)
        assert people[0]["department"] == "Radiology and Radiological Science"

    def test_umbrella_record_keeps_the_config_department(self, monkeypatch):
        people = self._people(monkeypatch, [
            "School of Medicine — Pediatrics",
            "School of Medicine — Pediatrics at the",
        ])
        school = {"school_slug": "x", "source": "x_faculty", "organization": "X U",
                  "location": "X", "id_prefix": "x"}
        dept = {"short": "SOM", "name": "School of Medicine", "majors": []}
        recs = [fg._normalize(school, dept, p) for p in people]
        assert [r["department"] for r in recs] == [
            "School of Medicine — Pediatrics", "School of Medicine"]
        # The unit stays the config short, so ids and the retirement ledger
        # do not move when the department label becomes finer.
        assert all(r["id"].startswith("faculty-x-som-") for r in recs)


# --- the finer labels must not hand the author gate a wrong field family -----

class TestDepartmentFieldFamily:
    """openalex_enrich._dept_fields scans substrings in order, so a clinical
    department named after "physical", "gynecology" or "reconstructive" fell
    into Physics ("physic"), Ecology ("ecolog") or Economics ("econ") — and the
    wrong-person gate then rejects the professor's real OpenAlex author. Under
    the old umbrella ("School of Medicine") all of them read as medicine."""

    @pytest.mark.parametrize("department", [
        "School of Medicine — Physical Medicine and Rehabilitation",
        "Feinberg School of Medicine — Physical Therapy and Human Movement Sciences",
        "Department of Physical Therapy",
        "School of Medicine — Gynecology and Obstetrics",
        "Feinberg School of Medicine — Obstetrics and Gynecology",
        "School of Medicine — Plastic and Reconstructive Surgery",
    ])
    def test_clinical_departments_keep_the_health_family(self, department):
        from src.collectors.openalex_enrich import _HEALTH, _dept_fields
        assert _dept_fields(department) == _HEALTH

    @pytest.mark.parametrize("department, field", [
        ("Department of Physics", "Physics and Astronomy"),
        ("Department of Physics and Astronomy", "Physics and Astronomy"),
        ("Department of Economics", "Economics, Econometrics and Finance"),
        ("Department of Ecology and Evolutionary Biology",
         "Agricultural and Biological Sciences"),
    ])
    def test_the_stems_they_collided_with_still_answer(self, department, field):
        from src.collectors.openalex_enrich import _dept_fields
        assert field in _dept_fields(department)

    @pytest.mark.parametrize("module_name, units_attr", [
        ("jhu_faculty", "_SOM_DEPARTMENTS"),
        ("northwestern_faculty", "_FEINBERG_DEPARTMENTS"),
    ])
    def test_every_medical_department_keeps_a_biomedical_field(self, module_name, units_attr):
        # The umbrella read as medicine; a finer label may narrow that family
        # but must not leave it with no biomedical field at all ("Biophysics
        # and Biophysical Chemistry" reads as Physics, so it is not listed).
        import importlib

        from src.collectors.openalex_enrich import _dept_fields
        units = getattr(importlib.import_module(f"src.collectors.schools.{module_name}"),
                        units_attr)
        biomedical = {"Medicine", "Biochemistry, Genetics and Molecular Biology"}
        labels = {units["prefix"] + n for n in units["names"]} | {
            units["prefix"] + n for n in units["aliases"].values()}
        assert not [label for label in sorted(labels)
                    if not (_dept_fields(label) or set()) & biomedical]


def _dept(module, short):
    return next(d for d in module.SCHOOL["departments"] if d["short"] == short)


def _fixture_json(name):
    return json.loads((FIXTURES / name).read_text())


# --- the two medical schools, on their committed seeds -----------------------

class TestMedicalSchoolDepartments:
    @pytest.mark.parametrize("module_name, short, umbrella, units_attr", [
        ("jhu_faculty", "SOM", "School of Medicine", "_SOM_DEPARTMENTS"),
        ("northwestern_faculty", "FEINBERG", "Feinberg School of Medicine",
         "_FEINBERG_DEPARTMENTS"),
    ])
    def test_seed_lands_at_department_level(self, module_name, short, umbrella, units_attr):
        import importlib
        module = importlib.import_module(f"src.collectors.schools.{module_name}")
        dept = _dept(module, short)
        records = [r for r in (fg._normalize(module.SCHOOL, dept, p)
                               for p in fg._fetch_json_dir(dept)) if r]
        departments = Counter(r["department"] for r in records)
        units = getattr(module, units_attr)
        allowed = {units["prefix"] + n for n in units["names"]} | {
            units["prefix"] + n for n in units["aliases"].values()} | {umbrella}
        assert set(departments) <= allowed
        # Before D23 every one of these records said only the school.
        assert departments[umbrella] < 0.05 * len(records)
        assert len(departments) > 20
        assert all(r["id"].startswith(f"faculty-{module.SCHOOL['id_prefix']}-{short.lower()}-")
                   for r in records)

    def test_jhu_title_text_from_another_institution_stays_umbrella(self):
        from src.collectors.schools import jhu_faculty
        units = jhu_faculty._SOM_DEPARTMENTS
        assert fg._json_department(
            "School of Medicine — Surgery, Georgetown University", units) == ""
        assert fg._json_department(
            "School of Medicine — Clinical Anesthesiology and Critical Care", units
        ) == "School of Medicine — Anesthesiology and Critical Care Medicine"
        assert fg._json_department(
            "School of Medicine — Pediatric Surgery", units) == "School of Medicine — Surgery"
        assert fg._json_department(
            "School of Medicine — Cardiac Surgery", units) == "School of Medicine — Surgery"
        assert fg._json_department(
            "School of Medicine — Biophysics and Biophysical Chemistry", units) == ""

    def test_feinberg_first_appointment_wins_without_its_division(self):
        from src.collectors.schools import northwestern_faculty
        units = northwestern_faculty._FEINBERG_DEPARTMENTS
        p = "Feinberg School of Medicine — "
        assert fg._json_department(
            p + "Medicine (General Internal Medicine) , Medica", units) == p + "Medicine"
        assert fg._json_department(
            p + "Pharmacology Research Associate Professor, We", units) == p + "Pharmacology"
        assert fg._json_department(
            p + "Neurology - Ken and Ruth Davee Department Pro", units) == p + "Neurology"
        assert fg._json_department(
            p + "Otolaryngology (Pediatric Otolaryngology", units
        ) == p + "Otolaryngology - Head and Neck Surgery"
        assert fg._json_department(
            p + "Robert H. Lurie Comprehensive Cancer Center", units) == ""


# --- collector configs on saved feeds: per-person links ----------------------

def _feed_urls(monkeypatch, module, short, fixture):
    _feed(monkeypatch, _fixture_json(fixture))
    return {p["name"]: p["url"] for p in fg._fetch_json_dir(_dept(module, short))}


class TestFeedProfileLinks:
    """Feeds that carry an id or slug, not a URL. Before D23 every one of these
    records stored the department's directory page as its profile link."""

    def test_ucr_profile_comes_from_the_net_id(self, monkeypatch):
        from src.collectors.schools import ucr_faculty
        assert _feed_urls(monkeypatch, ucr_faculty, "CS", "ucr_profile_api.json") == {
            "Ada Example": "https://profiles.ucr.edu/app/home/profile/adaexam",
            "Bo Sample": "",  # no netId: falls back to the directory page
        }

    def test_asu_prefers_the_declared_website_then_the_isearch_profile(self, monkeypatch):
        from src.collectors.schools import asu_faculty
        assert _feed_urls(monkeypatch, asu_faculty, "PHYS", "asu_isearch.json") == {
            "Ada Example": "https://search.asu.edu/profile/1000001",
            "Bo Sample": "https://bosample.example.org",
        }

    def test_uf_warrington_profile_comes_from_the_link_name(self, monkeypatch):
        from src.collectors.schools import uf_faculty
        assert _feed_urls(monkeypatch, uf_faculty, "WCB", "uf_warrington.json") == {
            "Ada Example": "https://warrington.ufl.edu/directory/ada-example/",
        }

    @pytest.mark.parametrize("short, host", [
        ("COP", "https://pharmacy.ufl.edu"),
        ("NUR2", "https://nursing.ufl.edu"),
        ("CVM3", "https://www.vetmed.ufl.edu"),
    ])
    def test_uf_apollo_staging_links_move_to_the_public_host(self, monkeypatch, short, host):
        from src.collectors.schools import uf_faculty
        urls = _feed_urls(monkeypatch, uf_faculty, short, "uf_apollo.json")
        assert urls == {"Ada Example": f"{host}/profile/example-ada/",
                        "Bo Sample": f"{host}/profile/sample-bo/"}

    def test_uf_phhp_keeps_no_staging_link(self, monkeypatch):
        from src.collectors.schools import uf_faculty
        urls = _feed_urls(monkeypatch, uf_faculty, "PHHP", "uf_apollo.json")
        assert set(urls.values()) == {""}

    @pytest.mark.parametrize("short, base", [
        ("ACCT", "https://tippie.uiowa.edu/people"),
        ("EDUTL", "https://education.uiowa.edu/directory"),
    ])
    def test_uiowa_profile_comes_from_the_slug(self, monkeypatch, short, base):
        from src.collectors.schools import uiowa_faculty
        urls = _feed_urls(monkeypatch, uiowa_faculty, short, "uiowa_profiles.json")
        # The emeritus row is gated out by personType.
        assert urls == {"Ada Example": f"{base}/ada-example"}

    def test_uiowa_record_never_carries_the_api_key(self, monkeypatch):
        from src.collectors.schools import uiowa_faculty
        dept = _dept(uiowa_faculty, "ACCT")
        _feed(monkeypatch, _fixture_json("uiowa_profiles.json"))
        school = uiowa_faculty.SCHOOL
        recs = [fg._normalize(school, dept, p) for p in fg._fetch_json_dir(dept)]
        assert recs and all("api-key" not in r["url"] for r in recs)

    def test_utah_engineering_profile_comes_from_the_unid(self, monkeypatch):
        from src.collectors.schools import utah_faculty
        assert _feed_urls(monkeypatch, utah_faculty, "CHE", "utah_coe.json") == {
            "Ada Example": "https://profiles.faculty.utah.edu/u0000001",
            "Bo Sample": "",
        }


# --- collector configs on saved pages: per-person link selectors -------------

def _card_urls(module, short, fixture):
    from bs4 import BeautifulSoup
    cfg = _dept(module, short)["scrape"]
    soup = BeautifulSoup((FIXTURES / fixture).read_text(), "html.parser")
    people = fg._parse_cards(soup, cfg["selectors"], cfg["url"],
                             cfg.get("ladder_filter"), cfg.get("name_flip", False),
                             cfg.get("link_filter"), cfg.get("section_filter"),
                             cfg.get("field_filter"))
    return [p["url"] for p in people]


class TestCardProfileLinks:
    def test_uiowa_h2_headline_links_its_profile(self):
        from src.collectors.schools import uiowa_faculty
        # Psychology/History/Sociology/Nursing render the headline as an h2.
        assert _card_urls(uiowa_faculty, "PSYC", "uiowa_sitenow_h2.html") == [
            "https://psychology.uiowa.edu/people/ada-example",
            "https://psychology.uiowa.edu/people/bo-sample"]

    def test_uf_abe_links_the_profile_where_the_card_has_one(self):
        from src.collectors.schools import uf_faculty
        assert _card_urls(uf_faculty, "ABE", "uf_abe.html") == [
            "https://abe.ufl.edu/people/faculty/ada-example/",
            "https://abe.ufl.edu/people/"]

    @pytest.mark.parametrize("short, fixture, expected", [
        ("MUSIC", "utah_music.html", [
            "https://music.utah.edu/faculty/ada-Ada-example.php",
            "https://profiles.faculty.utah.edu/u9000001"]),
        ("CS", "utah_cs.html", [
            "https://cs.utah.edu/~ada/", "https://www.cs.utah.edu/people/faculty/"]),
        ("ECON", "utah_econ.html", [
            "https://profiles.faculty.utah.edu/u9000002",
            "https://faculty.utah.edu/u9000001-EXAMPLE_PERSON/research/index.hml"]),
        ("MSE", "utah_mse.html", [
            "https://faculty.utah.edu/u9000001-EXAMPLE_PERSON/research/index.hml",
            "https://mse.utah.edu/faculty/"]),
        ("CVEEN", "utah_cveen.html", [
            "https://profiles.faculty.utah.edu/u9000001",
            "https://profiles.faculty.utah.edu/u9000002"]),
        ("PRT", "utah_prt.html", [
            "https://profiles.faculty.utah.edu/u9000001",
            "https://profiles.faculty.utah.edu/u9000002"]),
    ])
    def test_utah_cards_link_their_profiles(self, short, fixture, expected):
        from src.collectors.schools import utah_faculty
        assert _card_urls(utah_faculty, short, fixture) == expected
