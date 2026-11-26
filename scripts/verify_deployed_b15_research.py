"""Check all reviewed research fields through the released API and four public detail pages."""
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright
from verify_deployed_b15_keyboard import SITE, check_deployment

SCOPE = 'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
HEADERS = {'Accept': 'application/json', 'User-Agent': 'JoinALab first-party release verification'}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def read_public(row, retries):
    url = f"{SITE}/api/opportunities/{row['id']}?_release_scope={SCOPE}"
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=20) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as error:
            code = getattr(error, 'code', None)
            if code is not None and code not in (408, 429, 500, 502, 503, 504):
                raise
            retries.append({'id': row['id'], 'attempt': attempt + 1, 'status': code or type(error).__name__})
            if attempt == 3:
                raise
            retry_after = getattr(error, 'headers', {}).get('Retry-After', '') if code is not None else ''
            delay = max(2 ** (attempt + 1), float(retry_after) if retry_after.isdecimal() else (60 if code == 429 else 2))
            time.sleep(delay)


def main():
    release = os.environ['OFE_EXPECTED_SITE_SHA']
    expected = json.loads(Path('data/audits/release-probes/b15-research-286-expected.json').read_text())
    check_deployment(release)
    results = []
    retries = []
    for row in expected['rows']:
        doc = read_public(row, retries)
        raw = doc['metadata']['research_areas_raw']
        facet = doc['detail_fields']['fields']['research_content']['explicit']['research_areas']
        actual = digest(raw)
        assert doc['id'] == row['id'] and actual == row['research_sha256'] and digest(facet) == row['facet_sha256'], row['id']
        desc = digest(doc['description_clean']) if row['description_sha256'] is not None else None
        assert desc == row['description_sha256'], row['id']
        results.append({'id': row['id'], 'school': row['school'], 'research_sha256': actual, 'facet_sha256': digest(facet), 'description_sha256': desc})
        if len(results) % 50 == 0:
            print(f'{len(results)} original IDs passed', flush=True)
        time.sleep(0.65)
    output = Path(os.environ['RUNNER_TEMP']) / 'b15-286-official.json'
    receipt = {'time_utc': datetime.now(timezone.utc).isoformat(), 'release': release, 'site': SITE, 'source_pr': 1417,
               'scope': 'Anonymous first-party production API; four public Chromium detail pages. No accounts or writes.',
               'counts_by_school': dict(Counter(r['school'] for r in results)), 'rows': results,
               'retry_events': retries, 'visible_details': [], 'workflow_run': os.environ['GITHUB_RUN_ID']}
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
    pages = receipt['visible_details']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/google-chrome')
        page = browser.new_page(locale='en-US')
        for entry in expected['browser_checks']:
            url = f"{SITE}/opportunities/{entry['id']}"
            response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
            assert response and response.status == 200, entry['id']
            expect(page.locator('main')).to_contain_text(entry['fragment'], timeout=30000)
            pages.append({'id': entry['id'], 'status': response.status, 'page': url, 'visible_fragment': entry['fragment'], 'faculty_source': entry['school_source']})
        browser.close()
    check_deployment(release)
    assert len(results) == 286 and sum(r['description_sha256'] is not None for r in results) == 126
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
    print(f"286 research fields, 126 descriptions, {len(pages)} visible details, {len(retries)} retry events", flush=True)


if __name__ == '__main__':
    main()
