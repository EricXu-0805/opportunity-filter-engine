"""Source extraction survives writer, disk, match, detail and email boundaries.

Only synthetic reviewed collector records are admitted to ranking here. User
imports retain their unverified kind (covered by test_url_import_sources).
"""
import json
import socket
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend import data_loader
from backend.lib.email_target_conditions import build_target_conditions, target_condition_claim_violations
from backend.lib.public_opportunity_detail import project_public_detail
from backend.main import app
from backend.routes import matches
from src.collectors.manual_importer import save_opportunities
from src.matcher import embeddings, ranker
from src.matcher.config import MATCHER_VERSION
from src.normalizers.enricher import enrich_opportunity
from src.normalizers.normalizer import normalize
from src.parsers.llm_tagger import apply_updates, rule_based_tag
from tests.test_match_consistency import _profile, snapshot_env  # noqa: F401


@pytest.mark.parametrize('text,required,preferred,mentioned', [
    ('Application materials. A CV is required.', [], [], []),
    ('JavaScript is required. Python is preferred.', ['JavaScript'], ['Python'], []),
    ('Research uses R programming. No Python experience is required.', [], [], ['R']),
    ('The project uses Python. Applicants must submit a CV.', [], [], ['Python']),
])
def test_source_to_disk_to_match_and_email(monkeypatch, tmp_path, snapshot_env, text, required, preferred, mentioned):  # noqa: F811
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('Network forbidden'))
    raw = {'id':'b57-pipeline', 'source':'manual_test_fixture', 'source_type':'campus_program',
           'title':'Student research program', 'description_raw':text,
           'url':'https://example.edu/research', 'source_url':'https://example.edu/research'}
    row = normalize(raw)
    row.update(school='uiuc', audience='campus')
    enrich_opportunity(row)
    apply_updates(row, rule_based_tag(row))
    assert row['description_raw'] == text
    assert row['eligibility']['skills_required'] == required
    assert row['eligibility']['skills_preferred'] == preferred
    assert row['metadata']['skill_mentions'] == mentioned
    assert 'IS' not in row['eligibility']['majors']
    file = tmp_path / 'opportunities.json'
    background = {**deepcopy(row), 'id':'b57-unverified', 'source_type':'unknown',
                  'description_raw':'A separate unverified geology archive.',
                  'description_clean':'A separate unverified geology archive.'}
    assert save_opportunities([row, background], str(file)) == (2, 0)
    monkeypatch.setattr(embeddings, '_tfidf_vectorizer', embeddings._tfidf_vectorizer)
    monkeypatch.setattr(embeddings, '_tfidf_fitted', embeddings._tfidf_fitted)
    monkeypatch.setattr(data_loader, '_tfidf_fitted_mtime', -1)
    monkeypatch.setattr(data_loader, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(data_loader, '_opp_cache', [])
    monkeypatch.setattr(data_loader, '_opp_cache_by_id', {})
    monkeypatch.setattr(data_loader, '_opp_cache_mtime', 0)
    monkeypatch.setattr(data_loader, '_opp_cache_generation', 0)
    loaded = data_loader.load_opportunities()
    stored = json.loads(file.read_text())
    assert len(loaded) == len(stored) == 2
    for actual, persisted in zip(loaded, stored, strict=True):
        assert actual['description_raw'] == persisted['description_raw']
        for field in ('majors', 'skills_required', 'skills_preferred'):
            assert actual['eligibility'][field] == persisted['eligibility'][field]
        for field in ('skill_mentions', 'inferred_fields'):
            assert actual['metadata'][field] == persisted['metadata'][field]
    before = deepcopy(loaded)
    monkeypatch.setattr(matches, 'load_opportunities_generation', lambda:(loaded, 'b57-synthetic-disk'))
    monkeypatch.setattr(matches, 'load_opportunities_by_id', lambda:{r['id']:r for r in loaded})
    monkeypatch.setattr(matches, '_llm_explanation', lambda *a, **k: None)
    ranker.register_corpus(loaded)
    profile = _profile(major='Art History', hard_skills=[], desired_fields=[], research_interests_text='')
    client = TestClient(app)
    response = client.post('/api/matches?llm=false', json=profile)
    assert response.status_code == 200, response.text
    listing = response.json()
    assert len(listing['results']) == 1
    result = listing['results'][0]
    explanation = client.post('/api/matches/b57-pipeline/explain?llm=false', json=profile)
    assert explanation.status_code == 200, explanation.text
    detail = explanation.json()
    assert listing['matcher_version'] == MATCHER_VERSION
    assert MATCHER_VERSION.split('.')[0] == '16'
    for field in ('final_score','bucket','eligibility_score','reasons_fit','reasons_gap','unknowns'):
        assert detail[field] == result[field]
    assert not any('Missing skills' in reason for reason in result['reasons_gap'])
    public = project_public_detail(loaded[0])
    assert 'skill_mentions' not in public.get('metadata', {})
    context = build_target_conditions(loaded[0])
    assert all(condition['usage'] != 'usable' for condition in context['conditions'])
    assert 'unsupported_eligibility_claim' in target_condition_claim_violations(
        'I meet all eligibility requirements.', context)
    assert loaded == before
