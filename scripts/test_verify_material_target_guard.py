"""No-network checks for destructive local verifier boundaries."""
import json
from copy import deepcopy

import httpx
import pytest
from verify_contact_material_lifecycle_local import verify_candidate_database_info
from verify_material_archive_local import candidate_target, loopback, verify_fixture_identity


@pytest.mark.parametrize('value', [
    'https://127.0.0.1:56321', 'http://example.test:56321',
    'http://127.0.0.1:56321/auth/v1', 'http://127.0.0.1:56321?target=old',
    'http://127.0.0.1:56321#old', 'http://user:pass@127.0.0.1:56321',
    'http://user@127.0.0.1:56321',
])
def test_rejects_ambiguous_endpoint_without_network(value):
    with pytest.raises(ValueError):
        loopback(value)


def fixture():
    return {'api_url': 'http://127.0.0.1:56321', 'project_id': 'ofe-b37-m65',
            'service_role_key': 'synthetic-service', 'anon_key': 'synthetic-anon',
            'users': [{'id': '00000000-0000-4000-8000-000000000001',
                       'email': 'ofe-b37-owner@fixture.invalid', 'access_token': 'synthetic-session'}]}


@pytest.mark.parametrize(('field', 'value'), [('api_url', 'http://127.0.0.1:55321'), ('project_id', 'ofe-b33-materials')])
def test_rejects_old_candidate(field, value):
    data = fixture(); data[field] = value
    with pytest.raises(ValueError):
        candidate_target(data, 'http://127.0.0.1:56321', 'ofe-b37-m65', 'ofe-b37-')


def test_rejects_account_outside_batch_namespace():
    data = fixture(); data['users'][0]['email'] = 'ofe-b36-owner@fixture.invalid'
    with pytest.raises(ValueError):
        candidate_target(data, data['api_url'], data['project_id'], 'ofe-b37-')


@pytest.mark.parametrize('bindings', [
    [{'HostIp': '', 'HostPort': '56322'}], [{'HostIp': '0.0.0.0', 'HostPort': '56322'}],
    [{'HostIp': '127.0.0.1', 'HostPort': '55322'}], [],
    [{'HostIp': '127.0.0.1', 'HostPort': '56322'}, {'HostIp': '::', 'HostPort': '56322'}],
])
def test_rejects_nonunique_or_wrong_database_binding(bindings):
    with pytest.raises(ValueError):
        verify_candidate_database_info({'State': {'Running': True}, 'HostConfig': {'PortBindings': {'5432/tcp': bindings}}}, 56322)


def test_accepts_exact_candidate_and_live_identity():
    data = fixture(); user = data['users'][0]
    assert candidate_target(data, data['api_url'], data['project_id'], 'ofe-b37-') == data['api_url']
    verify_candidate_database_info({'State': {'Running': True}, 'HostConfig': {'PortBindings': {'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '56322'}]}}}, 56322)
    seen = []
    def response(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={**user, 'is_anonymous': False, 'email_confirmed_at': '2026-09-25T12:00:00Z'})
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert verify_fixture_identity(client, data, user)
    assert [method for method, _ in seen] == ['GET', 'GET']


@pytest.mark.parametrize('change', [{'email': 'someone@real.example'}, {'id': 'different'}, {'is_anonymous': True}, {'email_confirmed_at': None}])
def test_identity_mismatch_never_reaches_a_write(change):
    data = fixture(); user = data['users'][0]; seen = []
    actual = {**deepcopy(user), 'is_anonymous': False, 'email_confirmed_at': '2026-09-25T12:00:00Z', **change}
    def response(request):
        seen.append(request.method)
        return httpx.Response(200, content=json.dumps(actual))
    with httpx.Client(transport=httpx.MockTransport(response)) as client, pytest.raises(ValueError):
        verify_fixture_identity(client, data, user, require_session=False)
    assert seen == ['GET']


@pytest.mark.parametrize('scope', ['application', 'contact'])
@pytest.mark.parametrize(('status', 'body'), [
    (401, {'code': '42501', 'message': 'permission denied for function finalize_application_material'}),
    (403, {'code': '42501', 'message': 'material_identity_unavailable'}),
    (403, {'code': '42501', 'message': 'invalid stage token'}),
    (403, {'code': 'PGRST301', 'message': 'JWT expired'}),
    (500, {'code': '42501', 'message': 'permission denied for function finalize_application_material'}),
    (200, {}),
])
def test_finalize_business_rejection_is_not_execute_denial(scope, status, body):
    from verify_material_archive_local import verify_finalize_execute_denied
    with pytest.raises(AssertionError):
        verify_finalize_execute_denied(httpx.Response(status, json=body), scope)


@pytest.mark.parametrize('scope', ['application', 'contact'])
def test_finalize_accepts_only_exact_authenticated_function_denial(scope):
    from verify_material_archive_local import verify_finalize_execute_denied
    message = f'permission denied for function finalize_{scope}_material'
    proof = verify_finalize_execute_denied(httpx.Response(403, json={'code': '42501', 'message': message}), scope)
    assert proof == {'http_status': 403, 'postgres_code': '42501', 'permission_message': message}
    other = 'application' if scope == 'contact' else 'contact'
    with pytest.raises(AssertionError):
        verify_finalize_execute_denied(httpx.Response(403, json={'code': '42501', 'message': message}), other)


@pytest.mark.parametrize('receipt', [{}, {'Id': '', 'Key': 'placeholder'}, {'Id': 4, 'Key': 'placeholder'}, {'Id': 'valid-id', 'Key': 'wrong-path'}])
def test_legacy_successful_http_without_exact_receipt_never_passes(receipt):
    from verify_material_archive_local import verify_legacy_tracker
    data = fixture(); owner = {**data['users'][0], 'opportunity_id': 'test-opportunity'}
    calls = []; checks = []; journal = []
    def respond(request):
        calls.append(request.method)
        return httpx.Response(200, json=receipt)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(AssertionError):
        verify_legacy_tracker(client, data, owner, owner, lambda *args, **kwargs: checks.append(args), journal.append)
    assert calls == ['POST']
    assert checks == []
    assert len(journal) == 1 and len(journal[0]['paths']) == 2


@pytest.mark.parametrize('entrypoint', ['archive', 'lifecycle'])
def test_initial_external_failure_replaces_old_complete_report(tmp_path, monkeypatch, entrypoint):
    import sys
    from types import SimpleNamespace

    import verify_contact_material_lifecycle_local as lifecycle
    import verify_material_archive_local as archive

    data = fixture()
    data['users'] = [{**data['users'][0], 'id': f'00000000-0000-4000-8000-00000000000{i}',
                      'email': f'ofe-b37-owner{i}@fixture.invalid', 'event_id': 'event-id',
                      'opportunity_id': 'test-opportunity', 'label': label}
                     for i, label in enumerate(['owner_a', 'owner_b', 'merge_target'], 1)]
    source = tmp_path / 'private-fixture.json'; source.write_text(json.dumps(data))
    output = tmp_path / 'report.json'; output.write_text(json.dumps({'complete': True, 'run_id': 'old-run', 'secret_old': 'not-retained'}))
    argv = ['verifier', '--fixture', str(source), '--app-base', 'http://127.0.0.1:8200',
            '--output', str(output), '--expected-api-url', data['api_url'],
            '--expected-project-id', data['project_id'], '--fixture-prefix', 'ofe-b37-']
    observed = []
    def observe():
        current = json.loads(output.read_text())
        assert current['complete'] is False and current['run_id'] != 'old-run'
        observed.append(True)
    if entrypoint == 'archive':
        client_type = httpx.Client
        def respond(request):
            observe()
            return httpx.Response(401, json={'private': 'secret-response-must-not-leak'})
        monkeypatch.setattr(archive.httpx, 'Client', lambda **kwargs: client_type(transport=httpx.MockTransport(respond)))
        module = archive
    else:
        argv.extend(['--db-container', 'supabase_db_ofe-b37-m65', '--db-port', '56322', '--private-state', str(tmp_path / 'journal.json')])
        def inspect(*args, **kwargs):
            observe()
            return SimpleNamespace(returncode=1, stdout='secret-output-must-not-leak', stderr='secret-stderr')
        monkeypatch.setattr(lifecycle.subprocess, 'run', inspect)
        module = lifecycle
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 1 and observed == [True]
    result = json.loads(output.read_text())
    assert result['complete'] is False and result['passed'] is False
    assert result['failure_type'] == 'RuntimeError'
    assert 'secret' not in output.read_text()


def test_cleanup_drains_preceding_claim_batch_without_false_absence():
    from verify_material_archive_local import cleanup_until_absent
    outcomes = iter([{'claimed': 20, 'failed': 0}, {'claimed': 1, 'failed': 0}])
    reads = iter([httpx.Response(200, content=b'original'), httpx.Response(400, json={'statusCode': '404', 'error': 'not_found'})])
    observed = []
    result = cleanup_until_absent(lambda: next(outcomes), lambda: next(reads), observed)
    assert result['claimed'] == 21 and len(observed) == 2 and result['failed'] == 0


@pytest.mark.parametrize('status', [401, 403, 404, 500])
def test_cleanup_never_calls_arbitrary_http_error_absent(status):
    from verify_material_archive_local import cleanup_until_absent
    observed = []
    with pytest.raises(AssertionError):
        cleanup_until_absent(lambda: {'claimed': 1, 'failed': 0}, lambda: httpx.Response(status, json={'error': 'other'}), observed)
    assert len(observed) == 1


def test_cleanup_failed_batch_cannot_pass_even_if_object_is_absent():
    from verify_material_archive_local import cleanup_until_absent
    with pytest.raises(AssertionError):
        cleanup_until_absent(lambda: {'claimed': 1, 'failed': 1}, lambda: httpx.Response(400, json={'statusCode': '404', 'error': 'not_found'}), [])


def test_cleanup_existing_object_has_a_strict_batch_limit():
    from verify_material_archive_local import cleanup_until_absent
    observed = []
    with pytest.raises(AssertionError):
        cleanup_until_absent(lambda: {'claimed': 0, 'failed': 0}, lambda: httpx.Response(200, content=b'original'), observed, max_batches=3)
    assert len(observed) == 3
