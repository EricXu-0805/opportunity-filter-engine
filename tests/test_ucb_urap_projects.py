"""Tests for the URAP project-database collector (src/collectors/ucb_urap_projects).

Parsing tests use a fixture mirroring the live list-page structure (title link to
detail.php?id=, a "Name - Title, Department" line, a status/hours line, a
description). Normalization tests are pure dict transforms (no network/bs4).
"""

from __future__ import annotations

import pytest

from src.collectors import ucb_urap_projects as up
from src.evidence import target_truth
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


CLOSED_LIST_FIXTURE = """
<html><body>
  <div class="results">
    <div class="entry">
      <h3><a href="detail.php?id=19595-1">Machine learning for radiopharmaceutical imaging</a></h3>
      <div>Christoph Neumann - Professor, Nuclear Engineering</div>
      <div>Status: Closed- no longer accepting apprentices   Weekly Hours: 9-11 hours   Location: On Campus</div>
      <div>Applying deep networks to alpha-particle microdosimetry maps.</div>
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

    def test_closed_row_survives_html_parse_into_a_non_actionable_record(self):
        """End to end on real markup, with the un-spaced dash URAP actually emits.

        The fixture writes "Closed- no longer accepting apprentices" exactly as
        the live page does (compare "Open- accepting new students"). If either
        _STATUS_RE or the status recognizer loses that form, the row silently
        normalizes as an open, actionable project again — which is the whole
        defect, reintroduced one layer earlier.
        """
        rows = up.parse_list_page(self._soup(CLOSED_LIST_FIXTURE))
        assert len(rows) == 1
        assert rows[0]["status"].startswith("Closed-")

        record = up.normalize_project(rows[0])  # default past=False: an Open page
        assert record["metadata"]["urap_status"] == "closed"
        assert record["metadata"]["is_active"] is False
        assert record["application"]["application_url"] is None

        truth = target_truth(record)
        assert truth.actionable is False
        assert truth.reason_code == "listing_closed"
        assert truth.reference_only is True
        assert truth.accepting_state == "not_accepting"

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

    def test_past_mode_marks_closed_and_not_rolling(self):
        # Closed/past seed: non-actionable, flagged, lower confidence — but same
        # stable id as the open record (so a reopened project upserts in place).
        o = up.normalize_project(self._raw(), past=True)
        assert o["is_rolling"] is False
        assert o["metadata"]["urap_status"] == "closed"
        assert o["metadata"]["confidence_score"] == 0.5
        assert "Past URAP project" in o["description"]
        assert "Apply through the URAP application portal" not in o["description"]
        assert o["id"] == up.normalize_project(self._raw())["id"]

    def test_past_mode_leaves_the_actionable_universe(self):
        """A lower confidence score only deprioritizes; this excludes.

        The 861 records already in the corpus were written with
        `metadata.is_active=True`, which is why `hard_exclusion` — whose only
        activity check is `metadata.is_active is False` — let closed projects
        rank. A refresh must not recreate that state.
        """
        o = up.normalize_project(self._raw(), past=True)
        assert o["metadata"]["is_active"] is False
        assert target_truth(o).actionable is False
        assert target_truth(o).reason_code == "listing_closed"
        assert target_truth(o).reference_only is True

    def test_past_mode_offers_no_application_url(self):
        """URAP publishes one program-wide portal, not a per-project form.

        Carrying it on a closed project turns "here is where URAP applications
        go" into "apply to this", which is the CTA the source never offered.
        The project page stays reachable as reference.
        """
        o = up.normalize_project(self._raw(), past=True)
        assert o["application"]["application_url"] is None
        assert o["url"]
        assert o["source_url"]

    def test_open_mode_unchanged_default(self):
        o = up.normalize_project(self._raw())
        assert o["is_rolling"] is True
        assert o["metadata"]["urap_status"] == "open"
        assert o["metadata"]["is_active"] is True
        assert o["application"]["application_url"] == up.APPLICATION_URL
        assert target_truth(o).actionable is True
        assert target_truth(o).reference_only is False

    @pytest.mark.parametrize(
        "status_line",
        [
            "Closed - no longer accepting apprentices",
            "closed",
            "  CLOSED - project full  ",
        ],
    )
    def test_a_row_that_states_closed_wins_over_the_page_parameter(self, status_line):
        """The page is fetched with one status; each row states its own.

        `?status=Open` is a query, not a guarantee — URAP re-labels a project
        mid-cycle and the row keeps its own Status line. Trusting only the
        caller's flag writes that row back as open/active with an application
        URL, which is how a closed project becomes actionable again on the very
        next refresh.
        """
        raw = self._raw()
        raw["status"] = status_line
        o = up.normalize_project(raw)  # default past=False, i.e. an Open page
        assert o["metadata"]["urap_status"] == "closed"
        assert o["metadata"]["is_active"] is False
        assert o["application"]["application_url"] is None
        assert target_truth(o).actionable is False
        assert target_truth(o).reason_code == "listing_closed"

    @pytest.mark.parametrize(
        "status_line",
        ["Open- accepting new students", "Open", "", "Full for spring"],
    )
    def test_only_a_recognized_closed_status_downgrades_a_row(self, status_line):
        """Narrow by design: no prose guessing, only the parsed status field."""
        raw = self._raw()
        raw["status"] = status_line
        o = up.normalize_project(raw)
        assert o["metadata"]["urap_status"] == "open"
        assert o["metadata"]["is_active"] is True
        assert target_truth(o).actionable is True

    def test_closed_page_still_marks_every_row_closed(self, monkeypatch):
        raw = self._raw()
        raw["status"] = "Open"
        monkeypatch.setattr(up, "scrape_projects", lambda status="Open": [raw])
        out = up.fetch_and_normalize("Closed")
        assert [o["metadata"]["urap_status"] for o in out] == ["closed"]
        assert [o["metadata"]["is_active"] for o in out] == [False]

    def test_open_page_with_a_mixed_status_row_downgrades_only_that_row(
        self, monkeypatch,
    ):
        open_row = self._raw()
        open_row["status"] = "Open- accepting new students"
        closed_row = self._raw()
        closed_row["id"] = "20079-1"
        closed_row["status"] = "Closed - no longer accepting apprentices"
        monkeypatch.setattr(
            up, "scrape_projects", lambda status="Open": [open_row, closed_row],
        )
        out = up.fetch_and_normalize("Open")
        assert [o["metadata"]["urap_status"] for o in out] == ["open", "closed"]
        assert [o["metadata"]["is_active"] for o in out] == [True, False]
        assert [target_truth(o).actionable for o in out] == [True, False]


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
