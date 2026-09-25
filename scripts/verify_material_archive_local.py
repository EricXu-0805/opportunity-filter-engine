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
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.lib.material_archive import MaterialService


def loopback(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or not parsed.hostname or not ipaddress.ip_address(parsed.hostname).is_loopback:
        raise ValueError('Only explicit local HTTP test endpoints are allowed')
    return value.rstrip('/')


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--app-base', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-size', action='store_true')
    args = parser.parse_args()
    fixture = json.loads(Path(args.fixture).read_text())
    storage = loopback(fixture['api_url'])
    app = loopback(args.app_base) + '/api/application-materials'
    owner, other = fixture['users'][:2]
    assert owner['email'].endswith('.invalid') and other['email'].endswith('.invalid')
    scope = {'expected_owner_id': owner['id'], 'opportunity_id': owner['opportunity_id'], 'application_event_id': owner['event_id']}
    headers = {'Authorization': 'Bearer ' + owner['access_token']}
    service_headers = {'Authorization': 'Bearer ' + fixture['service_role_key'], 'apikey': fixture['service_role_key']}
    user_headers = {**headers, 'apikey': fixture['anon_key']}
    checks = []
    report = {'checked_at': datetime.now(UTC).isoformat(), 'app_base': args.app_base,
              'storage': storage, 'checks': checks, 'scope': 'disposable local Auth/PostgREST/Storage, no hosted writes'}
    def passed(name, **details):
        checks.append({'name': name, 'passed': True, **details})
        print(name + ': passed', flush=True)
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    def expect(response, code):
        if response.status_code != code:
            raise AssertionError(f'HTTP status {response.status_code}; expected {code}')
        return response
    with httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client:
        def meta(contents, filename='实际提交的材料.pdf'):
            return {'version': 1, **scope, 'material_id': str(uuid4()), 'record_id': str(uuid4()),
                    'filename': filename, 'mime_type': 'application/pdf', 'byte_length': len(contents),
                    'bytes_sha256': hashlib.sha256(contents).hexdigest(), 'attested': True}
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
            result = asyncio.run(cleanup())
            missing = client.get(storage_url(data), headers=service_headers)
            assert missing.status_code == 400 and missing.json()['statusCode'] == '404'
            return result
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
        other_scope = {'expected_owner_id': other['id'], 'opportunity_id': other['opportunity_id'], 'application_event_id': other['event_id']}
        expect(client.get(app + '/' + data['record_id'], params=other_scope,
                          headers={'Authorization': 'Bearer ' + other['access_token']}), 404)
        denied = client.get(storage_url(data), headers=user_headers)
        assert denied.status_code in (400, 401, 403, 404) and denied.content != contents
        denied = client.post(storage_url(data), headers={**user_headers, 'Content-Type': 'application/pdf', 'x-upsert': 'true'}, content=contents)
        assert denied.status_code >= 400
        denied = client.post(storage + '/rest/v1/rpc/finalize_application_material', headers=user_headers,
                             json={'p_verified_owner': owner['id'], 'p_verified_session_id': owner['session_id'],
                                   'p_material_id': data['material_id'], 'p_stage_token': str(uuid4()),
                                   'p_verified_byte_length': len(contents), 'p_verified_sha256': data['bytes_sha256']})
        assert denied.status_code >= 400
        passed('different owner and direct user Storage/finalize denied')
        # Simulate a lost upload/finalize response using actual user RPC and
        # immutable Storage bytes, then recover through the ordinary endpoint.
        recovery = meta(contents, 'retry.pdf')
        stage_args = {'p_expected_owner': owner['id'], 'p_material_id': recovery['material_id'],
                      'p_record_id': recovery['record_id'], 'p_application_event_id': owner['event_id'],
                      'p_opportunity_id': owner['opportunity_id'], 'p_filename': recovery['filename'],
                      'p_byte_length': len(contents), 'p_sha256': recovery['bytes_sha256']}
        expect(client.post(storage + '/rest/v1/rpc/stage_application_material', json=stage_args, headers=user_headers), 200)
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
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
