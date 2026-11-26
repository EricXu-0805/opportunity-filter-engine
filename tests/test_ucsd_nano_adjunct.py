from copy import deepcopy
from datetime import date

import pytest
from bs4 import BeautifulSoup

from backend.data_loader import _sanitize_opportunity
from backend.routes.opportunities import _redact
from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.ucsd_faculty import SCHOOL
from src.normalizers.reviewed_faculty_profiles import (
    REVIEWS,
    apply_reviewed_faculty_profile,
    carry_forward_reviewed_appointment,
)

NANO = next(dept for dept in SCHOOL["departments"] if dept["short"] == "NANO")
AS_OF = date(2026, 11, 26)
IDS = ["faculty-ucsd-nano-2aa92754", "faculty-ucsd-nano-04ac1d79", "faculty-ucsd-nano-27240933"]
ONG = "faculty-ucsd-nano-e94320ae"


def soup(html):
    return BeautifulSoup(html, "html.parser")


def roster(reviews, *, formal=False, modern_url=False):
    cards = []
    for review in reviews:
        name = review.name if formal else review.previous_name or review.name
        given, last = name.rsplit(" ", 1)
        href = review.profile_url if modern_url else review.previous_url
        cards.append(f'<tr><td><a href="{href}">{last}, {given}</a></td></tr>')
    return soup('<table><tbody><tr><td><strong>Professors</strong></td></tr>'
                + "".join(cards) + '<tr><td><a href="http://materialsvirtuallab.org/">Ong, Shyue Ping</a></td></tr>'
                + '</tbody></table>')


def personal(review, grades, name=None):
    return soup(f'<h3 class="faculty_profile_name">{name or review.name}</h3><p>' + "<br>".join(grades) + "</p>")


def current(review, rank, *, person=None, href=None):
    return soup(f'<div class="faculty-information"><h4><a href="{href or review.profile_url}">'
                f'{person or review.name}</a></h4><h5>{rank}</h5></div>')


def parse(monkeypatch, pages):
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        if url == NANO["scrape"]["extra_urls"][0]["url"] and url not in pages:
            return BeautifulSoup('<div class="faculty-information"><h4><a href="/other">Other Person</a></h4></div>', "html.parser")
        return pages[url]

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)
    rows = [faculty_graph._normalize(SCHOOL, NANO, person) for person in faculty_graph._scrape_directory(NANO)]
    return {row["id"]: row for row in rows}, calls


def historical(oid):
    review = REVIEWS[oid]
    row = faculty_graph._normalize(SCHOOL, NANO, {
        "name": review.previous_name or review.name, "url": review.previous_url, "title": "",
    })
    assert row['id'] == oid
    row['metadata'].update(last_seen_at='2026-07-24', last_verified='2026-07-24')
    return row


def test_three_official_adjunct_ranks_do_not_enter_the_ladder_roster(monkeypatch):
    reviews = [REVIEWS[oid] for oid in IDS]
    pages = {NANO["directory_url"]: roster(reviews)}
    for review in reviews:
        pages[review.profile_url] = personal(review, ["Adjunct Professor, NENG", "Faculty-Affiliate, ECE"])
    rows, requested = parse(monkeypatch, pages)
    assert list(rows) == [ONG]
    assert set(requested) == set(pages) | {NANO["scrape"]["extra_urls"][0]["url"]} and len(requested) == 5


@pytest.mark.parametrize("oid", IDS)
@pytest.mark.parametrize("modern_url", [True, False])
def test_two_matching_current_sources_restore_the_original_id(monkeypatch, oid, modern_url):
    review = REVIEWS[oid]
    pages = {NANO["directory_url"]: roster([review], formal=True, modern_url=modern_url),
             review.profile_url: personal(review, ["Associate Professor, NENG", "Faculty-Affiliate, ECE"]),
             review.roster_url: current(review, "Associate Professor", person=review.previous_name or review.name)}
    rows, calls = parse(monkeypatch, pages)
    assert set(rows) == {oid, ONG}
    assert len(calls) == 4
    prior = historical(oid)
    assert apply_reviewed_faculty_profile(prior, today=AS_OF)
    recovered = rows[oid]
    carry_forward_reviewed_appointment(prior, recovered)
    assert recovered["metadata"]["faculty_title"] == "Associate Professor"
    assert recovered["metadata"]["is_active"] is True
    assert not apply_reviewed_faculty_profile(recovered, today=AS_OF)


@pytest.mark.parametrize("failure", ["jacobs_unavailable", "directory_unavailable", "current_directory_adjunct",
                                     "directory_wrong_person", "directory_wrong_url", "jacobs_other_unit"])
def test_only_one_ladder_source_or_failed_read_keeps_archived_history(monkeypatch, failure):
    oid = IDS[-1]
    review = REVIEWS[oid]
    bio = personal(review, ["Faculty-Affiliate, NENG", "Professor, ECE"] if failure == "jacobs_other_unit"
                   else ["Professor, NENG", "Faculty-Affiliate, ECE"])
    directory = current(review, "Adjunct Professor" if failure == "current_directory_adjunct" else "Professor",
                        person="Different Person" if failure == "directory_wrong_person" else None,
                        href="https://example.edu/other" if failure == "directory_wrong_url" else None)
    pages = {NANO["directory_url"]: roster([review]), review.profile_url: None if failure == "jacobs_unavailable" else bio,
             review.roster_url: None if failure == "directory_unavailable" else directory}
    rows, _ = parse(monkeypatch, pages)
    fresh = rows[oid]
    assert not fresh["metadata"]["faculty_title"]
    old = historical(oid)
    assert apply_reviewed_faculty_profile(old, today=AS_OF)
    carry_forward_reviewed_appointment(old, fresh)
    assert fresh["metadata"]["deactivation_reason"] == "outside_unit_ladder"
    assert fresh["metadata"]["is_active"] is False
    assert fresh["metadata"]["deactivated_at"] == old["metadata"]["deactivated_at"]


@pytest.mark.parametrize("oid", IDS)
def test_old_row_is_archived_without_disowning_a_different_appointment(oid):
    review = REVIEWS[oid]
    original = historical(oid)
    foreign = deepcopy(original)
    foreign["department"] = "Department of Bioengineering"
    assert not apply_reviewed_faculty_profile(foreign, today=AS_OF)
    assert foreign["metadata"]["is_active"] is True
    old = deepcopy(original)
    old["metadata"]["contact_instruction_capture"] = {
        "version": 1, "status": "empty", "reason": None, "attempted_at": "2026-11-27T08:00:00+00:00",
        "source_url": review.previous_url, "record_source_url": review.previous_url,
        "requested_source_url": review.previous_url, "identity_name": old["pi_name"],
    }
    assert apply_reviewed_faculty_profile(old, today=date(2026, 11, 27), classify_title=False)
    assert old["url"] == review.profile_url
    assert old["metadata"]["is_active"] is False
    assert old["metadata"]["faculty_title"] == "Adjunct Professor"
    assert old["metadata"]["deactivation_reason"] == "outside_unit_ladder"
    assert old["metadata"]["faculty_profile_review"]["source_url"] == review.roster_url
    assert old["metadata"]["last_seen_at"] == "2026-07-24"
    public = _redact(_sanitize_opportunity(original))
    assert public["id"] == oid and public["pi_name"] == review.name
    assert public["url"] == public["source_url"] == review.profile_url
    assert public["target_truth"]["actionable"] is False
