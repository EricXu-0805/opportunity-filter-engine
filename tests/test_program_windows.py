"""Application windows read on configured programs' own pages (M05)."""

from __future__ import annotations

import copy
import json
from datetime import date, time
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend import data_loader
from backend.lib.opportunity_detail import build_detail_fields
from backend.lib.public_projection import neutralize_lifecycle_title, project_public_opportunity_payload
from src import evidence
from src.collectors import campus_graph as cg
from src.collectors import ucb_campus, ucb_sources
from src.collectors.schools import SCHOOL_CONFIGS
from src.program_windows import WINDOWS, apply_program_window, reviewed_window

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")


def _schools() -> dict[str, dict]:
    configs = SCHOOL_CONFIGS.values() if isinstance(SCHOOL_CONFIGS, dict) else SCHOOL_CONFIGS
    return {school["school_slug"]: school for school in configs}


def _spec(school_slug: str, key: str) -> tuple[dict, dict, dict]:
    school = {"sources": ucb_sources.UCB_SOURCES} if school_slug == "ucb" else _schools()[school_slug]
    for source in school["sources"]:
        for spec in source.get("programs", []):
            if spec["key"] == key:
                return school, source, spec
    raise LookupError((school_slug, key))


def _row(school_slug: str, key: str) -> dict:
    if school_slug == "manual":
        shard = Path(__file__).resolve().parents[1] / "data" / "processed" / "shards" / "national.json"
        return next(record for record in json.loads(shard.read_bytes()) if record["id"] == key)
    school, source, spec = _spec(school_slug, key)
    if school_slug == "ucb":
        return ucb_campus._normalize_program(source, spec)
    return cg._normalize_program(school, source, spec)


@pytest.mark.parametrize(("school", "key"), sorted(WINDOWS))
def test_every_window_is_for_the_page_its_program_is_configured_at(school, key):
    row = _row(school, key)
    assert row["url"] == row["source_url"] == WINDOWS[(school, key)].url


@pytest.mark.parametrize(("school", "key"), sorted(WINDOWS))
def test_every_window_quotes_its_closing_date(school, key):
    window = WINDOWS[(school, key)]
    closes = window.closes_on
    written = (f"{_MONTHS[closes.month - 1]} {closes.day}", f"{closes.month}/{closes.day}/{closes.year}")
    assert any(text in window.closes_quote for text in written)


@pytest.mark.parametrize(("school", "key"), sorted(k for k, w in WINDOWS.items() if w.opens_on))
def test_every_stated_opening_is_quoted_with_its_campus_zone(school, key):
    window = WINDOWS[(school, key)]
    opens = window.opens_on
    written = (f"{_MONTHS[opens.month - 1]} {opens.day}", f"{opens.month}/{opens.day}/{opens.year}")
    assert any(text in window.opens_quote for text in written)
    local = window.opens_at.astimezone(ZoneInfo(window.zone))
    assert (local.date(), local.time()) == (opens, time.min)


def test_a_harvested_program_carries_its_pages_stated_close_as_its_deadline():
    row = _row("unl", "unl_summer_research_program")

    assert row["deadline"] == "2027-03-01"
    assert row["deadline_is_estimate"] is False
    assert evidence.stated_listing_deadline(row) == date(2027, 3, 1)


def test_a_stored_row_gets_the_deadline_when_the_corpus_loads():
    stored = _row("northwestern", "nu_tgs_srop")
    stored.update(deadline=None, deadline_is_estimate=None, is_rolling=True)

    loaded = data_loader._sanitize_opportunity(stored)

    assert loaded["deadline"] == "2027-02-10"
    assert loaded["deadline_is_estimate"] is False
    assert loaded["is_rolling"] is False


@pytest.mark.parametrize(("school", "key"), sorted(WINDOWS))
def test_a_program_with_a_stated_close_is_not_under_no_deadline_listed(school, key):
    from backend.routes.matches import _match_card
    from src.saved_searches.filter import _matches_deadline

    stored = _row(school, key)
    stored.update(deadline=None, deadline_is_estimate=None, is_rolling=True)
    assert _matches_deadline(stored, "rolling") is True

    loaded = data_loader._sanitize_opportunity(stored)
    card = _match_card(loaded)

    assert (card["deadline"], card["is_rolling"]) == (WINDOWS[(school, key)].closes_on.isoformat(), False)
    assert _matches_deadline(loaded, "rolling") is False


def test_the_program_is_offered_until_its_close_and_closed_after(monkeypatch):
    row = _row("caltech", "wave_fellows")

    monkeypatch.setattr(evidence, "_today", lambda: date(2027, 1, 9))
    assert evidence.target_truth(row).actionable is True
    monkeypatch.setattr(evidence, "_today", lambda: date(2027, 1, 10))
    truth = evidence.target_truth(row)
    assert (truth.actionable, truth.reason_code, truth.evidence_key) == (False, "listing_closed", "deadline")


def test_northwestern_global_research_grant_closes_on_the_deadline_its_page_states(monkeypatch):
    # Read 2026-11-16: the page's DEADLINE heading is followed by "Thursday,
    # November 19, 2026 (11:59 PM CST)". The record carried that date only in
    # its note, so it would stay listed as rolling after the date passes.
    row = _row("northwestern", "nu_circumnavigator_grant")

    assert (row["deadline"], row["is_rolling"]) == ("2026-11-19", False)
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 20))
    assert evidence.target_truth(row).actionable is True
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 21))
    truth = evidence.target_truth(row)
    assert (truth.actionable, truth.reason_code, truth.evidence_key) == (False, "listing_closed", "deadline")


@pytest.mark.parametrize("change", ["moved", "display_link_moved", "source_page_moved", "discovered", "other_school",
                                    "other_key"])
def test_only_the_reviewed_program_at_its_reviewed_page_gets_the_window(change):
    row = _row("jhu", "summer_pura")
    row.update(deadline=None, deadline_is_estimate=None)
    if change == "moved":
        row["url"] = row["source_url"] = "https://hour.jhu.edu/opportunities/summer-pura-2027/"
    elif change == "display_link_moved":
        row["url"] = "https://hour.jhu.edu/opportunities/summer-pura-2027/"
    elif change == "source_page_moved":
        row["source_url"] = "https://hour.jhu.edu/opportunities/summer-pura-2027/"
    elif change == "discovered":
        row["metadata"]["discovered"] = True
    elif change == "other_school":
        row["metadata"]["collector_school"] = "jhu_other"
    else:
        row["metadata"]["collector_key"] = "pura"

    apply_program_window(row)

    assert reviewed_window(row) is None
    assert row["deadline"] is None


def test_a_program_without_a_window_keeps_no_deadline():
    row = _row("jhu", "pura")

    assert row["deadline"] is None
    assert row["is_rolling"] is True


def test_the_detail_page_shows_the_deadline_in_the_pages_words():
    row = _row("caltech", "surf_jpl")

    timing = build_detail_fields(copy.deepcopy(row), row)["fields"]["timing"]

    assert timing["explicit"]["deadline"] == "2027-02-22"
    assert timing["quotes"]["deadline"] == {
        "text": "SURF@JPL applications are due on February 22.",
        "source_url": "https://sfp.caltech.edu/undergraduate-research/programs/surfjpl/application-information",
        "observed_at": "2026-11-05",
    }


def test_a_deadline_other_than_the_windows_carries_no_quote():
    row = _row("caltech", "surf_jpl")
    payload = {**copy.deepcopy(row), "deadline": "2027-03-01"}

    timing = build_detail_fields(payload, row)["fields"]["timing"]

    assert timing["explicit"]["deadline"] == "2027-03-01"
    assert "deadline" not in timing["quotes"]


def _read_open(school_slug: str, key: str, read_at: str | None) -> dict:
    school, source, spec = _spec(school_slug, key)
    row = cg._normalize_program(school, source, spec, status="open", seed_page_verified=True,
                                extra_desc="Applications are now open.")
    row["metadata"]["last_verified"] = read_at
    assert row["title"].endswith(" (applications open)")
    return row


@pytest.mark.parametrize(("read_at", "kept"), [
    ("2026-10-23T11:43:39.652921", False),
    # Midnight on November 1 in Chicago, still on daylight time, is 05:00 UTC.
    ("2026-11-01T04:59:59", False),
    ("2026-11-01T05:00:00", True),
    ("2026-11-01T05:00:00+00:00", True),
    ("2026-11-01T00:30:00-05:00", True),
    (None, False),
    ("yesterday", False),
])
def test_an_open_status_read_before_the_stated_opening_does_not_title_the_row(read_at, kept):
    row = _read_open("northwestern", "nu_tgs_srop", read_at)

    assert neutralize_lifecycle_title(row["title"], row).endswith(" (applications open)") is kept


def test_the_card_drops_a_suffix_read_before_the_opening():
    row = _read_open("unl", "unl_summer_research_program", "2026-11-14T12:00:00")

    card = project_public_opportunity_payload({"title": row["title"]}, row)

    assert card["title"] == "Nebraska Summer Research Program (University of Nebraska-Lincoln)"
    assert card["target_truth"]["actionable"] is True


def test_a_window_that_states_no_opening_leaves_the_suffix_alone():
    row = _read_open("caltech", "wave_fellows", "2026-07-18T06:41:25")

    assert neutralize_lifecycle_title(row["title"], row).endswith(" (applications open)")


def test_the_public_payload_carries_the_pages_stated_opening():
    row = _row("unl", "unl_summer_research_program")

    out = project_public_opportunity_payload({"title": row["title"]}, row)

    assert out["application_opens"] == {
        "on": "2026-11-15",
        "at": "2026-11-15T06:00:00+00:00",
        "text": "November 15",
        "quote": "November 15: Online application opens.",
        "source_url": "https://summerprogram.unl.edu/",
    }
    assert out["target_truth"]["actionable"] is True


def test_the_match_card_carries_the_opening():
    from backend.routes.matches import _match_card

    assert _match_card(_row("jhu", "summer_pura"))["application_opens"]["text"] == "11/1/2026"


def test_a_window_that_states_no_opening_serves_none():
    row = _row("caltech", "surf_jpl")

    assert "application_opens" not in project_public_opportunity_payload({"title": row["title"]}, row)


def test_a_payload_cannot_bring_its_own_opening():
    row = _row("jhu", "pura")
    forged = {"on": "2099-01-01", "at": "2099-01-01T05:00:00+00:00", "text": "January 1", "quote": "x",
              "source_url": None}

    assert "application_opens" not in project_public_opportunity_payload(
        {"title": row["title"], "application_opens": forged}, row)


# Read 2026-11-05: the award on each program's overview page, the deadline on
# its application page (the window's sentence).
_CALTECH_PAGE_WORDS = {
    "surf": "$8,354 award for the ten-week period",
    "surf_jpl": "$9,600 award for the ten-week period",
    "wave_fellows": "$8,354 for the ten-week period, plus a on-campus housing supplement of $2,000",
}


@pytest.mark.parametrize("key", sorted(_CALTECH_PAGE_WORDS))
def test_caltechs_summer_programs_give_their_2027_award_and_deadline_in_the_pages_words(key):
    _, _, spec = _spec("caltech", key)

    assert spec["compensation"] == _CALTECH_PAGE_WORDS[key]
    assert spec["deadline_note"] == WINDOWS[("caltech", key)].closes_quote


def test_jhu_summer_pura_gives_its_award_and_deadline_in_the_pages_words():
    _, _, spec = _spec("jhu", "summer_pura")

    # Read 2026-11-05 on its page: "Award amount: $6000 per recipient".
    assert spec["compensation"] == "$6000 per recipient"
    assert spec["deadline_note"] == ("Deadline to apply: February 1 (11:59 pm) (this includes all sections: "
                                     "application, resume upload, proposal upload, and mentor letter/s)")


def test_jhu_pura_whose_page_refused_us_keeps_its_config():
    _, _, spec = _spec("jhu", "pura")

    assert (spec["compensation"], spec["deadline_note"]) == (
        "$3,000 fellowship", "Applications due September 1 (11:59 pm), including mentor letters")


def test_every_window_zone_resolves_from_the_shipped_tz_database():
    # zoneinfo reads the host's tz database first; tzdata (requirements.txt)
    # is what it falls back to on a host without one.
    zones = {window.zone for window in WINDOWS.values() if window.zone}
    assert zones
    for zone in zones:
        assert resources.files("tzdata.zoneinfo").joinpath(*zone.split("/")).is_file(), zone

def test_berkeley_haas_closed_cycle_in_old_national_and_new_campus_rows(monkeypatch):
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 25))
    campus = _row("ucb", "haas_scholars")
    assert (campus["school"], campus["audience"]) == ("ucb", "campus")
    assert campus["eligibility"]["min_gpa"] == 3.45
    assert campus["eligibility"]["international_friendly"] == "no"
    assert campus["eligibility"]["citizenship_required"] is False
    old = copy.deepcopy(campus)
    old.update(id="ucb-b701ddbcd6157b", school=None, audience="open", source="ucb_external_research",
               deadline=None, is_rolling=True)
    old["metadata"]["collector_source"] = "ucb_external_fellowships"
    for row in (campus, data_loader._sanitize_opportunity(old)):
        assert row["deadline"] == "2026-03-13" and row["is_rolling"] is False
        assert not evidence.target_truth(row).actionable


def test_berkeley_lab_suli_keeps_its_id_and_uses_the_doe_application():
    row = _row("ucb", "lbl_suli")
    assert row["id"] == "ucb-b923a71f6ac423"
    assert row["school"] is None and row["audience"] == "open"
    assert row["application"]["application_url"] == "https://science.osti.gov/wdts/suli/How-to-Apply"
    assert (row["deadline"], row["is_rolling"]) == ("2027-01-06", False)
    assert row["eligibility"]["min_gpa"] == 3.0
    assert row["eligibility"]["citizenship_required"] is True
    assert row["eligibility"]["preferred_year"] == []


def test_two_aggregated_estimates_use_the_reviewed_host_date_only_for_the_same_cohort():
    from src.collectors.base import RawOpportunity
    from src.collectors.nsf_reu import normalize_award
    from src.collectors.uiuc_sro import raw_to_normalized

    award = {"id": "2447669", "title": "REU Site: Genes & the Environment", "startDate": "11/01/2025"}
    directory = "https://researchops.web.illinois.edu/opportunity/cellular-and-molecular-biology-stress-summer-research-program"
    raw = RawOpportunity("uiuc_sro", "https://researchops.web.illinois.edu/?page=9", "Stress", "", directory,
                         extra_fields={"deadline_raw": "Anticipated 2/15/27"})
    funded = normalize_award(award)
    listed = raw_to_normalized(raw)
    for row, date_text, host in (
        (funded, "2026-03-15", "https://med.und.edu/education-training/biomedical-sciences/reu/index.html"),
        (listed, "2027-02-10", "https://wiscience.wisc.edu/research/summer_research_program/"),
    ):
        assert (row["deadline"], row["is_rolling"], row["deadline_is_estimate"]) == (date_text, False, False)
        timing = build_detail_fields(copy.deepcopy(row), row)["fields"]["timing"]
        assert timing["explicit"]["deadline"] == date_text
        assert timing["quotes"]["deadline"]["source_url"] == host
        assert "deadline" not in row["metadata"].get("inferred_fields", {})
        assert not row["metadata"].get("deadline_note")
        for change in ({"id": "different"}, {"url": host}, {"source_url": host},
                       {"deadline": "2028-02-15", "deadline_is_estimate": True}):
            moved = {**row, **change}
            assert reviewed_window(moved) is None
            before = copy.deepcopy(moved)
            apply_program_window(moved)
            assert moved == before

    assert normalize_award({**award, "id": "2447670"})["deadline"] == "2026-02-15"
    assert normalize_award({**award, "startDate": "11/01/2026"})["deadline"] == "2027-02-15"
    raw.extra_fields = {"deadline_raw": "2/15/27", "deadline_anticipated": "No"}
    assert raw_to_normalized(raw)["deadline"] == "2027-02-15"
    raw.extra_fields = {"deadline_raw": "Anticipated 2/15/27", "program_url": "https://other.example.edu/"}
    assert raw_to_normalized(raw)["deadline_is_estimate"] is True


def test_fodommat_directory_and_host_share_the_stated_2027_calendar(tmp_path):
    from src.collectors.base import RawOpportunity
    from src.collectors.uiuc_sro import merge_into_processed, raw_to_normalized
    from src.normalizers import fodommat
    from src.program_windows import public_opening

    directory = (
        "https://researchops.web.illinois.edu/opportunity/"
        "future-discovery-training-students-build-and-apply-open-source-machine-learning-models"
    )
    host = "https://reu.ncsa.illinois.edu/"
    raw = RawOpportunity("uiuc_sro", "https://researchops.web.illinois.edu/?page=11", "FoDOMMaT", "", directory,
                         extra_fields={"deadline_raw": "Anticipated 3/15/27", "program_url": host})
    row = raw_to_normalized(raw)
    manual = _row("manual", "ext-uiuc-ncsa-reu")
    assert row["id"] == "sro-1532726e" and row["id"] != manual["id"]
    for record in (row, manual):
        assert record["deadline"] == "2027-02-15"
        assert record["deadline_is_estimate"] is False and record["is_rolling"] is False
        assert public_opening(record)["on"] == "2026-12-15"
        timing = build_detail_fields(copy.deepcopy(record), record)["fields"]["timing"]
        assert timing["quotes"]["deadline"]["source_url"] == host
        fields = build_detail_fields(copy.deepcopy(record), record)["fields"]
        assert fields["eligibility"]["explicit"]["majors"] == ["all"]
        assert fields["eligibility"]["quotes"]["class_year"]["source_url"] == host
        assert fields["required_skills"]["explicit"]["required"] == ["Python", "machine learning"]
        assert fields["required_skills"]["quotes"]["required"]["source_url"] == host
    assert row["metadata"]["superseded_directory_deadline"] == {
        "date": "2027-03-15", "anticipated": True, "source_url": directory,
    }
    current = copy.deepcopy(row)
    apply_program_window(row)
    assert row == current
    # A shallow same-cycle refresh can retain the verified host evidence.
    output = tmp_path / "sro.json"
    output.write_text(json.dumps([row]))
    raw.extra_fields = {"deadline_raw": "Anticipated 3/15/27"}
    merge_into_processed([raw_to_normalized(raw)], str(output))
    [merged] = json.loads(output.read_text())
    assert fodommat.host_quote(merged, "skills_required")
    # A reused directory, a different host, or the next year's call cannot.
    for changed in (
        {"deadline_raw": "Anticipated 3/15/28", "program_url": host},
        {"deadline_raw": "3/15/27", "deadline_anticipated": "No", "program_url": host},
        {"deadline_raw": "Anticipated 3/15/27", "program_url": "https://wiscience.wisc.edu/research/srp/"},
    ):
        raw.extra_fields = changed
        other = raw_to_normalized(raw)
        assert reviewed_window(other) is None and public_opening(other) is None
        assert "superseded_directory_deadline" not in other["metadata"]
        assert not fodommat.host_quote(other, "skills_required")
    output.write_text(json.dumps([row]))
    raw.extra_fields = {"deadline_raw": "Anticipated 3/15/28"}
    merge_into_processed([raw_to_normalized(raw)], str(output))
    [later] = json.loads(output.read_text())
    assert later["deadline"] == "2028-03-15" and later["eligibility"]["skills_required"] == []
    assert "superseded_directory_deadline" not in later["metadata"]
    later_manual = {**manual, "deadline": "2028-02-26"}
    apply_program_window(later_manual)
    assert later_manual["deadline"] == "2028-02-26"
    assert not fodommat.host_quote(later_manual, "skills_required")


def test_chen_institute_remains_a_reference_while_the_two_fellowships_have_separate_windows():
    institute = _row("caltech", "chen_institute")
    assert institute["metadata"]["reference_only"] is True
    assert institute["is_rolling"] is False
    assert not institute["metadata"]["deadline_note"]
    assert not institute["application"]["application_url"]
    assert not evidence.target_truth(institute).actionable
    timing = build_detail_fields(copy.deepcopy(institute), institute)["fields"]["timing"]
    assert not timing["explicit"].get("rolling")
    assert not timing["explicit"].get("application_window")
    assert _row("caltech", "wave_fellows")["deadline"] == "2027-01-08"
    assert _row("caltech", "surf")["deadline"] == "2027-02-22"


def test_wlu_dart_keeps_its_identity_and_closes_the_2026_neuroscience_fellowship(monkeypatch):
    row = _row("wlu", "wlu_dart")
    assert row["id"] == "wlu-88e9e20591ba"
    assert row["department"] == "Neuroscience Program"
    assert row["school"] == "wlu" and row["audience"] == "campus"
    assert row["on_campus"] is True  # All three host labs are on a university campus.
    assert row["location"] == "University of Illinois Chicago, University of Florida, or University of Michigan"
    assert row["eligibility"]["preferred_year"] == []
    assert row["paid"] == "stipend"
    assert (row["deadline"], row["is_rolling"]) == ("2026-02-08", False)
    assert "business research" not in row["keywords"]
    assert "University of Florida" in row["description"]
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 26))
    truth = evidence.target_truth(data_loader._sanitize_opportunity(row))
    assert (truth.actionable, truth.reason_code) == (False, "listing_closed")


@pytest.mark.parametrize(("school", "key", "stored_id"), [
    ("ucr", "ucr_cnas_student_research", "ucr-e08f03f0945b"),
    ("umd", "honors_college", "umd-54542deb3560"),
    ("udel", "udel_undergraduate_research_program", "udel-f6a5e4ea0f51"),
    ("bc", "bc_undergrad_research_opportunities", "bc-ec4ea5f74178"),
])
def test_program_directories_never_inherit_a_linked_awards_requirements(school, key, stored_id):
    from src.normalizers.enricher import enrich_opportunity
    from src.parsers import llm_tagger

    config, source, spec = _spec(school, key)
    # A new deep crawl can find genuine requirements for an individual award
    # on a directory. They do not become requirements for the whole directory.
    row = cg._normalize_program(config, source, spec, status="open", seed_page_verified=True,
                                extra_desc="The award pays a stipend to senior Biology students. Python required.")
    enrich_opportunity(row)
    assert row["id"] == stored_id
    assert row["source_url"] == spec["url"] and row["application"]["application_url"] is None
    assert evidence.target_truth(row).reason_code == "reference_only"
    assert row["is_rolling"] is False and row["paid"] == "unknown"
    assert not any(row["eligibility"][field] for field in ("preferred_year", "majors", "skills_required"))
    assert not llm_tagger.needs_tagging(row) and llm_tagger.rule_based_tag(row) == {}
    assert not llm_tagger.apply_updates(row, {"paid": "yes", "preferred_year": ["senior"]})


def test_duke_focus_preference_window_is_cohort_specific(monkeypatch):
    row = _row("duke", "focus_program")
    assert row["id"] == "duke-0ad241611979" and row["is_rolling"] is False
    assert row["deadline"] == "2026-05-13" and not row["metadata"].get("reference_only")
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 26))
    assert evidence.target_truth(row).reason_code == "listing_closed"


def test_wisconsin_host_dates_survive_a_refresh_of_the_preferred_directory_id_and_alias(tmp_path):
    from src.collectors.base import RawOpportunity
    from src.collectors.uiuc_sro import merge_into_processed, raw_to_normalized
    from src.matcher.ranker import _filter_context, hard_exclusion
    from src.normalizers import host_program_terms
    from src.normalizers.wisc_biological_interactions import SUMMARY, SUPPORT
    from src.program_windows import public_opening
    from src.saved_searches.filter import match_filter

    directory = "https://researchops.web.illinois.edu/opportunity/cellular-and-molecular-biology-stress-summer-research-program"
    old_host = "https://wiscience.wisc.edu/IBS-SRP"
    host = "https://wiscience.wisc.edu/research/summer_research_program/"
    host_record = _row("wisc", "ibs_srp_cmbs_reu")
    original_id = host_record["id"]
    assert original_id == "wisc-86cba49b83d7"

    def source_row(page, program_url, raw_date="Anticipated 2/15/27"):
        return raw_to_normalized(RawOpportunity(
            "uiuc_sro", "https://researchops.web.illinois.edu/?page=9",
            "Cellular and Molecular Biology of Stress Summer Research Program", "", page,
            organization="University of Wisconsin-Madison",
            extra_fields={"deadline_raw": raw_date, "program_url": program_url},
        ))

    preferred = source_row(directory + "-0", old_host)
    alias = source_row(directory, "https://wiscience.wisc.edu/research/srp/")
    for row in (host_record, preferred, alias):
        assert row["deadline"] == "2027-02-10" and not row["is_rolling"] and not row["deadline_is_estimate"]
        opens = public_opening(row)
        assert (opens["on"], opens["source_url"]) == ("2026-11-01", host)
        timing = build_detail_fields(copy.deepcopy(row), row)["fields"]["timing"]
        assert timing["quotes"]["deadline"]["source_url"] == host
        assert SUMMARY in row["description_clean"] and "excluded by funding rules" not in row["description_clean"]
        assert row["paid"] == "yes" and row["compensation_details"] == SUPPORT and row["duration"] == "10 weeks"
        assert row["eligibility"]["min_gpa"] is None and row["eligibility"]["preferred_year"] == []
        loaded = data_loader._sanitize_opportunity(copy.deepcopy(row))
        assert loaded["description_clean"].count("UW–Madison students may apply") == 1
        student = {"home_school": "wisc", "year": "freshman", "major": "Biology", "gpa": 2.8}
        assert hard_exclusion(loaded, _filter_context(student)) is None
        card = project_public_opportunity_payload(loaded, loaded)
        assert card["paid"] == "yes" and not card.get("paid_attribution")
        assert not card.get("compensation_attribution")
        assert match_filter(loaded, {"paid": "yes"}) and not match_filter(loaded, {"paid": "no"})
        funding = build_detail_fields(card, loaded)["fields"]["funding"]
        assert funding["explicit"]["compensation"] == SUPPORT
        assert funding["quotes"]["paid"]["source_url"] == host
    assert preferred["metadata"]["superseded_directory_deadline"]["source_url"] == directory + "-0"
    output = tmp_path / "programs.json"
    output.write_text(json.dumps([host_record, alias, preferred]))
    merge_into_processed([preferred, alias], str(output))
    result = {r["id"]: r for r in json.loads(output.read_text())}
    assert set(result) == {"sro-595e912d", "sro-3c378261", original_id}
    assert result["sro-595e912d"]["metadata"]["is_active"] is True
    assert result["sro-3c378261"]["metadata"]["duplicate_of"] == "sro-595e912d"
    assert result["sro-3c378261"]["metadata"]["is_active"] is False
    for other in (
        {**host_record, "deadline": "2028-02-09"},
        {**host_record, "id": "different-campus-record"},
        {**preferred, "organization": "Another University"},
        source_row(directory + "-0", old_host, "Anticipated 2/15/28"),
        source_row(directory + "-0", "https://example.edu/unrelated"),
    ):
        assert reviewed_window(other) is None and public_opening(other) is None
        before = copy.deepcopy(other)
        host_program_terms.apply_terms(other)
        assert other == before and host_program_terms.quote(other, "paid") is None
    # The same-cycle shallow retry must retain the last deep source paragraph.
    preferred["description_clean"] += "\n\nPrevious deep source paragraph."
    preferred["description_raw"] = "Previous deep source paragraph."
    output.write_text(json.dumps([host_record, alias, preferred]))
    shallow = source_row(directory + "-0", directory + "-0")
    shallow["organization"] = ""
    merge_into_processed([shallow], str(output))
    same = next(r for r in json.loads(output.read_text()) if r["id"] == preferred["id"])
    assert same["description_clean"].count("Previous deep source paragraph.") == 1
    assert same["description_clean"].count(SUMMARY) == 1
    new_cycle = source_row(directory + "-0", old_host, "Anticipated 2/15/28")
    new_cycle["description_clean"] = new_cycle["description_raw"] = "New cohort eligibility is pending."
    for _ in range(2):
        merge_into_processed([copy.deepcopy(new_cycle)], str(output))
        current = next(r for r in json.loads(output.read_text()) if r["id"] == preferred["id"])
        assert current["description_clean"] == current["description_raw"] == "New cohort eligibility is pending."
        assert current["deadline"] == "2028-02-15" and current["compensation_details"] != SUPPORT




def test_ligo_surf_keeps_its_two_application_routes_separate():
    emitted = _row("caltech", "ligo_surf")
    assert emitted["id"] == "caltech-acdbfe29c21d"
    assert emitted["source_url"] == "https://ligosurf.caltech.edu/apply"
    assert emitted["application"]["application_url"] == emitted["source_url"]
    assert emitted["deadline"] is None
    assert emitted["is_rolling"] is False
    terms = emitted["metadata"]["deadline_note"]
    assert "NSF ETAP close January 15, 2027" in terms
    assert "applications close January 5, 2027" in terms
    assert "reference letters are due January 10, 2027" in terms
    eligibility = emitted["eligibility"]
    assert eligibility["citizenship_required"] is None
    assert eligibility["international_friendly"] == "unknown"
    assert "U.S. national status" in eligibility["work_auth_notes"]
    assert "institutions in India" in eligibility["work_auth_notes"]
    assert evidence.configured_note_last_date(emitted) == date(2027, 1, 15)


def test_crisp_and_smu_refresh_only_the_reviewed_opportunities_and_cohorts(monkeypatch, tmp_path):
    from src.collectors.base import RawOpportunity
    from src.collectors.nsf_reu import normalize_award
    from src.collectors.uiuc_sro import raw_to_normalized
    from src.program_windows import public_opening
    from src.reviewed_program_pairs import SMU, pairs_in_records
    from src.saved_searches.filter import matching_ids

    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 26))
    award = {
        "id": "2447670", "title": "REU Site: Advancing Data Science in the Public Interest",
        "awardeeName": "Southern Methodist University", "startDate": "12/01/2025",
    }
    crisp_url = "https://researchops.web.illinois.edu/opportunity/cancer-research-internship-summer-program-crisp"
    crisp_host = "https://cancer.iu.edu/education/summer/acs-cancer-research-internship.html"
    smu_host = (
        "https://www.smu.edu/Provost/saes/academic-enrichment/engaged-learning/"
        "research/research-experiences-undergraduates/data-science-reu"
    )

    def directory(url, deadline, host):
        return raw_to_normalized(RawOpportunity(
            "uiuc_sro", "https://researchops.web.illinois.edu/?page=4", "Program", "", url,
            extra_fields={"deadline_raw": "Anticipated " + deadline, "program_url": host},
        ))

    grant = normalize_award(award)
    smu = directory(SMU.directory_url, "2/15/27", smu_host)
    crisp = directory(crisp_url, "2/1/27", crisp_host)
    for row, close, opening, page in (
        (crisp, "2027-01-31", "2026-11-15", crisp_host),
        (grant, "2027-02-22", "2026-11-19", SMU.window.page),
        (smu, "2027-02-22", "2026-11-19", SMU.window.page),
    ):
        assert row["deadline"] == close and not row["deadline_is_estimate"] and not row["is_rolling"]
        assert public_opening(row)["on"] == opening
        timing = build_detail_fields(copy.deepcopy(row), row)["fields"]["timing"]
        assert timing["explicit"]["deadline"] == close and timing["quotes"]["deadline"]["source_url"] == page
        first = copy.deepcopy(row)
        apply_program_window(row)
        assert row == first
    from src.normalizers import host_program_terms
    for row in (grant, smu):
        fields = build_detail_fields(copy.deepcopy(row), row)["fields"]
        assert fields["funding"]["explicit"]["compensation"] == "$5,600 stipend"
        assert fields["timing"]["explicit"]["duration"] == "8 weeks"
        assert fields["funding"]["quotes"]["compensation"]["source_url"].startswith("https://www.smu.edu/")
        assert row["eligibility"]["skills_required"] == [] and row["eligibility"]["preferred_year"] == ["sophomore", "junior"]
        details = fields["eligibility"]
        assert details["explicit"]["work_authorization_notes"] == "U.S. citizen or permanent resident"
        assert details["explicit"]["international_students"] == "no" and details["explicit"]["citizenship"] == "required"
        for key in ("work_authorization_notes", "international_students", "citizenship"):
            assert details["quotes"][key]["source_url"].startswith("https://www.smu.edu/")
        assert host_program_terms.quote({**row, "compensation_details": "$4,800"}, "compensation") is None
    crisp_fields = build_detail_fields(copy.deepcopy(crisp), crisp)["fields"]
    assert crisp_fields["funding"]["quotes"]["paid"]["source_url"] == crisp_host
    assert crisp_fields["eligibility"]["explicit"]["min_gpa"] == 3.2
    assert crisp_fields["location"]["explicit"] == {"location": "Indianapolis, IN", "remote_option": "no"}
    assert crisp_fields["location"]["quotes"]["location"]["source_url"] == "https://cancer.iu.edu/education/summer/index.html"
    assert grant["metadata"]["superseded_work_auth_notes"]["basis"] == "nsf_reu_solicitation"
    assert grant["start_date"] is None and grant["metadata"]["nsf_award_start_date"] == "12/01/2025"
    assert grant["application"]["application_url"] == SMU.window.page
    assert grant["metadata"]["superseded_award_deadline_estimate"]["date"] == "2026-02-15"
    assert smu["metadata"]["superseded_directory_deadline"]["date"] == "2027-02-15"
    assert crisp["metadata"]["superseded_directory_deadline"]["date"] == "2027-02-01"
    assert pairs_in_records([crisp, smu, grant]) == (SMU,)
    assert matching_ids([smu, grant], {}) == [SMU.host_id]
    assert matching_ids([smu, grant], {"source": "uiuc_sro"}) == [SMU.directory_id]
    assert matching_ids([smu, grant], {"source": "nsf_reu"}) == [SMU.host_id]
    assert matching_ids([smu, grant], {}, preferred_ids=[SMU.directory_id]) == [SMU.directory_id]
    later = directory(SMU.directory_url, "2/15/28", smu_host)
    assert later["deadline"] == "2028-02-15" and later["deadline_is_estimate"]
    assert pairs_in_records([later, grant]) == ()
    from src.collectors.uiuc_sro import merge_into_processed
    for old, new in ((smu, later), (crisp, directory(crisp_url, "2/1/28", crisp_url))):
        stored = tmp_path / (old["id"] + ".json")
        stored.write_text(json.dumps([old]))
        merge_into_processed([new], str(stored))
        [changed] = json.loads(stored.read_text())
        assert changed["deadline"].startswith("2028") and changed["deadline_is_estimate"]
        assert changed["eligibility"]["min_gpa"] is None and changed["paid"] == new["paid"] != "yes"
        assert changed["compensation_details"] != "$5,600 stipend" and host_program_terms.checked_window(changed) is None
        assert changed["location"] != "Indianapolis, IN" and changed["eligibility"]["work_auth_notes"] != "U.S. citizen or permanent resident"
    for item in (directory(crisp_url, "2/1/27", smu_host), directory(SMU.directory_url, "2/15/27", crisp_host),
                 normalize_award({**award, "awardeeName": "Another university"}),
                 normalize_award({**award, "title": "REU Site: Different program"}),
                 normalize_award({**award, "startDate": "12/01/2027"})):
        assert reviewed_window(item) is None and item["deadline_is_estimate"]

    # A legacy partial input may contain the new external link but no deep
    # capture receipt. Never restore the prior program behind its back.
    moved = directory(SMU.directory_url, "2/15/27", crisp_host)
    stored = tmp_path / "redirected.json"
    stored.write_text(json.dumps([smu]))
    merge_into_processed([moved], str(stored))
    [merged] = json.loads(stored.read_text())
    assert merged["application"]["application_url"] == crisp_host
    assert merged["deadline"] == "2027-02-15" and merged["deadline_is_estimate"]
    assert merged["compensation_details"] != "$5,600 stipend" and reviewed_window(merged) is None


def test_boston_stars_student_deadline_and_current_application_destination(tmp_path):
    from src.collectors.base import RawOpportunity
    from src.collectors.uiuc_sro import merge_into_processed, raw_to_normalized
    from src.matcher.ranker import _filter_context, _requires_graduate_standing, hard_exclusion, rank_opportunity
    from src.normalizers import bu_stars
    from src.normalizers.school_audience import apply_school_audience
    from src.program_windows import STARS_HOST, STARS_OLD_HOST

    prefix = "https://researchops.web.illinois.edu/opportunity/summer-training-research-scholars"

    def directory(suffix, date_text, link, university="Boston University"):
        raw = RawOpportunity(
            "uiuc_sro", "https://researchops.web.illinois.edu/?page=4",
            "Summer Training as Research Scholars", "", prefix + suffix,
            organization=university, extra_fields={"deadline_raw": date_text, "program_url": link},
        )
        return raw_to_normalized(raw)

    campus = _row("bu", "stars")
    assert campus["id"] == "bu-bbc659c6ac92"
    current = directory("-stars-program", "2/1/27", STARS_HOST)
    alias = directory("-program-stars", "Anticipated 2/1/27", STARS_OLD_HOST)
    for row in (campus, current, alias):
        assert row["deadline"] == "2027-01-15" and row["is_rolling"] is False
        assert row["deadline_is_estimate"] is False and row["application"]["application_url"] == STARS_HOST
        quote = build_detail_fields(copy.deepcopy(row), row)["fields"]["timing"]["quotes"]["deadline"]
        assert quote["source_url"] == STARS_HOST and "11:59pm" in quote["text"]
        assert row["eligibility"]["preferred_year"] == ["sophomore", "junior"]
        assert row["eligibility"]["majors"] == [] and row["eligibility"]["min_gpa"] == 3.0
        assert row["application"]["requires_recommendation"] == "yes"
        apply_school_audience([row])
        assert row["audience"] == "open" and row["opportunity_type"] == "summer_program"
        loaded = data_loader._sanitize_opportunity(copy.deepcopy(row))
        # A domestic two-year student outside BU and from a differently named
        # STEM major can still discover the host record. The funding bar is real.
        student = {"home_school": "uiuc", "year": "sophomore", "major": "Geoscience", "gpa": 2.9}
        assert hard_exclusion(loaded, _filter_context(student)) is None
        assert hard_exclusion(loaded, _filter_context({**student, "international_student": True})) == "citizenship_restricted"
        ranked = rank_opportunity(student, loaded)
        assert "opportunity.majors" not in ranked.unknowns and "profile.gpa" in ranked.unknowns
        assert all("graduate / PhD" not in reason and "Limited prior experience" not in reason for reason in ranked.reasons_gap)
        prep = {**loaded, "description_clean": "Scholars learn how the PhD program in biomedical science reviews applications."}
        assert not _requires_graduate_standing(prep)
        assert _requires_graduate_standing({**prep, "id": "unreviewed"})
        card = project_public_opportunity_payload(loaded, loaded)
        assert "preferred_year_attribution" not in card and "international_attribution" not in card
        fields = build_detail_fields(card, loaded)["fields"]
        eligibility, materials = fields["eligibility"], fields["application_method"]
        assert eligibility["explicit"]["min_gpa"] == 3.0
        assert eligibility["explicit"]["class_year"] == ["sophomore", "junior"]
        assert eligibility["explicit"]["citizenship"] == "required"
        assert "STEM" in eligibility["explicit"]["degree_path"] and "2028" in eligibility["explicit"]["degree_path"]
        assert "interest" in eligibility["explicit"]["research_background"]
        assert "optional" in eligibility["explicit"]["research_background"]
        assert "explain" in eligibility["explicit"]["gpa_context"]
        assert "admitted" in eligibility["explicit"]["transfer_students"]
        assert "first year at Boston University" in eligibility["explicit"]["medical_students"]
        assert eligibility["explicit"]["majors"] == "STEM" and "majors" not in eligibility["inferred"]
        assert materials["explicit"]["requirements"] == ["three_recommendations"]
        assert "February 1" in materials["explicit"]["recommendation_deadline"]
        assert "2027" not in materials["explicit"]["recommendation_deadline"]
        for key in ("min_gpa", "degree_path", "class_year", "citizenship", "research_background"):
            assert eligibility["quotes"][key]["source_url"] == STARS_HOST
        for key in ("transfer_students", "medical_students", "gpa_context"):
            assert eligibility["quotes"][key]["source_url"] == bu_stars.FAQ
        assert materials["quotes"]["recommendation_deadline"]["source_url"] == bu_stars.FAQ
        first = copy.deepcopy(row)
        apply_program_window(row)
        bu_stars.apply_terms(row)
        assert row == first
    for row, anticipated in ((current, False), (alias, True)):
        assert row["metadata"]["superseded_directory_deadline"] == {
            "date": "2027-02-01", "anticipated": anticipated, "source_url": row["url"],
        }

    changed = directory("-stars-program", "2/1/28", STARS_HOST)
    stored = tmp_path / "stars.json"
    stored.write_text(json.dumps([current]))
    merge_into_processed([changed], str(stored))
    [new] = json.loads(stored.read_text())
    assert new["deadline"] == "2028-02-01" and reviewed_window(new) is None
    assert new["eligibility"]["min_gpa"] is None and new["application"]["requires_recommendation"] == "unknown"
    assert not list(bu_stars.detail_facts(new, "eligibility"))
    for unmatched in (
        directory("-program", "2/1/27", STARS_OLD_HOST),
        directory("-stars-program", "2/1/27", "https://www.example.edu/other"),
        directory("-stars-program", "2/1/27", STARS_HOST, university="Another school"),
        {**campus, "deadline": "2028-01-10"},
    ):
        assert reviewed_window(unmatched) is None
        assert not list(bu_stars.detail_facts(unmatched, "eligibility"))
    archived = copy.deepcopy(alias)
    archived["id"] = "sro-51c40e5b"
    archived["metadata"]["is_active"] = False
    assert not list(bu_stars.detail_facts(archived, "application_method"))

    stored.write_text(json.dumps([current]))
    changed_host = directory("-stars-program", "2/1/27", "https://www.example.edu/another-program")
    merge_into_processed([changed_host], str(stored))
    [new] = json.loads(stored.read_text())
    assert reviewed_window(new) is None and new["deadline"] == "2027-02-01"
    assert new["application"]["application_url"] == "https://www.example.edu/another-program"
    assert new["eligibility"]["min_gpa"] is None and new["application"]["requires_recommendation"] == "unknown"
    stored.write_text(json.dumps([current]))
    changed_school = directory("-stars-program", "", STARS_HOST, university="Another school")
    merge_into_processed([changed_school], str(stored))
    [new] = json.loads(stored.read_text())
    assert new["organization"] == "Another school" and reviewed_window(new) is None
    assert new["eligibility"]["min_gpa"] is None and new["application"]["requires_recommendation"] == "unknown"


@pytest.mark.parametrize(("oid", "slug", "organization", "host", "first_deadline", "opening"), [
    ("sro-e74d89e9", "michigan-humanities-emerging-research-scholars-program-michhers",
     "University of Michigan", "https://rackham.umich.edu/prospective-students/michhers/", "Anticipated 2/10/27", "2026-12-02"),
    ("sro-7f860ddc", "microbiology-summer-undergraduate-research-program-microsurp-trainee-program",
     "McGovern Medical School", "https://med.uth.edu/mmg/summer-research-program/", "2/1/27", "2026-12-01"),
])
def test_host_window_survives_a_partial_directory_refresh_only_for_the_same_program_and_cohort(
    tmp_path, monkeypatch, oid, slug, organization, host, first_deadline, opening,
):
    from backend.routes.matches import _match_card
    from src.collectors.base import RawOpportunity
    from src.collectors.uiuc_sro import merge_into_processed, raw_to_normalized

    directory_url = "https://researchops.web.illinois.edu/opportunity/" + slug

    def observed(deadline=first_deadline, link=host, school=organization, deep=False):
        return raw_to_normalized(RawOpportunity(
            "uiuc_sro", "https://researchops.web.illinois.edu/?page=3", slug, "", directory_url, organization=school,
            extra_fields={"deadline_raw": deadline, "program_url": link, "deep_scraped": deep},
        ))

    original = observed(deep=True)
    assert original["id"] == oid and original["deadline"] == "2027-02-01"
    assert original["deadline_is_estimate"] is False and original["is_rolling"] is False
    assert ("superseded_directory_deadline" in original["metadata"]) == first_deadline.startswith("Anticipated")
    stored = tmp_path / "program.json"

    def reread(new):
        stored.write_text(json.dumps([original]))
        merge_into_processed([new], str(stored))
        [loaded] = json.loads(stored.read_text())
        return loaded

    for row in (original, reread(observed(link="", school="")), reread(observed(deadline="", link="", school=""))):
        fields = build_detail_fields(copy.deepcopy(row), row)["fields"]["timing"]
        assert fields["explicit"]["deadline"] == "2027-02-01"
        assert fields["quotes"]["deadline"]["source_url"] == host
        assert row["metadata"].get("superseded_directory_deadline") == original["metadata"].get("superseded_directory_deadline")
        card = _match_card(row)
        assert card["application_opens"]["on"] == opening and card["application_opens"]["source_url"] == host
        assert card["deadline"] == "2027-02-01" and card["is_rolling"] is False
        monkeypatch.setattr(evidence, "_today", lambda: date(2027, 2, 3))
        assert evidence.target_truth(row).actionable is False
    for observation in (observed("2/1/28", link="", school=""), observed(link="https://www.example.org/"),
                        observed(deadline="", school="Different sponsor")):
        row = reread(observation)
        assert reviewed_window(row) is None
        assert "application_opens" not in _match_card(row)
        assert "superseded_directory_deadline" not in row["metadata"]
        assert row["deadline"] == observation["deadline"]


def test_stanford_application_window_is_for_the_reviewed_cycle_and_source():
    row = _row("stanford", "ssrp_amgen_scholars")
    assert row["id"] == "stanford-1a20b2e045cf" and row["deadline"] == "2027-02-01"
    for mismatch in (
        {**row, "id": "another-campus-program"},
        {**row, "source": "unrelated"},
        {**row, "deadline": "2028-02-02"},
        {**row, "deadline": None, "metadata": {**row["metadata"], "deadline_note": "Applications for 2028."}},
    ):
        assert reviewed_window(mismatch) is None


def test_mcnair_student_portal_deadline_and_undergraduate_admissions(monkeypatch):
    from backend.routes.matches import _match_card
    from src.matcher.ranker import _requires_graduate_standing

    row = _row("ucsd", "mcnair")
    assert row["id"] == "ucsd-c6d547c9321a" and not _requires_graduate_standing(row)
    assert row["eligibility"]["majors"] == [] and row["eligibility"]["preferred_year"] == ["junior", "senior"]
    assert "2.8" in row["description"] and "3.0" in row["description"]
    assert row["application"]["application_url"] == "https://ucsd-research.academicworks.com/opportunities/2368"
    assert row["deadline"] == "2026-11-20" and row["is_rolling"] is False
    assert "November 11 priority" in row["metadata"]["deadline_note"] and "October 29" in row["metadata"]["deadline_note"]
    assert _match_card(row)["deadline"] == "2026-11-20"
    timing = build_detail_fields(copy.deepcopy(row), row)["fields"]["timing"]
    assert timing["quotes"]["deadline"]["source_url"] == row["url"]
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 26))
    assert evidence.target_truth(row).reason_code == "listing_closed"
    monkeypatch.setattr(evidence, "_today", lambda: date(2026, 11, 19))
    assert evidence.target_truth(row).actionable
    for changed in ({"url": row["url"] + "0"}, {"id": "another-mcnair"}, {"deadline": "2027-11-20"}):
        assert reviewed_window({**row, **changed}) is None


def test_calbridge_undergraduate_program_preserves_transfer_eligibility_and_its_own_website():
    from src.matcher.ranker import _requires_graduate_standing

    row = _row("ucsb", "cal_bridge")
    assert row["id"] == "ucsb-45d0bef1a207" and not _requires_graduate_standing(row)
    source = "https://calbridge.org/undergraduate-program/"
    assert row["source_url"] == row["url"] == row["application"]["application_url"] == source
    assert "Community College students transferring" in row["description"]
    assert set(row["eligibility"]["majors"]) == {"Physics", "Astronomy", "Computer Science", "Computer Engineering",
                                                "Mathematics", "Statistics"}
    assert "April" in row["metadata"]["deadline_note"] and "2026 cohort" in row["metadata"]["deadline_note"]
    assert row["deadline"] is None and row["is_rolling"] is False
    assert "Santa Barbara" not in row["location"] and row["organization"] == "Cal-Bridge"
