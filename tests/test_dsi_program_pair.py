from copy import deepcopy

from backend.routes.matches import _match_card
from src.collectors.base import RawOpportunity
from src.collectors.uiuc_sro import raw_to_normalized
from src.program_windows import DSI_DIRECTORY, DSI_WINDOW
from src.reviewed_program_pairs import verified_pairs
from src.saved_searches.filter import matching_ids
from tests.test_program_windows import _row


def test_dsi_results_preserve_saved_sources_and_independent_cohorts():
    host = _row("uchicago", "dsi_summer_lab")
    directory = raw_to_normalized(RawOpportunity(
        "uiuc_sro", "https://researchops.web.illinois.edu/?page=0", "Data Science Institute Summer Lab",
        "", DSI_DIRECTORY, organization="University of Chicago",
        extra_fields={"deadline_raw": "Anticipated 1/12/27", "program_url": DSI_WINDOW.url + "#program-overview"},
    ))
    rows = [directory, host]
    assert matching_ids(rows, {}) == [host["id"]]
    assert matching_ids(rows, {"source": "uiuc_sro"}) == [directory["id"]]
    assert matching_ids(rows, {}, preferred_ids=[directory["id"]]) == [directory["id"]]
    cards = {r["id"]: _match_card(r) for r in rows}
    assert all(card["application_closes_at"] == "2027-01-11T23:59:00-06:00" for card in cards.values())
    assert len(verified_pairs(cards, projected=True)) == 1
    changed = deepcopy(directory)
    changed["application"]["application_url"] = "https://example.edu/another-project"
    changed["application_deadline_source_url"] = DSI_WINDOW.page
    changed["application_closes_at"] = "2027-01-11T23:59:00-06:00"
    cards[changed["id"]] = _match_card(changed)
    assert "application_deadline_source_url" not in cards[changed["id"]]
    assert "application_closes_at" not in cards[changed["id"]]
    assert not verified_pairs(cards, projected=True)
    assert set(matching_ids([host, changed], {})) == {r["id"] for r in rows}


def test_published_central_cutoff_expires_both_source_ids_and_warm_match_cache(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from backend.routes import matches
    from src import evidence
    from src.program_windows import reviewed_program_cutoff

    host = _row("uchicago", "dsi_summer_lab")
    directory = raw_to_normalized(RawOpportunity(
        "uiuc_sro", "https://researchops.web.illinois.edu/?page=0", "Data Science Institute Summer Lab",
        "", DSI_DIRECTORY, organization="University of Chicago",
        extra_fields={"deadline_raw": "Anticipated 1/12/27", "program_url": DSI_WINDOW.url + "#program-overview"},
    ))
    other = deepcopy(directory)
    other["application"]["application_url"] = "https://example.edu/another-program"
    cutoff = datetime(2027, 1, 12, 5, 59, tzinfo=UTC)
    moment = cutoff - timedelta(seconds=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    monkeypatch.setattr(evidence, "datetime", Clock)
    monkeypatch.setattr(matches.time, "time", lambda: moment.timestamp())
    monkeypatch.setattr(matches, "_active_corpus_identity", None)
    monkeypatch.setattr(matches, "_project_cutoffs", ())
    monkeypatch.setattr(matches, "_match_universe", None)
    monkeypatch.setattr(matches, "_match_snapshots", {})
    monkeypatch.setattr(matches, "_match_view_rows", {})
    corpus = [host, directory]
    matches._activate_corpus_generation(corpus)
    assert matches.release_actionable_corpus(corpus) == corpus
    stamp = matches._ranked_with(None)
    assert all(reviewed_program_cutoff(row) == cutoff for row in corpus)
    moment = cutoff
    assert matches.release_actionable_corpus(corpus) == []
    assert matches._ranked_with(None) != stamp
    for row in corpus:
        truth = evidence.target_truth(row)
        assert (truth.actionable, truth.reason_code) == (False, "listing_closed")
        assert datetime.fromisoformat(truth.expires_at) == cutoff
    assert reviewed_program_cutoff(other) is None
    assert evidence.target_truth(other).actionable


def test_later_campus_notice_survives_offline_retries_without_2027_funding_or_dates(tmp_path, monkeypatch):
    import json

    from bs4 import BeautifulSoup

    from src.collectors import campus_graph
    from src.collectors.schools.uchicago import SCHOOL

    source = next(s for s in SCHOOL["sources"] if any(p["key"] == "dsi_summer_lab" for p in s.get("programs", [])))
    program = next(p for p in source["programs"] if p["key"] == "dsi_summer_lab")
    school = {**SCHOOL, "sources": [{**source, "seeds": [program["url"]], "programs": [program]}]}
    stored = tmp_path / "processed.json"
    stored.write_text("[]")
    monkeypatch.setattr(campus_graph, "PROCESSED_FILE", stored)

    def read(body):
        if body is not None:
            soup = BeautifulSoup("<main><h1>DSI Summer Lab</h1>" + body + "</main>", "html.parser")
            soup._ofe_fetch_metadata = {"requested_url": program["url"], "final_url": program["url"],
                                        "checked_at": "2026-11-26T12:00:00+00:00"}
        else:
            soup = None
        monkeypatch.setattr(campus_graph, "_fetch", lambda *args, **kwargs: soup)
        rows, stats = campus_graph.fetch_and_normalize_with_evidence(school, deep=True)
        assert stats["live_pages_loaded"] == int(soup is not None)
        campus_graph.merge_into_processed(rows, school_slug="uchicago")
        [row] = json.loads(stored.read_text())
        assert row["id"] == "uchicago-8cd2def060b6"
        return row

    current = "<p>Applications for Summer 2027 are now open!</p>"
    current_with_archive = current + "<h2>Past Programs</h2><p>Applications for Summer 2028.</p>"
    first = read(current_with_archive)
    assert first["deadline"] == "2027-01-11" and "$1,800" in first["compensation_details"]
    later = read("<p>Applications for summer 2027 have closed. Details for summer 2028 will appear later.</p>")
    for row in (later, read(None), read("<p>University program information.</p>"), read(None)):
        assert row["metadata"]["first_seen_at"] == first["metadata"]["first_seen_at"]
        assert row["metadata"]["dsi_application_notice"]["observed_at"] == later["metadata"]["last_verified"]
        assert row["deadline"] is None and row["paid"] == "unknown" and not row["compensation_details"]
        assert "summer 2028" in row["description_clean"] and "fall 2027" not in row["description_clean"]
        assert "2027" not in row["eligibility"]["eligibility_text_raw"]

    next_date = read("<p>Applications for Summer 2028 are open!</p><p>Application deadline: February 2, 2028.</p>")
    assert next_date["deadline"] == "2028-02-02" and "February 2, 2028" in next_date["description_clean"]
    assert not next_date["compensation_details"] and read(None)["deadline"] == "2028-02-02"
    two_open = read(current + "<p>Applications for Summer 2028 are open.</p><p>Application deadline: February 2, 2028.</p>")
    assert two_open["deadline"] is None and not two_open["compensation_details"]
    closed = read("<p>Applications for Summer 2028 have closed.</p>")
    assert closed["deadline"] is None and "2027" not in closed["description_clean"]
    restored = read(current)
    assert restored["deadline"] == "2027-01-11" and "$1,800" in restored["compensation_details"]


def test_both_original_funding_fields_link_to_the_host_and_preserve_the_directory_amount():
    from backend.lib.opportunity_detail import build_detail_fields
    from src.program_windows import DSI_SUPPORT, apply_program_window

    campus = _row("uchicago", "dsi_summer_lab")
    directory = raw_to_normalized(RawOpportunity(
        "uiuc_sro", "https://researchops.web.illinois.edu/?page=0", "Data Science Institute Summer Lab",
        "", DSI_DIRECTORY, organization="University of Chicago",
        extra_fields={"deadline_raw": "Anticipated 1/12/27", "program_url": DSI_WINDOW.url + "#program-overview"},
    ))
    directory["compensation_details"] = "$5,600"
    apply_program_window(directory)
    for row in (campus, directory):
        assert row["compensation_details"] == DSI_SUPPORT
        fields = build_detail_fields(row, row)["fields"]["funding"]
        assert fields["explicit"]["compensation"] == DSI_SUPPORT
        assert fields["quotes"]["compensation"]["source_url"] == DSI_WINDOW.page
    assert directory["metadata"]["directory_compensation"] == "$5,600"
    different_cohort = {**directory, "deadline": "2028-01-12", "compensation_details": "New stipend pending"}
    apply_program_window(different_cohort)
    assert different_cohort["compensation_details"] == "New stipend pending"
    assert "compensation" not in build_detail_fields(different_cohort, different_cohort)["fields"]["funding"]["quotes"]


def test_summer_lab_separates_admission_work_authorization_and_funding_through_refresh(tmp_path):
    import json

    from backend.lib.opportunity_detail import build_detail_fields
    from src.collectors.uiuc_sro import merge_into_processed
    from src.program_windows import DSI_WORK_AUTHORIZATION

    def directory(deadline, *, deep=True, program_url=DSI_WINDOW.url):
        details = {"deadline_raw": deadline}
        if deep:
            details.update(program_url=program_url, citizenship="No Citizenship Requirements",
                           compensation="$5,600", detail_page_verified=True)
        raw = RawOpportunity("uiuc_sro", "https://researchops.web.illinois.edu/?page=0",
                             "Data Science Institute Summer Lab", "", DSI_DIRECTORY, organization="University of Chicago",
                             extra_fields=details)
        return raw_to_normalized(raw)

    def assert_qualifications(row):
        fields = build_detail_fields(row, row)["fields"]
        eligibility = fields["eligibility"]
        assert eligibility["explicit"]["citizenship"] == "not_required"
        assert eligibility["explicit"]["international_students"] == "yes"
        assert eligibility["explicit"]["work_authorization_notes"] == DSI_WORK_AUTHORIZATION
        for key in ("citizenship", "international_students", "work_authorization_notes"):
            assert eligibility["quotes"][key]["source_url"] == DSI_WINDOW.url + "faq/"
        assert "U.S. citizens or permanent residents" in fields["funding"]["explicit"]["compensation"]
        assert fields["funding"]["quotes"]["compensation"]["source_url"] == DSI_WINDOW.page

    host = _row("uchicago", "dsi_summer_lab")
    first = directory("Anticipated 1/12/27")
    assert_qualifications(host)
    assert_qualifications(first)
    assert first["metadata"]["superseded_work_auth_notes"]["value"] == "No Citizenship Requirements"
    stored = tmp_path / "directory.json"
    for incoming in (first, directory("", deep=False), directory("Anticipated 1/12/27")):
        merge_into_processed([incoming], str(stored))
        [row] = json.loads(stored.read_text())
        assert_qualifications(row)

    next_year = directory("Anticipated 1/12/28", deep=False)
    for incoming in (next_year, directory("", deep=False)):
        merge_into_processed([incoming], str(stored))
        [row] = json.loads(stored.read_text())
        assert row["id"] == first["id"]
        assert row["eligibility"]["work_auth_notes"] != DSI_WORK_AUTHORIZATION
        assert "$1,800" not in row["compensation_details"]
    for other in (directory("Anticipated 1/12/27", program_url="https://example.edu/different"),
                  _row("stanford", "ssrp_amgen_scholars")):
        assert DSI_WORK_AUTHORIZATION != other["eligibility"]["work_auth_notes"]
        assert DSI_WINDOW.url + "faq/" not in str(build_detail_fields(other, other))
