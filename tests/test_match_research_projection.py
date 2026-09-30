"""Hidden rerank's controlled candidate builder, with no provider calls."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.routes import matches
from tests.test_cold_email_writing_quality import OPP
from tests.test_email_research_context import attach_snapshot


@pytest.fixture
def capture_candidates(monkeypatch):
    captured = []
    monkeypatch.setattr(matches, '_resolve', lambda *_a, **_k: object())
    monkeypatch.setattr(matches, '_llm_rerank_cache', {})
    monkeypatch.setattr(matches, 'chat_completion', lambda *_a, **_k: pytest.fail('provider forbidden'))
    def score(_query, candidates):
        captured.extend(candidates)
        return None
    monkeypatch.setattr(matches, '_llm_score_candidates', score)
    def run(opp):
        outcome = matches.llm_rerank({'research_interests_text': 'research source fixture'},
            [SimpleNamespace(opportunity_id=opp['id'], final_score=80)], {opp['id']: opp})
        assert outcome.applied is False
        return json.dumps(captured)
    return run


def test_available_snapshot_replaces_stale_legacy_titles_without_sending_abstract_or_attempts(capture_candidates):
    opp = deepcopy(OPP); stored = attach_snapshot(opp)
    stored['works'][0]['title'] = 'Current Source Paper'
    opp['metadata']['research_refresh'] = {'error': 'PRIVATE_ATTEMPT'}
    captured = capture_candidates(opp)
    assert 'Current Source Paper' in captured
    assert 'Old unrelated cached work' not in captured
    assert stored['works'][0]['abstract'] not in captured
    assert 'PRIVATE_ATTEMPT' not in captured


@pytest.mark.parametrize('change', ['stale', 'invalid', 'author_changed', 'revoked', 'privacy'])
def test_unusable_new_source_never_restores_legacy_paper_candidate(capture_candidates, change):
    opp = deepcopy(OPP); stored = attach_snapshot(opp)
    if change == 'stale': stored['checked_at'] = '2020-01-01T00:00:00Z'
    elif change == 'invalid': opp['metadata']['research_snapshot'] = None
    elif change == 'author_changed': opp['metadata']['publication_author_id'] = 'https://openalex.org/A2'
    elif change == 'revoked': opp['metadata'].pop('publication_attribution_status')
    else: stored['works'][0]['abstract'] += ' private@example.edu'
    captured = capture_candidates(opp)
    assert 'Old unrelated cached work' not in captured
    assert stored['works'][0]['title'] not in captured
    assert 'private@example.edu' not in captured


def test_legacy_verified_title_compatibility_remains_without_a_new_snapshot(capture_candidates):
    opp = deepcopy(OPP)
    opp['metadata'].update(publication_attribution_status='verified_author_id', recent_works=[{'title': 'Verified Legacy Paper', 'year': 2025}])
    assert 'Verified Legacy Paper' in capture_candidates(opp)
