"""Follow faculty-page buttons through three genuine student paths on one release."""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

SITE = 'https://joinalab.com'
SCOPE = 'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'
CASES = (('faculty-msu-bmb-939e5db8', 'Ogunwobi'), ('faculty-ucb-cdss-0ac5b942', 'Michael Boots'))
CAMPUS = os.environ.get('LINK_PATH_CAMPUS','msu')
if CAMPUS == 'ucb':
    CASES = (('faculty-ucb-cdss-0ac5b942', 'Boots'),)
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
receipt = {'utc': datetime.now(timezone.utc).isoformat(), 'site': SITE, 'campus': CAMPUS, 'account': {}, 'records': [], 'matches_requests': []}


def version():
    with urlopen(SITE + '/api/health', timeout=45) as response:
        back = json.load(response)['release_sha']
    with urlopen(SITE + '/about', timeout=45) as response:
        front = re.search(r'data-release-sha="(\w{40})"', response.read().decode())[1]
    return dict(front=front, back=back)


def save():
    (OUT/'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


def classify(href, person, roster):
    if href.rstrip('/').casefold() == person.rstrip('/').casefold():
        return 'stored person URL'
    if href.rstrip('/').casefold() == roster.rstrip('/').casefold():
        return 'stored source URL'
    return 'other URL'


def field(page, key, free_text, preferences):
    control = page.locator('#' + key)
    if control.evaluate('e => e.tagName') != 'SELECT':
        control.fill(free_text)
        return free_text
    control.locator("option:not([value='']):not([disabled])").first.wait_for(state='attached', timeout=30000)
    options = control.locator("option:not([value='']):not([disabled])").evaluate_all(
        'items => items.map(x => ({v:x.value, label:x.textContent.trim()}))')
    choice = next((x for term in preferences for x in options if term in x['label'].casefold()), options[0])
    control.select_option(choice['v'])
    return choice['label']


def onboarding(page):
    account = receipt['account']
    page.goto(SITE, wait_until='domcontentloaded')
    tour = page.get_by_test_id('onboarding-intro')
    tour.get_by_test_id('onboarding-skip').click(timeout=45000)
    tour.get_by_test_id('onboarding-school-' + CAMPUS).click()
    assert tour.get_by_test_id('onboarding-school-' + CAMPUS).get_attribute('aria-pressed') == 'true'
    account['onboarding_attempts'] = []
    for _ in range(3):
        tour.get_by_test_id('onboarding-primary').click()
        try:
            tour.wait_for(state='hidden', timeout=10000)
            account['onboarding_attempts'].append('closed')
            break
        except Exception:
            error = tour.get_by_test_id('onboarding-error')
            account['onboarding_attempts'].append(error.inner_text() if error.is_visible() else 'school confirmation still open')
            page.screenshot(path=OUT/'campus-confirmation-retry.png')
            save()
            page.wait_for_timeout(3500)
    tour.wait_for(state='hidden', timeout=20000)
    page.locator('#student_name').wait_for()
    page.get_by_test_id('hydration-note').wait_for(state='hidden',timeout=45000)
    page.get_by_test_id('profile-refresh-status').wait_for(state='hidden',timeout=45000)
    page.locator('#student_name').fill('Faculty link QA')
    if CAMPUS == 'ucb':
        account['college'] = field(page,'college','College of Computing, Data Science, and Society',['computing, data science','data science'])
        account['major'] = field(page,'major','Data Science',['data science'])
    else:
        account['college'] = field(page, 'college', 'College of Natural Science', ['natural science','biological','science'])
        account['major'] = field(page, 'major', 'Biochemistry and Molecular Biology', ['biochemistry','molecular biology','biology','biological'])
    page.locator('#grade').select_option(label='Junior')
    page.locator('#research_interests').fill('biochemistry, cancer biology, evolutionary biology')
    page.locator('#grade').focus()
    for _ in range(120):
        if account.get('signup') == 200 and account.get('profile_commit') == 'applied':
            break
        page.wait_for_timeout(250)
    assert account.get('signup') == 200 and account.get('profile_commit') == 'applied', account
    save()


def click_external(page, link, item, route):
    link.wait_for(timeout=20000)
    href = link.get_attribute('href')
    assert urlsplit(href).hostname in ('directory.natsci.msu.edu', 'ccb.berkeley.edu'), href
    record = {'label':link.inner_text(), 'href':href, 'target':link.get_attribute('target'),
              'route':re.sub(r'([?&])returnSession=[^&]+', '', page.url), 'client_release':page.locator('html').get_attribute('data-release-sha'),
              'points_to':classify(href, item['person_url'], item['official_roster'])}
    item[route] = record
    link.scroll_into_view_if_needed()
    page.screenshot(path=OUT/(item['id'] + '-' + route + '.png'))
    save()
    statuses = []
    def observe(response):
        if response.request.is_navigation_request() and urlsplit(response.url).hostname in ('directory.natsci.msu.edu', 'ccb.berkeley.edu'):
            statuses.append({'url':response.url.split('?',1)[0], 'status':response.status})
    page.context.on('response', observe)
    try:
        with page.context.expect_page(timeout=35000) as opened:
            link.click(timeout=25000)
        external = opened.value
        try:
            external.wait_for_load_state('domcontentloaded', timeout=35000)
            external.locator('body').wait_for(timeout=10000)
            record.update(landed_url=external.url, title=external.title(),
                          headings=[x.strip()[:160] for x in external.locator('h1,h2').all_inner_texts()[:8]],
                          linked_people=external.locator("a[href*='/Profiles/Person/'],a[href*='/people/']").count())
        finally:
            record.setdefault('landed_url', external.url)
            external.close()
    except Exception as exc:
        record['navigation_error'] = str(exc)[:400]
    finally:
        record['navigation_responses'] = statuses
        page.context.remove_listener('response', observe)
        save()


def run():
    receipt['start'] = version()
    assert receipt['start']['front'] == receipt['start']['back']
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(locale='en-US')
        page = context.new_page()
        page.set_default_navigation_timeout(65000)
        def observe(response):
            path = urlsplit(response.url).path
            if path == '/auth/v1/signup':
                receipt['account']['signup'] = response.status
            if path.startswith('/rest/v1/') and ('profile' in path or 'favorite' in path):
                short = path.split('/')[-1]
                if short in ('user_profiles', 'commit_profile_patch_cas', 'user_favorites'):
                    receipt['account'].setdefault('responses', []).append({'endpoint':short,'status':response.status,'method':response.request.method})
            if path.endswith('/rpc/commit_profile_patch_cas') and response.ok:
                try:
                    result = response.json()
                    if isinstance(result, list):
                        result = result[0] if result else {}
                    if result.get('status') == 'applied':
                        receipt['account']['profile_commit'] = 'applied'
                except Exception:
                    pass
            if path.endswith('/matches/view'):
                request = response.request.post_data_json or {}
                receipt['matches_requests'].append({'http':response.status,'query':(request.get('view') or {}).get('search_query'),
                    'tab':(request.get('view') or {}).get('tab'), 'major':(request.get('profile') or {}).get('major')})
        context.on('response', observe)
        onboarding(page)
        for pid, query in CASES:
            item = {'id':pid, 'query':query}
            receipt['records'].append(item)
            with urlopen(SITE + '/api/opportunities/' + pid + '?' + urlencode({'_release_scope':SCOPE}), timeout=50) as resp:
                payload = json.load(resp)
            item.update(name=payload['pi_name'], person_url=payload['url'], official_roster=payload['source_url'])
            try:
                page.goto(SITE + '/opportunities/' + pid, wait_until='domcontentloaded')
                main = page.get_by_role('main')
                main.get_by_role('link', name='Back to matches', exact=True).wait_for(timeout=65000)
                item['h1'] = main.get_by_role('heading', level=1).inner_text()
                main.get_by_role('button',name='Add to favorites',exact=True).click(timeout=25000)
                main.get_by_role('button',name='Remove from favorites',exact=True).wait_for(timeout=25000)
                item['added_normally'] = True
                click_external(page, main.get_by_role('link',name='View faculty profile',exact=True),item,'detail')
            except Exception as exc:
                item['detail_error'] = str(exc)[:900]
            save()
        page.goto(SITE + '/favorites',wait_until='domcontentloaded')
        for item in receipt['records']:
            try:
                name = page.locator("h3 a[href='/opportunities/" + item['id'] + "']")
                name.wait_for(timeout=35000)
                card = name.locator('xpath=ancestor::div[contains(@class,"rounded-2xl")][1]')
                click_external(page,card.get_by_role('link',name='Faculty page',exact=True),item,'favorites')
            except Exception as exc:
                item['favorites_error'] = str(exc)[:900]
            save()
        for item in receipt['records']:
            for tab in ('all','starred'):
                try:
                    searchurl = SITE + '/results?' + urlencode({'tab':tab,'ai':'0','q':item['query']})
                    page.goto(searchurl,wait_until='domcontentloaded')
                    search = page.locator('#results-search-input')
                    search.wait_for(timeout=45000)
                    if search.input_value() != item['query']:
                        search.fill(item['query'])
                    if CAMPUS != 'ucb' and item['id'].startswith('faculty-ucb-') and tab == 'all':
                        cross = page.get_by_role('button', name="Include other schools' opportunities", exact=True)
                        if cross.is_visible() and cross.get_attribute('aria-pressed') == 'false':
                            cross.click(timeout=35000)
                            item['used_product_cross_school'] = cross.get_attribute('aria-pressed')
                    card = page.locator('#match-card-' + item['id'])
                    card.wait_for(timeout=55000)
                    item.setdefault('visible_matching_cards', {})[tab] = {
                        'card':card.get_attribute('id'),
                        'links':[{'label':a.inner_text().strip(), 'href':a.get_attribute('href')} for a in card.locator('a:visible').all()]
                    }
                    page.screenshot(path=OUT/(item['id'] + '-visible-matches-' + tab + '.png'))
                    click_external(page,card.get_by_role('link',name='Faculty page',exact=True),item,'matches_' + tab)
                    break
                except Exception as exc:
                    item['matches_' + tab + '_error'] = str(exc)[:650]
                    item['match_header_' + tab] = page.get_by_role('main').inner_text(timeout=5000)[:500]
                finally:
                    save()
        browser.close()
    receipt['end'] = version()
    receipt['stable_release'] = receipt['start'] == receipt['end'] and all(
        rec['client_release']==receipt['start']['front'] for row in receipt['records']
        for rec in [row.get(k) for k in ('detail','favorites','matches_all','matches_starred')] if rec)
    save()
    assert receipt['stable_release'] and all(row.get('favorites') and row.get('detail') for row in receipt['records'])
    assert receipt['records'][0].get('matches_all') or receipt['records'][0].get('matches_starred')


if __name__ == '__main__':
    try:
        run()
    finally:
        save()
