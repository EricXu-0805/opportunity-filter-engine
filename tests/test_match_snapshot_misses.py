"""What a match snapshot miss does before it ranks (M74).

The release and actionable filters read only the corpus, the release and the
UTC day, so they run once per corpus generation and UTC day, off the event
loop. A request that missed the snapshot store while another request's
ranking of the same profile finished uses that snapshot instead of ranking
the profile a second time.
"""

import asyncio
import os
import sys
from datetime import date

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.routes.matches as m_module
from backend.main import app
from src import evidence as evidence_module
from src.matcher import ranker
from tests.test_match_consistency import _profile, _varied_corpus

client = TestClient(app)
_TODAY = date(2026, 10, 11)


def _body(**profile_overrides) -> dict:
    return {
        "profile": _profile(**profile_overrides),
        "view": {"tab": "all", "today": _TODAY.isoformat()},
        "page_size": 5,
    }


@pytest.fixture
def corpus(monkeypatch):
    records = _varied_corpus()
    state = (
        ranker._corpus_ref,
        ranker._corpus_rows,
        ranker._static_cache,
        ranker._sim_matrix,
        dict(ranker._kw_word_res),
    )
    ranker.register_corpus(records)
    monkeypatch.setattr(m_module, "load_opportunities_generation", lambda: (records, "misses"))
    monkeypatch.setattr(m_module, "load_opportunities_by_id", lambda: {o["id"]: o for o in records})
    monkeypatch.setattr(m_module, "_SNAPSHOT_TTL_SECONDS", 300)
    utc = {"today": _TODAY}
    monkeypatch.setattr(evidence_module, "_today", lambda: utc["today"])
    m_module._match_snapshots.clear()
    yield {"records": records, "utc": utc}
    m_module._match_snapshots.clear()
    with ranker.corpus_generation_lock:
        (
            ranker._corpus_ref,
            ranker._corpus_rows,
            ranker._static_cache,
            ranker._sim_matrix,
            old_keyword_res,
        ) = state
        ranker._kw_word_res.clear()
        ranker._kw_word_res.update(old_keyword_res)


@pytest.fixture
def filter_calls(monkeypatch):
    """Each run of the actionable filter: whether an event loop was running in its thread."""
    calls: list[bool] = []
    real = m_module.actionable_opportunities

    def recording(records):
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        calls.append(on_loop)
        return real(records)

    monkeypatch.setattr(m_module, "actionable_opportunities", recording)
    return calls


def test_the_release_filters_run_once_per_corpus_and_utc_day(corpus, filter_calls, monkeypatch):
    first = client.post("/api/matches/view", json=_body())
    second = client.post("/api/matches/view", json=_body(major="Mathematics"))
    assert first.status_code == second.status_code == 200
    assert len(filter_calls) == 1, "two misses on one corpus and day filter it once"

    # A stated deadline closes a listing on a later UTC day.
    corpus["utc"]["today"] = date(2026, 10, 12)
    assert client.post("/api/matches/view", json=_body()).status_code == 200
    assert len(filter_calls) == 2

    reloaded = [dict(record) for record in corpus["records"]]
    ranker.register_corpus(reloaded)
    monkeypatch.setattr(m_module, "load_opportunities_generation", lambda: (reloaded, "reloaded"))
    assert client.post("/api/matches/view", json=_body()).status_code == 200
    assert len(filter_calls) == 3


def test_the_release_filters_never_run_on_the_event_loop(corpus, filter_calls):
    assert client.post("/api/matches/view", json=_body()).status_code == 200
    assert filter_calls == [False]


def test_a_retired_generation_is_filtered_but_not_kept(corpus, monkeypatch):
    retired = corpus["records"]
    monkeypatch.setattr(m_module, "_match_universe", None)
    m_module._activate_corpus_generation([dict(record) for record in retired])

    expected = m_module.actionable_opportunities(m_module.release_visible_opportunities(retired))
    assert m_module._release_universe(retired) == expected
    assert m_module._match_universe is None, "a reload retired this corpus while it was filtered"


class _StoreSeenBeforeTheOtherRankingLanded(dict):
    """The snapshot store as one request saw it on its first lookup: just
    before another request's ranking of the same profile stored its snapshot
    and left the in-flight table."""

    blind_next = False

    def get(self, key, default=None):
        if self.blind_next:
            self.blind_next = False
            return default
        return super().get(key, default)


def test_a_profile_is_not_ranked_again_when_its_snapshot_lands_mid_miss(corpus, monkeypatch):
    store = _StoreSeenBeforeTheOtherRankingLanded()
    monkeypatch.setattr(m_module, "_match_snapshots", store)
    rankings: list[str] = []
    real_rank = m_module.rank_visible_universe

    def counting_rank(profile, *args, **kwargs):
        rankings.append(profile["major"])
        return real_rank(profile, *args, **kwargs)

    monkeypatch.setattr(m_module, "rank_visible_universe", counting_rank)

    ranked = client.post("/api/matches/view", json=_body())
    store.blind_next = True
    joined = client.post("/api/matches/view", json=_body())

    assert ranked.status_code == joined.status_code == 200
    assert rankings == ["CS"], "the second request must use the stored snapshot"
    assert joined.json() == ranked.json()
