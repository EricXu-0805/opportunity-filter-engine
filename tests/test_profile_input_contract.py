"""B53 complete profile admission and real request/consumer boundaries, offline."""
import json
import socket
from copy import deepcopy

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import main
from backend.routes import matches
from backend.schemas import (
    PROFILE_LIST_LIMITS,
    PROFILE_MAX_CHARACTERS,
    PROFILE_TEXT_LIMITS,
    ProfileRequest,
    SkillItem,
)
from tests.test_cold_email_writing_quality import OPP
from tests.test_match_consistency import snapshot_env  # noqa: F401

REAL_EXPLANATION = matches._llm_explanation
REAL_RERANK = matches._llm_score_candidates


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('No external service is permitted')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(main, 'RATE_LIMIT_DISABLED', True)
    monkeypatch.setattr(main, 'feature_enabled', lambda _name: True)
    monkeypatch.setattr(matches, 'feature_enabled', lambda _name: True)


@pytest.fixture
def client():
    return TestClient(main.app)


def long_profile():
    return {'name': 'Audit', 'school': 'UIUC', 'home_school': 'uiuc', 'major': 'CS',
            'research_interests_text': ('方向😀\n' * 800) + 'INTEREST_TAIL',
            'coursework': [f'Course {i}' for i in range(60)] + ['CS 225'],
            'hard_skills': [{'name': f'Skill {i}', 'level': 'beginner'} for i in range(60)] +
                           [{'name': 'Python', 'level': 'experienced'}],
            'desired_fields': [f'Direction {i}' for i in range(25)] + ['machine learning']}


@pytest.mark.parametrize('field,limit', PROFILE_TEXT_LIMITS.items())
def test_text_boundaries_preserve_unicode_and_reject_overflow(field, limit):
    text = '😀' * limit
    assert getattr(ProfileRequest(**{field: text}), field) == text
    with pytest.raises(ValidationError) as error:
        ProfileRequest(**{field: text + 'A'})
    assert error.value.errors()[0]['ctx'] == {'field': f'profile.{field}', 'actual': limit + 1, 'limit': limit, 'unit': 'characters'}


@pytest.mark.parametrize('field,limits', PROFILE_LIST_LIMITS.items())
def test_list_limits_are_rejections_not_first_n(field, limits):
    count, length = limits
    values = [f'entry {i}' for i in range(count)]
    assert getattr(ProfileRequest(**{field: values}), field) == values
    with pytest.raises(ValidationError):
        ProfileRequest(**{field: values + ['late']})
    assert getattr(ProfileRequest(**{field: ['😀' * length]}), field) == ['😀' * length]
    with pytest.raises(ValidationError):
        ProfileRequest(**{field: ['😀' * (length + 1)]})


def test_skill_provenance_and_input_dictionaries_are_not_mutated():
    items = [{'name': 'N' * 999 + '尾', 'level': 'L' * 999 + '尾', 'source': ['invalid'], 'confirmed': 'true'},
             {'name': 'Python', 'source': 'github', 'confirmed': True}, 'Rust',
             SkillItem(name='MATLAB', source='resume', confirmed=False)]
    before = deepcopy(items)
    skills = ProfileRequest(hard_skills=items).hard_skills
    assert items == before
    assert skills[0].name == items[0]['name'] and skills[0].level == items[0]['level']
    assert skills[0].source == 'unknown' and skills[0].confirmed is False
    assert skills[1].source == 'github' and skills[1].confirmed is True
    assert skills[2].name == 'Rust' and skills[2].level == 'beginner'
    assert skills[3].source == 'resume' and skills[3].confirmed is False
    assert len(ProfileRequest(hard_skills=['Python'] * 512).hard_skills) == 512
    with pytest.raises(ValidationError):
        ProfileRequest(hard_skills=['Python'] * 513)


@pytest.mark.parametrize('field,value', [
    ('hard_skills', 'Python'), ('hard_skills', [3]), ('coursework', [3]),
    ('research_interests_text', None), ('name', '\ud800'),
    ('hard_skills', [{'name': '\udfff'}]), ('hard_skills', [{'name': 'Python', 'source': '\ud800'}]),
])
def test_invalid_shapes_and_surrogates_reject(field, value):
    with pytest.raises(ValidationError):
        ProfileRequest(**{field: value})


def test_aggregate_exact_boundary_and_emoji_interest_derivation(client, monkeypatch):
    monkeypatch.setattr(matches, 'load_opportunities_by_id', lambda: {OPP['id']: OPP})
    captured = []
    def capture(profile, _opp):
        captured.append(profile)
        return {'missing_skills': [], 'suggested_coursework': [], 'resume_tips': [], 'preparation_timeline': []}
    monkeypatch.setattr(matches, 'analyze_gaps', capture)
    profile = {'research_interests_text': '😀' * 60000, 'desired_fields': ['😀' * 60000]}
    response = client.post(f"/api/matches/{OPP['id']}/gaps", json=profile)
    assert response.status_code == 200, response.text
    assert captured[-1]['research_interests_text'] == profile['research_interests_text']
    assert captured[-1]['desired_fields'] == profile['desired_fields']
    profile['coursework'] = ['C' * 1000] * 38 + ['']
    model = ProfileRequest(**profile)
    remaining = PROFILE_MAX_CHARACTERS - len(json.dumps(model.model_dump(), ensure_ascii=False, separators=(',', ':')))
    # Fill additional whole entries, then use a final partial string.
    while remaining > 1000:
        profile['coursework'].insert(-1, 'D' * 1000)
        model = ProfileRequest(**profile)
        remaining = PROFILE_MAX_CHARACTERS - len(json.dumps(model.model_dump(), ensure_ascii=False, separators=(',', ':')))
    profile['coursework'][-1] = 'X' * remaining
    assert len(json.dumps(ProfileRequest(**profile).model_dump(), ensure_ascii=False, separators=(',', ':'))) == PROFILE_MAX_CHARACTERS
    assert client.post(f"/api/matches/{OPP['id']}/gaps", json=profile).status_code == 200
    profile['coursework'][-1] += 'X'
    response = client.post(f"/api/matches/{OPP['id']}/gaps", json=profile)
    assert response.status_code == 422
    assert response.json()['detail'] == {'code': 'PROFILE_INPUT_LIMIT_EXCEEDED', 'field': 'profile',
        'actual': PROFILE_MAX_CHARACTERS + 1, 'limit': PROFILE_MAX_CHARACTERS, 'unit': 'characters',
        'message': 'Profile input exceeds the supported limit.', 'retryable': False}


PROFILE_ROUTES = [
    ('/api/matches', False, {}), ('/api/matches/view', True, {'view': {}}),
    ('/api/matches/none/gaps', False, {}), ('/api/matches/none/explain', False, {}),
    ('/api/cold-email', True, {'opportunity_id': 'none'}),
    ('/api/cold-email/stream', True, {'opportunity_id': 'none'}),
    ('/api/cold-email/variants', True, {'opportunity_id': 'none'}),
    ('/api/cold-email/refine', True, {'opportunity_id': 'none', 'subject': 'S', 'body': 'B', 'instruction': 'Shorter'}),
    ('/api/tailor', True, {'opportunity_id': 'none'}),
    ('/api/tailor/renovate', True, {'opportunity_id': 'none'}),
    ('/api/tailor/bullet', True, {'opportunity_id': 'none'}),
    ('/api/opportunities/none/chat', True, {'message': 'What is this?'}),
    ('/api/roadmap', True, {'opportunity_ids': []}),
]


@pytest.mark.parametrize('path,nested,extra', PROFILE_ROUTES)
@pytest.mark.parametrize('mutation,code', [
    ({'research_interests_text': 'PRIVATE_STUDENT_SENTINEL' + 'X' * 60000}, 'PROFILE_INPUT_LIMIT_EXCEEDED'),
    ({'preferences': {'exclude_citizenship_restricted': {'private': 'PRIVATE_STUDENT_SENTINEL'}}}, 'PROFILE_INPUT_INVALID'),
])
def test_real_routes_reject_before_consumers_without_echo(client, monkeypatch, caplog, path, nested, extra, mutation, code):
    def forbidden(*_a, **_k):
        pytest.fail('Invalid profile reached corpus/provider')
    monkeypatch.setattr(matches, 'load_opportunities_by_id', forbidden)
    profile = {'name': 'Audit', **mutation}
    payload = {'profile': profile, **extra} if nested else profile
    response = client.post(path, json=payload)
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == code, response.text
    assert 'PRIVATE_STUDENT_SENTINEL' not in response.text + caplog.text


def test_real_match_and_gap_consumers_receive_late_material(client, monkeypatch, snapshot_env):  # noqa: F811
    profile = long_profile()
    original = matches._normalized_profile
    seen = []
    def capture(value):
        result = original(value); seen.append(result); return result
    monkeypatch.setattr(matches, '_normalized_profile', capture)
    response = client.post('/api/matches?llm=false', json=profile)
    assert response.status_code == 200 and response.json()['results']
    assert seen[-1]['research_interests_text'] == profile['research_interests_text']
    assert seen[-1]['coursework'] == profile['coursework']
    assert len(seen[-1]['hard_skills']) == 61
    response = client.post('/api/matches/opp-00/gaps', json=profile)
    assert response.status_code == 200
    assert 'Python' not in response.json()['missing_skills']


def test_real_explain_provider_keeps_full_interest(client, monkeypatch, snapshot_env):  # noqa: F811
    monkeypatch.setattr(matches, '_llm_explanation', REAL_EXPLANATION)
    calls = []
    def provider(messages, **_kwargs):
        calls.append(messages); return 'A controlled fit explanation.'
    monkeypatch.setattr(matches, 'chat_completion', provider)
    profile = long_profile()
    response = client.post('/api/matches/opp-00/explain?llm=true', json=profile)
    assert response.status_code == 200, response.text
    line = calls[0][1]['content'].splitlines()[0]
    assert json.loads(line.removeprefix('Student profile (JSON data): '))['research_interests_text'] == profile['research_interests_text']
    assert response.json()['method'] == 'llm'


def test_explain_budget_rejects_before_provider(client, monkeypatch, snapshot_env):  # noqa: F811
    monkeypatch.setattr(matches, '_llm_explanation', REAL_EXPLANATION)
    monkeypatch.setattr(matches, 'chat_completion', lambda *_a, **_k: pytest.fail('over-budget provider'))
    profile = long_profile(); profile['research_interests_text'] = '"' * 60000
    response = client.post('/api/matches/opp-00/explain?llm=true', json=profile)
    assert response.status_code == 413, response.text
    assert response.json()['detail']['code'] == 'MATCH_EXPLANATION_INPUT_TOO_LARGE'


def test_rerank_preflights_all_batches_before_first_provider(monkeypatch):
    monkeypatch.setattr(matches, '_LLM_RERANK_BATCH', 1)
    calls = []
    def provider(messages, **_kwargs):
        calls.append(messages)
        return '{"0":{"s":50,"r":"controlled fit"}}'
    monkeypatch.setattr(matches, 'chat_completion', provider)
    assert REAL_RERANK('Q' * 119000, [('a', 'A')]) is not None
    assert len(calls) == 1
    calls.clear()
    with pytest.raises(HTTPException) as error:
        REAL_RERANK('Q' * 119000, [('a', 'A'), ('b', 'B' * 2000)])
    assert error.value.status_code == 413
    assert error.value.detail['code'] == 'MATCH_RERANK_INPUT_TOO_LARGE'
    assert calls == []


def test_real_rerank_budget_does_not_block_rule_mode(client, monkeypatch, snapshot_env):  # noqa: F811
    monkeypatch.setattr(matches, '_llm_score_candidates', REAL_RERANK)
    monkeypatch.setattr(matches, 'chat_completion', lambda *_a, **_k: pytest.fail('over-budget provider'))
    profile = long_profile()
    profile['research_interests_text'] = 'I' * 60000
    profile['hard_skills'] = [{'name': 'S' * 1000, 'level': 'beginner'} for _ in range(60)]
    response = client.post('/api/matches?llm=false', json=profile)
    assert response.status_code == 200
    response = client.post('/api/matches?llm=true', json=profile)
    assert response.status_code == 413, response.text
    assert response.json()['detail']['code'] == 'MATCH_RERANK_INPUT_TOO_LARGE'


@pytest.mark.parametrize('path,nested,extra', [PROFILE_ROUTES[0], PROFILE_ROUTES[4], PROFILE_ROUTES[8], PROFILE_ROUTES[11]])
def test_shape_errors_with_surrogate_input_never_become_500(client, path, nested, extra):
    profile = {'name': 'Audit', 'preferences': {'show_reach_opportunities': {'private': '\ud800'}}}
    payload = {'profile': profile, **extra} if nested else profile
    response = client.post(path, content=json.dumps(payload, ensure_ascii=True), headers={'content-type': 'application/json'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'PROFILE_INPUT_INVALID'
    assert '\\ud800' not in response.text and 'private' not in response.text


def test_non_budget_rerank_failure_keeps_rule_fallback(client, monkeypatch, snapshot_env):  # noqa: F811
    def unavailable(*_args, **_kwargs):
        raise HTTPException(status_code=503, detail='Controlled provider failure')
    monkeypatch.setattr(matches, '_llm_score_candidates', unavailable)
    response = client.post('/api/matches?llm=true', json=long_profile())
    assert response.status_code == 200
    assert response.json()['results']
    assert all(result['ai_reason'] is None for result in response.json()['results'])


@pytest.mark.parametrize('secret', ['PRIVATE_STUDENT_SENTINEL', '\ud800'])
def test_parent_validation_never_reflects_whole_profile_or_surrogate(client, secret):
    payload = {'profile': {'name': 'Audit', 'research_interests_text': 'PRIVATE_STUDENT_SENTINEL'},
               'opportunity_id': 'none', 'sections': [
                   {'id': secret, 'heading': 'Research', 'kind': 'experience', 'bullets': []},
                   {'id': secret, 'heading': 'Research', 'kind': 'experience', 'bullets': []},
               ]}
    response = client.post('/api/tailor/renovate', content=json.dumps(payload, ensure_ascii=True), headers={'content-type': 'application/json'})
    assert response.status_code == 422
    assert response.json()['detail'] == [{'type': 'value_error', 'loc': ['body'], 'msg': 'Request input is invalid.'}]
    assert 'PRIVATE_STUDENT_SENTINEL' not in response.text and '\\ud800' not in response.text
