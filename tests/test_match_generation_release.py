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

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.routes.matches as m_module
from backend import data_loader
from backend.main import app
from src.matcher import embeddings, ranker
from tests.test_match_consistency import _profile, _varied_corpus

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
