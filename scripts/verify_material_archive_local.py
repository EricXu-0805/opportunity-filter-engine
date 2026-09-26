"""Opt-in real Auth/Storage/API check, restricted to an explicit loopback fixture.

The fixture contains disposable local users/keys; never commit it. No hosted
URLs are accepted. This script writes only fake PDFs and a sanitized report.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import ipaddress
import json
import os
import sys
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.lib.material_archive import MaterialService


@contextmanager
def sanitized_report(output, report):
    """Replace a prior result before any external check; never emit exception bodies."""
    report.update({'run_id': str(uuid4()), 'started_at': datetime.now(UTC).isoformat(),
                   'complete': False, 'passed': False})
    target = Path(output)
    target.write_text(json.dumps(report, indent=2) + '\n')
    try:
        yield report
    except BaseException as error:
        report.update({'complete': False, 'passed': False, 'failure_type': type(error).__name__,
                       'failure_summary': 'Verifier incomplete; inspect its private journal locally.',
                       'failed_at': datetime.now(UTC).isoformat(),
                       'failure_location': [{'file': Path(frame.filename).name, 'line': frame.lineno}
                                            for frame in traceback.extract_tb(error.__traceback__)[-3:]]})
        target.write_text(json.dumps(report, indent=2) + '\n')
        print('Verification incomplete; sanitized report preserved.', flush=True)
        raise SystemExit(1) from None



def storage_missing(response):
    if response.status_code != 400:
        return False
    body = response.json()
    return isinstance(body, dict) and str(body.get('statusCode')) == '404' and body.get('error') == 'not_found'


def cleanup_until_absent(cleanup, read_object, observations, *, max_batches=10):
    """A cleanup claim is capped at 20; a preceding local queue may take several batches."""
    batches = []
    for _ in range(max_batches):
        outcome = cleanup()
        batches.append(outcome)
        observations.append(outcome)
        if outcome['failed'] != 0:
            raise AssertionError('Cleanup reported failed jobs')
        response = read_object()
        if storage_missing(response):
            return {'claimed': sum(batch['claimed'] for batch in batches), 'failed': 0, 'batches': batches}
        if response.status_code != 200:
            raise AssertionError('Storage absence was not proven')
    raise AssertionError('Object still exists after the bounded cleanup batches')


def verify_finalize_execute_denied(response, scope):
    """Business-rule refusal or an expired JWT is not proof of denied EXECUTE."""
    if response.status_code != 403:
        raise AssertionError('Direct finalize did not return authenticated permission denial')
    body = response.json()
    if (not isinstance(body, dict) or body.get('code') != '42501'
        or body.get('message') != f'permission denied for function finalize_{scope}_material'):
        raise AssertionError('Direct finalize did not prove denied function EXECUTE')
    return {'http_status': 403, 'postgres_code': '42501', 'permission_message': body['message']}


def loopback(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or not parsed.hostname or not ipaddress.ip_address(parsed.hostname).is_loopback
        or parsed.path not in ('', '/') or parsed.query or parsed.fragment
        or parsed.username is not None or parsed.password is not None):
        raise ValueError('Only explicit local HTTP test endpoints are allowed')
    return value.rstrip('/')



def candidate_target(fixture, expected_api_url, expected_project_id, fixture_prefix):
    """Bind disposable data to the explicitly selected local candidate."""
    api = loopback(expected_api_url)
    if fixture.get('api_url') != api or fixture.get('project_id') != expected_project_id:
        raise ValueError('Fixture does not match the selected local candidate')
    if not expected_project_id.startswith('ofe-b') or not fixture_prefix.startswith('ofe-b') or not fixture_prefix.endswith('-'):
        raise ValueError('An explicit OFE batch project and disposable email prefix are required')
    if expected_project_id == 'ofe-b37-m65' and (api != 'http://127.0.0.1:56321' or fixture_prefix != 'ofe-b37-'):
        raise ValueError('Batch37 must use its separate candidate and fixture prefix')
    users = fixture.get('users', [])
    if not users or len({u['id'] for u in users}) != len(users):
        raise ValueError('Fixture accounts are absent or duplicated')
    if not all(u['email'].startswith(fixture_prefix) and u['email'].endswith('@fixture.invalid') for u in users):
        raise ValueError('Fixture contains an account outside the disposable namespace')
    return api


def verify_fixture_identity(client, fixture, user, *, require_session=True):
    """Check live Auth identity before mutation; never log credentials or bodies."""
    api = loopback(fixture['api_url'])
    service = {'apikey': fixture['service_role_key'], 'Authorization': 'Bearer ' + fixture['service_role_key']}
    response = client.get(api + '/auth/v1/admin/users/' + user['id'], headers=service)
    if response.status_code != 200:
        raise RuntimeError(f'Fixture identity lookup HTTP {response.status_code}')
    actual = response.json()
    if actual.get('id') != user['id'] or actual.get('email') != user['email'] or actual.get('is_anonymous') is not False or not actual.get('email_confirmed_at'):
        raise ValueError('Live Auth identity does not match the disposable formal account')
    if require_session:
        session = client.get(api + '/auth/v1/user', headers={'apikey': fixture['anon_key'], 'Authorization': 'Bearer ' + user['access_token']})
        if session.status_code != 200 or session.json().get('id') != user['id'] or session.json().get('email') != user['email']:
            raise ValueError('Fixture session does not match the live account')
    return True


def pdf(size=None):
    payload = max(0, (size or 0) - 800)
    for _ in range(5):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        if size:
            writer.add_attachment('synthetic-test-data.bin', b'0' * payload)
        output = io.BytesIO()
        writer.write(output)
        contents = output.getvalue()
        if not size or len(contents) == size:
            return contents
        payload += size - len(contents)
    raise AssertionError('Could not generate exact-size synthetic PDF')



def verify_legacy_tracker(client, fixture, owner, other, passed, remember):
    """Exercise the pre-existing bucket contract with real user sessions."""
    api = fixture['api_url']; contents = pdf()
    prefix = owner['id'] + '/' + owner['opportunity_id']
    name = 'legacy-' + uuid4().hex + '.pdf'; nested = 'directory-' + uuid4().hex
    paths = [prefix + '/' + name, prefix + '/' + nested + '/child.pdf']
    remember({'kind': 'legacy_tracker', 'owner_id': owner['id'], 'paths': paths})
    def headers(user):
        return {'apikey': fixture['anon_key'], 'Authorization': 'Bearer ' + user['access_token']}
    bucket = api + '/storage/v1/object/tracker-attachments'
    upload_receipts = []
    for path in paths:
        response = client.post(bucket + '/' + path, headers={**headers(owner), 'content-type': 'application/pdf', 'x-upsert': 'false'}, content=contents)
        assert response.status_code in (200, 201), f'Legacy upload HTTP {response.status_code}'
        receipt = response.json()
        assert isinstance(receipt.get('Id'), str) and receipt['Id']
        assert receipt.get('Key') == 'tracker-attachments/' + path
        upload_receipts.append({'http_status': response.status_code, 'id_nonempty_string': True, 'key_matches_full_requested_path': True, 'fields': sorted(receipt)})
    def listing(user):
        return client.post(api + '/storage/v1/object/list/tracker-attachments', headers=headers(user), json={'prefix': prefix, 'limit': 100, 'sortBy': {'column': 'created_at', 'order': 'desc'}})
    listed = listing(owner); assert listed.status_code == 200
    rows = listed.json(); file = next(row for row in rows if row['name'] == name); directory = next(row for row in rows if row['name'] == nested)
    assert file['id'] and file['metadata']['size'] == len(contents) and file['metadata']['mimetype'] == 'application/pdf'
    assert directory['id'] is None and directory['metadata'] is None
    sign = api + '/storage/v1/object/sign/tracker-attachments/' + paths[0]
    signed = client.post(sign, headers=headers(owner), json={'expiresIn': 60}); assert signed.status_code == 200
    relative = signed.json()['signedURL']; assert relative.startswith('/object/sign/tracker-attachments/')
    downloaded = client.get(api + '/storage/v1' + relative); assert downloaded.status_code == 200 and downloaded.content == contents
    other_list = listing(other); assert other_list.status_code == 200 and other_list.json() == []
    other_sign = client.post(sign, headers=headers(other), json={'expiresIn': 60}); assert other_sign.status_code in (400, 401, 403, 404)
    other_write = client.post(bucket + '/' + paths[0], headers={**headers(other), 'content-type': 'application/pdf', 'x-upsert': 'true'}, content=contents)
    assert other_write.status_code in (400, 401, 403, 404)
    other_delete = client.request('DELETE', bucket, headers=headers(other), json={'prefixes': paths})
    assert (other_delete.status_code == 200 and other_delete.json() == []) or other_delete.status_code in (400, 401, 403, 404)
    assert client.get(api + '/storage/v1' + relative).content == contents
    passed('legacy Tracker user upload, metadata, directory marker, original signed download and owner isolation', byte_length=len(contents), upload_receipts=upload_receipts, directory_id_and_metadata_null=True, other_list_status=other_list.status_code, other_signed_url_status=other_sign.status_code, other_upload_status=other_write.status_code, other_delete_status=other_delete.status_code)
    removed = client.request('DELETE', bucket, headers=headers(owner), json={'prefixes': paths}); assert removed.status_code == 200
    receipt_names = {row['name'] for row in removed.json()}; assert receipt_names == set(paths)
    assert listing(owner).json() == []
    missing = client.get(api + '/storage/v1' + relative); assert missing.status_code in (400, 404)
    service = {'apikey': fixture['service_role_key'], 'Authorization': 'Bearer ' + fixture['service_role_key']}
    absent_statuses = []
    for path in paths:
        absent = client.get(bucket + '/' + path, headers=service)
        assert absent.status_code in (400, 404) and str(absent.json().get('statusCode')) == '404'
        absent_statuses.append(absent.status_code)
    passed('legacy Tracker remove receipt contains exact full paths and files are absent', remove_status=removed.status_code, full_path_receipts=len(receipt_names), signed_download_after_delete_status=missing.status_code, physical_absence_statuses=absent_statuses, root_list_empty_after_delete=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--app-base', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--expected-api-url', required=True)
    parser.add_argument('--expected-project-id', required=True)
    parser.add_argument('--fixture-prefix', required=True)
    parser.add_argument('--max-size', action='store_true')
    parser.add_argument('--legacy-tracker', action='store_true', help='Also verify the original user-owned Tracker Storage bucket contract.')
    parser.add_argument('--private-state', help='Optional 0600 journal; an existing path is refused to prevent blind replay.')
    parser.add_argument('--skip-direct-finalize-probe', action='store_true', help='Explicitly omit the denied-EXECUTE probe; the report stays incomplete.')
    parser.add_argument('--skip-direct-finalize-reason', help='Required explanation when omitting the denied-EXECUTE probe.')
    parser.add_argument('--scope', choices=('application', 'contact'), default='application',
                        help='Association to verify; original application fixture format remains the default.')
    args = parser.parse_args()
    if args.expected_project_id == 'ofe-b37-m65' and args.skip_direct_finalize_probe:
        parser.error('Batch37 acceptance must execute the direct finalize permission probe')
    if args.skip_direct_finalize_probe and not (args.skip_direct_finalize_reason or '').strip():
        parser.error('--skip-direct-finalize-probe requires --skip-direct-finalize-reason')
    if args.skip_direct_finalize_reason and not args.skip_direct_finalize_probe:
        parser.error('--skip-direct-finalize-reason requires --skip-direct-finalize-probe')
    report = {'checks': [], 'omitted_checks': [], 'material_scope': args.scope}
    with sanitized_report(args.output, report):
        run(args, report)


def run(args, report):
    fixture = json.loads(Path(args.fixture).read_text())
    journal = Path(args.private_state) if args.private_state else None
    if journal and journal.exists():
        raise ValueError('Private journal exists; inspect it before rerunning')
    journal_state = {'scope': args.scope, 'materials': []}
    def remember(data):
        journal_state['materials'].append(data)
        if journal:
            fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as output:
                json.dump(journal_state, output, indent=2)
            os.chmod(journal, 0o600)
        return data
    storage = candidate_target(fixture, args.expected_api_url, args.expected_project_id, args.fixture_prefix)
    app_base = loopback(args.app_base)
    if args.expected_project_id == 'ofe-b37-m65' and app_base not in ('http://127.0.0.1:8200', 'http://127.0.0.1:3200'):
        raise ValueError('Batch37 must use its separate backend or frontend')
    app = app_base + f'/api/{args.scope}-materials'
    event_field = f'{args.scope}_event_id'
    def event_id(user):
        return user['event_id'] if args.scope == 'application' else user['contact_event_id']
    owner, other = fixture['users'][:2]
    assert owner['email'].endswith('.invalid') and other['email'].endswith('.invalid')
    scope = {'expected_owner_id': owner['id'], 'opportunity_id': owner['opportunity_id'], event_field: event_id(owner)}
    headers = {'Authorization': 'Bearer ' + owner['access_token']}
    service_headers = {'Authorization': 'Bearer ' + fixture['service_role_key'], 'apikey': fixture['service_role_key']}
    user_headers = {**headers, 'apikey': fixture['anon_key']}
    checks = report['checks']
    omitted_checks = ([{'name': 'direct user finalize denied', 'reason': args.skip_direct_finalize_reason}]
                      if args.skip_direct_finalize_probe else [])
    report.update({'checked_at': datetime.now(UTC).isoformat(), 'app_base': args.app_base,
              'storage': storage, 'project_id': args.expected_project_id, 'checks': checks, 'omitted_checks': omitted_checks, 'complete': False, 'material_scope': args.scope, 'scope': 'disposable local Auth/PostgREST/Storage, no hosted writes'})
    def passed(name, **details):
        checks.append({'name': name, 'passed': True, **details})
        print(name + ': passed', flush=True)
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    def expect(response, code):
        if response.status_code != code:
            raise AssertionError(f'HTTP status {response.status_code}; expected {code}')
        return response
    with httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client:
        for user in fixture['users']:
            verify_fixture_identity(client, fixture, user)
        passed('live disposable Auth identity and session verified', accounts=len(fixture['users']))
        def meta(contents, filename='实际提交的材料.pdf'):
            return remember({'version': 1, **scope, 'material_id': str(uuid4()), 'record_id': str(uuid4()),
                    'filename': filename, 'mime_type': 'application/pdf', 'byte_length': len(contents),
                    'bytes_sha256': hashlib.sha256(contents).hexdigest(), 'attested': True})
        def upload(data, contents):
            return client.post(app, headers=headers, files={'metadata': (None, json.dumps(data, ensure_ascii=False)),
                                'file': (data['filename'], contents, 'application/pdf')})
        def delete(data):
            return client.request('DELETE', app + '/' + data['record_id'], headers=headers,
                                  json={**scope, 'material_id': data['material_id']})
        def storage_url(data):
            return storage + '/storage/v1/object/application-materials/pdf/' + data['material_id'] + '.pdf'
        async def cleanup():
            async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False) as transport:
                return await MaterialService(transport, storage, fixture['service_role_key']).cleanup()
        def erased(data):
            observations = report.setdefault('cleanup_batches', [])
            return cleanup_until_absent(lambda: asyncio.run(cleanup()),
                                        lambda: client.get(storage_url(data), headers=service_headers), observations)
        if args.legacy_tracker:
            verify_legacy_tracker(client, fixture, owner, other, passed, remember)
        contents = pdf()
        data = meta(contents)
        created = expect(upload(data, contents), 200).json()
        assert created['record']['status'] == 'ready'
        assert created['record']['bytes_sha256'] == data['bytes_sha256']
        assert created['record']['confirmation_source'] == 'user_reported'
        assert expect(upload(data, contents), 200).json()['replayed'] is True
        downloaded = expect(client.get(app + '/' + data['record_id'] + '/file', params=scope, headers=headers), 200)
        assert downloaded.content == contents and downloaded.headers['x-ofe-material-sha256'] == data['bytes_sha256']
        assert 'no-store' in downloaded.headers['cache-control']
        assert 'attachment' in downloaded.headers['content-disposition']
        passed('archive, exact retry, original-byte download', byte_length=len(contents), sha256=data['bytes_sha256'])
        visible = expect(client.get(app, params=scope, headers=headers), 200).json()['items']
        assert any(row['record_id'] == data['record_id'] for row in visible)
        other_scope = {'expected_owner_id': other['id'], 'opportunity_id': other['opportunity_id'], event_field: event_id(other)}
        expect(client.get(app + '/' + data['record_id'], params=other_scope,
                          headers={'Authorization': 'Bearer ' + other['access_token']}), 404)
        denied = client.get(storage_url(data), headers=user_headers)
        storage_read_status = denied.status_code
        assert denied.status_code in (400, 401, 403, 404) and denied.content != contents
        denied = client.post(storage_url(data), headers={**user_headers, 'Content-Type': 'application/pdf', 'x-upsert': 'true'}, content=contents)
        assert denied.status_code in (400, 401, 403, 404)
        passed('different owner and direct user Storage denied', different_owner_read_status=404, storage_read_status=storage_read_status, storage_write_status=denied.status_code)
        if not args.skip_direct_finalize_probe:
            denied = client.post(storage + f'/rest/v1/rpc/finalize_{args.scope}_material', headers=user_headers,
                                 json={'p_verified_owner': owner['id'], 'p_verified_session_id': owner['session_id'],
                                       'p_material_id': data['material_id'], 'p_stage_token': str(uuid4()),
                                       'p_verified_byte_length': len(contents), 'p_verified_sha256': data['bytes_sha256']})
            report['direct_finalize_probe'] = {'http_status': denied.status_code, 'scope': args.scope}
            proof = verify_finalize_execute_denied(denied, args.scope)
            report['direct_finalize_probe'].update(proof)
            passed('direct user finalize denied', **proof)
        # Simulate a lost upload/finalize response using actual user RPC and
        # immutable Storage bytes, then recover through the ordinary endpoint.
        recovery = meta(contents, 'retry.pdf')
        stage_args = {'p_expected_owner': owner['id'], 'p_material_id': recovery['material_id'],
                      'p_record_id': recovery['record_id'], f'p_{event_field}': event_id(owner),
                      'p_opportunity_id': owner['opportunity_id'], 'p_filename': recovery['filename'],
                      'p_byte_length': len(contents), 'p_sha256': recovery['bytes_sha256']}
        expect(client.post(storage + f'/rest/v1/rpc/stage_{args.scope}_material', json=stage_args, headers=user_headers), 200)
        expect(client.post(storage_url(recovery), content=contents,
                           headers={**service_headers, 'Content-Type': 'application/pdf', 'x-upsert': 'false'}), 200)
        staged = expect(client.get(app + '/' + recovery['record_id'], params=scope, headers=headers), 200).json()['record']
        assert staged['status'] == 'staged' and staged['bytes_sha256'] is None and staged['linked_at'] is None
        assert expect(upload(recovery, contents), 200).json()['record']['status'] == 'ready'
        passed('interrupted-stage recovery verifies existing immutable object')
        bad = b'%PDF-1.7\nfake input\n%%EOF'
        cancelled = meta(bad, 'damaged.pdf')
        expect(upload(cancelled, bad), 422)
        expect(client.get(app + '/' + cancelled['record_id'], params=scope, headers=headers), 404)
        tombstone = expect(delete(cancelled), 200).json()['record']
        assert tombstone['status'] == 'deleted' and tombstone['filename'] is None and tombstone['linked_at'] is None
        # Valid late bytes still cannot reuse an already revoked ID.
        late = {**cancelled, 'byte_length': len(contents), 'bytes_sha256': hashlib.sha256(contents).hexdigest()}
        expect(upload(late, contents), 410)
        assert expect(delete(cancelled), 200).json()['record']['deleted_at'] == tombstone['deleted_at']
        replacement = meta(contents, 'corrected.pdf')
        expect(upload(replacement, contents), 200)
        passed('invalid PDF cancellation permits new attempt and fences late old upload')
        assert expect(client.get(storage_url(data), headers=service_headers), 200).content == contents
        gone = expect(delete(data), 200).json()['record']
        assert gone['status'] == 'deleted' and gone['filename'] is None and gone['bytes_sha256'] is None
        expect(client.get(app + '/' + data['record_id'] + '/file', params=scope, headers=headers), 409)
        outcome = erased(data)
        assert outcome['failed'] == 0
        passed('logical deletion denies download and actual Storage object removed', cleanup=outcome)
        if args.max_size:
            large = pdf(64 * 1024 * 1024)
            maximum = meta(large, 'maximum-size.pdf')
            expect(upload(maximum, large), 200)
            downloaded = expect(client.get(app + '/' + maximum['record_id'] + '/file', params=scope, headers=headers), 200)
            assert len(downloaded.content) == len(large) and hashlib.sha256(downloaded.content).hexdigest() == maximum['bytes_sha256']
            expect(delete(maximum), 200)
            erased(maximum)
            passed('64 MiB original file roundtrip through Next rewrite', byte_length=len(large), sha256=maximum['bytes_sha256'])
        for remaining in (recovery, replacement):
            expect(delete(remaining), 200)
            erased(remaining)
        report['passed'] = True
        report['complete'] = not omitted_checks
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
