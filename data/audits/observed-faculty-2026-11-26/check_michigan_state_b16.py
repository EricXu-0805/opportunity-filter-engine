"""Read the audited MSU faculty on the first production release containing B16."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

from bs4 import BeautifulSoup
import requests

b16 = '65d14e6968a093c66b2273d971ffb749d796c82a'
site = 'https://joinalab.com'
scope = 'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
duplicate_math = 'faculty-msu-math-7d462896'


def fixed_cohorts():
    data = Path(__file__).with_name('michigan-state-b16-public-cohorts.json')
    fixed = json.loads(data.read_text())
    assert fixed['source'] == b16
    return fixed['cohorts']


def release_rows(repo, revision):
    blob = subprocess.check_output(['git', '-C', str(repo), 'show', revision + ':data/processed/shards/msu.json'])
    return {row['id']: row for row in json.loads(blob)}


def http(path, params=None):
    for attempt in range(2):
        response = requests.get(site + path, params=params, timeout=(8, 35))
        if attempt or response.status_code != 429:
            return response
        try:
            delay = int(response.headers.get('Retry-After', 60))
        except ValueError:
            delay = 60
        time.sleep(min(max(delay, 1), 60))
    raise AssertionError('unreachable')


def versions():
    front, back = http('/about'), http('/api/health')
    front.raise_for_status()
    back.raise_for_status()
    return {
        'frontend': re.search('data-release-sha=["\']([0-9a-f]{40})', front.text).group(1),
        'backend': back.json()['release_sha'],
    }


def check(key, rows):
    detail_path = '/opportunities/' + key
    api_path = '/api/opportunities/' + key
    response = http(api_path, {'_release_scope': scope})
    result = {'id': key, 'api': site + api_path, 'detail': site + detail_path, 'api_http': response.status_code}
    if key == duplicate_math:
        result['passed'] = response.status_code == 404 and key not in rows
        return result
    if not response.ok:
        result['passed'] = False
        return result
    record = rows[key]
    body = response.json()
    rank = body.get('metadata', {}).get('faculty_title')
    expected_route = record['url']
    is_directory = '/directory/directory/department/' in expected_route.lower()
    expected_label = 'View source' if is_directory else 'View faculty profile'
    page = http(detail_path)
    dom = BeautifulSoup(page.content, 'html.parser')
    title = dom.find('h1')
    links = [
        {'label': element.get_text(' ', strip=True), 'href': element.get('href')}
        for element in dom.select('a[href]')
        if element.get_text(' ', strip=True) in ('View faculty profile', 'View source')
    ]
    expected_active = record['metadata'].get('is_active') is not False
    facts = {
        'same_id': body.get('id') == key,
        'same_person': body.get('pi_name') == record['pi_name'],
        'same_homepage': body.get('url') == expected_route,
        'same_roster': body.get('source_url') == record['source_url'],
        'same_rank': rank == record['metadata'].get('faculty_title'),
        'right_actionability': body.get('target_truth', {}).get('actionable') == expected_active,
        'same_heading': title is not None and title.get_text(' ', strip=True) == record['pi_name'],
        'same_control': any(link == {'label': expected_label, 'href': expected_route} for link in links),
        'no_false_homepage': not is_directory or all(link['label'] != 'View faculty profile' for link in links),
    }
    result.update(name=body.get('pi_name'), rank=rank, homepage=body.get('url'), roster=body.get('source_url'),
                  actionable=body.get('target_truth', {}).get('actionable'), html_http=page.status_code,
                  heading=title.get_text(' ', strip=True) if title else None, controls=links, checks=facts,
                  passed=page.ok and all(facts.values()))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('release')
    parser.add_argument('--repo', type=Path, default=Path.cwd(), help='Checkout containing the deployed commit and B16')
    parser.add_argument('--output', type=Path, help='Write the real public receipt here')
    parser.add_argument('--verify-inputs-only', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.release):
        parser.error('a full release commit is required')
    subprocess.run(['git', '-C', str(args.repo), 'merge-base', '--is-ancestor', b16, args.release], check=True)
    cohorts = fixed_cohorts()
    ids = sorted({key for group in cohorts.values() for key in group})
    rows = release_rows(args.repo, args.release)
    assert len(ids) == 43 and duplicate_math not in rows and all(key in rows for key in ids if key != duplicate_math)
    if args.verify_inputs_only:
        print('43 fixed original IDs, 42 existing records, one absent duplicate; no site request made')
        return
    if args.output is None:
        parser.error('--output is required for a real public read')
    result = {'release': args.release, 'cohorts': cohorts, 'started_at': datetime.now(timezone.utc).isoformat(),
              'initial': versions()}
    assert set(result['initial'].values()) == {args.release}, result['initial']
    output = args.output
    with ThreadPoolExecutor(max_workers=2) as pool:
        result['rows'] = list(pool.map(lambda key: check(key, rows), ids))
    result.update(final=versions(), finished_at=datetime.now(timezone.utc).isoformat())
    output.write_text(json.dumps(result, indent=2) + '\n')
    failed = [row['id'] for row in result['rows'] if not row['passed']]
    print('43 original IDs checked; failed:', failed, 'final versions:', result['final'], 'receipt:', output)
    assert result['final'] == result['initial'] and not failed


if __name__ == '__main__':
    main()
