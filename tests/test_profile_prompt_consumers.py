"""Real legacy-writing consumers retain the complete accepted student profile."""
import json
from copy import deepcopy

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.lib.prompt_budget import check_prompt_size
from backend.lib.prompt_safety import sanitize_field
from backend.routes import opportunities as chat
from backend.routes import tailor
from tests.test_cold_email_writing_quality import OPP

INTEREST = 'I want to study research tools. ' * 90 + 'Only nonclinical work; no animal experiments.'
PROFILE = {
    'name': 'Student', 'major': 'Computer Science', 'year': 'junior',
    'research_interests_text': INTEREST,
    'hard_skills': [{'name': f'Tool{i}', 'level': 'experienced', 'source': 'github'} for i in range(60)],
    'coursework': [f'CS {100+i}' for i in range(60)],
}
ORIGINAL = 'Built a parser in Python.'


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(tailor.router, prefix='/api')
    app.include_router(chat.router, prefix='/api')
    monkeypatch.setattr(tailor, 'load_opportunities_by_id', lambda: {OPP['id']: deepcopy(OPP)})
    monkeypatch.setattr(chat, 'load_opportunities_by_id', lambda: {OPP['id']: deepcopy(OPP)})
    monkeypatch.setattr(tailor, 'is_configured', lambda: True)
    for module in (tailor, chat):
        monkeypatch.setattr(module, 'chat_completion', lambda *_a, **_k: pytest.fail('unexpected provider call'))
    monkeypatch.setattr(chat, 'chat_completion_stream', lambda *_a, **_k: pytest.fail('unexpected stream provider'))
    return TestClient(app)


def check_complete(messages):
    text = '\n'.join(m['content'] for m in messages)
    assert INTEREST in text
    assert 'Tool59' in text
    assert 'CS 159' in text
    assert 'Tool59 (experienced)' not in text  # imported level is not a student assertion


def test_tailor_real_request_carries_late_profile_facts_and_keeps_attribution(client, monkeypatch):
    calls = []
    def provider(messages, **_kwargs):
        calls.append(deepcopy(messages))
        return json.dumps({'bullets': [{'text': ORIGINAL, 'source_evidence': ORIGINAL}]})
    monkeypatch.setattr(tailor, 'chat_completion', provider)
    body = {'profile': deepcopy(PROFILE), 'opportunity_id': OPP['id'], 'original_bullets': [ORIGINAL]}
    before = deepcopy(body)
    response = client.post('/api/tailor', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['method'] == 'ai'
    check_complete(calls[0])
    assert response.json()['tailored_bullets'][0]['text'] == ORIGINAL
    assert response.json()['tailored_bullets'][0]['source_evidence'] == ORIGINAL
    assert body == before


@pytest.mark.parametrize('stream', [False, True])
def test_chat_real_request_carries_late_profile_facts(client, monkeypatch, stream):
    calls = []
    def provider(messages, **_kwargs):
        calls.append(deepcopy(messages))
        return iter(['Controlled reply.']) if stream else 'Controlled reply.'
    monkeypatch.setattr(chat, 'chat_completion_stream' if stream else 'chat_completion', provider)
    response = client.post(f"/api/opportunities/{OPP['id']}/chat?stream={int(stream)}", json={
        'message': 'What are the requirements?', 'profile': PROFILE,
    })
    assert response.status_code == 200, response.text
    check_complete(calls[0])
    assert 'Controlled reply.' in response.text


@pytest.mark.parametrize('path,code', [
    ('tailor', 'TAILOR_INPUT_TOO_LARGE'), ('chat', 'CHAT_INPUT_TOO_LARGE'),
    ('chat-stream', 'CHAT_INPUT_TOO_LARGE'),
])
def test_route_oversized_combined_input_refuses_before_provider_or_fallback(client, monkeypatch, path, code):
    # Keep each schema field valid and lower the aggregate cap: exercise the
    # route's pre-provider guard, rather than winning at field validation.
    monkeypatch.setattr(tailor, 'TAILOR_PROMPT_MAX_CHARACTERS', 100)
    monkeypatch.setattr(chat, 'CHAT_PROMPT_MAX_CHARACTERS', 100)
    if path == 'tailor':
        url = '/api/tailor'
        body = {'profile': PROFILE, 'opportunity_id': OPP['id'], 'original_bullets': [ORIGINAL]}
    else:
        url = f"/api/opportunities/{OPP['id']}/chat?stream={int(path == 'chat-stream')}"
        body = {'message': 'What are the requirements?', 'profile': PROFILE}
    before = deepcopy(body)
    response = client.post(url, json=body)
    assert response.status_code == 413, response.text
    detail = response.json()['detail']
    assert detail['code'] == code and detail['retryable'] is False
    assert detail['max_characters'] == 100
    assert 'Student' not in response.text and INTEREST not in response.text
    assert 'text/event-stream' not in response.headers['content-type']
    assert body == before


@pytest.mark.parametrize('character', ['x', '研', '🧪', '\x01', '\n', '"', '\\'])
@pytest.mark.parametrize('delta', [-1, 0, 1])
def test_prompt_budget_counts_all_serialized_input_without_mutation(character, delta):
    messages = [{'role': 'system', 'content': 'Rules.'}, {'role': 'user', 'content': character * 20}]
    size = len(json.dumps(messages, ensure_ascii=False, separators=(',', ':')))
    before = deepcopy(messages)
    kwargs = {'limit': size - delta, 'code': 'TEST_LIMIT', 'message': 'Input too long.'}
    if delta > 0:
        with pytest.raises(HTTPException) as caught:
            check_prompt_size(messages, **kwargs)
        assert caught.value.status_code == 413
        assert caught.value.detail == {
            'code': 'TEST_LIMIT', 'message': 'Input too long.', 'max_characters': size - delta, 'retryable': False,
        }
    else:
        check_prompt_size(messages, **kwargs)
    assert messages == before


def test_full_field_option_keeps_tail_and_only_normalizes_whitespace():
    value = 'a' * 1000 + '\n\t末尾限制条件'
    assert sanitize_field(value, max_len=None) == 'a' * 1000 + ' 末尾限制条件'
    assert sanitize_field(value) == 'a' * 600  # explicit legacy excerpt callers retain their contract
