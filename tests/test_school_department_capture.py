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

from pathlib import Path

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
