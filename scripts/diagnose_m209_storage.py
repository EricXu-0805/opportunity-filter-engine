"""Temporary, runner-local validation for the M209 candidate."""
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

from scripts.restore_attachment_evidence import BUCKETS, validate_attachments

fixture = Path(sys.argv[1])
status = json.loads((fixture / 'status.json').read_bytes())
base = status['API_URL']
assert base == 'http://127.0.0.1:54321'
key = status['SERVICE_ROLE_KEY']
assert key
headers = {'apikey': key, 'Authorization': f'Bearer {key}'}
logical = 'https://scratch.supabase.co'
download_count = 0
pages_past_100 = 0


def use_runner_local_storage(request):
    # Bind the logical drill hostname to the ephemeral loopback gateway. HTTPX
    # opens a real network connection and consumes the real service's responses.
    global download_count, pages_past_100
    assert request.url.host == 'scratch.supabase.co'
    request.url = request.url.copy_with(scheme='http', host='127.0.0.1', port=54321)
    request.headers['Host'] = '127.0.0.1:54321'
    if request.method == 'GET' and '/object/' in request.url.path:
        download_count += 1
    if request.method == 'POST':
        assert '/object/list/' in request.url.path
        pages_past_100 += json.loads(request.content)['offset'] >= 100


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(objects, expected):
    global download_count, pages_past_100
    download_count = pages_past_100 = 0
    document = {'version': 1, 'source_environment': 'synthetic-source', 'source_backup_id': 'point-1',
                'buckets': {b: [{'key': k, 'size': len(v), 'sha256': sha(v)} for k, v in rows.items()]
                            for b, rows in objects.items()}}
    backup = fixture / 'source-manifest.json'
    raw = json.dumps(document, sort_keys=True).encode()
    pin = sha(raw)
    backup.write_bytes(raw)
    with httpx.Client(trust_env=False, timeout=10, event_hooks={'request': [use_runner_local_storage]}) as client:
        evidence = validate_attachments(client, logical, key, manifest_path=backup, manifest_sha256=pin,
                                        source_environment='synthetic-source', source_backup_id='point-1',
                                        scratch_environment='scratch')
    # Only the aggregate counters are published, even on a failure.
    print('Measured', evidence['result'], json.dumps(evidence.get('buckets'), sort_keys=True), flush=True)
    assert evidence['result'] == expected
    return evidence['buckets']


def store(method, route, **kwargs):
    response = direct.request(method, base + '/storage/v1/' + route, **kwargs)
    assert response.is_success, f'Runner-local {method} failed with status {response.status_code}'


with httpx.Client(headers=headers, trust_env=False, timeout=15) as direct:
    for bucket in BUCKETS:
        store('POST', 'bucket', json={'id': bucket, 'name': bucket, 'public': False})
    verify({b: {} for b in BUCKETS}, 'PASS')
    assert download_count == 0
    print('PASS both existing empty private buckets, complete inventory', flush=True)

    tracker, materials = BUCKETS
    source = {tracker: {'owner/position/pages/' + f'{i:03}.txt': f'synthetic record {i}'.encode()
                        for i in range(101)},
              materials: {'pdf/fixture.pdf': b'%PDF-1.7 synthetic material\n%%EOF'}}
    source[tracker]['owner/position/empty.txt'] = b''
    for bucket, objects in source.items():
        for path, content in objects.items():
            mime = 'text/plain' if path.endswith('.txt') else 'application/pdf'
            store('POST', 'object/' + bucket + '/' + quote(path), headers={'Content-Type': mime}, content=content)
    verified = verify(source, 'PASS')
    assert download_count == 103 and pages_past_100 >= 1
    assert verified[tracker]['verified'] == 102 and verified[materials]['verified'] == 1
    print('PASS 103 real object downloads across both buckets, including a zero-byte file, nested folders and a 101-object page boundary.', flush=True)

    path = 'pdf/fixture.pdf'
    original = source[materials][path]
    changed = b'!' + original[1:]
    assert len(original) == len(changed) and sha(original) != sha(changed)
    store('PUT', 'object/' + materials + '/' + path, content=changed, headers={'Content-Type': 'application/pdf'})
    corrupt = verify(source, 'FAIL')
    assert download_count == 103 and corrupt[materials]['mismatched'] == 1 and corrupt[tracker]['verified'] == 102
    print('PASS equal-length corruption rejected after a real PUT and 103 fresh downloads.', flush=True)
