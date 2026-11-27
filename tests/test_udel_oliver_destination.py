import json
from copy import deepcopy
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import udel_faculty

GSS = udel_faculty._GSS
PERSONAL = udel_faculty._OLIVER_PROFILE
MARINE = PERSONAL.removesuffix("matthew-oliver/")
OID = "faculty-udel-geol-cc0d1c3c"
OTHER_ID = "faculty-udel-smsp-496e2b15"


def page(html, requested, *, final=None):
    return ucb_common._mark_fetched_soup_observation(
        BeautifulSoup(html, "html.parser"), requested_url=requested, final_url=final or requested,
        observed_at="2026-11-26T17:28:01+00:00")


def card(name, link):
    return (f'<div class="media"><div class="media-content"><h4 class="media-heading">{name}</h4>'
            f'<span class="media-title">Professor</span><a href="{link}">Full profile &gt;</a>'
            '<div class="media-email"><a href="mailto:testfaculty@udel.example">Email</a></div></div></div>')


def test_normal_collect_merge_and_repeated_read_keep_original_and_email_evidence(monkeypatch, tmp_path):
    school = udel_faculty.SCHOOL
    units = [d for d in school["departments"] if d["short"] in ("GEOL", "SMSP")]
    monkeypatch.setattr(udel_faculty, "SCHOOL", dict(school, departments=units))
    monkeypatch.delenv("OFE_ENRICH_PROFILES", raising=False)
    corpus = tmp_path / "corpus.json"
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", corpus)
    corpus.write_text("[]")
    # Both actual departments use a relative off-unit href on the person's name card.
    c = card("Matthew Oliver", "/academics/colleges/ceoe/departments/smsp/faculty/matthew-oliver/")
    individual = page("<main><h1>Matthew Oliver</h1></main>", PERSONAL)
    responses = {GSS: page(c, GSS), MARINE: page(c, MARINE), PERSONAL: individual}
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url, **kwargs: responses[url])

    def cycle():
        ledger = {}
        with faculty_graph.run_start_ids({OID}):
            rows = udel_faculty.fetch_and_normalize(deep=True, unit_ledger=ledger)
        assert [r["id"] for r in rows] == [OID]
        assert set(ledger["geol"]["observed_entity_ids"]) == {OID}
        assert set(ledger["smsp"]["observed_entity_ids"]) == {OTHER_ID}
        udel_faculty.merge_into_processed(rows)
        [saved] = json.loads(corpus.read_text())
        return saved

    with patch.object(udel_faculty, "_read_oliver_destination"):
        original = cycle()
    assert original["url"] == original["source_url"] == GSS

    def check(expected):
        updated = cycle()
        assert updated["url"] == updated["source_url"] == expected
        assert updated["department"] == original["department"] and updated["id"] == OID
        assert updated["contact_email"] == original["contact_email"]
        assert {k: v for k, v in updated["metadata"].items() if "email" in k or "contact" in k} == {
            k: v for k, v in original["metadata"].items() if "email" in k or "contact" in k}
        return updated

    check(PERSONAL)
    responses[PERSONAL] = None
    check(GSS)
    responses[PERSONAL] = page("<main><h1>Another Person</h1></main>", PERSONAL)
    check(GSS)
    responses[PERSONAL] = individual
    check(PERSONAL)
    check(PERSONAL)


@pytest.mark.parametrize("case", ["other_name", "wrong_card", "duplicate_card", "ambiguous_link", "wrong_page", "duplicate_heading", "unread_roster", "redirect"])
def test_fail_closed_without_one_primary_card_and_one_personal_heading(monkeypatch, case):
    row = {"id": OID, "pi_name": "Matthew Oliver", "url": GSS, "source_url": GSS,
           "metadata": {"is_active": True, "verification_scope": "directory"}}
    original = deepcopy(row)
    primary_card = card("Matthew Oliver", PERSONAL)
    wrong = card("Other Person", PERSONAL)
    roster = primary_card
    individual = page("<main><h1>Matthew Oliver</h1></main>", PERSONAL)
    if case == "other_name":
        row["pi_name"] = "James Oliver"
        original = deepcopy(row)
    elif case == "wrong_card":
        roster = card("Matthew Oliver", GSS) + wrong
    elif case == "duplicate_card":
        roster = primary_card + primary_card
    elif case == "ambiguous_link":
        roster = primary_card.replace('</h4>', '</h4><a href="/another/">Full profile &gt;</a>')
    elif case == "wrong_page":
        individual = page("<h1>Different Oliver</h1>", PERSONAL)
    elif case == "duplicate_heading":
        individual = page("<h1>Matthew Oliver</h1><h1>Other Person</h1>", PERSONAL)
    elif case == "redirect":
        individual = page("<h1>Matthew Oliver</h1>", PERSONAL, final=PERSONAL+"new/")
    source = None if case == "unread_roster" else page(roster, GSS)
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url, **kwargs: {GSS: source, PERSONAL: individual}[url])
    udel_faculty._read_oliver_destination([row])
    assert row == original
