"""Complete email inputs are bounded at every provider boundary, never truncated."""
import asyncio
import json
from copy import deepcopy

import pytest
from fastapi import HTTPException

from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.routes import cold_email as ce
from tests.test_cold_email_selection_refine import payload
from tests.test_cold_email_writing_quality import OPP, PROFILE
from tests.test_email_contact_context import FIRST, post, result
from tests.test_email_lab_context import email_parts
from tests.test_email_lab_context_v2 import attach_lab_v2
from tests.test_email_paper_reading import writing_client  # noqa: F401


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch):
    monkeypatch.setattr(ce, 'chat_completion', lambda *_a, **_k: pytest.fail('unexpected provider I/O'))


def size(messages):
    return len(json.dumps(messages, ensure_ascii=False, separators=(',', ':')))


def full_lab(opp, fill):
    snapshot = attach_lab_v2(opp)
    snapshot['pages'][0]['sections'] = [{'section_id': 's1', 'heading': '', 'text': fill * 3999 + 'P'}]
    snapshot['pages'][1]['sections'] = [
        {'section_id': f's{i + 1}', 'heading': '', 'text': fill * 1999 + str(i)} for i in range(10)]
    public = project_public_detail(opp)
    assert public['lab_context']['status'] == 'available'
    return public


def assert_limit(exc):
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 413
    assert exc.detail == {
        'code': 'EMAIL_INPUT_TOO_LARGE',
        'message': 'The combined email input is too long. Reduce the selected material or edit request and try again.',
        'max_characters': 120000,
    }


@pytest.mark.parametrize('character', ['x', '研', '🧪', '\n', '\x01', '"', '\\'])
@pytest.mark.parametrize('extra', [-1, 0, 1])
def test_exact_serialized_boundary_counts_json_escaping_and_unicode_without_mutating(monkeypatch, character, extra):
    messages = [{'role': 'user', 'content': character * 1000}]
    target = ce.EMAIL_PROMPT_MAX_CHARACTERS + extra
    messages[0]['content'] += 'z' * (target - size(messages))
    assert size(messages) == target
    before = deepcopy(messages); calls = []
    def provider(value, **kwargs):
        calls.append((deepcopy(value), kwargs))
        return 'unchanged provider output'
    monkeypatch.setattr(ce, 'chat_completion', provider)
    if extra <= 0:
        assert ce._email_chat_completion(messages, max_tokens=7) == 'unchanged provider output'
        assert calls == [(before, {'max_tokens': 7})]
    else:
        with pytest.raises(ce._EmailInputTooLarge) as caught:
            ce._email_chat_completion(messages, max_tokens=7)
        assert_limit(caught.value)
        assert calls == []
    assert messages == before


def call_stage(stage, public):
    parts = email_parts(public)
    professor, student = ce._render_professor_brief(parts, public), ce._render_student_brief(parts)
    if stage == 'draft': return ce._draft_email(professor, student, False, None, 'cs', is_faculty=True)
    if stage == 'judge': return ce._judge_drafts(['Email A.', 'Email B.'], professor, student, None)
    if stage == 'critique': return ce._llm_critique('Email A.', professor, student, None)
    if stage == 'revise': return ce._revise_email('Email A.', {}, professor, student, None)
    request = ce.EmailRefineRequest.model_validate(payload(opportunity_id=public['id'], profile=PROFILE))
    if stage == 'refine':
        request = request.model_copy(update={'selection': None})
        return asyncio.run(ce._refine_email_snapshot(request, public))
    return asyncio.run(ce._refine_selection_snapshot(request, public))


@pytest.mark.parametrize('stage', ['draft', 'judge', 'critique', 'revise', 'refine', 'selection'])
@pytest.mark.parametrize('oversized', [False, True])
def test_every_provider_site_limits_full_valid_v2_source_without_truncation(monkeypatch, stage, oversized):
    opp = deepcopy(OPP); public = full_lab(opp, '\x01' if oversized else 'x')
    before = deepcopy(public); calls = []
    def provider(messages, **_kwargs):
        calls.append(deepcopy(messages))
        return None
    monkeypatch.setattr(ce, 'chat_completion', provider)
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    if oversized:
        with pytest.raises(ce._EmailInputTooLarge) as caught:
            call_stage(stage, public)
        assert_limit(caught.value)
        assert calls == []
    else:
        call_stage(stage, public)
        assert len(calls) == 1 and size(calls[0]) <= ce.EMAIL_PROMPT_MAX_CHARACTERS
        snapshot = json.dumps(public['lab_context']['snapshot'], ensure_ascii=False, sort_keys=True)
        assert snapshot in calls[0][1]['content']
    assert public == before


@pytest.mark.parametrize('stage', ['judge', 'critique', 'revise'])
def test_provider_generated_drafts_and_revision_notes_also_count(monkeypatch, stage):
    private = 'PRIVATE_DRAFT_MARKER' + 'x' * 120000
    with pytest.raises(ce._EmailInputTooLarge) as caught:
        if stage == 'judge': ce._judge_drafts([private, 'Small draft.'], 'Short professor brief', 'Short student brief', None)
        elif stage == 'critique': ce._llm_critique(private, 'Short professor brief', 'Short student brief', None)
        else: ce._revise_email('Small draft.', {'llm': {'revision_notes': private}}, 'Short professor brief', 'Short student brief', None)
    assert_limit(caught.value)
    assert 'PRIVATE_DRAFT_MARKER' not in str(caught.value.detail)


@pytest.mark.parametrize('path', ['', 'stream', 'refine', 'selection'])
def test_oversized_route_is_an_explicit_error_without_template_or_provider(writing_client, monkeypatch, path):  # noqa: F811
    client, opp = writing_client; full_lab(opp, '\x01')
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', lambda *_a, **_k: pytest.fail('oversized input reached provider'))
    def no_fallback(*_args, **_kwargs):
        pytest.fail('oversized input must not be disguised as successful local work')
    monkeypatch.setattr(ce, 'generate_cold_email', no_fallback)
    monkeypatch.setattr(ce, '_local_refine_fallback', no_fallback)
    monkeypatch.setattr(ce, '_template_after_timeout', no_fallback)
    if path == 'selection':
        response = client.post('/api/cold-email/refine', json=payload(opportunity_id=opp['id'],
            expected_target_version=writing_target_version(project_public_detail(opp))))
    else:
        response = post(client, path, FIRST, opportunity_id=opp['id'], engine='ai')
    if path == 'stream':
        assert response.status_code == 200  # Headers precede worker validation.
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert events[-1] == {'stage': 'error', 'code': 'EMAIL_INPUT_TOO_LARGE', 'status': 413,
                             'message': ce._EMAIL_INPUT_TOO_LARGE_MESSAGE}
        assert all(event['stage'] != 'done' for event in events)
    else:
        assert response.status_code == 413, response.text
        assert response.json()['detail']['code'] == 'EMAIL_INPUT_TOO_LARGE'
    assert 'body' not in response.text and '\\u0001' not in response.text


@pytest.mark.parametrize('path,engine', [('', 'template'), ('stream', 'template'), ('variants', 'ai')])
def test_template_only_routes_do_not_apply_a_provider_budget(writing_client, monkeypatch, path, engine):  # noqa: F811
    client, opp = writing_client; full_lab(opp, '\x01')
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, '_email_chat_completion', lambda *_a, **_k: pytest.fail('template entered provider boundary'))
    out = result(post(client, path, FIRST, opportunity_id=opp['id'], engine=engine), path)
    assert out['pipeline_version'] == 'w12.15'
    if path == 'variants':
        assert out['variants'] and all(item['body'] for item in out['variants'])
    else:
        assert out['method'] == 'template'


@pytest.mark.parametrize('path', ['', 'stream'])
@pytest.mark.parametrize('stage', ['judge', 'critique', 'revise'])
def test_later_stage_overflow_is_not_swallowed_after_successful_draft(writing_client, monkeypatch, path, stage):  # noqa: F811
    client, opp = writing_client; attach_lab_v2(opp); calls = []
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setenv('OFE_COLD_EMAIL_NDRAFT', '2' if stage == 'judge' else '1')
    monkeypatch.setenv('OFE_COLD_EMAIL_CRITIQUE', '1' if stage == 'critique' else '0')
    # Deterministic content checks are independently tested. Keep this fixture
    # focused on propagation when provider output enlarges a later prompt.
    monkeypatch.setattr(ce, '_deterministic_findings', lambda *_a, **_k:
                        {'banned_filler': ['fixture issue']} if stage == 'revise' else {})
    def provider(messages, **_kwargs):
        assert size(messages) <= 120000
        calls.append(deepcopy(messages))
        return 'Subject: Research inquiry\n\nDear Professor Nielsen,\n\n' + 'x' * 120000
    monkeypatch.setattr(ce, 'chat_completion', provider)
    monkeypatch.setattr(ce, 'generate_cold_email', lambda *_a, **_k: pytest.fail('must not fall back'))
    response = post(client, path, FIRST, opportunity_id=opp['id'], engine='ai')
    assert len(calls) == (2 if stage == 'judge' else 1)
    if path == 'stream':
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert events[-1]['stage'] == 'error' and events[-1]['code'] == 'EMAIL_INPUT_TOO_LARGE'
        assert all(event['stage'] != 'done' for event in events)
    else:
        assert response.status_code == 413 and response.json()['detail']['code'] == 'EMAIL_INPUT_TOO_LARGE'
