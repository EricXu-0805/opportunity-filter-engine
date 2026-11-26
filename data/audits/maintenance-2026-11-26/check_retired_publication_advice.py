"""Read public, historical and current faculty publication sections in two languages."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

SITE = 'https://joinalab.com'
SCOPE = 'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
PEOPLE = (
    ('faculty-ncsu-chass-089a76c8', 'Jeffery Braden', 'inactive'),
    ('faculty-ncsu-chass-9dbafbfb', 'Kirsti Cole', 'professor'),
    ('faculty-ncsu-chass-fe45bd2c', 'Jennifer Despain', 'lecturer'),
)
TEXT = {
    'en': {
        'section': 'Recent publications',
        'source_note': 'These links search Google Scholar by title. They are not stored paper sources or evidence that you have read them.',
        'professor': 'From this professor’s public publication record — skim one before you reach out.',
        'lecturer': 'From their public publication record — skim one before you reach out.',
    },
    'zh': {
        'section': '近期论文',
        'source_note': '这些链接按标题搜索 Google Scholar，并非已保存的论文来源，也不代表你已阅读。',
        'professor': '来自这位教授的公开发表记录 —— 联系前先翻一篇,套磁信会具体得多。',
        'lecturer': '来自其公开发表记录 —— 联系前先翻一篇,套磁信会具体得多。',
    },
}


def read_json(path):
    with urlopen(SITE + path, timeout=40) as response:
        return json.load(response)


def verify_page(page, language, sha, name, kind, titles, expectation):
    text = TEXT[language]
    page.get_by_role('heading', name=name, exact=True, level=1).wait_for(timeout=45000)
    assert page.locator('html').get_attribute('data-release-sha') == sha
    section = page.locator('section').filter(has=page.get_by_role('heading', name=text['section'], exact=True))
    section.get_by_text(text['source_note'], exact=True).wait_for(timeout=35000)
    links = dict(section.get_by_role('link').evaluate_all('(anchors) => anchors.map(a => [a.innerText, a.href])'))
    assert set(links) == set(titles) and len(links) == len(titles) == 3
    for title, href in links.items():
        url = urlsplit(href)
        assert url.hostname == 'scholar.google.com' and parse_qs(url.query).get('q') == ['"' + title + '"']
    displayed = {key: section.get_by_text(text[key], exact=True).is_visible() for key in ('professor', 'lecturer')}
    expected = 'professor' if kind == 'inactive' and expectation == 'before' else kind
    assert displayed == {key: key == expected for key in displayed}, (kind, language, displayed, expected)
    return {'language': language, 'person': name, 'heading': text['section'], 'visible_scholar_titles': links,
            'source_disclaimer_visible': True, 'visible_outreach_advice': displayed, 'sha': sha, 'passed': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sha')
    parser.add_argument('expectation', choices=['before', 'fixed'])
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    start = read_json('/api/health')['release_sha']
    assert start == args.sha
    rows = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(locale='en-US')
        page = context.new_page()
        account_http = []
        def observe(response):
            path = urlsplit(response.url).path
            if path in ('/auth/v1/signup', '/rest/v1/rpc/commit_profile_patch_cas'):
                account_http.append({'path': path, 'status': response.status})
        page.on('response', observe)
        for oid, name, kind in PEOPLE:
            normal = read_json('/api/opportunities/' + oid + '?' + urlencode({'_release_scope': SCOPE}))
            metadata = normal['metadata']
            assert normal['pi_name'] == name and normal['target_truth']['actionable'] is (kind != 'inactive')
            assert metadata['publication_attribution_status'] == 'verified_author_id'
            titles = [work['title'] for work in metadata['recent_works']]
            record = {'id': oid, 'url': SITE + '/opportunities/' + oid, 'public_rank': metadata.get('faculty_title'),
                      'api_actionable': normal['target_truth']['actionable'], 'observations': []}
            try:
                response = page.goto(record['url'], wait_until='domcontentloaded', timeout=60000)
                assert response and response.status == 200
                page.get_by_role('heading', name=name, exact=True, level=1).wait_for(timeout=45000)
                if oid == PEOPLE[0][0]:
                    tour = page.get_by_test_id('onboarding-intro')
                    tour.wait_for(timeout=30000)
                    tour.get_by_test_id('onboarding-skip').click()
                    tour.get_by_test_id('onboarding-school-ncsu').click()
                    for wait_ms in (2500, 5000, 10000, 15000):
                        tour.get_by_test_id('onboarding-primary').click()
                        try:
                            tour.wait_for(state='hidden', timeout=wait_ms)
                            break
                        except Exception:
                            if not tour.get_by_test_id('onboarding-error').is_visible():
                                tour.wait_for(state='hidden', timeout=20000)
                                break
                            page.wait_for_timeout(wait_ms)
                    assert not tour.is_visible(), account_http
                if page.locator('html').get_attribute('lang') == 'zh':
                    page.get_by_role('button', name='Switch to English', exact=True).click()
                record['observations'].append(verify_page(page, 'en', args.sha, name, kind, titles, args.expectation))
                page.get_by_role('button', name='切换到中文', exact=True).click()
                record['observations'].append(verify_page(page, 'zh', args.sha, name, kind, titles, args.expectation))
            except Exception as exc:
                record['error'] = f'{type(exc).__name__}: {exc}'[:800]
            finally:
                rows.append(record)
        context.close()
        browser.close()
    end = read_json('/api/health')['release_sha']
    receipt = {'expected_head': args.sha, 'backend_start': start, 'backend_end': end, 'site': SITE,
               'checked_at': datetime.now(timezone.utc).isoformat(), 'expected_behavior': args.expectation,
               'guest_http': account_http, 'guest_setup': 'One dedicated QA visitor completed the normal NC State school-selection tour and changed the on-screen language. No emails or applications.', 'rows': rows}
    args.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
    print([(r['id'],len(r['observations']),r.get('error','')) for r in rows],flush=True)
    assert start == end and all(len(r['observations']) == 2 and 'error' not in r for r in rows)


if __name__ == '__main__':
    main()
