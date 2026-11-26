"""A corpus reload frees the previous generation's match state (M74).

Match snapshots, view rows and the filtered universe hold records of the
generation they were built from. The loader activates a generation as it
publishes it, so the old records are freed then, not at the next match
request, as when snapshots held copied cards.
"""

import gc
import json
import os
import sys
import weakref
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.routes.matches as m_module
from backend import data_loader
from backend.lib.contact_visibility import build_identity_bound_contact_evidence
from backend.main import app
from src.matcher import embeddings, ranker
from tests.test_match_consistency import _opp, _profile, _varied_corpus

client = TestClient(app)


class _Probe:
    """Rides in every record of one generation; alive while any of them is."""


@pytest.fixture
def shards(tmp_path, monkeypatch):
    saved = (
        data_loader._opp_cache,
        data_loader._opp_cache_by_id,
        data_loader._opp_cache_mtime,
        data_loader._opp_cache_generation,
        data_loader._tfidf_fitted_mtime,
        embeddings._tfidf_vectorizer,
        embeddings._tfidf_fitted,
        ranker._corpus_ref,
        ranker._corpus_rows,
        ranker._static_cache,
        ranker._static_texts,
        ranker._rank_contact_cache,
        ranker._sim_matrix,
        dict(ranker._kw_word_res),
    )
    data_loader._opp_cache = []
    data_loader._opp_cache_by_id = {}
    data_loader._opp_cache_mtime = 0
    (tmp_path / "shards").mkdir()
    monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
    monkeypatch.setattr(m_module, "_SNAPSHOT_TTL_SECONDS", 300)
    monkeypatch.setattr(m_module, "_active_corpus_identity", None)
    monkeypatch.setattr(m_module, "_match_view_rows", {})
    monkeypatch.setattr(m_module, "_match_snapshots", {})
    monkeypatch.setattr(m_module, "_match_universe", None)
    yield tmp_path / "shards" / "all.json"
    (
        data_loader._opp_cache,
        data_loader._opp_cache_by_id,
        data_loader._opp_cache_mtime,
        data_loader._opp_cache_generation,
        data_loader._tfidf_fitted_mtime,
        embeddings._tfidf_vectorizer,
        embeddings._tfidf_fitted,
        ranker._corpus_ref,
        ranker._corpus_rows,
        ranker._static_cache,
        ranker._static_texts,
        ranker._rank_contact_cache,
        ranker._sim_matrix,
        old_keyword_res,
    ) = saved
    ranker._kw_word_res.clear()
    ranker._kw_word_res.update(old_keyword_res)


def test_publishing_a_reload_frees_the_previous_generation(shards):
    shards.write_text(json.dumps(_varied_corpus()))
    old = data_loader.load_opportunities()
    m_module.prepare_match_views(old)
    body = {"profile": _profile(), "view": {"tab": "all", "today": "2026-10-11"}, "page_size": 3}
    response = client.post("/api/matches/view", json=body)
    assert response.status_code == 200, response.text
    assert m_module._match_snapshots and m_module._match_view_rows
    assert m_module._match_universe is not None
    probe = _Probe()
    for record in old:
        record["probe"] = probe
    released = weakref.ref(probe)
    del old, probe, record, response

    shards.write_text(json.dumps(_varied_corpus()))
    stat = shards.stat()
    os.utime(shards, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    new = data_loader.load_opportunities()
    gc.collect()

    assert released() is None, "the old generation outlived its publish"
    assert m_module._active_corpus_identity == id(new)
    assert m_module._match_snapshots == {} and m_module._match_view_rows == {}
    assert m_module._match_universe is None


def test_incomplete_smaller_refresh_preserves_cached_ranks_and_can_retry(shards, monkeypatch):
    # The last old row is outside the smaller candidate's index range.
    old = [_opp(str(index), contact_email="researcher@example.edu",
                application={"contact_method": "email"}) for index in range(4)]
    shards.write_text(json.dumps(old))
    original = data_loader.load_opportunities()
    profile = _profile()
    expected = ranker.rank_opportunity(profile, original[-1])
    assert expected.evidence_rank == 1

    new = [dict(row, contact_email="") for row in old[:2]]
    prior_mtime = shards.stat().st_mtime_ns
    shards.write_text(json.dumps(new))
    os.utime(shards, ns=(prior_mtime, prior_mtime + 1_000_000_000))
    with monkeypatch.context() as fault:
        # The registration returns, but the loader's post-registration
        # validation finds that the candidate lacks its complete matrix.
        fault.setattr(ranker, "_build_sim_matrix", lambda rows: None)
        assert data_loader.load_opportunities() is original
        assert ranker.rank_opportunity(profile, original[-1]) == expected

    # The new file was not committed on failure. An ordinary retry of the
    # same file must load and score the new rows, including reused public IDs.
    recovered = data_loader.load_opportunities()
    assert recovered is not original
    assert [row["id"] for row in recovered] == [row["id"] for row in new]
    assert ranker.rank_opportunity(profile, recovered[0]).evidence_rank == 0


def test_ranking_contact_strength_rechecks_timestamp_for_a_registered_profile(shards):
    # The stamped contact crosses its 60-day limit between these two readings.
    first = datetime(2026, 2, 1, tzinfo=UTC)
    last = first + timedelta(days=1)
    address = "researcher@example.edu"
    stamp = build_identity_bound_contact_evidence(
        email=address, email_source="bound_directory_card",
        contact_source_url="https://faculty.example.edu/profile",
        contact_verified_at=first - timedelta(days=60) + timedelta(hours=12),
    )
    assert stamp is not None
    rows = _varied_corpus() + [_opp("same", contact_email=address, metadata=stamp)]
    shards.write_text(json.dumps(rows))
    record = next(row for row in data_loader.load_opportunities() if row["id"] == "same")
    with ranker.corpus_generation_lock:
        for moment, expected in ((first, 2), (first, 2), (last, 0), (first, 2)):
            assert ranker._ranking_contact_strength(record, moment) == expected
