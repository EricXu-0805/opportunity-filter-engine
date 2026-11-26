"""Read the Caltech LIGO bookmark and each public application portal, without submitting a form."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from playwright.sync_api import sync_playwright

release = 'daa5a43eb3b91974869c59dfb9a3c342b9082c6b'
site = 'https://joinalab.com'
original = 'caltech-acdbfe29c21d'
product = f'{site}/opportunities/{original}'
host = 'https://ligosurf.caltech.edu/apply'
usa = 'https://etap.nsf.gov/award/8325/opportunity/12125'
india = 'https://www.gw.iucaa.in/ligo-surf-program/'
root = Path('evidence')
root.mkdir(exist_ok=True)
record = {'expected_release': release, 'original_id': original, 'started_at': datetime.now(timezone.utc).isoformat(), 'pages': {}, 'checks': {}}


def nav(page, name, url):
    response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
    record['pages'][name] = {'requested': url, 'final': page.url, 'http': response.status}
    assert response.ok, (name, response.status)


def visible_links(page, url):
    return page.locator('a').evaluate_all('''(anchors, url) => anchors.filter(a => a.getClientRects().length > 0 && a.href === url).map(a => ({href:a.href,text:(a.textContent || '').trim()}))''', url)


def save(page, name):
    body = ' '.join(page.locator('body').inner_text().replace('\xa0',' ').split())
    record['pages'][name]['title'] = page.title()
    record['pages'][name]['date_excerpts'] = [m.group(0) for m in re.finditer(r'.{0,75}(?:January (?:5|10|15), 2027|(?:5th|10th) Jan 2027|01/15/2027).{0,65}', body, re.I)][:10]
    page.screenshot(path=str(root / f'{name}.png'))
    return body


try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome')
        context = browser.new_context(locale='en-US')
        page = context.new_page()
        def version():
            r = context.request.get(site+'/api/health', timeout=45000)
            assert r.ok
            return r.json()['release_sha']
        record['backend_at_start'] = version()
        nav(page, 'product', product)
        page.get_by_role('heading',name=re.compile('LIGO SURF')).first.wait_for(timeout=30000)
        record['frontend_release'] = page.locator('html').get_attribute('data-release-sha')
        body = save(page,'product')
        record['pages']['product']['heading'] = page.locator('h1').inner_text()
        record['pages']['product']['application_links'] = visible_links(page, host)
        record['checks']['product_visible_correct_host'] = bool(record['pages']['product']['application_links'])
        record['checks']['three_dates_visible_on_original'] = all(f'January {d}, 2027' in body for d in (5, 10, 15))
        record['checks']['eligibility_distinguishes_routes'] = 'institutions in India' in body and re.search('U.S. (?:citizen|national)',body,re.I) is not None
        api = context.request.get(f'{site}/api/opportunities/{original}', timeout=45000)
        assert api.ok
        data = api.json()
        record['api'] = {k:data.get(k) for k in ('id','source_url','deadline','is_rolling','eligibility','application')}
        record['api']['deadline_note'] = data.get('metadata',{}).get('deadline_note')
        record['checks']['api_source_and_routes'] = (data['id']==original and data['source_url']==host and data['application']['application_url']==host and data['deadline'] is None and data['is_rolling'] is False and data['eligibility']['international_friendly']=='unknown' and all(f'January {d}, 2027' in (record['api']['deadline_note'] or '') for d in (5,10,15)))
        nav(page, 'host', host)
        record['pages']['host']['application_links'] = visible_links(page,usa)+visible_links(page,india)
        save(page,'host')
        record['checks']['host_links_both_portals'] = {l['href'] for l in record['pages']['host']['application_links']} == {usa,india}
        nav(page,'US_ETAP',usa)
        page.get_by_text(re.compile('01/15/2027')).first.wait_for(timeout=25000)
        us_body=save(page,'US_ETAP')
        record['checks']['us_january_15_eligibility'] = '01/15/2027' in us_body and 'U.S. citizen, permanent resident or U.S. national' in us_body
        nav(page,'India',india)
        india_body=save(page,'India')
        record['checks']['india_january_5_and_reference_january_10'] = 'deadline for submission is 5th Jan 2027' in india_body and 'deadline for sending reference letters is 10th Jan 2027' in india_body
        record['backend_at_finish'] = version()
        record['checks']['same_product_release'] = record['backend_at_start'] == record['frontend_release'] == record['backend_at_finish'] == release
        browser.close()
except Exception as error:
    record['error'] = str(error)[:1000]
finally:
    record['finished_at'] = datetime.now(timezone.utc).isoformat()
    (root/'ligo.json').write_text(json.dumps(record, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(record['checks'],indent=2),flush=True)
assert 'error' not in record and len(record['checks'])==8 and all(record['checks'].values()), record.get('error') or record['checks']
