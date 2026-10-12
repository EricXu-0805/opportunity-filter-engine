"""Results-page view rows (M74): the view pass reads each card's own values
without projecting a card for every visible row.

A snapshot keeps one `_MatchViewRow` per visible row and projects cards only
for the rows a response serves. These tests hold the row built straight from
a canonical record equal to the row read off the full card, the view pass over
rows equal to the view pass over cards, and the page cards equal to
`_match_card`, so the switch cannot change a response.
"""

import copy
import os
import sys
from datetime import date

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.routes.matches as m_module
from backend.main import app
from backend.schemas import MatchViewState
from src.matcher import ranker
from src.matcher.ranker import MatchResult
from tests.test_public_contact_projection import CONTACT_VARIANTS

client = TestClient(app)


def _listing(ident: str, **overrides) -> dict:
    base = {
        "id": ident,
        "title": f"Robotics Research {ident}",
        "organization": "Example University",
        "department": "Computer Science",
        "opportunity_type": "research",
        "source": "example_board",
        "source_type": "campus_program",
        "school": "uiuc",
        "audience": "open",
        "paid": "yes",
        "on_campus": True,
        "is_rolling": False,
        "deadline": "2099-01-15",
        "posted_date": "2026-09-01",
        "url": f"https://example.edu/{ident}",
        "contact_email": f"{ident}@example.edu",
        "description_clean": "Machine learning for robot perception.",
        "keywords": ["machine learning", "robotics"],
        "eligibility": {"international_friendly": "yes", "skills_required": ["Python"]},
        "application": {"application_url": f"https://example.edu/{ident}/apply"},
        "metadata": {"is_active": True},
    }
    base.update(overrides)
    return base


def _faculty(ident: str, **overrides) -> dict:
    base = {
        "id": ident,
        "title": "Prof. Jane Doe",
        "pi_name": "Jane Doe",
        "faculty_title": "Lecturer",
        "organization": "Example University",
        "department": "Electrical & Computer Engineering",
        "opportunity_type": "research",
        "source": "example_faculty",
        "source_type": "faculty_research",
        "school": "ucb",
        "url": f"https://example.edu/people/{ident}",
        "description_clean": "Research on power electronics at example dot edu.",
        "keywords": ["power electronics", "control systems"],
        "eligibility": {"international_friendly": "yes", "majors": ["EECS"]},
        "application": {"application_url": f"https://example.edu/{ident}"},
        "metadata": {"is_active": True, "research_areas_raw": "Power & Energy"},
    }
    base.update(overrides)
    return base


def _records() -> list[dict]:
    """Records that exercise every step between a record and its card's view."""
    records = [
        _listing("plain"),
        _listing("title-email", title="Email jane@example.edu about the lab"),
        _listing("org-email", organization="jane at example dot edu"),
        _listing("dept-email", department="Contact: jane[at]example[dot]edu"),
        _listing("source-email", source="feed jane@example.edu"),
        _listing("school-email", school="jane@example.edu", audience="jane@example.edu"),
        _listing("paid-email", paid="jane@example.edu", posted_date="jane@example.edu"),
        _listing(
            "keywords-email",
            keywords=["machine learning", "coordinator@example.edu", 7, None,
                      ["nested", "jane@example.edu"], {"k": "jane@example.edu"}],
        ),
        _listing("intl-email", eligibility={"international_friendly": "jane@example.edu"}),
        _listing("eligibility-list", eligibility=["not", "a", "dict"]),
        _listing("suffix-open", title="Summer Lab (applications open)"),
        _listing("suffix-closed", title="Summer Lab (applications open)",
                 metadata={"is_active": True, "listing_status": "closed"}),
        _listing("passed", deadline="2020-01-01"),
        _listing("estimate", deadline_is_estimate=True),
        _listing("inferred-deadline",
                 metadata={"is_active": True, "inferred_fields": {"deadline": "estimate:award"}}),
        _listing("bad-deadline", deadline="soon"),
        _listing("no-description", description_clean=None,
                 description_raw="Raw text naming jane@example.edu"),
        _listing("empty-description", description_clean=""),
        _listing("no-title", title=None),
        _listing("numeric-title", title=12345),
        _listing("rolling", is_rolling=True, deadline=None),
        _listing("off-campus", on_campus=False, audience="unknown", school=None),
        _listing("no-scope", school=None),
        _listing("unknown-kind", source_type=None, title="Lab (applications open)"),
        _listing("unreviewed-kind", source_type="mystery_feed"),
        _listing("source-type-email", source_type="jane@example.edu"),
        _faculty("faculty"),
        _faculty("faculty-prof", faculty_title="Professor of EECS"),
        _faculty("faculty-email", description_clean="Write to jane.doe@example.edu."),
        _faculty("faculty-suffix", title="Jane Doe (applications open)", pi_name=""),
        _faculty("faculty-not-accepting",
                 description_clean="Not currently accepting undergraduate students."),
    ]
    for index, variant in enumerate(CONTACT_VARIANTS):
        records.append(_listing(f"variant-description-{index}", description_clean=variant))
        records.append(_listing(f"variant-title-{index}", title=f"Lab {variant}"))
        records.append(_listing(f"variant-keyword-{index}", keywords=["robotics", variant]))
    for record in records:
        if record.get("title") is None:
            del record["title"]
        if record.get("source_type") is None:
            del record["source_type"]
    return records


RECORDS = _records()


@pytest.mark.parametrize("record", RECORDS, ids=[record["id"] for record in RECORDS])
def test_the_row_built_from_the_record_is_the_row_read_off_its_card(record):
    before = copy.deepcopy(record)

    built = m_module._match_view_row(record)
    memoized = m_module._match_view_row(record, m_module._memoized(m_module.contains_embedded_email))
    read = m_module._view_row_from_card(m_module._match_card(record), record=record)

    assert built == read
    assert memoized == read
    assert built.record is record
    assert record == before, "building a view row must not touch the canonical record"


def _results(records: list[dict]) -> list[MatchResult]:
    buckets = ("high_priority", "good_match", "reach")
    return [
        MatchResult(
            opportunity_id=record["id"],
            eligibility_score=60.0,
            readiness_score=60.0,
            upside_score=60.0,
            final_score=40.0 + index % 50,
            bucket=buckets[index % 3],
            reasons_fit=[f"Fit {index}"],
            reasons_gap=[],
            next_steps=[],
            field_relevant=index % 2 == 0,
        )
        for index, record in enumerate(records)
    ]


_TODAY = date(2026, 10, 11).isoformat()
VIEWS = [
    {},
    {"tab": "all"},
    {"tab": "good_match"},
    {"tab": "reach"},
    {"tab": "starred", "favorite_ids": ["plain", "faculty", "title-email"]},
    {"tab": "all", "dismissed_ids": ["plain", "faculty"]},
    {"tab": "all", "dismissed_ids": ["plain"], "show_dismissed": True},
    {"tab": "all", "paid": "yes"},
    {"tab": "all", "paid": "no"},
    {"tab": "all", "intl": "yes"},
    {"tab": "all", "source": "example_faculty"},
    {"tab": "all", "source": "[email redacted]"},
    {"tab": "all", "on_campus": "yes"},
    {"tab": "all", "on_campus": "no"},
    {"tab": "all", "deadline": "rolling"},
    {"tab": "all", "deadline": "30"},
    {"tab": "all", "deadline": "passed"},
    {"tab": "all", "scope": "campus"},
    {"tab": "all", "scope": "open"},
    {"tab": "all", "min_score": 60},
    {"tab": "all", "sort_by": "newest"},
    {"tab": "all", "sort_by": "deadline"},
    {"tab": "all", "search_query": "machine learning"},
    {"tab": "all", "search_query": "ml"},
    {"tab": "all", "search_query": "edu"},
    {"tab": "all", "search_query": "@"},
    {"tab": "all", "search_query": "jane"},
    {"tab": "all", "search_query": "coordinator"},
    {"tab": "all", "search_query": "example"},
    {"tab": "all", "search_query": "email"},
    {"tab": "all", "search_query": "redacted"},
    {"tab": "all", "search_query": "["},
    {"tab": "all", "search_query": "lab"},
    {"tab": "all", "search_query": "fit 3"},
    {"tab": "high_priority", "search_query": "robotics", "sort_by": "deadline", "paid": "yes"},
]


@pytest.mark.parametrize("overrides", VIEWS, ids=[str(view) for view in VIEWS])
def test_the_view_pass_over_rows_answers_as_it_did_over_cards(overrides):
    results = _results(RECORDS)
    cards = {record["id"]: m_module._match_card(record) for record in RECORDS}
    rows = {record["id"]: m_module._match_view_row(record) for record in RECORDS}
    view = MatchViewState(**{"today": _TODAY, **overrides})

    on_cards = m_module._apply_match_view(results, cards, view, "uiuc")
    on_rows = m_module._apply_match_view_rows(results, rows, view, "uiuc")

    assert on_rows == on_cards


def test_a_redacted_contact_is_not_searchable():
    """Search reads the card's text, so an address the card hides finds nothing."""
    record = _listing(
        "hidden-contact",
        description_clean="Questions to jane.doe@example.edu about robot perception.",
        keywords=["robotics"],
    )
    rows = {record["id"]: m_module._match_view_row(record)}
    results = _results([record])

    def found(query: str) -> list[str]:
        view = MatchViewState(today=_TODAY, tab="all", search_query=query)
        filtered, *_ = m_module._apply_match_view_rows(results, rows, view, "uiuc")
        return [result.opportunity_id for result in filtered]

    assert found("robotics") == ["hidden-contact"]
    for query in ("jane.doe", "@", "example.edu", "robot perception"):
        assert found(query) == [], query


@pytest.fixture
def match_env(monkeypatch):
    from tests.test_match_consistency import _opp, _varied_corpus

    corpus = sorted(
        [*_varied_corpus(), _opp("opp-email", description_clean="Mail opp@example.edu")],
        key=lambda record: record["id"],
    )
    ranker_state = (
        ranker._corpus_ref,
        ranker._corpus_rows,
        ranker._static_cache,
        ranker._sim_matrix,
        dict(ranker._kw_word_res),
    )
    ranker.register_corpus(corpus)
    monkeypatch.setattr(m_module, "load_opportunities_generation", lambda: (corpus, "view-rows"))
    monkeypatch.setattr(m_module, "load_opportunities_by_id", lambda: {o["id"]: o for o in corpus})
    monkeypatch.setattr(m_module, "_SNAPSHOT_TTL_SECONDS", 300)
    m_module._match_snapshots.clear()
    yield corpus
    m_module._match_snapshots.clear()
    with ranker.corpus_generation_lock:
        (
            ranker._corpus_ref,
            ranker._corpus_rows,
            ranker._static_cache,
            ranker._sim_matrix,
            old_keyword_res,
        ) = ranker_state
        ranker._kw_word_res.clear()
        ranker._kw_word_res.update(old_keyword_res)


def test_a_page_projects_cards_only_for_its_own_rows(match_env, monkeypatch):
    from tests.test_match_consistency import _profile

    projected: list[str] = []
    real_match_card = m_module._match_card

    def counting_match_card(opportunity):
        projected.append(opportunity["id"])
        return real_match_card(opportunity)

    monkeypatch.setattr(m_module, "_match_card", counting_match_card)
    body = {"profile": _profile(), "view": {"tab": "all", "today": _TODAY}, "page_size": 3}

    response = client.post("/api/matches/view", json=body)

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["filtered_total"] > 3
    served = [row["opportunity_id"] for row in page["results"]]
    assert projected == served
    by_id = {record["id"]: record for record in match_env}
    for row in page["results"]:
        expected = m_module._public_match_payload(real_match_card(by_id[row["opportunity_id"]]))
        assert row["opportunity"] == expected

    # The next page projects its own rows; the first page's are kept.
    projected.clear()
    again = client.post("/api/matches/view", json=body)
    assert again.json() == page
    assert projected == []
    following = client.post("/api/matches/view", json={**body, "cursor": page["next_cursor"]})
    assert following.status_code == 200, following.text
    assert projected == [row["opportunity_id"] for row in following.json()["results"]]


def test_a_snapshot_is_not_served_into_the_next_utc_day(match_env, monkeypatch):
    """Cards are projected when a page is served and their truth reads the UTC
    day, so a list ranked on one UTC day is not served on the next even while
    the host's own calendar has not turned."""
    from src import evidence as evidence_module
    from tests.test_match_consistency import _profile

    utc = {"today": date(2026, 10, 11)}
    monkeypatch.setattr(evidence_module, "_today", lambda: utc["today"])
    rankings: list[int] = []
    real_rank = m_module.rank_visible_universe

    def counting_rank(*args, **kwargs):
        rankings.append(1)
        return real_rank(*args, **kwargs)

    monkeypatch.setattr(m_module, "rank_visible_universe", counting_rank)
    body = {"profile": _profile(), "view": {"tab": "all", "today": _TODAY}, "page_size": 3}

    assert client.post("/api/matches/view", json=body).status_code == 200
    assert client.post("/api/matches/view", json=body).status_code == 200
    assert len(rankings) == 1

    utc["today"] = date(2026, 10, 12)
    assert client.post("/api/matches/view", json=body).status_code == 200
    assert len(rankings) == 2


@pytest.fixture
def view_row_table(monkeypatch):
    monkeypatch.setattr(m_module, "_active_corpus_identity", None)
    monkeypatch.setattr(m_module, "_match_view_rows", {})
    monkeypatch.setattr(m_module, "_match_snapshots", {})
    built: list[str] = []
    real_row = m_module._match_view_row

    def recording_row(opportunity, redacts=m_module.contains_embedded_email):
        built.append(opportunity["id"])
        return real_row(opportunity, redacts)

    monkeypatch.setattr(m_module, "_match_view_row", recording_row)
    return built


def test_rows_of_the_active_generation_are_built_once(view_row_table):
    corpus = [_listing(f"kept-{n}") for n in range(3)]
    identity = m_module._activate_corpus_generation(corpus)
    ids = {record["id"] for record in corpus}

    first = m_module._snapshot_view_rows(corpus, ids, identity)
    again = m_module._snapshot_view_rows(corpus, ids, identity)

    assert view_row_table == [record["id"] for record in corpus]
    assert again == first
    assert all(first[record["id"]].record is record for record in corpus)


def test_a_reload_during_a_build_leaves_no_old_row_in_the_table(view_row_table, monkeypatch):
    """The ranking keeps its rows, but a reload that emptied the table while
    they were built must not find them there: each one holds an old record."""
    old = [_listing(f"old-{n}") for n in range(4)]
    new = [_listing(f"new-{n}") for n in range(4)]
    identity = m_module._activate_corpus_generation(old)
    recording_row = m_module._match_view_row

    def reloading_row(opportunity, redacts=m_module.contains_embedded_email):
        if len(view_row_table) == 1:
            m_module._activate_corpus_generation(new)
        return recording_row(opportunity, redacts)

    monkeypatch.setattr(m_module, "_match_view_row", reloading_row)

    rows = m_module._snapshot_view_rows(old, {record["id"] for record in old}, identity)

    assert m_module._active_corpus_identity == id(new)
    assert all(rows[record["id"]].record is record for record in old)
    assert m_module._match_view_rows == {}


def test_no_ascii_character_is_a_format_control():
    """contains_embedded_email skips the per-character format-control scan
    for ASCII text; that is exact only while no ASCII character is one."""
    import unicodedata

    from backend.lib.public_projection import _format_control_views

    assert not [code for code in range(128) if unicodedata.category(chr(code)) == "Cf"]
    for text in ("plain ascii text", "jane​@example.edu", "a­b﻿c", "用户⁠艾特"):
        spaced = "".join(" " if unicodedata.category(c) == "Cf" else c for c in text)
        removed = "".join(c for c in text if unicodedata.category(c) != "Cf")
        assert _format_control_views(text) == (spaced, removed)
