"""Read every current AOE saved detail after the named source is truly deployed."""
import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SITE = 'https://joinalab.com'
REPO = 'EricXu-0805/opportunity-filter-engine'
SOURCE = '09b348c6faff83cedeeb967e2af7dd20b600197d'
ROSTER = 'https://www.aoe.vt.edu/people/faculty.html'
SCOPE = 'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
CONTROLS = {'faculty-vt-aoe-d8633d35', 'faculty-vt-aoe-83afac67', 'faculty-vt-aoe-5572a837',
            'faculty-vt-aoe-7ebe485f', 'faculty-vt-aoe-4159123a'}


def get(session, path, **kwargs):
    for attempt in range(2):
        try:
            response = session.get(SITE + path, timeout=(10, 35), **kwargs)
            if response.status_code not in {429, 502, 503, 504} or attempt:
                response.raise_for_status()
                return response
            pause = response.headers.get('Retry-After', '60')
        except (requests.Timeout, requests.ConnectionError):
            if attempt:
                raise
            pause = '60'
        time.sleep(max(60, min(120, int(pause) if pause.isdigit() else 60)))


def release(session):
    front = re.search(r'data-release-sha="([a-f0-9]{40})"', get(session, '/about').text)
    return [front[1] if front else None, get(session, '/api/health').json()['release_sha']]


def in_main(base, head):
    return subprocess.check_output(['gh', 'api', f'repos/{REPO}/compare/{base}...{head}', '--jq', '.status'],
                                   text=True).strip() in {'identical', 'ahead'}


def check(session, expected):
    pid = expected['id']
    data = get(session, f'/api/opportunities/{pid}', params={'_release_scope': SCOPE}).json()
    facts = data['detail_fields']['fields']['professor_or_lab']; explicit = facts['explicit']; quotes = facts['quotes']
    assert data['id'] == pid and data['pi_name'] == expected['pi_name'] and data['url'] == expected['profile_url']
    assert data['target_truth']['actionable'] is True
    assert explicit['faculty_directory_section'] == expected['group'] and quotes['faculty_directory_section']['source_url'] == ROSTER
    assert explicit.get('faculty_rank') == expected['role']
    if expected['role']:
        assert quotes['faculty_rank']['source_url'] == expected['profile_url']
        assert quotes['faculty_rank']['text'] == expected['role']
    else:
        assert 'faculty_rank' in facts['unknown'] and 'faculty_rank' not in quotes
    result = {'id': pid, 'name': data['pi_name'], 'current': True, 'profile_url': data['url'], 'group': expected['group'],
              'group_quote': quotes['faculty_directory_section'], 'stated_role': expected['role'], 'role_quote': quotes.get('faculty_rank')}
    if pid in CONTROLS:
        page = BeautifulSoup(get(session, f'/opportunities/{pid}').content, 'html.parser')
        assert page.h1 and page.h1.get_text(' ', strip=True) == data['pi_name']
        text = page.get_text(' ', strip=True)
        assert 'Department directory section' in text and expected['group'] in text
        assert not expected['role'] or expected['role'] in text
        result['public_detail_heading'] = data['pi_name']
        result['public_detail_group_and_role'] = True
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--sha', required=True); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); assert re.fullmatch('[0-9a-f]{40}', args.sha)
    assert in_main(SOURCE, args.sha) and in_main(args.sha, 'main')
    originals = json.loads(Path(__file__).with_name('53-candidate-public-route-details.json').read_text())['rows']
    assert len({r['id'] for r in originals}) == len(originals) == 53
    session = requests.Session(); receipt = {'source': SOURCE, 'started_at': datetime.now(timezone.utc).isoformat(), 'start': release(session), 'results': [], 'failed': []}
    assert receipt['start'] == [args.sha] * 2
    try:
        for row in originals:
            try:
                receipt['results'].append(check(session, row))
            except (AssertionError, requests.RequestException, KeyError, ValueError) as error:
                receipt['failed'].append({'id': row['id'], 'error': type(error).__name__, 'detail': str(error)[:240]})
            args.out.write_text(json.dumps(receipt, indent=2) + '\n'); time.sleep(4)
    finally:
        receipt['end'] = release(session); args.out.write_text(json.dumps(receipt, indent=2) + '\n')
    assert receipt['start'] == receipt['end'] and len(receipt['results']) == 53 and not receipt['failed']


if __name__ == '__main__':
    main()
