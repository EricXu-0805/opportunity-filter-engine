"""Private first-contact context: controlled local source/auth tests only."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend.lib import private_target_resolution as resolution
from backend.routes import private_import_targets as private_route
from tests.test_private_import_targets import ID, OTHER, OWNER, app, raw_record
from tests.test_private_import_targets import storage as storage_fixture


@pytest.fixture
def storage(monkeypatch):
    result = storage_fixture.__wrapped__(monkeypatch)
    monkeypatch.setattr(resolution.storage, 'new_client', private_route.new_client)
    return result


def get_context(*, owner=OWNER, target_id=ID, authorized=True, params=None):
    return TestClient(app).get(f'/api/private-import-targets/{target_id}/email-context',
        params=params or {'expected_owner_id': owner},
        headers={'Authorization': 'Bearer fixture-token'} if authorized else {})


def test_context_route_registered(storage):
    storage['row'] = raw_record()
    response = get_context()
    assert response.status_code == 200
    assert response.json()['purpose'] == 'first_contact'


@pytest.mark.parametrize('text,kind', [
    ('Please do not email faculty about opportunities.', 'no_email'),
    ('Undergraduate applicants: please do not email us.', 'no_email'),
    ('We do not accept unsolicited emails.', 'no_email'),
    ('Cold emails are not accepted.', 'no_email'),
    ('No email inquiries.', 'no_email'),
    ('Apply only through the online portal.', 'form_only'),
    ('Applications must be submitted only via the portal.', 'form_only'),
    ('Applications may only be submitted through the application form.', 'form_only'),
    ('We only accept applications through our online form.', 'form_only'),
    ('请勿发送电子邮件联系。', 'no_email'),
    ('不接受主动邮件。', 'no_email'),
    ('仅通过在线申请系统提交。', 'form_only'),
    ('申请必须使用在线表格。', 'form_only'),
    ('Do not email us', 'no_email'),
    ('Instructions\nDo not email us\nContact details', 'no_email'),
    ('Undergraduates:\nDo not email us.', 'no_email'),
])
def test_direct_restrictions_are_bound_to_exact_source(text, kind):
    from backend.lib.private_email_context import private_contact_policy
    policy = private_contact_policy(text)
    assert policy['state'] == 'blocked'
    assert any(q['restriction'] == kind for q in policy['quotes'])
    for quote in policy['quotes']:
        assert text[quote['start']:quote['end']] == quote['quote']


@pytest.mark.parametrize('text', [
    'Please email the contact for more details.',
    'No email address is listed.',
    'No prior research experience is required. Email us with questions.',
    'Do not hesitate to email us.',
    'Email is not prohibited.',
    'We no longer say do not email us.',
    'If your application is incomplete, do not email us.',
    'For example, a page may say do not email us.',
    'Do not email us about a recommendation letter.',
    'Graduate applicants: do not email us.',
    'Graduates:\nDo not email us.\nUndergraduates:\nEmail us for information.',
    'Can I apply only through the online portal?',
    'Use our online application portal.',
    '请勿犹豫，欢迎邮件联系。',
    '不需要邮件确认。',
    '如果缺少材料，请勿发送邮件。',
    '研究生请勿发送邮件。',
    '例如：请勿发送邮件。',
    '请勿发送邮件吗？',
])
def test_no_policy_permission_and_no_false_unconditional_ban(text):
    from backend.lib.private_email_context import private_contact_policy
    assert private_contact_policy(text)['state'] == 'unknown'


def test_late_restriction_and_unicode_offsets_scan_complete_text():
    from backend.lib.private_email_context import private_contact_policy
    text = '普通说明😀\n' * 20_000 + 'Please do not email us.\n最后一段'
    policy = private_contact_policy(text)
    assert policy['state'] == 'blocked'
    quote = policy['quotes'][0]
    assert quote['start'] > 100_000
    assert text[quote['start']:quote['end']] == quote['quote']


def test_reference_capacity_cannot_turn_detected_ban_into_unknown():
    from backend.lib.private_email_context import MAX_QUOTES, private_contact_policy
    text = 'Do not email us.\n' * 23 + 'Apply only through the online portal.'
    policy = private_contact_policy(text)
    assert policy['state'] == 'blocked'
    assert policy['reason'] == 'policy_review_required'
    assert len(policy['quotes']) == MAX_QUOTES
    assert private_contact_policy('x' * 2100 + ' Do not email us.') == {
        'state': 'blocked', 'reason': 'policy_review_required', 'quotes': []}


def test_multiple_restrictions_stay_blocked():
    from backend.lib.private_email_context import private_contact_policy
    policy = private_contact_policy('Do not email us. Apply only through the online portal.')
    assert policy['state'] == 'blocked' and policy['reason'] == 'multiple_restrictions'


def test_max_size_punctuation_free_cjk_policy_scan_is_linear():
    import time

    from backend.lib.private_email_context import MAX_SOURCE_CHARACTERS, private_contact_policy
    text = '申请仅限' * (MAX_SOURCE_CHARACTERS // 4)
    started = time.perf_counter()
    policy = private_contact_policy(text)
    # The nested 60x60 gap regex took about 12 s here; the linear scan ~0.3 s.
    assert time.perf_counter() - started < 4
    assert policy == {'state': 'unknown', 'reason': 'policy_review_required', 'quotes': []}
    assert private_contact_policy('申请仅限' * 1000 + '表格。')['state'] == 'blocked'


def test_cjk_application_only_matches_the_bounded_gap_rule_exactly():
    import random
    import re

    from backend.lib.private_email_context import _cjk_application_only
    oracle = re.compile(r'(?:申请|材料)[^。！？\r\n]{0,60}(?:仅限|只能|必须)[^。！？\r\n]{0,60}(?:表格|系统|门户)')
    assert _cjk_application_only('申请' + 'x' * 60 + '必须' + 'x' * 60 + '表格')
    assert not _cjk_application_only('申请' + 'x' * 61 + '必须' + '表格')
    assert not _cjk_application_only('申请' + '必须' + 'x' * 61 + '表格')
    assert not _cjk_application_only('申请必须。表格')
    rng = random.Random(20260930)
    pieces = ['申请', '材料', '仅限', '只能', '必须', '表格', '系统', '门户', '申', '限', 'x' * 7, 'xx', '。', '\n', '！']
    for _ in range(3000):
        text = ''.join(rng.choice(pieces) for _ in range(rng.randint(0, 40)))
        assert _cjk_application_only(text) == bool(oracle.search(text)), text


def test_policy_scan_runs_off_the_event_loop(storage, monkeypatch):
    import asyncio
    import time

    import backend.lib.private_email_context as context_module
    storage['row'] = raw_record()
    real = context_module.private_contact_policy

    def slow_policy(text):
        time.sleep(0.3)
        return real(text)

    monkeypatch.setattr(context_module, 'private_contact_policy', slow_policy)

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        result = await context_module.resolve_private_email_context(
            ID, authorization='Bearer fixture-token', expected_owner_id=OWNER)
        task.cancel()
        return ticks, result

    ticks, result = asyncio.run(scenario())
    assert result['purpose'] == 'first_contact'
    assert ticks >= 10


def test_complete_context_is_private_local_and_not_public_authority(storage, monkeypatch):
    import json

    import backend.data_loader as loader
    import backend.lib.llm as llm
    import backend.lib.public_opportunity_detail as public_detail
    def forbidden(*args, **kwargs):
        raise AssertionError('Public corpus/provider must not be used')
    monkeypatch.setattr(llm, 'chat_completion', forbidden)
    monkeypatch.setattr(loader, 'load_opportunities_by_id', forbidden)
    monkeypatch.setattr(public_detail, 'project_public_detail', forbidden)
    row = raw_record()
    row['opportunity']['description_raw'] = 'Saved original source.\n' * 1000 + 'Please do not email us.'
    row['opportunity']['extra_fields'].update({
        'target_truth': {'actionable': True}, 'eligibility': {'skills_required': ['FORGED']},
        'contact_instructions': {'email_policy': 'allowed'}, 'provider_allowed': True,
        'recipient_email': 'FORGED@example.com', 'research_context': {'status': 'available'},
        'writing_version': 'pwt1:' + 'f' * 64, 'verification': 'official'})
    before = deepcopy(row)
    storage['row'] = row
    response = get_context()
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['provider_allowed'] is False and result['verification'] == 'unverified'
    assert result['contact_policy']['state'] == 'blocked'
    assert result['source_version'].startswith('pit1:') and result['writing_version'].startswith('pwt1:')
    assert len(result['writing_version']) == 69
    assert not {'description_raw','eligibility','recipient_email','research_context','lab_context','target_truth'} & result.keys()
    assert 'FORGED' not in json.dumps(result) and 'Saved original source' not in json.dumps(result)
    assert storage['row'] == before
    assert [call[1] for call in storage['calls']] == ['/auth/v1/user', '/rest/v1/rpc/read_private_import_target']
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('case,status,code', [
    ('no_auth', 401, 'private_target_auth_required'),
    ('anonymous', 401, 'private_target_auth_required'),
    ('retired', 401, 'private_target_auth_required'),
    ('other_owner', 409, 'private_target_owner_changed'),
    ('missing', 404, 'private_target_not_found'),
    ('deleted', 409, 'private_target_deleted'),
])
def test_owner_and_tombstone_gate(storage, case, status, code):
    storage['row'] = raw_record()
    if case == 'anonymous': storage['user']['is_anonymous'] = True
    if case == 'retired': storage['failure'] = '42501'
    if case == 'missing': storage['row'] = None
    if case == 'deleted': storage['row'] = raw_record(revision=2, deleted=True)
    response = get_context(owner=OTHER if case == 'other_owner' else OWNER, authorized=case != 'no_auth')
    assert response.status_code == status
    assert response.json() == {'detail': {'code': code}}
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('params', [
    {}, {'expected_owner_id':'bad'}, {'expected_owner_id':OWNER,'provider_allowed':'true'},
    {'expected_owner_id':OWNER,'expected_target_version':'PRIVATE_VALUE'},
    [('expected_owner_id',OWNER),('expected_owner_id',OWNER)],
])
def test_bad_queries_do_not_read_or_reflect_inputs(storage, params):
    response = TestClient(app).get(f'/api/private-import-targets/{ID}/email-context', params=params)
    assert response.status_code == 422 and not storage['calls']
    assert response.json() == {'detail': {'code': 'private_target_invalid_request'}}


def test_refresh_returns_new_version_and_writer_checks_reviewed_version(storage):
    import asyncio

    from backend.lib.private_email_context import resolve_private_email_context
    from backend.lib.private_import_targets_schema import PrivateTargetError
    storage['row'] = raw_record()
    previous = get_context().json()['writing_version']
    result = asyncio.run(resolve_private_email_context(ID, authorization='Bearer fixture-token', expected_owner_id=OWNER,
                                                       expected_writing_version=previous))
    assert result['writing_version'] == previous
    storage['row'] = raw_record(revision=2)
    refreshed = get_context().json()
    assert refreshed['writing_version'] != previous
    with pytest.raises(PrivateTargetError) as caught:
        asyncio.run(resolve_private_email_context(ID, authorization='Bearer fixture-token', expected_owner_id=OWNER,
                                                  expected_writing_version=previous))
    assert (caught.value.code, caught.value.status) == ('private_target_changed', 409)


def test_writing_version_binds_purpose_projection_policy_and_exact_value(storage, monkeypatch):
    import backend.lib.private_email_context as context_module
    storage['row'] = raw_record()
    one = get_context().json()
    assert get_context().json() == one
    monkeypatch.setattr(context_module, 'POLICY_VERSION', 2)
    assert get_context().json()['writing_version'] != one['writing_version']
    monkeypatch.setattr(context_module, 'POLICY_VERSION', 1)
    monkeypatch.setattr(context_module, 'PROJECTION_VERSION', 2)
    assert get_context().json()['writing_version'] != one['writing_version']


def test_invalid_writing_version_refused_before_auth(storage):
    import asyncio

    from backend.lib.private_email_context import resolve_private_email_context
    from backend.lib.private_import_targets_schema import PrivateTargetError
    with pytest.raises(PrivateTargetError) as caught:
        asyncio.run(resolve_private_email_context(ID, authorization='Bearer fixture-token', expected_owner_id=OWNER,
                                                  expected_writing_version='pit1:' + 'a'*64))
    assert caught.value.status == 422 and not storage['calls']


@pytest.mark.parametrize('text', [None, '', '   ', 'bad\x00text', 'bad\ud800text'])
def test_invalid_local_policy_input_is_fixed_error(text):
    from backend.lib.private_email_context import private_contact_policy
    from backend.lib.private_import_targets_schema import PrivateTargetError
    with pytest.raises(PrivateTargetError) as caught:
        private_contact_policy(text)
    assert (caught.value.code, caught.value.status) == ('private_target_invalid_receipt', 502)


def test_local_policy_source_capacity_is_explicit_not_a_prefix():
    from backend.lib.private_email_context import MAX_SOURCE_CHARACTERS, private_contact_policy
    from backend.lib.private_import_targets_schema import PrivateTargetError
    with pytest.raises(PrivateTargetError) as caught:
        private_contact_policy('x' * (MAX_SOURCE_CHARACTERS + 1))
    assert (caught.value.code, caught.value.status) == ('private_target_too_large', 413)


def test_http_context_current_shape_and_hash_can_be_consumed_by_browser(storage):
    import hashlib
    import json
    storage['row'] = raw_record()
    result = get_context().json()
    version = result.pop('writing_version')
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    assert version == 'pwt1:' + hashlib.sha256(encoded).hexdigest()
    assert set(result) == {'version','target_scope','verification','purpose','id','owner_id','revision',
                          'source_version','projection_version','policy_version','title','organization',
                          'source_url','import_source','contact_policy','provider_allowed'}
