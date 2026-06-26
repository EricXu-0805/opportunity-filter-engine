"""Tests for the URAP project-database collector (src/collectors/ucb_urap_projects).

Parsing tests use a fixture mirroring the live list-page structure (title link to
detail.php?id=, a "Name - Title, Department" line, a status/hours line, a
description). Normalization tests are pure dict transforms (no network/bs4).
"""

from __future__ import annotations

import pytest

from src.collectors import ucb_urap_projects as up
from src.normalizers.school_audience import SOURCE_DEFAULTS

LIST_FIXTURE = """
<html><body>
  <div class="results">
    <div class="entry">
      <h3><a href="detail.php?id=20078-1">Stability driven interpretation of neural networks</a></h3>
      <div>Reza Abbasi-Asl - Professor, Neuroscience</div>
      <div>Status: Open- accepting new students   Weekly Hours: 12 or more hours   Location: Off Campus</div>
      <p>Deep neural networks achieve state-of-the-art performance in computer vision and natural language processing tasks.</p>
    </div>
    <div class="entry">
      <h3><a href="detail.php?id=20099-2">Microbial ecology of coastal sediments</a></h3>
      <div>Jane Doe - Associate Professor, Integrative Biology</div>
      <div>Status: Open   Weekly Hours: 6-8 hours   Location: On Campus</div>
      <p>Investigating microbial community structure using genomics and statistics.</p>
    </div>
  </div>
</body></html>
"""


class TestParseListPage:
    def _soup(self, html):
        bs4 = pytest.importorskip("bs4")
        return bs4.BeautifulSoup(html, "html.parser")

    def test_extracts_both_projects(self):
        rows = up.parse_list_page(self._soup(LIST_FIXTURE))
        assert len(rows) == 2
        ids = {r["id"] for r in rows}
        assert ids == {"20078-1", "20099-2"}

    def test_captures_title_url_faculty_department(self):
        rows = {r["id"]: r for r in up.parse_list_page(self._soup(LIST_FIXTURE))}
        r = rows["20078-1"]
        assert "Stability driven" in r["title"]
        assert r["url"].endswith("detail.php?id=20078-1")
        assert r["faculty"] == "Reza Abbasi-Asl"
        assert r["department"] == "Neuroscience"
        assert "12 or more hours" in r["weekly_hours"]
        assert "neural networks" in r["description"].lower()

    def test_no_detail_links_yields_empty(self):
        rows = up.parse_list_page(self._soup("<html><body><p>No projects match.</p></body></html>"))
        assert rows == []


class TestNormalize:
    def _raw(self):
        return {
            "id": "20078-1",
            "title": "Stability driven interpretation of neural networks",
            "url": "https://urapprojects.berkeley.edu/detail.php?id=20078-1",
            "faculty": "Reza Abbasi-Asl",
            "faculty_title": "Professor",
            "department": "Neuroscience",
            "description": "Deep neural networks and computer vision research.",
            "weekly_hours": "12 or more hours",
            "location": "Off Campus",
        }

    def test_schema_and_dq_critical_fields(self):
        o = up.normalize_project(self._raw())
        assert o["source"] == "ucb_urap_projects"
        assert o["id"].startswith("ucb-urap-proj-")
        assert o["opportunity_type"] == "research"
        assert o["paid"] == "no"
        assert o["deadline"] is None and o["is_rolling"] is True
        # DQ: never a pi_name/contact_email (avoids the ucb_* joint-appointment gate).
        assert o["pi_name"] is None and o["contact_email"] is None
        assert isinstance(o["eligibility"], dict) and isinstance(o["metadata"], dict)
        assert isinstance(o["keywords"], list) and o["keywords"]
        assert "description_clean" in o and len(o["description_clean"]) <= 1500

    def test_school_audience_matches_source_default(self):
        o = up.normalize_project(self._raw())
        assert (o["school"], o["audience"]) == SOURCE_DEFAULTS["ucb_urap_projects"] == ("ucb", "campus")

    def test_faculty_name_in_lab_not_pi(self):
        o = up.normalize_project(self._raw())
        assert "Reza Abbasi-Asl" in o["lab_or_program"]
        assert "Reza Abbasi-Asl" in o["description"]

    def test_stable_id_across_reruns(self):
        assert up.normalize_project(self._raw())["id"] == up.normalize_project(self._raw())["id"]


class TestMerge:
    def test_empty_scrape_does_not_touch_corpus(self, tmp_path, monkeypatch):
        # Off-season Open returns 0 — must NOT overwrite/delete the corpus.
        f = tmp_path / "opportunities.json"
        f.write_text('[{"id": "keep-me"}]', encoding="utf-8")
        monkeypatch.setattr(up, "PROCESSED_FILE", f)
        added, updated = up.merge_into_processed([])
        assert (added, updated) == (0, 0)
        import json
        assert [o["id"] for o in json.loads(f.read_text())] == ["keep-me"]
