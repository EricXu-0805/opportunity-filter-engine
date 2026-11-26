"""Read two saved searches on a second, separately authenticated browser using a disposable local database."""
import json
import secrets
import sys
import uuid
from pathlib import Path
from urllib import request
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import expect, sync_playwright


database = 'http://127.0.0.1:54321'
web = 'http://127.0.0.1:3100'
config = json.loads(Path(sys.argv[1]).read_text())
assert config['API_URL'] == database
corrected = sys.argv[2] == 'after'


def database_request(path, body, session=None):
    headers = {'apikey': config['ANON_KEY'], 'content-type': 'application/json'}
    if session:
        headers['authorization'] = 'Bearer ' + session['access_token']
    req = request.Request(database + path, headers=headers, data=json.dumps(body).encode())
    with request.urlopen(req, timeout=25) as response:
        return json.load(response)


def browser_device(browser, session):
    ctx = browser.new_context(locale='en-US', service_workers='block', viewport={'width': 1280, 'height': 960})
    values = {'ofe_auth': json.dumps(session), 'ofe_lang': 'en', 'ofe_onboarding_seen': '1',
              'ofe_semantic_rerank_opt_in_v1': '0',
              'ofe_school_confirmed': json.dumps({'slug': 'uiuc', 'ts': '2026-11-26T00:00:00Z'})}
    ctx.add_init_script("if (location.origin === 'http://127.0.0.1:3100' && !localStorage.getItem('qa-init')) {"
                        "for (const [k,v] of Object.entries(" + json.dumps(values) + ")) localStorage.setItem(k,v);"
                        "localStorage.setItem('qa-init','1')}")
    page = ctx.new_page()
    page.set_default_timeout(60000)
    page.goto(web, wait_until='domcontentloaded')
    expect(page.locator('#student_name')).to_have_value('Saved Search QA', timeout=90000)
    return ctx, page


def actual_view(params):
    def request_matches(response):
        if urlsplit(response.url).path != '/api/matches/view' or response.request.method != 'POST':
            return False
        view = response.request.post_data_json['view']
        return all(view.get(k) == v for k,v in params.items())
    return request_matches


def ids_and_total(response, page):
    assert response.ok
    data = response.json()
    total = data['filtered_total']
    view_id = data['view_id']
    ids = []
    while True:
        items = [item['opportunity_id'] for item in data['results']]
        assert len(items) == len(set(items)) and not set(ids).intersection(items)
        if items:
            expect(page.locator('#match-card-' + items[0])).to_be_visible(timeout=90000)
        ids.extend(items)
        if not data['has_more']:
            break
        cursor = data['next_cursor']
        assert cursor and items and len(ids) < total
        with page.expect_response(lambda r: urlsplit(r.url).path == '/api/matches/view'
                                  and (r.request.post_data_json or {}).get('cursor') == cursor,
                                  timeout=90000) as following:
            page.get_by_role('button', name='Next', exact=True).click()
        assert following.value.ok
        data = following.value.json()
        assert data['view_id'] == view_id and data['filtered_total'] == total
    assert len(ids) == total
    return ids, total



creds = {'email': str(uuid.uuid4()) + '@example.test', 'password': secrets.token_urlsafe(24) + '!1'}
first = database_request('/auth/v1/signup', creds)
assert not first['user']['is_anonymous']
owner = first['user']['id']
profile = {'name': 'Saved Search QA', 'home_school':'uiuc', 'search_weight':50,
           'college':'Grainger College of Engineering', 'major':'Computer Science', 'institution':'uiuc',
           'grade':'Sophomore','research_interests':'machine learning, artificial intelligence and robotics',
           'skills': [], 'resume_text':'', 'coursework':[], 'seeking_types':['research'], 'is_international':False}
profile_commit = database_request('/rest/v1/rpc/commit_profile_patch_cas', {
    'p_expected_device_id': owner, 'p_expected_revision': 0, 'p_patch': profile}, first)
assert profile_commit['status'] == 'applied'
searches = [
    ('Computing methods', {'tab':'all','type':'research','topic':'machine learning'},
     {'tab':'all','opportunity_type':'research','research_topic':'machine learning'}),
    ('Off campus and no listed deadline', {'tab':'all','dl':'rolling','paid':'no','intl':'no','scope':'open','loc':'no'},
     {'tab':'all','deadline':'rolling','paid':'no','intl':'no','scope':'open','on_campus':'no'}),
]
baselines = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--disable-dev-shm-usage'])
    first_device, page = browser_device(browser, first)
    for name, params, view in searches:
        with page.expect_response(actual_view(view),timeout=90000) as result:
            page.goto(web + '/results?' + urlencode(params), wait_until='domcontentloaded')
        baselines[name] = ids_and_total(result.value, page)
        if name == 'Computing methods':
            assert baselines[name][1] > 0
        page.get_by_role('button',name='Save to account',exact=True).click()
        dialog = page.get_by_role('dialog')
        dialog.get_by_label('Name',exact=True).fill(name)
        check = dialog.get_by_role('checkbox')
        if check.count():
            assert not check.is_checked()
        with page.expect_response(lambda r: urlsplit(r.url).path == '/rest/v1/saved_searches' and r.request.method == 'POST') as write:
            dialog.get_by_role('button',name='Save search',exact=True).click()
        assert write.value.ok,write.value.status
        saved = write.value.json()
        assert saved['name'] == name and write.value.request.post_data_json['device_id'] == owner
        print('saved', name, write.value.status, saved['filters_json'], 'total',baselines[name][1])
    first_device.close()

    second = database_request('/auth/v1/token?grant_type=password', creds)
    assert second['user']['id'] == owner and not second['user']['is_anonymous']
    assert first['refresh_token'] != second['refresh_token']
    second_device, page = browser_device(browser, second)
    for name, params, view in searches:
        with page.expect_response(lambda r: urlsplit(r.url).path == '/rest/v1/saved_searches' and r.request.method == 'GET') as restored:
            page.goto(web + '/favorites', wait_until='domcontentloaded')
        assert restored.value.ok
        link = page.get_by_role('link',name='Apply saved search "' + name + '"',exact=True)
        expect(link).to_be_visible()
        text = link.inner_text()
        href = parse_qs(urlsplit(link.get_attribute('href')).query)
        assert all(href.get(k) == [v] for k,v in params.items()), href
        if name.startswith('Off campus'):
            labels = ('Unpaid / not disclosed', 'Show all (incl. US-only)', 'Off campus / Remote',
                      'Open to all (incl. unconfirmed)', 'No deadline listed')
            if corrected:
                assert all(label in text for label in labels) and '≤rollingd' not in text, text
            else:
                assert '≤rollingd' in text and not any(label in text for label in labels), text
        with page.expect_response(actual_view(view),timeout=90000) as rerun:
            link.click()
        received = ids_and_total(rerun.value, page)
        assert received == baselines[name], (received[1],baselines[name][1])
        print('second device read',name, restored.value.status, 'summary:',text.replace('\n',' '),
              'same results and original IDs:',len(received[0]),'of', received[1])
    second_device.close()
    browser.close()
