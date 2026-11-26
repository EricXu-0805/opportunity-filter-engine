"""Tests for the URAP project-database collector (src/collectors/ucb_urap_projects).

Parsing tests use a fixture mirroring the live list-page structure (title link to
detail.php?id=, a "Name - Title, Department" line, a status/hours line, a
description). Normalization tests are pure dict transforms (no network/bs4).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src import urap_windows
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
        assert o["deadline"] is None and o["is_rolling"] is False
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

    def test_unverified_list_row_is_not_actionable(self):
        o = up.normalize_project(self._raw())
        assert o["is_rolling"] is False
        assert o["metadata"]["urap_status"] == "unknown"
        assert o["application"]["application_url"] is None
        assert target_truth(o).actionable is False
        assert target_truth(o).accepting_state == "unknown"

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
    def test_only_a_recognized_closed_status_marks_a_row_closed(self, status_line):
        """Narrow by design: no prose guessing, only the parsed status field."""
        raw = self._raw()
        raw["status"] = status_line
        o = up.normalize_project(raw)
        assert o["metadata"]["urap_status"] == "unknown"
        assert o["metadata"]["is_active"] is False
        assert target_truth(o).actionable is False

    def test_closed_page_still_marks_every_row_closed(self, monkeypatch):
        raw = self._raw()
        raw["status"] = "Open"
        monkeypatch.setattr(up, "scrape_projects", lambda status="Open", **kwargs: [raw])
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
            up, "scrape_projects", lambda status="Open", **kwargs: [open_row, closed_row],
        )
        calls = []
        monkeypatch.setattr(up, "_fetch", lambda url, params: calls.append((url, params)))
        out = up.fetch_and_normalize("Open")
        assert calls == [(f"{up.BASE_URL}/detail.php", {"id": open_row["id"]})]
        assert [o["metadata"]["urap_status"] for o in out] == ["unknown", "closed"]
        assert all(not target_truth(o).actionable for o in out)


class TestMerge:
    def test_empty_scrape_does_not_touch_corpus(self, tmp_path, monkeypatch):
        # Off-season Open returns 0 — must NOT overwrite/delete the corpus.
        f = tmp_path / "opportunities.json"
        f.write_text('[{"id": "keep-me"}]', encoding="utf-8")
        monkeypatch.setattr(up, "PROCESSED_FILE", f)
        added, updated = up.merge_into_processed([])
        assert (added, updated) == (0, 0)
        assert [o["id"] for o in json.loads(f.read_text())] == ["keep-me"]

PROJECT = {"id": "20152-2", "title": "Steelhead trout bioenergetics and movement study",
           "url": "https://urapprojects.berkeley.edu/detail.php?id=20152-2", "status": "Open"}
FALL = ("Open. Apprentices needed for the fall semester. Enter your application online beginning August 21st. "
        "The deadline to apply is Monday, August 31st, 4pm.")
SPRING = ("Open. Apprentices needed for the spring semester. Enter your application online beginning January 15th. "
          "The deadline to apply is Monday, January 25th, 12pm noon.")


def detail_soup(notice=FALL, term="Fall 2026", *, body="", title=PROJECT["title"]):
    html = (f"<h2>Project Descriptions<span>{term}</span></h2><h3>{title}</h3>"
            f"<p><em>{notice}</em></p>{body}")
    return pytest.importorskip("bs4").BeautifulSoup(html, "html.parser")


def detail_raw(soup, at):
    window = up.parse_project_notice(soup, PROJECT["title"], PROJECT["url"], at)
    return {**PROJECT, "detail": window}


def test_berkeley_local_window_and_cached_open_record(monkeypatch):
    closes = datetime(2026, 8, 31, 23, tzinfo=UTC)  # 4pm Berkeley daylight time
    raw = detail_raw(detail_soup(), closes)
    assert raw["detail"]["deadline_at"] == "2026-08-31T16:00:00-07:00"
    before_open = up.normalize_project(raw, now=datetime(2026, 8, 21, 6, 59, tzinfo=UTC))
    assert before_open["metadata"]["urap_status"] == "upcoming"
    assert before_open["application"]["application_url"] is None
    during = up.normalize_project(raw, now=closes.replace(hour=22, minute=59))
    assert during["metadata"]["urap_status"] == "open"
    assert during["deadline"] == "2026-08-31" and not during["is_rolling"]
    assert during["application"]["application_url"] == up.APPLICATION_URL
    after = up.normalize_project(raw, now=closes)
    assert after["metadata"]["urap_status"] == "closed"
    assert after["application"]["application_url"] is None
    assert after["id"] == during["id"] == "ucb-urap-proj-4029d15a89db"

    from src import evidence

    monkeypatch.setattr(evidence, "_today", lambda: closes.date())
    monkeypatch.setattr(evidence, "window_phase", lambda detail: urap_windows.window_phase(detail, closes))
    assert target_truth(during).actionable is False
    assert target_truth(during).reference_only is True


@pytest.mark.parametrize("soup", [
    lambda: detail_soup("Open.", body=f"<p>{FALL}</p>"),
    lambda: detail_soup("Open.", body=f"<p>Research milestone: <em>{FALL}</em></p>"),
    lambda: detail_soup(FALL.replace("deadline to apply", "deadline to present results")),
    lambda: detail_soup(FALL.replace("Monday,", "Tuesday,")),
    lambda: detail_soup(FALL.replace("August 31st,", "August 31st, 2027,")),
    lambda: detail_soup(term=""),
    lambda: detail_soup(title="Unrelated research project"),
    lambda: detail_soup(body="<p><em>Closed. Full.</em></p>"),
])
def test_prose_unrelated_or_ambiguous_evidence_cannot_open_a_project(soup):
    now = datetime(2026, 8, 25, tzinfo=UTC)
    raw = detail_raw(soup(), now)
    assert raw["detail"] is None
    assert up.normalize_project(raw, now=now)["application"]["application_url"] is None


def test_detail_closure_wins_on_open_list_even_if_body_has_a_deadline():
    now = datetime(2026, 8, 25, tzinfo=UTC)
    raw = detail_raw(detail_soup("Closed. Faculty is no longer accepting apprentices.", body=f"<p>{FALL}</p>"), now)
    record = up.normalize_project(raw, now=now)
    assert record["metadata"]["urap_status"] == "closed"
    assert record["deadline"] is None
    assert not target_truth(record).actionable


def test_transient_failure_preserves_evidence_until_same_id_reopens(tmp_path, monkeypatch):
    file = tmp_path / "opportunities.json"
    file.write_text("[]")
    monkeypatch.setattr(up, "PROCESSED_FILE", file)
    monkeypatch.setattr(up, "scrape_projects", lambda status="Open", **kwargs: [PROJECT])
    monkeypatch.setattr(up, "_fetch", lambda url, params: None)
    fall_read = datetime(2026, 11, 25, tzinfo=UTC)
    old = up.normalize_project(detail_raw(detail_soup(), fall_read), now=fall_read)
    up.merge_into_processed([old])
    up.merge_into_processed(up.fetch_and_normalize("Open"))
    held, = json.loads(file.read_text())
    assert held == old
    spring_read = datetime(2027, 1, 18, tzinfo=UTC)
    new = up.normalize_project(detail_raw(detail_soup(SPRING, "Spring 2027"), spring_read), now=spring_read)
    assert up.merge_into_processed([new]) == (0, 1)
    reopened, = json.loads(file.read_text())
    assert reopened["id"] == held["id"] and reopened["metadata"]["first_seen_at"] == old["metadata"]["first_seen_at"]
    assert reopened["application"]["application_url"] == up.APPLICATION_URL
    assert reopened["metadata"]["urap_status"] == "open" and not reopened["is_rolling"]
    assert reopened["metadata"]["urap_window"]["deadline_at"] == "2027-01-25T12:00:00-08:00"


def test_reviewed_legacy_window_only_touches_the_verified_project():
    from backend.data_loader import _sanitize_opportunity

    file = up.PROJECT_ROOT / "data/processed/shards/ucb.json"
    stored = next(row for row in json.loads(file.read_text()) if row["id"] == "ucb-urap-proj-4029d15a89db")
    # Model the previous collector even after the next scheduled shard refresh.
    legacy = up.normalize_project(PROJECT)
    legacy.update(deadline=None, is_rolling=True)
    legacy["metadata"].update(urap_status="open", is_active=True)
    legacy["description_clean"] += " Apply through the URAP application portal."
    legacy["application"]["application_url"] = up.APPLICATION_URL
    wrong = {**legacy, "source_url": "https://example.org/"}
    urap_windows.apply_legacy_window(wrong)
    assert wrong["is_rolling"] and legacy["metadata"]["urap_status"] == "open"
    assert legacy["id"] == stored["id"]
    _sanitize_opportunity(legacy)
    assert target_truth(legacy).reference_only and not target_truth(legacy).actionable
    assert legacy["deadline"] == "2026-08-31" and not legacy["is_rolling"]
    assert "Apply through" not in legacy["description_clean"]
    assert legacy["application"]["application_url"] is None

    from backend.lib.opportunity_detail import build_detail_fields
    from backend.lib.public_opportunity_detail import project_public_detail

    public = project_public_detail(legacy)
    assert public["target_truth"]["verified_at"] == "2026-11-25T12:06:36+00:00"
    assert "urap_window" not in public["metadata"]
    timing = build_detail_fields(public, legacy)["fields"]["timing"]
    assert timing["quotes"]["deadline"] == {
        "text": "The deadline to apply is Monday, August 31st, 4pm.", "source_url": PROJECT["url"],
        "observed_at": "2026-11-25T12:06:36+00:00",
    }


def test_match_universe_and_snapshot_expire_with_a_still_cached_record(monkeypatch):
    from backend.routes import matches
    from src import evidence

    cutoff = datetime(2026, 8, 31, 23, tzinfo=UTC)
    moment = [cutoff.replace(hour=22, minute=59)]
    record = up.normalize_project(detail_raw(detail_soup(), moment[0]), now=moment[0])
    corpus = [record]
    monkeypatch.setattr(evidence, "_today", lambda: moment[0].date())
    monkeypatch.setattr(evidence, "window_phase", lambda detail: urap_windows.window_phase(detail, moment[0]))
    monkeypatch.setattr(matches.time, "time", lambda: moment[0].timestamp())
    monkeypatch.setattr(matches, "_active_corpus_identity", None)
    monkeypatch.setattr(matches, "_project_cutoffs", ())
    monkeypatch.setattr(matches, "_match_universe", None)
    monkeypatch.setattr(matches, "_match_snapshots", {})
    monkeypatch.setattr(matches, "_match_view_rows", {})
    matches._activate_corpus_generation(corpus)
    assert matches._release_universe(corpus) == corpus
    before = matches._ranked_with(None)
    moment[0] = cutoff
    assert matches._ranked_with(None) != before
    assert matches._release_universe(corpus) == []


@pytest.mark.parametrize(("deadline", "hour", "minute"), [
    ("The deadline to apply is Monday, August 31st, 4 p.m.", 16, 0),
    ("The deadline to apply is Monday, August 31st, 4 p.m..", 16, 0),
    ("The deadline to apply is Monday, August 31st, 4:00 PM.", 16, 0),
    ("The deadline to apply is Monday, August 31st, noon.", 12, 0),
    ("The deadline to apply is Monday, August 31st, 12 noon.", 12, 0),
    ("The deadline to apply is Monday, August 31st, 12am midnight.", 0, 0),
    ("The deadline to apply is Monday, August 31st, 11:59pm PT.", 23, 59),
    ("The deadline to apply is Monday, Aug. 31st by 4pm.", 16, 0),
    ("The deadline to apply is 4pm on Monday, August 31st.", 16, 0),
    ("Applications are due Monday, Aug. 31st at 4pm.", 16, 0),
])
def test_published_clock_and_date_forms(deadline, hour, minute):
    notice = FALL[:FALL.index("The deadline")] + deadline
    detail = detail_raw(detail_soup(notice), datetime(2026, 8, 18, tzinfo=UTC))["detail"]
    assert detail["opens_on"] == "2026-08-21"
    assert detail["deadline_at"] == f"2026-08-31T{hour:02}:{minute:02}:00-07:00"
    assert detail["deadline_quote"] == deadline


@pytest.mark.parametrize("clock", ["", ", 4pm ET", ", 4pm PST", ", 0pm", ", 12:65pm",
                                   ", 4pm noon", ", 12:01am midnight", ", 12pm midnight",
                                   ", 4 p.m. Eastern Time", ", 4 p.m. EDT", ", noon or midnight"])
def test_uncertain_cutoff_does_not_grant_application_access(clock):
    at = datetime(2026, 8, 24, tzinfo=UTC)
    raw = detail_raw(detail_soup(FALL.replace(", 4pm", clock)), at)
    assert raw["detail"] is None
    assert up.normalize_project(raw, now=at)["metadata"]["urap_status"] == "unknown"


def test_contradictory_or_duplicate_deadline_never_opens():
    notice = FALL + " Applications are due on another date."
    assert detail_raw(detail_soup(notice), datetime(2026, 8, 24, tzinfo=UTC))["detail"] is None


def test_previous_calendar_year_for_spring_requires_corroboration():
    notice = ("Open. Enter your application online beginning December 1st. "
              "The deadline to apply is Monday, December 14th, 4pm.")
    now = datetime(2026, 12, 2, tzinfo=UTC)
    detail = detail_raw(detail_soup(notice, "Spring 2027"), now)["detail"]
    assert detail["opens_on"] == "2026-12-01"
    assert detail["deadline_at"] == "2026-12-14T16:00:00-08:00"
    assert detail_raw(detail_soup(notice.replace("Monday, ", ""), "Spring 2027"), now)["detail"] is None


@pytest.mark.parametrize("clock", ["4pm.", "4 p.m.", "4:00 PM PT."])
def test_deadline_quote_stops_at_next_sentence(clock):
    notice = FALL.replace("4pm.", clock) + " Please include your transcript with your application."
    detail = detail_raw(detail_soup(notice), datetime(2026, 8, 24, tzinfo=UTC))["detail"]
    assert detail["deadline_quote"].endswith(clock)
    assert "Please" not in detail["deadline_quote"]

def test_list_failure_is_distinct_from_a_supported_seasonal_zero(monkeypatch):
    from src.collectors.source_health import collection_evidence_issues

    monkeypatch.setattr(up, "_fetch", lambda url, params: None)
    errors = []
    assert up.fetch_and_normalize("Open", list_errors=errors) == []
    assert up.fetch_and_normalize("Closed", list_errors=errors) == []
    assert errors == ["Open list page 1: fetch failed", "Closed list page 1: fetch failed"]
    assert collection_evidence_issues({"list_errors": errors}) == (["list_errors"], [])

    errors.clear()
    monkeypatch.setattr(up, "_fetch", lambda *args: detail_soup(body="Showing 0 projects out of 0 found."))
    assert up.fetch_and_normalize("Open", list_errors=errors) == []
    assert not errors


@pytest.mark.parametrize("second_page, expected", [
    (None, "fetch failed"), (LIST_FIXTURE, "did not report a result count"),
    ("Showing , projects out of 3 found.", "did not report a result count"),
    ("Showing 1 project out of 3 found.", "read 0 distinct new IDs"),
    ("Showing 0 projects out of 3 found.", "only 2 distinct IDs"),
])
def test_incomplete_second_page_retains_first_page_and_reports_gap(monkeypatch, second_page, expected):
    first = detail_soup(body="Showing 2 projects out of 3 found." + LIST_FIXTURE)
    pages = iter([first, detail_soup(body=second_page) if second_page else None])
    monkeypatch.setattr(up, "_fetch", lambda *args: next(pages))
    monkeypatch.setattr(up, "PER_PAGE", 2)
    monkeypatch.setattr(up, "_PAGE_DELAY", 0)
    errors = []
    assert len(up.scrape_projects("Closed", list_errors=errors)) == 2
    assert len(errors) == 1 and expected in errors[0]
